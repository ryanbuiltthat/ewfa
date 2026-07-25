"""Service entrypoint: fast inference loop + nightly batch + on-demand commands.

Fast loop (every `fast_loop_minutes`): build features -> predict -> publish over
MQTT -> append to dataset. Once per day at `nightly_retrain_hour`: run the batch
(dataset consolidation + recalibrate/retrain in Phase 4). Between and during the
loop's sleep it drains the command queue, so dashboard buttons (run inference,
retrain, promote, rollback) are honored within a few seconds. Command execution
happens on this single thread, so no two tasks ever overlap.

Pipeline/model state is published to `creek/status/*` so the HA dashboard can show
what the service is doing and surface the result of each command.
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime

from .commands import CommandProcessor, CommandQueue
from .config import DATA_DIR, Config
from .dataset import DatasetWriter
from .features import FeatureBuilder
from .ha import HAClient
from .model import Model
from .mqtt_client import MqttClient
from .registry import ModelRegistry

log = logging.getLogger("app")

_running = True


def _handle_sigterm(_signum, _frame):
    global _running
    log.info("SIGTERM received — shutting down cleanly.")
    _running = False


def _now_iso() -> str:
    # tz-aware local time so HA can consume last_inference_at / last_nightly_at /
    # ran_at as proper `device_class: timestamp` sensors.
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _publish_pipeline(mqtt: MqttClient, status: dict, state: str, task: str) -> None:
    status["state"] = state
    status["task"] = task
    mqtt.publish("status/pipeline", dict(status))


def _publish_registry(mqtt: MqttClient, registry: ModelRegistry) -> None:
    mqtt.publish("status/registry", registry.snapshot())


def _run_inference_once(
    features: FeatureBuilder, model: Model, dataset: DatasetWriter,
    mqtt: MqttClient, status: dict,
) -> str:
    row = features.build()
    pred = model.predict(row)
    mqtt.publish("flood_probability", {"value": pred.flood_probability, "method": pred.method})
    mqtt.publish("predicted_crest", {"value": pred.predicted_crest_ft})
    mqtt.publish("lag_estimate", {"value": pred.lag_estimate_min})
    dataset.append_row(row)
    status["last_inference_at"] = _now_iso()
    return f"p={pred.flood_probability} method={pred.method}"


def _nightly_batch(
    cfg: Config, dataset: DatasetWriter, mqtt: MqttClient, model: Model,
    registry: ModelRegistry, status: dict,
) -> str:
    rows = dataset.row_count()
    events = model.event_count()
    log.info("Nightly batch: dataset=%d rows, events=%d", rows, events)
    # Phase 4: append day's data, recalibrate/retrain, version artifact via
    # registry.set_candidate(version, metrics), log skill metrics.
    method = "ml" if events >= cfg.min_events_for_ml else "threshold"
    ran_at = _now_iso()
    status["last_nightly_at"] = ran_at
    mqtt.publish(
        "model_health",
        {
            "dataset_rows": rows,
            "event_count": events,
            "min_events_for_ml": cfg.min_events_for_ml,
            "active_method": method,
            "ran_at": ran_at,
        },
    )
    _publish_registry(mqtt, registry)
    return f"rows={rows} events={events} method={method}"


def _process_commands(
    processor: CommandProcessor, cmd_queue: CommandQueue, mqtt: MqttClient, status: dict,
) -> None:
    for command in cmd_queue.drain():
        _publish_pipeline(mqtt, status, "running", command)
        result = processor.handle(command)
        mqtt.publish("status/command_result", result.as_dict(), retain=False)
        if not result.ok:
            status["last_error"] = f"{command}: {result.message}"
        log.info("Command %s -> ok=%s %s", command, result.ok, result.message)
        _publish_pipeline(mqtt, status, "idle", "none")


def main() -> int:
    cfg = Config.load()
    logging.basicConfig(
        level=cfg.py_log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    signal.signal(signal.SIGTERM, _handle_sigterm)

    data_dir = DATA_DIR
    log.info("Ackerly Creek modeling service starting (loop=%dm)", cfg.fast_loop_minutes)

    ha = HAClient(cfg.ha_api_url, cfg.supervisor_token)
    if not ha.ping():
        log.error("Cannot reach HA Core via Supervisor proxy — check homeassistant_api + token.")
        return 1

    registry = ModelRegistry(data_dir)
    cmd_queue = CommandQueue()
    mqtt = MqttClient(cfg.mqtt_host, cfg.mqtt_port, cfg.mqtt_user, cfg.mqtt_pass, cfg.mqtt_base_topic)
    mqtt.subscribe_commands(cmd_queue)   # subscription happens on connect
    mqtt.connect()

    features = FeatureBuilder(cfg, ha)
    model = Model(cfg, registry)
    dataset = DatasetWriter(data_dir)

    status = {
        "state": "idle",
        "task": "none",
        "last_inference_at": None,
        "last_nightly_at": None,
        "last_error": None,
    }

    processor = CommandProcessor(
        {
            "run_inference": lambda: _run_inference_once(features, model, dataset, mqtt, status),
            "retrain": lambda: _nightly_batch(cfg, dataset, mqtt, model, registry, status),
            "promote": lambda: _promote(mqtt, registry),
            "rollback": lambda: _rollback(mqtt, registry),
        }
    )

    # Prime the dashboard sensors immediately.
    _publish_pipeline(mqtt, status, "idle", "none")
    _publish_registry(mqtt, registry)

    last_nightly_day: int | None = None
    interval = max(1, cfg.fast_loop_minutes) * 60

    try:
        while _running:
            _publish_pipeline(mqtt, status, "running", "inference")
            try:
                _run_inference_once(features, model, dataset, mqtt, status)
            except Exception:  # a transient feature/predict error must not kill the loop
                log.exception("Inference failed")
                status["last_error"] = "inference failed (see log)"
            _publish_pipeline(mqtt, status, "idle", "none")

            _process_commands(processor, cmd_queue, mqtt, status)

            now = datetime.now()
            if now.hour == cfg.nightly_retrain_hour and now.day != last_nightly_day:
                _publish_pipeline(mqtt, status, "running", "retrain")
                _nightly_batch(cfg, dataset, mqtt, model, registry, status)
                _publish_pipeline(mqtt, status, "idle", "none")
                last_nightly_day = now.day

            # Sleep in short slices so SIGTERM and commands are honored promptly.
            waited = 0
            while _running and waited < interval:
                time.sleep(min(5, interval - waited))
                waited += 5
                _process_commands(processor, cmd_queue, mqtt, status)
    finally:
        mqtt.disconnect()
        log.info("Stopped.")
    return 0


def _promote(mqtt: MqttClient, registry: ModelRegistry) -> str:
    version = registry.promote()
    _publish_registry(mqtt, registry)
    return f"promoted {version}"


def _rollback(mqtt: MqttClient, registry: ModelRegistry) -> str:
    version = registry.rollback()
    _publish_registry(mqtt, registry)
    return f"rolled back to {version}"


if __name__ == "__main__":
    sys.exit(main())

"""Service entrypoint: fast inference loop + nightly batch.

Fast loop (every `fast_loop_minutes`): build features -> predict -> publish over
MQTT -> append to dataset. Once per day at `nightly_retrain_hour`: run the batch
(dataset consolidation + recalibrate/retrain in Phase 4) and publish model_health.
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime

from .config import DATA_DIR, Config
from .dataset import DatasetWriter
from .features import FeatureBuilder
from .ha import HAClient
from .model import Model
from .mqtt_client import MqttPublisher

log = logging.getLogger("app")

_running = True


def _handle_sigterm(_signum, _frame):
    global _running
    log.info("SIGTERM received — shutting down cleanly.")
    _running = False


def _run_nightly(cfg: Config, dataset: DatasetWriter, mqtt: MqttPublisher, model: Model) -> None:
    log.info("Nightly batch: dataset=%d rows, events=%d", dataset.row_count(), model.event_count())
    # Phase 4: append day's data, recalibrate/retrain, version artifact, log skill metrics.
    mqtt.publish(
        "model_health",
        {
            "dataset_rows": dataset.row_count(),
            "event_count": model.event_count(),
            "min_events_for_ml": cfg.min_events_for_ml,
            "active_method": "ml" if model.event_count() >= cfg.min_events_for_ml else "threshold",
            "ran_at": datetime.now().isoformat(timespec="seconds"),
        },
    )


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

    mqtt = MqttPublisher(cfg.mqtt_host, cfg.mqtt_port, cfg.mqtt_user, cfg.mqtt_pass, cfg.mqtt_base_topic)
    mqtt.connect()

    features = FeatureBuilder(cfg, ha)
    model = Model(cfg, data_dir)
    dataset = DatasetWriter(data_dir)

    last_nightly_day: int | None = None
    interval = max(1, cfg.fast_loop_minutes) * 60

    try:
        while _running:
            row = features.build()
            pred = model.predict(row)

            mqtt.publish("flood_probability", {"value": pred.flood_probability, "method": pred.method})
            mqtt.publish("predicted_crest", {"value": pred.predicted_crest_ft})
            mqtt.publish("lag_estimate", {"value": pred.lag_estimate_min})
            dataset.append_row(row)

            now = datetime.now()
            if now.hour == cfg.nightly_retrain_hour and now.day != last_nightly_day:
                _run_nightly(cfg, dataset, mqtt, model)
                last_nightly_day = now.day

            # Sleep in short slices so SIGTERM is honored promptly.
            waited = 0
            while _running and waited < interval:
                time.sleep(min(5, interval - waited))
                waited += 5
    finally:
        mqtt.disconnect()
        log.info("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

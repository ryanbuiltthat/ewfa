"""MQTT Discovery — auto-provision the add-on's HA entities.

Publishing retained config messages under
`homeassistant/<component>/creek_modeling/<slug>/config` makes Home Assistant create
(and update) the `creek_*` sensors and buttons automatically — no HA package or
`configuration.yaml` edit for them, and they refresh whenever the add-on updates.

Because every entity carries a `device` block, Home Assistant prefixes the device name
when it mints the entity_id — the published slug `creek_flood_probability` lands as
`sensor.ackerly_creek_modeling_creek_flood_probability`. That prefix is what the
dashboard references; only entities defined here get it. The HA-side template sensors in
`ha-packages/creek_warning.yaml` (soil mean, ponding, the stale watchdogs) and the
ESPHome creek node are *not* published here and keep their unprefixed IDs.

All entities share one `device` and an `availability_topic` driven by the MQTT LWT, so
they show *unavailable* when the add-on is stopped.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("app.discovery")

DISCOVERY_PREFIX = "homeassistant"
NODE_ID = "creek_modeling"


class DiscoveryPublisher:
    def __init__(self, publish_raw, base_topic: str):
        """`publish_raw(topic, payload_str, retain)` sends a raw string; `base_topic`
        is the add-on's MQTT base (default `creek`)."""
        self._publish_raw = publish_raw
        self._base = base_topic.rstrip("/")

    def _device(self) -> dict:
        return {
            "identifiers": ["ackerly_creek_modeling"],
            "name": "Ackerly Creek Modeling",
            "manufacturer": "ewfa",
            "model": "Flood modeling add-on",
        }

    def _availability(self) -> dict:
        return {
            "availability_topic": f"{self._base}/status/availability",
            "payload_available": "online",
            "payload_not_available": "offline",
        }

    def _specs(self) -> list[tuple[str, str, dict]]:
        """(component, slug, partial-config). State/command topics are relative to base."""
        b = self._base
        return [
            # --- model outputs ---
            ("sensor", "creek_flood_probability", {
                "name": "Creek Flood Probability",
                "state_topic": f"{b}/flood_probability",
                "value_template": "{{ (value_json.value | float(0) * 100) | round(0) }}",
                "unit_of_measurement": "%", "state_class": "measurement",
                "json_attributes_topic": f"{b}/flood_probability", "icon": "mdi:water-alert"}),
            ("sensor", "creek_model_method", {
                "name": "Creek Model Method",
                "state_topic": f"{b}/flood_probability",
                "value_template": "{{ value_json.method }}", "icon": "mdi:function-variant"}),
            ("sensor", "creek_predicted_crest", {
                "name": "Creek Predicted Crest",
                "state_topic": f"{b}/predicted_crest",
                "value_template": "{{ value_json.value if value_json.value is not none else 'unknown' }}",
                "unit_of_measurement": "ft", "state_class": "measurement", "icon": "mdi:wave"}),
            ("sensor", "creek_lag_estimate", {
                "name": "Creek Lag Estimate",
                "state_topic": f"{b}/lag_estimate",
                "value_template": "{{ value_json.value if value_json.value is not none else 'unknown' }}",
                "unit_of_measurement": "min", "state_class": "measurement", "icon": "mdi:timer-sand"}),
            ("sensor", "creek_alert_tier", {
                "name": "Creek Alert Tier",
                "state_topic": f"{b}/alert_tier",
                "value_template": "{{ value_json.value }}",
                "json_attributes_topic": f"{b}/alert_tier", "icon": "mdi:alert-decagram"}),
            ("sensor", "creek_tier_reason", {
                "name": "Creek Tier Reason",
                "state_topic": f"{b}/alert_tier",
                "value_template": "{{ value_json.why }}",
                "icon": "mdi:comment-question-outline"}),
            # --- pipeline status ---
            ("sensor", "creek_pipeline_state", {
                "name": "Creek Pipeline State",
                "state_topic": f"{b}/status/pipeline",
                "value_template": "{{ value_json.state }}",
                "json_attributes_topic": f"{b}/status/pipeline", "icon": "mdi:cog-play"}),
            ("sensor", "creek_last_inference", {
                "name": "Creek Last Inference",
                "state_topic": f"{b}/status/pipeline", "device_class": "timestamp",
                "value_template": "{{ value_json.last_inference_at if value_json.last_inference_at is not none else none }}",
                "icon": "mdi:clock-check-outline"}),
            ("sensor", "creek_last_nightly", {
                "name": "Creek Last Nightly Run",
                "state_topic": f"{b}/status/pipeline", "device_class": "timestamp",
                "value_template": "{{ value_json.last_nightly_at if value_json.last_nightly_at is not none else none }}",
                "icon": "mdi:weather-night"}),
            ("sensor", "creek_last_command", {
                "name": "Creek Last Command",
                "state_topic": f"{b}/status/command_result",
                "value_template": "{{ value_json.command }} ({{ 'ok' if value_json.ok else 'failed' }})",
                "json_attributes_topic": f"{b}/status/command_result", "icon": "mdi:console"}),
            # --- model health / registry ---
            ("sensor", "creek_model_health", {
                "name": "Creek Model Health",
                "state_topic": f"{b}/model_health",
                "value_template": "{{ value_json.active_method }}",
                "json_attributes_topic": f"{b}/model_health", "icon": "mdi:heart-pulse"}),
            ("sensor", "creek_dataset_rows", {
                "name": "Creek Dataset Rows",
                "state_topic": f"{b}/model_health",
                "value_template": "{{ value_json.dataset_rows }}",
                "state_class": "measurement", "icon": "mdi:table"}),
            ("sensor", "creek_event_count", {
                "name": "Creek Event Count",
                "state_topic": f"{b}/status/registry",
                "value_template": "{{ value_json.event_count }}",
                "state_class": "measurement", "icon": "mdi:weather-lightning-rainy"}),
            ("sensor", "creek_active_model", {
                "name": "Creek Active Model",
                "state_topic": f"{b}/status/registry",
                "value_template": "{{ value_json.active_version if value_json.active_version is not none else 'none' }}",
                "json_attributes_topic": f"{b}/status/registry", "icon": "mdi:cube-outline"}),
            ("sensor", "creek_candidate_model", {
                "name": "Creek Candidate Model",
                "state_topic": f"{b}/status/registry",
                "value_template": "{{ value_json.candidate_version if value_json.candidate_version is not none else 'none' }}",
                "icon": "mdi:cube-scan"}),
            # --- ingested features (Addendum C 2a): rain accumulations + NWS QPF ---
            *(
                ("sensor", f"creek_rain_{w}h", {
                    "name": f"Creek Rain {w}h",
                    "state_topic": f"{b}/features",
                    "value_template": f"{{{{ value_json.rain_{w}h_in if value_json.rain_{w}h_in is not none else none }}}}",
                    "unit_of_measurement": "in", "device_class": "precipitation",
                    "state_class": "measurement", "icon": "mdi:weather-pouring"})
                for w in (1, 3, 6, 24, 72)
            ),
            ("sensor", "creek_qpf_6h", {
                "name": "Creek QPF 6h",
                "state_topic": f"{b}/features",
                "value_template": "{{ value_json.qpf_6h_in if value_json.qpf_6h_in is not none else none }}",
                "unit_of_measurement": "in", "device_class": "precipitation",
                "state_class": "measurement", "icon": "mdi:weather-rainy"}),
            ("sensor", "creek_qpf_24h", {
                "name": "Creek QPF 24h",
                "state_topic": f"{b}/features",
                "value_template": "{{ value_json.qpf_24h_in if value_json.qpf_24h_in is not none else none }}",
                "unit_of_measurement": "in", "device_class": "precipitation",
                "state_class": "measurement", "icon": "mdi:weather-rainy"}),
            # --- ingested features (Addendum C 2b): upstream WU + NWM reach ---
            *(
                ("sensor", f"creek_upstream_rain_{w}h", {
                    "name": f"Creek Upstream Rain {w}h",
                    "state_topic": f"{b}/features",
                    "value_template": f"{{{{ value_json.upstream_rain_{w}h_in if value_json.upstream_rain_{w}h_in is not none else none }}}}",
                    "unit_of_measurement": "in", "device_class": "precipitation",
                    "state_class": "measurement", "icon": "mdi:weather-pouring"})
                for w in (1, 3, 6, 24, 72)
            ),
            ("sensor", "creek_upstream_precip_today", {
                "name": "Creek Upstream Precip Today",
                "state_topic": f"{b}/features",
                "value_template": "{{ value_json.upstream_precip_today_in if value_json.upstream_precip_today_in is not none else none }}",
                "unit_of_measurement": "in", "device_class": "precipitation",
                "state_class": "measurement", "icon": "mdi:weather-pouring"}),
            ("sensor", "creek_nwm_flow", {
                "name": "Creek NWM Flow",
                "state_topic": f"{b}/features",
                "value_template": "{{ value_json.nwm_flow_cfs if value_json.nwm_flow_cfs is not none else none }}",
                "unit_of_measurement": "ft³/s", "state_class": "measurement",
                "icon": "mdi:waves-arrow-right"}),
            ("sensor", "creek_nwm_flow_peak", {
                "name": "Creek NWM Flow Peak",
                "state_topic": f"{b}/features",
                "value_template": "{{ value_json.nwm_flow_max_cfs if value_json.nwm_flow_max_cfs is not none else none }}",
                "unit_of_measurement": "ft³/s", "state_class": "measurement",
                "icon": "mdi:waves-arrow-up"}),
            # --- ingested features (Addendum C 2c): USGS downstream gauges ---
            *(
                spec
                for site, label, pretty in (
                    ("01534860", "leggetts", "Leggetts"),
                    ("01534000", "tunkhannock", "Tunkhannock"),
                )
                for spec in (
                    ("sensor", f"creek_usgs_{label}_gage", {
                        "name": f"Creek USGS {pretty} Gage Height",
                        "state_topic": f"{b}/features",
                        "value_template": (f"{{{{ value_json.usgs_{label}_gage_ft "
                                           f"if value_json.usgs_{label}_gage_ft is not none else none }}}}"),
                        "unit_of_measurement": "ft", "state_class": "measurement",
                        "icon": "mdi:altimeter"}),
                    ("sensor", f"creek_usgs_{label}_flow", {
                        "name": f"Creek USGS {pretty} Flow",
                        "state_topic": f"{b}/features",
                        "value_template": (f"{{{{ value_json.usgs_{label}_flow_cfs "
                                           f"if value_json.usgs_{label}_flow_cfs is not none else none }}}}"),
                        "unit_of_measurement": "ft³/s", "state_class": "measurement",
                        "icon": "mdi:waves"}),
                    ("sensor", f"creek_usgs_{label}_rise_3h", {
                        "name": f"Creek USGS {pretty} Rise 3h",
                        "state_topic": f"{b}/features",
                        "value_template": (f"{{{{ value_json.usgs_{label}_rise_3h_ft "
                                           f"if value_json.usgs_{label}_rise_3h_ft is not none else none }}}}"),
                        "unit_of_measurement": "ft", "state_class": "measurement",
                        "icon": "mdi:trending-up"}),
                )
            ),
            # --- command buttons ---
            ("button", "creek_run_inference_now", {
                "name": "Creek Run Inference Now",
                "command_topic": f"{b}/cmd/run_inference", "payload_press": "run", "icon": "mdi:play"}),
            ("button", "creek_retrain_now", {
                "name": "Creek Retrain Now",
                "command_topic": f"{b}/cmd/retrain", "payload_press": "run", "icon": "mdi:brain"}),
            ("button", "creek_promote_model", {
                "name": "Creek Promote Model",
                "command_topic": f"{b}/cmd/promote", "payload_press": "run", "icon": "mdi:arrow-up-bold-box"}),
            ("button", "creek_rollback_model", {
                "name": "Creek Rollback Model",
                "command_topic": f"{b}/cmd/rollback", "payload_press": "run", "icon": "mdi:undo-variant"}),
        ]

    def configs(self) -> list[tuple[str, dict]]:
        """Build (discovery_topic, full_config) pairs — exposed for testing."""
        out = []
        device, avail = self._device(), self._availability()
        for component, slug, cfg in self._specs():
            full = {
                "unique_id": f"creek_modeling_{slug}",
                "object_id": slug,
                "device": device,
                **avail,
                **cfg,
            }
            topic = f"{DISCOVERY_PREFIX}/{component}/{NODE_ID}/{slug}/config"
            out.append((topic, full))
        return out

    def publish_all(self) -> None:
        pairs = self.configs()
        for topic, cfg in pairs:
            self._publish_raw(topic, json.dumps(cfg), True)
        log.info("Published MQTT discovery for %d entities", len(pairs))

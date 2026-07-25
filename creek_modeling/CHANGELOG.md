# Changelog

All notable changes to the **Ackerly Creek Modeling** add-on are documented here.
The version matches `version:` in `config.yaml`; bump it to trigger the GUI Update button.

## 0.2.0

- **On-demand commands:** subscribes to `creek/cmd/{run_inference,retrain,promote,rollback}`
  so the HA dashboard can drive the pipeline. Commands execute on the service's single
  thread (no overlapping runs) and are honored within a few seconds.
- **Status publishing:** new `creek/status/pipeline` (state/task/last-run/last-error),
  `creek/status/registry` (active/candidate/history + metrics), and
  `creek/status/command_result` (echo of each command's outcome).
- **Model registry** (`app/registry.py`): real `models/registry.json` schema with working
  `promote()`/`rollback()` pointer logic; ML training/artifact loading remains a Phase-4 stub
  behind the same interface.
- **Fix:** construct the MQTT client with paho-mqtt 2.x's `CallbackAPIVersion` (the previous
  1.x-style constructor raised on the pinned `paho-mqtt>=2.1`).

## 0.1.0

- Phase 2 skeleton: validates the Supervisor Core-API proxy and MQTT wiring.
- Builds live features (creek stage, rate-of-rise, WH51 soil moisture + ponding flag).
- Returns a transparent conservative **threshold** estimate; gates ML on
  `min_events_for_ml` storms captured.
- Publishes `creek/flood_probability`, `creek/predicted_crest`, `creek/lag_estimate`,
  `creek/model_health` over MQTT.
- Installable as a Git-based add-on repository (GUI) or as a local add-on.

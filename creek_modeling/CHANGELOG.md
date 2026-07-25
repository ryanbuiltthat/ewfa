# Changelog

All notable changes to the **Ackerly Creek Modeling** add-on are documented here.
The version matches `version:` in `config.yaml`; bump it to trigger the GUI Update button.

## 0.4.0

- **Forecast/upstream ingestion — slice 2a** (spec Addendum C): the add-on now fetches its
  own features and publishes them on `creek/features`, auto-created as discovery sensors:
  - **On-site rain accumulations** `rain_{1,3,6,24,72}h` — a rolling accumulator integrates
    the Ecowitt rain rate (in or mm) into a 72 h ring persisted under `/data/state/`.
  - **NWS QPF** `qpf_6h` / `qpf_24h` — free NOAA gridpoint forecast (no key), pro-rated from
    the mm interval values to inches. Location read from HA config; refresh ~15 min.
- Sources run through a coordinator with per-source refresh + last-good caching, so a flaky
  API never stalls or crashes the fast loop. Feature rows (and the dataset) widen accordingly.
- Adds tests for the accumulator, QPF parsing/proration, and the coordinator. Bump 0.4.0.
- (Slice 2b — Weather Underground upstream + NWM reach — to follow.)

## 0.3.0

- **MQTT Discovery:** the add-on now auto-provisions its HA entities (all `creek_*` sensors
  and the four command buttons) under an *Ackerly Creek Modeling* device — no HA package or
  `configuration.yaml` edit for them, and they re-publish on every (re)connect so they track
  add-on updates. Removes `ha-packages/creek_modeling.yaml`; the sensor-fault watchdogs move
  into the Layer-1 `creek_warning.yaml`.
- **Availability (LWT):** publishes `creek/status/availability` online/offline so discovered
  entities show *unavailable* when the add-on stops.
- **Alert tier in the add-on:** computes and publishes `creek/alert_tier` (`value` + `label`)
  from probability + ponding (`app/tiers.py`), replacing the HA template. PLACEHOLDER
  thresholds (open question #7).

## 0.2.0

- **On-demand commands:** subscribes to `creek/cmd/{run_inference,retrain,promote,rollback}`
  so the HA dashboard can drive the pipeline. Commands execute on the service's single
  thread (no overlapping runs) and are honored within a few seconds.
- **Status publishing:** timestamps are tz-aware ISO (proper HA `timestamp` sensors);
  new `creek/status/pipeline` (state/task/last-run/last-error),
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

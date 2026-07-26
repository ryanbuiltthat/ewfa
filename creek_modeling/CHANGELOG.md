# Changelog

All notable changes to the **Ackerly Creek Modeling** add-on are documented here.
The version matches `version:` in `config.yaml`; bump it to trigger the GUI Update button.

## 0.7.0

- **NWS active alert products — ingestion slice 2d** (spec §3): `app/sources/alerts.py`
  polls `api.weather.gov/alerts/active?point=` (free, no key, 5 min) and reports flags for
  an active Flood Watch, Flood Warning, and Flash Flood Warning covering the site, plus a
  total active-product count. Querying by point rather than county zone means only alerts
  whose polygon actually covers us count.
- **Tier force-promotion** (spec §6): an active product now imposes a *floor* on the alert
  tier regardless of what our own instruments show — Flood Watch → ≥ Advisory, Flood
  Warning → ≥ Watch (the rule §6 mandates), Flash Flood Warning → ≥ Warning. A floor never
  lowers a tier the sensors have already earned. The Watch and Flash Flood floors go beyond
  the letter of §6 and are marked as such in `tiers.py`: a Flood Watch *is* the forecast-risk
  case Advisory describes, and in a basin with a tens-of-minutes response (§1) a flash flood
  warning is materially more urgent than an areal one.
- Adds a `Creek NWS Alerts Missing` watchdog. The feed reports "no alerts" as 0 rather than
  null, so an unavailable count means the call itself is failing — and a Flood Warning could
  be in effect without us escalating.

## 0.6.0

- **Forecast-driven alert tiers** (spec §6, Addendum C.3): `app/tiers.py` now evaluates the
  full feature row instead of probability alone, so **Tier 1 Advisory** (NWS QPF onto wet
  soil) and **Tier 2 Watch** (upstream/on-site rain accumulating) fire *without the creek
  gauge* — the first genuinely useful warnings the system can issue before the SEN0676 is
  mounted. Each tier publishes the reasons that fired it (`why` attribute), surfaced on the
  dashboard and in the notification.
  - **Breaking (entity semantics):** the tier scale is now `0` All-clear · `1` Advisory ·
    `2` Watch · `3` Warning · `4` Emergency, matching spec §6 plus an explicit all-clear.
    Previously `0`–`3` collapsed Advisory into Watch. The dashboard is updated in the same
    commit; any external automation keyed on the old numbers needs re-checking.
- **USGS downstream gauges — ingestion slice 2c**: new `app/sources/usgs.py` polls NWIS
  instantaneous values for 01534860 (Lackawanna River below Leggetts Creek at Scranton) and
  01534000 (Tunkhannock Creek), reporting gage height, discharge, and 3 h rise for each. Free,
  no key. Leggetts Creek drains the same Clarks Summit / Chinchilla upland as our upstream
  half, so that gauge sees roughly our rain. These are a
  *different, larger* basin — not a creek-level proxy — but they are the only observed
  rainfall→response signal available before the creek node exists, which gives the Phase-3
  lag estimate a head start. New `usgs_downstream` option (default on).
- **Ingest watchdogs**: four new HA-side binary sensors flag a source publishing no value
  (QPF, upstream PWS, NWM, USGS). They test for a *value*, not staleness — a feature
  legitimately sitting at 0.00 in never changes state, so a staleness check would false-alarm.
- **Tier notification automation** replaces the old Tier 0 placeholder, which keyed off a
  `sensor.nws_qpf_24h` REST sensor that Addendum C decided never to build. Notifications
  only; escalating/wake-the-house actions stay unwired until thresholds are calibrated.
- **Fixes:**
  - Entity IDs in `ha-packages/creek_warning.yaml` and the dashboard now match reality.
    MQTT-discovery entities carry the device-name prefix (`sensor.ackerly_creek_modeling_creek_*`);
    HA-package templates and the ESPHome node do not. A previous blanket rename had applied
    the prefix to seven entities that never had it, and the pipeline-state watchdog was
    missing the prefix it did need. `discovery.py`'s docstring claimed the old scheme.
  - `sensor.outside_weather_station_rain_rate` → `sensor.weather_station_rain_rate` in the
    rain-rate watchdog (missed by the earlier entity-name correction).
  - An unset `nwm_reach_id` reaches Python as the literal string `"null"` from
    `bashio::config`; it now disables the source instead of polling a bogus reach.

## 0.5.0

- **Forecast/upstream ingestion — slice 2b** (spec Addendum C): adds two sources, published
  on `creek/features` and auto-created as discovery sensors:
  - **Weather Underground upstream PWS** — mean `precipRate` across the configured upstream
    stations feeds a rolling accumulator (`upstream_rain_{1,3,6,24,72}h`), plus
    `upstream_precip_today`. A single station failing is skipped, not fatal. Key stays in options.
  - **NWM / NWPS reach** — short-range streamflow forecast for `nwm_reach_id`: near-term
    (`nwm_flow`) and short-range peak (`nwm_flow_peak`) discharge in ft³/s.
- Extracts the rolling accumulator into `app/sources/accumulator.py`, shared by on-site rain
  and upstream WU. Dashboard gains an "Upstream & model" card. Tests for WU + NWM. Bump 0.5.0.

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

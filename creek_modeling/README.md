# Ackerly Creek Modeling (HAOS add-on)

Layer 2 of the [Ackerly Creek Flood Early-Warning System](../creek-flood-warning-spec.md).
Runs the flood-probability + predicted-stage inference (fast loop) and the nightly
retrain/recalibrate batch, publishing results to Home Assistant over MQTT.

Resolves Open Question #1 — HA install is HAOS, so Layer 2 ships as a Supervisor add-on.
The repo doubles as a **Git-based add-on store** (`repository.yaml` at the repo root), so the
add-on installs and updates entirely through the GUI; a local-add-on copy still works offline.

## Install via repository (GUI, recommended)

1. **Settings → Add-ons → Add-on Store →** ⋮ (top-right) **→ Repositories**, paste
   `https://github.com/ryanbuiltthat/ewfa`, and **Add**.
2. The **Ackerly Creek Modeling** card appears in the store. Open it and **Install**
   (first install builds the Debian image on the host — amd64 only).
3. Set options (API keys, entity IDs, thresholds) on the **Configuration** tab, then
   **Start**. Requires the **Mosquitto broker** add-on (declared `mqtt:need`).
4. Updates: bump `version` in `config.yaml` upstream; the GUI shows an **Update** button
   after **⋮ → Check for updates**.

## Install as a local add-on (offline fallback)

1. Copy this folder to the HAOS `/addons/` directory (via the Samba or SSH & Web Terminal
   add-on): `/addons/creek_modeling/`.
2. **Settings → Add-ons → Add-on Store → ⋮ → Check for updates**. The add-on appears
   under **Local add-ons**.
3. Open it, set options on the **Configuration** tab, then **Start**.

## Required HA-side config

The add-on's `creek_*` sensors and buttons are created **automatically via MQTT Discovery**
(under an *Ackerly Creek Modeling* device) — no package or config edit, and they update with
the add-on. Only two things need a one-time manual step: the Layer-1 package
`ha-packages/creek_warning.yaml` (soil sensors + Tier-0 automation + watchdogs) and the
`dashboards/creek_flood_watch.yaml` dashboard registration. Full steps are in
[DOCS.md](./DOCS.md#companion-home-assistant-config).

## How it talks to HA

- **Reads** entity states through the Supervisor proxy at `http://supervisor/core/api`,
  authenticated by the injected `SUPERVISOR_TOKEN` — no long-lived token needed
  (`homeassistant_api: true`).
- **Writes** `creek/flood_probability`, `creek/predicted_crest`, `creek/lag_estimate`,
  and `creek/model_health` over MQTT (broker from service discovery). Add matching HA
  MQTT sensors to surface them as entities for the alert automations.

## Inputs

| Option | Default | Notes |
|---|---|---|
| `stage_entity` | `sensor.creek_stage` | Creek node (ESPHome) level — set to the real entity |
| `soil_moisture_entities` | WH51 #1, #2 | `sensor.outside_weather_station_soil_moisture_1` (near house / willow), `_2` (near creek) — both low-lying, pond early |
| `onsite_rain_rate_entity` | `sensor.outside_weather_station_rain_rate` | Ecowitt |
| `onsite_rain_daily_entity` | `sensor.outside_weather_station_daily_rain` | Ecowitt |
| `min_events_for_ml` | `10` | Stay on threshold model until ≥ N storms captured |

## Model features (spec §5)

Features the nightly dataset builder records per row and the model consumes. Live subset
today; the rest fill in through Phase 3/4 as sources come online.

- **Creek stage** (`stage_entity`) and **rate-of-rise** (in/min, derived).
- **Soil moisture — antecedent wetness** (Ecowitt WH51 ×2, both in low-lying, early-ponding
  spots): `sensor.outside_weather_station_soil_moisture_1` (near house / willow) and
  `sensor.outside_weather_station_soil_moisture_2` (near creek). Recorded individually plus
  a mean and a `ponding_flag`. **Note:** WH51 readings are relative (0–100%) and
  site-specific — see open question #7; the saturated/dry endpoints need field calibration
  before the ponding threshold and Tier 0 condition are meaningful.
- **Rainfall** — on-site rate/daily (Ecowitt) and upstream PWS accumulations (1/3/6/24/72 h).
- **Forecast/model** — NWS QPF (next 6/24 h) and NWM reach forecast (live); Google flood
  status (not built yet).
- **Neighbouring gauges** — USGS 01534860 (Lackawanna below Leggetts Ck) and 01534000
  (Tunkhannock Ck): gage height, discharge and 3 h rise. Different basins with their own lag,
  so not a stand-in for creek level; they are the
  observed rainfall→response record used to bootstrap the lag estimate while the creek node
  is still to be built.
- **Context** — SNODAS SWE, temperature (rain-on-snow flag), season. (Not built yet.)

## Persistent storage (`/data`)

```text
/data/datasets/dataset.parquet   nightly-appended feature/label rows
/data/events.sqlite              annotated storm event log
/data/models/registry.json       versioned artifacts + skill metrics
```

## Status

Phase 2 **skeleton**: validates the Supervisor proxy + MQTT wiring, builds live
features (stage, rate-of-rise, soil moisture + ponding flag), and returns a
transparent conservative **threshold** estimate. Gradient-boosting inference and
nightly retrain land in Phase 4 behind the same interfaces (`app/model.py`).

## Local dev (outside HAOS)

`app/` runs on any Python 3.11+. With no `/data/options.json` present it falls back to
env-only config; point `HA_API_URL`/`SUPERVISOR_TOKEN` at a dev HA and `MQTT_*` at a
broker to smoke-test.

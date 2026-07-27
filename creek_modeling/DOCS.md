# Ackerly Creek Modeling

Layer 2 of the Ackerly Creek Flood Early-Warning System. Runs the flood-probability +
predicted-stage inference (fast loop) and the nightly retrain/recalibrate batch, publishing
results to Home Assistant over MQTT.

## Prerequisites

- **Mosquitto broker** add-on installed and configured. This add-on declares `mqtt:need` and
  will exit on start if no MQTT service is available.
- Host architecture **amd64** (the add-on is amd64-only).

## Companion Home Assistant config

**The add-on's own entities are created automatically via MQTT Discovery** — the `creek_*`
sensors and buttons (flood probability, predicted crest, lag, alert tier, pipeline/model
status, and the Run inference / Retrain / Promote / Rollback buttons) appear under an
**Ackerly Creek Modeling** device with no package or `configuration.yaml` edit, and they
re-publish (so they stay current) whenever the add-on updates. An MQTT LWT flips them to
*unavailable* when the add-on is stopped.

Two things still need a **one-time** manual setup (they can't come from the add-on):

1. **Layer-1 package** — soil-moisture template sensors, the Tier-0 automation, and the
   sensor-fault watchdogs. Copy `ha-packages/creek_warning.yaml` from the
   [ewfa repo](https://github.com/ryanbuiltthat/ewfa) → `/config/ha-packages/`, and enable
   packages in `/config/configuration.yaml`:

   ```yaml
   homeassistant:
     packages: !include_dir_named ha-packages
   ```

2. **Dashboard** — copy `dashboards/creek_flood_watch.yaml` → `/config/dashboards/` and
   register it (core Lovelace, keeps your UI dashboards untouched):

   ```yaml
   lovelace:
     mode: storage
     dashboards:
       creek-flood-watch:     # slug must contain a hyphen
         mode: yaml
         title: Creek Flood Watch
         icon: mdi:water-alert
         show_in_sidebar: true
         filename: dashboards/creek_flood_watch.yaml
   ```

Then **Developer Tools → YAML → Check Configuration** and **Restart**. `!include_dir_named`
and `filename:` are relative to the config directory; the package `template:` block merges
with anything you already have.

> These two files are the source of truth in the repo; the `/config` copies are a deploy
> target — re-copy after pulling repo changes. (The discovered entities need no re-copy.)

## Configuration

Set these on the **Configuration** tab.

| Option | Default | Notes |
|---|---|---|
| `log_level` | `info` | `trace`…`fatal` |
| `fast_loop_minutes` | `5` | Inference cadence (1–60) |
| `nightly_retrain_hour` | `3` | Local hour (0–23) for the nightly batch |
| `mqtt_base_topic` | `creek` | Base MQTT topic |
| `publish_prefix` | `creek` | MQTT topic prefix (entity IDs come from discovery, see below) |
| `min_events_for_ml` | `10` | Stay on the threshold model until ≥ N storms captured |
| `google_floods_api_key` | `""` | Optional (Google Flood status) |
| `wu_api_key` | `""` | Optional (Weather Underground PWS) |
| `nwm_reach_id` | `4196026` | NWM reach at the sensor site (open question #3) |
| `upstream_pws_ids` | `KPAGLENB2`, `KPACLARK41` | Upstream PWS in the Clarks Summit corridor (open question #4) |
| `stage_entity` | `sensor.creek_stage` | Creek node (ESPHome) level — set to the real entity |
| `soil_moisture_entities` | WH51 #1, #2 | `..._soil_moisture_willow` (near house), `..._soil_moisture_field` (near creek); order is significant |
| `onsite_rain_rate_entity` | `sensor.outside_weather_station_rain_intensity` | Ecowitt |
| `onsite_rain_daily_entity` | `sensor.outside_weather_station_rain_24hr` | Ecowitt. **Currently unused** — the rolling rain accumulations are integrated from `onsite_rain_rate_entity`, not read from here |
| `usgs_downstream` | `true` | Poll USGS 01534860 / 01534000 (free, no key) for lag validation |
| `snodas_swe` | `true` | Daily SNODAS snow-water-equivalent for the site cell (free, no key) |
| `onsite_temp_entity` | `sensor.outside_weather_station_outdoors_temp` | Ecowitt; needed for the rain-on-snow flag |

## How it talks to Home Assistant

- **Reads** entity states through the Supervisor proxy at `http://supervisor/core/api`,
  authenticated by the injected `SUPERVISOR_TOKEN` — no long-lived token needed
  (`homeassistant_api: true`).
- **Writes** its outputs, ingested features and status over MQTT (broker discovered via
  services) and auto-creates the matching HA entities via MQTT discovery — no package edit.
- **Watchdogs** for every input and source are computed in the add-on and published on
  `creek/status/health`, so they appear automatically with everything else.
- **Entity IDs:** the discovered entities belong to an *Ackerly Creek Modeling* device, so
  Home Assistant prefixes the device name:
  `sensor.ackerly_creek_modeling_creek_flood_probability`,
  `sensor.ackerly_creek_modeling_creek_qpf_24h`, and so on. Entities defined in
  `ha-packages/creek_warning.yaml` and the ESPHome creek node are *not* discovery entities and
  stay unprefixed (`sensor.creek_*`). That package is now down to two things that cannot live
  here: the tier notification automation, and the add-on's own liveness watchdog.

## Alert tiers

`app/tiers.py` evaluates spec §6 and publishes `creek/alert_tier` with a numeric level, a
label, and the reasons that fired:

| Level | Label | Driven by | Needs the creek gauge? |
|---|---|---|---|
| 0 | All-clear | nothing elevated | — |
| 1 | Advisory | NWS QPF + antecedent soil moisture | No |
| 2 | Watch | upstream / on-site rain accumulation | No |
| 3 | Warning | stage, rate-of-rise | Yes |
| 4 | Emergency | stage near bank top | Yes |

An active NWS product additionally sets a **floor** on the tier, whatever our own sensors
say (spec §6): Flood Watch → ≥ Advisory, Flood Warning → ≥ Watch, Flash Flood Warning →
≥ Warning. A floor never lowers a tier the sensors have already earned.

Levels 1–2 run entirely off forecast and rainfall data, so the system issues useful
warnings before the SEN0676 is mounted. Levels 3–4 stay dormant until the ESPHome node
reports stage. **All thresholds are placeholders** pending the surveyed datum (open
question #5), WH51 calibration (#7), and observed storms (Phase 3).

## Persistent storage

```text
/data/datasets/parts/*.jsonl              today's rows, appended each fast loop
/data/datasets/dataset.parquet            consolidated nightly from completed parts
/data/models/registry.json                versioned artifacts + skill metrics
/data/models/model-<version>.json         a candidate/active artifact (xgboost native format)
/data/models/model-<version>.meta.json    its feature column order + horizon
/data/state/*.json                        rain/API/SNODAS accumulator state
/share/creek_modeling/events.sqlite       annotated storm event log
```

`/data` is private to this add-on. The storm log is the exception and lives in `/share`,
because it is the one file a human is expected to edit: `/data` inside the SSH/Terminal
add-on is *that* add-on's own `/data`, so a `sqlite3 /data/events.sqlite` typed there
would silently create and edit an empty database. `/share` is one path that means the same
thing from every add-on, and it is exported over Samba. An events.sqlite left in `/data`
by an earlier version is moved across automatically on first start; if `/share` is
unavailable the add-on logs a warning and keeps using `/data`. The resolved path is logged
at startup — `Storm event log at …`.

Annotating a storm (the "annotated" half of the Phase 3 event log) is a SQLite update.
The `sqlite3` CLI is installed in this add-on's image, but you do not need it — run this
from the **SSH & Web Terminal** add-on, or open the file over Samba with any SQLite
browser:

```sh
sqlite3 /share/creek_modeling/events.sqlite \
  "SELECT id, datetime(started_ts,'unixepoch','localtime'), ended_ts
     FROM storm_events ORDER BY id DESC LIMIT 5;"

sqlite3 /share/creek_modeling/events.sqlite \
  "UPDATE storm_events SET notes='basement dry; culvert ran full' WHERE id=3;"
```

Editing while the service is running is fine — both sides use a 5 s busy timeout, and the
fast loop's writes are sub-millisecond.

## Status

Phase 2 (Ingest) — complete except for Google Flood Forecasting, which is waiting on API
access. Live: on-site rain accumulations, the Antecedent Precipitation Index, NWS QPF, NWS
active alert products, Weather Underground upstream PWS, NWM reach forecast, USGS gauges,
SNODAS snowpack with a rain-on-snow flag, forecast-driven alert tiers, and watchdogs on
every ingest source. Gradient-boosting inference and
nightly retrain land in Phase 4 behind the same interfaces (`app/model.py`).

> **Calibration note:** WH51 soil-moisture readings are relative (0–100 %) and site-specific.
> The saturated/dry endpoints need field calibration (open question #7) before the ponding
> threshold and Tier 0 condition are meaningful.

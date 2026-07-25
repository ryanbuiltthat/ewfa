# Ackerly Creek Modeling

Layer 2 of the Ackerly Creek Flood Early-Warning System. Runs the flood-probability +
predicted-stage inference (fast loop) and the nightly retrain/recalibrate batch, publishing
results to Home Assistant over MQTT.

## Prerequisites

- **Mosquitto broker** add-on installed and configured. This add-on declares `mqtt:need` and
  will exit on start if no MQTT service is available.
- Host architecture **amd64** (the add-on is amd64-only).

## Configuration

Set these on the **Configuration** tab.

| Option | Default | Notes |
|---|---|---|
| `log_level` | `info` | `trace`…`fatal` |
| `fast_loop_minutes` | `5` | Inference cadence (1–60) |
| `nightly_retrain_hour` | `3` | Local hour (0–23) for the nightly batch |
| `mqtt_base_topic` | `creek` | Base MQTT topic |
| `publish_prefix` | `creek` | Entity prefix, e.g. `sensor.creek_flood_probability` |
| `min_events_for_ml` | `10` | Stay on the threshold model until ≥ N storms captured |
| `google_floods_api_key` | `""` | Optional (Google Flood status) |
| `wu_api_key` | `""` | Optional (Weather Underground PWS) |
| `nwm_reach_id` | `""` | Optional (National Water Model reach) |
| `upstream_pws_ids` | `[]` | Optional upstream PWS station IDs |
| `stage_entity` | `sensor.creek_stage` | Creek node (ESPHome) level — set to the real entity |
| `soil_moisture_entities` | WH51 #1, #2 | `..._soil_moisture_1` (near house / willow), `_2` (near creek) |
| `onsite_rain_rate_entity` | `sensor.outside_weather_station_rain_rate` | Ecowitt |
| `onsite_rain_daily_entity` | `sensor.outside_weather_station_daily_rain` | Ecowitt |

## How it talks to Home Assistant

- **Reads** entity states through the Supervisor proxy at `http://supervisor/core/api`,
  authenticated by the injected `SUPERVISOR_TOKEN` — no long-lived token needed
  (`homeassistant_api: true`).
- **Writes** `creek/flood_probability`, `creek/predicted_crest`, `creek/lag_estimate`, and
  `creek/model_health` over MQTT (broker discovered via services). Add matching HA MQTT
  sensors (see `ha-packages/creek_warning.yaml`) to surface them as entities for the alert
  automations.

## Persistent storage (`/data`)

```text
/data/datasets/dataset.parquet   nightly-appended feature/label rows
/data/events.sqlite              annotated storm event log
/data/models/registry.json       versioned artifacts + skill metrics
```

## Status

Phase 2 **skeleton**: validates the Supervisor proxy + MQTT wiring, builds live features
(stage, rate-of-rise, soil moisture + ponding flag), and returns a transparent conservative
**threshold** estimate. Gradient-boosting inference and nightly retrain land in Phase 4 behind
the same interfaces (`app/model.py`).

> **Calibration note:** WH51 soil-moisture readings are relative (0–100 %) and site-specific.
> The saturated/dry endpoints need field calibration (open question #7) before the ponding
> threshold and Tier 0 condition are meaningful.

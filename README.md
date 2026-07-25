# Creek Flood Early-Warning System

A DIY flood early-warning system for a property mid-watershed on Ackerly Creek (Lackawanna County, PA) — built on Home Assistant, ESPHome, and a radar-based stream gauge, with a roadmap toward predictive flood-probability modeling.

There is no official USGS gauge on this creek. This project instruments the creek directly and fuses that reading with upstream rainfall, soil saturation, forecast precipitation, and National Water Model data to give advance warning before water rises — motivated by a prior basement flood at the property.

## How it works

1. **Instrument** — An 80 GHz FMCW radar sensor (DFRobot SEN0676) mounted above the creek measures water level to ±5 mm, reporting over Modbus RTU to an ESP32-C6 running ESPHome. The node is solar-powered and reports over WiFi, with an adaptive fast-reporting mode that kicks in during rapid rate-of-rise.
2. **Ingest** — Home Assistant pulls in upstream rain-gauge data, NWS/NOAA forecasts, National Water Model reach data, and soil-moisture readings (Ecowitt WH51 probes), alongside the creek-level telemetry.
3. **Correlate & predict** — A local modeling service (Home Assistant add-on) builds a nightly dataset of storm events, starting with threshold-based alerts and evolving into a trained model that outputs flood probability with lead time.
4. **Alert** — A four-tier alert system (Advisory / Watch / Warning / Emergency) with hysteresis notifies the household, force-promoted to at least Watch level on any official NWS flood warning for the county.

## Repo structure

```
esphome/          ESPHome firmware config for the creek sensor node
ha-packages/      Home Assistant package YAML (sensors, templates, automations)
dashboards/       Lovelace dashboards (flood-watch + operator console)
creek_modeling/   HA add-on: nightly dataset builder + prediction service
docs/             Project docs, including open questions and decisions log
repository.yaml   Marks the repo as an installable HA add-on store
creek-flood-warning-spec.md   Source-of-truth project specification
```

## Hardware

-[DFRobot SEN0676](https://www.dfrobot.com/product-2959.html) 80 GHz FMCW radar water-level sensor
- ESP32-C6 (ESPHome)
- Solar panel + LiPo battery + Adafruit solar charger
- Ecowitt weather station + WH51 soil moisture probes
- Home Assistant OS on a mini PC

## Status

Actively being built in phases: instrument → ingest → collect & correlate → predict → harden. See [creek-flood-warning-spec.md](./creek-flood-warning-spec.md) for the full spec and [docs/open-questions.md](./docs/open-questions.md) for items still being resolved.

## Disclaimer

This is a personal, best-effort early-warning aid, not a substitute for official NWS/NOAA flood warnings. Do not rely on it as your sole source of flood safety information.

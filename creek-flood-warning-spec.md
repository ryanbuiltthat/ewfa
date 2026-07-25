# Ackerly Creek Flood Early-Warning System — Project Specification

**Owner:** Ryan
**Location:** Glenburn Township, Lackawanna County, PA (41.5237, -75.7304), mid-watershed on Ackerly Creek
**Motivation:** Prior 100-year storm event caused 40" of basement flooding. Goal is a tiered early-warning system that predicts flood *probability* before water rises — not just threshold alarms.

---

## 1. Watershed Context

- Ackerly Creek: ~8.7 mi long, ~18 mi² basin, flows NW from headwaters swamp in South Abington Twp through Waverly, Glenburn, Dalton, joining South Branch Tunkhannock Creek at La Plume.
- Sensor site is mid-watershed; upstream drainage (~half the basin) lies SE toward Chinchilla / Clarks Summit / South Abington.
- **No official gauge exists on Ackerly Creek.** USGS 01533960 (East Benton) and 01533970 (Dalton) are water-quality sites only. Active continuous gauges — USGS 01533990 (SB Tunkhannock at Bardwell), USGS 01534000 (Tunkhannock Creek nr Tunkhannock), SRBC CIM at La Plume — are all *downstream*; useful for validation only.
- Flashy small basin: expected rainfall-to-crest lag is likely tens of minutes to a few hours. This lag is the warning window; empirically measuring it is a core project outcome.
- Regional hazard note: NEPA rain-on-snow events are a major flood driver; snowpack state must be a model input (via SNODAS data, no hardware).

## 2. Hardware (on hand unless noted)

| Component | Role | Status |
|---|---|---|
| DFRobot SEN0676 (80 GHz FMCW radar, ±5 mm, ±3° lens, 0.15–40 m, UART Modbus RTU, 3.5–5 V, ~30 mA) | Primary creek level | **To purchase** |
| ESP32-C6 | Creek node MCU, ESPHome, WiFi to outdoor AP on back deck | On hand |
| SparkFun LiPo fuel gauge + Adafruit solar/DC charger + panel + LiPo | Creek node power | On hand |
| Ecowitt weather station (uploads to Weather Underground) | On-site rain, temp, wind | Installed |
| Ecowitt WH51 soil moisture ×2 | Antecedent wetness | **Ordered** |
| Aluminum pole on large cherry tree at water's edge, guy-wired above | Sensor mount | To build |
| Submersible pressure transducer (4–20 mA, stilling pipe) | Dissimilar-redundancy backup level sensor | Future phase |
| Creek camera (solar WiFi or PoE) | Visual confirmation, storm archive | Future phase |

### Mounting geometry (from low-water surface = 0)
- Bank top: +3 ft. Design flood: +7 ft (4 ft overbank). Sensor blanking zone: 0.15 m.
- **Mount sensor face 9–10 ft above low water** (~6–7 ft above bank). Arm reaches ~mid-channel (~5 ft). Plumb the sensor (±3° beam; verify with bubble level). Rigidity matters: pole sway = level noise.

### Creek node firmware (ESPHome)
- SEN0676 on hardware UART, Modbus RTU polling.
- Report level every 30–60 s normal; consider adaptive fast mode (5–10 s) when rate-of-rise exceeds threshold.
- Also report: battery voltage (fuel gauge), WiFi RSSI, uptime.
- Sensor powered from clean 5 V rail (boost/buck from battery — sensor needs 3.5–5 V).

## 3. Data Sources & APIs

| Source | Registration | Use |
|---|---|---|
| ESPHome creek node | — (native HA API) | Real-time stage; the ground truth |
| Ecowitt local integration in HA | — | Real-time on-site rain, soil moisture (WH51) |
| Weather.com / WU PWS API | Key already held (via Ecowitt→WU upload; key in WU member settings) | Upstream neighbor PWS rainfall: Clarks Summit / South Abington / Chinchilla / Waverly corridor. **Task: enumerate and select 3–5 upstream stations by ID.** |
| NWS `api.weather.gov` | None (User-Agent header) | Gridded QPF (forecast precip) for 41.5237,-75.7304; active Flood Watch/Warning products for Lackawanna County |
| NOAA NWPS API `api.water.noaa.gov/nwps/v1` | None | National Water Model reach forecast for Ackerly Creek segment (**task: resolve NWM/NHDPlus reach ID**); downstream gauges 01533990 / 01534000 for validation |
| USGS Water Services | None | Instantaneous values, downstream gauges |
| Google Flood Forecasting API `floodforecasting.googleapis.com` | Google Cloud project + enable API + API key (pilot signup may apply) | `gauges:searchGaugesByArea` over watershed polygon → find real/virtual (hybas) gauges incl. non-quality-verified; gauge model thresholds (warning/danger/extreme); flood status; `v1.flashFloods` |
| SNODAS (NOHRSC) | None | Snow water equivalent for grid cell — rain-on-snow feature |

## 4. Architecture

```
[Creek node: C6 + SEN0676 + solar] --WiFi/ESPHome API--> [Home Assistant (mini PC)]
[Ecowitt GW: rain, WH51 soil] --local--> [HA]
[WU PWS / NWS / NWPS / USGS / Google Floods / SNODAS] --REST sensors--> [HA]
[HA recorder / InfluxDB] <----> [Modeling service (Docker container or HAOS add-on)]
[Modeling service] --MQTT--> [HA: flood_probability, predicted_crest, lag_estimate, model_health]
[HA automations] --> alert tiers --> mobile notifications / TTS / etc.
```

**Layer 1 — HA package** (`packages/creek_warning.yaml`): ESPHome entities, REST sensors per API, template sensors (rate-of-rise in/min, 1/6/24/72-h rain accumulations, Antecedent Precipitation Index), alert automations, sensor-fault watchdogs (stale data, radar/pressure divergence when transducer added).

**Layer 2 — Modeling service** (Python, containerized; add-on if HA install type supports it — *open question: HAOS vs Container on the mini PC*):
- **Fast loop (5 min):** compute flood probability + predicted stage from live features; publish via MQTT.
- **Nightly batch:** append day's data to dataset (Parquet/SQLite), recalibrate/retrain, version model artifact, log skill metrics (hit rate, false alarms, lead time), publish model_health.
- Post-storm: manual review + model promotion step.
- Compute: mini PC CPU is sufficient. **Explicitly out of scope: Pi5/Hailo-8 or any NPU** (tabular model, trains in seconds). Revisit only if a creek camera + Frigate vision analytics is added later.

**Layer 3 — HACS custom integration** (end state, after model proves out): config flow UI for API keys, station IDs, thresholds, alert tier tuning. Do not build before Phase 4.

## 5. Model Approach

- Target: creek stage (and/or exceedance probability of tier thresholds) at +30 min, +1 h, +3 h horizons.
- Features: current stage, rate-of-rise, on-site + upstream rain accumulations (1/3/6/24/72 h), API/soil moisture (WH51), QPF next 6/24 h, NWM reach forecast, Google flood status, season, SNODAS SWE, temperature (rain-on-snow flag).
- Start simple → escalate only as data justifies: (1) empirical lag + linear rainfall-runoff response conditioned on soil moisture; (2) gradient boosting (XGBoost/LightGBM) once ≥ ~10 significant rain events are captured; (3) revisit later.
- Honest constraint: no meaningful model tuning until several storms are recorded. Early months = data collection + threshold-based alerting only.

## 6. Alert Tiers

| Tier | Trigger basis | Example condition (tune with data) |
|---|---|---|
| 0 Advisory | Forecast risk | QPF ≥ X" in 24 h AND soil moisture ≥ Y% |
| 1 Watch | Upstream rain materializing | Upstream PWS accumulation ≥ X" in Y h, creek not yet responding |
| 2 Warning | Creek responding | Stage ≥ A ft OR rate-of-rise ≥ B in/min sustained C min |
| 3 Emergency | Flood in progress / imminent | Stage ≥ bank − margin OR model P(overbank) ≥ threshold |

Each tier maps to escalating HA actions (notification → persistent alarm → wake-the-house). Include an "all-clear" state and hysteresis to prevent flapping. NWS Flood Warning for the county force-promotes to ≥ Tier 1.

## 7. Phases & Deliverables

**Phase 1 — Instrument (weekend 1–2):**
ESPHome YAML for creek node (SEN0676 Modbus, power telemetry, adaptive reporting); pole/arm install per §2 geometry; WH51 probes into Ecowitt; verify long-term statistics recording in HA.

**Phase 2 — Ingest (weeks 1–4, parallel):**
`packages/creek_warning.yaml` with all REST sensors; enumerate upstream WU station IDs; resolve NWM reach ID; register Google Floods API and run `searchGaugesByArea` over the watershed; SNODAS fetch; data-quality watchdogs.

**Phase 3 — Collect & correlate (months 1–3):**
Nightly dataset builder; storm event log (annotated); first lag/response estimates; threshold-based Tier 2/3 alerts live (conservative values); downstream-gauge sanity comparisons.

**Phase 4 — Predict (after ~10 events):**
Fast-loop inference service; model registry + nightly retrain; tier logic upgraded from thresholds to probability; skill dashboard (lead time achieved, false alarm rate).

**Phase 5 — Harden & polish:**
Pressure-transducer redundancy + divergence alarm; creek camera; HACS integration with config flow; documentation/runbook.

## 8. Conventions & Environment

- Dev environment: Windows, Git Bash, VS Code + Claude Code; corporate SSL notes apply on work machine only — prefer home environment for this repo.
- ESPHome-first for all firmware; YAML in-repo; consistent with existing fleet (16-ch CT power meter, etc.).
- HA config as packages under version control; secrets via `secrets.yaml` / HA credentials — never committed.
- Modeling service: Python 3.11+, containerized, single `docker-compose.yml`, data in Parquet + SQLite, MQTT for HA interface.
- Every automation that can wake the family must be testable via a dry-run script/service.

## 9. Open Questions (resolve in Phase 1–2)

1. HA install type on mini PC (HAOS/Supervised → add-on path; Container → sidecar docker-compose path).
2. Google Floods API: does a virtual gauge (hybas) land on Ackerly Creek or nearest SB Tunkhannock reach? What are its thresholds?
3. NWM reach ID for the Ackerly segment at 41.5237,-75.7304.
4. Which 3–5 upstream PWS stations are reliable (uptime, tipping-bucket quality)?
5. Exact low-water reference datum and surveyed bank height at the sensor site (measure at install).
6. WiFi RSSI at the pole via the outdoor AP (bag test before final mount).

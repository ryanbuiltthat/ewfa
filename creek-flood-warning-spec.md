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
| Ecowitt WH51 soil moisture ×2 | Antecedent wetness | **Installed (×2)** |
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

**Layer 1 — HA package** (`ha-packages/creek_warning.yaml`): ESPHome entities, REST sensors per API, template sensors (rate-of-rise in/min, 1/6/24/72-h rain accumulations, Antecedent Precipitation Index), alert automations, sensor-fault watchdogs (stale data, radar/pressure divergence when transducer added).

**Layer 2 — Modeling service** (Python, containerized as a **local Home Assistant add-on** — HA install is HAOS; see [Addendum A](#addendum-a--modeling-service-as-a-haos-add-on-resolves-open-question-1)):
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
ESPHome YAML for creek node (SEN0676 Modbus, power telemetry, adaptive reporting); pole/arm install per §2 geometry; ~~WH51 probes into Ecowitt~~ **done (×2 installed)**; verify long-term statistics recording in HA.

- **Follow-up:** Confirm WH51 entities appear in HA via the Ecowitt integration and are captured in recorder long-term statistics (check `state_class`); these feed the nightly dataset builder.

**Phase 2 — Ingest (weeks 1–4, parallel):**
`ha-packages/creek_warning.yaml` with all REST sensors; enumerate upstream WU station IDs; resolve NWM reach ID; register Google Floods API and run `searchGaugesByArea` over the watershed; SNODAS fetch; data-quality watchdogs.

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
- Modeling service: Python 3.11+, packaged as a **local HAOS add-on** (`config.yaml` + `Dockerfile` + `run.sh`), data in Parquet + SQLite under `/data`, MQTT for HA interface. See [Addendum A](#addendum-a--modeling-service-as-a-haos-add-on-resolves-open-question-1).
- Every automation that can wake the family must be testable via a dry-run script/service.
- Frontend: any custom Lovelace cards / flood dashboard follow the HA design system — design tokens (no hardcoded colors), light/dark parity, WCAG AA contrast, `<ha-card>` + MDI icons, responsive breakpoints. Ref: <https://design.home-assistant.io/>. (No frontend exists yet; applies when the dashboard/cards land — see Phase 5. Reuse the Prism theme where possible.)

## 9. Open Questions (resolve in Phase 1–2)

1. ~~HA install type on mini PC (HAOS/Supervised → add-on path; Container → sidecar docker-compose path).~~ **RESOLVED: HA install is HAOS.** Layer 2 modeling service is built as a local add-on — see [Addendum A](#addendum-a--modeling-service-as-a-haos-add-on-resolves-open-question-1).
2. Google Floods API: does a virtual gauge (hybas) land on Ackerly Creek or nearest SB Tunkhannock reach? What are its thresholds?
3. NWM reach ID for the Ackerly segment at 41.5237,-75.7304.
4. Which 3–5 upstream PWS stations are reliable (uptime, tipping-bucket quality)?
5. Exact low-water reference datum and surveyed bank height at the sensor site (measure at install).
6. WiFi RSSI at the pole via the outdoor AP (bag test before final mount).
7. WH51 readings are relative (0–100%) and site-specific. After the next soaking rain and a dry stretch, record the empirical "saturated" and "dry" values at each burial spot; these calibrate the Tier 0 soil-moisture threshold.

---

## Addendum A — Modeling service as a HAOS add-on (resolves Open Question #1)

**Decision:** The Home Assistant install on the mini PC is **HAOS** (Home Assistant Operating System, Supervisor-managed). The Layer 2 modeling service is therefore built as a **local add-on**, not a sidecar `docker-compose` service. This addendum supersedes the "Docker container *or* HAOS add-on" hedge in §4 and the `docker-compose.yml` note in §8.

### A.1 Why add-on over sidecar Container

- HAOS does not expose the host Docker socket for user compose stacks; add-ons are the supported way to run custom containers on HAOS.
- The Supervisor provides, for free, exactly the plumbing this service needs: an authenticated **proxy to the HA Core API** (no long-lived token to mint or rotate), **MQTT service discovery** (broker host/credentials injected at runtime), managed lifecycle (auto-start, restart, logs, watchdog), and a **persistent `/data` volume** that survives add-on updates.
- Config UI comes for free: the `schema` block renders a form in **Settings → Add-ons**, so API keys and thresholds are edited in the HA UI instead of a `.env` file. This is a natural stepping-stone toward the Layer 3 HACS integration's config flow (§4).

### A.2 Add-on layout

The add-on **source** lives in the repo at `creek_modeling/` (per the README repo structure).
Preferred install is via the **Git-based add-on repository** (add the repo URL in
**Settings → Add-ons → Add-on Store → ⋮ → Repositories**), which enables GUI install and
versioned updates. It can also run as a **local add-on**: copy that folder into the HAOS
`/addons/` directory as `/addons/creek_modeling/` (via the Samba or SSH add-on, or
`addon_config`), where it appears under **Settings → Add-ons → Local add-ons**. (Repo dir =
`creek_modeling/`; local install target = `/addons/creek_modeling/` — same files.)

```text
modeling/                # repo source (installs to HAOS /addons/creek_modeling/)
├── config.yaml          # add-on manifest + options schema
├── build.yaml           # per-arch BUILD_FROM (Debian base)
├── Dockerfile           # build recipe (HA base image + Python deps)
├── run.sh               # entrypoint (bashio: read options, export env, exec service)
├── requirements.txt     # pandas, pyarrow, xgboost/lightgbm, paho-mqtt, requests, ...
├── icon.png / logo.png  # optional, for the add-on store card
└── app/                 # the modeling service itself
    ├── __main__.py      # fast loop (5 min) + nightly batch scheduler
    ├── config.py        # options.json + env loader
    ├── features.py      # feature builders (rate-of-rise, APIndex, accumulations)
    ├── model.py         # train / infer / registry
    ├── dataset.py       # Parquet feature rows + SQLite storm-event log
    ├── ha.py            # HA Core API client (Supervisor proxy)
    └── mqtt_client.py   # MQTT publisher for model outputs
```

### A.3 `config.yaml` manifest (with options schema)

```yaml
name: Ackerly Creek Modeling
version: "0.1.0"
slug: creek_modeling
description: Flood-probability + predicted-stage inference and nightly retrain for Ackerly Creek.
url: https://github.com/ryanbuiltthat/ewfa
arch:
  - amd64          # mini PC; add aarch64 only if the host changes
startup: application # start after HA Core is up (needs the API + MQTT)
boot: auto
init: false          # s6-overlay from the base image is the init; run.sh is the service

# --- Supervisor-granted capabilities ---
homeassistant_api: true   # proxy to Core REST API at http://supervisor/core/api
hassio_api: true          # (optional) Supervisor API, e.g. to read add-on/service info
auth_api: false
services:
  - mqtt:need             # auto-discover the Mosquitto broker; creds injected at runtime
map:
  - addon_config:rw       # optional: human-editable configs/notes outside /data
  - share:rw              # optional: drop Parquet exports where other tools can read them

# --- User-configurable options (rendered as a form in the HA UI) ---
options:
  log_level: info
  fast_loop_minutes: 5
  nightly_retrain_hour: 3
  mqtt_base_topic: creek
  publish_prefix: creek          # -> sensor.creek_flood_probability, etc.
  min_events_for_ml: 10          # gate: threshold model until >= N storms captured
  google_floods_api_key: ""
  wu_api_key: ""
  nwm_reach_id: ""
  upstream_pws_ids: []

schema:
  log_level: list(trace|debug|info|notice|warning|error|fatal)
  fast_loop_minutes: int(1,60)
  nightly_retrain_hour: int(0,23)
  mqtt_base_topic: str
  publish_prefix: str
  min_events_for_ml: int(1,100)
  google_floods_api_key: password?
  wu_api_key: password?
  nwm_reach_id: str?
  upstream_pws_ids:
    - str
```

Notes:

- `password?` masks secrets in the UI and marks them optional; keys live in Supervisor-managed options, not in a committed file (consistent with §8's "never commit secrets").
- `services: [mqtt:need]` makes the add-on refuse to start unless an MQTT broker (Mosquitto add-on) is present, and injects host/port/user/pass via `bashio::services mqtt`.
- No `ports:` are published — the service is headless and talks out via MQTT + the Supervisor API proxy. Add a `ports`/`ingress` block later only if a debug/status web UI is wanted.

### A.4 `Dockerfile`

Use the Debian add-on base image (Alpine/musl makes `xgboost`/`lightgbm`/`pandas` wheels painful); it ships `bashio`, `s6-overlay`, and `tempio`.

```dockerfile
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip python3-venv libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --break-system-packages -r /tmp/requirements.txt

COPY run.sh /run.sh
COPY app/ /app/
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
```

(`libgomp1` is the OpenMP runtime XGBoost/LightGBM link against.) `BUILD_FROM` is overridden per-arch by Supervisor at build time via a `build.yaml`, but pinning amd64 as the default is fine for a single mini PC.

### A.5 `run.sh` (entrypoint)

```bash
#!/usr/bin/with-contenv bashio
set -euo pipefail

# --- Options → environment ---
export LOG_LEVEL="$(bashio::config 'log_level')"
export FAST_LOOP_MINUTES="$(bashio::config 'fast_loop_minutes')"
export NIGHTLY_RETRAIN_HOUR="$(bashio::config 'nightly_retrain_hour')"
export MQTT_BASE_TOPIC="$(bashio::config 'mqtt_base_topic')"
export PUBLISH_PREFIX="$(bashio::config 'publish_prefix')"
export MIN_EVENTS_FOR_ML="$(bashio::config 'min_events_for_ml')"
export GOOGLE_FLOODS_API_KEY="$(bashio::config 'google_floods_api_key')"
export WU_API_KEY="$(bashio::config 'wu_api_key')"
export NWM_REACH_ID="$(bashio::config 'nwm_reach_id')"

# --- HA Core API via the Supervisor proxy (no long-lived token needed) ---
export HA_API_URL="http://supervisor/core/api"
export SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"   # injected by Supervisor

# --- MQTT from the Mosquitto add-on via service discovery ---
if bashio::services.available "mqtt"; then
  export MQTT_HOST="$(bashio::services 'mqtt' 'host')"
  export MQTT_PORT="$(bashio::services 'mqtt' 'port')"
  export MQTT_USER="$(bashio::services 'mqtt' 'username')"
  export MQTT_PASS="$(bashio::services 'mqtt' 'password')"
else
  bashio::exit.nok "No MQTT service available — install/configure the Mosquitto add-on."
fi

# --- Persistent storage (survives add-on updates/restarts) ---
export DATA_DIR="/data"          # dataset.parquet, events.sqlite, model registry
mkdir -p "${DATA_DIR}/models" "${DATA_DIR}/datasets"

bashio::log.info "Starting Ackerly Creek modeling service (fast loop ${FAST_LOOP_MINUTES}m)…"
exec python3 -m app
```

### A.6 HA access via the Supervisor proxy

Because `homeassistant_api: true` is set, the container reaches HA Core at `http://supervisor/core/api`, authenticating with the `SUPERVISOR_TOKEN` env var that Supervisor injects — **no user-created long-lived access token is required or stored.**

```python
# app/ha.py  (sketch)
import os, requests
_HDRS = {"Authorization": f"Bearer {os.environ['SUPERVISOR_TOKEN']}",
         "Content-Type": "application/json"}
def get_state(entity_id: str):
    r = requests.get(f"{os.environ['HA_API_URL']}/states/{entity_id}",
                     headers=_HDRS, timeout=10)
    r.raise_for_status()
    return r.json()
```

Live inputs (current stage, on-site/upstream rain, soil moisture, QPF/NWM/SNODAS REST sensors from Layer 1) are read either from Core states via this proxy **or**, for history/backfill, from the recorder/InfluxDB as before. Outputs (`flood_probability`, `predicted_crest`, `lag_estimate`, `model_health`) are **published over MQTT** using the discovered broker — matching the §4 architecture diagram — so HA sees them as MQTT sensors and the alert automations (§6) fire off those entities.

### A.7 Persistent storage layout (`/data`)

Supervisor bind-mounts a per-add-on volume at `/data` that persists across restarts and add-on updates; `/data/options.json` holds the current options (already parsed by `bashio::config`). The service owns the rest:

```text
/data/
├── options.json                 # (managed by Supervisor)
├── datasets/
│   └── dataset.parquet          # nightly-appended feature/label rows (§4 batch)
├── events.sqlite                # annotated storm event log (§7 Phase 3)
├── models/
│   ├── registry.json            # versioned artifacts + skill metrics (hit rate, FA, lead time)
│   └── model-<version>.pkl      # promoted artifacts (§4 post-storm promotion)
└── state/
    └── last_run.json            # fast-loop / nightly-batch bookkeeping
```

This satisfies §4's "append day's data to dataset (Parquet/SQLite), version model artifact" and §7's storm event log without any external volume.

### A.8 Impact on phases

- **Phase 2 (Ingest):** unchanged in scope; the add-on skeleton (`config.yaml`/`Dockerfile`/`run.sh` + a no-op fast loop that just logs) can be stood up here to validate the Supervisor proxy + MQTT wiring before any modeling exists.
- **Phase 4 (Predict):** the fast-loop inference service and nightly retrain land inside this add-on; `min_events_for_ml` gates the threshold→ML transition (§5) via an option, no rebuild required.
- **Build/CI:** local-add-on iteration needs no registry; when promoting to a Git add-on repo, reuse the existing ESPHome-fleet GitHub Actions pattern (§8) to lint (`config.yaml`) and build the image per push.

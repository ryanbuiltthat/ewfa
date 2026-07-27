# Ackerly Creek Flood Early-Warning System — Project Specification

**Owner:** Ryan
**Location:** Glenburn Township, Lackawanna County, PA (41.5237, -75.7304), mid-watershed on Ackerly Creek
**Motivation:** Prior 100-year storm event caused 40" of basement flooding. Goal is a tiered early-warning system that predicts flood *probability* before water rises — not just threshold alarms.

---

## 1. Watershed Context

- Ackerly Creek: ~8.7 mi long, ~18 mi² basin, flows NW from headwaters swamp in South Abington Twp through Waverly, Glenburn, Dalton, joining South Branch Tunkhannock Creek at La Plume.
- Sensor site is mid-watershed; upstream drainage (~half the basin) lies SE toward Chinchilla / Clarks Summit / South Abington.
- **No official gauge exists on Ackerly Creek.** USGS 01533960 (East Benton) and 01533970 (Dalton) are water-quality sites only. ~~USGS 01533990 (SB Tunkhannock at Bardwell)~~ **does not exist** — NWIS returns "no sites found" for that number; it was a bad ID, not a retired gauge. The nearest gauges that actually publish continuous instantaneous values are:
  - **USGS 01534860** — Lackawanna River below Leggetts Creek at Scranton (~7 mi SE). Adjacent basin, but Leggetts Creek drains the same Clarks Summit / Chinchilla / South Abington upland that forms Ackerly's upstream half, so it sees substantially the same rain. Best available response analog.
  - **USGS 01534000** — Tunkhannock Creek nr Tunkhannock (~11 mi W). The receiving system downstream of the confluence; much larger drainage, longer lag.
  - SRBC CIM at La Plume — downstream.

  All are off-basin or downstream: useful for validation and for empirically estimating the rainfall→response lag, never as a stand-in for creek stage.
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
| Weather.com / WU PWS API | Key already held (via Ecowitt→WU upload; key in WU member settings) | Upstream neighbor PWS rainfall: Clarks Summit / South Abington / Chinchilla / Waverly corridor. Stations in use: `KPAGLENB2`, `KPACLARK41` (open question #4 — 2 of the 3–5 wanted). |
| NWS `api.weather.gov` | None (User-Agent header) | Gridded QPF (forecast precip) for 41.5237,-75.7304; active Flood Watch/Warning products for Lackawanna County |
| NOAA NWPS API `api.water.noaa.gov/nwps/v1` | None | National Water Model reach forecast for the Ackerly Creek segment — reach `4196026` (open question #3, resolved) |
| USGS Water Services | None | Instantaneous values — gauges 01534860 (Lackawanna bl Leggetts Ck) and 01534000 (Tunkhannock Ck); see §1 |
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

Implemented in `creek_modeling/app/tiers.py`, which emits the four escalation tiers below
*plus* the explicit all-clear this section calls for — so the published scale is 0–4, with
the tier number one higher than this table's original 0–3 numbering:

| Level | Tier | Trigger basis | Example condition (tune with data) | Needs the creek gauge? |
|---|---|---|---|---|
| 0 | All-clear | Nothing elevated | — | — |
| 1 | Advisory | Forecast risk | QPF ≥ X" in 24 h AND soil moisture ≥ Y% | No |
| 2 | Watch | Upstream rain materializing | Upstream PWS accumulation ≥ X" in Y h, creek not yet responding | No |
| 3 | Warning | Creek responding | Stage ≥ A ft OR rate-of-rise ≥ B in/min sustained C min | Yes |
| 4 | Emergency | Flood in progress / imminent | Stage ≥ bank − margin OR model P(overbank) ≥ threshold | Yes |

Advisory and Watch are deliberately gauge-independent: they run off forecast and rainfall
features that flow without the creek node, so the system warns during the wait for the
SEN0676. Warning and Emergency stay dormant until the node reports stage. Each tier also
publishes the reasons that fired it.

Original table, retained for reference:

| Tier | Trigger basis | Example condition (tune with data) |
|---|---|---|
| 0 Advisory | Forecast risk | QPF ≥ X" in 24 h AND soil moisture ≥ Y% |
| 1 Watch | Upstream rain materializing | Upstream PWS accumulation ≥ X" in Y h, creek not yet responding |
| 2 Warning | Creek responding | Stage ≥ A ft OR rate-of-rise ≥ B in/min sustained C min |
| 3 Emergency | Flood in progress / imminent | Stage ≥ bank − margin OR model P(overbank) ≥ threshold |

Each tier maps to escalating HA actions (notification → persistent alarm → wake-the-house). Include an "all-clear" state and hysteresis to prevent flapping. NWS Flood Warning for the county force-promotes to ≥ Tier 1.

## 7. Phases & Deliverables

**Phase 1 — Instrument (weekend 1–2):**
~~ESPHome YAML for creek node (SEN0676 Modbus, power telemetry, adaptive reporting)~~
**done** (`esphome/creek_node.yaml` — reads the raw distance register and converts to stage
on the node, so the datum stays a re-settable HA number while open question #5 is open;
adaptive 60 s → 5 s on rate-of-rise, held 10 min. **Written against the datasheet and never
run on hardware** — `esphome/README.md` carries the bench-test procedure, which must come
before the pole install); pole/arm install per §2 geometry; ~~WH51 probes into Ecowitt~~ **done (×2 installed)**; verify long-term statistics recording in HA.

- **Follow-up:** Confirm WH51 entities appear in HA via the Ecowitt integration and are captured in recorder long-term statistics (check `state_class`); these feed the nightly dataset builder.

**Phase 2 — Ingest (weeks 1–4, parallel):**
`ha-packages/creek_warning.yaml` with all REST sensors; enumerate upstream WU station IDs; resolve NWM reach ID; register Google Floods API and run `searchGaugesByArea` over the watershed; SNODAS fetch; data-quality watchdogs.

**Phase 3 — Collect & correlate (months 1–3):**
~~Nightly dataset builder~~ **done** (`app/dataset.py`: per-day JSONL parts, consolidated
nightly into Parquet); ~~storm event log (annotated)~~ **done** (`app/storms.py`, events
defined by rainfall so the record stays valid once the gauge lands); ~~first lag/response
estimates~~ **done** (`app/lag.py`, cross-correlation); ~~threshold-based alerts live
(conservative values)~~ **done** (`app/tiers.py`, Phase 2 — and the forecast-driven tiers
run without the gauge); ~~downstream-gauge sanity comparisons~~ **done** (lag falls back to
USGS and labels itself as a proxy).

What Phase 3 still needs is **time, not code**: storms have to actually happen. The lag
estimate stays a USGS-proxy number until the SEN0676 is mounted, and the thresholds
throughout stay uncalibrated until the storm log has entries to fit against.

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
3. ~~NWM reach ID for the Ackerly segment at 41.5237,-75.7304.~~ **RESOLVED: `4196026`** (reach position 41.5235,-75.7293, ~100 m from the site; verified live against the NWPS API).
4. ~~Which 3–5 upstream PWS stations are reliable (uptime, tipping-bucket quality)?~~ **PARTLY RESOLVED: `KPAGLENB2`, `KPACLARK41`.** Two of the 3–5 wanted; add more from the Chinchilla / South Abington / Waverly corridor as reliable ones are identified.
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
export DATA_DIR="/data"          # dataset.parquet, model registry, accumulator state
mkdir -p "${DATA_DIR}/models" "${DATA_DIR}/datasets"
export SHARE_DIR="/share"        # events.sqlite — hand-annotated, so not add-on-private
mkdir -p "${SHARE_DIR}/creek_modeling"

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
├── models/
│   ├── registry.json            # versioned artifacts + skill metrics (hit rate, FA, lead time)
│   └── model-<version>.pkl      # promoted artifacts (§4 post-storm promotion)
└── state/
    └── last_run.json            # fast-loop / nightly-batch bookkeeping
```

The storm event log is the one exception, and lives in the shared volume instead:

```text
/share/creek_modeling/events.sqlite   # annotated storm event log (§7 Phase 3)
```

`/data` is private to each add-on, which makes it the wrong home for the only file the
project expects a *human* to edit: the documented `sqlite3 /data/events.sqlite` typed in
the SSH/Terminal add-on opens that add-on's own empty `/data`, succeeding while annotating
nothing. `/share` resolves identically from every add-on and is exported over Samba, so one
path works from a terminal or a GUI SQLite browser. A log left in `/data` by an earlier
version is migrated on first start, and `/data` remains the fallback if `/share` is
unavailable.

This satisfies §4's "append day's data to dataset (Parquet/SQLite), version model artifact" and §7's storm event log without any external volume.

### A.8 Impact on phases

- **Phase 2 (Ingest):** unchanged in scope; the add-on skeleton (`config.yaml`/`Dockerfile`/`run.sh` + a no-op fast loop that just logs) can be stood up here to validate the Supervisor proxy + MQTT wiring before any modeling exists.
- **Phase 4 (Predict):** the fast-loop inference service and nightly retrain land inside this add-on; `min_events_for_ml` gates the threshold→ML transition (§5) via an option, no rebuild required.
- **Build/CI:** local-add-on iteration needs no registry; when promoting to a Git add-on repo, reuse the existing ESPHome-fleet GitHub Actions pattern (§8) to lint (`config.yaml`) and build the image per push.

## Addendum B — Flood-watch dashboard + on-demand controls

The headless add-on (no `ingress`/`ports`) is driven and observed entirely over MQTT, so a
single Lovelace dashboard doubles as an operations console during the data-collection phase.
Implemented ahead of its Phase-5 slot because watching ingestion and manually kicking the
pipeline is most useful *now*. Stock cards + the Prism theme; no custom frontend yet (§8).

### B.1 MQTT interface (add-on ⇄ HA)

- **Commands** — HA → add-on, non-retained, `creek/cmd/<name>`:
  `run_inference`, `retrain`, `promote`, `rollback`. The add-on keys off the trailing topic
  segment (payload ignored) and executes on its single loop thread — commands are drained
  between/within the fast-loop sleep, so no two tasks overlap and a press is honored within a
  few seconds.
- **Status** — add-on → HA, retained JSON:
  `creek/status/pipeline` (`state`, `task`, `last_inference_at`, `last_nightly_at`,
  `last_error`), `creek/status/registry` (active/candidate versions + metrics + history,
  `event_count`), and `creek/status/command_result` (echo of each command's outcome,
  non-retained). Outputs `creek/flood_probability`, `predicted_crest`, `lag_estimate`,
  `model_health`, and `creek/alert_tier` (tier + label, §6). Timestamps are tz-aware ISO.
- **Availability** — `creek/status/availability` online/offline, backed by the MQTT LWT, so
  the discovered entities go *unavailable* when the add-on stops.

### B.1a Auto-provisioning via MQTT Discovery

The add-on publishes retained MQTT-discovery configs
(`homeassistant/<component>/creek_modeling/<slug>/config`) for all of its `creek_*` sensors
and command buttons, grouped under an **Ackerly Creek Modeling** device. HA creates/updates
them with no package or `configuration.yaml` edit, and they re-publish on every reconnect so
they track add-on updates. This supersedes the earlier "define them in a HA package" approach.
Because each entity carries a `device` block, HA prefixes the device name when minting entity
IDs — `sensor.ackerly_creek_modeling_creek_flood_probability`.

The soil-moisture mean, the ponding flag and the sensor-fault watchdogs were migrated here
too: the add-on already computed the first two, and it can see source liveness and input
freshness that an HA template cannot. `creek_warning.yaml` is down to the two things that
must stay HA-side — the tier notification automation (it calls `persistent_notification`) and
the add-on's own liveness watchdog, since a service cannot report its own death.

### B.2 Model registry (`/data/models/registry.json`)

`{active, candidate, history[], event_count}` with a `metrics` dict per entry. `promote()`
moves candidate→active (old active pushed to `history`); `rollback()` restores the most
recent history entry and keeps the demoted model as the new candidate. Pointer/metric logic
is live now; loading the `.pkl` artifact stays the Phase-4 stub (§5).

### B.3 HA entities & dashboard

`ha-packages/creek_modeling.yaml` defines the MQTT sensors for every output/status topic,
four MQTT `button` entities for the commands, a placeholder `sensor.creek_alert_tier` (§6),
and sensor-fault "stale" watchdogs (§4). `dashboards/creek_flood_watch.yaml` presents two
views: a glanceable **household** view (tier + probability gauge + creek trend + plain-language
status) and an **operator** view (controls, pipeline/model status, ingestion-health with
staleness, and a candidate-vs-active model review).

### B.4 Later (optional)

An `ingress` log-viewer panel could be added in Phase 5 for raw log tailing; the MQTT
command/status path above stays the primary interface.

## Addendum C — Forecast/upstream ingestion (in the add-on)

Resolves how the §5 features beyond stage/soil are collected. Decision: the add-on fetches
them directly (Python) and publishes each as an MQTT-discovery sensor, rather than HA `rest:`
sensors — consistent with Addendum B (versioned, unit-testable with mocked HTTP,
auto-provisioned, secrets stay in add-on options). These are independent of the creek gauge,
so they proceed while the water-level sensor is pending and enable forecast-based Tiers 0/1.

### C.1 Architecture

`app/sources/` — one module per source, each returning `{feature: float|None}`; a coordinator
merges them into the feature row and respects a per-source refresh interval with last-good
caching (a source that errors returns its cached value / `None`, never crashing the loop).
All rainfall features are normalized to **inches**. The merged features are published on
`creek/features` (one retained JSON) and written into the widened `FeatureRow`/dataset; each
is an MQTT-discovery sensor under the *Ackerly Creek Modeling* device. Location (lat/lon) is
read once from HA `/api/config` — no new option.

### C.2 Sources (delivered in two slices)

- **2a — on-site rain + NWS QPF:**
  - `rain.py` — rolling accumulator: samples `onsite_rain_rate_entity` each fast loop,
    integrates rate×Δt into a 72 h ring persisted under `/data/state/`, and reports
    `rain_{1,3,6,24,72}h_in`. Builds up over the first 72 h from a cold start.
  - `nws.py` — `api.weather.gov` `points/{lat},{lon}` → `forecastGridData` →
    `quantitativePrecipitation` (mm, ISO-interval values); pro-rated into `qpf_6h_in` /
    `qpf_24h_in`. No key; requires a `User-Agent`. Refresh ~15 min.
    Proration runs over each interval's *remaining* time, so the interval already in
    progress contributes its full forecast rather than a share scaled by how much of it
    has elapsed. BGM issues this grid in 6-hour blocks, which makes that interval most of
    a 6 h forecast; prorating it over its full span assumes the un-elapsed remainder has
    already fallen, and decays the number toward zero as a forecast storm approaches.
    Rain that really has fallen is not lost — the on-site gauge measures it as `rain_*_in`.
    **Note the standing limitation:** gridded QPF cannot resolve convection at all. A
    pop-up thunderstorm reads near zero here no matter how it is prorated, so QPF is a
    frontal-rain signal and the on-site rain rate is the only nowcast.
- **2b — upstream + model (done):** `wu.py` (Weather Underground PWS upstream accumulations
  via the shared accumulator, `wu_api_key` + `upstream_pws_ids`) and `nwm.py` (NWPS reach
  short-range streamflow forecast — near-term + peak discharge, `nwm_reach_id`).
- **2c — downstream observations (done):** `usgs.py` (NWIS instantaneous values for the two
  downstream gauges named in §1 — gage height, discharge, and 3 h rise each; free, no key).
  A larger basin with a longer lag, so *not* a creek-level proxy; its value is being the only
  **observed** rainfall→response record available before the creek node exists, which lets the
  Phase-3 lag/response work start against real hydrographs instead of waiting on hardware.

- **2d — NWS alert products (done):** `alerts.py` (active Flood Watch / Flood Warning /
  Flash Flood Warning covering the site, by point rather than county zone). These impose a
  *floor* on the alert tier per §6 — a forecaster issuing a product knows things our
  instruments do not, which matters most while the creek gauge is missing.
- **2e — SNODAS snowpack (done):** `snodas.py` (snow water equivalent for the site's grid
  cell, read straight from the gridded masked product since NOHRSC exposes no point API).
  Combined with temperature into the rain-on-snow flag §1 calls out as a major NEPA driver.
- **2f — Antecedent Precipitation Index (done):** `apindex.py`, an exponentially-decaying
  rainfall memory riding on the on-site rain samples. Complements the two WH51 probes with a
  basin-wide view of how wet the ground already is.

Still to build for Phase 2: **Google Flood Forecasting** (`gauges:searchGaugesByArea`, §3)
— deferred pending API access, and open question #2 stays open with it.

### C.3 Consumption

Ingested features are recorded to the dataset, published on `creek/features`, and — as of
slice 2c — consumed by the tier logic. `app/tiers.py` evaluates §6 against the whole feature
row and emits `0` All-clear · `1` Advisory · `2` Watch · `3` Warning · `4` Emergency (the §6
table plus the explicit all-clear state §6 also calls for), with the reasons that fired.

The design point: **Advisory and Watch are gauge-independent.** Advisory comes from QPF plus
antecedent soil moisture, Watch from upstream/on-site rain accumulation — both already
flowing. So the system issues real warnings during the wait for the SEN0676, while Warning
and Emergency (stage, rate-of-rise) stay dormant until the creek node reports. Feeding these
features into the *model* remains Phase 4, behind the same interfaces.

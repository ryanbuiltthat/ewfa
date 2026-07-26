# Changelog

All notable changes to the **Ackerly Creek Modeling** add-on are documented here.
The version matches `version:` in `config.yaml`; bump it to trigger the GUI Update button.

## 0.11.1

- **Fix the `Creek Modeling Service Stale` watchdog** (`ha-packages/creek_warning.yaml`).
  It inferred liveness from `last_changed` on the pipeline-state entity, which only toggles
  idle/running for a moment each loop — if Home Assistant ever missed that brief transition,
  last_changed froze and the watchdog stuck at Problem indefinitely. It now compares the
  *value* of `creek_last_inference`, which advances every fast loop by construction. Adds a
  `last_inference` attribute so a Problem can be told apart at a glance: entity missing
  versus loop genuinely stalled.
  - This watchdog is the one thing left in the HA package, so it does **not** arrive with an
    add-on update — re-copy `ha-packages/creek_warning.yaml` into your HA config directory.
  - A copy of that file predating 0.6.0 referenced the unprefixed
    `sensor.creek_pipeline_state`, which never existed, so it reported Problem permanently.

## 0.11.0 — Phase 3 (Collect & correlate)

- **Storm event log** (`app/storms.py`, spec §7): detects storms from the live feature
  stream and records them in `events.sqlite` with onset conditions (API, soil moisture,
  SWE, rain-on-snow), running peaks (rain, upstream rain, QPF, stage, rate-of-rise,
  downstream rise, alert tier) and a `notes` column for annotation. Events are defined by
  *rainfall*, not by creek response, so the record being built now stays valid once the
  SEN0676 is mounted — response columns are simply null until then. A brief lull does not
  split one storm in two, and a restart mid-storm resumes the open event.
  - This also makes `min_events_for_ml` meaningful for the first time: the table existed
    but nothing ever wrote to it, so the threshold→ML gate (§5) could never open. The
    nightly batch now sets the registry's event count from completed storms.
- **Nightly dataset builder** (`app/dataset.py`, §4): the fast loop appends to a per-day
  JSONL part file and the nightly batch folds completed parts into `dataset.parquet`.
  Previously every fast loop read the entire Parquet dataset, concatenated one row and
  rewrote it — ~700 ms per append after a year on this schema, but the real cost was
  rewriting the whole dataset 288 times a day onto an SSD. Consolidation is atomic
  (write-temp-then-replace), de-duplicates by timestamp, and survives a torn final line
  from an unclean shutdown without losing the rest of the day.
- **Lag estimation** (`app/lag.py`, §1/§7): cross-correlates rainfall against the response
  series to estimate the rainfall→crest lag §1 calls "the warning window". Correlates on
  first *differences* of the response, since rainfall drives the rise while the level
  itself is dominated by baseflow. Falls back to a USGS downstream gauge while the creek
  node is missing — a different, larger basin, so the result is labelled with the series
  used and must not be read as Ackerly's lag. That fallback is the "downstream-gauge
  sanity comparison" §7 asks for.
  - Near-ties resolve to the *shorter* lag. Storms recur, so shifting rain forward by a
    whole inter-storm interval lines it up with the next storm's rise and scores just as
    well — measurably better, even, since the longer shift drops the worst-fitting edge
    samples. Physically the earliest lag that explains the response is the causal one.
  - Refuses to guess: reports `lag_minutes: null` with a reason when there is too little
    data, no rain on record, or the best correlation is below 0.30.

## 0.10.0

- **Watchdogs and soil templates move into the add-on.** The soil-moisture mean, the ponding
  flag and eight of the nine sensor-fault watchdogs are now computed here and auto-created
  via MQTT discovery, so they need no file copied into the HA config directory and no
  `configuration.yaml` edit. `ha-packages/creek_warning.yaml` shrinks to just the tier
  notification automation (it calls `persistent_notification`, so it has to be HA-side) and
  the add-on's own liveness watchdog — a service cannot report its own death.
- **The watchdogs are also more accurate here**, because the add-on can see two things a
  template could not:
  - *Whether a source is still alive.* The coordinator serves a source's last-good value
    indefinitely, so a feature still holding a number proved nothing — `has_value()` stayed
    true long after an API stopped answering. The coordinator now tracks each source's last
    successful poll and the watchdogs key off that age.
  - *Whether an input entity is reporting.* A rain rate legitimately sitting at 0.00 in/h
    never changes state, so the old `last_changed` check false-alarmed through dry spells
    and stayed quiet when the gauge actually died. The raw rate is now a feature
    (`rain_rate_in_hr`, null when the entity is unavailable) and staleness tracks the last
    usable read.
  - A boot grace period means a cold start no longer lights up every watchdog at once, and
    a source that is switched off is reported as fine rather than permanently missing.
- **Fix: `creek_temperature` and `creek_rain_on_snow` never worked.** Both are derived in
  `FeatureBuilder` rather than by a source, so they were absent from `FEATURE_KEYS` — and
  the `creek/features` payload is built from that tuple, so the two entities referenced
  fields that were never published and sat at unknown from 0.8.0. Derived keys are now
  published explicitly, with a test that fails if any discovery template references a field
  its topic does not carry.

**Upgrade note:** entity IDs for the migrated entities gain the device prefix —
`binary_sensor.creek_stage_stale` becomes
`binary_sensor.ackerly_creek_modeling_creek_stage_stale`, and likewise for the soil mean,
ponding and the other watchdogs. The bundled dashboard is updated. The old entities linger
in the entity registry as unavailable until deleted (Settings → Devices & Services →
Entities, filter Unavailable).

## 0.9.0

- **Antecedent Precipitation Index — ingestion slice 2f** (spec §4/§5): `api_index_in`, an
  exponentially-decaying rainfall memory. It complements the WH51 probes rather than
  duplicating them — those read two buried points, this summarises weeks of rainfall over
  the whole basin, and wet antecedent conditions are what turn an ordinary storm into a
  flood. Needs no creek gauge.
  - Decay is applied as a continuous power of elapsed time, not a discrete daily step, so
    an irregular sampling interval or a restart decays correctly.
  - State is persisted with its timestamp, so downtime decays the index instead of freezing
    it. A gap beyond 14 days restarts from zero rather than carrying a stale value across
    rainfall that was never sampled — being wrong in the direction of *understating*
    wetness is the dangerous one, so it is made explicit rather than silent.
  - Rides on the existing on-site rain samples (the accumulator now exposes its per-update
    increment), so the rain-rate entity is still read once per loop.
- **Tier**: the index gives a second route to Advisory alongside soil moisture — high QPF
  onto a wet basin — so a failed WH51 probe cannot mask saturated ground.

## 0.8.0

- **SNODAS snowpack — ingestion slice 2e** (spec §1/§5): `app/sources/snodas.py` reports
  `snow_water_equivalent_in` for the site's grid cell. NOHRSC publishes no point API (the
  "nearest" page returns HTML whatever `fmt` you ask for), so this reads the gridded masked
  product directly: pull the daily tar, stream the SWE member's gzip to the one cell we
  need, and discard the rest rather than decompressing a 46 MB raster. Grid geometry was
  verified against a real February file — the site cell read 42 mm, ocean and Florida cells
  read no-data, and a Cascades cell saturated. Daily product, so results are cached per date
  under `/data/state/` and the fetch walks back up to 5 days for late or skipped postings.
- **Rain-on-snow flag** — derived in `features.py` because it spans sources: a meaningful
  pack, above-freezing temperature, and rain either falling or forecast. Needs the new
  `onsite_temp_entity` option (readings are normalised to °F either way). Every input must
  be present, so a missing source can never fabricate the condition.
- **Tier rule for rain-on-snow**: Advisory when it is forecast, Watch once the rain is
  actually falling. The pack melts into the same storm, so the same QPF yields more runoff.
- Adds a `Creek Snowpack Data Missing` watchdog. Off-season a bare cell reads 0.00 in rather
  than null, so this flags a genuinely failing fetch, not the absence of snow.

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

# Storm Runbook

What to do when a storm hits. Checklist form — meant to be readable on a phone at 2 am.

> **ewfa will not wake you.** Alerts are persistent notifications in the HA UI only.
> No push, no TTS (uncalibrated thresholds — spec §8 requires dry-run testing first).
> **NWS/NOAA is still your real alerting path.** This is a data-collection aid.

> **Tier 4 cannot fire yet.** The SEN0676 radar isn't mounted, so tiers 3–4 are dormant
> and a dangerous storm tops out at Watch (unless a Flash Flood Warning floors it to
> Warning). A low tier is not reassurance.

---

## Before / early in the storm — 30 seconds

- [ ] Open **Creek Flood Watch → Operator → Watchdogs**.
- [ ] All watchdogs off? Good. If **Modeling service stale** or **Upstream PWS missing** is
      on, fix it now — a storm recorded with dark sources is a wasted storm, and the ML
      gate wants 10 of them.
- [ ] Don't act on the tier itself. Treat it as *go look*, not an alarm.
- [ ] **Ignore QPF for thunderstorms.** Gridded forecast, 6-hour blocks — it cannot resolve
      convection and will read near zero during a pop-up storm. That is expected, not a
      fault. Watch **rain rate / rain 1h** (on-site, every 5 min) instead; that is the only
      nowcast. QPF is for frontal rain.
- [ ] If it's raining and **rain rate is also flat**, that's a real fault — Ecowitt
      ingestion, not NWS. Check the Ingestion health card.

## During — you are the gauge

With no creek sensor, your eyes are the only record of the response side. **Note clock
times**, roughly is fine:

- [ ] Creek visibly starts rising — **time**
- [ ] Creek appears to crest — **time**
- [ ] High-water mark (photo against a fixed reference — rock, post, tree)
- [ ] Culvert running full? — **time**
- [ ] Basement: dry / damp / water — **time**

Time-stamped phone photos count as all of the above.

- [ ] **While the ground is soaked**, write down both soil probes at peak wetness:
      `..._soil_moisture_willow` (house) and `..._soil_moisture_field` (creek).
      These are the "saturated" endpoints for open question #7. Grab the "dry" values in
      the next dry spell.

## After — next day

Storm events don't close until 6 h of quiet, so do this the following day.

- [ ] **Operator tab → Storms & lag → "Ready to annotate"** — confirm it names the storm
      you watched (`Storm #<n>`), then type the times from *During* into **"↳ notes"** and
      hit enter. That's it — no terminal, no SQL.

  It targets the most recent **closed** storm, not just the newest row, so it's still
  right even if a second storm has already opened since. If it says `none yet`, nothing
  has closed — wait for the 6 h quiet window, or check Storm In Progress.

- [ ] **Only if you need something the text box can't do** — annotating an *older*
      un-annotated storm, or correcting a note already saved — use SQL directly. From the
      **SSH & Web Terminal** add-on, no `docker exec`, no protection-mode toggle:

```sh
sqlite3 /share/creek_modeling/events.sqlite \
  "SELECT id, datetime(started_ts,'unixepoch','localtime') AS started, ended_ts, notes
     FROM storm_events ORDER BY id DESC LIMIT 5;"

sqlite3 /share/creek_modeling/events.sqlite \
  "UPDATE storm_events SET notes='crest ~40min after upstream peak; culvert full; basement dry'
     WHERE id=3;"
```

Same path over Samba if you'd rather use a GUI SQLite browser: `\\<ha-host>\share\creek_modeling\`.

Either way, put the times from *During* in the notes. That's what calibrates the lag.

- [ ] Judge the tiers: did it fire? too early, too late, not at all? Note it — every
      threshold in `creek_modeling/app/tiers.py` and `app/storms.py` is a placeholder, and
      an observed storm is the only thing that can move them off literature defaults.
- [ ] Check **Storms recorded** on the Operator tab against `min_events_for_ml` (10).

## Nothing to press

- **Run inference now** only skips the wait for the next 5-minute tick.
- **Retrain / Promote / Rollback** do nothing useful until Phase 4.
- The nightly batch (3 am) rolls up the dataset and refits the lag on its own.

---

## What runs without you

| | |
|---|---|
| Storm detection | opens at 0.10 in/h rain (on-site or upstream), closes after 6 h quiet |
| Event log | peaks + onset conditions written to `/share/creek_modeling/events.sqlite`, survives restarts |
| Tier evaluation | every 5 min; active NWS products floor the tier |
| Dataset | JSONL parts per fast loop, consolidated to Parquet nightly |

## Related

- [open-questions.md](./open-questions.md) — #5 (datum), #7 (soil calibration), #8/#9/#10
  (thresholds) are all things a storm helps answer
- [creek-flood-warning-spec.md](../creek-flood-warning-spec.md) — §6 alert tiers, §7 phases

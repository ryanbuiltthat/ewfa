# Open Questions

Working list of items still being resolved. Mirrors §9 of the
[project spec](../creek-flood-warning-spec.md) (the source of truth) and extends it
with field-calibration items surfaced during build-out. Strike through and note the
resolution as each is answered.

1. ~~HA install type on mini PC (HAOS/Supervised → add-on path; Container → sidecar docker-compose path).~~ **RESOLVED: HA install is HAOS.** Layer 2 modeling service is built as a local add-on (spec Addendum A).
2. Google Floods API: does a virtual gauge (hybas) land on Ackerly Creek or nearest SB Tunkhannock reach? What are its thresholds? (Still open — `google_floods_api_key` exists as an option but no source module is built yet.)
3. ~~NWM reach ID for the Ackerly segment at 41.5237,-75.7304.~~ **RESOLVED:** set in the
   add-on's `nwm_reach_id` option; `app/sources/nwm.py` is live against it. (The value lives
   in Supervisor-managed options, not in the repo — worth mirroring into `config.yaml`'s
   `options:` defaults so a clean reinstall reproduces it.)
4. ~~Which 3–5 upstream PWS stations are reliable (uptime, tipping-bucket quality)?~~
   **RESOLVED:** stations selected and set in the add-on's `upstream_pws_ids` option;
   `app/sources/wu.py` is live against them. Same note about mirroring into `config.yaml`.
   Revisit if the `Creek Upstream Data Missing` watchdog starts firing — that means the
   stations have gone offline or dropped out of the WU API.
5. Exact low-water reference datum and surveyed bank height at the sensor site (measure at install).
6. WiFi RSSI at the pole via the outdoor AP (bag test before final mount).
7. WH51 readings are relative (0–100%) and site-specific. After the next soaking rain and a dry stretch, record the empirical "saturated" and "dry" values at each burial spot; these calibrate the Tier 0 soil-moisture threshold.

8. Tier thresholds in `creek_modeling/app/tiers.py` are placeholders. The forecast/rainfall
   ones (Advisory, Watch) can be tuned from the first few storms without the creek gauge;
   the stage-based ones (Warning, Emergency) depend on #5.

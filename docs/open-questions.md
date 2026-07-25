# Open Questions

Working list of items still being resolved. Mirrors §9 of the
[project spec](../creek-flood-warning-spec.md) (the source of truth) and extends it
with field-calibration items surfaced during build-out. Strike through and note the
resolution as each is answered.

1. ~~HA install type on mini PC (HAOS/Supervised → add-on path; Container → sidecar docker-compose path).~~ **RESOLVED: HA install is HAOS.** Layer 2 modeling service is built as a local add-on (spec Addendum A).
2. Google Floods API: does a virtual gauge (hybas) land on Ackerly Creek or nearest SB Tunkhannock reach? What are its thresholds?
3. NWM reach ID for the Ackerly segment at 41.5237,-75.7304.
4. Which 3–5 upstream PWS stations are reliable (uptime, tipping-bucket quality)?
5. Exact low-water reference datum and surveyed bank height at the sensor site (measure at install).
6. WiFi RSSI at the pole via the outdoor AP (bag test before final mount).
7. WH51 readings are relative (0–100%) and site-specific. After the next soaking rain and a dry stretch, record the empirical "saturated" and "dry" values at each burial spot; these calibrate the Tier 0 soil-moisture threshold.

# Open Questions

Working list of items still being resolved. Mirrors §9 of the
[project spec](../creek-flood-warning-spec.md) (the source of truth) and extends it
with field-calibration items surfaced during build-out. Strike through and note the
resolution as each is answered.

1. ~~HA install type on mini PC (HAOS/Supervised → add-on path; Container → sidecar docker-compose path).~~ **RESOLVED: HA install is HAOS.** Layer 2 modeling service is built as a local add-on (spec Addendum A).
2. Google Floods API: does a virtual gauge (hybas) land on Ackerly Creek or nearest SB Tunkhannock reach? What are its thresholds? (Still open — `google_floods_api_key` exists as an option but no source module is built yet.)
3. ~~NWM reach ID for the Ackerly segment at 41.5237,-75.7304.~~ **RESOLVED: `4196026`.**
   Verified against `api.water.noaa.gov/nwps/v1/reaches/4196026` — the reach reports its own
   position as 41.5235,-75.7293, ~100 m from the sensor site, and returns a short-range
   streamflow forecast. Recorded as the `nwm_reach_id` default in `creek_modeling/config.yaml`.
4. ~~Which 3–5 upstream PWS stations are reliable (uptime, tipping-bucket quality)?~~
   **PARTLY RESOLVED: `KPAGLENB2`, `KPACLARK41`** (Glenburn + Clarks Summit), recorded as the
   `upstream_pws_ids` default. Spec §3 calls for 3–5 stations to average over; with two, one
   station dropping out halves the sample. Worth adding 1–3 more from the Chinchilla /
   South Abington / Waverly corridor. Revisit if the `Creek Upstream Data Missing` watchdog
   starts firing — that means the stations went offline or left the WU API.
5. Exact low-water reference datum and surveyed bank height at the sensor site (measure at install).
6. WiFi RSSI at the pole via the outdoor AP (bag test before final mount).
7. WH51 readings are relative (0–100%) and site-specific. After the next soaking rain and a dry stretch, record the empirical "saturated" and "dry" values at each burial spot; these calibrate the Tier 0 soil-moisture threshold.

8. Tier thresholds in `creek_modeling/app/tiers.py` are placeholders. The forecast/rainfall
   ones (Advisory, Watch) can be tuned from the first few storms without the creek gauge;
   the stage-based ones (Warning, Emergency) depend on #5.

9. The API recession constant `k` (`app/sources/apindex.py`, currently 0.92 ≈ a two-week
   memory) is a literature default, not a fitted value. Fit it once a few storms are
   recorded — the right `k` is the one whose index best separates storms that produced a
   creek response from those that did not.
10. Rain-on-snow thresholds (`app/features.py`: 0.20 in SWE, 34 °F) are placeholders, and
   the flag cannot be validated until a winter rain-on-snow event is actually captured.

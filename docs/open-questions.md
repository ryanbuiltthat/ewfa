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

11. Solar/battery sizing for the creek node. Load ~80 mA (1.92 Ah/day). Scoped to the
   stated flood season (early spring → mid-December), a **7 W panel** covers March–November
   and is marginal only in early December on a linear charger.
   **The binding constraint is recovery, not capacity.** Li-ion cannot be charged below
   0 °C, so a freeze runs on the pack alone — but late-autumn *surplus* (harvest minus
   load) is ~+0.9 Wh/day in November and **negative in early December** at 80 mA on a
   linear charger. A node that goes flat in a December cold snap therefore stays flat
   through January and February and only recovers around March, which is when the season
   reopens and ice-jam / rain-on-snow risk peaks. A bigger pack does not help: it delays
   the crossing and then refills proportionally slower on the same absent surplus.
   Fix the surplus instead: (a) duty-cycle the radar on a switched 5 V rail, ~80 → ~48 mA,
   which alone turns early December positive; (b) MPPT/buck charger rather than linear,
   recovering the third burned going 6 V → 4 V; (c) low-voltage protection on the pack,
   required regardless, or a flat node becomes a scrap pack. With those, **4P–6P is
   plenty**. A deliberate winter shutdown (pull and charge the pack indoors, reinstall in
   February) is a legitimate zero-cost alternative.
   **Still open:** confirm the Adafruit board exposes the bq24074 NTC input; measure the
   C6's real draw (an estimate, ~56 % of the budget); PVWatts the actual pole, where tree
   shading will dominate. See `esphome/README.md`.

12. Charger and regulator selection for the creek node (spun out of #11).
   **Chemistry change does not fix cold charging.** LiFePO4 has the same 0 °C charge
   prohibition as Li-ion; NiMH is marginal and brings unreliable −ΔV termination at solar
   currents. Lead-acid genuinely charges to about −20 °C, but a *flat* lead-acid freezes at
   −8 °C and splits its case, it stores less usable energy at 0 °C than the 18650s already
   on hand, and it weighs ~2.5 kg on a guy-wired pole.
   **The controller is the trap.** 12 V MPPT controllers idle at 10–18 mA — 12–37 % of this
   node's budget — so going lead-acid would spend a fifth of the power the exercise is
   meant to save. PWM controllers throw away ~28 % clamping an 18 V Vmp panel to 13 V.
   **Decision: keep Li-ion, replace the charger.** A CN3791-class 1S MPPT module (~0.5 mA
   idle) recovers the third the linear bq24074 burns going 6 V → 4 V and closes the
   December gap. Pair with 4P–6P 18650 and low-voltage protection. Choose the 5 V boost
   with an enable pin — that EN line is the radar load switch, so duty-cycling costs a GPIO
   and a 100 ms settle rather than a separate MOSFET.
   **OTA over winter:** bring the node indoors with the pack; on USB it stays on WiFi and
   takes updates normally. Winter is when firmware iteration happens anyway.

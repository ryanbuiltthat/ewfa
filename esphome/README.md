# Creek node — ESP32-C6 + SEN0676 radar

Phase 1 firmware (spec §2). Publishes `sensor.creek_stage`, which is what the modeling
add-on reads and what unlocks alert tiers 3–4.

> **Not yet run against hardware.** The radar is still to purchase, and the register map
> below is transcribed from the DFRobot datasheet. Bench-test before it goes up a pole —
> the procedure is at the bottom of this file.

## Files

| | |
|---|---|
| `creek_node.yaml` | The node config. Tunables are all in `substitutions:` at the top. |
| `secrets.yaml.example` | Copy to `secrets.yaml` (gitignored) and fill in. |

## Wiring

`creek_node.yaml` picks the pins; the C6 routes peripherals through a GPIO matrix, so
these are a choice, not a constraint. They avoid the C6 strapping pins (GPIO8/9/15) and
the USB-JTAG pair (GPIO12/13).

| ESP32-C6 | Device | Notes |
|---|---|---|
| GPIO5 | SEN0676 RX | node TX → sensor RX |
| GPIO4 | SEN0676 TX | node RX ← sensor TX |
| GPIO6 / GPIO7 | Fuel gauge SDA / SCL | I²C, address 0x36 |
| 5 V rail | SEN0676 VCC | sensor wants 3.5–5 V @ ~30 mA — boost/buck off the LiPo, not the C6's 3V3 |
| GND | both | common ground |

**Check the sensor's UART logic level before connecting it directly.** The datasheet gives
the supply as 3.5–5 V but does not state the signalling level. If the sensor drives 5 V TTL
and it is wired straight to GPIO4, that pin is over its absolute maximum — a level shifter
or divider on the node's RX line is needed. Measure it on the bench.

## SEN0676 Modbus registers

From the datasheet (`SEN0676_..._datasheet_V1.0.pdf`). Modbus RTU, 8N1, CRC16 (poly
`A001`), read `0x03`, write single `0x06`, default slave address `1`, default baud 115200.

| Register | Access | Meaning | Unit |
|---|---|---|---|
| `0x0001` | R | "Empty height" — radar face → water surface | mm, filtered |
| `0x0003` | R | Water level = installation height − empty height | mm, filtered |
| `0x0005` | R/W | Installation height (radar → channel bottom) | **cm** |
| `0x03F4` | R/W | Device address | `0x01`–`0xFD` |
| `0x03F6` | R/W | Baud rate ÷ 100 (`0x60` = 9600) | — |
| `0x07D4` | R/W | Max range, default `0x0A` | m |

**The firmware reads `0x0001`, not the ready-made water level in `0x0003`.** Three reasons:

1. `0x0003` is derived from the installation height in `0x0005`, which is stored in
   **centimetres** — that would quantise a ±5 mm sensor to 1 cm, throwing away most of the
   precision the SEN0676 was bought for.
2. The datum is not surveyed yet (open question #5). Doing the conversion on the node means
   the datum is a Home Assistant number, re-settable at install with no reflash and nothing
   written to the sensor's flash.
3. `0x0001` is a raw measurement. If stage ever looks wrong, `sensor.creek_radar_distance`
   shows what the sensor actually returned.

The default 10 m range (`0x07D4`) needs no change: mounted 9–10 ft up, the distance to
water runs ~0.9 m at design flood to ~3 m at low water.

## Setting the datum at install

`number.creek_mount_height_above_datum` is the distance in **mm** from the radar face down
to the low-water reference (stage = 0). Stage is then `(mount_height − distance) / 304.8`.

1. Mount and plumb the sensor (±3° beam — use a bubble level; see §2 geometry).
2. At a known low-water moment, measure radar face → water surface with a tape.
3. Set the number to that value in mm. `sensor.creek_stage` should read ~0.00 ft.
4. Record the figure in open question #5, along with surveyed bank height.

Until then it sits at 3000 mm (~9.8 ft), the §2 target — a placeholder, so **stage is not
trustworthy before step 3**.

## Reporting cadence

Spec §2 wants 30–60 s normally and 5–10 s once the creek is rising. The node polls at 60 s
and drops to 5 s when its own rate-of-rise crosses **0.02 in/min**, holding fast for 10
minutes so the mode cannot chatter through the rise it exists to capture.

That threshold is deliberately below the add-on's Tier 3 warning trigger (0.05 in/min) —
the node should already be sampling fast by the time a warning is plausible, not start
afterwards. `test_esphome_entities.py` asserts that ordering, so lowering the add-on
threshold without revisiting this fails the build.

It retunes the **poller**, not a publish filter: a reading never taken cannot be recovered,
and the crest is the whole point.

## Bench test — before this goes on a pole

The register map has never been exercised. Work through this on a desk:

1. **Flash and check the bus.** `esphome logs creek_node.yaml`. The I²C scan should find
   the fuel gauge at `0x36`. `sensor.creek_radar_distance` should show a plausible mm
   figure — point the sensor at the ceiling and compare against a tape measure.
2. **If distance never appears**, the likely causes in order: TX/RX swapped; baud not
   115200 (a previously-configured sensor may be at 9600 — see `0x03F6`); slave address not
   1 (see `0x03F4`); or `0x0001` is not the register the shipped firmware uses. Read
   `0x0003` as a cross-check — it should differ from `0x0001` by the stored installation
   height.
3. **Verify the reading tracks reality.** Move a reflector between ~0.3 m and ~3 m and
   confirm the value follows in mm. Anything closer than 150 mm is inside the blanking zone
   and is correctly rejected as unavailable rather than reported.
4. **Verify stage maths.** Set the mount-height number to the measured face-to-target
   distance; stage should read ~0. Raise the target 12 in; stage should read ~1.00 ft.
5. **Verify adaptive mode.** Move the target upward steadily and watch for
   `poll interval -> 5000 ms` in the log and `binary_sensor.creek_fast_reporting` turning
   on. Confirm it returns to 60 s about 10 minutes after the movement stops.
6. **Only then** do the pole install, the plumb check, and the §2 geometry.

Also worth doing before the mount: the open question #6 WiFi bag test at the pole
location, since `power_save_mode: LIGHT` is a solar-budget compromise that a marginal link
will not tolerate.

## Power budget

Worked per the EE skill's §4.1 method, sized for the **early-spring to mid-December**
flood season rather than year-round. **One assumption is soft:** the C6 figure is an
estimate and is ~56 % of the total — measure it on the bench before buying anything.

| | |
|---|---|
| SEN0676 | 30 mA (datasheet), ~35 mA from the cell through an 85 %-efficient boost |
| ESP32-C6 | ~45 mA, WiFi up with `power_save_mode: LIGHT` — **estimate** |
| **Average** | **~80 mA** → **1.92 Ah/day = 7.1 Wh/day** at 3.7 V |

### A 7 W panel covers the season

Assuming 0.75 derate (dirt, angle, temperature, non-STC light) → 5.25 W effective.

| Charger | Efficiency | Needs |
|---|---|---|
| Linear (bq24074-class, 6 V panel → 4 V cell) | ~67 % | **2.0 peak-sun-hours/day** |
| MPPT / buck | ~90 % | **1.5 peak-sun-hours/day** |

Approximate NEPA (41.5 °N) peak-sun-hours on a steep, winter-friendly tilt — **check
PVWatts for the actual site before committing**, since tree shading at a creekside pole
will matter more than any of this:

| | Mar | Apr–Aug | Sep | Oct | Nov | early Dec |
|---|---|---|---|---|---|---|
| PSH | 3.3 | 4.0–4.8 | 3.9 | 3.0 | 2.3 | 1.9 |
| Linear charger | ok | ok | ok | ok | ok | **short** |
| MPPT | ok | ok | ok | ok | ok | ok |

So 7 W is comfortable March through November and marginal in the first half of December,
*only* on a linear charger. **The charger topology is worth more than another 2 W of
panel** — a linear charger burns the panel-to-cell voltage difference as heat, and at
6 V → 4 V that is a third of the harvest. An MPPT or buck charger removes the December
gap outright.

### Sub-freezing charging, and why the pack size is not the answer

**Lithium-ion must not be charged below 0 °C.** It plates metallic lithium on the anode:
permanent capacity loss, then internal shorts. A damage-and-safety limit, not a derating.
Use the charger's NTC input (the bq24074 has one — verify the Adafruit board exposes it
rather than tying it off) with a 10 kΩ thermistor bonded to a **cell body**, mid-pack, not
floating in enclosure air, which reads above freezing long before the cells do.
Discharging cold is fine to about −20 °C; only charging is prohibited.

So during a hard freeze the node runs on the pack alone. The obvious response is a huge
pack, and it is the wrong one.

**The problem is not the freeze, it is the recovery.** Surplus — what is left to refill a
depleted pack after the load is served — is nearly zero in late autumn:

| | Charger | Load | Surplus | Refill 6P from empty |
|---|---|---|---|---|
| Nov | linear | 80 mA | +0.9 Wh/day | **70 days** |
| early Dec | linear | 80 mA | **−0.5 Wh/day** | **never** |
| early Dec | MPPT | 80 mA | +1.9 Wh/day | 36 days |
| Nov | linear | **48 mA** | +3.8 Wh/day | 18 days |
| early Dec | MPPT | **48 mA** | +4.7 Wh/day | 14 days |

A node that goes flat in a December cold snap does not come back when the creek thaws. At
an 80 mA load on a linear charger it is still flat in January, still flat in February, and
only climbing out around March — **which is exactly when the season reopens, and when
ice-jam and rain-on-snow risk peak.** Rain on snow is the major regional flood driver per
spec §1, and an ice-jammed channel floods harder than an open one, so the tail of that
outage lands on the highest-risk weeks of the year rather than the emptiest.

That is the real cost of dying in winter — not the frozen days, which genuinely do not
matter much, but the months of dead recovery afterwards. (The radar itself is not blind on
ice: it measures distance to whatever surface is there.)

**A bigger pack does not fix this.** It postpones the crossing and then takes proportionally
longer to refill on the same non-existent surplus. What fixes it is making the surplus
real:

1. **Duty-cycle the radar on a switched 5 V rail.** ~80 mA → ~48 mA. This is the change
   that turns early December from a net drain into a genuine surplus, and it is worth more
   than any amount of pack. Needs a load switch, a GPIO, and a settle delay before the
   Modbus read (datasheet: 100 ms startup). Not implemented — no hardware to test against.
2. **MPPT or buck charger** instead of linear. Recovers the third of the harvest a linear
   charger burns going 6 V → 4 V.
3. **Low-voltage protection on the pack — required either way.** Without a cutoff the C6
   will drag cells into deep discharge and ruin them, which converts "node is down" into
   "pack is scrap, discovered in March." With one, going flat is survivable.

### Chemistry: does another battery type solve the cold-charge problem?

| | Charges below 0 °C? | Verdict |
|---|---|---|
| Li-ion (18650) | **No** — lithium plating | Current plan; needs NTC cutoff |
| **LiFePO4** | **No** — same 0 °C limit | **Does not help.** The common assumption that LFP fixes this is wrong; it buys cycle life and safety, not cold charging |
| **NiMH** | Marginally — most datasheets also say 0–45 °C, some allow C/20 trickle lower | **Not worth it.** Tolerates trickle overcharge, which suits solar, but −ΔV termination is unreliable at solar currents, self-discharge is worse, and the cell stack voltage is awkward |
| **Lead-acid (AGM)** | **Yes** — to about −20 °C with temperature-compensated voltage | **Genuinely solves it**, with two catches below |

**Lead-acid's own winter trap:** a *discharged* lead-acid battery freezes. Electrolyte
freeze point tracks state of charge — −24 °C at the 50 % DoD floor, but **−8 °C when flat,
at which point the case splits.** So it still needs low-voltage disconnect, and its failure
mode is worse than Li-ion's: a ruined battery and spilled acid rather than a degraded pack.
It is also ~2.5 kg for *less* usable energy than the 18650s already on hand:

| Pack | Usable @ 0 °C | Days @ 80 mA | Days @ 48 mA |
|---|---|---|---|
| 18650 6P (18 Ah) | 67 Wh | 9.4 | 15.5 |
| SLA 12V 7Ah | 34 Wh | 4.7 | 7.8 |
| SLA 12V 12Ah | 58 Wh | 8.1 | 13.4 |

### The controller is the real trap, not the chemistry

Going lead-acid means adopting a 12 V charge controller, and at this scale their idle draw
is not a rounding error:

| Controller | Quiescent | Share of an 80 mA budget | Of a 48 mA budget |
|---|---|---|---|
| CN3791 1S Li MPPT module | ~0.5 mA | 0.6 % | 1.0 % |
| Genasun GV-4 | ~1 mA | 1.2 % | 2.1 % |
| Victron SmartSolar 75/10 | ~10 mA | **12.5 %** | **20.8 %** |
| EPEver Tracer AN | ~18 mA | **22.5 %** | **37.5 %** |

A good 12 V controller would eat a fifth of the power the whole exercise is trying to save.
**Also avoid PWM controllers**: with a nominal-12 V panel (Vmp ~18 V) clamped to a 13 V
battery they throw away ~28 %, which is the same mistake as the linear charger.

### Recommendation: keep Li-ion, change the charger

The chemistry is not the problem. The charger is.

1. **Replace the linear bq24074 with a CN3791-class 1S MPPT** (6 V panel input). Recovers
   the third burned going 6 V → 4 V, closes the December gap, and draws ~0.5 mA idle.
2. **4P–6P of 18650** — free, already on hand, and more usable energy than an SLA twice its
   weight on a guy-wired pole.
3. **Low-voltage protection.** Required for either chemistry.
4. **Pick the 5 V boost with an enable pin.** That EN line *is* the radar load switch —
   duty-cycling then costs a GPIO and a 100 ms settle, with no separate MOSFET. Choose a
   boost with genuine shutdown (µA-level) rather than one that idles at mA.

### OTA over winter is a solved problem

The one real objection to pulling the pack in December is losing OTA. It costs nothing to
fix: **bring the node indoors with the pack.** On USB at a desk it stays on WiFi, takes OTA
updates normally, and is available for bench work — and winter is when firmware iteration
would happen anyway, since there is nothing to measure on a frozen creek. Reinstall in
February with current firmware.

That makes the winter shutdown the cheap path and unattended winter operation an optional
upgrade, rather than the other way round.

### Pack sizing (1S × P, ~3000 mAh cells)

With the load duty-cycled, **4P–6P is plenty** — the earlier 8P–10P recommendation was
compensating for a surplus problem that pack size cannot solve.

| Pack | Capacity | @ 20 °C | @ 0 °C, 80 mA | @ 0 °C, 48 mA |
|---|---|---|---|---|
| 4P | 12 Ah | 5.0 days | 3.8 days | 6.3 days |
| 6P | 18 Ah | 7.5 days | 5.6 days | 9.4 days |

**The zero-cost alternative:** given the season genuinely ends mid-December, a planned
winter shutdown is legitimate — pull the pack in December, charge it indoors, reinstall in
February. It sidesteps the recovery problem entirely and needs no new hardware. It only
works if it is deliberate, because the failure mode of *forgetting* is the March outage
above.

### If you build the pack

- **Match and pre-balance cells** to within ~0.05 V before welding. In parallel a
  mismatched cell is charged by its neighbours through the nickel — spot-welding makes that
  uncontrolled current path permanent.
- **Fuse each cell** to the bus with a narrowed link, so one internal short does not have
  the others dumping into it.
- **Capacity-test salvaged cells.** A parallel pack is only as good as its worst member.

Deep sleep is still excluded. A flood-warning node asleep during the rise is not a
flood-warning node.

Tracked as open question #11.

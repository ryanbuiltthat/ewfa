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

### Sub-freezing charging is the real constraint

**Lithium-ion must not be charged below 0 °C.** Doing so plates metallic lithium on the
anode: permanent capacity loss, and eventually internal shorts. This is not a derating —
it is a damage-and-safety limit, and it applies to every 18650 regardless of brand.

The season runs to mid-December and starts in early spring, so sub-freezing days are
routine at both ends. That means:

- **Use the charger's NTC/thermistor input** (the bq24074 has one — verify the specific
  Adafruit board exposes it rather than tying it off) with a 10 kΩ NTC bonded to the pack,
  not to the enclosure air. It suspends charging outside the safe window automatically.
- **Discharging cold is fine** — down to about −20 °C, at reduced capacity. Only charging
  is prohibited.
- Therefore the pack must carry the **longest sub-freezing stretch**, not merely the
  longest overcast one. In NEPA a week below freezing in December is unremarkable, and
  during it the panel contributes nothing no matter how big it is.

That is what sets pack size.

### Pack sizing (1S × P, ~3000 mAh cells)

Usable capacity taken as 80 % to protect cycle life. The cold column is the one that
matters, since the no-charge window is by definition cold:

| Pack | Capacity | Autonomy @ 20 °C | Autonomy @ 0 °C |
|---|---|---|---|
| 4P | 12 Ah | 5.0 days | 3.8 days |
| **6P** | **18 Ah** | **7.5 days** | **5.6 days** |
| **8P** | **24 Ah** | **10.0 days** | **7.5 days** |
| 10P | 30 Ah | 12.5 days | 9.4 days |

**6P–8P is the sensible build.** 4P looks adequate at room temperature and is not: it
gives under four days in exactly the conditions where charging is also unavailable.

### If you build the pack

- **Match cells before welding.** Same capacity grade, and charge them all to within
  ~0.05 V of each other first. In parallel a mismatched cell is charged by its neighbours
  through the nickel, which is exactly the uncontrolled current path spot-welding makes
  permanent.
- **Fuse each cell** with a narrowed nickel link to the bus. A single internal short in one
  of eight paralleled cells otherwise has the other seven dumping into it.
- **NTC bonded to a cell body**, mid-pack, not floating in the enclosure — air temperature
  will read above freezing long before the cells do.
- Salvaged cells: capacity-test before committing. A pack is only as good as its worst
  parallel member, and the whole point here is multi-day autonomy.

### Duty-cycling the radar — now optional

Switching the SEN0676's 5 V rail between reads cuts its contribution from ~35 mA to under
1 mA — total draw ~48 mA, roughly a 40 % saving. With a 7 W panel and a 6P+ pack that is no
longer needed for the energy balance. It remains attractive for one reason: it stretches
the sub-freezing no-charge window by the same 40 %, turning 8P's 7.5 cold days into ~12.
Needs a load switch, a GPIO, and a settle delay before the Modbus read (datasheet: 100 ms
startup). Not implemented — no hardware to test against.

Deep sleep is still excluded. A flood-warning node asleep during the rise is not a
flood-warning node.

Tracked as open question #11.

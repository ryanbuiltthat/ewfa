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

## Power

Continuous operation — no deep sleep. A flood-warning node that is asleep during the rise
is not a flood-warning node, and the adaptive fast mode exists precisely so the sampling
rate rises when it matters. The radar's ~30 mA is the dominant draw. If the solar budget
turns out not to cover 24/7 operation, the next thing to try is powering the radar through
a switched rail between reads rather than sleeping the node — the node needs to stay on the
network to be trusted.

# Wiring reference / diagram prompt

Two uses. It is the plain-text wiring reference for the bench build, and it is a
self-contained prompt for generating a Fritzing-style diagram — self-contained meaning it
assumes no knowledge of this project, so it can be pasted into a fresh session.

Keep it in sync with the connection table in [README.md](./README.md#wiring) and the pin
substitutions in [creek_node.yaml](./creek_node.yaml). Where they disagree, the YAML wins —
it is the only one a compiler checks.

**Two entries are deliberately unsettled**, and the callouts say so rather than pretending
otherwise:

- **Panel voltage** is written as 12 V to match the CN3791 variant on hand. If the panel is
  6 V nominal, the board is the wrong variant (open question #12).
- **GPIO18 → SHDN** is the intended radar duty-cycle line. GPIO18 is clear of the C6's
  strapping pins, the USB-JTAG pair and SPI flash, but nothing in the firmware drives it
  yet — that waits on hardware to test against.

---

````text
Create a Fritzing-style wiring diagram (breadboard view: realistic component
illustrations with colored wires and labels, NOT a schematic) for a solar-powered
creek water-level sensor node mounted on a pole outdoors.

LAYOUT
Landscape. Two visually grouped zones with a labeled divider:
  LEFT  = "POWER"   (solar → charge → battery → regulated rails)
  RIGHT = "SENSING" (MCU + peripherals)
Label every wire at both ends. Use red for positive rails, black for ground,
distinct colors for each signal. Keep wires orthogonal and untangled.

COMPONENTS
Power zone (left to right):
 1. Solar panel, 7 W, nominal 12 V — two leads
 2. KSD9700 bimetallic thermal switch, 5 °C normally-open — small white plastic
    body with two black leads
 3. HiLetgo CN3791 MPPT solar charge controller (12 V variant) — small PCB with
    two JST-PH2.0 sockets labeled "IN" and "BAT"
 4. 1S 18650 battery pack — four 18650 cells in parallel, joined by nickel strip,
    single + and − output
 5. 1S lithium protection board (over-discharge / over-current) — small PCB with
    B+, B−, P+, P− pads
 6. Pololu U1V11F3 — 3.3 V step-up regulator, small purple PCB, pins: VIN, GND,
    VOUT, SHDN
 7. Pololu U1V11F5 — 5 V step-up regulator, identical board, same pin names

Sensing zone (right):
 8. ESP32-C6-DevKitC-1 development board with labeled GPIO headers
 9. DFRobot SEN0676 80 GHz radar level sensor — small square PCB with a lens,
    four wires: VCC, GND, TX, RX
10. SparkFun MAX17043 LiPo fuel gauge breakout — pins VCC, GND, SDA, SCL

CONNECTIONS
Power chain:
  Solar panel +        → KSD9700 lead 1                      (red)
  KSD9700 lead 2       → CN3791 "IN" +                       (red)
  Solar panel −        → CN3791 "IN" −                       (black)
  CN3791 "BAT" +       → protection board B+                 (red)
  CN3791 "BAT" −       → protection board B−                 (black)
  Protection board P+  → PACK+ rail                          (red)
  Protection board P−  → GND rail                            (black)
  PACK+ → U1V11F3 VIN, U1V11F5 VIN, MAX17043 VCC             (red)
  GND   → U1V11F3 GND, U1V11F5 GND, MAX17043 GND, C6 GND,
          SEN0676 GND                                        (black)

Regulated rails:
  U1V11F3 VOUT → ESP32-C6 "3V3" pin      (orange)  [C6 always powered]
  U1V11F5 VOUT → SEN0676 VCC             (yellow)  [radar, switchable]

Data + control:
  ESP32-C6 GPIO10 → SEN0676 RX           (green)   UART TX, Modbus RTU
  ESP32-C6 GPIO11 ← SEN0676 TX           (blue)    UART RX
  ESP32-C6 GPIO6  ↔ MAX17043 SDA         (white)   I²C, addr 0x36
  ESP32-C6 GPIO7  ↔ MAX17043 SCL         (purple)  I²C
  ESP32-C6 GPIO18 → U1V11F5 SHDN         (gray)    radar power duty-cycle
  U1V11F3 SHDN: leave unconnected (internal pull-up = always enabled)

CALLOUT ANNOTATIONS (as labeled notes with leader lines, not wires)
 A. On the KSD9700: "Bonded to a CELL BODY mid-pack with thermal tape — NOT to
    enclosure air. Opens below 5 °C to block sub-freezing charging."
 B. On the KSD9700: "In the PANEL line only — never the battery line."
 C. On the GPIO18 → SHDN wire: "Cuts radar power between reads (~80 mA → ~48 mA)."
 D. Between SEN0676 TX and GPIO11: "⚠ TBD: verify sensor UART logic level. If it
    drives 5 V, a level shifter is required here — GPIO11 is 3.3 V max."
 E. On the CN3791: "⚠ Confirm which JST is IN and which is BAT before wiring."
 F. On the protection board: "Required — the CN3791 does not protect against
    over-discharge."

STYLE
Clean, well-spaced, hobbyist-electronics documentation look. Light background.
Include a small legend mapping wire colors to function. Title the diagram
"Ackerly Creek Node — Wiring".
````

---

## Why the callouts are callouts

Each one is a mistake that is silent, expensive, or both — the reasoning lives in
[README.md](./README.md) and open questions #11–13:

| | |
|---|---|
| A | Enclosure air reads above freezing hours before the cells do, so an air-mounted switch enables charging into a cold pack — the exact failure it was fitted to prevent. |
| B | Switching the panel leaves the discharge path intact: a failed-open switch costs charging, visible as a declining battery, rather than killing the load. |
| C | The duty-cycle is what turns early-December surplus positive; it is worth more than pack capacity. |
| D | The datasheet gives the SEN0676 supply as 3.5–5 V but never states the signalling level. 5 V TTL straight into GPIO11 is over its absolute maximum. |
| E | The two JSTs are input and battery, not paired panel inputs. A panel into the battery connector destroys the module. |
| F | The CN3791 is a charger, not a BMS. This is what separates "node went flat" from "pack is scrap". |

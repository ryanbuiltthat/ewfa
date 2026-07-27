"""The ESPHome creek node must publish the entity IDs the rest of the system reads.

`stage_entity` in the add-on's config.yaml, and the creek entities on the dashboard, are
just strings — nothing connects them to the firmware. If the node's device name or a
sensor name changes, the add-on reads an entity that does not exist, which in Home
Assistant is silence rather than an error: `get_float` returns None, stage stays null, and
tiers 3-4 simply never fire. Every watchdog stays green throughout, because "no stage" is
also what "no sensor built yet" looks like.

This is the same drift that broke the dashboard in 84ff4f5, one layer further down.

Home Assistant builds an ESPHome entity_id as slugify("<friendly_name> <entity name>"), so
device `Creek` + sensor `Stage` -> sensor.creek_stage.

Run: python creek_modeling/tests/test_esphome_entities.py
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
NODE = ROOT / "esphome" / "creek_node.yaml"
ADDON_CONFIG = ROOT / "creek_modeling" / "config.yaml"
DASHBOARD = ROOT / "dashboards" / "creek_flood_watch.yaml"

# Domains an ESPHome config declares that become HA entities.
ENTITY_DOMAINS = ("sensor", "binary_sensor", "text_sensor", "number", "switch", "button")


class _EsphomeLoader(yaml.SafeLoader):
    """ESPHome YAML carries tags SafeLoader rejects (`!secret`, `!lambda`)."""


_EsphomeLoader.add_multi_constructor(
    "!", lambda loader, suffix, node: f"<{suffix}>"
)


def _substitute(raw: str, subs: dict) -> str:
    for key, value in subs.items():
        raw = raw.replace("${%s}" % key, str(value))
    return raw


def load_node() -> dict:
    raw = NODE.read_text(encoding="utf-8")
    subs = yaml.load(raw, Loader=_EsphomeLoader).get("substitutions", {})
    return yaml.load(_substitute(raw, subs), Loader=_EsphomeLoader)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def node_entity_ids() -> dict[str, str]:
    """{entity name: entity_id} for every named entity the node declares."""
    doc = load_node()
    prefix = doc["esphome"]["friendly_name"]
    out = {}

    def collect(domain, entry):
        # max17043 nests its named sensors one level down (battery_voltage/battery_level).
        for key, value in entry.items():
            if key == "name" and isinstance(value, str):
                out[value] = f"{domain}.{slugify(prefix)}_{slugify(value)}"
            elif isinstance(value, dict) and "name" in value:
                out[value["name"]] = f"{domain}.{slugify(prefix)}_{slugify(value['name'])}"

    for domain in ENTITY_DOMAINS:
        for entry in doc.get(domain) or []:
            collect(domain, entry)
    return out


def test_node_publishes_the_stage_entity_the_addon_reads():
    expected = yaml.safe_load(ADDON_CONFIG.read_text(encoding="utf-8"))["options"]["stage_entity"]
    ids = set(node_entity_ids().values())
    assert expected in ids, (
        f"add-on reads {expected!r} but the node publishes {sorted(ids)}")


def test_dashboard_creek_node_entities_are_published_by_the_node():
    """The dashboard's non-add-on `sensor.creek_*` references must come from the node.

    Scoped to sensor.creek_* deliberately: add-on entities carry the
    `ackerly_creek_modeling_` device prefix, and test_dashboard_entities.py owns those.
    """
    dash = DASHBOARD.read_text(encoding="utf-8")
    referenced = set(re.findall(r"\bsensor\.creek_[a-z0-9_]+\b", dash))
    published = set(node_entity_ids().values())
    missing = sorted(referenced - published)
    assert not missing, f"dashboard references node entities the node does not publish: {missing}"


def test_every_entity_lands_under_the_creek_prefix():
    """The repo's convention (DOCS.md): node entities are plain `sensor.creek_*`, with no
    doubled device name. A friendly_name of "Creek Node" would silently produce
    sensor.creek_node_stage and break every reference at once."""
    bad = [eid for eid in node_entity_ids().values()
           if not re.match(r"^[a-z_]+\.creek_[a-z0-9_]+$", eid)]
    assert not bad, f"entities outside the creek_ prefix convention: {bad}"


def test_fast_poll_is_faster_than_normal_and_both_match_the_spec():
    """Spec §2: 30-60 s normal, 5-10 s once rising. A fast interval that is not actually
    faster would be a silent no-op — the node would look adaptive and sample nothing extra."""
    subs = yaml.load(NODE.read_text(encoding="utf-8"), Loader=_EsphomeLoader)["substitutions"]
    normal = int(subs["normal_interval_ms"])
    fast = int(subs["fast_interval_ms"])
    assert fast < normal, f"fast interval {fast}ms is not faster than normal {normal}ms"
    assert 30_000 <= normal <= 60_000, f"normal interval {normal}ms outside spec §2's 30-60 s"
    assert 5_000 <= fast <= 10_000, f"fast interval {fast}ms outside spec §2's 5-10 s"


def test_fast_mode_trips_before_the_addons_warning_threshold():
    """The node must already be sampling fast by the time the add-on would call a Tier 3
    Warning, or the warning arrives describing a rise nobody measured at resolution."""
    sys.path.insert(0, str(ROOT / "creek_modeling"))
    from app.tiers import WARNING_RATE_OF_RISE_IN_MIN

    subs = yaml.load(NODE.read_text(encoding="utf-8"), Loader=_EsphomeLoader)["substitutions"]
    node_threshold = float(subs["fast_threshold_in_min"])
    assert node_threshold < WARNING_RATE_OF_RISE_IN_MIN, (
        f"node speeds up at {node_threshold} in/min but the add-on warns at "
        f"{WARNING_RATE_OF_RISE_IN_MIN} in/min — it would still be on the slow cadence")


def test_blanking_zone_matches_the_sensor_datasheet():
    """SEN0676 minimum range is 0.15 m; anything closer is not a measurement."""
    subs = yaml.load(NODE.read_text(encoding="utf-8"), Loader=_EsphomeLoader)["substitutions"]
    assert int(subs["blanking_mm"]) >= 150, "blanking zone below the datasheet minimum range"


# ESP32-C6 strapping pins (TRM): MTMS, MTDI, plus 8/9/15. A C3/S3 habit says three; the
# C6 has five, and GPIO4/5 look innocuous. ESPHome only *warns* about strapping-pin use, so
# a build stays green while the node reboots into the wrong mode or fails to flash.
C6_STRAPPING_PINS = {"GPIO4", "GPIO5", "GPIO8", "GPIO9", "GPIO15"}
# USB-JTAG pair; taking these costs the serial console the bench test depends on.
C6_USB_PINS = {"GPIO12", "GPIO13"}


def test_no_peripheral_lands_on_a_strapping_or_usb_pin():
    subs = yaml.load(NODE.read_text(encoding="utf-8"), Loader=_EsphomeLoader)["substitutions"]
    assigned = {k: v for k, v in subs.items() if k.endswith("_pin")}
    bad = {k: v for k, v in assigned.items() if v in C6_STRAPPING_PINS | C6_USB_PINS}
    assert not bad, f"pins on strapping/USB lines: {bad}"


def test_pin_assignments_are_unique():
    subs = yaml.load(NODE.read_text(encoding="utf-8"), Loader=_EsphomeLoader)["substitutions"]
    pins = [v for k, v in subs.items() if k.endswith("_pin")]
    assert len(pins) == len(set(pins)), f"a GPIO is assigned twice: {pins}"


def test_median_filter_is_valid_esphome():
    """send_first_at must be <= send_every. ESPHome rejects the config outright, so this
    fails the fast Python suite rather than waiting on the slow compile job."""
    doc = load_node()
    for entry in doc.get("sensor") or []:
        for f in entry.get("filters") or []:
            median = (f or {}).get("median")
            if median:
                every = median.get("send_every", 1)
                first = median.get("send_first_at", 1)
                assert first <= every, (
                    f"send_first_at ({first}) must be <= send_every ({every})")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()

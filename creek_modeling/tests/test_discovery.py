"""Plain-assert tests for the discovery payloads. Run: python creek_modeling/tests/test_discovery.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.discovery import DiscoveryPublisher  # noqa: E402


def build():
    published = []
    pub = DiscoveryPublisher(lambda t, p, r: published.append((t, p, r)), "creek")
    return pub, published


def test_topics_and_counts():
    pub, _ = build()
    pairs = pub.configs()
    sensors = [t for t, _ in pairs if "/sensor/" in t]
    binaries = [t for t, _ in pairs if "/binary_sensor/" in t]
    buttons = [t for t, _ in pairs if "/button/" in t]
    # 15 status/model + 7 (2a) + 8 (2b) + 6 (2c) + 1 (2d) + 2 (2e swe/temp)
    assert len(sensors) == 39, len(sensors)
    # 2d NWS watch/warning/flash flags + 2e rain-on-snow
    assert len(binaries) == 4, len(binaries)
    assert len(buttons) == 4, len(buttons)
    for topic, _ in pairs:
        assert topic.startswith("homeassistant/")
        assert topic.endswith("/config")
        assert "/creek_modeling/" in topic  # node_id


def test_stable_entity_id_hints_and_unique_ids():
    pub, _ = build()
    cfgs = {c["object_id"]: c for _, c in pub.configs()}
    fp = cfgs["creek_flood_probability"]
    assert fp["name"] == "Creek Flood Probability"        # slugifies to sensor.creek_flood_probability
    assert fp["unique_id"] == "creek_modeling_creek_flood_probability"
    assert fp["state_topic"] == "creek/flood_probability"


def test_every_entity_has_device_and_availability():
    pub, _ = build()
    for _, c in pub.configs():
        assert c["device"]["identifiers"] == ["ackerly_creek_modeling"]
        assert c["availability_topic"] == "creek/status/availability"
        assert c["payload_not_available"] == "offline"


def test_buttons_have_command_topics():
    pub, _ = build()
    cfgs = {c["object_id"]: c for _, c in pub.configs()}
    assert cfgs["creek_retrain_now"]["command_topic"] == "creek/cmd/retrain"
    assert cfgs["creek_run_inference_now"]["command_topic"] == "creek/cmd/run_inference"


def test_base_topic_is_honored():
    published = []
    pub = DiscoveryPublisher(lambda t, p, r: published.append((t, p, r)), "flood")
    cfgs = {c["object_id"]: c for _, c in pub.configs()}
    assert cfgs["creek_flood_probability"]["state_topic"] == "flood/flood_probability"


def test_rain_and_qpf_sensors_present():
    pub, _ = build()
    cfgs = {c["object_id"]: c for _, c in pub.configs()}
    for w in (1, 3, 6, 24, 72):
        assert cfgs[f"creek_rain_{w}h"]["state_topic"] == "creek/features"
    assert cfgs["creek_qpf_6h"]["device_class"] == "precipitation"
    assert cfgs["creek_qpf_24h"]["unit_of_measurement"] == "in"


def test_publish_all_emits_retained_json():
    pub, published = build()
    pub.publish_all()
    assert len(published) == 47
    for topic, payload, retain in published:
        assert retain is True
        json.loads(payload)  # valid JSON


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()

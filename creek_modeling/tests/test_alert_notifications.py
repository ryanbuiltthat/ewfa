"""The tier-change alert automation in the HA package.

This automation is the one piece of the system that only ever runs unattended, at the
worst possible moment, on a phone that is face-down in a dark room. Nothing exercises it
in normal use, so the parts that would silently render it useless -- no targets, a
critical floor set above any tier that can actually fire, a push that does not route
through the alarm stream -- are pinned here instead.

Run: python creek_modeling/tests/test_alert_notifications.py
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "ha-packages" / "creek_warning.yaml"

# Highest tier app/tiers.py can emit, and the highest reachable without the creek gauge.
MAX_TIER = 4
MAX_TIER_WITHOUT_GAUGE = 2


def automation():
    doc = yaml.safe_load(PACKAGE.read_text(encoding="utf-8"))
    for entry in doc["automation"]:
        if entry.get("id") == "creek_tier_change":
            return entry
    raise AssertionError("creek_tier_change automation is missing from the package")


def push_step():
    """The repeat block that fans the push out to every configured target."""
    for action in automation()["actions"]:
        if "repeat" in action:
            return action["repeat"]["sequence"][0]
    raise AssertionError("no repeat/for_each push step in the automation")


def test_there_is_at_least_one_notify_target():
    targets = automation()["variables"]["notify_targets"]
    assert isinstance(targets, list) and targets, targets
    for t in targets:
        assert t.startswith("notify."), f"{t} is not a notify service"


def test_every_target_is_notified_not_just_the_first():
    """A plain `action: notify.x` reaches one phone. The fan-out is the whole point of
    a configurable target list."""
    step = push_step()
    assert automation()["actions"][-1]["repeat"]["for_each"] == "{{ notify_targets }}"
    assert step["action"] == "{{ repeat.item }}"


def test_one_dead_target_does_not_silence_the_rest():
    """An unavailable or misspelled notify service raises. Without continue_on_error the
    automation aborts there and every target after it in the list is never told."""
    assert push_step()["continue_on_error"] is True


def test_the_critical_floor_is_reachable_today():
    """Tiers 3-4 need the creek gauge, which is not mounted. A floor above 2 would mean
    no critical alert can physically fire -- the feature would look wired up and never
    make a sound."""
    floor = automation()["variables"]["critical_from_tier"]
    assert 0 <= floor <= MAX_TIER, floor
    assert floor <= MAX_TIER_WITHOUT_GAUGE, (
        f"critical_from_tier={floor} cannot fire until the creek gauge is mounted")


def test_a_critical_push_routes_through_the_alarm_stream():
    """`alarm_stream` is what carries the sound through silent, vibrate and Do Not
    Disturb. Any other channel and a Warning at 3 a.m. is a silent notification."""
    data = push_step()["data"]["data"]
    assert "alarm_stream" in data["channel"], data["channel"]
    assert "is_critical" in data["channel"], "the channel must depend on the tier"
    assert data["ttl"] == 0            # past Doze batching
    assert data["priority"] == "high"


def test_the_push_replaces_rather_than_stacks():
    """A storm walks the tier up and back down repeatedly; without a constant tag each
    step leaves its own notification and the phone fills with stale alarms."""
    assert push_step()["data"]["data"]["tag"] == "creek_alert_tier"


def test_the_alert_describes_the_tier_that_fired_it():
    """Reading states()/state_attr() in the actions is a race: the entity can move on
    before they run, and the push then names a different tier than the one that fired."""
    v = automation()["variables"]
    for key in ("tier", "label", "why", "is_critical"):
        assert "trigger.to_state" in v[key], f"{key} does not read from the trigger"
        assert "state_attr(" not in v[key], f"{key} re-reads live state"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()

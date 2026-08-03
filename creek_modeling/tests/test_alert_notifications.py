"""The tier-change alert automation in the HA package.

This automation is the one piece of the system that only ever runs unattended, at the
worst possible moment, on a phone that is face-down in a dark room. Nothing exercises it
in normal use, so the parts that would silently render it useless -- no targets, a
critical floor set above any tier that can actually fire, a push that does not route
through the alarm stream -- are pinned here instead.

Two rounds got this wrong before landing on the current shape, both worth remembering:

  0.14.1 called `action: "{{ repeat.item }}"` against a list of `notify.<name>` strings,
  assuming companion-app phones have a fixed, guessable notify *service* name. They do
  not -- it failed with "unknown action: notify.ryanphone".

  0.14.2 switched to a device action (device_id / domain: mobile_app / type: notify) but
  kept the repeat/for_each loop, templating device_id as `"{{ repeat.item }}"`. That also
  failed, for a structural reason rather than a naming one: Home Assistant resolves a
  device action's device_id when the automation is *set up*, before any per-iteration
  template rendering happens, so the literal string was never evaluated as a template at
  all -- "Unknown device '{{ repeat.item }}'".

0.14.3 uses one explicit, non-templated action per phone (device_id is a literal value,
never a template), sharing content via a YAML anchor rather than a runtime loop. Every
test below that references "the repeat step" from earlier versions was rewritten to walk
the actual list of per-phone device actions instead.

Run: python creek_modeling/tests/test_alert_notifications.py
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "ha-packages" / "creek_warning.yaml"

# Home Assistant device ids are a 32-character lowercase hex string.
DEVICE_ID = re.compile(r"^[0-9a-f]{32}$")

# Highest tier app/tiers.py can emit, and the highest reachable without the creek gauge.
MAX_TIER = 4
MAX_TIER_WITHOUT_GAUGE = 2


def automation():
    doc = yaml.safe_load(PACKAGE.read_text(encoding="utf-8"))
    for entry in doc["automation"]:
        if entry.get("id") == "creek_tier_change":
            return entry
    raise AssertionError("creek_tier_change automation is missing from the package")


def push_steps():
    """Every per-phone companion-app action -- anything with a device_id key. Not a
    repeat block: see the module docstring for why that shape does not work here."""
    steps = [a for a in automation()["actions"] if isinstance(a, dict) and "device_id" in a]
    if not steps:
        raise AssertionError("no per-phone device-action push step in the automation")
    return steps


def test_there_is_at_least_one_notify_target():
    assert len(push_steps()) >= 1


def test_targets_are_device_ids_not_notify_service_names():
    """The regression this guards: `notify.<name>` is not a real, callable service for a
    companion-app phone -- there is no fixed name to template against, and 0.14.1 shipped
    exactly that assumption and broke ("unknown action: notify.ryanphone")."""
    for step in push_steps():
        t = str(step["device_id"])
        assert DEVICE_ID.match(t), f"{t} does not look like a device id"
        assert not t.startswith("notify."), f"{t} is a notify-service name, not a device id"


def test_device_id_is_never_templated():
    """The 0.14.2 regression: Home Assistant resolves a device action's device_id when
    the automation is set up, before any per-iteration Jinja rendering, so a templated
    value like "{{ repeat.item }}" is never evaluated -- it errors as a literal, invalid
    device id and the whole automation fails to load."""
    for step in push_steps():
        assert "{{" not in str(step["device_id"]), step["device_id"]


def test_there_is_no_repeat_loop_over_the_targets():
    """Structural guard for the same 0.14.2 regression: device actions cannot be driven
    by repeat/for_each at all, so if one reappears here it is broken again regardless of
    what device_id inside it looks like."""
    def walk(node):
        if isinstance(node, dict):
            assert "repeat" not in node, "a repeat step cannot drive per-phone device actions"
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(automation()["actions"])


def test_every_target_is_notified_not_just_the_first():
    """Two phones are configured; both must have their own action, not just one."""
    ids = {step["device_id"] for step in push_steps()}
    assert len(ids) == len(push_steps()), "duplicate device_id -- one phone shadows another"
    assert len(ids) >= 2, "fewer push actions than configured phones"


def test_the_push_is_a_device_action_not_a_templated_service_call():
    """The fix itself: target each phone by device id through the mobile_app/notify
    device action, not by templating a notify.<name> service string that may not exist."""
    for step in push_steps():
        assert step["domain"] == "mobile_app"
        assert step["type"] == "notify"
        assert "action" not in step, "reverted to calling a templated service name"


def test_one_dead_target_does_not_silence_the_rest():
    """An unavailable or misconfigured device raises. Without continue_on_error on every
    block, the automation aborts there and every action after it is never run."""
    for step in push_steps():
        assert step["continue_on_error"] is True


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
    for step in push_steps():
        data = step["data"]
        assert "alarm_stream" in data["channel"], data["channel"]
        assert "is_critical" in data["channel"], "the channel must depend on the tier"
        assert data["ttl"] == 0            # past Doze batching
        assert data["priority"] == "high"


def test_the_push_replaces_rather_than_stacks():
    """A storm walks the tier up and back down repeatedly; without a constant tag each
    step leaves its own notification and the phone fills with stale alarms."""
    for step in push_steps():
        assert step["data"]["tag"] == "creek_alert_tier"


def test_title_and_message_are_present_on_the_device_action():
    """Device actions carry title/message as top-level keys, not nested under `data:`
    the way a plain notify service call does -- a leftover nested `data.title` would
    silently produce a blank notification."""
    for step in push_steps():
        assert "{{ push_title }}" in step["title"]
        assert "{{ why }}" in step["message"]


def test_every_phone_gets_identical_content():
    """The anchor/merge-key sharing is a source-file convenience -- confirm it actually
    produces the same notification for every phone rather than only the first."""
    steps = push_steps()
    shared = [{k: v for k, v in s.items() if k != "device_id"} for s in steps]
    assert all(s == shared[0] for s in shared), "phones would receive different pushes"


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

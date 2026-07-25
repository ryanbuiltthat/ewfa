"""Plain-assert tests for the tier mapping. Run: python creek_modeling/tests/test_tiers.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tiers import compute_tier  # noqa: E402


def test_all_clear():
    assert compute_tier(0.0, False) == (0, "All-clear")
    assert compute_tier(0.19, False) == (0, "All-clear")


def test_ponding_forces_watch():
    assert compute_tier(0.0, True) == (1, "Watch")


def test_watch_warning_emergency_thresholds():
    assert compute_tier(0.20, False) == (1, "Watch")
    assert compute_tier(0.50, False) == (2, "Warning")
    assert compute_tier(0.80, False) == (3, "Emergency")
    assert compute_tier(1.0, False) == (3, "Emergency")


def test_none_probability_is_all_clear():
    assert compute_tier(None, False) == (0, "All-clear")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()

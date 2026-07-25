"""Tests for NWS QPF parsing/proration (no HTTP). Run: python creek_modeling/tests/test_nws.py"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.sources.nws import NwsQpf, _duration_seconds  # noqa: E402


def test_duration_parsing():
    assert _duration_seconds("PT6H") == 21600
    assert _duration_seconds("PT1H") == 3600
    assert _duration_seconds("PT30M") == 1800
    assert _duration_seconds("P1DT6H") == 108000
    assert _duration_seconds("PT0H") == 0


NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
VALUES = [
    {"validTime": "2026-01-01T00:00:00+00:00/PT6H", "value": 25.4},   # fully in next 6h
    {"validTime": "2026-01-01T06:00:00+00:00/PT6H", "value": 25.4},   # in 24h, not 6h
    {"validTime": "2025-12-31T21:00:00+00:00/PT6H", "value": 20.0},   # 21:00-03:00, half overlaps
    {"validTime": "2026-01-01T12:00:00+00:00/PT6H", "value": None},   # ignored
]


def test_qpf_6h_prorates_partial_intervals():
    # A fully in (25.4mm) + C half in (10mm) = 35.4mm -> 1.3937 in
    got = NwsQpf._qpf_within(VALUES, NOW, 6)
    assert abs(got - (35.4 / 25.4)) < 1e-3, got


def test_qpf_24h_sums_intervals():
    # A(25.4) + B(25.4) + C(10) = 60.8mm -> 2.3937 in
    got = NwsQpf._qpf_within(VALUES, NOW, 24)
    assert abs(got - (60.8 / 25.4)) < 1e-3, got


def test_qpf_zero_when_no_overlap():
    future = [{"validTime": "2026-01-05T00:00:00+00:00/PT6H", "value": 50.0}]
    assert NwsQpf._qpf_within(future, NOW, 24) == 0.0


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()

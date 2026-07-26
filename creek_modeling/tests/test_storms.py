"""Tests for the storm event log (spec §7 Phase 3).
Run: python creek_modeling/tests/test_storms.py
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import storms as st  # noqa: E402
from app.features import FeatureRow  # noqa: E402
from app.storms import StormLog  # noqa: E402

T0 = 1769904000.0
HOUR = 3600.0


def row(ts, rain=0.0, upstream=0.0, **kw):
    base = dict(
        ts=ts, stage_ft=None, rate_of_rise_in_min=None, soil_moisture_mean_pct=55.0,
        soil_moisture_near_house_pct=55.0, soil_moisture_near_creek_pct=55.0,
        ponding_flag=False, rain_1h_in=rain, upstream_rain_1h_in=upstream,
        api_index_in=1.5,
    )
    base.update(kw)
    return FeatureRow(**base)


def make():
    return StormLog(Path(tempfile.mkdtemp()))


def test_rain_opens_an_event_and_quiet_alone_does_not():
    s = make()
    assert s.observe(row(T0, rain=0.01)) is None
    assert s.count(completed_only=False) == 0
    assert s.observe(row(T0 + 300, rain=0.4)) == "opened"
    assert s.count(completed_only=False) == 1


def test_upstream_rain_alone_can_open_an_event():
    # The upstream corridor is half the basin, and it rains there first.
    s = make()
    assert s.observe(row(T0, upstream=0.5)) == "opened"


def test_a_brief_lull_does_not_split_one_storm_in_two():
    s = make()
    s.observe(row(T0, rain=0.5))
    s.observe(row(T0 + HOUR, rain=0.0))          # a pause, not the end
    s.observe(row(T0 + 2 * HOUR, rain=0.4))
    assert s.count(completed_only=False) == 1
    assert s.count() == 0                         # still open


def test_event_closes_after_the_quiet_window():
    s = make()
    s.observe(row(T0, rain=0.5))
    assert s.observe(row(T0 + st.END_QUIET_SECONDS + 60, rain=0.0)) == "closed"
    assert s.count() == 1
    event = s.latest()
    assert event["ended_ts"] is not None


def test_onset_conditions_are_captured_from_the_opening_row():
    s = make()
    s.observe(row(T0, rain=0.5, api_index_in=2.75, soil_moisture_mean_pct=81.0,
                  snow_water_equivalent_in=1.2, rain_on_snow_flag=True))
    e = s.latest()
    assert e["api_at_onset_in"] == 2.75
    assert e["soil_at_onset_pct"] == 81.0
    assert e["swe_at_onset_in"] == 1.2
    assert e["rain_on_snow"] == 1


def test_peaks_track_the_maximum_over_the_event():
    s = make()
    s.observe(row(T0, rain=0.3))
    s.observe(row(T0 + 300, rain=0.9, stage_ft=2.4, rate_of_rise_in_min=0.08), alert_tier=3)
    s.observe(row(T0 + 600, rain=0.5, stage_ft=1.8), alert_tier=1)
    e = s.latest()
    assert e["peak_rain_1h_in"] == 0.9
    assert e["peak_stage_ft"] == 2.4          # not overwritten by the later lower value
    assert e["peak_rate_of_rise_in_min"] == 0.08
    assert e["peak_alert_tier"] == 3


def test_accumulation_takes_the_largest_window_rather_than_summing_samples():
    # rain_24h_in is already a rolling sum; adding each sample would count it many times.
    s = make()
    s.observe(row(T0, rain=0.5, rain_24h_in=0.5))
    s.observe(row(T0 + 300, rain=0.5, rain_24h_in=1.1))
    s.observe(row(T0 + 600, rain=0.5, rain_24h_in=0.9))
    assert s.latest()["max_24h_rain_in"] == 1.1


def test_missing_response_features_leave_nulls_rather_than_zeros():
    # No creek gauge yet — the event must record "unknown", not a fake 0.0 peak.
    s = make()
    s.observe(row(T0, rain=0.5))
    e = s.latest()
    assert e["peak_stage_ft"] is None
    assert e["peak_rate_of_rise_in_min"] is None


def test_count_gates_on_completed_events_only():
    s = make()
    s.observe(row(T0, rain=0.5))
    assert s.count() == 0                     # an open storm is not yet an observation
    s.observe(row(T0 + st.END_QUIET_SECONDS + 60, rain=0.0))
    assert s.count() == 1


def test_a_restart_mid_storm_resumes_the_open_event():
    d = Path(tempfile.mkdtemp())
    first = StormLog(d)
    first.observe(row(T0, rain=0.5))
    reopened = StormLog(d)                    # as after an add-on restart
    reopened.observe(row(T0 + 300, rain=0.6))
    assert reopened.count(completed_only=False) == 1


def test_annotation_is_preserved():
    s = make()
    s.observe(row(T0, rain=0.5))
    s.annotate(s.latest()["id"], "basement stayed dry; culvert ran full")
    assert "culvert" in s.latest()["notes"]


def test_legacy_table_is_migrated_not_dropped():
    d = Path(tempfile.mkdtemp())
    db = d / "events.sqlite"
    with sqlite3.connect(db) as con:          # the original 0.1.0 schema
        con.execute("CREATE TABLE storm_events (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    " started_ts REAL NOT NULL, ended_ts REAL, peak_stage_ft REAL,"
                    " notes TEXT)")
        con.execute("INSERT INTO storm_events (started_ts, notes) VALUES (?,?)",
                    (T0, "hand-annotated before the upgrade"))
    s = StormLog(d)
    assert s.count(completed_only=False) == 1
    assert "hand-annotated" in s.latest()["notes"]
    assert "api_at_onset_in" in s.latest()     # new columns added alongside


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()

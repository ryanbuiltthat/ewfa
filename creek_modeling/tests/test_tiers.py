"""Plain-assert tests for tier evaluation. Run: python creek_modeling/tests/test_tiers.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.features import FeatureRow  # noqa: E402
from app.tiers import compute_tier  # noqa: E402


def row(**kw):
    """A feature row with nothing elevated and no creek gauge, plus overrides."""
    base = dict(
        ts=0.0, stage_ft=None, rate_of_rise_in_min=None,
        soil_moisture_mean_pct=40.0, soil_moisture_near_house_pct=40.0,
        soil_moisture_near_creek_pct=40.0, ponding_flag=False,
    )
    base.update(kw)
    return FeatureRow(**base)


def test_quiet_conditions_are_all_clear():
    tier, label, reasons = compute_tier(row(), 0.0)
    assert (tier, label) == (0, "All-clear")
    assert reasons == []


def test_missing_features_never_fire_a_tier():
    # Every forecast/rain feature is None before its source has polled once.
    tier, _, reasons = compute_tier(row(soil_moisture_mean_pct=None), None)
    assert tier == 0
    assert reasons == []


def test_advisory_needs_both_qpf_and_wet_soil():
    # Forecast rain alone onto dry ground is not an advisory...
    assert compute_tier(row(qpf_24h_in=1.5), 0.0)[0] == 0
    # ...nor is wet ground alone...
    assert compute_tier(row(soil_moisture_mean_pct=75.0), 0.0)[0] == 0
    # ...but together they are (spec §6 Tier 0).
    tier, label, reasons = compute_tier(row(qpf_24h_in=1.5, soil_moisture_mean_pct=75.0), 0.0)
    assert (tier, label) == (1, "Advisory")
    assert "forecast" in reasons[0]


def test_heavy_short_fuse_qpf_is_an_advisory_on_its_own():
    tier, label, _ = compute_tier(row(qpf_6h_in=0.9), 0.0)
    assert (tier, label) == (1, "Advisory")


def test_ponding_is_an_advisory():
    tier, label, reasons = compute_tier(row(ponding_flag=True), 0.0)
    assert (tier, label) == (1, "Advisory")
    assert reasons == ["low-lying ground already ponding"]


def test_upstream_rain_is_a_watch_without_any_gauge():
    tier, label, reasons = compute_tier(row(upstream_rain_3h_in=0.8), 0.0)
    assert (tier, label) == (2, "Watch")
    assert "upstream rain in 3 h" in reasons[0]
    # This is the whole point of the slice: no stage, no rate-of-rise, still a warning.


def test_onsite_rain_is_a_watch():
    assert compute_tier(row(rain_6h_in=1.2), 0.0)[0] == 2


def test_an_inbound_radar_cell_is_a_watch_before_any_gauge_sees_rain():
    """The 2g slice's whole purpose: on the dominant W/NW approach the upstream gauges
    are geometrically behind the house, so the radar track is the only leading signal."""
    tier, label, reasons = compute_tier(
        row(radar_threat_eta_min=25.0, radar_threat_cells=2.0, radar_threat_max_dbz=52.0), 0.0)
    assert (tier, label) == (2, "Watch")
    assert "radar" in reasons[0] and "25 min" in reasons[0]


def test_a_distant_or_absent_radar_cell_never_fires():
    # Beyond the gate: inbound but 80 min out is not yet a watch...
    assert compute_tier(row(radar_threat_eta_min=80.0, radar_threat_cells=1.0), 0.0)[0] == 0
    # ...and None (no inbound cell, or the source never polled) must never fire.
    assert compute_tier(row(radar_threat_eta_min=None), 0.0)[0] == 0


def test_stage_drives_warning_and_emergency():
    assert compute_tier(row(stage_ft=2.1), 0.0)[:2] == (3, "Warning")
    assert compute_tier(row(stage_ft=2.9), 0.0)[:2] == (4, "Emergency")


def test_rate_of_rise_drives_warning():
    tier, _, reasons = compute_tier(row(rate_of_rise_in_min=0.06), 0.0)
    assert tier == 3
    assert "rising" in reasons[0]


def test_probability_still_escalates():
    assert compute_tier(row(), 0.25)[0] == 2
    assert compute_tier(row(), 0.60)[0] == 3
    assert compute_tier(row(), 0.85)[0] == 4


def test_highest_tier_wins_and_only_its_reasons_are_returned():
    tier, label, reasons = compute_tier(
        row(ponding_flag=True, upstream_rain_3h_in=1.0, stage_ft=2.2), 0.0
    )
    assert (tier, label) == (3, "Warning")
    assert reasons == ["stage 2.20 ft"]          # no advisory/watch noise


def test_nws_products_force_promote_the_tier():
    # Quiet instruments, but a forecaster has issued a product: escalate anyway (spec §6).
    assert compute_tier(row(nws_flood_watch=1.0), 0.0)[:2] == (1, "Advisory")
    assert compute_tier(row(nws_flood_warning=1.0), 0.0)[:2] == (2, "Watch")
    assert compute_tier(row(nws_flash_flood_warning=1.0), 0.0)[:2] == (3, "Warning")
    _, _, reasons = compute_tier(row(nws_flood_warning=1.0), 0.0)
    assert reasons == ["NWS Flood Warning in effect"]


def test_nws_floor_never_lowers_an_earned_tier():
    # Stage already says Emergency; a mere Flood Watch must not pull it down.
    tier, label, _ = compute_tier(row(stage_ft=2.9, nws_flood_watch=1.0), 0.0)
    assert (tier, label) == (4, "Emergency")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()

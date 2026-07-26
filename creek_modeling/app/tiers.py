"""Alert-tier evaluation (spec §6).

Lives in the add-on so the tier is published over MQTT (and auto-created via discovery)
instead of living in an HA template.

Tiers 0–3 in the spec table are *escalation* levels; §6 also calls for an explicit
all-clear. This module therefore emits 0–4, where 0 is All-clear and 1–4 are the spec's
Advisory / Watch / Warning / Emergency:

    0 All-clear   nothing elevated
    1 Advisory    forecast risk        — QPF + antecedent wetness      (no gauge needed)
    2 Watch       rain materializing   — upstream/on-site accumulation (no gauge needed)
    3 Warning     creek responding     — stage / rate-of-rise          (needs the gauge)
    4 Emergency   flood imminent       — stage near bank / high P      (needs the gauge)

The Advisory and Watch rules are deliberately gauge-independent: they run off forecast
and rainfall features that are already flowing, so the system issues useful warnings
before the SEN0676 is mounted. Warning/Emergency stay dormant (their inputs are None)
until the creek node reports.

Every rule that fires contributes a human-readable reason, published as an attribute so
the dashboard can say *why* rather than just showing a number.

ALL THRESHOLDS BELOW ARE PLACEHOLDERS AND UNCALIBRATED. Stage values depend on the
surveyed datum (open question #5), the soil percentages on WH51 field calibration (open
question #7), and the rainfall values on observed storms (Phase 3). Treat a tier as a
prompt to go look, not as a validated alarm.
"""
from __future__ import annotations

from .features import FeatureRow

TIER_LABELS = {
    0: "All-clear",
    1: "Advisory",
    2: "Watch",
    3: "Warning",
    4: "Emergency",
}

# --- Tier 1 Advisory: forecast risk (spec §6 "QPF >= X in 24 h AND soil >= Y%") ---
ADVISORY_QPF_24H_IN = 1.0
ADVISORY_SOIL_PCT = 70.0
ADVISORY_QPF_6H_IN = 0.75          # heavy short-fuse rain earns an advisory on its own

# --- Tier 2 Watch: rain materializing upstream, creek not yet responding ---
WATCH_UPSTREAM_3H_IN = 0.75
WATCH_UPSTREAM_6H_IN = 1.00
WATCH_ONSITE_6H_IN = 1.00
WATCH_PROBABILITY = 0.20

# --- Tier 3 Warning: creek responding (gauge required) ---
WARNING_STAGE_FT = 2.0             # bank top is +3 ft (spec §2)
WARNING_RATE_OF_RISE_IN_MIN = 0.05
WARNING_PROBABILITY = 0.50

# --- Tier 4 Emergency: overbank imminent (gauge required) ---
EMERGENCY_STAGE_FT = 2.5           # bank top minus a 6 in margin
EMERGENCY_PROBABILITY = 0.80


def _ge(value: float | None, threshold: float) -> bool:
    """True only when we actually have a reading — a missing feature never fires a tier."""
    return value is not None and value >= threshold


def compute_tier(row: FeatureRow, flood_probability: float | None) -> tuple[int, str, list[str]]:
    """Highest tier whose conditions are met, with the reasons that got it there."""
    p = flood_probability or 0.0
    reasons: list[tuple[int, str]] = []

    # --- Tier 1 Advisory (forecast only; no gauge needed) ---
    if _ge(row.qpf_24h_in, ADVISORY_QPF_24H_IN) and _ge(row.soil_moisture_mean_pct, ADVISORY_SOIL_PCT):
        reasons.append((1, f"{row.qpf_24h_in:.2f}\" forecast in 24 h onto "
                           f"{row.soil_moisture_mean_pct:.0f}% soil moisture"))
    if _ge(row.qpf_6h_in, ADVISORY_QPF_6H_IN):
        reasons.append((1, f"{row.qpf_6h_in:.2f}\" forecast in the next 6 h"))
    if row.ponding_flag:
        reasons.append((1, "low-lying ground already ponding"))

    # --- Tier 2 Watch (rain on the ground upstream; still no gauge needed) ---
    if _ge(row.upstream_rain_3h_in, WATCH_UPSTREAM_3H_IN):
        reasons.append((2, f"{row.upstream_rain_3h_in:.2f}\" upstream rain in 3 h"))
    if _ge(row.upstream_rain_6h_in, WATCH_UPSTREAM_6H_IN):
        reasons.append((2, f"{row.upstream_rain_6h_in:.2f}\" upstream rain in 6 h"))
    if _ge(row.rain_6h_in, WATCH_ONSITE_6H_IN):
        reasons.append((2, f"{row.rain_6h_in:.2f}\" on-site rain in 6 h"))
    if p >= WATCH_PROBABILITY:
        reasons.append((2, f"model probability {p * 100:.0f}%"))

    # --- Tier 3 Warning (needs the creek node) ---
    if _ge(row.stage_ft, WARNING_STAGE_FT):
        reasons.append((3, f"stage {row.stage_ft:.2f} ft"))
    if _ge(row.rate_of_rise_in_min, WARNING_RATE_OF_RISE_IN_MIN):
        reasons.append((3, f"rising {row.rate_of_rise_in_min:.3f} in/min"))
    if p >= WARNING_PROBABILITY:
        reasons.append((3, f"model probability {p * 100:.0f}%"))

    # --- Tier 4 Emergency (needs the creek node) ---
    if _ge(row.stage_ft, EMERGENCY_STAGE_FT):
        reasons.append((4, f"stage {row.stage_ft:.2f} ft — near bank top"))
    if p >= EMERGENCY_PROBABILITY:
        reasons.append((4, f"model probability {p * 100:.0f}%"))

    if not reasons:
        return 0, TIER_LABELS[0], []

    tier = max(t for t, _ in reasons)
    # Only explain the tier that was actually reached; lower-tier noise is not useful.
    return tier, TIER_LABELS[tier], [text for t, text in reasons if t == tier]

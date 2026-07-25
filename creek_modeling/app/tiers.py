"""Alert-tier mapping (spec §6).

Moved into the add-on so the tier is published over MQTT (and auto-created via
discovery) instead of living in an HA template. PLACEHOLDER thresholds — they are
UNCALIBRATED (open question #7) and will fold in stage + rate-of-rise once the
ESPHome creek node is reporting. Not a live alert yet.
"""
from __future__ import annotations

TIER_LABELS = {0: "All-clear", 1: "Watch", 2: "Warning", 3: "Emergency"}


def compute_tier(flood_probability: float | None, ponding: bool) -> tuple[int, str]:
    """Map model probability (0..1) + ponding flag to a tier 0..3 and its label."""
    p = (flood_probability or 0.0) * 100.0
    if p >= 80:
        tier = 3
    elif p >= 50:
        tier = 2
    elif p >= 20 or ponding:
        tier = 1
    else:
        tier = 0
    return tier, TIER_LABELS[tier]

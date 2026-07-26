"""Rainfall→response lag estimation (spec §7 Phase 3).

§1 calls the rainfall-to-crest lag "the warning window", and measuring it empirically a
core project outcome. This estimates it by cross-correlation: shift a rainfall series
forward against a response series and take the shift that lines them up best.

The response series is chosen by what exists:

  * `stage_ft` — the real target, once the SEN0676 is mounted.
  * `usgs_leggetts_rise_3h_ft` — the fallback while it is not. A different, larger basin
    with its own longer lag, so the number it yields is **not** Ackerly's lag. It is a
    sanity check that the correlation machinery works and that our rainfall inputs track a
    real hydrograph at all — the "downstream-gauge sanity comparison" §7 asks for. The
    result is labelled with the series used so the two are never confused.

Correlation is computed on first differences of the response, not its level: a rising
limb is what rainfall causes, whereas the level itself is dominated by baseflow and would
correlate with anything that trends. Pearson r is computed directly rather than pulled
from numpy so the estimator has no dependency beyond pandas.
"""
from __future__ import annotations

import logging
import math

log = logging.getLogger("app.lag")

# Candidate lags to test, in minutes. §1 expects "tens of minutes to a few hours" for
# Ackerly; the downstream gauges respond slower, so the range runs out to 12 h.
MIN_LAG_MIN = 0
MAX_LAG_MIN = 720
LAG_STEP_MIN = 15

# Guardrails — a lag fitted on too little data, or on a period with no rain, is noise.
MIN_PAIRS = 24                 # overlapping samples after shifting
MIN_RAIN_TOTAL_IN = 0.25       # the window must contain a real storm
MIN_CORRELATION = 0.30         # below this, report no estimate rather than a bad one

# A longer lag must beat the incumbent by this much to displace it. Storms recur, so
# shifting rain forward by a whole inter-storm interval lines it up with the *next*
# storm's rise and scores just as well — and often a hair better, since the longer shift
# drops the edge storms and with them the samples that fit worst. Physically the earliest
# lag that explains the response is the causal one, so ties and near-ties go to it.
TIE_MARGIN = 0.02

RESPONSE_PREFERENCE = (
    ("stage_ft", "creek stage"),
    ("usgs_leggetts_rise_3h_ft", "USGS Leggetts (proxy)"),
    ("usgs_tunkhannock_rise_3h_ft", "USGS Tunkhannock (proxy)"),
)
RAIN_PREFERENCE = ("upstream_rain_1h_in", "rain_1h_in")


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _pick(df, candidates) -> tuple[str, str] | None:
    for name, label in candidates:
        if name in df.columns and df[name].notna().sum() >= MIN_PAIRS:
            return name, label
    return None


def estimate_lag(df) -> dict:
    """Best-fitting lag in minutes, with the series and correlation behind it.

    Returns a dict that is always safe to publish: `lag_minutes` is None whenever the
    data cannot support an estimate, with `reason` saying why.
    """
    result = {"lag_minutes": None, "correlation": None, "response": None,
              "rain_series": None, "samples": 0, "reason": None}

    if df is None or len(df) < MIN_PAIRS:
        result["reason"] = "not enough data yet"
        return result

    response = _pick(df, RESPONSE_PREFERENCE)
    if response is None:
        result["reason"] = "no response series available"
        return result
    response_col, response_label = response
    result["response"] = response_label

    rain_col = next((c for c in RAIN_PREFERENCE
                     if c in df.columns and df[c].notna().sum() >= MIN_PAIRS), None)
    if rain_col is None:
        result["reason"] = "no rainfall series available"
        return result
    result["rain_series"] = rain_col

    frame = df[["ts", rain_col, response_col]].dropna().sort_values("ts")
    if len(frame) < MIN_PAIRS:
        result["reason"] = "not enough overlapping samples"
        return result
    if float(frame[rain_col].max() or 0.0) < MIN_RAIN_TOTAL_IN:
        result["reason"] = "no significant rain in the record yet"
        return result

    times = frame["ts"].tolist()
    rain = [float(v) for v in frame[rain_col]]
    level = [float(v) for v in frame[response_col]]
    # First differences: rainfall drives the *rise*, not the absolute level.
    rises = [level[i] - level[i - 1] for i in range(1, len(level))]
    rain_at = dict(zip(times, rain))

    best = None
    for lag in range(MIN_LAG_MIN, MAX_LAG_MIN + 1, LAG_STEP_MIN):
        xs, ys = [], []
        offset = lag * 60.0
        for i, rise in enumerate(rises, start=1):
            source_ts = _nearest(times, times[i] - offset)
            if source_ts is None:
                continue
            xs.append(rain_at[source_ts])
            ys.append(rise)
        if len(xs) < MIN_PAIRS:
            continue
        r = _pearson(xs, ys)
        if r is not None and (best is None or r > best[1] + TIE_MARGIN):
            best = (lag, r, len(xs))

    if best is None:
        result["reason"] = "no usable overlap at any lag"
        return result

    lag, r, samples = best
    result["samples"] = samples
    result["correlation"] = round(r, 3)
    if r < MIN_CORRELATION:
        result["reason"] = f"best correlation {r:.2f} below {MIN_CORRELATION}"
        return result

    result["lag_minutes"] = lag
    log.info("Lag estimate: %d min against %s (r=%.2f, n=%d)",
             lag, response_label, r, samples)
    return result


def _nearest(times: list[float], target: float, tolerance: float = 600.0) -> float | None:
    """Closest sample timestamp to `target`, or None if the gap is too large.

    The fast loop is nominally every 5 min but restarts and slow polls leave gaps; a
    tolerance keeps those from silently pairing rain with a response hours away.
    """
    if not times or target < times[0] - tolerance:
        return None
    lo, hi = 0, len(times) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if times[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    best = min((times[max(0, lo - 1)], times[lo]), key=lambda t: abs(t - target))
    return best if abs(best - target) <= tolerance else None

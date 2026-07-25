"""On-site rain accumulator.

Home Assistant exposes an Ecowitt *rain rate* (in/hr or mm/hr) but no rolling
multi-window totals. This samples the rate each fast loop, integrates rate x elapsed
time into a 72 h ring persisted under `/data/state/`, and reports 1/3/6/24/72 h
accumulations (spec §5). All values are normalized to **inches**.

Cold start: totals build up over the first 72 h. Gaps (add-on downtime) are not
integrated — an elapsed interval longer than `MAX_GAP_S` is treated as a break, not
72 h of the current rate.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("app.sources.rain")

WINDOWS_H = (1, 3, 6, 24, 72)
RETAIN_S = 72 * 3600
MAX_GAP_S = 15 * 60          # don't integrate across a gap longer than this
MM_PER_INCH = 25.4


class RainAccumulator:
    name = "rain"
    refresh_seconds = 0        # sample every fast loop

    def __init__(self, data_dir: Path, rate_entity: str, ha, now_fn=time.time):
        self._entity = rate_entity
        self._ha = ha
        self._now = now_fn                                   # injectable for tests
        self._path = data_dir / "state" / "rain_accum.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._increments: list[list[float]] = self._load()   # [[ts, inches], ...]
        self._last_ts: float | None = None                   # not persisted — avoids
        self._in_per_unit: float | None = None               # gap integration on restart

    def _load(self) -> list[list[float]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [list(x) for x in data.get("increments", [])]
        except (FileNotFoundError, ValueError, OSError):
            return []

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps({"increments": self._increments}), encoding="utf-8")
        except OSError as exc:
            log.warning("could not persist rain accumulator: %s", exc)

    def _unit_factor(self) -> float:
        """Inches per reported unit (1.0 for in/hr, 1/25.4 for mm/hr). Cached."""
        if self._in_per_unit is None:
            unit = (self._ha.get_unit(self._entity) or "").lower()
            self._in_per_unit = (1.0 / MM_PER_INCH) if "mm" in unit else 1.0
        return self._in_per_unit

    def poll(self) -> dict:
        now = self._now()
        rate = self._ha.get_float(self._entity)   # per hour, in the entity's unit
        if rate is not None and self._last_ts is not None:
            dt_s = now - self._last_ts
            if 0 < dt_s <= MAX_GAP_S:
                inches = max(0.0, rate) * self._unit_factor() * (dt_s / 3600.0)
                if inches > 0:
                    self._increments.append([now, inches])
        self._last_ts = now

        cutoff = now - RETAIN_S
        self._increments = [x for x in self._increments if x[0] >= cutoff]
        self._save()

        return {
            f"rain_{w}h_in": round(sum(inc for ts, inc in self._increments
                                       if ts >= now - w * 3600), 3)
            for w in WINDOWS_H
        }

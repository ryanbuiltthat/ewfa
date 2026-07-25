"""Forecast/upstream data sources (spec Addendum C).

Each source exposes `name`, `refresh_seconds`, and `poll() -> dict[str, float|None]`.
`SourceCoordinator` polls each on its own cadence, merges the latest values, and keeps
the last-good result when a source errors — so a flaky API never stalls or crashes the
fast loop. All rainfall features are in inches.

The set of feature keys produced is declared in `FEATURE_KEYS` so the FeatureRow,
discovery, and dataset stay in sync.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from ..config import Config
from ..ha import HAClient
from .nws import NwsQpf
from .rain import RainAccumulator

log = logging.getLogger("app.sources")

# Numeric features produced by slice 2a, in publish/record order.
FEATURE_KEYS = (
    "rain_1h_in", "rain_3h_in", "rain_6h_in", "rain_24h_in", "rain_72h_in",
    "qpf_6h_in", "qpf_24h_in",
)


class SourceCoordinator:
    def __init__(self, cfg: Config, ha: HAClient, data_dir: Path):
        self._sources = []
        if cfg.onsite_rain_rate_entity:
            self._sources.append(RainAccumulator(data_dir, cfg.onsite_rain_rate_entity, ha))
        else:
            log.warning("onsite_rain_rate_entity unset — rain accumulation disabled")

        latlon = ha.get_lat_lon()
        if latlon:
            self._sources.append(NwsQpf(*latlon))
            log.info("NWS QPF enabled for lat/lon %.4f,%.4f", *latlon)
        else:
            log.warning("No lat/lon from HA config — NWS QPF disabled")

        self._cache: dict[str, float | None] = {}
        self._next_poll: dict[str, float] = {}

    def features(self) -> dict:
        """Merged latest feature values; polls each source only when its interval elapses."""
        now = time.monotonic()
        for src in self._sources:
            if now >= self._next_poll.get(src.name, 0.0):
                try:
                    self._cache.update(src.poll())
                except Exception:  # keep last-good cache; never break the loop
                    log.exception("source %s poll failed", src.name)
                self._next_poll[src.name] = now + src.refresh_seconds
        return {k: self._cache.get(k) for k in FEATURE_KEYS}

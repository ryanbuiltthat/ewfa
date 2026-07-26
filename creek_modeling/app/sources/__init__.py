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
from .alerts import NwsAlerts
from .nwm import NwmReach
from .nws import NwsQpf
from .rain import RainAccumulator
from .snodas import SnodasSwe
from .usgs import SITES as USGS_SITES, UsgsDownstream, feature_keys as usgs_feature_keys
from .wu import WuUpstream

log = logging.getLogger("app.sources")

# Numeric features produced by the ingestion sources, in publish/record order.
FEATURE_KEYS = (
    # 2a — on-site rain + NWS QPF
    "rain_1h_in", "rain_3h_in", "rain_6h_in", "rain_24h_in", "rain_72h_in",
    "qpf_6h_in", "qpf_24h_in",
    # 2f — antecedent precipitation index (rides on the on-site rain samples)
    "api_index_in",
    # 2b — upstream WU + NWM reach
    "upstream_rain_1h_in", "upstream_rain_3h_in", "upstream_rain_6h_in",
    "upstream_rain_24h_in", "upstream_rain_72h_in", "upstream_precip_today_in",
    "nwm_flow_cfs", "nwm_flow_max_cfs",
    # 2c — USGS downstream gauges
    *usgs_feature_keys(),
    # 2d — NWS active alert products
    "nws_flood_watch", "nws_flood_warning", "nws_flash_flood_warning", "nws_alert_count",
    # 2e — SNODAS snowpack
    "snow_water_equivalent_in",
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
            self._sources.append(NwsAlerts(*latlon))
            log.info("NWS QPF + alerts enabled for lat/lon %.4f,%.4f", *latlon)
            if cfg.snodas_swe:
                self._sources.append(SnodasSwe(*latlon, data_dir))
                log.info("SNODAS SWE enabled")
        else:
            log.warning("No lat/lon from HA config — NWS QPF, alerts and SNODAS disabled")

        if cfg.wu_api_key and cfg.upstream_pws_ids:
            self._sources.append(WuUpstream(cfg.wu_api_key, cfg.upstream_pws_ids, data_dir))
            log.info("WU upstream enabled for %d station(s)", len(cfg.upstream_pws_ids))
        else:
            log.info("WU upstream disabled (needs wu_api_key + upstream_pws_ids)")

        # `bashio::config` renders an unset optional as the literal string "null", which
        # would otherwise enable the source and fail every poll against a bogus reach.
        reach_id = cfg.nwm_reach_id.strip()
        if reach_id and reach_id != "null":
            self._sources.append(NwmReach(reach_id))
            log.info("NWM reach %s enabled", reach_id)
        else:
            log.info("NWM reach disabled (needs nwm_reach_id)")

        if cfg.usgs_downstream:
            self._sources.append(UsgsDownstream())
            log.info("USGS downstream gauges enabled: %s", ", ".join(USGS_SITES))
        else:
            log.info("USGS downstream gauges disabled")

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

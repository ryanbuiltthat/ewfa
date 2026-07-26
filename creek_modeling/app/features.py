"""Feature builders.

Builds the live feature row each fast loop: the cheap local features computed here
(stage, rate-of-rise, soil moisture, ponding) plus everything the SourceCoordinator
ingests (rain accumulations, QPF, upstream PWS, NWM reach, USGS downstream gauges).
Still outstanding from spec §5: the Antecedent Precipitation Index, SNODAS SWE and the
rain-on-snow flag, and Google flood status.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass

from .config import Config
from .ha import HAClient

log = logging.getLogger("app.features")


@dataclass
class FeatureRow:
    ts: float                       # unix seconds
    stage_ft: float | None          # current creek stage
    rate_of_rise_in_min: float | None
    soil_moisture_mean_pct: float | None
    soil_moisture_near_house_pct: float | None   # WH51 #1, willow tree
    soil_moisture_near_creek_pct: float | None   # WH51 #2, closest to creek
    ponding_flag: bool              # low-lying sensors saturated -> fast runoff
    # --- forecast/upstream features (Addendum C, filled by SourceCoordinator) ---
    rain_1h_in: float | None = None
    rain_3h_in: float | None = None
    rain_6h_in: float | None = None
    rain_24h_in: float | None = None
    rain_72h_in: float | None = None
    qpf_6h_in: float | None = None
    qpf_24h_in: float | None = None
    upstream_rain_1h_in: float | None = None
    upstream_rain_3h_in: float | None = None
    upstream_rain_6h_in: float | None = None
    upstream_rain_24h_in: float | None = None
    upstream_rain_72h_in: float | None = None
    upstream_precip_today_in: float | None = None
    nwm_flow_cfs: float | None = None
    nwm_flow_max_cfs: float | None = None
    # USGS downstream gauges — no gauge of our own yet, so these carry the only
    # observed rainfall->response signal available (spec §1, slice 2c).
    usgs_leggetts_gage_ft: float | None = None
    usgs_leggetts_flow_cfs: float | None = None
    usgs_leggetts_rise_3h_ft: float | None = None
    usgs_tunkhannock_gage_ft: float | None = None
    usgs_tunkhannock_flow_cfs: float | None = None
    usgs_tunkhannock_rise_3h_ft: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# Above this soil-moisture reading the low-lying areas are effectively saturated
# and "pond", shortening the rainfall->runoff response. Tune with observed storms.
PONDING_SATURATION_PCT = 85.0


class FeatureBuilder:
    def __init__(self, cfg: Config, ha: HAClient, sources=None):
        self._cfg = cfg
        self._ha = ha
        self._sources = sources   # SourceCoordinator | None (Addendum C)
        self._last_stage: tuple[float, float] | None = None  # (ts, stage_ft)

    def _rate_of_rise(self, ts: float, stage_ft: float | None) -> float | None:
        """Inches per minute since the previous sample; None on first/invalid."""
        if stage_ft is None:
            return None
        prev = self._last_stage
        self._last_stage = (ts, stage_ft)
        if prev is None:
            return None
        prev_ts, prev_stage = prev
        dt_min = (ts - prev_ts) / 60.0
        if dt_min <= 0:
            return None
        return (stage_ft - prev_stage) * 12.0 / dt_min

    def build(self) -> FeatureRow:
        ts = time.time()
        stage_ft = self._ha.get_float(self._cfg.stage_entity)

        soils = [self._ha.get_float(e) for e in self._cfg.soil_moisture_entities]
        near_house = soils[0] if len(soils) >= 1 else None
        near_creek = soils[1] if len(soils) >= 2 else None
        present = [s for s in soils if s is not None]
        soil_mean = sum(present) / len(present) if present else None
        ponding = any(s >= PONDING_SATURATION_PCT for s in present)

        row = FeatureRow(
            ts=ts,
            stage_ft=stage_ft,
            rate_of_rise_in_min=self._rate_of_rise(ts, stage_ft),
            soil_moisture_mean_pct=soil_mean,
            soil_moisture_near_house_pct=near_house,
            soil_moisture_near_creek_pct=near_creek,
            ponding_flag=ponding,
        )
        if self._sources is not None:
            for key, value in self._sources.features().items():
                setattr(row, key, value)
        log.debug("Built feature row: %s", row)
        return row

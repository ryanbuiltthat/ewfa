"""Inference + model registry.

Until >= `min_events_for_ml` storms are captured (spec §5), this returns a
transparent, conservative *threshold* estimate rather than an ML prediction —
early months are data-collection + threshold alerting only. The ML path
(gradient boosting) slots into `_ml_predict` once the registry has a promoted
artifact; the caller interface does not change.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Config
from .features import FeatureRow
from .registry import ModelRegistry

log = logging.getLogger("app.model")


@dataclass
class Prediction:
    flood_probability: float        # 0..1
    predicted_crest_ft: float | None
    lag_estimate_min: float | None
    method: str                     # "threshold" | "ml:<version>"


class Model:
    def __init__(self, cfg: Config, registry: ModelRegistry):
        self._cfg = cfg
        # Share the one registry instance the service owns, so a promote/rollback
        # command is visible here on the next prediction without a reload race.
        self._registry = registry
        self._artifact = self._load_promoted()

    def _load_promoted(self):
        """Load the promoted ML artifact if the registry names one; else None."""
        version = self._registry.active_version
        if not version:
            return None
        # Phase 4: actually load models/<version>.pkl here.
        log.info("Registry active artifact %s (loading deferred to Phase 4)", version)
        return None

    def event_count(self) -> int:
        return self._registry.event_count

    def predict(self, row: FeatureRow) -> Prediction:
        if self._artifact is not None and self.event_count() >= self._cfg.min_events_for_ml:
            return self._ml_predict(row)
        return self._threshold_predict(row)

    def _threshold_predict(self, row: FeatureRow) -> Prediction:
        """Conservative, explainable proxy. NOT a calibrated probability yet.

        Combines rate-of-rise with an antecedent-wetness bump: when the low-lying
        soil sensors are saturated/ponding, the same rain produces faster runoff,
        so nudge probability up. Real thresholds get tuned against §6 tiers.
        """
        p = 0.0
        ror = row.rate_of_rise_in_min or 0.0
        if ror > 0:
            # 0 in/min -> 0; ~0.5 in/min sustained -> ~0.5, saturating toward 1.
            p = min(1.0, ror / 0.5 * 0.5)
        if row.ponding_flag:
            p = min(1.0, p + 0.15)
        return Prediction(
            flood_probability=round(p, 3),
            predicted_crest_ft=None,          # requires lag/response fit (Phase 3)
            lag_estimate_min=None,            # empirical, measured from storms (Phase 3)
            method="threshold",
        )

    def _ml_predict(self, row: FeatureRow) -> Prediction:  # pragma: no cover - Phase 4
        raise NotImplementedError("Gradient-boosting inference lands in Phase 4.")

"""Frozen causal runtime adapter for BULLISH_STRICT_top25_gbt_v2."""
from __future__ import annotations

import math

from studies.nt_reduced_f3_top25_population_parity_smoke.implementation.reduced_feature_engine import (
    ReducedFeatureEngine,
)
from studies.full_trade_path_builder.implementation.phase_a_core import SourceProvenance

MODEL_ID = "BULLISH_STRICT_top25_gbt_v2"
ENTRY_DIRECTION = -1
FEATURES = (
    "rolling_5m_low_signed_distance_atr",
    "rth_elapsed_seconds",
    "rolling_15m_high_signed_distance_atr",
    "rolling_60m_high_signed_distance_atr",
    "rolling_15m_low_signed_distance_atr",
    "rolling_30m_low_signed_distance_atr",
    "price_change_points_60s",
    "rolling_30m_high_signed_distance_atr",
    "range_points_1800s",
    "opening_range_30m_low_developing_signed_distance_points",
    "est_bear_vol_sum_300s",
    "full_level_envelope_width_atr",
    "rth_vol_cum",
    "est_delta_sum_1800s",
    "price_change_atr_60s",
    "prior_day_close_signed_distance_atr",
    "up_down_vol_ratio_1800s",
    "price_change_atr_30s",
    "pct_levels_behind_trade",
    "prior_day_low_signed_distance_points",
    "opening_range_30m_low_final_signed_distance_points",
    "vol_max_1s_1800s",
    "price_position_in_full_envelope",
    "rth_abs_delta_cum",
    "n_levels_below",
)


class FrozenBullishAdapter:
    """Independent state instance using the frozen order and short mapping."""

    def __init__(self):
        self.features = list(FEATURES)
        self.engine = ReducedFeatureEngine(self.features)

    def snapshot(self, decision_ns, reference_price, atr_at_checkpoint, provenance):
        if not isinstance(provenance, SourceProvenance):
            raise TypeError("SourceProvenance required")
        provenance.assert_admissible(decision_ns)
        if not math.isfinite(atr_at_checkpoint) or atr_at_checkpoint <= 0:
            return [float("nan")] * 25, {f: True for f in FEATURES}, True
        vector, nulls, any_null = self.engine.ordered_vector(
            decision_ns, reference_price, atr_at_checkpoint
        )
        finite = [v is not None and isinstance(v, (int, float)) and math.isfinite(float(v))
                  for v in vector]
        any_bad = any_null or not all(finite)
        return [float(v) if ok else float("nan") for v, ok in zip(vector, finite)], nulls, any_bad

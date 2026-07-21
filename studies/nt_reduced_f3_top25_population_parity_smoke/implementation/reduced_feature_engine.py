"""Wraps the two central, verified trackers (`OHLCVDeltaTracker`,
`PriceLevelTracker`) exactly as `ohlcv_volume_delta_price_level_features/
attach_features.py` already does (audited call pattern, reused not
reinvented), and slices out only the 25 features `F3_top25_gbt_v1` needs.

Does not implement any other feature family (no MedianCenterTracker/F0) --
"do not implement the unused 670 features" is satisfied at the
tracker-instantiation level; the two reused trackers still compute their
full internal feature set per `calculate()` call (there is no partial-
compute mode), only the returned dict is sliced.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from features.trackers.ohlcv_delta import OHLCVDeltaTracker
from features.trackers.price_levels import PriceLevelTracker

ENTRY_DIRECTION = -1  # this population is short-only, confirmed repo-wide this session


class ReducedFeatureEngine:
    def __init__(self, ordered_features: List[str]):
        self.ordered_features = list(ordered_features)
        self.ohlcv = OHLCVDeltaTracker()
        self.price = PriceLevelTracker()
        self._last_1m_close_ts: Optional[int] = None

    # -- update path, mirrors attach_features.py's buffered-replay pattern --
    def update_1s(self, ts_event: int, open_px: float, high: float, low: float,
                  close: float, volume: float) -> dict:
        """Unconditional rolling-window update (A1-A3). Returns the per-bar
        estimate dict so the caller can buffer it for `accumulate_regime_rth`
        once regime/RTH context resolves at the parent minute's close."""
        return self.ohlcv.update(ts_event, open_px, high, low, close, volume)

    def accumulate_regime_rth(self, ts_event: int, high: float, low: float,
                              volume: float, est_delta: float) -> None:
        self.ohlcv.accumulate_regime_rth(ts_event, high, low, volume, est_delta)

    def reset_regime(self, ts_event: int, anchor_price: float) -> None:
        self.ohlcv.reset_regime(ts_event, anchor_price)

    def reset_rth(self, ts_event: int) -> None:
        self.ohlcv.reset_rth(ts_event)

    def end_rth(self) -> None:
        self.ohlcv.end_rth()

    def update_1m(self, ts_event: int, open_px: float, high: float, low: float,
                  close: float, is_rth: bool) -> None:
        self.price.update_1m(ts_event, open_px, high, low, close, is_rth)
        self._last_1m_close_ts = ts_event

    # -- snapshot path --
    def snapshot(self, observation_ts: int, reference_price: float, atr: float) -> Dict[str, object]:
        """Compute the full internal feature dicts from both trackers, then
        slice out exactly `self.ordered_features`, IN ORDER. Returns
        (feature_dict, null_mask_dict) via a single call for atomicity --
        both trackers are read-only at this point (no state mutation)."""
        f_ohlcv = self.ohlcv.calculate(atr=atr)
        f_price = self.price.calculate(observation_ts, reference_price, atr, direction=ENTRY_DIRECTION)
        merged = {**f_ohlcv, **f_price}

        values: Dict[str, object] = {}
        null_mask: Dict[str, bool] = {}
        for feat in self.ordered_features:
            v = merged.get(feat, None)
            values[feat] = v
            null_mask[feat] = v is None
        return values, null_mask

    def ordered_vector(self, observation_ts: int, reference_price: float, atr: float):
        """Returns (list_of_25_values_in_order, null_mask_dict, any_null:bool)."""
        values, null_mask = self.snapshot(observation_ts, reference_price, atr)
        vec = [values[f] for f in self.ordered_features]
        any_null = any(null_mask.values())
        return vec, null_mask, any_null

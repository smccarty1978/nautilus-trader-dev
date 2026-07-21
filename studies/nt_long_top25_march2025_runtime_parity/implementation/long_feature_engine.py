"""Live feature engine for the long TOP25 set.

Unlike the short-side engine (2 trackers), the long TOP25 needs THREE central
trackers, because 6 of its 25 features are regime-center/sequence family:

  OHLCVDeltaTracker    ->  9 features   (absolute; no direction argument)
  PriceLevelTracker    -> 10 features   (direction=+1, the LONG entry)
  MedianCenterTracker  ->  6 features   (regime-direction-relative)

The single genuinely direction-normalized feature in the whole top-100 is
`pct_levels_behind_trade` (rank 25, present here), which is why
PriceLevelTracker is called with direction=+1 rather than the short side's -1.

MedianCenterTracker.calculate() computes
    aligned_* = current_regime * (close - median) / atr
so passing the PREVAILING regime direction (-1) makes the center features
auto-orient bearish -- matching the offline atlas, which built them per-regime.

Offline/live equivalence for all six of these was verified before this engine
was written (studies/.../results/seq_feature_equivalence.json: max_abs_diff 0.0
on seq_*; 7.105e-15 on the median centers). Do not "fix" them here.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Dict, List, Optional

from features.trackers.median_center import MedianCenterTracker
from features.trackers.ohlcv_delta import OHLCVDeltaTracker
from features.trackers.price_levels import PriceLevelTracker

ENTRY_DIRECTION = +1        # long counter-regime entry
PREVAILING_DIRECTION = -1   # bearish regime being observed


class LongFeatureEngine:
    def __init__(self, ordered_features: List[str]):
        self.ordered_features = list(ordered_features)
        self.ohlcv = OHLCVDeltaTracker()
        self.price = PriceLevelTracker()
        self.center = MedianCenterTracker()
        self._last_1m_close_ts: Optional[int] = None

    # ---------------- update path ----------------
    def update_1s(self, ts_event: int, open_px: float, high: float, low: float,
                  close: float, volume: float, current_regime: int, atr: float) -> dict:
        """Unconditional rolling-window updates. Returns the OHLCV per-bar
        estimate dict so the caller can buffer it for `accumulate_regime_rth`
        once regime/RTH context resolves at the parent minute's close."""
        est = self.ohlcv.update(ts_event, open_px, high, low, close, volume)
        # MedianCenterTracker needs a bar-like object and the CURRENT regime.
        self.center.update_1s(
            SimpleNamespace(open=open_px, high=high, low=low, close=close,
                            volume=volume, ts_init=int(ts_event)),
            int(current_regime), float(atr) if atr and atr > 0 else 1.0)
        return est

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

    # ---------------- snapshot path ----------------
    def snapshot(self, snap_bar_ts: int, observation_ts: int, reference_price: float,
                 atr: float, current_regime: int = PREVAILING_DIRECTION,
                 center_atr: float = None):
        """Read-only: computes each tracker's full internal dict, merges, then
        slices exactly `self.ordered_features` IN ORDER.

        TWO DIFFERENT TIMESTAMPS, matching the offline producers exactly:

        * `snap_bar_ts` -> PriceLevelTracker. The offline replay
          (`attach_features_long.py:172`) calls
          `price_tracker.calculate(bar_ts, closes[i], ...)` where `bar_ts` is
          the SNAP BAR (last completed 1s bar strictly before the observation),
          NOT the observation instant. Passing `observation_ts` here instead
          shifts every time-derived value by the snap->observation gap (measured
          at up to 12 s on real March data).
        * `observation_ts` -> MedianCenterTracker, whose `calculate()` slices
          completed regimes with `searchsorted(end_times, ts, 'right')`. The
          observation instant is the correct slice point, matching the offline
          `compute_sequence_features(checkpoint_ts, ...)`.

        OHLCVDeltaTracker takes no timestamp; its state must simply exclude any
        bar at or after the observation (the caller guarantees this by updating
        AFTER checkpoints are emitted)."""
        a = float(atr) if atr and atr > 0 else 1.0
        # TWO DIFFERENT ATRs, matching the two offline producers:
        #   frozen entry ATR  -> OHLCV + price-level (attach_features_long passes
        #                        the surface's atr_at_entry into calculate()).
        #   running 1m ATR    -> median-center/sequence. The atlas built these
        #                        from build_median_centers_df over a 1s frame
        #                        carrying the LIVE per-bar `atr` column merged
        #                        from 1m -- not the regime-entry snapshot.
        # Evidence: with the frozen ATR, the ATR-free ratio
        # aligned_5m/aligned_15m matched offline at 3.55e-15 on 100% of rows
        # while the values themselves diverged, and the implied
        # live_atr/offline_atr ran 0.48-1.09 (median 0.83). The price/median
        # arithmetic was already exact; only the denominator was wrong.
        ca = float(center_atr) if center_atr and center_atr > 0 else a
        f_ohlcv = self.ohlcv.calculate(atr=a)
        f_price = self.price.calculate(snap_bar_ts, reference_price, a,
                                       direction=ENTRY_DIRECTION)
        f_center = self.center.calculate(
            int(current_regime), ca,
            SimpleNamespace(close=reference_price, ts_init=int(observation_ts)))
        merged = {**f_ohlcv, **f_price, **f_center}

        values: Dict[str, object] = {}
        null_mask: Dict[str, bool] = {}
        for feat in self.ordered_features:
            v = merged.get(feat, None)
            values[feat] = v
            null_mask[feat] = v is None
        return values, null_mask

    def ordered_vector(self, snap_bar_ts: int, observation_ts: int,
                       reference_price: float, atr: float,
                       current_regime: int = PREVAILING_DIRECTION,
                       center_atr: float = None):
        values, null_mask = self.snapshot(snap_bar_ts, observation_ts, reference_price,
                                          atr, current_regime, center_atr)
        vec = [values[f] for f in self.ordered_features]
        return vec, null_mask, any(null_mask.values())

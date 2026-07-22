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

MINUTE BARS ARE SYNTHESIZED FROM THE 1s STREAM, NEVER TAKEN FROM THE 1m FEED.
The offline attach never sees a 1m bar: it buckets raw 1s bars with
`common.minute_bucket_key` (`(ts-1)//60s`) and finalizes the bucket when a bar
with a new key arrives. Because the raw bars are OPEN-labelled, that bucket is
shifted +1 second from the true minute and its rollover fires one second late.
Driving `PriceLevelTracker` / the RTH accumulators from the catalog 1m bar
instead -- which is what an earlier version of this engine did -- reproduces
neither the values nor the timing. See `common.minute_bucket_key` for the
measured proof and why it is not a look-ahead.
"""
from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from typing import Callable, Deque, Dict, List, Optional

import common as C

from features.trackers.median_center import MedianCenterTracker
from features.trackers.ohlcv_delta import OHLCVDeltaTracker
from features.trackers.price_levels import PriceLevelTracker

ENTRY_DIRECTION = +1        # long counter-regime entry
PREVAILING_DIRECTION = -1   # bearish regime being observed
NS = 1_000_000_000


class LongFeatureEngine:
    def __init__(self, ordered_features: List[str],
                 is_rth_ts: Callable[[int], bool]):
        self.ordered_features = list(ordered_features)
        self.ohlcv = OHLCVDeltaTracker()
        self.price = PriceLevelTracker()
        self.center = MedianCenterTracker()
        self._is_rth_ts = is_rth_ts
        self._last_1m_close_ts: Optional[int] = None

        # --- synthesized-minute state (mirrors attach_features_long.py:127-166)
        self._minute_key: Optional[int] = None
        self._m_open: Optional[float] = None
        self._m_high: Optional[float] = None
        self._m_low: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._minute_buffer: List[tuple] = []
        self._was_rth = False
        # Regime flips are detected on the 1m close but APPLIED at the bucket
        # rollover, exactly as offline advances `reg_idx` there.
        self._pending_regime_starts: Deque[int] = deque()

    # ---------------- update path ----------------
    def declare_regime_start(self, regime_start_ns: int) -> None:
        """Called from the 1m handler the instant a flip is confirmed. The
        OHLCV tracker's regime reset is deferred to the next bucket rollover
        (offline: `while m_close_ts >= regime_starts[reg_idx+1]`), and its
        anchor is the just-closed bucket's OPEN, not the 1m bar's close."""
        self._pending_regime_starts.append(int(regime_start_ns))

    def update_1s(self, ts_event: int, open_px: float, high: float, low: float,
                  close: float, volume: float, current_regime: int, atr: float) -> dict:
        """One completed 1s bar. Folds it into the rolling-window trackers, then
        runs the minute-bucket rollover if this bar opens a new bucket.

        ORDER IS THE OFFLINE ORDER (attach_features_long.py:135-166):
        `ohlcv.update` -> rollover(regime, RTH, buffer flush, price.update_1m)
        -> `prev_close = close`. The caller MUST already have emitted every
        checkpoint due at this instant before calling this, so a snapshot sees
        state as of the previous bar -- the offline snap bar.
        """
        est = self.ohlcv.update(ts_event, open_px, high, low, close, volume)
        # MedianCenterTracker needs a bar-like object and the CURRENT regime.
        self.center.update_1s(
            SimpleNamespace(open=open_px, high=high, low=low, close=close,
                            volume=volume, ts_init=int(ts_event)),
            int(current_regime), float(atr) if atr and atr > 0 else 1.0)

        bar = (int(ts_event), float(high), float(low), float(volume),
               est.get("bar_est_delta", 0.0) if est else 0.0)
        mkey = C.minute_bucket_key(int(ts_event))
        if self._minute_key is None:
            self._minute_key = mkey
            self._m_open, self._m_high, self._m_low = open_px, high, low
            self._minute_buffer = [bar]
        elif mkey != self._minute_key:
            self._finalize_minute()
            self._minute_key = mkey
            self._m_open, self._m_high, self._m_low = open_px, high, low
            self._minute_buffer = [bar]
        else:
            self._m_high = max(self._m_high, high)
            self._m_low = min(self._m_low, low)
            self._minute_buffer.append(bar)

        self._prev_close = close
        return est

    def _finalize_minute(self) -> None:
        """Close the current bucket. `m_close_ts` is derived from the bucket
        key, never from a bar timestamp, so a missing first second of the next
        minute delays the rollover without corrupting the label."""
        m_close_ts = int((self._minute_key + 1) * 60 * NS)

        while (self._pending_regime_starts
               and self._pending_regime_starts[0] <= m_close_ts):
            rs = self._pending_regime_starts.popleft()
            self.ohlcv.reset_regime(rs, float(self._m_open))

        now_rth = bool(self._is_rth_ts(m_close_ts))
        if now_rth and not self._was_rth:
            self.ohlcv.reset_rth(m_close_ts)
        elif not now_rth and self._was_rth:
            self.ohlcv.end_rth()
        self._was_rth = now_rth

        for b_ts, b_high, b_low, b_vol, b_delta in self._minute_buffer:
            self.ohlcv.accumulate_regime_rth(b_ts, b_high, b_low, b_vol, b_delta)

        # `prev_close` is the LAST 1s close of the bucket -- offline passes it
        # because it assigns `prev_close = closes[i]` after the rollover.
        self.price.update_1m(m_close_ts, self._m_open, self._m_high, self._m_low,
                             self._prev_close, now_rth)
        self._last_1m_close_ts = m_close_ts

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

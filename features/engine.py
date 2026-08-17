from collections import deque
from datetime import datetime
import pytz
from typing import Dict, Any, List, Optional, Union
import copy

from features.trackers.velocity import ArrivalVelocityTracker
from features.trackers.volume import ArrivalVolumeTracker
from features.trackers.pullback import PullbackTracker
from features.trackers.ohlcv_delta import OHLCVDeltaTracker
from features.trackers.price_levels import PriceLevelTracker
from features.trackers.median_center import MedianCenterTracker
from features.trackers.rolling_5m_productivity import Rolling5mProductivityTracker
from features.trackers.wick import WickTracker
from features.registry import FEATURE_REGISTRY, resolve_feature_name
from utils.session_boundaries import is_in_session

CT = pytz.timezone('America/Chicago')


def _is_rth(ts_init_ns: int) -> bool:
    """RTH membership for a completed-bar close timestamp.

    This was a local copy of the boundary ending at 15:00, kept deliberately so that
    `features/` would not depend on a study module, with a comment asking future editors
    to "update both call sites in lockstep". They were not updated in lockstep: the
    canonical project window is 08:30-15:15 CT (`utils/session_boundaries.py`,
    AGENTS.md), and this copy silently disagreed with it by 15 minutes.

    `utils/` is shared infrastructure, not a study, so importing it introduces no
    study coupling -- which removes the reason the copy existed.
    """
    return is_in_session(int(ts_init_ns), "RTH")


def _coerce(val):
    """Preserve None (unavailable) and str (enum/name features) as-is;
    cast bool/numeric to float for the legacy all-float snapshot convention."""
    if val is None or isinstance(val, str):
        return val
    if isinstance(val, bool):
        return float(val)
    return float(val)


class FeatureEngine:
    """
    Composed Feature Engine.

    Coordinates low-level trackers and manages timeframe-specific updates.
    Ensures clear call ordering and explicit stream updates.
    """

    def __init__(self, buffer_size_1s: int = 60, buffer_size_1m: int = 30,
                 rolling_productivity_window_seconds: int = 300):
        self._velocity_tracker = ArrivalVelocityTracker(maxlen=buffer_size_1s)
        self._volume_tracker = ArrivalVolumeTracker(maxlen=buffer_size_1s)
        self._ohlcv_delta_tracker = OHLCVDeltaTracker()
        self._price_level_tracker = PriceLevelTracker()
        self._median_center_tracker = MedianCenterTracker()
        self._rolling_productivity_tracker = Rolling5mProductivityTracker(
            window_seconds=rolling_productivity_window_seconds)
        self._wick_tracker = WickTracker()
        self.last_atr = 1.0

        # 1s price streams
        self._highs_1s = deque(maxlen=buffer_size_1s)
        self._lows_1s = deque(maxlen=buffer_size_1s)
        self._closes_1s = deque(maxlen=buffer_size_1s)

        # 1m states
        self.bars_since_breach_1m = []
        self.breach_price = None
        self.last_regime_id = 0
        self.bars_in_regime = 0
        self.last_regime = 0
        self._was_rth = False

        # Buffer of this-still-forming-minute's 1s bars, for OHLCVDeltaTracker's
        # regime/RTH-conditional accumulation only. NT dispatches an entire
        # minute's 1s bars before its parent 1m bar closes, so the correct
        # regime/RTH context for these bars is only knowable once update_1m()
        # fires -- buffered here and replayed retroactively at that point
        # (same buffered-retroactive-replay pattern CLAUDE.md invariant 4
        # mandates for MFE/MAE). The rolling-window (A1-A3) part of
        # OHLCVDeltaTracker has no such dependency and updates immediately
        # in update_1s(), unaffected by this buffer.
        self._minute_1s_buffer: List[tuple] = []

        # EMA/Spread histories
        self.short_ema_history = deque(maxlen=10)
        self.long_ema_history = deque(maxlen=10)
        self.ema_spread_history = deque(maxlen=10)

    def update_1s(self, bar) -> None:
        """Explicitly update 1s data stream."""
        open_px = float(bar.open)
        high_px = float(bar.high)
        low_px = float(bar.low)
        close_px = float(bar.close)
        volume_val = float(bar.volume)

        self._velocity_tracker.update(close_px)
        self._volume_tracker.update(volume_val, open_px, close_px)
        b_est = self._ohlcv_delta_tracker.update(
            int(bar.ts_init), open_px, high_px, low_px, close_px, volume_val)
        # Production NT bars always carry a positive availability timestamp.
        # Some legacy unit fixtures deliberately use zero as an unspecified
        # ts_init; do not invent a completed-bar timestamp for those fixtures.
        if int(bar.ts_init) > 0:
            self._rolling_productivity_tracker.on_completed_1s(
                int(bar.ts_init), high_px, low_px, close_px)
        self._median_center_tracker.update_1s(bar, self.last_regime, self.last_atr)
        # Regime/RTH context for this bar is not yet knowable (see the
        # buffer's docstring in __init__) -- buffer for retroactive replay
        # in update_1m(), rather than accumulating immediately.
        self._minute_1s_buffer.append(
            (int(bar.ts_init), high_px, low_px, volume_val, b_est["bar_est_delta"]))

        self._highs_1s.append(high_px)
        self._lows_1s.append(low_px)
        self._closes_1s.append(close_px)

    def update_30s(self, bar) -> None:
        """Explicitly update 30s data stream (optional placeholder)."""
        pass

    def update_1m(self, bar, regime) -> None:
        """Explicitly update 1m data stream after regime calculations close."""
        had_active_regime = self.last_regime_id != 0
        buffered_minute = self._minute_1s_buffer
        self._minute_1s_buffer = []
        # Session attribution uses the completed parent-minute close boundary.
        # It must be transitioned before flushing its completed 1s members.
        is_rth_now = _is_rth(int(bar.ts_init))
        if is_rth_now and not self._was_rth:
            self._ohlcv_delta_tracker.reset_rth(int(bar.ts_init))
        elif not is_rth_now and self._was_rth:
            self._ohlcv_delta_tracker.end_rth()
        self._was_rth = is_rth_now

        # A real flip has an active prior regime, so its already-completed
        # minute is flushed before the reset below. A first regime has no
        # declared start before this close; discard its pre-start buffer.
        if had_active_regime:
            for buf_ts, buf_high, buf_low, buf_vol, buf_delta in buffered_minute:
                self._ohlcv_delta_tracker.accumulate_regime(
                    buf_ts, buf_high, buf_low, buf_vol, buf_delta)
        # Valid completed RTH minutes are session data even before the first
        # 1m regime exists; never couple them to regime initialization.
        for _buf_ts, _buf_high, _buf_low, buf_vol, buf_delta in buffered_minute:
            self._ohlcv_delta_tracker.accumulate_rth(buf_vol, buf_delta)
        if regime.regime_id != self.last_regime_id:
            self.bars_in_regime = 0
            self.bars_since_breach_1m = []
            self.breach_price = None
            self.last_regime_id = regime.regime_id
            self.last_regime = regime.regime
            # Anchor = this (new-regime) bar's OPEN, matching the project-wide
            # "entry_open" convention for a regime's anchor price (see e.g.
            # studies/regime_sequence_chop_context/build_weakness_atlas.py) --
            # not the bar's close, which this call previously used and which
            # disagreed with the offline replay's own (correct) anchor basis
            # in attach_features.py.
            self._ohlcv_delta_tracker.reset_regime(int(bar.ts_init), float(bar.open))
        else:
            self.bars_in_regime += 1

        if regime.has_breached:
            self.bars_since_breach_1m.append(bar)
            if self.breach_price is None:
                self.breach_price = regime.regime_high if regime.regime == 1 else regime.regime_low

        self.short_ema_history.append(regime.short_ema_close.value)
        self.long_ema_history.append(regime.long_ema_close.value)

        atr = regime.atr.value
        if atr > 0:
            spread = (regime.short_ema_close.value - regime.long_ema_close.value) / atr
        else:
            spread = 0.0
        self.ema_spread_history.append(spread)

        self.last_atr = regime.atr.value if regime.atr.value > 0 else 1.0

        # Retroactively attribute this minute's buffered 1s bars to whichever
        # regime/RTH state is active AFTER the reset decisions above -- their
        # true membership was only knowable now, not when update_1s() ran.
        for buf_ts, buf_high, buf_low, buf_vol, buf_delta in self._minute_1s_buffer:
            self._ohlcv_delta_tracker.accumulate_regime_rth(buf_ts, buf_high, buf_low, buf_vol, buf_delta)
        self._minute_1s_buffer = []

        self._price_level_tracker.update_1m(
            int(bar.ts_init), float(bar.open), float(bar.high), float(bar.low),
            float(bar.close), is_rth_now)

        self._median_center_tracker.update_1m(bar, regime)
        self._wick_tracker.update(float(bar.open), float(bar.high), float(bar.low), float(bar.close))

    def update_5m(self, bar) -> None:
        """Explicitly update 5m data stream (optional placeholder)."""
        pass

    def on_new_breach(self, regime) -> None:
        """Call on breach events to reset state."""
        self.bars_since_breach_1m = []
        self.breach_price = regime.regime_high if regime.regime == 1 else regime.regime_low

    def snapshot(self, feature_set: Union[str, List[str]], snap_context: Dict[str, Any]) -> Dict[str, float]:
        """
        Creates and returns an immutable, deduplicated snapshot of features at a specific decision point.
        
        Args:
            feature_set: "all" or list of target feature names to snap.
            snap_context: Must contain "touch_bar", "regime", and "direction" (+1/-1).
        """
        touch_bar = snap_context.get("touch_bar")
        regime = snap_context.get("regime")
        direction = snap_context.get("direction", 1)

        if touch_bar is None or regime is None:
            raise ValueError("snap_context must provide 'touch_bar' and 'regime'")

        atr = regime.atr.value
        if atr <= 0 or len(self._closes_1s) < 30:
            return {}

        raw_features = {}

        # 1. Arrival Velocity
        raw_features.update(self._velocity_tracker.calculate(atr))

        # 2. Arrival Volume
        raw_features.update(self._volume_tracker.calculate())

        # 3. Pullback 1s
        raw_features.update(PullbackTracker.calculate_1s(
            list(self._highs_1s),
            list(self._lows_1s),
            list(self._closes_1s),
            atr
        ))

        # 4. Pullback 1m
        ema = regime.short_ema_close.value
        touch_price = float(touch_bar.low) if direction == 1 else float(touch_bar.high)
        raw_features.update(PullbackTracker.calculate_1m(
            self.bars_since_breach_1m,
            self.breach_price or ema,
            touch_price,
            atr,
            direction
        ))

        # 5. Context Features
        raw_features.update(self._get_context_features(touch_bar, regime))

        # 6. OHLCV estimated volume/delta (Part A)
        raw_features.update(self._ohlcv_delta_tracker.calculate(atr))

        # 7. Price-level context (Part B)
        reference_price = float(touch_bar.close)
        raw_features.update(self._price_level_tracker.calculate(
            int(touch_bar.ts_init), reference_price, atr, direction))

        # 8. Median Center, Activity & Sequence Features
        raw_features.update(self._median_center_tracker.calculate(
            self.last_regime, atr, touch_bar))

        # 9. Wick Imbalance
        raw_features.update(self._wick_tracker.calculate())

        # Study collectors supply the fixed current-regime-start ATR and the
        # already-causal structural lifetime speed at their decision boundary.
        # The engine owns the completed-1s routing; the study owns when this
        # block is requested and how its companion structural state is formed.
        rolling_context = snap_context.get("rolling_productivity")
        if rolling_context is not None:
            raw_features.update(self._rolling_productivity_tracker.snapshot(
                checkpoint_ns=int(rolling_context["checkpoint_ns"]),
                direction=direction,
                current_regime_start_atr=float(rolling_context["current_regime_start_atr"]),
                regime_expansion_atr_per_min=rolling_context.get("regime_expansion_atr_per_min"),
            ))

        # Filter, map aliases, and deduplicate
        output = {}
        target_keys = FEATURE_REGISTRY.keys() if feature_set == "all" else feature_set

        for raw_key in target_keys:
            canonical_key = resolve_feature_name(raw_key)
            if canonical_key in FEATURE_REGISTRY:
                # Ensure values are fetched and mapped
                val = raw_features.get(raw_key, raw_features.get(canonical_key, None))
                output[canonical_key] = _coerce(val)

        # Return a deep copy to guarantee snapshot immutability
        return copy.deepcopy(output)

    def _get_context_features(self, touch_bar, regime) -> Dict[str, float]:
        atr = regime.atr.value if regime.atr.value > 0 else 1.0

        ema_slope_short = 0.0
        if len(self.short_ema_history) >= 6:
            ema_slope_short = (self.short_ema_history[-1] - self.short_ema_history[-6]) / (5 * atr)

        ema_slope_long = 0.0
        if len(self.long_ema_history) >= 6:
            ema_slope_long = (self.long_ema_history[-1] - self.long_ema_history[-6]) / (5 * atr)

        # Databento aggregation shift: RTH checks always run close-time based
        dt = datetime.fromtimestamp(touch_bar.ts_init / 1e9, tz=pytz.utc).astimezone(CT)
        minutes_since_open = (dt.hour - 8) * 60 + (dt.minute - 30)
        # Canonical boundary, not a second inline re-derivation (this one also
        # ended RTH at 15:00 while the project window ends at 15:15).
        is_rth = 1.0 if _is_rth(int(touch_bar.ts_init)) else 0.0

        return {
            'ema_slope_short': float(ema_slope_short),
            'ema_slope_long': float(ema_slope_long),
            'regime_age_bars': float(self.bars_in_regime),
            'is_rth': is_rth,
            'minutes_since_rth_open': float(minutes_since_open),
        }

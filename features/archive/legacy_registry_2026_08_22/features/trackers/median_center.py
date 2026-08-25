"""Causal Median Center, Activity, and Sequence feature tracker.

Tracks F0 features dynamically using causal deques on 1s and 1m bar streams.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import numpy as np
import pytz
from typing import Dict, List, Optional, Tuple

CT = pytz.timezone("America/Chicago")


def _get_session_start_ns(ts_ns: int) -> int:
    """Return the CME session start (17:00 CT of trading day) for a given UTC timestamp."""
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=pytz.utc).astimezone(CT)
    if dt.hour >= 17:
        start_dt = dt.replace(hour=17, minute=0, second=0, microsecond=0)
    else:
        start_dt = (dt - timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
    start_dt = CT.normalize(start_dt)
    return int(start_dt.astimezone(pytz.utc).timestamp() * 1e9)


class MedianCenterTracker:
    """Tracks median center context, completed regime sequences, and activity features."""

    def __init__(self) -> None:
        # Raw 1s bar deques
        self.prices_1s: deque = deque(maxlen=3600)
        self.highs_1s: deque = deque(maxlen=3600)
        self.lows_1s: deque = deque(maxlen=3600)
        self.volumes_1s: deque = deque(maxlen=3600)
        self.timestamps_1s: deque = deque(maxlen=3600)

        # median history for slopes (maxlen is 900 to support slope_30m_15m)
        self.median_5m_history: deque = deque(maxlen=900)
        self.median_15m_history: deque = deque(maxlen=900)
        self.median_30m_history: deque = deque(maxlen=900)



        # Slope history for accelerations (maxlen=400 to support lookback + 1 safely)
        self.slope_5m_1m_aligned_history: deque = deque(maxlen=400)
        self.slope_15m_3m_aligned_history: deque = deque(maxlen=400)
        self.slope_30m_5m_aligned_history: deque = deque(maxlen=400)

        # Spread history for spread changes (maxlen=150 to support lookback + 1 safely)
        self.spread_5m_15m_history: deque = deque(maxlen=150)
        self.spread_15m_30m_history: deque = deque(maxlen=150)
        self.spread_5m_30m_history: deque = deque(maxlen=150)

        # Ordering state run tracker
        self.last_ordering_state: int = 0
        self.seconds_in_current_ordering: int = 0
        self.ordering_state_changes_history: deque = deque(maxlen=3600)

        # Crossing histories (maxlen=1800 for 30m lookback)
        self.last_sign_no_zero_5m: Optional[float] = None
        self.last_sign_no_zero_15m: Optional[float] = None
        self.last_sign_no_zero_30m: Optional[float] = None

        self.sign_5m_history: deque = deque(maxlen=1800)
        self.cross_5m_history: deque = deque(maxlen=1800)
        self.cross_15m_history: deque = deque(maxlen=1800)
        self.cross_30m_history: deque = deque(maxlen=1800)

        # Active regime tracking
        self._active_regime_direction: int = 0
        self._active_regime_start_ts: int = 0
        self._active_regime_start_price: Optional[float] = None
        self._active_regime_high: float = -np.inf
        self._active_regime_low: float = np.inf
        self._active_regime_volume: float = 0.0
        self._active_regime_closes: List[float] = []
        self._active_regime_last_close: Optional[float] = None
        self._active_regime_sum_abs_diff: float = 0.0

        # Completed regimes (maxlen=300 to prevent truncation in choppy markets)
        self.completed_regimes: deque = deque(maxlen=300)

    def _reset_active_regime(self, direction: int, start_ts: int) -> None:
        self._active_regime_direction = direction
        self._active_regime_start_ts = start_ts
        self._active_regime_start_price = None
        self._active_regime_high = -np.inf
        self._active_regime_low = np.inf
        self._active_regime_volume = 0.0
        self._active_regime_closes = []
        self._active_regime_last_close = None
        self._active_regime_sum_abs_diff = 0.0

    def update_1s(self, bar, current_regime: int, current_atr: float) -> None:
        px_open = float(bar.open)
        px_high = float(bar.high)
        px_low = float(bar.low)
        px_close = float(bar.close)
        vol = float(bar.volume)
        ts = int(bar.ts_init)

        self.prices_1s.append(px_close)
        self.highs_1s.append(px_high)
        self.lows_1s.append(px_low)
        self.volumes_1s.append(vol)
        self.timestamps_1s.append(ts)



        # Dynamic rolling medians
        median_5m = float(np.median(list(self.prices_1s)[-300:])) if len(self.prices_1s) > 0 else px_close
        median_15m = float(np.median(list(self.prices_1s)[-900:])) if len(self.prices_1s) > 0 else px_close
        median_30m = float(np.median(list(self.prices_1s)[-1800:])) if len(self.prices_1s) > 0 else px_close

        self.median_5m_history.append(median_5m)
        self.median_15m_history.append(median_15m)
        self.median_30m_history.append(median_30m)

        # Compute intermediate values for spread & slope histories
        s5 = current_regime * median_5m
        s15 = current_regime * median_15m
        s30 = current_regime * median_30m

        atr = current_atr if current_atr > 0 else 1.0
        spread_5m_15m = current_regime * (median_5m - median_15m) / atr
        spread_15m_30m = current_regime * (median_15m - median_30m) / atr
        spread_5m_30m = current_regime * (median_5m - median_30m) / atr

        self.spread_5m_15m_history.append(spread_5m_15m)
        self.spread_15m_30m_history.append(spread_15m_30m)
        self.spread_5m_30m_history.append(spread_5m_30m)

        # Ordering state
        ordering = 0
        if s5 > s15 and s15 > s30:
            ordering = 0
        elif s5 > s30 and s30 > s15:
            ordering = 1
        elif s15 > s5 and s5 > s30:
            ordering = 2
        elif s15 > s30 and s30 > s5:
            ordering = 3
        elif s30 > s5 and s5 > s15:
            ordering = 4
        elif s30 > s15 and s15 > s5:
            ordering = 5

        # Check compression
        max_val = max(s5, s15, s30)
        min_val = min(s5, s15, s30)
        if (max_val - min_val) < 0.1 * atr:
            ordering = 6

        if ordering != self.last_ordering_state:
            self.seconds_in_current_ordering = 1
            self.ordering_state_changes_history.append(1)
        else:
            self.seconds_in_current_ordering += 1
            self.ordering_state_changes_history.append(0)
        self.last_ordering_state = ordering

        # Crossing state updates
        diff_5m = px_close - median_5m
        sign_5m = 1.0 if diff_5m > 0 else (-1.0 if diff_5m < 0 else 0.0)
        self.sign_5m_history.append(sign_5m)

        def update_cross(sign_val, last_sign):
            if last_sign is None:
                return 0.0, sign_val if sign_val != 0.0 else 1.0
            new_sign = sign_val if sign_val != 0.0 else last_sign
            cross = 1.0 if new_sign != last_sign else 0.0
            return cross, new_sign

        cross_5m, self.last_sign_no_zero_5m = update_cross(sign_5m, self.last_sign_no_zero_5m)
        self.cross_5m_history.append(cross_5m)

        diff_15m = px_close - median_15m
        sign_15m = 1.0 if diff_15m > 0 else (-1.0 if diff_15m < 0 else 0.0)
        cross_15m, self.last_sign_no_zero_15m = update_cross(sign_15m, self.last_sign_no_zero_15m)
        self.cross_15m_history.append(cross_15m)

        diff_30m = px_close - median_30m
        sign_30m = 1.0 if diff_30m > 0 else (-1.0 if diff_30m < 0 else 0.0)
        cross_30m, self.last_sign_no_zero_30m = update_cross(sign_30m, self.last_sign_no_zero_30m)
        self.cross_30m_history.append(cross_30m)

        # Update active completed-regime statistics
        if current_regime != 0:
            if self._active_regime_direction == 0:
                self._reset_active_regime(current_regime, ts)
            elif self._active_regime_direction != current_regime:
                self.on_regime_change(current_regime, ts)

            if self._active_regime_start_price is None:
                self._active_regime_start_price = px_open

            self._active_regime_high = max(self._active_regime_high, px_high)
            self._active_regime_low = min(self._active_regime_low, px_low)
            self._active_regime_volume += vol
            self._active_regime_closes.append(px_close)

            if self._active_regime_last_close is not None:
                self._active_regime_sum_abs_diff += abs(px_close - self._active_regime_last_close)
            self._active_regime_last_close = px_close

        # Compute current slopes and append them to aligned histories (separates state mutation from calculate)
        y_5m = list(self.median_5m_history)
        slope_5m_1m = self._calculate_slope(y_5m, 60)

        y_15m = list(self.median_15m_history)
        slope_15m_3m = self._calculate_slope(y_15m, 180)

        y_30m = list(self.median_30m_history)
        slope_30m_5m = self._calculate_slope(y_30m, 300)

        s_5m_1m_al = current_regime * slope_5m_1m / atr
        s_15m_3m_al = current_regime * slope_15m_3m / atr
        s_30m_5m_al = current_regime * slope_30m_5m / atr

        self.slope_5m_1m_aligned_history.append(s_5m_1m_al)
        self.slope_15m_3m_aligned_history.append(s_15m_3m_al)
        self.slope_30m_5m_aligned_history.append(s_30m_5m_al)

    def update_1m(self, bar, regime) -> None:
        """Call on completed 1m bar close."""
        # Check for regime flip
        if regime.regime != self._active_regime_direction:
            self.on_regime_change(regime.regime, int(bar.ts_init))

    def on_regime_change(self, new_regime: int, flip_ts: int) -> None:
        # If we had a running active regime, complete it
        if self._active_regime_direction != 0 and self._active_regime_closes:
            dir_val = self._active_regime_direction
            start_px = self._active_regime_start_price
            end_px = self._active_regime_closes[-1]
            net_aligned = dir_val * (end_px - start_px)

            if dir_val == 1:
                mfe = self._active_regime_high - start_px
                mae = start_px - self._active_regime_low
            else:
                mfe = start_px - self._active_regime_low
                mae = self._active_regime_high - start_px

            reg_center = float(np.median(self._active_regime_closes))
            vol_sum = self._active_regime_volume

            total_diff = self._active_regime_sum_abs_diff
            dir_eff = net_aligned / total_diff if total_diff > 0 else 0.0

            completed = {
                "direction": dir_val,
                "start_time": self._active_regime_start_ts,
                "end_time": flip_ts,
                "duration": (flip_ts - self._active_regime_start_ts) / 1e9,
                "start_price": start_px,
                "end_price": end_px,
                "net_aligned_move": net_aligned,
                "MFE": mfe,
                "MAE": mae,
                "regime_center": reg_center,
                "volume": vol_sum,
                "directional_efficiency": dir_eff
            }
            self.completed_regimes.append(completed)

        # Reset active regime for new regime
        self._reset_active_regime(new_regime, flip_ts)

    def _calculate_slope(self, y: List[float], N: int) -> float:
        if len(y) < N:
            return 0.0
        slice_y = y[-N:]
        sum_y = sum(slice_y)
        sum_xy = sum(i * slice_y[i] for i in range(N))
        sum_x = N * (N - 1) / 2
        sum_x2 = N * (N - 1) * (2 * N - 1) / 6
        num = N * sum_xy - sum_x * sum_y
        den = N * sum_x2 - sum_x ** 2
        return num / den if den != 0 else 0.0

    def calculate(self, current_regime: int, current_atr: float, touch_bar) -> Dict[str, float]:
        """Calculate and return all 149 features."""
        px_close = float(touch_bar.close)
        atr = current_atr if current_atr > 0 else 1.0
        direction = current_regime

        # 1. Rolling medians
        median_5m = self.median_5m_history[-1] if self.median_5m_history else px_close
        median_15m = self.median_15m_history[-1] if self.median_15m_history else px_close
        median_30m = self.median_30m_history[-1] if self.median_30m_history else px_close

        # 2. Relative price-to-center distances
        aligned_5m = direction * (px_close - median_5m) / atr
        aligned_15m = direction * (px_close - median_15m) / atr
        aligned_30m = direction * (px_close - median_30m) / atr

        # 3. Slopes
        s_5m_1m_al = self.slope_5m_1m_aligned_history[-1] if self.slope_5m_1m_aligned_history else 0.0
        s_15m_3m_al = self.slope_15m_3m_aligned_history[-1] if self.slope_15m_3m_aligned_history else 0.0
        s_30m_5m_al = self.slope_30m_5m_aligned_history[-1] if self.slope_30m_5m_aligned_history else 0.0

        y_5m = list(self.median_5m_history)
        slope_5m_3m = self._calculate_slope(y_5m, 180)
        slope_5m_5m = self._calculate_slope(y_5m, 300)
        s_5m_3m_al = direction * slope_5m_3m / atr
        s_5m_5m_al = direction * slope_5m_5m / atr

        y_15m = list(self.median_15m_history)
        slope_15m_5m = self._calculate_slope(y_15m, 300)
        slope_15m_10m = self._calculate_slope(y_15m, 600)
        s_15m_5m_al = direction * slope_15m_5m / atr
        s_15m_10m_al = direction * slope_15m_10m / atr

        y_30m = list(self.median_30m_history)
        slope_30m_10m = self._calculate_slope(y_30m, 600)
        slope_30m_15m = self._calculate_slope(y_30m, 900)
        s_30m_10m_al = direction * slope_30m_10m / atr
        s_30m_15m_al = direction * slope_30m_15m / atr

        # 4. Slope changes & accelerations
        center_slope_change_5m = s_5m_1m_al - s_5m_5m_al
        center_slope_change_15m = s_15m_3m_al - s_15m_10m_al
        center_slope_change_30m = s_30m_5m_al - s_30m_15m_al

        def get_accel(hist, lookback):
            if len(hist) >= lookback + 1:
                return hist[-1] - hist[-(lookback + 1)]
            return 0.0

        center_slope_acceleration_5m = get_accel(self.slope_5m_1m_aligned_history, 60)
        center_slope_acceleration_15m = get_accel(self.slope_15m_3m_aligned_history, 180)
        center_slope_acceleration_30m = get_accel(self.slope_30m_5m_aligned_history, 300)

        # 5. Spreads & spread changes
        c_spread_5m_15m = self.spread_5m_15m_history[-1] if self.spread_5m_15m_history else 0.0
        c_spread_15m_30m = self.spread_15m_30m_history[-1] if self.spread_15m_30m_history else 0.0
        c_spread_5m_30m = self.spread_5m_30m_history[-1] if self.spread_5m_30m_history else 0.0

        spread_change_5m_15m = get_accel(self.spread_5m_15m_history, 60)
        spread_change_15m_30m = get_accel(self.spread_15m_30m_history, 60)
        spread_change_5m_30m = get_accel(self.spread_5m_30m_history, 60)

        # 6. Ordering & persistence
        ordering_state = self.last_ordering_state
        sec_ordering = self.seconds_in_current_ordering
        ordering_changes_15m = sum(list(self.ordering_state_changes_history)[-900:])
        ordering_changes_30m = sum(list(self.ordering_state_changes_history)[-1800:])
        ordering_changes_60m = sum(list(self.ordering_state_changes_history)[-3600:])

        # 7. Crossing behavior (over last 1800 seconds)
        price_cross_5m = sum(self.cross_5m_history)
        price_cross_15m = sum(self.cross_15m_history)
        price_cross_30m = sum(self.cross_30m_history)
        crosses_per_min = (price_cross_5m + price_cross_15m + price_cross_30m) / 30.0

        fav_frac_5m = sum(1.0 for s in self.sign_5m_history if s > 0) / max(1, len(self.sign_5m_history))
        adv_frac_5m = sum(1.0 for s in self.sign_5m_history if s < 0) / max(1, len(self.sign_5m_history))

        # Base features dict
        res = {
            'aligned_price_minus_center_5m': aligned_5m,
            'aligned_price_minus_center_15m': aligned_15m,
            'aligned_price_minus_center_30m': aligned_30m,
            'slope_5m_1m_aligned_atr': s_5m_1m_al,
            'slope_5m_3m_aligned_atr': s_5m_3m_al,
            'slope_5m_5m_aligned_atr': s_5m_5m_al,
            'slope_15m_3m_aligned_atr': s_15m_3m_al,
            'slope_15m_5m_aligned_atr': s_15m_5m_al,
            'slope_15m_10m_aligned_atr': s_15m_10m_al,
            'slope_30m_5m_aligned_atr': s_30m_5m_al,
            'slope_30m_10m_aligned_atr': s_30m_10m_al,
            'slope_30m_15m_aligned_atr': s_30m_15m_al,
            'center_slope_change_5m': center_slope_change_5m,
            'center_slope_change_15m': center_slope_change_15m,
            'center_slope_change_30m': center_slope_change_30m,
            'center_slope_acceleration_5m': center_slope_acceleration_5m,
            'center_slope_acceleration_15m': center_slope_acceleration_15m,
            'center_slope_acceleration_30m': center_slope_acceleration_30m,
            'center_spread_5m_15m': c_spread_5m_15m,
            'center_spread_15m_30m': c_spread_15m_30m,
            'center_spread_5m_30m': c_spread_5m_30m,
            'spread_change_5m_15m': spread_change_5m_15m,
            'spread_change_15m_30m': spread_change_15m_30m,
            'spread_change_5m_30m': spread_change_5m_30m,
            'ordering_state': float(ordering_state),
            'seconds_in_current_ordering': float(sec_ordering),
            'ordering_changes_15m': float(ordering_changes_15m),
            'ordering_changes_30m': float(ordering_changes_30m),
            'ordering_changes_60m': float(ordering_changes_60m),
            'price_cross_count_5m': float(price_cross_5m),
            'price_cross_count_15m': float(price_cross_15m),
            'price_cross_count_30m': float(price_cross_30m),
            'crosses_per_minute': crosses_per_min,
            'fraction_of_time_on_favorable_side': fav_frac_5m,
            'fraction_of_time_on_adverse_side': adv_frac_5m,
        }

        # 8. Activity features
        flip_ts = int(touch_bar.ts_init)
        regs_end_times = [r['end_time'] for r in self.completed_regimes]
        idx_right = np.searchsorted(regs_end_times, flip_ts, side='right')

        # Rolling window counts & durations
        for W_min in (5, 15, 30, 60, 120):
            W_ns = W_min * 60 * 1_000_000_000
            idx_left = np.searchsorted(regs_end_times, flip_ts - W_ns, side='right')
            count_reg = idx_right - idx_left
            res[f"activity_regime_count_{W_min}m"] = float(count_reg)
            if W_min == 30:
                res["activity_flip_count_30m"] = float(count_reg)

            if count_reg > 0:
                res[f"activity_duration_median_{W_min}m"] = float(
                    np.median([r['duration'] for r in list(self.completed_regimes)[idx_left:idx_right]])
                )
            else:
                res[f"activity_duration_median_{W_min}m"] = 0.0

        # Session regime count
        sess_start = _get_session_start_ns(flip_ts)
        idx_sess = np.searchsorted(regs_end_times, sess_start, side='left')
        res["activity_regime_count_std"] = float(max(0, idx_right - idx_sess))

        # Medians of last completed regime durations
        if idx_right >= 3:
            res["duration_median_last_3"] = float(
                np.median([r['duration'] for r in list(self.completed_regimes)[idx_right-3:idx_right]])
            )
        else:
            res["duration_median_last_3"] = 0.0

        if idx_right >= 5:
            res["duration_median_last_5"] = float(
                np.median([r['duration'] for r in list(self.completed_regimes)[idx_right-5:idx_right]])
            )
        else:
            res["duration_median_last_5"] = 0.0

        if idx_right >= 10:
            res["duration_median_last_10"] = float(
                np.median([r['duration'] for r in list(self.completed_regimes)[idx_right-10:idx_right]])
            )
        else:
            res["duration_median_last_10"] = 0.0

        res["duration_ratio_3_vs_10"] = res["duration_median_last_3"] / (res["duration_median_last_10"] + 1e-8)
        res["duration_ratio_5_vs_10"] = res["duration_median_last_5"] / (res["duration_median_last_10"] + 1e-8)

        # 9. Cross-family context
        res["cross_family_spread_vs_reg_count"] = c_spread_5m_30m / max(res.get("activity_regime_count_30m", 0.0), 1.0)
        res["cross_family_slope_vs_reg_count"] = s_30m_15m_al / max(res.get("activity_regime_count_30m", 0.0), 1.0)

        # 10. Completed regime sequence stats (seq_Kr_*)
        for K in (3, 5, 8, 12):
            prefix = f"seq_{K}r_"
            if idx_right < K:
                # Pad with 0.0 defaults
                for suffix in (
                    "alternation_rate", "perfect_alternation", "efficiency", "disp_atr",
                    "mean_overlap", "median_overlap", "max_overlap", "overlap_above_50", "overlap_above_75",
                    "mean_retracement", "mean_retracement_mfe", "reclaim_rate", "range_atr", "position_pct",
                    "dist_to_high_atr", "dist_to_low_atr", "center_migration_slope_atr", "center_migration_r2",
                    "center_dir_consistency", "center_reversal_count", "asym_duration", "asym_mfe",
                    "asym_net_move", "asym_efficiency", "asym_volume"
                ):
                    res[f"{prefix}{suffix}"] = None
                continue

            sub = list(self.completed_regimes)[idx_right - K : idx_right]

            # Alternation
            dirs = [int(r['direction']) for r in sub]
            changes = sum(1 for i in range(K - 1) if dirs[i] != dirs[i+1])
            res[f"{prefix}alternation_rate"] = changes / (K - 1)
            res[f"{prefix}perfect_alternation"] = float(changes == (K - 1))

            # Sequence Efficiency
            seq_start_price = sub[0]['start_price']
            total_abs_net_move = sum(abs(r['net_aligned_move']) for r in sub)
            net_disp = px_close - seq_start_price
            res[f"{prefix}efficiency"] = abs(net_disp) / (total_abs_net_move + 1e-8)
            res[f"{prefix}disp_atr"] = (direction * net_disp) / (atr + 1e-8)

            # Range Overlap
            overlaps = []
            for i in range(K - 1):
                r1 = sub[i]
                r2 = sub[i+1]

                if r1['direction'] == 1:
                    high1 = r1['start_price'] + r1['MFE']
                    low1 = r1['start_price'] - r1['MAE']
                else:
                    high1 = r1['start_price'] + r1['MAE']
                    low1 = r1['start_price'] - r1['MFE']

                if r2['direction'] == 1:
                    high2 = r2['start_price'] + r2['MFE']
                    low2 = r2['start_price'] - r2['MAE']
                else:
                    high2 = r2['start_price'] + r2['MAE']
                    low2 = r2['start_price'] - r2['MFE']

                inter = max(0.0, min(high1, high2) - max(low1, low2))
                min_rng = min(high1 - low1, high2 - low2)
                overlaps.append(inter / (min_rng + 1e-8))

            n_over = len(overlaps)
            mean_overlap = sum(overlaps) / n_over if n_over > 0 else 0.0
            max_overlap = max(overlaps) if overlaps else 0.0

            if overlaps:
                sorted_over = sorted(overlaps)
                if n_over % 2 == 1:
                    median_overlap = float(sorted_over[n_over // 2])
                else:
                    median_overlap = float((sorted_over[n_over // 2 - 1] + sorted_over[n_over // 2]) / 2.0)
            else:
                median_overlap = 0.0

            res[f"{prefix}mean_overlap"] = mean_overlap
            res[f"{prefix}median_overlap"] = median_overlap
            res[f"{prefix}max_overlap"] = max_overlap
            res[f"{prefix}overlap_above_50"] = sum(1.0 for o in overlaps if o > 0.5) / max(1, n_over)
            res[f"{prefix}overlap_above_75"] = sum(1.0 for o in overlaps if o > 0.75) / max(1, n_over)

            # Retracement Behavior
            retracements = []
            retracements_mfe = []
            reclaim_count = 0
            for i in range(K - 1):
                r1 = sub[i]
                r2 = sub[i+1]
                if r1['direction'] != r2['direction']:
                    p_net = abs(r1['net_aligned_move'])
                    o_net = abs(r2['net_aligned_move'])
                    retracements.append(o_net / (p_net + 1e-8))

                    p_mfe = r1['MFE']
                    retracements_mfe.append(o_net / (p_mfe + 1e-8))

                    r1_start = r1['start_price']
                    if r2['direction'] == 1:
                        r2_high = r2['start_price'] + r2['MFE']
                        r2_low = r2['start_price'] - r2['MAE']
                    else:
                        r2_high = r2['start_price'] + r2['MAE']
                        r2_low = r2['start_price'] - r2['MFE']

                    if r1['direction'] == 1:
                        if r2_low <= r1_start:
                            reclaim_count += 1
                    else:
                        if r2_high >= r1_start:
                            reclaim_count += 1

            res[f"{prefix}mean_retracement"] = sum(retracements) / len(retracements) if retracements else 0.0
            res[f"{prefix}mean_retracement_mfe"] = sum(retracements_mfe) / len(retracements_mfe) if retracements_mfe else 0.0
            res[f"{prefix}reclaim_rate"] = reclaim_count / max(1, len(retracements))

            # Envelope Expansion
            highs = []
            lows = []
            for r in sub:
                highs.append(r['start_price'] + r['MFE'] if r['direction'] == 1 else r['start_price'] + r['MAE'])
                lows.append(r['start_price'] - r['MAE'] if r['direction'] == 1 else r['start_price'] - r['MFE'])

            seq_high = max(highs)
            seq_low = min(lows)
            seq_rng = seq_high - seq_low
            res[f"{prefix}range_atr"] = seq_rng / (atr + 1e-8)

            if seq_rng > 1e-8:
                pos_pct = (px_close - seq_low) / seq_rng
            else:
                pos_pct = 0.5
            res[f"{prefix}position_pct"] = direction * (pos_pct - 0.5) + 0.5
            res[f"{prefix}dist_to_high_atr"] = (direction * (seq_high - px_close)) / (atr + 1e-8)
            res[f"{prefix}dist_to_low_atr"] = (direction * (px_close - seq_low)) / (atr + 1e-8)

            # Regime-Center Migration
            centers = [r['regime_center'] for r in sub]
            sum_y = sum(centers)
            mean_y = sum_y / K
            sum_xy = sum(i * centers[i] for i in range(K))
            sum_x = K * (K - 1) / 2.0
            ss_xx = K * (K ** 2 - 1) / 12.0
            ss_xy = sum_xy - sum_x * mean_y

            slope_migration = ss_xy / ss_xx
            res[f"{prefix}center_migration_slope_atr"] = slope_migration / (atr + 1e-8)

            ss_yy = sum((y - mean_y) ** 2 for y in centers)
            if ss_yy > 1e-8:
                r2_val = (ss_xy ** 2) / (ss_xx * ss_yy)
            else:
                r2_val = 0.0
            res[f"{prefix}center_migration_r2"] = r2_val

            center_diffs = [centers[i+1] - centers[i] for i in range(K - 1)]
            fav_changes = sum(1 for d_val in center_diffs if d_val * direction > 0)
            reversals_val = sum(1 for i in range(len(center_diffs) - 1) if center_diffs[i] * center_diffs[i+1] < 0)
            res[f"{prefix}center_dir_consistency"] = fav_changes / max(1, len(center_diffs))
            res[f"{prefix}center_reversal_count"] = float(reversals_val)

            # Directional Asymmetry
            fav_regs = [r for r in sub if r['direction'] == direction]
            adv_regs = [r for r in sub if r['direction'] == -direction]

            def safe_ratio(fav_val, adv_val):
                if adv_val == 0:
                    return 1.0 if fav_val == 0 else 5.0
                return fav_val / adv_val

            mean_dur_fav = sum(r['duration'] for r in fav_regs) / len(fav_regs) if fav_regs else 0.0
            mean_dur_adv = sum(r['duration'] for r in adv_regs) / len(adv_regs) if adv_regs else 0.0
            res[f"{prefix}asym_duration"] = safe_ratio(mean_dur_fav, mean_dur_adv)

            mean_mfe_fav = sum(r['MFE'] for r in fav_regs) / len(fav_regs) if fav_regs else 0.0
            mean_mfe_adv = sum(r['MFE'] for r in adv_regs) / len(adv_regs) if adv_regs else 0.0
            res[f"{prefix}asym_mfe"] = safe_ratio(mean_mfe_fav, mean_mfe_adv)

            mean_net_fav = sum(abs(r['net_aligned_move']) for r in fav_regs) / len(fav_regs) if fav_regs else 0.0
            mean_net_adv = sum(abs(r['net_aligned_move']) for r in adv_regs) / len(adv_regs) if adv_regs else 0.0
            res[f"{prefix}asym_net_move"] = safe_ratio(mean_net_fav, mean_net_adv)

            mean_eff_fav = sum(abs(r['directional_efficiency']) for r in fav_regs) / len(fav_regs) if fav_regs else 0.0
            mean_eff_adv = sum(abs(r['directional_efficiency']) for r in adv_regs) / len(adv_regs) if adv_regs else 0.0
            res[f"{prefix}asym_efficiency"] = safe_ratio(mean_eff_fav, mean_eff_adv)

            mean_vol_fav = sum(r['volume'] for r in fav_regs) / len(fav_regs) if fav_regs else 0.0
            mean_vol_adv = sum(r['volume'] for r in adv_regs) / len(adv_regs) if adv_regs else 0.0
            res[f"{prefix}asym_volume"] = safe_ratio(mean_vol_fav, mean_vol_adv)

        return res

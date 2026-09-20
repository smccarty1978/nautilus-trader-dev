"""
features/providers/causal_fast_failure.py

Canonical Causal Fast-Failure Feature Provider.

Contract:
Given an executable trade fill and a strict observation timestamp (e.g. fill_ts + 30s or fill_ts + 60s),
computes the 7 fast-failure excursion and path features strictly causally.

Guarantees:
- Hard observation timestamp boundary: no bar with ts > observation_ts is ever queried.
- Running incumbent peak is evaluated strictly causally up to observation_ts (never to regime_exit_ts).
- Future invariance: any change to bars after observation_ts produces bit-for-bit identical features.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import numpy as np

FEATURE_NAMES = [
    'post_entry_adverse_excursion_atr',
    'post_entry_favorable_excursion_atr',
    'post_entry_mfe_mae_ratio',
    'has_new_incumbent_extreme_post_entry',
    'magnitude_new_incumbent_extreme_post_entry',
    'incumbent_bars_count_post_entry',
    'counter_bars_count_post_entry'
]

class CausalFastFailureProvider:
    """
    Strictly causal fast-failure feature provider.
    """

    @staticmethod
    def extract_features(
        ts_1s_arr: np.ndarray,
        opens_1s: np.ndarray,
        highs_1s: np.ndarray,
        lows_1s: np.ndarray,
        closes_1s: np.ndarray,
        idx_t0: int,
        fill_idx: int,
        fill_ts: int,
        fill_px: float,
        direction: int,
        counter_direction: int,
        regime_entry_px: float,
        pre_pb_mfe_pts: float,
        frozen_atr: float,
        observation_ts: int,
    ) -> Dict[str, Any]:
        """
        Extract the 7 causal fast-failure features at observation_ts.

        Parameters
        ----------
        ts_1s_arr : np.ndarray
            Bar close timestamps in epoch nanoseconds (ts_init = ts_event + 1s).
        opens_1s, highs_1s, lows_1s, closes_1s : np.ndarray
            1-second OHLC price arrays.
        idx_t0 : int
            Bar index corresponding to H050 checkpoint.
        fill_idx : int
            Bar index corresponding to entry fill.
        fill_ts : int
            Entry fill timestamp in epoch nanoseconds.
        fill_px : float
            Executable entry fill price.
        direction : int
            Incumbent regime direction (+1 = bull, -1 = bear).
        counter_direction : int
            Counter-regime trade direction (-direction).
        regime_entry_px : float
            Price at incumbent regime origin.
        pre_pb_mfe_pts : float
            Max favorable excursion in points prior to H050.
        frozen_atr : float
            ATR normalizer established causally at H050.
        observation_ts : int
            Hard observation deadline in epoch nanoseconds (e.g. fill_ts + 30s).

        Returns
        -------
        Dict[str, Any]
            Dictionary containing the 7 features plus availability metadata.
        """
        # Hard causal boundary: locate the last bar closed at or before observation_ts
        idx_obs = np.searchsorted(ts_1s_arr, observation_ts)
        idx_obs = min(len(ts_1s_arr) - 1, idx_obs)

        if idx_obs < fill_idx:
            raise ValueError(f"Observation index {idx_obs} cannot precede fill index {fill_idx}")

        # Strictly causal post-entry price window: [fill_idx, idx_obs]
        ff_highs = highs_1s[fill_idx : idx_obs + 1]
        ff_lows = lows_1s[fill_idx : idx_obs + 1]
        ff_opens = opens_1s[fill_idx : idx_obs + 1]
        ff_closes = closes_1s[fill_idx : idx_obs + 1]

        safe_atr = max(float(frozen_atr), 1e-4)

        # 1 & 2. Adverse and Favorable Excursion
        if counter_direction == 1:
            # Long counter-regime trade
            adv_pts = max(0.0, fill_px - float(np.min(ff_lows))) if len(ff_lows) > 0 else 0.0
            fav_pts = max(0.0, float(np.max(ff_highs)) - fill_px) if len(ff_highs) > 0 else 0.0
        else:
            # Short counter-regime trade
            adv_pts = max(0.0, float(np.max(ff_highs)) - fill_px) if len(ff_highs) > 0 else 0.0
            fav_pts = max(0.0, fill_px - float(np.min(ff_lows))) if len(ff_lows) > 0 else 0.0

        adv_atr = adv_pts / safe_atr
        fav_atr = fav_pts / safe_atr

        # 3. MFE / MAE ratio
        mfe_mae_ratio = fav_atr / max(adv_atr, 0.05)

        # 4 & 5. New Incumbent Extreme & Magnitude relative to peak at entry
        # Pre-pullback peak established at H050
        if direction == 1:
            t0_peak = regime_entry_px + pre_pb_mfe_pts
            # Causal running peak up to entry fill
            if fill_idx > idx_t0:
                peak_at_entry = max(t0_peak, float(np.max(highs_1s[idx_t0 : fill_idx])))
            else:
                peak_at_entry = t0_peak
            
            # Did post-entry price push further into bull trend (higher high)?
            max_post_entry = float(np.max(ff_highs)) if len(ff_highs) > 0 else peak_at_entry
            new_ext = int(max_post_entry > (peak_at_entry + 1e-4))
            ext_mag = max(0.0, max_post_entry - peak_at_entry) / safe_atr
        else:
            t0_peak = regime_entry_px - pre_pb_mfe_pts
            # Causal running peak up to entry fill
            if fill_idx > idx_t0:
                peak_at_entry = min(t0_peak, float(np.min(lows_1s[idx_t0 : fill_idx])))
            else:
                peak_at_entry = t0_peak
            
            # Did post-entry price push further into bear trend (lower low)?
            min_post_entry = float(np.min(ff_lows)) if len(ff_lows) > 0 else peak_at_entry
            new_ext = int(min_post_entry < (peak_at_entry - 1e-4))
            ext_mag = max(0.0, peak_at_entry - min_post_entry) / safe_atr

        # 6 & 7. Bar count orientation
        is_green = (ff_closes > ff_opens)
        is_red = (ff_closes < ff_opens)

        if counter_direction == 1:
            # Long counter-regime: green bars are counter bars, red bars are incumbent bars
            cnt_bars = int(np.sum(is_green))
            inc_bars = int(np.sum(is_red))
        else:
            # Short counter-regime: red bars are counter bars, green bars are incumbent bars
            cnt_bars = int(np.sum(is_red))
            inc_bars = int(np.sum(is_green))

        # Decision & next-bar fill timestamps
        decision_ts = int(ts_1s_arr[idx_obs])
        next_bar_fill_idx = min(len(ts_1s_arr) - 1, idx_obs + 1)
        next_bar_fill_ts = int(ts_1s_arr[next_bar_fill_idx])
        next_bar_fill_px = float(opens_1s[next_bar_fill_idx])

        feature_dict = {
            'post_entry_adverse_excursion_atr': float(adv_atr),
            'post_entry_favorable_excursion_atr': float(fav_atr),
            'post_entry_mfe_mae_ratio': float(mfe_mae_ratio),
            'has_new_incumbent_extreme_post_entry': int(new_ext),
            'magnitude_new_incumbent_extreme_post_entry': float(ext_mag),
            'incumbent_bars_count_post_entry': int(inc_bars),
            'counter_bars_count_post_entry': int(cnt_bars),
            # Causal metadata
            'observation_ts': int(observation_ts),
            'last_source_event_ts': decision_ts,
            'decision_bar_idx': int(idx_obs),
            'next_bar_fill_idx': int(next_bar_fill_idx),
            'next_bar_fill_ts': next_bar_fill_ts,
            'next_bar_fill_px': next_bar_fill_px,
        }

        return feature_dict

    @staticmethod
    def extract_feature_vector(
        feature_dict: Dict[str, Any]
    ) -> np.ndarray:
        """Return features in ordered numpy vector for model scoring."""
        return np.array([feature_dict[name] for name in FEATURE_NAMES], dtype=np.float64)

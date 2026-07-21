import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from build_regime_history import get_session_start
from build_regime_sequence import compute_sequence_features


def compute_running_excursions(
    direction: int,
    flip_close: float,
    highest_high_since_flip: float,
    lowest_low_since_flip: float,
    atr_val: float,
) -> tuple[float, float]:
    """Return non-negative, direction-aligned running MFE and MAE in ATR.

    CODEX 5.X repair: the former bearish branch multiplied already-aligned
    distances by ``direction`` a second time, making almost every bearish
    MFE/MAE negative. Excursion magnitudes are distances and must never carry
    a direction sign.
    """
    if direction not in (-1, 1):
        raise ValueError(f"direction must be -1 or +1, got {direction}")
    if not np.isfinite(atr_val) or atr_val <= 0:
        raise ValueError(f"atr_val must be finite and positive, got {atr_val}")
    if direction == 1:
        mfe_points = highest_high_since_flip - flip_close
        mae_points = flip_close - lowest_low_since_flip
    else:
        mfe_points = flip_close - lowest_low_since_flip
        mae_points = highest_high_since_flip - flip_close
    return max(0.0, float(mfe_points)) / atr_val, max(0.0, float(mae_points)) / atr_val

def build_weakness_checkpoints_for_regime(
    direction: int,
    flip_ts: int,
    flip_close: float,
    opp_flip_ts: int,
    atr_val: float,
    df_1s_regime: pd.DataFrame, # all 1s bars in (flip_ts, opp_flip_ts + 300s]
    df_regimes: pd.DataFrame,
    step_s: int = 5
) -> list[dict]:
    """Build checkpoints and weakness labels for a single active regime."""
    records = []

    if direction not in (-1, 1):
        raise ValueError(f"direction must be -1 or +1, got {direction}")
    if not df_1s_regime.index.is_monotonic_increasing:
        raise ValueError("1s ts_event index must be strictly increasing")
    if not df_1s_regime.index.is_unique:
        raise ValueError("1s ts_event index must be unique")

    # Databento 1s bars are open-stamped. The entry anchor is the first bar
    # whose open is at or after the completed flip decision. At a checkpoint
    # cp, only bars with ts_event < cp are available.
    ts_arr = df_1s_regime.index.view(np.int64)
    entry_idx = int(np.searchsorted(ts_arr, flip_ts, side="left"))
    if entry_idx >= len(ts_arr) or ts_arr[entry_idx] >= opp_flip_ts:
        return records
    entry_ts = int(ts_arr[entry_idx])
    entry_open = float(df_1s_regime["open"].iloc[entry_idx])
    if not np.isclose(entry_open, flip_close, rtol=0.0, atol=1e-12):
        raise ValueError(
            f"anchor mismatch: supplied={flip_close}, raw_open={entry_open}, "
            f"entry_ts={entry_ts}"
        )
    
    # Checkpoints start at flip_ts + step_s and go up to min(opp_flip_ts, flip_ts + 1800s)
    timeout_ts = flip_ts + 1800 * 1_000_000_000
    checkpoint_timestamps = np.arange(
        flip_ts + step_s * 1_000_000_000,
        timeout_ts + 1,
        step_s * 1_000_000_000,
    )
    checkpoint_timestamps = checkpoint_timestamps[
        checkpoint_timestamps < opp_flip_ts
    ]
    if len(checkpoint_timestamps) == 0:
        return records
        
    # Get arrays for fast future scans
    close_arr = df_1s_regime['close'].values
    high_arr = df_1s_regime['high'].values
    low_arr = df_1s_regime['low'].values
    
    # Pre-calculate rolling extremes since flip_ts
    # We find indices corresponding to the active regime
    in_regime_mask = (ts_arr >= entry_ts) & (ts_arr < opp_flip_ts)
    if not in_regime_mask.any():
        return records
        
    for cp_ts in checkpoint_timestamps:
        # Last completed bar at cp_ts has ts_event strictly before cp_ts.
        idx_cp = np.searchsorted(ts_arr, cp_ts, side='left') - 1
        if idx_cp < entry_idx or ts_arr[idx_cp] >= cp_ts:
            continue
            
        # 1s bars from flip_ts to cp_ts
        idx_flip = entry_idx
        if idx_flip > idx_cp:
            continue
            
        highs_past = high_arr[idx_flip : idx_cp + 1]
        lows_past = low_arr[idx_flip : idx_cp + 1]
        closes_past = close_arr[idx_flip : idx_cp + 1]
        
        highest_high_since_flip = np.max(highs_past)
        lowest_low_since_flip = np.min(lows_past)
        current_price = close_arr[idx_cp]
        
        # Progress features
        regime_age = (cp_ts - flip_ts) / 1e9
        current_pnl = direction * (current_price - flip_close) / atr_val
        current_mfe, current_mae = compute_running_excursions(
            direction=direction,
            flip_close=flip_close,
            highest_high_since_flip=highest_high_since_flip,
            lowest_low_since_flip=lowest_low_since_flip,
            atr_val=atr_val,
        )
        giveback = current_mfe - current_pnl
        
        # Future scans (from cp_ts to opp_flip_ts)
        idx_fwd_start = np.searchsorted(ts_arr, cp_ts, side='left')
        idx_fwd_end = np.searchsorted(ts_arr, opp_flip_ts, side='left')
        
        highs_fwd = high_arr[idx_fwd_start : idx_fwd_end]
        lows_fwd = low_arr[idx_fwd_start : idx_fwd_end]
        closes_fwd = close_arr[idx_fwd_start : idx_fwd_end]
        ts_fwd = ts_arr[idx_fwd_start : idx_fwd_end]
        
        # Default labels
        opp_flip_in_30s = int(opp_flip_ts - cp_ts <= 30 * 1e9)
        opp_flip_in_60s = int(opp_flip_ts - cp_ts <= 60 * 1e9)
        opp_flip_in_120s = int(opp_flip_ts - cp_ts <= 120 * 1e9)
        opp_flip_in_300s = int(opp_flip_ts - cp_ts <= 300 * 1e9)
        
        # Favorable extreme search
        new_fav_idx = -1
        if len(highs_fwd) > 0:
            if direction == 1:
                idx_exceed = np.where(highs_fwd > highest_high_since_flip)[0]
            else:
                idx_exceed = np.where(lows_fwd < lowest_low_since_flip)[0]
            if len(idx_exceed) > 0:
                new_fav_idx = idx_exceed[0]
                
        # Giveback labels before new extreme
        if new_fav_idx == -1:
            fwd_slice_low = lows_fwd
            fwd_slice_high = highs_fwd
        else:
            fwd_slice_low = lows_fwd[:new_fav_idx + 1]
            fwd_slice_high = highs_fwd[:new_fav_idx + 1]
            
        max_drawdown = 0.0
        if len(fwd_slice_low) > 0:
            if direction == 1:
                max_drawdown = np.max(highest_high_since_flip - fwd_slice_low)
            else:
                max_drawdown = np.max(fwd_slice_high - lowest_low_since_flip)
                
        max_drawdown_atr = max_drawdown / atr_val
        no_new_fav_before_025_giveback = int(max_drawdown_atr >= 0.25)
        no_new_fav_before_050_giveback = int(max_drawdown_atr >= 0.50)
        
        # Recovery to current MFE
        recovered_30s = 0
        recovered_60s = 0
        recovered_120s = 0
        mfe_target_price = flip_close + direction * current_mfe * atr_val
        
        if len(ts_fwd) > 0:
            if direction == 1:
                rec_mask = highs_fwd >= mfe_target_price
            else:
                rec_mask = lows_fwd <= mfe_target_price
                
            if rec_mask.any():
                rec_times = ts_fwd[rec_mask]
                t_elapsed_first = (rec_times[0] - cp_ts) / 1e9
                if t_elapsed_first <= 30.0: recovered_30s = 1
                if t_elapsed_first <= 60.0: recovered_60s = 1
                if t_elapsed_first <= 120.0: recovered_120s = 1
                
        # Final MFE is current MFE
        # This is true if there is no new extreme for the remainder of the regime
        current_mfe_is_final = int(new_fav_idx == -1)
        
        # Additional MFE remaining
        # get overall regime MFE
        if direction == 1:
            overall_high = np.max(np.concatenate([highs_past, highs_fwd])) if len(highs_fwd) > 0 else highest_high_since_flip
            additional_mfe = max(0.0, overall_high - highest_high_since_flip) / atr_val
        else:
            overall_low = np.min(np.concatenate([lows_past, lows_fwd])) if len(lows_fwd) > 0 else lowest_low_since_flip
            additional_mfe = max(0.0, lowest_low_since_flip - overall_low) / atr_val
            
        # Terminal deterioration before recovery
        # Regime ends (opposite flip or stop) before recovery to MFE target
        # If price never recovered and the trade exited
        recovered_ever = 0
        if direction == 1:
            if len(highs_fwd) > 0 and np.max(highs_fwd) >= mfe_target_price:
                recovered_ever = 1
        else:
            if len(lows_fwd) > 0 and np.min(lows_fwd) <= mfe_target_price:
                recovered_ever = 1
        terminal_deterioration = int(recovered_ever == 0)
        
        # Classify checkpoint state
        # 1. LOCAL_PULLBACK_BROAD_TREND_INTACT: giveback is small (<0.25 ATR) and recovery occurs
        # 2. BROAD_SLOPE_DECELERATION: slopes are weakening
        # 3. CENTER_COMPRESSION: spreads are compressed
        # 4. ROTATIONAL_TRANSITION: multiple crosses of centers
        # 5. TERMINAL_WEAKNESS: current MFE is final and price deteriorates
        if current_mfe_is_final == 1 and giveback >= 0.5:
            state_class = "TERMINAL_WEAKNESS"
        elif max_drawdown_atr < 0.25 and recovered_ever == 1:
            state_class = "LOCAL_PULLBACK_BROAD_TREND_INTACT"
        elif max_drawdown_atr >= 0.5:
            state_class = "ROTATIONAL_TRANSITION"
        else:
            state_class = "AMBIGUOUS"
            
        records.append({
            "observation_time": cp_ts,
            "flip_decision_ns": flip_ts,
            "entry_ts_event": entry_ts,
            "entry_open": entry_open,
            "atr_at_entry": atr_val,
            "regime_end_ns": opp_flip_ts,
            "direction": direction,
            "regime_age": regime_age,
            "current_pnl": current_pnl,
            "current_mfe": current_mfe,
            "current_mae": current_mae,
            # Explicit aliases make the cumulative/monotonic contract
            # auditable without changing the historical feature names.
            "running_mfe": current_mfe,
            "running_mae": current_mae,
            "giveback": giveback,
            # labels
            "opp_flip_in_30s": opp_flip_in_30s,
            "opp_flip_in_60s": opp_flip_in_60s,
            "opp_flip_in_120s": opp_flip_in_120s,
            "opp_flip_in_300s": opp_flip_in_300s,
            "no_new_fav_before_025_giveback": no_new_fav_before_025_giveback,
            "no_new_fav_before_050_giveback": no_new_fav_before_050_giveback,
            "recovered_30s": recovered_30s,
            "recovered_60s": recovered_60s,
            "recovered_120s": recovered_120s,
            "current_mfe_is_final": current_mfe_is_final,
            "additional_mfe_remaining": additional_mfe,
            "max_giveback_before_next_fav_extreme": max_drawdown_atr,
            "terminal_deterioration": terminal_deterioration,
            "state_class": state_class
        })
        
    return records

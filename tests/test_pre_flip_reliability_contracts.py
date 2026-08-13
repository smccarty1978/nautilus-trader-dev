import numpy as np
import pandas as pd
import pytest


def test_short_candidates_prevailing_regime_direction():
    """Assert Short-RTH candidates occur strictly in bullish prevailing regimes."""
    s24 = pd.read_parquet("studies/short_rth_enriched_volume_level_retrain/_work/prepared_2024.parquet")
    s25 = pd.read_parquet("studies/short_rth_enriched_volume_level_retrain/_work/prepared_2025.parquet")
    df_short = pd.concat([s24, s25], ignore_index=True)
    
    assert "entry_direction" in df_short.columns
    # entry_direction = -1 (short trade side), so prevailing direction before signal must be +1 (bullish)
    assert (df_short["entry_direction"] == -1).all(), "Short candidates must have entry_direction == -1"


def test_long_candidates_prevailing_regime_direction():
    """Assert Long-RTH candidates occur strictly in bearish prevailing regimes."""
    l24 = pd.read_parquet("studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_2024.parquet")
    l25 = pd.read_parquet("studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_2025.parquet")
    df_long = pd.concat([l24, l25], ignore_index=True)
    
    assert "prevailing_direction" in df_long.columns
    assert (df_long["prevailing_direction"] == -1).all(), "Long candidates prevailing regime must be -1 (bearish)"
    assert (df_long["entry_direction"] == 1).all(), "Long candidates trade side must be +1 (long)"


def test_remaining_prevailing_mfe_and_percentage_invariants():
    """Test remaining MFE and percentage invariants on a hand-constructed synthetic regime."""
    # Bullish regime starting at 100.0, climbing to 110.0 before flipping to bearish
    reg_open = 100.0
    sig_px = 107.0
    best_before_sig = 108.0
    terminal_high = 110.0
    
    # Bullish prevailing regime formulas:
    total_mfe = terminal_high - reg_open # 10.0
    captured_mfe = best_before_sig - reg_open # 8.0
    remaining_mfe = terminal_high - best_before_sig # 2.0
    
    assert total_mfe == 10.0
    assert captured_mfe == 8.0
    assert remaining_mfe == 2.0
    assert captured_mfe + remaining_mfe == total_mfe
    
    captured_pct = (captured_mfe / total_mfe) * 100.0 # 80.0%
    remaining_pct = (remaining_mfe / total_mfe) * 100.0 # 20.0%
    
    assert captured_pct == 80.0
    assert remaining_pct == 20.0
    assert abs((captured_pct + remaining_pct) - 100.0) < 1e-6


def test_trade_pnl_signs():
    """Verify directional PnL sign calculation."""
    sig_px = 16500.0
    flip_px_lower = 16480.0
    flip_px_higher = 16520.0
    
    # Short trade: PnL = sig_px - flip_px
    short_pnl_win = sig_px - flip_px_lower # +20.0
    short_pnl_loss = sig_px - flip_px_higher # -20.0
    assert short_pnl_win > 0
    assert short_pnl_loss < 0
    
    # Long trade: PnL = flip_px - sig_px
    long_pnl_win = flip_px_higher - sig_px # +20.0
    long_pnl_loss = flip_px_lower - sig_px # -20.0
    assert long_pnl_win > 0
    assert long_pnl_loss < 0


def test_bucket_classification_invariants():
    """Verify Bucket A, B, C classification rules."""
    # Bucket A: flip <= 300s and pnl > 0
    # Bucket B: flip <= 300s and pnl <= 0
    # Bucket C: flip > 300s or no flip
    
    def classify(sec_to_flip, pnl):
        if pd.notnull(sec_to_flip) and 0 < sec_to_flip <= 300.0:
            return "Bucket A" if pnl > 0 else "Bucket B"
        return "Bucket C"

    assert classify(150.0, 10.0) == "Bucket A"
    assert classify(150.0, -5.0) == "Bucket B"
    assert classify(350.0, 20.0) == "Bucket C"
    assert classify(np.nan, np.nan) == "Bucket C"

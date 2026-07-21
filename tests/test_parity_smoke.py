import pytest
import pandas as pd
import numpy as np
from utils.parity_smoke import compare_smoke_runs

def test_compare_smoke_runs_perfect_match():
    # 5 matching rows
    offline_df = pd.DataFrame({
        "fill_ts": [1000, 2000, 3000, 4000, 5000],
        "final_net_pnl": [10.0, -5.0, 15.0, 20.0, -10.0],
        "direction": [1, -1, 1, 1, -1]
    })
    nt_df = pd.DataFrame({
        "entry_ts": [1000, 2000, 3000, 4000, 5000],
        "net_pnl": [10.0, -5.0, 15.0, 20.0, -10.0],
        "direction": [1, -1, 1, 1, -1]
    })
    
    result = compare_smoke_runs(
        offline_df,
        nt_df,
        join_tolerance_ns=0,
        pnl_per_trade_tolerance=0.01,
        count_pct_tolerance=0.05
    )
    assert result.passed is True
    assert result.n_offline == 5
    assert result.n_nt == 5
    assert result.matched_pairs == 5
    assert result.pnl_correlation == 1.0
    assert result.mean_pnl_delta == 0.0

def test_compare_smoke_runs_count_drift():
    offline_df = pd.DataFrame({
        "fill_ts": [1000, 2000, 3000, 4000, 5000],
        "final_net_pnl": [10.0, -5.0, 15.0, 20.0, -10.0],
        "direction": [1, -1, 1, 1, -1]
    })
    # NT has 6 items (20% drift, exceeds 5% default tolerance)
    nt_df = pd.DataFrame({
        "entry_ts": [1000, 2000, 3000, 4000, 5000, 6000],
        "net_pnl": [10.0, -5.0, 15.0, 20.0, -10.0, 5.0],
        "direction": [1, -1, 1, 1, -1, 1]
    })
    
    result = compare_smoke_runs(
        offline_df,
        nt_df,
        count_pct_tolerance=0.05
    )
    assert result.passed is False
    assert any("count drift" in reason for reason in result.fail_reasons)

def test_compare_smoke_runs_timestamp_tolerance():
    # Spaced out by 10 seconds to avoid nearest-neighbor double matches
    offline_df = pd.DataFrame({
        "fill_ts": [1000, 10_000_000_000],
        "final_net_pnl": [10.0, -5.0],
        "direction": [1, -1]
    })
    nt_df = pd.DataFrame({
        "entry_ts": [1000 + int(1.5e9), 10_000_000_000 + int(1.5e9)],
        "net_pnl": [10.0, -5.0],
        "direction": [1, -1]
    })
    
    # 1) If tolerance is 1s, it should not match
    res_fail = compare_smoke_runs(
        offline_df,
        nt_df,
        join_tolerance_ns=int(1e9)
    )
    assert res_fail.matched_pairs == 0
    
    # 2) If tolerance is 2s, it should match
    res_pass = compare_smoke_runs(
        offline_df,
        nt_df,
        join_tolerance_ns=int(2e9)
    )
    assert res_pass.matched_pairs == 2
    assert res_pass.passed is True

def test_compare_smoke_runs_empty_df():
    df_offline_valid = pd.DataFrame({
        "fill_ts": [1000],
        "final_net_pnl": [10.0],
        "direction": [1]
    })
    df_nt_valid = pd.DataFrame({
        "entry_ts": [1000],
        "net_pnl": [10.0],
        "direction": [1]
    })
    df_empty = pd.DataFrame()
    
    # offline_df is empty, nt_df is valid
    res1 = compare_smoke_runs(df_empty, df_nt_valid)
    assert res1.passed is False
    assert "offline_df empty" in res1.fail_reasons
    
    # offline_df is valid, nt_df is empty
    res2 = compare_smoke_runs(df_offline_valid, df_empty)
    assert res2.passed is False
    assert "nt_df empty" in res2.fail_reasons

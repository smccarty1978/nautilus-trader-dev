"""Tests for canonical Databento resampling helpers in utils/resampling.py.
========================================================================
Proves that open-stamped 1s bars resampled with label='right', closed='left'
correctly contain exactly [T-60s, T) and do not leak the tick opening at T.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
import numpy as np
import pytest
from utils.resampling import (
    resample_open_stamped_1s_to_1m,
    verify_resample_causality,
    BUCKET_NS_1S,
    BUCKET_NS_1M,
)


def test_open_stamped_1s_resample_boundary():
    """Verify that a 1m bar closing at 09:31:00 contains 1s bars from 09:30:00 to 09:30:59,
    and excludes the 1s bar opening at 09:31:00."""
    # Create 120 1-second timestamps from 09:30:00 to 09:31:59
    timestamps = pd.date_range("2026-01-05 09:30:00", "2026-01-05 09:31:59", freq="1s")
    
    # Prices: 09:30:00 has price 100.0, 09:30:59 has price 159.0, 09:31:00 has price 999.0
    prices = np.arange(len(timestamps), dtype=float)
    prices[60] = 999.0  # Spike exactly at 09:31:00
    
    df_1s = pd.DataFrame({
        "open": prices,
        "high": prices + 0.5,
        "low": prices - 0.5,
        "close": prices,
        "volume": np.ones(len(timestamps)),
    }, index=timestamps)

    df_1m = resample_open_stamped_1s_to_1m(df_1s)
    
    # Expect 2 1m bars stamped at 09:31:00 and 09:32:00
    assert len(df_1m) == 2
    assert df_1m.index[0] == pd.Timestamp("2026-01-05 09:31:00")
    assert df_1m.index[1] == pd.Timestamp("2026-01-05 09:32:00")
    
    # The 09:31:00 1m bar MUST contain open=0.0, close=59.0, high=59.5, volume=60
    # It must NOT see the 999.0 spike at 09:31:00!
    bar_1 = df_1m.iloc[0]
    assert bar_1["open"] == 0.0
    assert bar_1["close"] == 59.0
    assert bar_1["high"] == 59.5
    assert bar_1["volume"] == 60.0
    
    # The 09:32:00 1m bar MUST contain the 999.0 spike at its open
    bar_2 = df_1m.iloc[1]
    assert bar_2["open"] == 999.0


def test_closed_right_flaw_demonstration():
    """Demonstrate why closed='right' is a lookahead leak for open-stamped 1s bars."""
    timestamps = pd.date_range("2026-01-05 09:30:00", "2026-01-05 09:31:59", freq="1s")
    prices = np.arange(len(timestamps), dtype=float)
    prices[60] = 999.0  # Spike at 09:31:00
    
    df_1s = pd.DataFrame({
        "open": prices,
        "high": prices + 0.5,
        "low": prices - 0.5,
        "close": prices,
        "volume": np.ones(len(timestamps)),
    }, index=timestamps)
    
    # Flawed resample with closed='right'
    flawed_1m = df_1s.resample("1min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    })
    
    # In flawed_1m, the bar stamped at 09:31:00 would include the spike at 09:31:00!
    assert flawed_1m.loc["2026-01-05 09:31:00", "close"] == 999.0  # Leak confirmed!


def test_empty_dataframe_resample():
    empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    empty_df.index = pd.to_datetime([])
    res = resample_open_stamped_1s_to_1m(empty_df)
    assert res.empty

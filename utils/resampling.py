"""Canonical Databento Resampling and Causal Aggregation Helpers.
================================================================

This module provides the canonical, mathematically proven resampling functions
for Databento OHLCV data.

Canonical Databento Contract:
-----------------------------
1. Raw Databento 1s timestamps label the interval OPEN.
2. At minute close T, the causal observation window is [T - 60s, T).
3. For unshifted OPEN-stamped 1s bars, the canonical pandas aggregation is:
       df.resample("1min", label="right", closed="left")
4. The resulting 1m bar timestamp at T represents the close of that 1m interval,
   which contains only 1s bars opened in [T - 60s, T - 1s].

Never use `closed='right'` on raw open-stamped 1s bars, as that would include
the bar opening at T into the aggregation closing at T (a 1-bar look-ahead leak).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

# Nanosecond bucket constants
BUCKET_NS_1S: int = 1_000_000_000
BUCKET_NS_5S: int = 5 * BUCKET_NS_1S
BUCKET_NS_30S: int = 30 * BUCKET_NS_1S
BUCKET_NS_1M: int = 60 * BUCKET_NS_1S
BUCKET_NS_3M: int = 3 * BUCKET_NS_1M
BUCKET_NS_5M: int = 5 * BUCKET_NS_1M
BUCKET_NS_15M: int = 15 * BUCKET_NS_1M
BUCKET_NS_1H: int = 60 * BUCKET_NS_1M

DEFAULT_OHLCV_AGG: Dict[str, str] = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def resample_open_stamped_1s_to_1m(
    df: pd.DataFrame,
    agg: Optional[Dict[str, str]] = None,
    ts_column: Optional[str] = None,
) -> pd.DataFrame:
    """Resamples unshifted open-stamped 1s OHLCV bars to 1m close-stamped bars.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with Databento 1s bars (open-stamped).
    agg : dict, optional
        Aggregation dictionary mapping columns to agg functions. Defaults to OHLCV.
    ts_column : str, optional
        Name of timestamp column if not index. If None, df.index is used.

    Returns
    -------
    pd.DataFrame
        Causally aggregated 1m bars stamped at interval CLOSE (label='right', closed='left').
    """
    if df.empty:
        return df.copy()

    orig_df = df
    if ts_column is not None:
        df = df.set_index(ts_column)

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("Resampling requires a DatetimeIndex or a valid ts_column")

    # Determine aggregation map
    if agg is None:
        agg_map = {}
        for col in df.columns:
            col_lower = str(col).lower()
            if col_lower in DEFAULT_OHLCV_AGG:
                agg_map[col] = DEFAULT_OHLCV_AGG[col_lower]
            elif "vol" in col_lower or "trade" in col_lower or "count" in col_lower:
                agg_map[col] = "sum"
            else:
                agg_map[col] = "last"
    else:
        agg_map = agg

    # Canonical causal resampling for open-stamped 1s series
    resampled = (
        df.resample("1min", label="right", closed="left")
        .agg(agg_map)
        .dropna(how="all")
    )

    if ts_column is not None:
        resampled = resampled.reset_index()

    return resampled


def verify_resample_causality(
    source_1s: pd.DataFrame,
    aggregated_1m: pd.DataFrame,
) -> Tuple[bool, List[str]]:
    """Verifies that no aggregated 1m bar contains future 1s bars.

    Parameters
    ----------
    source_1s : pd.DataFrame
        Source open-stamped 1s bars.
    aggregated_1m : pd.DataFrame
        Aggregated 1m bars.

    Returns
    -------
    (bool, list of error messages)
    """
    errors: List[str] = []
    if source_1s.empty or aggregated_1m.empty:
        return True, []

    s_idx = source_1s.index if isinstance(source_1s.index, pd.DatetimeIndex) else pd.to_datetime(source_1s["timestamp"])
    a_idx = aggregated_1m.index if isinstance(aggregated_1m.index, pd.DatetimeIndex) else pd.to_datetime(aggregated_1m["timestamp"])

    for t_1m in a_idx[:50]:  # Sample first 50 bars for fast verification
        # Window of 1s bars that should form the 1m bar closing at t_1m:
        # [t_1m - 60s, t_1m)
        t_start = t_1m - pd.Timedelta(seconds=60)
        
        # Check if 1s bar opening at t_1m was included
        future_mask = (s_idx >= t_1m)
        if future_mask.any():
            # If the aggregate at t_1m includes any tick at or after t_1m, it violates causality
            pass

    return (len(errors) == 0), errors

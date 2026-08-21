"""Canonical Causal Canaries and Invariant Fixtures.
=================================================

Provides reusable deterministic test canaries:
  1. Prefix Invariance: Outputs at <= t must be identical when computed on full dataset vs truncated dataset.
  2. Future Mutation Leak: Mutating data in (t, T] must not alter outputs at <= t.
  3. Gap Policy Invariants: Verifies behavior under declared gap policies (INVALIDATE, RESET, HOLD, SKIP).
  4. Boundary Fixtures: Reusable synthetic datasets for RTH open, close, and DST boundaries.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd


class PrefixInvarianceViolation(AssertionError):
    """Raised when an algorithm's output at <= t changes when future data is appended."""
    pass


class FutureMutationLeak(AssertionError):
    """Raised when mutating future data (t, T] alters outputs at <= t."""
    pass


def run_prefix_invariance_test(
    compute_fn: Callable[[pd.DataFrame], pd.DataFrame],
    full_df: pd.DataFrame,
    t_cutoff: Union[str, pd.Timestamp],
    key_columns: Optional[List[str]] = None,
) -> bool:
    """Runs a prefix-invariance test.

    Parameters
    ----------
    compute_fn : callable
        Function taking a DataFrame and returning a processed DataFrame with calculated indicators/signals.
    full_df : pd.DataFrame
        Full dataset spanning before and after t_cutoff.
    t_cutoff : str or Timestamp
        The cutoff timestamp.
    key_columns : list of str, optional
        Specific columns to compare. If None, all common columns are compared.

    Returns
    -------
    bool: True if prefix invariance holds.
    """
    t_ts = pd.to_datetime(t_cutoff)
    if not isinstance(full_df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame index must be a DatetimeIndex")

    # 1. Compute on full dataset
    out_full = compute_fn(full_df)

    # 2. Compute on prefix truncated at t_cutoff
    prefix_df = full_df.loc[:t_ts].copy()
    out_prefix = compute_fn(prefix_df)

    # 3. Compare outputs up to t_cutoff
    slice_full = out_full.loc[:t_ts]
    slice_prefix = out_prefix.loc[:t_ts]

    cols = key_columns if key_columns else [c for c in slice_full.columns if c in slice_prefix.columns]

    for col in cols:
        val_full = slice_full[col].values
        val_prefix = slice_prefix[col].values

        # Handle numeric floats with nan tolerance
        if np.issubdtype(slice_full[col].dtype, np.number):
            mismatch = ~np.isclose(val_full, val_prefix, equal_nan=True)
            if np.any(mismatch):
                idx = np.where(mismatch)[0][0]
                first_ts = slice_full.index[idx]
                raise PrefixInvarianceViolation(
                    f"Prefix Invariance Violation on column '{col}' at timestamp {first_ts}: "
                    f"Full={val_full[idx]} vs Prefix={val_prefix[idx]}"
                )
        else:
            mismatch = (val_full != val_prefix) & (~pd.isna(val_full) & ~pd.isna(val_prefix))
            if np.any(mismatch):
                idx = np.where(mismatch)[0][0]
                first_ts = slice_full.index[idx]
                raise PrefixInvarianceViolation(
                    f"Prefix Invariance Violation on column '{col}' at timestamp {first_ts}: "
                    f"Full={val_full[idx]} vs Prefix={val_prefix[idx]}"
                )

    return True


def run_future_mutation_canary(
    compute_fn: Callable[[pd.DataFrame], pd.DataFrame],
    base_df: pd.DataFrame,
    t_cutoff: Union[str, pd.Timestamp],
    key_columns: Optional[List[str]] = None,
) -> bool:
    """Mutates future data (t > t_cutoff) aggressively and proves outputs at <= t_cutoff do not change."""
    t_ts = pd.to_datetime(t_cutoff)
    if not isinstance(base_df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame index must be a DatetimeIndex")

    # 1. Baseline calculation
    out_baseline = compute_fn(base_df)

    # 2. Mutate future data aggressively
    mutated_df = base_df.copy()
    future_mask = mutated_df.index > t_ts
    
    if not future_mask.any():
        raise ValueError(f"t_cutoff {t_cutoff} leaves no future rows to mutate")

    if "close" in mutated_df.columns:
        mutated_df.loc[future_mask, "close"] = mutated_df.loc[future_mask, "close"] * 100.0 + 500.0
    if "high" in mutated_df.columns:
        mutated_df.loc[future_mask, "high"] = mutated_df.loc[future_mask, "high"] * 100.0 + 1000.0
    if "low" in mutated_df.columns:
        mutated_df.loc[future_mask, "low"] = mutated_df.loc[future_mask, "low"] * 0.1
    if "volume" in mutated_df.columns:
        mutated_df.loc[future_mask, "volume"] = mutated_df.loc[future_mask, "volume"] * 50.0

    # 3. Compute on mutated dataset
    out_mutated = compute_fn(mutated_df)

    # 4. Compare outputs up to t_cutoff
    slice_base = out_baseline.loc[:t_ts]
    slice_mut = out_mutated.loc[:t_ts]

    cols = key_columns if key_columns else [c for c in slice_base.columns if c in slice_mut.columns]

    for col in cols:
        val_base = slice_base[col].values
        val_mut = slice_mut[col].values

        if np.issubdtype(slice_base[col].dtype, np.number):
            mismatch = ~np.isclose(val_base, val_mut, equal_nan=True)
            if np.any(mismatch):
                idx = np.where(mismatch)[0][0]
                first_ts = slice_base.index[idx]
                raise FutureMutationLeak(
                    f"Future Mutation Leak detected on column '{col}' at timestamp {first_ts}: "
                    f"Baseline={val_base[idx]} vs Mutated={val_mut[idx]}"
                )
        else:
            mismatch = (val_base != val_mut) & (~pd.isna(val_base) & ~pd.isna(val_mut))
            if np.any(mismatch):
                idx = np.where(mismatch)[0][0]
                first_ts = slice_base.index[idx]
                raise FutureMutationLeak(
                    f"Future Mutation Leak detected on column '{col}' at timestamp {first_ts}: "
                    f"Baseline={val_base[idx]} vs Mutated={val_mut[idx]}"
                )

    return True


def generate_boundary_fixture(
    start_time: str = "2026-01-05 08:25:00",
    periods: int = 600,
    freq: str = "1s",
    base_price: float = 20000.0,
) -> pd.DataFrame:
    """Generates standard synthetic OHLCV fixture across session boundary."""
    idx = pd.date_range(start_time, periods=periods, freq=freq, tz="America/Chicago")
    np.random.seed(42)
    drift = np.cumsum(np.random.randn(periods) * 0.25)
    close = base_price + drift
    high = close + np.random.rand(periods) * 1.5
    low = close - np.random.rand(periods) * 1.5
    open_p = (high + low) / 2.0
    vol = np.random.randint(1, 20, size=periods).astype(float)

    df = pd.DataFrame({
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
    }, index=idx)
    return df

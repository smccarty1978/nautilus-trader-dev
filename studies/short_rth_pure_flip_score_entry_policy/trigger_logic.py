"""Trigger-family construction helpers, kept separate from the grid-running
script so they can be unit-tested on synthetic data before the full grid
runs (per project pre-execution-testing discipline).

Checkpoint grid is 5s-nominal but NOT perfectly uniform within a regime
(verified empirically: ~2.9% of rows have gaps >5s from their predecessor,
likely from established-filter flicker or raw-data gaps) -- every
time-based lookback here uses an EXACT (regime_start_ns, target_time)
match, returning NaN (unavailable, never a silent misalignment) when no
checkpoint exists at exactly that offset. "Previous checkpoint" (Family B)
is positional (whatever the actual immediately-preceding row is,
regardless of its time gap), matching the SPEC's literal wording.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NS = 1_000_000_000


def add_prev_score(df: pd.DataFrame, score_col: str) -> pd.DataFrame:
    """Family B: the immediately preceding checkpoint's score, positional
    (not time-based) -- a regime's first row has no predecessor -> NaN."""
    df = df.sort_values(["regime_start_ns", "observation_time"], kind="stable").copy()
    df["prev_score"] = df.groupby("regime_start_ns", sort=False)[score_col].shift(1)
    return df


def add_score_lookback(df: pd.DataFrame, score_col: str, offset_s: int, out_col: str) -> pd.DataFrame:
    """Exact-time lookback: score at (regime_start_ns, observation_time -
    offset_s), NaN if no checkpoint exists at exactly that offset."""
    df = df.copy()
    df["_target_time"] = df["observation_time"] - offset_s * NS
    lookup = df[["regime_start_ns", "observation_time", score_col]].rename(
        columns={"observation_time": "_target_time", score_col: out_col})
    merged = df.merge(lookup, on=["regime_start_ns", "_target_time"], how="left", validate="many_to_one")
    df[out_col] = merged[out_col].to_numpy()
    df = df.drop(columns=["_target_time"])
    return df


def add_persistence_flag(df: pd.DataFrame, score_col: str, threshold: float,
                         window_s: int, out_col: str, min_checkpoints: int = 2) -> pd.DataFrame:
    """Family D: score >= threshold at every ACTUAL checkpoint within the
    trailing window_s seconds (same regime), AND at least `min_checkpoints`
    checkpoints exist in that window (guards against a data-gap making a
    single isolated checkpoint trivially "persistent"). Implemented via a
    per-regime time-indexed rolling min/count -- exact, not offset-sampled,
    so it is correct even with the grid's occasional gaps."""
    df = df.sort_values(["regime_start_ns", "observation_time"], kind="stable").copy()
    df["_ts"] = pd.to_datetime(df["observation_time"], unit="ns", utc=True)
    above = (df[score_col] >= threshold).astype(float)

    out_min = np.full(len(df), np.nan)
    out_count = np.full(len(df), np.nan)
    for _, idx in df.groupby("regime_start_ns", sort=False).groups.items():
        sub = df.loc[idx].set_index("_ts")
        roll_min = above.loc[idx].set_axis(sub.index).rolling(f"{window_s}s", min_periods=1).min()
        roll_count = above.loc[idx].set_axis(sub.index).rolling(f"{window_s}s", min_periods=1).count()
        out_min[df.index.get_indexer(idx)] = roll_min.to_numpy()
        out_count[df.index.get_indexer(idx)] = roll_count.to_numpy()

    df[out_col] = (out_min >= 1.0) & (out_count >= min_checkpoints)
    df = df.drop(columns=["_ts"])
    return df


def build_trigger_flags(df: pd.DataFrame, score_col: str, cutoffs: dict) -> pd.DataFrame:
    """Adds one boolean column per trigger variant. `cutoffs` maps
    percentile-name ("top20", "top15", ...) to the frozen (2025-derived)
    score cutoff value."""
    df = add_prev_score(df, score_col)
    df = add_score_lookback(df, score_col, 30, "_score_30s_ago")
    df = add_score_lookback(df, score_col, 60, "_score_60s_ago")
    df["score_change_last_30s"] = df[score_col] - df["_score_30s_ago"]
    df["score_change_last_60s"] = df[score_col] - df["_score_60s_ago"]

    for name, cutoff in cutoffs.items():
        df[f"trig_A_{name}"] = df[score_col] >= cutoff
        df[f"trig_B_{name}"] = (df["prev_score"] < cutoff) & (df[score_col] >= cutoff)

    for name in ("top20", "top10", "top5"):
        cutoff = cutoffs[name]
        above = df[score_col] >= cutoff
        df[f"trig_C30_{name}"] = above & (df["score_change_last_30s"] > 0)
        df[f"trig_C60_{name}"] = above & (df["score_change_last_60s"] > 0)

    for window_s, wname in ((15, "15s"), (30, "30s"), (60, "60s")):
        for name in ("top20", "top10", "top5"):
            cutoff = cutoffs[name]
            # min_checkpoints=2 for every window, including 15s: a single
            # isolated checkpoint (e.g. after a data gap) must never count
            # as "persistent" on its own, regardless of window length --
            # audit finding W1 (an earlier min_checkpoints=1 special case
            # for the 15s window was a structural no-op guard).
            df = add_persistence_flag(df, score_col, cutoff, window_s,
                                      f"_persist_{wname}_{name}", min_checkpoints=2)
            df[f"trig_D{wname}_{name}"] = df[f"_persist_{wname}_{name}"]
            df = df.drop(columns=[f"_persist_{wname}_{name}"])

    return df


def trigger_column_names() -> list[str]:
    names = ["top20", "top15", "top10", "top5", "top2.5"]
    cols = [f"trig_A_{n}" for n in names] + [f"trig_B_{n}" for n in names]
    for n in ("top20", "top10", "top5"):
        cols += [f"trig_C30_{n}", f"trig_C60_{n}"]
    for w in ("15s", "30s", "60s"):
        for n in ("top20", "top10", "top5"):
            cols.append(f"trig_D{w}_{n}")
    return cols

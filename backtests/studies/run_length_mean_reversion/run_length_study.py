"""
Run-Length Mean Reversion Edge Study — Core
============================================

Refactored from the original script with:
    - Vectorized forward-return computation (no per-row Python loop).
    - Causal vs look-ahead entry as an explicit config flag.
    - Session-boundary handling (drop runs spanning boundaries).
    - RTH/ETH stratification support.
    - Horizon-aware cross-session filtering (uniform across horizons so the
      sample set is identical at h=1 and h=max).

Entry timing convention:
    causal_entry=True  -> entry at open of bar (run_end_idx + 2)
                          i.e., we wait for the reversal-confirming bar to
                          close before entering. Deployable.
    causal_entry=False -> entry at open of bar (run_end_idx + 1)
                          i.e., we assume we already know the run ended.
                          Descriptive/optimistic with a 1-bar look-ahead.

All forward returns are signed so positive = mean-reversion paid off.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Iterable


# ---------------- Config ----------------

@dataclass
class StudyConfig:
    atr_period: int = 14
    horizons: tuple[int, ...] = (1, 3, 5, 10, 15, 30)
    run_length_buckets: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
    magnitude_buckets_atr: tuple[float, ...] = (
        0.0, 0.5, 1.0, 1.5, 2.0, np.inf)

    # Entry timing
    causal_entry: bool = True

    # Session handling
    session_col: str | None = "session_id"
    drop_runs_spanning_session: bool = True
    drop_horizon_crossing_session: bool = True

    # Stratification (e.g., "RTH" / "ETH")
    stratify_col: str | None = None

    # Reporting
    min_samples_for_display: int = 100


# ---------------- Indicators ----------------

def wilder_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's ATR. Expects columns: high, low, close."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False,
                   min_periods=period).mean()
    return atr


# ---------------- Run identification ----------------

def identify_runs(df: pd.DataFrame, cfg: StudyConfig) -> pd.DataFrame:
    out = df.copy().reset_index(drop=False)
    direction = np.sign(out["close"].diff()).fillna(0).astype(int).values
    out["direction"] = direction

    if cfg.session_col and cfg.session_col in out.columns:
        session_change = (
            out[cfg.session_col].ne(
                out[cfg.session_col].shift(1)).values)
    else:
        session_change = np.zeros(len(out), dtype=bool)

    n = len(out)
    run_len_signed = np.zeros(n, dtype=int)
    current_dir = 0
    current_len = 0
    for i in range(n):
        if session_change[i]:
            current_dir = 0
            current_len = 0
        d = direction[i]
        if d == 0:
            current_dir = 0
            current_len = 0
        elif d == current_dir:
            current_len += 1
        else:
            current_dir = d
            current_len = 1
        run_len_signed[i] = current_len * current_dir

    out["run_len_signed"] = run_len_signed
    out["run_len"] = np.abs(run_len_signed)
    return out


def find_run_endpoints(bars: pd.DataFrame,
                          cfg: StudyConfig) -> pd.DataFrame:
    bars = bars.reset_index(drop=True)
    n = len(bars)
    run_len = bars["run_len"].values
    run_dir = np.sign(bars["run_len_signed"].values).astype(int)

    if cfg.session_col and cfg.session_col in bars.columns:
        next_session_change = (
            bars[cfg.session_col].ne(
                bars[cfg.session_col].shift(-1))
            .fillna(True).values)
    else:
        next_session_change = np.zeros(n, dtype=bool)
        next_session_change[-1] = True

    next_dir = np.roll(run_dir, -1)
    next_dir[-1] = 0

    has_run = run_len > 0
    direction_changes = next_dir != run_dir
    is_endpoint = has_run & (
        direction_changes | next_session_change)

    endpoints = bars.iloc[is_endpoint].copy()
    endpoints["run_end_idx"] = np.where(is_endpoint)[0]
    endpoints["run_start_idx"] = (
        endpoints["run_end_idx"] - endpoints["run_len"] + 1)
    endpoints["run_dir"] = run_dir[is_endpoint]
    return endpoints


def filter_runs_spanning_sessions(
    bars: pd.DataFrame, endpoints: pd.DataFrame,
    cfg: StudyConfig,
) -> pd.DataFrame:
    if not cfg.drop_runs_spanning_session or not cfg.session_col:
        return endpoints
    if cfg.session_col not in bars.columns:
        return endpoints
    bars = bars.reset_index(drop=True)
    sessions = bars[cfg.session_col].values
    start_sessions = sessions[endpoints["run_start_idx"].values]
    end_sessions = sessions[endpoints["run_end_idx"].values]
    same_session = start_sessions == end_sessions
    return endpoints[same_session].copy()


def filter_horizon_crossing_session(
    bars: pd.DataFrame, feats: pd.DataFrame,
    cfg: StudyConfig,
) -> pd.DataFrame:
    if not cfg.drop_horizon_crossing_session or not cfg.session_col:
        return feats
    if cfg.session_col not in bars.columns:
        return feats
    bars = bars.reset_index(drop=True)
    sessions = bars[cfg.session_col].values
    n = len(bars)
    max_h = max(cfg.horizons)
    entry_idx = feats["entry_idx"].values
    window_end_idx = entry_idx + max_h - 1
    fits = window_end_idx < n
    safe_end = np.where(fits, window_end_idx, n - 1)
    entry_sessions = sessions[entry_idx]
    end_sessions = sessions[safe_end]
    same_session = (entry_sessions == end_sessions) & fits
    return feats[same_session].copy()


# ---------------- Run features ----------------

def compute_run_features(
    bars: pd.DataFrame, endpoints: pd.DataFrame,
    cfg: StudyConfig,
) -> pd.DataFrame:
    bars = bars.reset_index(drop=True)
    opens = bars["open"].values
    closes = bars["close"].values
    atr = bars["atr"].values

    feats = endpoints.copy()
    start_idx = feats["run_start_idx"].values
    end_idx = feats["run_end_idx"].values

    feats["run_magnitude_pts"] = closes[end_idx] - opens[start_idx]
    atr_lookup_idx = np.maximum(start_idx - 1, 0)
    feats["atr_at_run_start"] = atr[atr_lookup_idx]
    feats["run_magnitude_atr"] = (
        np.abs(feats["run_magnitude_pts"])
        / feats["atr_at_run_start"])

    entry_offset = 2 if cfg.causal_entry else 1
    feats["entry_idx"] = feats["run_end_idx"] + entry_offset

    feats = feats[
        feats["atr_at_run_start"].notna()
        & (feats["atr_at_run_start"] > 0)]
    feats = feats[feats["entry_idx"] < len(bars)]
    return feats


# ---------------- Forward returns (vectorized) ----------------

def compute_forward_returns(
    bars: pd.DataFrame, feats: pd.DataFrame,
    cfg: StudyConfig,
) -> pd.DataFrame:
    bars = bars.reset_index(drop=True)
    opens = bars["open"].values
    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values
    n = len(bars)

    out = feats.copy().reset_index(drop=True)
    entry_idx = out["entry_idx"].values
    run_dir = out["run_dir"].values
    atr0 = out["atr_at_run_start"].values
    mr_sign = -run_dir

    entry_price = opens[entry_idx]
    out["entry_price"] = entry_price

    valid_entry = entry_idx < n
    if not valid_entry.all():
        out = out[valid_entry].reset_index(drop=True)
        entry_idx = out["entry_idx"].values
        run_dir = out["run_dir"].values
        atr0 = out["atr_at_run_start"].values
        mr_sign = -run_dir
        entry_price = opens[entry_idx]

    for h in cfg.horizons:
        exit_idx = entry_idx + h - 1
        valid = exit_idx < n
        safe_exit = np.where(valid, exit_idx, n - 1)

        rolling_high = (pd.Series(highs)
            .rolling(window=h, min_periods=1).max().values)
        rolling_low = (pd.Series(lows)
            .rolling(window=h, min_periods=1).min().values)

        window_high = rolling_high[safe_exit]
        window_low = rolling_low[safe_exit]
        close_exit = closes[safe_exit]

        ret_pts = mr_sign * (close_exit - entry_price)

        long_mask = mr_sign > 0
        mfe_pts = np.where(long_mask,
                                window_high - entry_price,
                                entry_price - window_low)
        mae_pts = np.where(long_mask,
                                window_low - entry_price,
                                entry_price - window_high)

        ret_pts = np.where(valid, ret_pts, np.nan)
        mfe_pts = np.where(valid, mfe_pts, np.nan)
        mae_pts = np.where(valid, mae_pts, np.nan)

        out[f"ret_atr_h{h}"] = ret_pts / atr0
        out[f"mfe_atr_h{h}"] = mfe_pts / atr0
        out[f"mae_atr_h{h}"] = mae_pts / atr0
        out[f"hit_h{h}"] = np.where(valid,
                                            (ret_pts > 0).astype(float),
                                            np.nan)

    return out


# ---------------- Bucketing & aggregation ----------------

def bucket_run_length(run_len: pd.Series,
                          buckets: Iterable[int]) -> pd.Series:
    cap = max(buckets)
    return run_len.clip(upper=cap)


def bucket_magnitude(mag_atr: pd.Series,
                          edges: Iterable[float]) -> pd.Series:
    edges = list(edges)
    labels = [f"[{edges[i]:.1f},{edges[i+1]:.1f})"
              for i in range(len(edges) - 1)]
    return pd.cut(mag_atr, bins=edges, labels=labels,
                     include_lowest=True, right=False)


def aggregate_edge_map(results: pd.DataFrame, cfg: StudyConfig,
                            horizon: int) -> pd.DataFrame:
    rl_bucket = bucket_run_length(
        results["run_len"], cfg.run_length_buckets)
    mag_bucket = bucket_magnitude(
        results["run_magnitude_atr"],
        cfg.magnitude_buckets_atr)
    df = results.assign(rl_bucket=rl_bucket,
                              mag_bucket=mag_bucket)
    df = df.dropna(
        subset=[f"ret_atr_h{horizon}", "mag_bucket"])
    grouped = df.groupby(
        ["rl_bucket", "mag_bucket"], observed=True).agg(
            n=(f"ret_atr_h{horizon}", "size"),
            hit_rate=(f"hit_h{horizon}", "mean"),
            mean_ret_atr=(f"ret_atr_h{horizon}", "mean"),
            median_ret_atr=(f"ret_atr_h{horizon}", "median"),
            mean_mfe=(f"mfe_atr_h{horizon}", "mean"),
            mean_mae=(f"mae_atr_h{horizon}", "mean"),
        ).reset_index()
    grouped["reliable"] = grouped["n"] >= cfg.min_samples_for_display
    return grouped


def bootstrap_hit_rate_ci(hits: np.ndarray, n_boot: int = 1000,
                                  alpha: float = 0.05,
                                  seed: int = 42) -> tuple[float, float]:
    if len(hits) == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    boots = rng.choice(hits, size=(n_boot, len(hits)),
                            replace=True).mean(axis=1)
    return (np.quantile(boots, alpha / 2),
              np.quantile(boots, 1 - alpha / 2))


# ---------------- Pipeline ----------------

def run_study(bars: pd.DataFrame,
                  cfg: StudyConfig | None = None) -> dict:
    cfg = cfg or StudyConfig()
    bars = bars.copy()
    bars["atr"] = wilder_atr(bars, period=cfg.atr_period)
    bars = identify_runs(bars, cfg)
    endpoints = find_run_endpoints(bars, cfg)
    endpoints = filter_runs_spanning_sessions(bars, endpoints, cfg)
    feats = compute_run_features(bars, endpoints, cfg)
    feats = filter_horizon_crossing_session(bars, feats, cfg)

    if cfg.stratify_col and cfg.stratify_col in bars.columns:
        feats[cfg.stratify_col] = (
            bars.iloc[feats["run_end_idx"].values]
            [cfg.stratify_col].values)

    results = compute_forward_returns(bars, feats, cfg)
    edge_maps = {h: aggregate_edge_map(results, cfg, h)
                    for h in cfg.horizons}

    stratified_edge_maps = None
    stratified_baselines = None
    if cfg.stratify_col and cfg.stratify_col in results.columns:
        stratified_edge_maps = {}
        stratified_baselines = {}
        for stratum, group in results.groupby(
                cfg.stratify_col, observed=True):
            stratified_edge_maps[stratum] = {
                h: aggregate_edge_map(group, cfg, h)
                for h in cfg.horizons}
            stratified_baselines[stratum] = {
                h: group[f"hit_h{h}"].mean()
                for h in cfg.horizons}

    baselines = {h: results[f"hit_h{h}"].mean()
                    for h in cfg.horizons}

    return {
        "results": results,
        "edge_maps": edge_maps,
        "stratified_edge_maps": stratified_edge_maps,
        "baselines": baselines,
        "stratified_baselines": stratified_baselines,
        "config": cfg,
        "n_runs": len(results),
    }


def edge_map_to_pivot(edge_map: pd.DataFrame,
                           value_col: str) -> pd.DataFrame:
    return edge_map.pivot(index="rl_bucket",
                                columns="mag_bucket",
                                values=value_col)

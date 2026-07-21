"""
Phase 2-3: Build causal exit features and exit state labels.

All features are computed causally from data available at observation_time.
No future data is used.

Canonicalization: all directional price quantities are in ATR units,
positive = favorable for the direction of the trade.
"""

from pathlib import Path
import numpy as np
import pandas as pd

BASE_DIR = Path("studies/rl_regime_feasibility")
OUT_DIR  = BASE_DIR / "exit_optimal_stopping/results"

NQ_MULT    = 20.0
COMMISSION = 5.0
STOP_ATR   = 1.5


# ──────────────────────────────────────────────────────────────────────────────
# Feature computation
# ──────────────────────────────────────────────────────────────────────────────

def compute_pullback_features(grp: pd.DataFrame) -> pd.DataFrame:
    """
    Per-episode stateful pullback sequence tracker.
    Input grp must be sorted by seconds_since_entry.
    Returns grp with pullback feature columns added.
    """
    grp = grp.copy()
    n = len(grp)

    pnl = grp["unrealized_pnl_atr"].values
    times = grp["seconds_since_entry"].values

    # State variables
    pullback_count    = np.zeros(n, dtype=int)
    current_pb_depth  = np.zeros(n)
    current_pb_dur    = np.zeros(n)
    current_pb_recov  = np.zeros(n)

    last_pb_depth     = np.zeros(n)
    last_pb_dur       = np.zeros(n)
    last_pb_recov_s   = np.zeros(n)
    last_pb_new_prog  = np.zeros(n)

    prior_pb_depth    = np.zeros(n)
    prior_pb_recov_s  = np.zeros(n)
    prior_pb_new_prog = np.zeros(n)

    max_pb_depth      = np.zeros(n)
    pb_depth_trend    = np.zeros(n)  # recent - older pullback depth
    pb_recov_trend    = np.zeros(n)  # recent - older recovery time

    PULLBACK_THRESHOLD = 0.10  # ATR: min fall from peak to count as pullback

    # Running state
    peak_val = pnl[0] if len(pnl) > 0 else 0.0
    peak_time = times[0] if len(times) > 0 else 0.0
    in_pullback = False
    pullback_start_time = 0.0
    pullback_start_val = 0.0
    pb_history = []  # list of (depth, duration, recovery_s, new_progress)

    for i in range(n):
        t = times[i]
        v = pnl[i]

        # Did we make a new peak?
        if v > peak_val:
            if in_pullback:
                # Pullback recovered — log it
                pb_depth = peak_val - pullback_start_val  # depth before this PB
                pb_dur   = t - pullback_start_time
                pb_recov = t - pullback_start_time
                pb_new   = v - peak_val  # new progress after recovery
                pb_history.append((pb_depth, pb_dur, pb_recov, pb_new))
                in_pullback = False
            peak_val = v
            peak_time = t

        elif not in_pullback and (peak_val - v) >= PULLBACK_THRESHOLD:
            # Start of pullback
            in_pullback = True
            pullback_start_time = t
            pullback_start_val = v

        # Fill arrays
        n_pbs = len(pb_history)
        pullback_count[i] = n_pbs + (1 if in_pullback else 0)

        if in_pullback:
            current_pb_depth[i] = peak_val - v
            current_pb_dur[i]   = t - pullback_start_time
        else:
            current_pb_depth[i] = 0.0
            current_pb_dur[i]   = 0.0

        if n_pbs >= 1:
            last_pb_depth[i]    = pb_history[-1][0]
            last_pb_dur[i]      = pb_history[-1][1]
            last_pb_recov_s[i]  = pb_history[-1][2]
            last_pb_new_prog[i] = pb_history[-1][3]
        if n_pbs >= 2:
            prior_pb_depth[i]    = pb_history[-2][0]
            prior_pb_recov_s[i]  = pb_history[-2][2]
            prior_pb_new_prog[i] = pb_history[-2][3]

        if n_pbs > 0:
            depths = [h[0] for h in pb_history]
            max_pb_depth[i] = max(depths)
            if n_pbs >= 2:
                pb_depth_trend[i]  = depths[-1] - depths[-2]
                recov_times = [h[2] for h in pb_history]
                pb_recov_trend[i]  = recov_times[-1] - recov_times[-2]
        else:
            max_pb_depth[i] = 0.0

    grp["pullback_count"]         = pullback_count
    grp["current_pullback_depth"] = current_pb_depth
    grp["current_pullback_dur_s"] = current_pb_dur
    grp["last_pb_depth"]          = last_pb_depth
    grp["last_pb_dur_s"]          = last_pb_dur
    grp["last_pb_recov_s"]        = last_pb_recov_s
    grp["last_pb_new_prog"]       = last_pb_new_prog
    grp["prior_pb_depth"]         = prior_pb_depth
    grp["prior_pb_recov_s"]       = prior_pb_recov_s
    grp["prior_pb_new_prog"]      = prior_pb_new_prog
    grp["max_pullback_depth"]     = max_pb_depth
    grp["pb_depth_trend"]         = pb_depth_trend
    grp["pb_recov_trend"]         = pb_recov_trend

    return grp


def compute_seconds_since_trade_peak(grp: pd.DataFrame) -> pd.Series:
    """Running time since last maximum of unrealized_pnl_atr."""
    grp = grp.sort_values("seconds_since_entry")
    pnl = grp["unrealized_pnl_atr"].values
    times = grp["seconds_since_entry"].values
    peak_time = times[0]
    peak_val = pnl[0]
    result = np.zeros(len(grp))
    for i in range(len(pnl)):
        if pnl[i] >= peak_val:
            peak_val = pnl[i]
            peak_time = times[i]
        result[i] = times[i] - peak_time
    return pd.Series(result, index=grp.index)


def compute_entry_relative_features(checkpoints: pd.DataFrame,
                                     entry_pop: pd.DataFrame) -> pd.DataFrame:
    """
    Join entry-time snapshot features onto checkpoints, compute deltas.
    """
    # Get entry-time values of key features
    entry_snap_feats = [
        "episode_id", "kalman_velocity_atr_per_s", "progress_efficiency",
        "regime_age_1m_bars", "adx14_1m"
    ]
    entry_feats = (entry_pop[["episode_id", "step_index", "observation_time"]]
                   .merge(
                       checkpoints[checkpoints["seconds_since_entry"] < 5][
                           entry_snap_feats
                       ].groupby("episode_id").first().reset_index(),
                       on="episode_id", how="left"
                   ))
    entry_feats = entry_feats.rename(columns={
        "kalman_velocity_atr_per_s": "entry_kalman_vel",
        "progress_efficiency": "entry_path_eff",
        "regime_age_1m_bars": "entry_regime_age",
        "adx14_1m": "entry_adx14",
    })

    df = checkpoints.merge(
        entry_feats[["episode_id", "entry_kalman_vel", "entry_path_eff",
                     "entry_regime_age", "entry_adx14"]],
        on="episode_id", how="left"
    )

    # Entry-relative deltas
    df["delta_kalman_vel"]   = df["kalman_velocity_atr_per_s"] - df.get("entry_kalman_vel", 0.0)
    df["delta_path_eff"]     = df["progress_efficiency"] - df.get("entry_path_eff", 0.0)
    df["delta_adx14"]        = df["adx14_1m"] - df.get("entry_adx14", 0.0)
    df["regime_age_change"]  = df["regime_age_1m_bars"] - df.get("entry_regime_age", 0.0)

    return df


def compute_all_exit_features(checkpoints: pd.DataFrame,
                               entry_pop: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the full set of causal exit features.
    All quantities available at observation_time only.
    """
    print("  Computing pullback sequence features (per-episode) ...")
    df = checkpoints.sort_values(["episode_id", "seconds_since_entry"])

    # Per-episode pullback features
    df = df.groupby("episode_id", group_keys=False).apply(compute_pullback_features)

    # Seconds since trade peak
    print("  Computing seconds since trade peak ...")
    df["secs_since_trade_peak"] = df.groupby("episode_id", group_keys=False).apply(
        lambda g: compute_seconds_since_trade_peak(g)
    ).reset_index(level=0, drop=True)

    # Fraction of time near trade MFE (approx: using giveback thresholds)
    df["near_mfe_flag"] = (df["giveback_from_mfe_atr"] < 0.15).astype(float)
    df["pct_time_near_mfe_60s"] = (df.sort_values(["episode_id", "seconds_since_entry"])
                                     .groupby("episode_id")["near_mfe_flag"]
                                     .transform(lambda x: x.rolling(12, min_periods=1).mean()))

    # Slope features from existing aligned returns
    # aligned_return_5s/15s/30s/60s are already in ATR units, direction-aligned
    # slope_decay = short-window return - longer-window return
    df["slope_decay_5s_vs_60s"] = df.get("aligned_return_5s_atr", 0) - df.get("aligned_return_60s_atr", 0)
    df["slope_decay_15s_vs_60s"] = df.get("aligned_return_15s_atr", 0) - df.get("aligned_return_60s_atr", 0)

    # Kalman deterioration
    df["kalman_vel_vs_entry"] = df["kalman_velocity_atr_per_s"] - df.groupby("episode_id")["kalman_velocity_atr_per_s"].transform("first")
    df["kalman_acc_adverse"]  = (-df["kalman_acceleration_atr_per_s2"]).clip(lower=0.0)

    # Volatility ratios
    if "realized_vol_60s_atr" in df.columns:
        df["vol_60s"] = df["realized_vol_60s_atr"]

    # Range to progress
    df["range_to_progress_ratio"] = np.where(
        df["unrealized_pnl_atr"].abs() > 0.05,
        df.get("range_5s_atr", 0.0) / df["unrealized_pnl_atr"].abs().clip(lower=0.05),
        0.0
    )

    # Trade phase features
    df["phase_early"]  = (df["unrealized_pnl_atr"] < 0.25).astype(float)
    df["phase_mid"]    = ((df["unrealized_pnl_atr"] >= 0.25) & (df["unrealized_pnl_atr"] < 1.0)).astype(float)
    df["phase_profit"] = (df["unrealized_pnl_atr"] >= 1.0).astype(float)

    # Entry-relative features
    print("  Computing entry-relative features ...")
    df = compute_entry_relative_features(df, entry_pop)

    return df


def compute_exit_state_labels(checkpoints: pd.DataFrame) -> pd.DataFrame:
    """
    Phase 3: Assign retrospective exit state labels.
    These use future data — training/diagnostic only, never for exit decisions.

    States:
      EARLY_FAILURE       : trade never progresses; MFE < 0.25 ATR, MAE < -0.5 ATR before end
      HEALTHY_PULLBACK    : giveback > 0.2 ATR AND new favorable extreme within 120s
      HEALTHY_CONTINUATION: remaining_mfe > 0.25 ATR, low giveback (< 0.3 ATR)
      STALL               : remaining_mfe < 0.1 ATR for > 60s, no major adverse break yet
      TERMINAL_DECAY      : current_mfe_is_final=1 AND max_future_giveback > 0.3 ATR
      AMBIGUOUS           : doesn't fit above clearly
    """
    df = checkpoints.copy()
    df["exit_state"] = "AMBIGUOUS"

    early_fail = (
        (df["trade_mfe_atr"] < 0.25) &
        (df["trade_mae_atr"] < -0.5)
    )
    healthy_pb = (
        (df["giveback_from_mfe_atr"] > 0.20) &
        (df["remaining_mfe_atr"] > 0.15)
    )
    healthy_cont = (
        (df["unrealized_pnl_atr"] > 0.25) &
        (df["giveback_from_mfe_atr"] < 0.25) &
        (df["remaining_mfe_atr"] > 0.25)
    )
    stall = (
        (df["secs_since_trade_peak"] > 60) &
        (df["remaining_mfe_atr"] < 0.15) &
        (df["max_future_giveback_atr"] < 0.40)
    )
    terminal = (
        (df["current_mfe_is_final"] == 1) &
        (df["max_future_giveback_atr"] > 0.25)
    )

    df.loc[early_fail, "exit_state"]      = "EARLY_FAILURE"
    df.loc[healthy_cont, "exit_state"]    = "HEALTHY_CONTINUATION"
    df.loc[healthy_pb, "exit_state"]      = "HEALTHY_PULLBACK"
    df.loc[stall, "exit_state"]           = "STALL"
    df.loc[terminal, "exit_state"]        = "TERMINAL_DECAY"

    return df


def main():
    print("=" * 70)
    print("Phase 2-3: Build Causal Exit Features and State Labels")
    print("=" * 70)

    print("\nLoading checkpoints ...")
    checkpoints = pd.read_parquet(OUT_DIR / "exit_atlas_checkpoints.parquet")
    entry_trades = pd.read_parquet(OUT_DIR / "entry_population_trades.parquet")
    entry_p2 = entry_trades[entry_trades["population"] == "P2"].copy()
    print(f"  Checkpoints: {checkpoints.shape}")

    print("\nComputing exit features ...")
    feat_df = compute_all_exit_features(checkpoints, entry_p2)
    print(f"  Features computed: {feat_df.shape}")

    print("\nComputing exit state labels ...")
    feat_df = compute_exit_state_labels(feat_df)
    state_counts = feat_df["exit_state"].value_counts()
    print(f"  State distribution:\n{state_counts.to_string()}")

    # Define the feature contract
    exit_feats = [
        # Trade progress
        "seconds_since_entry", "seconds_since_flip",
        "unrealized_pnl_atr", "trade_mfe_atr", "trade_mae_atr",
        "giveback_from_mfe_atr", "giveback_fraction",
        "secs_since_trade_peak",
        # Pullback sequence
        "pullback_count", "current_pullback_depth", "current_pullback_dur_s",
        "last_pb_depth", "last_pb_dur_s", "last_pb_recov_s", "last_pb_new_prog",
        "prior_pb_depth", "prior_pb_recov_s", "prior_pb_new_prog",
        "max_pullback_depth", "pb_depth_trend", "pb_recov_trend",
        "pct_time_near_mfe_60s",
        # Path quality (from existing features)
        "progress_efficiency", "aligned_return_5s_atr",
        "aligned_return_15s_atr", "aligned_return_30s_atr", "aligned_return_60s_atr",
        # Slope decay
        "slope_decay_5s_vs_60s", "slope_decay_15s_vs_60s",
        # Kalman
        "kalman_velocity_atr_per_s", "kalman_acceleration_atr_per_s2",
        "kalman_innovation_zscore", "kalman_vel_vs_entry", "kalman_acc_adverse",
        # Volatility
        "realized_vol_60s_atr", "range_5s_atr",
        "range_to_progress_ratio",
        # Regime/market context
        "regime_5s_aligned", "regime_30s_aligned", "regime_5m_aligned",
        "regime_age_1m_bars", "adx14_1m",
        "ema3_ema9_spread_30s_atr", "position_in_trailing_1m_range",
        "minutes_since_rth_open", "bollinger_width_percentile_1m",
        # Volume
        "volume_5s_zscore", "volume_30s_vs_5m",
        # Entry-relative
        "entry_delay_s", "entry_regime_age", "entry_adx14",
        "delta_kalman_vel", "delta_path_eff", "delta_adx14",
        "phase_early", "phase_mid", "phase_profit",
    ]
    # Keep only columns that exist
    exit_feats = [f for f in exit_feats if f in feat_df.columns]

    import json
    contract = {
        "features": exit_feats,
        "n_features": len(exit_feats),
        "no_forward_info": True,
        "note": "All features computable at observation_time from causally available data only.",
    }
    with open(OUT_DIR / "exit_feature_contract.json", "w") as f:
        json.dump(contract, f, indent=2)

    # Save exit features + state labels
    id_cols = ["episode_id", "observation_time", "period", "seconds_since_entry",
               "population", "exit_state",
               "unrealized_pnl_raw", "exit_now_pnl",
               # Retrospective targets (for model training only)
               "remaining_mfe_atr", "max_future_giveback_atr",
               "current_mfe_is_final", "best_future_exit_pnl",
               "prob_remaining_gain_ge_025atr", "prob_remaining_gain_ge_050atr",
               "giveback_exceeds_025atr", "giveback_exceeds_050atr", "giveback_exceeds_100atr",
               # Forward labels (for target computation and replay)
               "base__pnl_300s", "base__pnl_regime", "total_pnl_hold_300s", "total_pnl_hold_regime",
               "trade_mfe_atr", "trade_mae_atr", "giveback_from_mfe_atr", "giveback_fraction",
               "unrealized_pnl_atr", "atr_at_flip",
               ]
    id_cols = [c for c in id_cols if c in feat_df.columns]
    save_df = feat_df[list(dict.fromkeys(id_cols + exit_feats))].copy()
    save_df.to_parquet(OUT_DIR / "exit_features.parquet", index=False)
    print(f"\nSaved exit_features.parquet: {save_df.shape}")

    # Save state labels separately
    state_df = feat_df[["episode_id", "observation_time", "exit_state", "period"]].copy()
    state_df.to_parquet(OUT_DIR / "exit_state_labels.parquet", index=False)
    print(f"Saved exit_state_labels.parquet: {state_df.shape}")

    print(f"\nFeature contract: {len(exit_feats)} features")
    print("Phase 2-3 complete.")


if __name__ == "__main__":
    main()

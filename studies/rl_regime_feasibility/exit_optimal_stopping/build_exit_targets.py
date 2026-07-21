"""
Phase 4: Build exit targets.

Target families:
  T1: Remaining opportunity (remaining_mfe regression + threshold probs)
  T2: Expected giveback (max_future_giveback regression + threshold probs)
  T3: Terminal hazard (discrete-time classification)
  T4: Hold-vs-exit advantage via backward induction (fitted-Q)
  T5: Acceptable-exit window membership

All targets are RETROSPECTIVE — use future data.
They must ONLY be used for model training/diagnostics.
Never read inside the replay loop.
"""

from pathlib import Path
import numpy as np
import pandas as pd

BASE_DIR = Path("studies/rl_regime_feasibility")
OUT_DIR  = BASE_DIR / "exit_optimal_stopping/results"

NQ_MULT    = 20.0
COMMISSION = 5.0
DISCOUNT   = 0.99   # slight time discount for Q backward induction (per 5s step)


def compute_fitted_q_targets(df: pd.DataFrame) -> pd.DataFrame:
    """
    Backward induction of Q_exit, Q_hold, hold_advantage per checkpoint.

    Q_exit(t)  = exit_now_pnl = unrealized_pnl_raw - commission
    Q_hold(t)  = V(t+1) = max value achievable from t+1 onward
    V(t)       = max(Q_exit(t), Q_hold(t))
    hold_adv(t) = Q_hold(t) - Q_exit(t)

    The policy: exit when hold_adv <= threshold.

    Uses only the 5-second checkpoint price path (no 1s stop monitoring here;
    approximation: stop monitoring handled via forward labels in replay).
    """
    print("  Computing fitted-Q via backward induction ...")
    df = df.sort_values(["episode_id", "seconds_since_entry"])

    # Initialize arrays
    q_exit    = df["exit_now_pnl"].values.copy()
    hold_adv  = np.zeros(len(df))
    q_hold    = np.zeros(len(df))
    v_star    = q_exit.copy()

    # We need episode boundaries
    ep_ids     = df["episode_id"].values
    ep_change  = np.concatenate([[True], ep_ids[1:] != ep_ids[:-1]])
    ep_end     = np.concatenate([ep_change[1:], [True]])

    # Backward pass
    for i in range(len(df) - 1, -1, -1):
        if ep_end[i]:
            # Terminal: must exit
            v_star[i]   = q_exit[i]
            q_hold[i]   = q_exit[i]
            hold_adv[i] = 0.0
        else:
            # Q_hold = V(next step) discounted
            v_next        = v_star[i + 1]
            q_hold[i]     = DISCOUNT * v_next
            v_star[i]     = max(q_exit[i], q_hold[i])
            hold_adv[i]   = q_hold[i] - q_exit[i]

    df = df.copy()
    df["q_exit"]        = q_exit
    df["q_hold"]        = q_hold
    df["v_star"]        = v_star
    df["hold_advantage"] = hold_adv   # >0 means hold is better; <=0 means exit now

    return df


def compute_hazard_targets(df: pd.DataFrame) -> pd.DataFrame:
    """
    Target family 3: terminal hazard flags at various horizons.
    A checkpoint is 'terminal' if remaining_mfe_atr < threshold AND max_future_giveback > threshold.
    """
    df = df.copy()

    # Terminal decay in next 30s / 60s / 120s
    # Proxy: remaining_mfe < 0.1 ATR in that window
    # We don't have horizon-specific remaining_mfe, so use current remaining_mfe
    # as proxy (if remaining_mfe is tiny, trade is near its terminal state)
    df["hazard_terminal_30s"]  = (
        (df["remaining_mfe_atr"] < 0.10) &
        (df["max_future_giveback_atr"] > 0.20)
    ).astype(int)
    df["hazard_terminal_60s"]  = (
        (df["remaining_mfe_atr"] < 0.15) &
        (df["max_future_giveback_atr"] > 0.25)
    ).astype(int)
    df["hazard_terminal_120s"] = (
        (df["remaining_mfe_atr"] < 0.20) &
        (df["max_future_giveback_atr"] > 0.30)
    ).astype(int)

    # No new extreme in next 60s: remaining_mfe < 0.1 ATR
    df["no_new_extreme_60s"] = (df["remaining_mfe_atr"] < 0.10).astype(int)

    # Current MFE is final (from atlas)
    if "current_mfe_is_final" not in df.columns:
        df["current_mfe_is_final"] = 0

    return df


def compute_exit_window_targets(df: pd.DataFrame,
                                  window_df: pd.DataFrame) -> pd.DataFrame:
    """
    Target family 5: acceptable exit window membership.
    """
    # Join window info
    df = df.merge(
        window_df[["episode_id", "exit_window_010atr_first_s", "exit_window_010atr_last_s",
                   "exit_window_025atr_first_s", "exit_window_025atr_last_s"]],
        on="episode_id", how="left"
    )

    # Is current checkpoint inside 0.10 ATR optimal window?
    df["inside_010atr_window"] = (
        (df["seconds_since_entry"] >= df["exit_window_010atr_first_s"]) &
        (df["seconds_since_entry"] <= df["exit_window_010atr_last_s"])
    ).astype(int)
    df["inside_025atr_window"] = (
        (df["seconds_since_entry"] >= df["exit_window_025atr_first_s"]) &
        (df["seconds_since_entry"] <= df["exit_window_025atr_last_s"])
    ).astype(int)

    return df


def main():
    print("=" * 70)
    print("Phase 4: Build Exit Targets")
    print("=" * 70)

    print("\nLoading exit features ...")
    df = pd.read_parquet(OUT_DIR / "exit_features.parquet")
    window_df = pd.read_parquet(OUT_DIR / "exit_window_analysis.parquet")
    print(f"  exit_features: {df.shape}")

    # T4: Fitted-Q (backward induction)
    print("\nBuilding fitted-Q targets ...")
    df = compute_fitted_q_targets(df)

    # T3: Hazard targets
    print("Building hazard targets ...")
    df = compute_hazard_targets(df)

    # T5: Exit window targets
    print("Building exit window targets ...")
    df = compute_exit_window_targets(df, window_df)

    # Report target distributions
    print("\nTarget distributions:")
    target_cols = [
        "remaining_mfe_atr", "max_future_giveback_atr", "hold_advantage",
        "hazard_terminal_30s", "hazard_terminal_60s", "hazard_terminal_120s",
        "no_new_extreme_60s", "inside_010atr_window", "inside_025atr_window",
    ]
    for col in target_cols:
        if col not in df.columns:
            continue
        if df[col].dtype in [np.float32, np.float64]:
            print(f"  {col}: mean={df[col].mean():.3f}, std={df[col].std():.3f}, "
                  f"p25={df[col].quantile(.25):.3f}, p75={df[col].quantile(.75):.3f}")
        else:
            print(f"  {col}: mean={df[col].mean():.3f} (binary)")

    # Report hold_advantage distribution
    ha = df["hold_advantage"]
    print(f"\nHold advantage summary:")
    print(f"  Mean: ${ha.mean():.2f}")
    print(f"  % > 0 (hold better):  {(ha > 0).mean()*100:.1f}%")
    print(f"  % > 5 (strong hold):  {(ha > 5).mean()*100:.1f}%")
    print(f"  % < 0 (exit better):  {(ha < 0).mean()*100:.1f}%")
    print(f"  % < -5 (strong exit): {(ha < -5).mean()*100:.1f}%")

    # Save
    df.to_parquet(OUT_DIR / "exit_targets.parquet", index=False)
    print(f"\nSaved exit_targets.parquet: {df.shape}")
    print("Phase 4 complete.")


if __name__ == "__main__":
    main()

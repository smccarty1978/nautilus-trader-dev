"""
Phase 7-9: Exit policy simulation (fully vectorised — no per-episode Python loops).

For each policy the first-signal checkpoint per episode is found via:
  1. Filter rows where signal == True
  2. Sort by seconds_since_entry, take first per episode
  3. For episodes with no signal, fall back to regime exit or last checkpoint.

This runs in O(N) for all episodes simultaneously.
"""

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

from pathlib import Path
import json
import numpy as np
import pandas as pd
import joblib

BASE_DIR   = Path("studies/rl_regime_feasibility")
OUT_DIR    = BASE_DIR / "exit_optimal_stopping/results"
MODEL_DIR  = OUT_DIR / "models"

NQ_MULT    = 20.0
COMMISSION = 5.0
STOP_ATR   = 1.5

COST_SCENARIOS = [
    ("base",     0.0),
    ("plus_1t",  12.5),
    ("plus_2t",  25.0),
]


# ── Execution audit ───────────────────────────────────────────────────────────

def run_execution_audit(df: pd.DataFrame) -> pd.DataFrame:
    neg   = int((df["seconds_since_entry"] < 0).sum())
    dupes = int(df.duplicated(["episode_id", "observation_time"]).sum())
    stop_viol = int((df["unrealized_pnl_atr"] < -(STOP_ATR + 0.1)).sum())

    violations = []
    if neg > 0:
        violations.append(f"VIOLATION: {neg} negative seconds_since_entry")
    if dupes > 0:
        violations.append(f"VIOLATION: {dupes} duplicate obs pairs")
    if violations:
        raise AssertionError(str(violations))

    print(f"  Execution audit PASSED (minor stop violations: {stop_viol})")
    return pd.DataFrame([
        {"check": "neg_entry_seconds",  "violations": neg,       "pass": True},
        {"check": "dup_obs",            "violations": dupes,     "pass": True},
        {"check": "past_stop_level",    "violations": stop_viol, "pass": stop_viol < len(df) * 0.01},
    ])


# ── Vectorised episode building ───────────────────────────────────────────────

def build_episode_base(df: pd.DataFrame) -> pd.DataFrame:
    """Build per-episode metadata (period, fallback PnL values)."""
    first = df.sort_values("seconds_since_entry").groupby("episode_id").first()
    last  = df.sort_values("seconds_since_entry").groupby("episode_id").last()

    if "total_pnl_hold_regime" in first.columns:
        regime_pnl = first["total_pnl_hold_regime"].fillna(last["exit_now_pnl"])
    else:
        regime_pnl = last["exit_now_pnl"]

    ep = pd.DataFrame({
        "period": first["period"],
        "regime_pnl":    regime_pnl,
        "last_exit_pnl": last["exit_now_pnl"],
    })
    return ep


def first_signal_per_episode(df: pd.DataFrame, sig_col: str) -> pd.DataFrame:
    """
    Find the first checkpoint per episode where signal == True.
    Returns DataFrame indexed by episode_id with 'sig_pnl' column.
    """
    triggered = df[df[sig_col] == True].copy()
    if len(triggered) == 0:
        return pd.DataFrame(columns=["sig_pnl"])
    return (triggered
            .sort_values("seconds_since_entry")
            .groupby("episode_id")[["exit_now_pnl"]]
            .first()
            .rename(columns={"exit_now_pnl": "sig_pnl"}))


def fixed_time_exit_per_episode(df: pd.DataFrame, hold_s: float) -> pd.DataFrame:
    """First checkpoint at or after hold_s, else last checkpoint."""
    past_hold = df[df["seconds_since_entry"] >= hold_s].copy()
    if len(past_hold) == 0:
        last = df.sort_values("seconds_since_entry").groupby("episode_id")[["exit_now_pnl"]].last()
        return last.rename(columns={"exit_now_pnl": "sig_pnl"})
    first_past = (past_hold
                  .sort_values("seconds_since_entry")
                  .groupby("episode_id")[["exit_now_pnl"]]
                  .first()
                  .rename(columns={"exit_now_pnl": "sig_pnl"}))
    # For episodes not in first_past, use last checkpoint
    last = (df.sort_values("seconds_since_entry")
              .groupby("episode_id")[["exit_now_pnl"]]
              .last()
              .rename(columns={"exit_now_pnl": "sig_pnl"}))
    result = last.copy()
    result.loc[first_past.index, "sig_pnl"] = first_past["sig_pnl"]
    return result


def simulate_policy(ep: pd.DataFrame, sig_exits: pd.DataFrame,
                     cost_adj: float = 0.0) -> pd.DataFrame:
    """
    Combine per-episode signal exits with fallback regime exit.
    sig_exits: indexed by episode_id, column 'sig_pnl'
    Returns per-episode result DataFrame.
    """
    result = ep.copy()
    # Default: regime exit
    result["pnl"] = result["regime_pnl"] - cost_adj

    # Override with signal exit where available
    common = result.index.intersection(sig_exits.index)
    result.loc[common, "pnl"] = sig_exits.loc[common, "sig_pnl"] - cost_adj

    return result[["period", "pnl"]].reset_index()


def compute_metrics(results: pd.DataFrame, policy: str, cost: str) -> pd.DataFrame:
    rows = []
    for period, grp in results.groupby("period"):
        pnls = grp["pnl"].values
        pos = pnls[pnls > 0]
        neg_v = pnls[pnls < 0]
        rows.append({
            "policy": policy, "period": period, "cost_scenario": cost,
            "n_trades": len(pnls),
            "total_pnl": float(pnls.sum()),
            "ev_per_trade": float(pnls.mean()),
            "win_rate": float((pnls > 0).mean()),
            "profit_factor": float(pos.sum() / max(-neg_v.sum(), 1e-9)),
            "median_pnl": float(np.median(pnls)),
            "mean_winner": float(pos.mean()) if len(pos) else 0.0,
            "mean_loser":  float(neg_v.mean()) if len(neg_v) else 0.0,
        })
    return pd.DataFrame(rows)


def main():
    print("=" * 70)
    print("Phase 7-9: Run Replay Policies (fully vectorised)")
    print("=" * 70)

    print("\nLoading data ...")
    df = pd.read_parquet(OUT_DIR / "exit_targets.parquet")
    with open(OUT_DIR / "exit_feature_contract.json") as f:
        feats = [f for f in json.load(f)["features"] if f in df.columns]
    with open(OUT_DIR / "policy_thresholds.json") as f:
        thresholds = json.load(f)
    print(f"  Checkpoints: {df.shape}")

    # Execution audit
    print("\nRunning execution audit ...")
    audit_df = run_execution_audit(df)
    audit_df.to_parquet(OUT_DIR / "execution_audit.parquet", index=False)

    # Load models + vectorised pre-score
    print("\nPre-scoring all checkpoints ...")
    m1 = joblib.load(MODEL_DIR / "m1_remaining_opp.pkl")["model"]
    m3 = joblib.load(MODEL_DIR / "m3_hazard.pkl")["model"]
    m4 = joblib.load(MODEL_DIR / "m4_fitted_q.pkl")["model"]
    X = df[feats].fillna(0).values
    df["score_m1"] = m1.predict(X)
    df["score_m3"] = m3.predict_proba(X)[:, 1]
    df["score_m4"] = m4.predict(X)
    print("  Scoring done.")

    thr_m1 = thresholds["m1_remaining_opp"]
    thr_m3 = thresholds["m3_hazard"]
    thr_m4 = thresholds["m4_fitted_q"]

    min_s  = 30.0
    elig   = df["seconds_since_entry"] >= min_s
    mfe    = df["trade_mfe_atr"].values

    # Build signal columns (vectorised)
    df["sig_E3"] = elig & (df["score_m1"] < thr_m1)
    df["sig_E4"] = elig & (df["score_m3"] > thr_m3)
    df["sig_E5"] = elig & (df["score_m4"] < thr_m4)

    # E5 hysteresis=2 (vectorised via shifted signal within episode)
    df = df.sort_values(["episode_id", "seconds_since_entry"]).copy()
    shifted = df.groupby("episode_id")["sig_E5"].shift(1, fill_value=False)
    df["sig_E5h"] = df["sig_E5"] & shifted

    # E7 multi-stage
    df["sig_E7"] = (
        elig &
        (
            ((mfe >= 0.5) & (mfe < 1.5) & (df["score_m3"] > thr_m3 * 1.2) & (df["score_m4"] < -10.0)) |
            ((mfe >= 1.5) & (df["score_m1"] < thr_m1) & (df["score_m3"] > thr_m3)) |
            ((mfe >= 1.5) & (df["score_m4"] < -5.0))
        )
    )

    print("\nBuilding episode-level data ...")
    ep_base = build_episode_base(df)

    # Fixed exits (independent of cost)
    fix_300  = fixed_time_exit_per_episode(df, 300)
    fix_120  = fixed_time_exit_per_episode(df, 120)

    # Signal exits
    sig_exits = {
        "E3_remaining_opp":   first_signal_per_episode(df, "sig_E3"),
        "E4_hazard":          first_signal_per_episode(df, "sig_E4"),
        "E5_fitted_q":        first_signal_per_episode(df, "sig_E5"),
        "E5_fitted_q_h2":     first_signal_per_episode(df, "sig_E5h"),
        "E7_multistage":      first_signal_per_episode(df, "sig_E7"),
    }

    for name, sig_df in sig_exits.items():
        fired_pct = len(sig_df) / ep_base.index.nunique() * 100
        print(f"  {name}: signal fired in {fired_pct:.1f}% of episodes")

    # Run all policies × all costs
    all_metrics = []
    all_results_rows = []

    for cost_label, cost_adj in COST_SCENARIOS:
        print(f"\n  Cost: {cost_label}")

        # E0: regime exit
        e0 = ep_base.copy().reset_index()
        e0["pnl"]    = e0["regime_pnl"] - cost_adj
        e0["policy"] = "E0_regime"
        e0["cost_scenario"] = cost_label
        all_results_rows.append(e0[["episode_id","period","policy","pnl","cost_scenario"]])
        all_metrics.append(compute_metrics(e0, "E0_regime", cost_label))

        # E1: fixed 300s
        e1 = simulate_policy(ep_base, fix_300, cost_adj)
        e1["policy"] = "E1_fixed_300s"; e1["cost_scenario"] = cost_label
        all_results_rows.append(e1[["episode_id","period","policy","pnl","cost_scenario"]])
        all_metrics.append(compute_metrics(e1, "E1_fixed_300s", cost_label))

        # E2: fixed 120s
        e2 = simulate_policy(ep_base, fix_120, cost_adj)
        e2["policy"] = "E2_fixed_120s"; e2["cost_scenario"] = cost_label
        all_results_rows.append(e2[["episode_id","period","policy","pnl","cost_scenario"]])
        all_metrics.append(compute_metrics(e2, "E2_fixed_120s", cost_label))

        # Model-based exits
        for pname, sig_df in sig_exits.items():
            ex = simulate_policy(ep_base, sig_df, cost_adj)
            ex["policy"] = pname; ex["cost_scenario"] = cost_label
            all_results_rows.append(ex[["episode_id","period","policy","pnl","cost_scenario"]])
            all_metrics.append(compute_metrics(ex, pname, cost_label))

    results_df = pd.concat(all_results_rows, ignore_index=True)
    results_df.to_parquet(OUT_DIR / "exit_policy_episode_results.parquet", index=False)

    metrics = pd.concat(all_metrics, ignore_index=True)
    metrics.to_parquet(OUT_DIR / "exit_policy_metrics.parquet", index=False)

    # Attribution table
    base_m = metrics[metrics["cost_scenario"] == "base"].copy()
    base_ev = {}
    for period, grp in base_m[base_m["policy"] == "E0_regime"].groupby("period"):
        base_ev[period] = float(grp["ev_per_trade"].iloc[0])

    attr_rows = []
    for _, row in base_m.iterrows():
        attr_rows.append({
            "policy": row["policy"], "period": row["period"],
            "ev_per_trade": row["ev_per_trade"],
            "exit_vs_E0": row["ev_per_trade"] - base_ev.get(row["period"], 0),
            "win_rate": row["win_rate"],
            "profit_factor": row["profit_factor"],
            "n_trades": row["n_trades"],
        })
    attr_df = pd.DataFrame(attr_rows)
    attr_df.to_parquet(OUT_DIR / "entry_exit_attribution.parquet", index=False)

    # Print results
    print("\n" + "=" * 70)
    print("POLICY RESULTS (base cost)")
    print("=" * 70)
    for period in ["val", "test"]:
        print(f"\nPeriod: {period}")
        sub = base_m[base_m["period"] == period].sort_values("ev_per_trade", ascending=False)
        print(f"  {'Policy':<30} {'EV/trade':>10} {'WR':>7} {'PF':>7} {'N':>7}")
        print(f"  {'-'*30} {'-'*10} {'-'*7} {'-'*7} {'-'*7}")
        for _, row in sub.iterrows():
            print(f"  {row['policy']:<30} {row['ev_per_trade']:>10.2f} "
                  f"{row['win_rate']:>7.3f} {row['profit_factor']:>7.3f} {row['n_trades']:>7}")

    print("\n" + "=" * 70)
    print("ATTRIBUTION vs E0 (base cost)")
    print("=" * 70)
    for period in ["val", "test"]:
        print(f"\nPeriod: {period}")
        sub = attr_df[attr_df["period"] == period].sort_values("exit_vs_E0", ascending=False)
        for _, row in sub.iterrows():
            flag = " <<< BEST" if row["exit_vs_E0"] == sub["exit_vs_E0"].max() else ""
            print(f"  {row['policy']:<30} EV={row['ev_per_trade']:>8.2f} vs_E0={row['exit_vs_E0']:>+8.2f}{flag}")

    print("\n" + "=" * 70)
    print("COST STRESS — E5 fitted-Q")
    print("=" * 70)
    for period in ["val", "test"]:
        vals = []
        for cost in ["base", "plus_1t", "plus_2t"]:
            sub = metrics[(metrics["policy"] == "E5_fitted_q") &
                          (metrics["period"] == period) &
                          (metrics["cost_scenario"] == cost)]
            vals.append(f"${sub['ev_per_trade'].iloc[0]:.2f}" if len(sub) else "N/A")
        print(f"  {period}: " + "  |  ".join(vals))

    print("\nPhase 7-9 complete.")


if __name__ == "__main__":
    main()

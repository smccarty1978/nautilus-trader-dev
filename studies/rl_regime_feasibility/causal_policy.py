"""Gate 2: Best frozen causal policy vs clairvoyant oracle.

Evaluates whether the best offline-selected causal policy can capture
a meaningful fraction of the oracle PnL on the historical test set
(2025-03-01 to 2025-05-31).

Policy types:
  baseline_hold    : always hold to episode end (regime flip / 30min timeout)
  baseline_stop    : only catastrophic stop; no ML timing
  ml_{model}_{h}s  : enter at obs_0, exit when model probability drops
                     below threshold (based on val-calibrated threshold)
  fixed_{h}s       : exit at fixed horizon H regardless of model

For each policy, we compute PnL per episode on the test set using
the forward labels from labels.py (base cost scenario).

Gate 2 pass:
  Best policy PnL/episode > 0.5 * oracle PnL/episode on test set.

Outputs:
  results/gate2_policy_results.parquet
  results/gate2_report.txt
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import numpy as np
import pandas as pd

OUT_DIR    = Path("studies/rl_regime_feasibility/results")
SNAP_FILE  = OUT_DIR / "feature_snapshots.parquet"
LBL_FILE   = OUT_DIR / "forward_labels.parquet"
ORC_FILE   = OUT_DIR / "oracle_summary.parquet"
PRED_FILE  = OUT_DIR / "gate1_predictions.parquet"

HORIZONS_S = [5, 15, 30, 60, 120, 300]
_COMM      = 5.0    # base $5 RT


def _load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    snaps = pd.read_parquet(SNAP_FILE)
    lbls  = pd.read_parquet(LBL_FILE)
    df    = snaps.merge(lbls, on="observation_time", how="inner")
    oracle = pd.read_parquet(ORC_FILE)
    return df, oracle, df[df["period"] == "test"].copy()


def _baseline_hold(test: pd.DataFrame) -> float:
    """Exit at episode end: use pnl_regime from label."""
    ep_pnls = (
        test.groupby("episode_id", sort=False)
        .first()["base__pnl_regime"]
        .dropna()
    )
    return float(ep_pnls.mean())


def _baseline_fixed(test: pd.DataFrame, h_s: int) -> float:
    """Exit at fixed horizon H regardless of anything."""
    col = f"base__pnl_{h_s}s"
    if col not in test.columns:
        return float("nan")
    ep_pnls = (
        test.groupby("episode_id", sort=False)
        .first()[col]
        .dropna()
    )
    return float(ep_pnls.mean())


def _ml_policy(test: pd.DataFrame, pred_df: pd.DataFrame,
               prob_col: str, threshold: float, h_s: int) -> float:
    """Exit at first observation where model prob < threshold.
    If never drops below threshold: exit at horizon H.
    Entry occurs only if the initial probability at step 0 exceeds threshold.
    If not, the policy remains flat and PnL is 0.0.
    """
    if pred_df is None or prob_col not in pred_df.columns:
        return float("nan")

    merged = test.merge(
        pred_df[["observation_time", prob_col]],
        on="observation_time", how="left",
    )

    # For each episode: check entry and exit
    results = []
    for ep_id, ep_df in merged.groupby("episode_id", sort=False):
        ep_df = ep_df.sort_values("step_index")
        probs = ep_df[prob_col].values

        if len(probs) == 0 or math.isnan(probs[0]):
            continue

        # Correct Entry Condition: Only enter if initial score exceeds threshold
        if probs[0] < threshold:
            results.append(0.0)
            continue

        # Find first step below threshold (Exit A)
        exit_step = None
        for i, p in enumerate(probs):
            if math.isnan(p):
                continue
            if p < threshold:
                exit_step = i
                break

        if exit_step is None:
            # Never dropped: use fixed horizon
            exit_h = h_s
        else:
            # Exit at this step — approximate by mapping to nearest horizon
            exit_s = float(ep_df.iloc[exit_step]["seconds_since_flip"])
            exit_h = min(HORIZONS_S, key=lambda h: abs(h - exit_s))

        # PnL from first observation using that horizon
        first_row = ep_df.iloc[0]
        pnl_col   = f"base__pnl_{exit_h}s"
        if pnl_col in first_row.index:
            pnl = first_row[pnl_col]
            if not math.isnan(pnl):
                results.append(pnl)
            else:
                results.append(0.0)
    return float(np.mean(results)) if results else float("nan")

def run_gate2() -> dict:
    test_df, oracle_df, test = _load_data()
    oracle_test = oracle_df[oracle_df["period"] == "test"]

    if len(test) == 0:
        print("No test data found."); return {}

    oracle_ev = float(oracle_test["oracle_pnl"].mean())
    oracle_n  = len(oracle_test)
    print(f"Oracle (test, {oracle_n:,} eps): EV={oracle_ev:+.2f}/ep")

    # Load predictions (from gate1)
    pred_df = None
    if PRED_FILE.exists():
        pred_df = pd.read_parquet(PRED_FILE)
        print(f"  Loaded predictions for {len(pred_df):,} val observations")

    policies = []

    # Baselines
    for h in HORIZONS_S:
        ev = _baseline_fixed(test, h)
        policies.append({
            "policy":      f"fixed_{h}s",
            "ev_per_ep":   ev,
            "pct_oracle":  100 * ev / oracle_ev if oracle_ev != 0 else float("nan"),
        })

    hold_ev = _baseline_hold(test)
    policies.append({
        "policy":     "hold_to_episode_end",
        "ev_per_ep":  hold_ev,
        "pct_oracle": 100 * hold_ev / oracle_ev if oracle_ev != 0 else float("nan"),
    })

    # ML policies
    if pred_df is not None:
        from studies.rl_regime_feasibility.causal_models import HORIZONS_S as H_LIST
        import re
        prob_cols = [c for c in pred_df.columns if c.endswith("_prob")]
        for prob_col in prob_cols:
            m = re.match(r"(.+)_h(\d+)_prob", prob_col)
            if not m:
                continue
            model_name, h_s = m.group(1), int(m.group(2))
            thr_col = prob_col.replace("_prob", "_thr")
            thr = float(pred_df[thr_col].iloc[0]) if thr_col in pred_df.columns else 0.5

            ev = _ml_policy(test, pred_df, prob_col, thr, h_s)
            policies.append({
                "policy":     f"ml_{model_name}_h{h_s}s",
                "ev_per_ep":  ev,
                "pct_oracle": 100 * ev / oracle_ev if oracle_ev != 0 else float("nan"),
            })

    results_df = pd.DataFrame(policies).sort_values("ev_per_ep", ascending=False)
    results_df.to_parquet(OUT_DIR / "gate2_policy_results.parquet", index=False)

    # Gate 2 verdict
    best_ev  = results_df["ev_per_ep"].max() if len(results_df) else float("nan")
    gate2_pass = (not math.isnan(best_ev)) and (not math.isnan(oracle_ev)) and \
                 oracle_ev > 0 and (best_ev / oracle_ev) >= 0.50

    _write_gate2_report(results_df, oracle_ev, oracle_n, gate2_pass)

    return {"results": results_df, "oracle_ev": oracle_ev, "gate2_pass": gate2_pass}


def _write_gate2_report(results: pd.DataFrame, oracle_ev: float,
                        oracle_n: int, gate2_pass: bool) -> None:
    lines = []
    lines.append("=" * 70)
    lines.append("GATE 2: CAUSAL POLICY vs CLAIRVOYANT ORACLE")
    lines.append("=" * 70)
    lines.append(f"\nOracle EV/episode = {oracle_ev:+.2f}  (n={oracle_n:,} test episodes)")
    lines.append(f"Gate 2 pass criterion: best_policy_EV >= 50% of oracle_EV\n")
    lines.append(f"  {'Policy':<35}  {'EV/ep':>8}  {'% Oracle':>10}")
    lines.append("  " + "-" * 60)
    for _, r in results.iterrows():
        pct = f"{r['pct_oracle']:.1f}%" if not math.isnan(r["pct_oracle"]) else "  n/a"
        ev  = f"{r['ev_per_ep']:+.2f}"  if not math.isnan(r["ev_per_ep"])  else "  n/a"
        lines.append(f"  {r['policy']:<35}  {ev:>8}  {pct:>10}")

    verdict = "FEASIBLE" if gate2_pass else "NOT FEASIBLE"
    lines.append(f"\nGATE 2 VERDICT: {verdict}")

    report = "\n".join(lines)
    print("\n" + report)
    (OUT_DIR / "gate2_report.txt").write_text(report)


if __name__ == "__main__":
    run_gate2()

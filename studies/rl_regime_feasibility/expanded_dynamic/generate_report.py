"""Phase 8: Generate final decision-ready report.

Produces:
  results/final_report.md
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

OUT_DIR = Path("studies/rl_regime_feasibility/expanded_dynamic/results")

_ORACLE_EV = 167.36  # test-period oracle EV from original study
_PASS_EV   = 0.50 * _ORACLE_EV  # Gate 2 threshold: 50% of oracle


def load_results() -> dict:
    r = {}
    for name, path in [
        ("ablation_metrics",   OUT_DIR / "ablation_metrics.parquet"),
        ("replay_summary",     OUT_DIR / "replay_summary.parquet"),
        ("control_results",    OUT_DIR / "control_results.parquet"),
        ("feature_inventory",  OUT_DIR / "existing_feature_inventory.parquet"),
    ]:
        try:
            r[name] = pd.read_parquet(path)
        except Exception as e:
            print(f"  WARNING: {name} not found ({e})")
            r[name] = pd.DataFrame()

    for name, path in [
        ("policy_thresholds", OUT_DIR / "policy_thresholds.json"),
        ("knn_kc_audit",      OUT_DIR / "knn_kc_audit.json"),
    ]:
        try:
            with open(path) as f:
                r[name] = json.load(f)
        except Exception as e:
            print(f"  WARNING: {name} not found ({e})")
            r[name] = {}

    return r


def generate_report(r: dict) -> str:
    lines = []

    def h1(s):  lines.append(f"# {s}")
    def h2(s):  lines.append(f"\n## {s}")
    def h3(s):  lines.append(f"\n### {s}")
    def ln(s=""): lines.append(s)
    def tbl(df, cols=None):
        if cols:
            df = df[cols]
        # Manual markdown table (no tabulate dependency)
        header = "| " + " | ".join(str(c) for c in df.columns) + " |"
        sep    = "| " + " | ".join("---" for _ in df.columns) + " |"
        lines.append(header)
        lines.append(sep)
        for _, row in df.iterrows():
            lines.append("| " + " | ".join(str(v) for v in row.values) + " |")

    h1("Expanded Dynamic Study — Final Report")
    ln("**Study**: rl_regime_feasibility/expanded_dynamic")
    ln("**Date**: 2026-07-03")
    ln()
    ln("## Study Design Summary")
    ln()
    ln("This study tests whether expanded causal regime-path features and pre-flip context")
    ln("(from regime_dna.parquet) can identify profitable dynamic entry + exit policies")
    ln("during 1-minute regime-flip episodes on NQ.v.0.")
    ln()
    ln("**Non-negotiable design rules:**")
    ln("- Exact same 1s replay engine as 2x2 study")
    ln("- Locked chronological split: train=2024, val=Jan-Feb 2025, test=Mar-May 2025")
    ln("- No test set used for any selection")
    ln("- Reuse existing KNN/kC artifacts only as frozen CAUSAL_SAFE features")
    ln("- Max one entry per episode")

    # Phase 1: Audit summary
    h2("Phase 1: KNN/kC Artifact Audit")
    ln()
    inv = r.get("feature_inventory", pd.DataFrame())
    if len(inv) > 0:
        src_counts = inv["source"].value_counts().to_dict()
        ln(f"Feature inventory: {len(inv)} total features")
        for src, n in src_counts.items():
            ln(f"  - {src}: {n}")
    ln()
    ln("| Artifact | Classification | Decision |")
    ln("|----------|---------------|---------|")
    ln("| `regime_dna.parquet` (pre-flip DNA) | CAUSAL_SAFE | INCLUDED |")
    ln("| `dna_knn_scores.parquet` | NONCAUSAL | EXCLUDED (train-test contamination + dead signal) |")
    ln("| `obs_depth*.parquet` (hC values) | NONCAUSAL | EXCLUDED (selection bias) |")
    ln("| `early_health_capsule.parquet` | CAUSAL_UNCERTAIN | EXCLUDED (post_* forward-looking) |")
    ln("| `transition_atlas.parquet` | NONCAUSAL | EXCLUDED (population summary) |")
    ln("| `hc_sizing_extremes/trades.parquet` | NONCAUSAL | EXCLUDED (60 trades, not representative) |")

    # Phase 2: Feature set
    h2("Phase 2: Expanded Feature Set")
    ln()
    if len(inv) > 0:
        src_counts = inv["source"].value_counts().to_dict()
        ln(f"| Source | Count |")
        ln("|--------|-------|")
        for src, n in src_counts.items():
            ln(f"| {src} | {n} |")
    ln()
    ln("Pre-flip DNA features joined on flip_time=regime_start_ts (100% coverage of RL episodes).")
    ln("Derived features: path geometry ratios, interaction terms, regime alignment composite.")

    # Phase 4: Ablation results
    h2("Phase 4: Model Ablations")
    ln()
    abl = r.get("ablation_metrics", pd.DataFrame())
    if len(abl) > 0:
        tbl(abl, ["ablation", "n_features", "val_auc", "test_auc", "gate1_pass"])
        ln()
        best_test = abl.loc[abl["test_auc"].idxmax()]
        ln(f"Best ablation by test AUC: **{best_test['ablation']}** ({best_test['test_auc']:.4f})")
        n_pass = abl["gate1_pass"].sum()
        ln(f"Gate 1 (AUC >= 0.54): {n_pass}/{len(abl)} ablations pass")
    else:
        ln("*Ablation results not available*")

    # Phase 5: Policy
    h2("Phase 5: Dynamic Policy")
    ln()
    thr = r.get("policy_thresholds", {})
    if thr:
        ln(f"| Parameter | Value |")
        ln("|-----------|-------|")
        for k, v in thr.items():
            ln(f"| {k} | {v} |")

    # Phase 6: Replay results
    h2("Phase 6: Exact 1s Replay Results")
    ln()
    replay = r.get("replay_summary", pd.DataFrame())
    if len(replay) > 0:
        row = replay.iloc[0]
        n_ep   = int(row.get("n_episodes", 0))
        n_tr   = int(row.get("n_traded", 0))
        t_rate = float(row.get("trade_rate", 0)) * 100
        total  = float(row.get("total_pnl", 0))
        ev_ep  = float(row.get("ev_per_episode", 0))
        ev_tr  = float(row.get("ev_per_trade", 0))
        wr     = float(row.get("win_rate", 0)) * 100
        ci_lo  = float(row.get("ci_lo_95", 0))
        ci_hi  = float(row.get("ci_hi_95", 0))

        oracle_pct = 100 * ev_ep / _ORACLE_EV if _ORACLE_EV != 0 else 0.0
        gate2_pass = ev_ep >= _PASS_EV

        ln(f"| Metric | Value |")
        ln(f"|--------|-------|")
        ln(f"| Test episodes | {n_ep:,} |")
        ln(f"| Traded episodes | {n_tr:,} ({t_rate:.1f}%) |")
        ln(f"| Total PnL | ${total:+,.0f} |")
        ln(f"| **EV / episode** | **${ev_ep:+.2f}** |")
        ln(f"| EV / trade | ${ev_tr:+.2f} |")
        ln(f"| Win rate | {wr:.1f}% |")
        ln(f"| 95% bootstrap CI | ({ci_lo:+.2f}, {ci_hi:+.2f}) |")
        ln(f"| Oracle EV (ceiling) | +${_ORACLE_EV:,.2f} |")
        ln(f"| % of oracle EV | {oracle_pct:+.1f}% |")
        ln(f"| Gate 2 threshold (50% of oracle) | ${_PASS_EV:.2f} |")
        ln(f"| **Gate 2 result** | **{'PASS' if gate2_pass else 'FAIL'}** |")
        ln()

        # vs baseline canonical (-$6.46)
        baseline_ev = -6.46
        delta = ev_ep - baseline_ev
        ln(f"vs canonical baseline (-$6.46/ep): **delta = ${delta:+.2f}/ep**")
    else:
        ln("*Replay results not available*")

    # Phase 7: Controls
    h2("Phase 7: Control Experiments")
    ln()
    ctrl = r.get("control_results", pd.DataFrame())
    if len(ctrl) > 0:
        tbl(ctrl, ["control", "val_auc", "test_auc", "delta_val", "delta_test", "interpretation"])
        ln()
        # Interpret DNA shuffle
        dna_row = ctrl[ctrl["control"] == "1_dna_shuffle"]
        if len(dna_row) > 0:
            dna_delta = float(dna_row.iloc[0]["delta_test"])
            if abs(dna_delta) < 0.002:
                ln("**DNA shuffle**: near-zero AUC change => pre-flip DNA adds negligible information")
            elif dna_delta < -0.005:
                ln(f"**DNA shuffle**: AUC drops {dna_delta:.4f} => DNA features carry genuine predictive signal")
    else:
        ln("*Control results not available*")

    # Final verdict
    h2("Final Verdict")
    ln()
    replay = r.get("replay_summary", pd.DataFrame())
    abl    = r.get("ablation_metrics", pd.DataFrame())

    gate1_any  = any(abl["gate1_pass"]) if len(abl) > 0 else False
    gate2_pass = False
    ev_ep = 0.0
    if len(replay) > 0:
        ev_ep     = float(replay.iloc[0].get("ev_per_episode", 0))
        gate2_pass = ev_ep >= _PASS_EV
        ci_lo      = float(replay.iloc[0].get("ci_lo_95", 0))

    if gate1_any and gate2_pass:
        verdict = "STRONG PASS"
        action  = "Proceed with full RL / PPO development on this feature set."
    elif gate1_any and ev_ep > 0:
        verdict = "CONDITIONAL PASS"
        action  = "Marginal positive EV detected. Validate with wider date range before RL investment."
    else:
        verdict = "FAIL"
        action  = "Do not proceed with RL on OHLCV-only expanded feature set. Edge remains undetectable."

    ln(f"### Decision: {verdict}")
    ln()
    ln(f"**Gate 1 (AUC >= 0.54)**: {'PASS' if gate1_any else 'FAIL'}")
    ln(f"**Gate 2 (EV >= ${_PASS_EV:.0f}/ep = 50% of oracle)**: {'PASS' if gate2_pass else 'FAIL'}")
    ln()
    ln(f"**Recommended action**: {action}")
    ln()

    # Comparison to prior work
    h3("Comparison to Prior Study (Canonical -$6.46/ep)")
    ln()
    ln(f"| Study | Entry | Exit | EV/ep | Result |")
    ln(f"|-------|-------|------|-------|--------|")
    ln(f"| Canonical 2x2 Cell C | First crossing h300 | Fixed 300s | -$6.46 | FAIL |")
    ln(f"| Canonical 2x2 Cell D | First crossing h300 | Dynamic score | -$2.12 | FAIL |")
    ln(f"| Expanded dynamic (this) | Entry model | Exit model | ${ev_ep:+.2f} | {'PASS' if gate2_pass else 'FAIL'} |")

    ln()
    h3("Key Caveats")
    ln("- Models trained on OHLCV-derived features only; no order flow or book data")
    ln("- 1s bar execution mode may slightly overstate vs tick execution")
    ln("- Exit model trained on ALL positioned steps (assumes entry at step 0), not actual policy entries")
    ln("- Pre-flip DNA features are episode-level constants (same value for all steps in an episode)")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Phase 8: Generating final report ...")
    r = load_results()
    report = generate_report(r)
    out_path = OUT_DIR / "final_report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Saved: {out_path}")
    print("\n--- REPORT PREVIEW (first 80 lines) ---")
    for line in report.split("\n")[:80]:
        print(line)

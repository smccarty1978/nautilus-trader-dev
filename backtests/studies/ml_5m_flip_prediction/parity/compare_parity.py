"""Compare offline vs runtime feature rows + scores + decisions.

Reads:
  parity_offline_features_2025.parquet   — from export_offline_features.py
  parity_runtime_features_2025.parquet   — from NT strategy in parity mode
  models/ml_5m_flip/feature_contract_v1.json — tolerance rules

Outputs:
  feature_parity_report_2025.json       — per-feature summary
  feature_parity_failures_2025.csv      — per-event failure details
  score_parity_report_2025.json         — score diff summary
  decision_parity_report_2025.json      — decision agreement
"""

import sys
import os
import json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

PARITY_DIR = Path("studies/ml_5m_flip_prediction/parity")
OFFLINE_PATH = PARITY_DIR / "parity_offline_features_2025.parquet"
RUNTIME_PATH = PARITY_DIR / "parity_runtime_features_2025.parquet"
CONTRACT_PATH = "models/ml_5m_flip/feature_contract_v1.json"
THR_PATH = "models/ml_5m_flip/threshold_2026.json"

OUT_FEATURE_REPORT = PARITY_DIR / "feature_parity_report_2025.json"
OUT_FEATURE_FAILURES = PARITY_DIR / "feature_parity_failures_2025.csv"
OUT_SCORE_REPORT = PARITY_DIR / "score_parity_report_2025.json"
OUT_DECISION_REPORT = PARITY_DIR / "decision_parity_report_2025.json"

SCORE_TOL = 1e-6
SCORE_LOOSER_TOL = 1e-4  # acceptable if features within tolerance
                         # but model FP nondeterminism still produces tiny drift


def main():
    print("Loading parity inputs...")
    if not OFFLINE_PATH.exists():
        print(f"  ERROR: missing {OFFLINE_PATH}")
        return
    if not RUNTIME_PATH.exists():
        print(f"  WARN: runtime parquet not found at {RUNTIME_PATH}")
        print(f"        Run NT strategy in parity mode first.")
        return

    offline = pd.read_parquet(OFFLINE_PATH)
    runtime = pd.read_parquet(RUNTIME_PATH)
    print(f"  offline rows: {len(offline):,}")
    print(f"  runtime rows: {len(runtime):,}")

    with open(CONTRACT_PATH) as f:
        contract = json.load(f)
    feature_specs = {f["name"]: f for f in contract["features"]}
    feat_cols = [f["name"] for f in contract["features"]]
    print(f"  contract features: {len(feat_cols)}")

    with open(THR_PATH) as f:
        threshold = json.load(f)["bottom_50"]
    print(f"  threshold: {threshold:.6f}")

    # Match by event_id
    offline = offline.set_index("event_id")
    runtime = runtime.set_index("event_id")
    matched_ids = sorted(set(offline.index) & set(runtime.index))
    only_offline = sorted(set(offline.index) - set(runtime.index))
    only_runtime = sorted(set(runtime.index) - set(offline.index))
    print(f"\n  Matched: {len(matched_ids):,}")
    print(f"  Only offline: {len(only_offline)}")
    print(f"  Only runtime: {len(only_runtime)}")
    if only_offline:
        print(f"    First missing in runtime: {only_offline[:5]}")

    if not matched_ids:
        print("  No matches — cannot compare. Aborting.")
        return

    off_m = offline.loc[matched_ids]
    rt_m = runtime.loc[matched_ids]

    # ============================================================
    # Feature parity
    # ============================================================
    print("\n--- FEATURE PARITY ---")
    feature_results = {}
    failure_rows = []

    for col in feat_cols:
        if col not in off_m.columns:
            feature_results[col] = {"status": "MISSING_OFFLINE"}
            continue
        if col not in rt_m.columns:
            feature_results[col] = {"status": "MISSING_RUNTIME"}
            continue
        spec = feature_specs[col]
        tol = spec["parity_tolerance"]
        tol_cat = spec["parity_tolerance_category"]

        off_v = off_m[col].astype(float).values
        rt_v = rt_m[col].astype(float).values
        # Treat NaN as equal to NaN
        both_nan = np.isnan(off_v) & np.isnan(rt_v)
        diff = np.abs(off_v - rt_v)
        diff_safe = np.where(both_nan, 0.0, diff)
        # Replace NaN diff (one is NaN, other isn't) with infinity to fail
        nan_mismatch = (np.isnan(off_v) ^ np.isnan(rt_v))
        diff_safe = np.where(nan_mismatch, np.inf, diff_safe)

        n = len(diff_safe)
        n_pass = int((diff_safe <= tol).sum())
        n_fail = n - n_pass
        max_diff = float(diff_safe[~np.isinf(diff_safe)].max()
                          if (~np.isinf(diff_safe)).any() else np.inf)
        mean_diff = float(diff_safe[~np.isinf(diff_safe)].mean()
                           if (~np.isinf(diff_safe)).any() else np.nan)

        feature_results[col] = {
            "status": "PASS" if n_fail == 0 else "FAIL",
            "tolerance": tol,
            "tolerance_category": tol_cat,
            "n_total": n,
            "n_pass": n_pass,
            "n_fail": n_fail,
            "max_diff": max_diff,
            "mean_diff": mean_diff,
        }

        if n_fail > 0:
            fail_idx = np.where(diff_safe > tol)[0]
            for idx in fail_idx[:10]:  # cap per-feature failures
                failure_rows.append({
                    "event_id": matched_ids[idx],
                    "feature": col,
                    "offline_value": off_v[idx],
                    "runtime_value": rt_v[idx],
                    "abs_diff": diff_safe[idx],
                    "tolerance": tol,
                    "tolerance_category": tol_cat,
                })

    # Summary
    n_pass_features = sum(1 for r in feature_results.values()
                           if r.get("status") == "PASS")
    n_fail_features = sum(1 for r in feature_results.values()
                           if r.get("status") == "FAIL")
    print(f"  Features PASS:  {n_pass_features}")
    print(f"  Features FAIL:  {n_fail_features}")
    if n_fail_features > 0:
        print(f"\n  Top failing features (by max_diff):")
        fails = [(name, r) for name, r in feature_results.items()
                 if r.get("status") == "FAIL"]
        fails.sort(
            key=lambda x: -x[1]["max_diff"]
            if not np.isinf(x[1]["max_diff"]) else -1e308)
        for name, r in fails[:15]:
            print(f"    {name:<40} cat={r['tolerance_category']:<10} "
                  f"max_diff={r['max_diff']:.3e} "
                  f"({r['n_fail']}/{r['n_total']} fail)")

    # Save
    summary = {
        "matched_events": len(matched_ids),
        "n_features_pass": n_pass_features,
        "n_features_fail": n_fail_features,
        "by_feature": feature_results,
    }
    with open(OUT_FEATURE_REPORT, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n  Saved: {OUT_FEATURE_REPORT}")

    if failure_rows:
        pd.DataFrame(failure_rows).to_csv(OUT_FEATURE_FAILURES,
                                           index=False)
        print(f"  Saved: {OUT_FEATURE_FAILURES} ({len(failure_rows)} rows)")

    # ============================================================
    # Score parity
    # ============================================================
    if "offline_pred" in off_m.columns and "runtime_pred" in rt_m.columns:
        off_score = off_m["offline_pred"].values
        rt_score = rt_m["runtime_pred"].values
        sd = np.abs(off_score - rt_score)
        n_pass_strict = int((sd <= SCORE_TOL).sum())
        n_pass_loose = int((sd <= SCORE_LOOSER_TOL).sum())
        score_summary = {
            "matched_events": len(matched_ids),
            "score_tol_strict": SCORE_TOL,
            "score_tol_looser": SCORE_LOOSER_TOL,
            "n_pass_strict": n_pass_strict,
            "n_pass_looser": n_pass_loose,
            "max_diff": float(sd.max()),
            "mean_diff": float(sd.mean()),
            "p50_diff": float(np.percentile(sd, 50)),
            "p95_diff": float(np.percentile(sd, 95)),
        }
        with open(OUT_SCORE_REPORT, "w") as f:
            json.dump(score_summary, f, indent=2)
        print(f"\n--- SCORE PARITY ---")
        print(f"  Matched: {len(matched_ids):,}")
        print(f"  PASS @ {SCORE_TOL:.0e}: {n_pass_strict}")
        print(f"  PASS @ {SCORE_LOOSER_TOL:.0e}: {n_pass_loose}")
        print(f"  Max diff: {sd.max():.3e}")
        print(f"  Saved: {OUT_SCORE_REPORT}")
    else:
        print("\n  WARN: score columns missing (offline_pred or runtime_pred)")

    # ============================================================
    # Decision parity
    # ============================================================
    if ("offline_decision" in off_m.columns
            and "runtime_decision" in rt_m.columns):
        off_dec = off_m["offline_decision"].astype(int).values
        rt_dec = rt_m["runtime_decision"].astype(int).values
        agree = int((off_dec == rt_dec).sum())
        decision_summary = {
            "matched_events": len(matched_ids),
            "agreements": agree,
            "disagreements": len(matched_ids) - agree,
            "agreement_pct": agree / len(matched_ids) * 100,
            "approved_offline": int(off_dec.sum()),
            "approved_runtime": int(rt_dec.sum()),
        }
        with open(OUT_DECISION_REPORT, "w") as f:
            json.dump(decision_summary, f, indent=2)
        print(f"\n--- DECISION PARITY ---")
        print(f"  Matched: {len(matched_ids):,}")
        print(f"  Agreement: {agree} / {len(matched_ids)}  "
              f"({agree/len(matched_ids)*100:.1f}%)")
        print(f"  Saved: {OUT_DECISION_REPORT}")


if __name__ == "__main__":
    main()

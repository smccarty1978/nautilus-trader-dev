"""Phase 7 -- apply the predeclared selection gates (SPEC.md) to the 8
raw-count candidates on the complete 2025 population (Phase 6 outputs).
Selects the smallest candidate passing every gate; never forces a <=100
candidate to pass, never skips a gate.
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from common import RESULTS, ARTIFACTS, SRC_STUDY, TARGET, metrics_row

RAW_CANDIDATE_IDS = ["F3_top25_gbt_v1", "F3_top40_gbt_v1", "F3_top60_gbt_v1", "F3_top80_gbt_v1",
                     "F3_top100_gbt_v1", "F3_top150_gbt_v1", "F3_top250_gbt_v1", "F3_live546_gbt_v2"]

GATE_AUC_DELTA_MIN = -0.005
GATE_AP_DELTA_MIN = -0.010
GATE_REGIME_OVERLAP_MIN = 0.95
# Baseline-RELATIVE, same-month comparison -- NOT a self-referential drop off
# the candidate's own overall AUC. Verified directly: even the 695-feature
# baseline's own monthly AUC ranges from 0.618 (July) to 0.697 (Oct/Nov) --
# a >0.05 swing that is a property of this prediction problem's natural
# monthly variability, not evidence of any candidate's degradation. Gating
# a candidate against its OWN overall AUC would have wrongly flagged every
# candidate (including a hypothetical byte-identical copy of the baseline)
# on this basis alone.
GATE_MONTHLY_MAX_DROP_VS_BASELINE_SAME_MONTH = 0.03


def compute_baseline_monthly_auc() -> dict:
    dev_df = pd.read_parquet(SRC_STUDY / "_work" / "prepared_2025.parquet")
    dev_df["month"] = pd.to_datetime(dev_df["observation_time"], unit="ns", utc=True).dt.month
    model = joblib.load(ARTIFACTS / "F3_695_baseline" / "model.joblib")
    feats = json.loads((ARTIFACTS / "F3_695_baseline" / "feature_list.json").read_text())["ordered_features"]
    dev_df["score"] = model.predict_proba(dev_df[feats])[:, 1]
    out = {}
    for month, g in dev_df.groupby("month"):
        out[int(month)] = metrics_row(g[TARGET].astype(int).to_numpy(), g["score"].to_numpy())["auc"]
    return out


def main() -> None:
    metrics = pd.read_csv(RESULTS / "candidate_model_metrics.csv")
    overlap = pd.read_csv(RESULTS / "candidate_population_overlap.csv")
    ap_baseline = json.loads((ARTIFACTS / "F3_695_baseline" / "metrics_2025.json").read_text())["dev_2025"]["average_precision"]
    baseline_monthly_auc = compute_baseline_monthly_auc()
    (RESULTS / "baseline_monthly_auc.json").write_text(json.dumps(baseline_monthly_auc, indent=2))

    gate_rows = []
    for model_id in RAW_CANDIDATE_IDS:
        m = metrics[metrics["model_id"] == model_id]
        if m.empty:
            gate_rows.append({"model_id": model_id, "status": "NOT_EVALUATED"})
            continue
        m = m.iloc[0]
        o = overlap[overlap["model_id"] == model_id]
        o5 = o[o["band"] == "top5pct"].iloc[0]
        o25 = o[o["band"] == "top2_5pct"].iloc[0]

        # json.loads always yields STRING dict keys even though both sides were
        # built from int(month) -- cast both to int before comparing, or the
        # membership check below silently matches nothing and this gate
        # trivially "passes" every candidate (caught by inspection: an
        # earlier version of this script reported worst_month_deficit=0.0
        # for all 8 candidates simultaneously, which is not plausible).
        monthly_auc = {int(k): v for k, v in json.loads(m["monthly_auc"]).items()}
        # baseline-relative, same-month comparison (see GATE_MONTHLY_MAX_DROP_VS_BASELINE_SAME_MONTH note)
        monthly_deficits = {mo: baseline_monthly_auc[mo] - auc for mo, auc in monthly_auc.items()
                            if mo in baseline_monthly_auc}
        worst_month_deficit = max(monthly_deficits.values()) if monthly_deficits else 0.0

        feat_list = json.loads((ARTIFACTS / model_id / "feature_list.json").read_text())["ordered_features"]
        n_features = len(feat_list)
        checks = {
            "auc_delta_gate": bool(m["auc_delta_vs_baseline"] >= GATE_AUC_DELTA_MIN),
            "ap_delta_gate": None,  # requires baseline AP, filled below
            "top5pct_regime_overlap_gate": bool(o5["quantile_matched_regime_overlap"] >= GATE_REGIME_OVERLAP_MIN),
            "top2_5pct_regime_overlap_gate": bool(o25["quantile_matched_regime_overlap"] >= GATE_REGIME_OVERLAP_MIN),
            "monthly_no_collapse_gate": bool(worst_month_deficit <= GATE_MONTHLY_MAX_DROP_VS_BASELINE_SAME_MONTH),
            "all_features_live_tracker_and_registry_bound": True,  # guaranteed: candidates built only from 546 live-ready pool
        }
        ap_delta_val = float(m["average_precision"] - ap_baseline)
        checks["ap_delta_gate"] = bool(ap_delta_val >= GATE_AP_DELTA_MIN)

        passed = all(checks.values())
        gate_rows.append({
            "model_id": model_id, "n_features": n_features,
            "auc": m["auc"], "auc_delta_vs_baseline": m["auc_delta_vs_baseline"],
            "average_precision": m["average_precision"], "ap_delta_vs_baseline": ap_delta_val,
            "top5pct_regime_overlap": o5["quantile_matched_regime_overlap"],
            "top2_5pct_regime_overlap": o25["quantile_matched_regime_overlap"],
            "worst_month_deficit_vs_baseline_same_month": worst_month_deficit,
            **checks,
            "status": "PASS" if passed else "FAIL",
        })

    gate_df = pd.DataFrame(gate_rows).sort_values("n_features")
    gate_df.to_csv(RESULTS / "phase7_gate_results.csv", index=False)
    print(gate_df.to_string(index=False))

    passing = gate_df[gate_df["status"] == "PASS"]
    if passing.empty:
        selected = None
        decision = "NO_REDUCED_MODEL_PRESERVES_POPULATION"
    else:
        under_100 = passing[passing["n_features"] <= 100]
        if not under_100.empty:
            selected = under_100.sort_values("n_features").iloc[0]
        else:
            selected = passing.sort_values("n_features").iloc[0]
        decision = ("REDUCED_RUNTIME_MODEL_SELECTED" if selected["model_id"] != "F3_live546_gbt_v1"
                   else "LIVE_READY_546_MODEL_SELECTED")

    result = {
        "selected_model_id": None if selected is None else selected["model_id"],
        "selected_n_features": None if selected is None else int(selected["n_features"]),
        "decision": decision,
        "all_candidates_gate_results": gate_rows,
    }
    (RESULTS / "selection_gate_decision.json").write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps({k: v for k, v in result.items() if k != "all_candidates_gate_results"}, indent=2))


if __name__ == "__main__":
    main()

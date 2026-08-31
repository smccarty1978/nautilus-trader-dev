"""Assemble the 2024 OOS card from the governed OOS artifacts. Read-only aggregation."""
from __future__ import annotations
import json
from pathlib import Path

S = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\studies\clean_maturity_flip_model_180s_horizon")
A = S / "artifacts"


def L(name):
    return json.loads((A / name).read_text(encoding="utf-8"))


agg = L("train_experiment_freeze.json")
merge = L("oos_partition_merge.json")
unlock = L("oos_unlock.json")
ct = L("oos_2024_classification_timing.json")
econ = L("oos_2024_economic_path.json")
tps = L("two_phase_selection_dispatch_summary.json")
train_diag = L("diag_classification_180s_vs_300s.json")


def dir_block(d):
    b = ct[d]
    c180 = b["classification_180s"]
    c300 = b["classification_300s_parent_benchmark"]
    td = train_diag[d]
    tr180 = td["classification_180s_full_train"]
    tr300 = td["classification_300s_full_train"]
    st = b["frozen_score_tail_180s"]
    stp = b["frozen_score_tail_300s_parent_benchmark"]
    tm = b["first_crossing_timing_180s"]
    tmp = b["first_crossing_timing_300s_parent_benchmark"]
    ep90 = econ["p90"][d]
    return {
        "model_id": b["model_id_180s"],
        "n_labeled_oos": b["n_180s"],
        "classification_generalization": {
            "base_rate_180s": c180["positive_rate"],
            "roc_auc_180s": c180["roc_auc"],
            "pr_auc_180s": c180["pr_auc"],
            "pr_auc_over_base_rate_180s": c180["pr_auc_over_base_rate"],
            "brier_180s": c180["brier"],
            "expected_calibration_error_180s": c180["calibration"]["expected_calibration_error"],
            "parent_300s_benchmark": {
                "base_rate": c300["positive_rate"], "roc_auc": c300["roc_auc"],
                "pr_auc": c300["pr_auc"], "pr_auc_over_base_rate": c300["pr_auc_over_base_rate"],
                "brier": c300["brier"],
            },
            "roc_auc_delta_180s_minus_300s_OOS": round(c180["roc_auc"] - c300["roc_auc"], 4),
            "roc_auc_delta_180s_minus_300s_TRAIN": round(tr180["roc_auc"] - tr300["roc_auc"], 4),
            "lift_ratio_180s_over_300s_OOS": round(c180["pr_auc_over_base_rate"] / c300["pr_auc_over_base_rate"], 3),
            "relationship_replicates": (c180["roc_auc"] - c300["roc_auc"]) > 0
                and (c180["pr_auc_over_base_rate"] > c300["pr_auc_over_base_rate"]),
        },
        "frozen_score_tail": {
            k: {"threshold_TRAIN": st[k]["threshold"], "retained_n": st[k]["retained_n"],
                "retained_frac": st[k]["retained_frac"], "actual_flip_prob": st[k]["actual_flip_prob"],
                "precision_lift_over_2024_base": st[k]["precision_lift_over_base"],
                "median_seconds_to_flip": st[k]["median_seconds_to_flip"],
                "parent_300s": {"retained_frac": stp[k]["retained_frac"],
                                "actual_flip_prob": stp[k]["actual_flip_prob"],
                                "precision_lift_over_2024_base": stp[k]["precision_lift_over_base"],
                                "median_seconds_to_flip": stp[k]["median_seconds_to_flip"]}}
            for k in ("p90", "p95", "p97_5")
        },
        "timing": {
            k: {"median_sec_to_flip_180s": tm[k]["median_seconds_to_flip"],
                "median_sec_to_flip_300s": tmp[k]["median_seconds_to_flip"],
                "delta_sec_180s_closer": (tmp[k]["median_seconds_to_flip"] - tm[k]["median_seconds_to_flip"])
                if (tm[k]["median_seconds_to_flip"] and tmp[k]["median_seconds_to_flip"]) else None}
            for k in ("p90", "p95", "p97_5")
        },
        "economic_preservation_p90_first_crossing": {
            "n_first_crossings_180s": ep90.get("n_first_crossings_180s"),
            "n_first_crossings_300s": ep90.get("n_first_crossings_300s"),
            "180s": ep90.get("summary_180s"),
            "300s": ep90.get("summary_300s"),
        },
        "train_to_oos_degradation": b["train_to_oos_degradation"],
        "train_2023_reject_only_gate": b["train_2023_reject_only_gate"],
    }


card = {
    "card": "2024_OOS",
    "study_id": "clean_maturity_flip_model_180s_horizon",
    "branch": "study/clean_maturity_flip_180s_reconcile",
    "oos_year": 2024,
    "oos_accessed": "YES (this card)",
    "y2025_2026_accessed": "NO",
    "frozen_identities": {
        "aggregate_train_freeze_sha256": agg["freeze_sha256"],
        "LONG_model_id": next(r["model_id"] for r in agg["model_artifacts"] if r["model_role"] == "LONG_C"),
        "SHORT_model_id": next(r["model_id"] for r in agg["model_artifacts"] if r["model_role"] == "SHORT_C"),
        "preprocessing_hash": agg["preprocessing_hash"],
        "authorization_sha256": agg["authorization_sha256"],
        "stage_scoped_lineage": agg["stage_scoped_lineage"],
        "target": "prevailing 1m regime flip within (T, T+180s], inclusive upper bound",
        "thresholds_TRAIN_only": {r: agg["thresholds"][r] for r in ("LONG_C", "SHORT_C")},
        "no_refit_no_retune_no_threshold_change": True,
    },
    "oos_collection": {
        "candidates": merge["candidate_rows"], "observations": merge["observation_rows"],
        "disposition_counts": merge["disposition_counts"],
        "oos_pristine_2024_only": merge["oos_pristine_2024_only"],
        "forward_timestamp_year_ranges": merge["forward_timestamp_year_ranges"],
        "merge_sha256": merge["merge_sha256"],
        "train_freeze_sha256_bound": merge["train_freeze_sha256"],
        "oos_unlock_token_sha256": unlock["unlock_token_sha256"],
        "pristine_oos_proven": unlock["lineage_audit"]["pristine_oos_proven"],
    },
    "LONG": dir_block("LONG"),
    "SHORT": dir_block("SHORT"),
}
(A / "2024_OOS_CARD.json").write_text(json.dumps(card, indent=2, default=str), encoding="utf-8")
print("WROTE 2024_OOS_CARD.json", (A / "2024_OOS_CARD.json").stat().st_size, "bytes")
for d in ("LONG", "SHORT"):
    g = card[d]["classification_generalization"]
    print(f"{d}: 180s ROC {g['roc_auc_180s']:.3f} vs 300s {g['parent_300s_benchmark']['roc_auc']:.3f} "
          f"(OOS delta {g['roc_auc_delta_180s_minus_300s_OOS']:+.3f}, TRAIN delta {g['roc_auc_delta_180s_minus_300s_TRAIN']:+.3f}); "
          f"replicates={g['relationship_replicates']}; PR-AUC retention TRAIN2023->OOS {card[d]['train_to_oos_degradation']['pr_auc_retention_frac']:.3f}")

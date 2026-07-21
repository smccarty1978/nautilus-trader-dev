"""Phase 5 - evaluate the preservation gates and emit the final decision.

Gate thresholds are exactly as briefed. The TOP100 reference used for the
"strong preservation" deltas is the TOP100 model re-fit in THIS harness (the
like-for-like comparison), which is also asserted to reproduce the prior study's
published 0.6682 / 0.6512.

Selection never reads 2026: the per-feature-set model is chosen on 2025 AUC
(tie-break 2025 AP) inside train_reduced.py, and the feature-set preference
order below is applied to gate outcomes, not to a 2026 ranking. 2026 enters only
as a pass/fail gate input and for decision labelling - as briefed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

STUDY = Path(__file__).resolve().parents[1]
RESULTS = STUDY / "results"

PRIOR_PUBLISHED = {"2025_auc": 0.6682, "2026_auc": 0.6512,
                   "2025_top_decile_flip_rate": 0.511, "2026_top_decile_flip_rate": 0.537}

MIN_VIABLE = {"2025_auc": 0.63, "2026_auc": 0.62,
              "2025_top_decile_lift": 1.70, "2026_top_decile_lift": 1.70,
              "monthly_auc_floor": 0.58}
STRONG = {"d_2025_auc": 0.015, "d_2026_auc": 0.020,
          "d_2025_flip_pp": 0.05, "d_2026_flip_pp": 0.05,
          "monthly_auc_floor": 0.60}


def main() -> None:
    mm = pd.read_csv(RESULTS / "model_metrics.csv")
    monthly = json.load(open(RESULTS / "monthly_auc_2026.json"))
    manifest = json.load(open(RESULTS / "model_manifest.json"))
    chosen = manifest["selected_per_feature_set"]  # e.g. {"TOP50": "TOP50_gbt", ...}

    ref_tag = chosen["TOP100"]
    ref = mm.set_index(["feature_set", "model"]).loc[tuple(ref_tag.split("_", 1))]
    repro = {
        "top100_refit_2025_auc": round(float(ref["2025_auc"]), 4),
        "top100_refit_2026_auc": round(float(ref["2026_auc"]), 4),
        "prior_published_2025_auc": PRIOR_PUBLISHED["2025_auc"],
        "prior_published_2026_auc": PRIOR_PUBLISHED["2026_auc"],
        "reproduces_prior": bool(
            abs(float(ref["2025_auc"]) - PRIOR_PUBLISHED["2025_auc"]) < 5e-4
            and abs(float(ref["2026_auc"]) - PRIOR_PUBLISHED["2026_auc"]) < 5e-4),
    }

    gates = {"top100_reproducibility": repro, "feature_sets": {}}
    for fs in ("TOP50", "TOP25"):
        tag = chosen[fs]
        r = mm.set_index(["feature_set", "model"]).loc[tuple(tag.split("_", 1))]
        months = {k: v for k, v in monthly[tag].items() if v is not None}

        mv = {
            "2025_auc>=0.63": bool(r["2025_auc"] >= MIN_VIABLE["2025_auc"]),
            "2026_auc>=0.62": bool(r["2026_auc"] >= MIN_VIABLE["2026_auc"]),
            "2025_lift>=1.70": bool(r["2025_top_decile_lift"] >= MIN_VIABLE["2025_top_decile_lift"]),
            "2026_lift>=1.70": bool(r["2026_top_decile_lift"] >= MIN_VIABLE["2026_top_decile_lift"]),
            "2026_decile_not_inverted": bool(not r["2026_decile_inverted"]),
            "all_2026_months>0.58": bool(all(v > MIN_VIABLE["monthly_auc_floor"] for v in months.values())),
        }
        sp = {
            "2025_auc_within_0.015": bool(abs(r["2025_auc"] - ref["2025_auc"]) <= STRONG["d_2025_auc"]),
            "2026_auc_within_0.020": bool(abs(r["2026_auc"] - ref["2026_auc"]) <= STRONG["d_2026_auc"]),
            "2025_flip_within_5pp": bool(abs(r["2025_top_decile_flip_rate"]
                                             - ref["2025_top_decile_flip_rate"]) <= STRONG["d_2025_flip_pp"]),
            "2026_flip_within_5pp": bool(abs(r["2026_top_decile_flip_rate"]
                                             - ref["2026_top_decile_flip_rate"]) <= STRONG["d_2026_flip_pp"]),
            "all_2026_months>0.60": bool(all(v > STRONG["monthly_auc_floor"] for v in months.values())),
        }
        gates["feature_sets"][fs] = {
            "selected_model": tag,
            "metrics": {k: round(float(r[k]), 5) for k in
                        ("2025_auc", "2026_auc", "2025_average_precision", "2026_average_precision",
                         "2025_top_decile_flip_rate", "2026_top_decile_flip_rate",
                         "2025_top_decile_lift", "2026_top_decile_lift",
                         "2025_decile_monotonicity_spearman", "2026_decile_monotonicity_spearman")},
            "delta_vs_top100": {
                "2025_auc": round(float(r["2025_auc"] - ref["2025_auc"]), 5),
                "2026_auc": round(float(r["2026_auc"] - ref["2026_auc"]), 5),
                "2025_top_decile_flip_pp": round(float(
                    (r["2025_top_decile_flip_rate"] - ref["2025_top_decile_flip_rate"]) * 100), 3),
                "2026_top_decile_flip_pp": round(float(
                    (r["2026_top_decile_flip_rate"] - ref["2026_top_decile_flip_rate"]) * 100), 3),
            },
            "monthly_auc_2026": months,
            "minimum_viable": mv, "minimum_viable_pass": all(mv.values()),
            "strong_preservation": sp, "strong_preservation_pass": all(sp.values()),
        }

    g50, g25 = gates["feature_sets"]["TOP50"], gates["feature_sets"]["TOP25"]
    # Preference order exactly as briefed.
    if g25["strong_preservation_pass"]:
        decision, preferred = "LONG_TOP25_SIGNAL_STRONG_PRESERVATION", "TOP25"
    elif g50["strong_preservation_pass"]:
        decision, preferred = "LONG_TOP50_SIGNAL_STRONG_PRESERVATION", "TOP50"
    elif g25["minimum_viable_pass"] or g50["minimum_viable_pass"]:
        # "materially better" is judged on the SELECTION year only (2025 AUC,
        # tie-break 2025 AP). Deliberately NOT a 2026 comparison: 2026 may act
        # only as a pre-registered pass/fail gate, never as a ranking signal
        # between candidate feature sets.
        better = (g50["minimum_viable_pass"]
                  and (g50["metrics"]["2025_auc"] - g25["metrics"]["2025_auc"] >= 0.010
                       or (abs(g50["metrics"]["2025_auc"] - g25["metrics"]["2025_auc"]) < 1e-12
                           and g50["metrics"]["2025_average_precision"]
                           > g25["metrics"]["2025_average_precision"])))
        if g25["minimum_viable_pass"] and not better:
            decision, preferred = "LONG_TOP25_SIGNAL_WEAK_BUT_USABLE", "TOP25"
        elif g50["minimum_viable_pass"]:
            decision, preferred = "LONG_TOP50_SIGNAL_WEAK_BUT_USABLE", "TOP50"
        else:
            decision, preferred = "LONG_TOP25_SIGNAL_WEAK_BUT_USABLE", "TOP25"
    else:
        # Neither viable. Distinguish "2025 looked fine, 2026 broke" from "never worked".
        held_2025 = all(gates["feature_sets"][f]["minimum_viable"]["2025_auc>=0.63"]
                        for f in ("TOP50", "TOP25"))
        failed_2026 = any(not gates["feature_sets"][f]["minimum_viable"]["2026_auc>=0.62"]
                          for f in ("TOP50", "TOP25"))
        decision = ("LONG_REDUCED_FEATURE_FAILS_2026" if held_2025 and failed_2026
                    else "LONG_TOP100_STILL_REQUIRED")
        preferred = "TOP100"

    gates["preferred_feature_set"] = preferred
    gates["decision"] = decision
    (RESULTS / "viability_gates.json").write_text(json.dumps(gates, indent=2), encoding="utf-8")

    # Final chosen model's predictions become the study's headline artifacts.
    src_tag = chosen[preferred] if preferred != "TOP100" else ref_tag
    for sp_ in ("2025", "2026"):
        pd.read_parquet(STUDY / "_work" / f"pred_{src_tag}_{sp_}.parquet").to_parquet(
            RESULTS / f"selected_model_predictions_{sp_}.parquet", index=False)

    fsm = json.load(open(RESULTS / "feature_sets_manifest.json"))
    (RESULTS / "final_decision.json").write_text(json.dumps({
        "study": "long_rth_pure_flip_top50_top25_training",
        "decision": decision,
        "preferred_feature_set": preferred,
        "selected_model": src_tag,
        "n_features": len(fsm["feature_sets"][preferred]["feature_names_in_order"])
        if preferred != "TOP100" else 100,
        "ordered_feature_list_sha256": fsm["feature_sets"][preferred]["ordered_list_sha256"],
        "headline": gates["feature_sets"].get(preferred, {}).get("metrics"),
        "top100_reference": {"2025_auc": round(float(ref["2025_auc"]), 5),
                             "2026_auc": round(float(ref["2026_auc"]), 5)},
        "top100_reproducibility": repro,
        "gates": {f: {"minimum_viable_pass": gates["feature_sets"][f]["minimum_viable_pass"],
                      "strong_preservation_pass": gates["feature_sets"][f]["strong_preservation_pass"]}
                  for f in ("TOP50", "TOP25")},
        "scope": "offline reduced-feature training only; no NautilusTrader, no MBP-1, "
                 "no surface rebuild, no trade economics, no entry/stop/exit/threshold tuning",
        "selection_discipline": "2025 AUC only (tie-break 2025 AP); 2026 sealed - "
                                "never used for fit, selection, hyperparameters, "
                                "thresholds, or calibration",
    }, indent=2), encoding="utf-8")

    print(json.dumps({f: {"mv": gates["feature_sets"][f]["minimum_viable_pass"],
                          "strong": gates["feature_sets"][f]["strong_preservation_pass"],
                          **gates["feature_sets"][f]["metrics"]}
                      for f in ("TOP50", "TOP25")}, indent=2))
    print(f"\ntop100 reproducibility: {repro}")
    print(f"DECISION: {decision}  (preferred={preferred})")


if __name__ == "__main__":
    main()

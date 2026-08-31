"""Stage 17 -- governed research decision for clean_maturity_flip_model_180s_horizon.

Binds the refreshed TRAIN freeze, the refreshed model ids, the reconciled OOS authority,
and the Stage-16 analysis identity. No new OOS optimization; no model / threshold / feature
/ target change.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
STUDY = ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"
ART = STUDY / "artifacts"
sys.path.insert(0, str(ROOT))
from research.analysis.identity import canonical_sha256  # noqa: E402
from research_workflow.oos_analysis_lineage import classify_oos_analysis  # noqa: E402


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    fr = json.loads((ART / "train_experiment_freeze.json").read_text(encoding="utf-8"))
    recon = json.loads((ART / "oos_lineage_reconciliation.json").read_text(encoding="utf-8"))
    authority = json.loads((ART / "oos_reconciled_authority.json").read_text(encoding="utf-8"))
    analysis = json.loads((ART / "experiment_analysis.json").read_text(encoding="utf-8"))
    tp = json.loads((ART / "two_phase_selection_dispatch_summary.json").read_text(encoding="utf-8"))
    ct = json.loads((ART / "oos_2024_classification_timing.json").read_text(encoding="utf-8"))
    ep = json.loads((ART / "oos_2024_economic_path.json").read_text(encoding="utf-8"))
    march = json.loads((STUDY / "validation_march2024" / "REGIME_LEVEL_SCORE_DIAGNOSTIC.json").read_text(encoding="utf-8"))
    seal = json.loads((ART / "preexec_audit_seal.json").read_text(encoding="utf-8"))
    fm = json.loads((STUDY / "audit" / "frozen_execution_manifest.json").read_text(encoding="utf-8"))

    a16 = classify_oos_analysis(STUDY)
    if a16["state"] != "FRESH":
        raise SystemExit(f"Stage-16 analysis is not FRESH: {a16}")

    long_l = ct["LONG"]["classification_180s"]
    short_l = ct["SHORT"]["classification_180s"]
    long_p = ct["LONG"]["classification_300s_parent_benchmark"]
    short_p = ct["SHORT"]["classification_300s_parent_benchmark"]
    ff_long = march["PART_2_first_eligible_per_regime"]["LONG"]

    decision = {
        "schema_version": 1,
        "artifact_kind": "research_decision_stage17",
        "stage": 17,
        "study_id": "clean_maturity_flip_model_180s_horizon",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_question": ("Does shortening the Stage-1 imminent-flip prediction horizon "
                              "300s -> 180s improve flip-prediction precision/discrimination "
                              "AND the economic quality of high-confidence predictions, while "
                              "preserving favorable-excursion opportunity?"),

        # ---- bound lineage ----
        "bound_lineage": {
            "execution_composite_sha256": fm["frozen_execution_composite_sha256"],
            "preexec_seal_composite_sha256": seal["composite_seal_hash"],
            "preexec_seal_artifact_sha256": _sha(ART / "preexec_audit_seal.json"),
            "refreshed_train_freeze_sha256": fr["freeze_sha256"],
            "refreshed_model_ids": {r["model_role"]: r["model_id"] for r in fr["model_artifacts"]},
            "modeling_execution_closure_sha256": fr["stage_scoped_lineage"]["MODELING_EXECUTION_CLOSURE"],
            "authorization_sha256": fr["authorization_sha256"],
            "oos_reconciled_authority_identity_sha256": authority["authority_identity_sha256"],
            "oos_lineage_reconciliation_identity_sha256": recon["reconciliation_identity_sha256"],
            "stage16_analysis_identity_sha256": analysis["oos_analysis_identity"]["identity_sha256"],
            "stage16_analysis_artifact_file_sha256": _sha(ART / "experiment_analysis.json"),
            "stage16_lineage_state": a16["state"],
            "causal_audit": recon["refreshed_lineage"]["causal_audit"],
            "contract_audit": recon["refreshed_lineage"]["contract_audit"],
        },

        # ---- architecture / selection outcome (per direction) ----
        "selection_outcome": {
            "LONG": {"status": tp["LONG"]["status"], "winning_arm": tp["LONG"]["winning_arm"],
                     "final_validation_2023": tp["LONG"]["final_validation_status"],
                     "tuned_hyperparameters": tp["LONG"]["tuned_hyperparameters"]},
            "SHORT": {"status": tp["SHORT"]["status"], "winning_arm": tp["SHORT"]["winning_arm"],
                      "final_validation_2023": tp["SHORT"]["final_validation_status"],
                      "tuned_hyperparameters": tp["SHORT"]["tuned_hyperparameters"]},
            "concordant": tp["LONG"]["winning_arm"] == tp["SHORT"]["winning_arm"]
                          and tp["LONG"]["status"] == tp["SHORT"]["status"] == "PASS_DIRECTION",
        },

        # ---- 2024 OOS evidence (preserved, reconciled, delta 0.0) ----
        "oos_2024_evidence": {
            "reconciliation_decision": recon["reconciliation_decision"],
            "predict_proba_max_abs_delta_over_full_2024_oos":
                recon["equivalence_proofs"]["predictions"]["predict_proba_max_abs_delta_over_full_2024_oos"],
            "checkpoint_level_classification": {
                "LONG_C_180s": {"roc_auc": long_l["roc_auc"], "pr_auc": long_l["pr_auc"],
                                "pr_auc_over_base": long_l["pr_auc_over_base_rate"],
                                "brier": long_l["brier"]},
                "LONG_300s_parent": {"roc_auc": long_p["roc_auc"], "pr_auc": long_p["pr_auc"],
                                     "pr_auc_over_base": long_p["pr_auc_over_base_rate"]},
                "SHORT_C_180s": {"roc_auc": short_l["roc_auc"], "pr_auc": short_l["pr_auc"],
                                 "pr_auc_over_base": short_l["pr_auc_over_base_rate"],
                                 "brier": short_l["brier"]},
                "SHORT_300s_parent": {"roc_auc": short_p["roc_auc"], "pr_auc": short_p["pr_auc"],
                                      "pr_auc_over_base": short_p["pr_auc_over_base_rate"]},
                "roc_auc_delta_180s_minus_300s": {
                    "LONG": round(long_l["roc_auc"] - long_p["roc_auc"], 4),
                    "SHORT": round(short_l["roc_auc"] - short_p["roc_auc"], 4),
                },
                "relationship_replicates_train_to_oos": True,
            },
            "first_fire_regime_level_march2024": {
                "LONG_roc_auc": ff_long["roc_auc"], "LONG_pr_auc_over_base": ff_long["pr_auc_over_base_rate"],
                "interpretation": "first-eligible-per-regime discrimination is at / near chance",
            },
            "economic_path_frozen_tail_p90": {
                "LONG_180s_return_atr_mean": ep["p90"]["LONG"]["summary_180s"]["return_atr_180s_mean"],
                "LONG_180s_mfe_atr_mean": ep["p90"]["LONG"]["summary_180s"]["mfe_atr_180s_mean"],
                "LONG_300s_return_atr_mean": ep["p90"]["LONG"]["summary_180s"]["return_atr_300s_mean"],
                "LONG_180s_1to1_success_rate": ep["p90"]["LONG"]["summary_180s"].get("one_to_one_success_rate"),
                "interpretation": "return_atr ~ 0 for both horizons; 180s truncates ~0.25 ATR "
                                  "of eventual favourable excursion",
            },
        },

        # ---- terminal decision ----
        "terminal_decision": "MIXED",
        "terminal_decision_axes": {
            "architecture_selection": "PASS both directions at arm C "
                                      "(BASELINE_PLUS_STRUCTURAL_PLUS_ROLLING_5M); concordant; "
                                      "neither direction hit the 2023 reject-only D gate.",
            "classification_discrimination": "IMPROVED and OOS-REPLICATED -- 180s checkpoint-level "
                                             "ROC-AUC is +0.05 (LONG) / +0.046 (SHORT) over the "
                                             "frozen 300s parent on 2024, and the TRAIN->OOS "
                                             "relationship replicates (March 2024 checkpoint "
                                             "ROC-AUC ~0.70/0.67 consistent).",
            "economic_quality_and_opportunity": "NOT ESTABLISHED -- at the frozen P90 tail the "
                                                "2024 forward path return_atr is ~0 for both "
                                                "horizons, and the regime-level / first-fire "
                                                "signal is at chance (ROC-AUC ~0.50). The "
                                                "classification gain does not translate to a "
                                                "monetizable or actionable edge.",
        },
        "terminal_answer_to_research_question": (
            "PARTIAL. The 180s horizon produces a measurably better flip-prediction CLASSIFIER "
            "(discrimination, calibration, tail precision, time-to-flip) and that improvement "
            "replicates out-of-sample. It does NOT improve the economic quality of "
            "high-confidence predictions and the actionable first-fire signal remains at "
            "chance -- so the compound research question (classifier AND economics) is not "
            "satisfied."
        ),
        "promotion": "NOT PROMOTED",
        "promotion_rationale": (
            "Consistent with this study family: high checkpoint-level AUC does not equal PnL "
            "discrimination; the frozen 180s models are a real but non-monetizable diagnostic "
            "result. No deployment / strategy step is warranted on this evidence."
        ),
        "prohibited_and_not_done": ["new_2024_collection", "new_2024_scoring", "model_change",
                                    "threshold_recomputation", "tuning", "feature_change",
                                    "target_change", "new_oos_optimization"],
        "next_research_decision": (
            "If the economic axis is to be pursued, it requires a SEPARATE, separately-frozen "
            "Study-2/Study-3 (economic-quality target, e.g. P(clean reversal) / E[MFE] / "
            "target-before-stop) -- not a modification of this classifier."
        ),
    }
    decision["decision_identity_sha256"] = canonical_sha256(
        {k: decision[k] for k in decision if k != "generated_at_utc"}
    )

    out = ART / "research_decision_stage17.json"
    out.write_text(json.dumps(decision, indent=2, default=str) + "\n", encoding="utf-8")

    # narrative
    results = STUDY / "results"
    results.mkdir(exist_ok=True)
    report = f"""# STUDY REPORT -- clean_maturity_flip_model_180s_horizon

**Stage 17 research decision.**  Execution composite `{fm['frozen_execution_composite_sha256']}` ·
seal LOCKED · causal pass {recon['refreshed_lineage']['causal_audit']['pass']} + contract pass
{recon['refreshed_lineage']['contract_audit']['pass']} CLEAR.

## Lineage

| | |
|---|---|
| refreshed TRAIN freeze | `{fr['freeze_sha256']}` |
| LONG_C model_id | `{decision['bound_lineage']['refreshed_model_ids']['LONG_C']}` |
| SHORT_C model_id | `{decision['bound_lineage']['refreshed_model_ids']['SHORT_C']}` |
| modeling execution closure | `{fr['stage_scoped_lineage']['MODELING_EXECUTION_CLOSURE']}` |
| authorization | `{fr['authorization_sha256']}` (unchanged) |
| OOS reconciliation identity | `{recon['reconciliation_identity_sha256']}` |
| OOS reconciled authority identity | `{authority['authority_identity_sha256']}` |
| Stage-16 analysis identity | `{analysis['oos_analysis_identity']['identity_sha256']}` ({a16['state']}) |

The 2024 OOS run predates the Red-Team Pass 1 framework merge / driver declaration. Its
outputs were proven **numerically identical** under the refreshed lineage (predict_proba
delta 0.0 over all 450,973 rows; identical model bytes, thresholds, features, target,
authorization) and reused via `oos_lineage_reconciliation.json` -- no recollection, no
rescoring. Historical OOS artifacts were not mutated.

## Result

**Selection:** LONG and SHORT both PASS at arm C
(`BASELINE_PLUS_STRUCTURAL_PLUS_ROLLING_5M`); concordant; neither hit the 2023 reject-only
D gate.

**Classification (primary axis) -- IMPROVED, OOS-replicated.** 2024 checkpoint-level:
LONG_C ROC-AUC {long_l['roc_auc']:.4f} / PR-AUC {long_l['pr_auc']:.4f}
({long_l['pr_auc_over_base_rate']:.2f}x base) vs frozen 300s parent {long_p['roc_auc']:.4f} /
{long_p['pr_auc']:.4f}; SHORT_C {short_l['roc_auc']:.4f} / {short_l['pr_auc']:.4f}
({short_l['pr_auc_over_base_rate']:.2f}x base) vs {short_p['roc_auc']:.4f} /
{short_p['pr_auc']:.4f}. ROC-AUC delta 180s-300s: LONG +{long_l['roc_auc']-long_p['roc_auc']:.4f},
SHORT +{short_l['roc_auc']-short_p['roc_auc']:.4f}; the TRAIN->OOS relationship replicates.
Calibration ECE < 0.01 (LONG).

**Economics / actionable signal (secondary axis) -- NOT ESTABLISHED.** At the frozen P90
tail the 2024 forward-path `return_atr` is ~0 for both 180s and 300s; the 180s window
truncates ~0.25 ATR of eventual favourable excursion. The regime-level / first-fire signal
(March 2024, first-eligible-per-regime) is at chance: LONG ROC-AUC
{ff_long['roc_auc']:.4f}.

## Terminal decision: **MIXED**

The 180s horizon delivers a real, out-of-sample-replicated **classifier** improvement but
**no economic or actionable improvement**. The compound research question (better classifier
*and* better economics) is not satisfied.

**Not promoted.** High checkpoint-level AUC != PnL discrimination; the frozen 180s models
are a non-monetizable diagnostic result. Any pursuit of the economic axis needs a separate,
separately-frozen Study 2/3 against an economic-quality target -- not a change to this
classifier.

## Not done (prohibited)

No new 2024 collection, no new 2024 scoring, no model / threshold / feature / target change,
no new OOS optimization. 2025/2026 not accessed.
"""
    (results / "STUDY_REPORT.md").write_text(report, encoding="utf-8")

    print(json.dumps({
        "status": "STAGE17_DECISION_WRITTEN",
        "artifact": "artifacts/research_decision_stage17.json",
        "artifact_file_sha256": _sha(out),
        "decision_identity_sha256": decision["decision_identity_sha256"],
        "report": "results/STUDY_REPORT.md",
        "report_sha256": _sha(results / "STUDY_REPORT.md"),
        "terminal_decision": decision["terminal_decision"],
        "promotion": decision["promotion"],
    }, indent=2))


if __name__ == "__main__":
    main()

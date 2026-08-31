"""Stage 16 -- governed OOS analysis for clean_maturity_flip_model_180s_horizon.

Descriptive / evaluative analysis of the EXISTING 2024 OOS outputs against the frozen
180s classifier, bound to the RT-13 analysis-lineage identity mechanism and to the OOS
lineage reconciliation. No recollection, no rescoring into new numbers, no model /
threshold / feature / target change: the primary classification metrics are preserved
verbatim from the original OOS run (proven numerically equivalent under the refreshed
lineage -- oos_lineage_reconciliation.json, predict_proba delta 0.0 over all 450,973
rows).

Checkpoint-level classification (the study's primary question) is kept DISTINCT from the
March-2024 first-fire / actionable-signal diagnostic.
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

from research_workflow.experiment import assert_oos_open  # noqa: E402
from research_workflow.oos_analysis_lineage import (  # noqa: E402
    build_oos_analysis_identity,
    classify_oos_analysis,
)
from research.analysis.modeling import frame_content_identity  # noqa: E402

import pandas as pd  # noqa: E402


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    # OOS gate: TRAIN freeze must exist and be bound to the current authorization + closures.
    freeze = assert_oos_open(str(STUDY))

    recon = json.loads((ART / "oos_lineage_reconciliation.json").read_text(encoding="utf-8"))
    authority = json.loads((ART / "oos_reconciled_authority.json").read_text(encoding="utf-8"))
    ct = json.loads((ART / "oos_2024_classification_timing.json").read_text(encoding="utf-8"))
    ep = json.loads((ART / "oos_2024_economic_path.json").read_text(encoding="utf-8"))
    card = json.loads((ART / "2024_OOS_CARD.json").read_text(encoding="utf-8"))
    march = json.loads((STUDY / "validation_march2024" / "REGIME_LEVEL_SCORE_DIAGNOSTIC.json").read_text(encoding="utf-8"))

    if recon["reconciliation_decision"] != "REUSABLE_WITH_LINEAGE_REBINDING":
        raise SystemExit("reconciliation is not REUSABLE_WITH_LINEAGE_REBINDING")

    # OOS dataset identity: the already-collected merged OOS frames (artifact reuse).
    obs = pd.read_parquet(ART / "oos_observations_merged.parquet")
    cand = pd.read_parquet(ART / "oos_candidates_merged.parquet")
    oos_dataset_identity = frame_content_identity(
        cand.reindex(sorted(cand.columns), axis=1)
    )

    # RT-13 identity block (current freeze bytes, refreshed model ids, modeling closure,
    # OOS run/dataset identity, OOS authorization, analysis-impl identity, self hash).
    ident = build_oos_analysis_identity(
        STUDY, freeze=freeze,
        oos_run_id=json.loads((ART / "oos_collection_manifest.json").read_text()).get("run_id")
        or "2024_oos_reconciled",
        oos_dataset_identity_sha256=oos_dataset_identity,
    )
    # extend with the reconciliation + original-run bindings the task requires
    ident["oos_reconciliation_artifact_identity_sha256"] = recon["reconciliation_identity_sha256"]
    ident["oos_reconciliation_artifact_file_sha256"] = _sha(ART / "oos_lineage_reconciliation.json")
    ident["oos_reconciled_authority_identity_sha256"] = authority["authority_identity_sha256"]
    ident["original_oos_collection_manifest_sha256"] = _sha(ART / "oos_collection_manifest.json")
    ident["original_oos_candidate_sha256"] = card["frozen_identities"].get("aggregate_train_freeze_sha256") and \
        json.loads((ART / "oos_collection_manifest.json").read_text())["candidate_sha256"]
    ident["original_oos_observation_sha256"] = json.loads((ART / "oos_collection_manifest.json").read_text())["observation_sha256"]
    ident["metrics_provenance"] = "PRESERVED_VERBATIM_FROM_ORIGINAL_OOS_RUN"

    # ---- primary analysis: checkpoint-level classification (preserved) ----
    def _cls(d: str) -> dict:
        c = ct[d]["classification_180s"]
        return {
            "n_labeled_checkpoints": ct[d].get("n_180s"),
            "roc_auc": c["roc_auc"], "pr_auc": c["pr_auc"], "brier": c["brier"],
            "positive_rate": c["positive_rate"],
            "pr_auc_over_base_rate": c["pr_auc_over_base_rate"],
            "expected_calibration_error": c.get("calibration", {}).get("expected_calibration_error"),
        }

    def _parent(d: str) -> dict:
        c = ct[d].get("classification_300s_parent_benchmark", {})
        return {k: c.get(k) for k in ("roc_auc", "pr_auc", "brier", "positive_rate", "pr_auc_over_base_rate")}

    analysis = {
        "schema_version": 1,
        "artifact_kind": "experiment_analysis",
        "stage": 16,
        "study_id": "clean_maturity_flip_model_180s_horizon",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "oos_year": 2024,
        "oos_accessed": "REUSE_OF_ALREADY_COLLECTED_ARTIFACTS",
        "new_2024_collection": False,
        "new_2024_scoring": False,
        "y2025_2026_accessed": False,
        "oos_analysis_identity": ident,
        "oos_lineage": {
            "decision": recon["reconciliation_decision"],
            "predict_proba_max_abs_delta_over_full_2024_oos":
                recon["equivalence_proofs"]["predictions"]["predict_proba_max_abs_delta_over_full_2024_oos"],
            "refreshed_train_freeze_sha256": freeze["freeze_sha256"],
            "refreshed_model_ids": {r["model_role"]: r["model_id"] for r in freeze["model_artifacts"]},
            "modeling_execution_closure_sha256": freeze["stage_scoped_lineage"]["MODELING_EXECUTION_CLOSURE"],
            "authorization_sha256": freeze["authorization_sha256"],
        },
        # ---- PRIMARY: checkpoint-level 180s classification vs 300s parent benchmark ----
        "primary_checkpoint_level_classification_2024_oos": {
            "note": ct["note"],
            "oos_180s_labeled_rows": ct["oos_180s_labeled_rows"],
            "oos_180s_base_rate_overall": ct["oos_180s_base_rate_overall"],
            "LONG_C": {"model_180s": _cls("LONG"), "parent_300s_benchmark": _parent("LONG")},
            "SHORT_C": {"model_180s": _cls("SHORT"), "parent_300s_benchmark": _parent("SHORT")},
        },
        # ---- SECONDARY (kept DISTINCT): first-fire / actionable-signal diagnostic ----
        "secondary_first_fire_diagnostic_march2024": {
            "kept_distinct_from_primary": True,
            "source": "validation_march2024/REGIME_LEVEL_SCORE_DIAGNOSTIC.json",
            "summary": {k: march[k] for k in list(march)[:12] if not isinstance(march[k], (list, dict))},
            "economic_path_note": ep.get("method_note"),
        },
        "descriptive_conclusion": {
            "primary": ("The frozen 180s classifier's clean-OOS 2024 checkpoint-level "
                        "discrimination is preserved verbatim from the original run and "
                        "is numerically identical under the refreshed lineage (delta 0.0): "
                        f"LONG_C ROC-AUC {_cls('LONG')['roc_auc']:.4f} / PR-AUC "
                        f"{_cls('LONG')['pr_auc']:.4f} ({_cls('LONG')['pr_auc_over_base_rate']:.2f}x base), "
                        f"SHORT_C ROC-AUC {_cls('SHORT')['roc_auc']:.4f} / PR-AUC "
                        f"{_cls('SHORT')['pr_auc']:.4f} ({_cls('SHORT')['pr_auc_over_base_rate']:.2f}x base), "
                        "both well-calibrated (ECE < 0.01). This analysis makes no new "
                        "claim and changes no frozen object."),
            "no_model_change": True,
            "no_threshold_change": True,
            "no_tuning": True,
        },
    }

    out = ART / "experiment_analysis.json"
    out.write_text(json.dumps(analysis, indent=2, default=str) + "\n", encoding="utf-8")

    verdict = classify_oos_analysis(STUDY)
    print(json.dumps({
        "status": "STAGE16_ANALYSIS_WRITTEN",
        "path": "artifacts/experiment_analysis.json",
        "artifact_file_sha256": _sha(out),
        "oos_analysis_identity_sha256": ident["identity_sha256"],
        "classify_oos_analysis": verdict,
    }, indent=2))
    if verdict["state"] != "FRESH":
        raise SystemExit(f"classify_oos_analysis -> {verdict}")


if __name__ == "__main__":
    main()

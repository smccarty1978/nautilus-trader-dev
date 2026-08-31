"""Derived 'current OOS authority' view for clean_maturity_flip_model_180s_horizon.

Does NOT mutate historical OOS evidence. Points Stage 16/17 at:
  - the ORIGINAL 2024 OOS collection/result artifacts (unchanged), and
  - the reconciliation artifact that proves they are reusable under the refreshed
    TRAIN/model lineage.

Meaning: "The historical 2024 OOS outputs are AUTHORIZED FOR REUSE under the refreshed
lineage because equivalence has been proven." NOT "the historical OOS run was produced
under the refreshed lineage."
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


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    recon = json.loads((ART / "oos_lineage_reconciliation.json").read_text(encoding="utf-8"))
    fr = json.loads((ART / "train_experiment_freeze.json").read_text(encoding="utf-8"))
    fm = json.loads((STUDY / "audit" / "frozen_execution_manifest.json").read_text(encoding="utf-8"))
    seal = json.loads((ART / "preexec_audit_seal.json").read_text(encoding="utf-8"))

    if recon["reconciliation_decision"] != "REUSABLE_WITH_LINEAGE_REBINDING":
        raise SystemExit(f"reconciliation decision is {recon['reconciliation_decision']!r}, not reusable")
    if not all(v["pass"] for v in recon["equivalence_proofs"].values()):
        raise SystemExit("reconciliation equivalence proofs did not all pass")

    body = {
        "schema_version": 1,
        "artifact_kind": "oos_reconciled_authority",
        "study_id": "clean_maturity_flip_model_180s_horizon",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "meaning": ("The historical 2024 OOS outputs are AUTHORIZED FOR REUSE as the "
                    "governed OOS evidence under the refreshed TRAIN/model lineage, because "
                    "numeric equivalence is proven in the reconciliation artifact. This is "
                    "NOT a claim that the historical OOS run was originally produced under "
                    "the refreshed lineage."),
        "oos_year": 2024,
        "no_new_2024_collection": True,
        "no_new_2024_scoring": True,
        "historical_oos_artifacts_mutated": False,
        # ---- the ORIGINAL OOS evidence this authority view points at (unchanged) ----
        "original_oos_artifacts": {
            "oos_candidates_merged": {"path": "artifacts/oos_candidates_merged.parquet",
                                      "sha256": _sha(ART / "oos_candidates_merged.parquet")},
            "oos_observations_merged": {"path": "artifacts/oos_observations_merged.parquet",
                                        "sha256": _sha(ART / "oos_observations_merged.parquet")},
            "oos_collection_manifest": {"path": "artifacts/oos_collection_manifest.json",
                                        "sha256": _sha(ART / "oos_collection_manifest.json")},
            "oos_2024_classification_timing": {"path": "artifacts/oos_2024_classification_timing.json",
                                               "sha256": _sha(ART / "oos_2024_classification_timing.json")},
            "oos_2024_economic_path": {"path": "artifacts/oos_2024_economic_path.json",
                                       "sha256": _sha(ART / "oos_2024_economic_path.json")},
            "card_2024_oos": {"path": "artifacts/2024_OOS_CARD.json",
                              "sha256": _sha(ART / "2024_OOS_CARD.json")},
            "oos_unlock": {"path": "artifacts/oos_unlock.json",
                           "sha256": _sha(ART / "oos_unlock.json")},
        },
        "original_oos_lineage_as_run": {
            "train_freeze_sha256": recon["prior_lineage"]["train_freeze_sha256"],
            "model_ids": recon["prior_lineage"]["model_ids"],
            "execution_composite_sha256": recon["prior_lineage"]["execution_composite_sha256"],
            "stage_scoped_lineage": recon["prior_lineage"]["stage_scoped_lineage"],
        },
        # ---- the reconciliation that authorizes reuse ----
        "reconciliation": {
            "path": "artifacts/oos_lineage_reconciliation.json",
            "artifact_file_sha256": _sha(ART / "oos_lineage_reconciliation.json"),
            "reconciliation_identity_sha256": recon["reconciliation_identity_sha256"],
            "decision": recon["reconciliation_decision"],
            "predict_proba_max_abs_delta_over_full_2024_oos":
                recon["equivalence_proofs"]["predictions"]["predict_proba_max_abs_delta_over_full_2024_oos"],
        },
        # ---- the refreshed lineage the OOS evidence is now bound to ----
        "refreshed_lineage": {
            "execution_composite_sha256": fm["frozen_execution_composite_sha256"],
            "preexec_seal_composite_sha256": seal["composite_seal_hash"],
            "preexec_seal_artifact_sha256": _sha(ART / "preexec_audit_seal.json"),
            "train_freeze_sha256": fr["freeze_sha256"],
            "model_ids": {r["model_role"]: r["model_id"] for r in fr["model_artifacts"]},
            "model_artifact_sha256": {r["model_role"]: r["artifact_sha256"] for r in fr["model_artifacts"]},
            "preprocessing_hash": fr["preprocessing_hash"],
            "thresholds": fr["thresholds"],
            "stage_scoped_lineage": fr["stage_scoped_lineage"],
            "authorization_sha256": fr["authorization_sha256"],
            "causal_audit": recon["refreshed_lineage"]["causal_audit"],
            "contract_audit": recon["refreshed_lineage"]["contract_audit"],
        },
        "authorized_for": ["stage_16_analysis", "stage_17_decision"],
        "prohibited": ["new_2024_collection", "new_2024_scoring", "model_change",
                       "threshold_change", "tuning", "feature_change", "target_change"],
    }
    body["authority_identity_sha256"] = canonical_sha256(
        {k: body[k] for k in body if k != "generated_at_utc"}
    )
    out = ART / "oos_reconciled_authority.json"
    out.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "OOS_RECONCILED_AUTHORITY_WRITTEN",
        "path": "artifacts/oos_reconciled_authority.json",
        "authority_identity_sha256": body["authority_identity_sha256"],
        "artifact_file_sha256": _sha(out),
    }, indent=2))


if __name__ == "__main__":
    main()

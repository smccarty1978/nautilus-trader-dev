"""Terminal closure for clean_maturity_flip_model_180s_horizon.

Writes artifacts/study_closure.json binding the full terminal evidence chain, then
verifies WorkflowEngine.advance() -> STUDY_CLOSED. Terminal-record only: no data access,
no recollection, no rescoring, no re-analysis. Does not mutate any historical artifact or
any model.
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
    fm = json.loads((STUDY / "audit" / "frozen_execution_manifest.json").read_text(encoding="utf-8"))
    seal = json.loads((ART / "preexec_audit_seal.json").read_text(encoding="utf-8"))
    causal = json.loads((STUDY / "audit" / "status.json").read_text(encoding="utf-8"))
    contract = json.loads((STUDY / "audit" / "contract_status.json").read_text(encoding="utf-8"))
    fr = json.loads((ART / "train_experiment_freeze.json").read_text(encoding="utf-8"))
    recon = json.loads((ART / "oos_lineage_reconciliation.json").read_text(encoding="utf-8"))
    authority = json.loads((ART / "oos_reconciled_authority.json").read_text(encoding="utf-8"))
    analysis = json.loads((ART / "experiment_analysis.json").read_text(encoding="utf-8"))
    decision = json.loads((ART / "research_decision_stage17.json").read_text(encoding="utf-8"))

    assert causal["pass"] == 17 and causal["verdict"] == "CLEAR"
    assert contract["pass"] == 16 and contract["verdict"] == "CLEAR"
    assert decision["terminal_decision"] == "MIXED" and decision["promotion"] == "NOT PROMOTED"

    model_ids = {r["model_role"]: r["model_id"] for r in fr["model_artifacts"]}
    model_status = {}
    for arm, mid in model_ids.items():
        rec = json.loads((ROOT / "studies" / "model_registry" / f"{mid}.json").read_text())
        model_status[arm] = {
            "model_id": mid,
            "preserved": True,
            "artifact_status": rec["artifact_status"],
            "scientific_status_registry": rec["scientific_status"],
            "reuse_status_registry": rec["reuse_status"],
            "score_semantics": rec["score_semantics"],
            "ordered_model_inputs_count": len(rec["ordered_model_inputs"]),
            "native_booster_present": "native_booster_path" in rec,
            "artifact_sha256": next(r["artifact_sha256"] for r in fr["model_artifacts"] if r["model_role"] == arm),
            "golden_fixture_sha256": next(r["golden_fixture_sha256"] for r in fr["model_artifacts"] if r["model_role"] == arm),
        }

    body = {
        "schema_version": 1,
        "study_id": "clean_maturity_flip_model_180s_horizon",
        "status": "CLOSED",
        "outcome": "DIAGNOSTIC_NEGATIVE",
        "terminal_decision": "MIXED",
        "closed_at_utc": datetime.now(timezone.utc).isoformat(),

        # ---- terminal evidence chain ----
        "bound_evidence": {
            "execution_composite_sha256": fm["frozen_execution_composite_sha256"],
            "preexec_seal_status": seal["seal_status"],
            "preexec_seal_composite_sha256": seal["composite_seal_hash"],
            "preexec_seal_artifact_sha256": _sha(ART / "preexec_audit_seal.json"),
            "causal_audit": {"pass": causal["pass"], "verdict": causal["verdict"],
                             "report": causal["audit_report_path"],
                             "report_sha256": causal["audit_report_sha256"],
                             "auditor": causal["auditor"]},
            "contract_audit": {"pass": contract["pass"], "verdict": contract["verdict"],
                               "report": contract["audit_report_path"],
                               "report_sha256": contract["audit_report_sha256"],
                               "auditor": contract["auditor"]},
            "train_freeze_sha256": fr["freeze_sha256"],
            "refreshed_model_ids": model_ids,
            "modeling_execution_closure_sha256": fr["stage_scoped_lineage"]["MODELING_EXECUTION_CLOSURE"],
            "authorization_sha256": fr["authorization_sha256"],
            "oos_lineage_reconciliation": {
                "path": "artifacts/oos_lineage_reconciliation.json",
                "identity_sha256": recon["reconciliation_identity_sha256"],
                "artifact_file_sha256": _sha(ART / "oos_lineage_reconciliation.json"),
                "decision": recon["reconciliation_decision"],
            },
            "oos_reconciled_authority": {
                "path": "artifacts/oos_reconciled_authority.json",
                "identity_sha256": authority["authority_identity_sha256"],
                "artifact_file_sha256": _sha(ART / "oos_reconciled_authority.json"),
            },
            "stage16_analysis": {
                "path": "artifacts/experiment_analysis.json",
                "identity_sha256": analysis["oos_analysis_identity"]["identity_sha256"],
                "artifact_file_sha256": _sha(ART / "experiment_analysis.json"),
                "lineage_state": "FRESH",
            },
            "stage17_research_decision": {
                "path": "artifacts/research_decision_stage17.json",
                "identity_sha256": decision["decision_identity_sha256"],
                "artifact_file_sha256": _sha(ART / "research_decision_stage17.json"),
            },
            "final_report": {
                "path": "results/STUDY_REPORT.md",
                "sha256": _sha(STUDY / "results" / "STUDY_REPORT.md"),
            },
        },

        # ---- research interpretation (terminal) ----
        "research_interpretation": {
            "classification_axis": "PASS / OOS-REPLICATED -- the 180s Model C classifier "
                                   "improves checkpoint-level discrimination vs the frozen "
                                   "300s parent (ROC-AUC +0.05 LONG / +0.046 SHORT on 2024) "
                                   "and that improvement replicates out of sample.",
            "economic_actionable_axis": "NOT ESTABLISHED -- first-fire / regime-level "
                                        "discrimination is ~chance (ROC-AUC ~0.50) and the "
                                        "frozen P90-tail 2024 economic return is ~0.",
            "overall": "A diagnostic classifier improvement exists but does not produce "
                       "demonstrated monetizable first-fire discrimination. The 180s models "
                       "are retained as valid diagnostic classifiers; the horizon change is "
                       "NOT promoted as an actionable trading signal.",
        },

        # ---- model disposition ----
        "models": model_status,
        "model_scientific_assessment": {
            "assessment": "VALID_DIAGNOSTIC",
            "rationale": "Valid target and valid model with negative economics. The frozen "
                         "180s Model C classifiers are scientifically useful diagnostic "
                         "models (real, OOS-replicated checkpoint-level discrimination); "
                         "they are explicitly NOT INVALID_TARGET.",
            "registry_scientific_status_value": "UNASSESSED",
            "capability_note": "There is no governed function to assign scientific_status "
                               "on an existing model_registry record (persist_models "
                               "writes UNASSESSED; register_historical_model is for "
                               "byte-registering a different id). This closure is the "
                               "authoritative diagnostic assessment. The registry records "
                               "remain UNASSESSED + reuse_status PERMITTED, which passes "
                               "the RT-09 derived-input reuse gate (UNASSESSED is 'not "
                               "flagged invalid'); VALID_DIAGNOSTIC reuse-as-derived-input "
                               "additionally requires an explicit policy.",
            "reuse_policy": "Discoverable for future GOVERNED derived-input use if a child "
                            "study's reuse policy explicitly permits diagnostic-derived "
                            "input (research_workflow.model_artifacts."
                            "assert_scientific_status_reusable). Never as a primary target.",
        },

        # ---- explicit prohibitions ----
        "authorized_further_work": [],
        "prohibited": [
            "promotion of this classifier to a strategy / deployment",
            "further classifier tuning",
            "threshold / P90 modification",
            "further 2024 optimization",
            "OOS threshold search",
            "any rescue attempt on this study",
            "new 2024 / 2025 / 2026 data access",
        ],
        "further_economic_research_requires": (
            "a SEPARATE study with a SEPARATELY-frozen research_decision.yaml against an "
            "economic-quality target/objective (e.g. P(clean reversal) / E[MFE] / "
            "target-before-stop) -- NOT continued work on this classifier."
        ),
        "no_governed_reopen_path": True,
    }
    body["closure_identity_sha256"] = canonical_sha256(
        {k: body[k] for k in body if k != "closed_at_utc"}
    )

    out = ART / "study_closure.json"
    out.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")

    # ---- validate + workflow terminal check ----
    from research_workflow.study_closure import load_study_closure, closure_artifact_sha256
    loaded = load_study_closure(STUDY)
    assert loaded is not None and loaded["status"] == "CLOSED"

    from research_workflow.workflow_engine import WorkflowEngine
    state = WorkflowEngine(STUDY).advance()

    print(json.dumps({
        "status": "STUDY_CLOSED_WRITTEN",
        "artifact": "artifacts/study_closure.json",
        "artifact_file_sha256": _sha(out),
        "closure_canonical_file_sha256": closure_artifact_sha256(STUDY),
        "closure_identity_sha256": body["closure_identity_sha256"],
        "validated": True,
        "workflow_terminal_state": state["terminal_state"],
        "workflow_next_deterministic_action": state["next_deterministic_action"],
        "workflow_closure_summary": {k: state.get(k) for k in
                                     ("study_id", "status", "outcome", "terminal_decision")
                                     if k in state},
    }, indent=2))

    if state["terminal_state"] != "STUDY_CLOSED" or state["next_deterministic_action"] is not None:
        raise SystemExit(f"workflow did not reach STUDY_CLOSED terminal: {state['terminal_state']} / "
                         f"{state['next_deterministic_action']}")


if __name__ == "__main__":
    main()

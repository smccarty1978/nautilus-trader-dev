#!/usr/bin/env python3
"""Idempotent pre-study capability reconciliation orchestrator."""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *cmd], cwd=ROOT, check=True, capture_output=True, text=True)

def reconcile(study: Path) -> dict:
    # Deterministic inventory and evidence refresh.  Each command is safe to
    # repeat; a changed closure naturally regenerates the downstream artifacts.
    run(["scripts/materialize_feature_candidate.py"])
    try:
        run(["scripts/prepare_feature_candidate.py", "--study", str(study)])
    except subprocess.CalledProcessError as exc:
        err_msg = exc.stderr or exc.stdout or str(exc)
        if "CANDIDATE_PROVIDER_UNRESOLVED" in err_msg or "UnresolvedDependencyError" in err_msg:
            return {"state": "IMPLEMENTATION_REQUIRED", "error": "CANDIDATE_PROVIDER_UNRESOLVED", "detail": err_msg.strip()}
        raise
    run(["scripts/research_preflight.py", "--study", str(study), "--feature-authority", "candidate", "--skip-tests"])
    from research_workflow.causal_audit import run_causal_review
    from research_workflow.contract_audit import run_contract_review
    if run_causal_review(study).get("status") != "CLEAR": return {"state":"SAFETY_OR_AUTHORIZATION_BLOCK"}
    if run_contract_review(study).get("status") != "CLEAR": return {"state":"SAFETY_OR_AUTHORIZATION_BLOCK"}
    run(["scripts/materialize_scoped_promotions.py", "--study", str(study), "--out", "features/feature_scoped_promotions.json"])
    from scripts.check_feature_promotion import check_scoped_promotions
    checked = check_scoped_promotions()
    if not checked["passed"]: return {"state":"IMPLEMENTATION_REQUIRED", "promotion":checked}
    from research_workflow.seal import generate_preexec_audit_seal
    seal = generate_preexec_audit_seal(study)
    # Apply only explicitly recorded FEATURE_DEFINITION scopes to the generated
    # candidate bundle, then atomically regenerate the active pointer.
    records = json.loads((ROOT / "features/feature_scoped_promotions.json").read_text())['records']
    promoted = {r.get('canonical_name') for r in records
                if r.get('promotion_decision') == 'PROMOTE'
                and r.get('canonical_name')}
    if promoted:
        reg_p = ROOT / 'features/authority/candidate/canonical_registry.json'
        facts_p = ROOT / 'features/authority/candidate/promotion_facts.json'
        reg = json.loads(reg_p.read_text()); facts = json.loads(facts_p.read_text())
        for row in reg.get('definitions', []):
            if row.get('canonical_name') in promoted: row['status'] = 'verified'
        for row in facts.get('definitions', []):
            if row.get('canonical_name') in promoted: row['lifecycle_status'] = 'verified'
        reg_p.write_text(json.dumps(reg, indent=2, sort_keys=True)+'\n'); facts_p.write_text(json.dumps(facts, indent=2, sort_keys=True)+'\n')
        run(["scripts/authorize_feature_candidate_activation.py", "--study", str(study),
             "--causal-status", str(study / "audit" / "status.json"),
             "--contract-status", str(study / "audit" / "contract_status.json")])
        # Complete the deterministic activation in the same run.  Only the
        # study-declared scopes are required; unrelated provisional candidates
        # remain inert and unavailable to canonical resolution.
        from features.candidate_authority import activate_pipeline_candidate
        activate_pipeline_candidate(
            parity_matrix_path=ROOT / "scratch" / "feature_system_v2_full_legacy_parity_matrix.json",
            required_names=set(promoted),
        )
    # READY is reserved for capabilities actually present in active authority.
    # Candidate evidence alone is not sufficient for study scaffolding.
    from features.candidate_authority import load_authority
    active = load_authority("active")
    active_names = {x.get("canonical_name") for x in active["registry"].get("definitions", [])
                    if x.get("status") == "verified"}
    candidate_names = {x.get("canonical_name") for x in records
                       if x.get("scope_type") in {"FEATURE_DEFINITION", "FEATURE_PARAMETER_VALUE"}}
    remaining = sorted(candidate_names - active_names)
    state = "READY_TO_SCAFFOLD" if not remaining else "PROMOTION_REQUIRED"
    return {"state": state, "seal_id":seal.get('seal_id'), "promoted":sorted(promoted),
            "required_scopes_total": len(candidate_names),
            "active_verified_scopes": len(candidate_names & active_names),
            "remaining_promotion_scopes": remaining}

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--study', required=True, type=Path); a=ap.parse_args()
    result=reconcile(a.study.resolve()); print(json.dumps(result, indent=2, sort_keys=True)); return 0 if result['state']=='READY_TO_SCAFFOLD' else 1
if __name__=='__main__': raise SystemExit(main())

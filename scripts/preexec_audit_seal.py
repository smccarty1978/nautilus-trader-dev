"""Cryptographic Pre-Execution Audit Seal Manager.
=================================================
Ensures that code, configuration, feature surface, and internal self-attested review audits
are immutably hashed, provenance-authenticated, and sealed before any execution occurs.
(Independent verification authority is held exclusively by the external Red Team).

If any source file or audit report changes after sealing, or if audits were
performed against an earlier code version, execution halts immediately with
PREEXEC_AUDIT_STALE.
"""

from __future__ import annotations

import glob
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class PreexecAuditStaleError(RuntimeError):
    """Raised when source files or audits have drifted from the cryptographic seal."""
    pass


def _hash_file(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_execution_files_manifest(
    study_dir: Path, repo_root: Optional[Path] = None
) -> Tuple[str, Dict[str, str]]:
    """Computes individual file SHA-256 hashes and composite hash for all execution-affecting files
    using the canonical execution dependency resolver.
    """
    from scripts.resolve_execution_manifest import resolve_execution_manifest

    composite_sha, file_hashes, _ = resolve_execution_manifest(study_dir, repo_root)
    return composite_sha, file_hashes


def _find_latest_audit_pass_files(study_dir: Path) -> List[str]:
    """Finds all existing pass_NN.md and contract_pass_NN.md files in audit directory."""
    audit_dir = study_dir / "audit"
    if not audit_dir.exists():
        return []
    rel_files = []
    for p in sorted(audit_dir.glob("*.md")):
        rel_files.append(f"audit/{p.name}")
    return rel_files


def generate_preexec_audit_seal(study_dir: Path, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Generates and writes artifacts/preexec_audit_seal.json after verifying audits are CLEAR and fresh."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]

    # 1. Compute current execution code manifest & composite hash
    current_composite_sha, exec_file_hashes = compute_execution_files_manifest(study_dir, repo_root)

    # 2. Verify audits exist, are CLEAR, and have authentic provenance
    status_file = study_dir / "audit" / "status.json"
    contract_status_file = study_dir / "audit" / "contract_status.json"

    if not status_file.exists():
        raise PreexecAuditStaleError(f"PREEXEC_AUDIT_STALE: Missing causal audit status file: {status_file}")
    if not contract_status_file.exists():
        raise PreexecAuditStaleError(f"PREEXEC_AUDIT_STALE: Missing contract audit status file: {contract_status_file}")

    with open(status_file, "r") as f:
        status_data = json.load(f)
    with open(contract_status_file, "r") as f:
        contract_status_data = json.load(f)

    # Provenance validation (R3-2: Version 2 required)
    if status_data.get("audit_provenance_version") != 2:
        raise PreexecAuditStaleError("PROVENANCE_V1_RETIRED: status.json audit_provenance_version must strictly be 2")
    if contract_status_data.get("audit_provenance_version") != 2:
        raise PreexecAuditStaleError("PROVENANCE_V1_RETIRED: contract_status.json audit_provenance_version must strictly be 2")

    # Report hash binding validation
    causal_report_rel = status_data.get("audit_report_path")
    contract_report_rel = contract_status_data.get("audit_report_path")

    if not causal_report_rel or not (study_dir / causal_report_rel).exists():
        raise PreexecAuditStaleError(f"PREEXEC_AUDIT_PROVENANCE_INVALID: Missing causal audit report {causal_report_rel}")
    if not contract_report_rel or not (study_dir / contract_report_rel).exists():
        raise PreexecAuditStaleError(f"PREEXEC_AUDIT_PROVENANCE_INVALID: Missing contract audit report {contract_report_rel}")

    actual_causal_report_sha = _hash_file(study_dir / causal_report_rel)
    actual_contract_report_sha = _hash_file(study_dir / contract_report_rel)

    if status_data.get("audit_report_sha256") != actual_causal_report_sha:
        raise PreexecAuditStaleError(
            f"PREEXEC_AUDIT_PROVENANCE_INVALID: Causal audit report markdown tampered!\n"
            f"  Report SHA: {actual_causal_report_sha}\n"
            f"  Status recorded SHA: {status_data.get('audit_report_sha256')}"
        )
    if contract_status_data.get("audit_report_sha256") != actual_contract_report_sha:
        raise PreexecAuditStaleError(
            f"PREEXEC_AUDIT_PROVENANCE_INVALID: Contract audit report markdown tampered!\n"
            f"  Report SHA: {actual_contract_report_sha}\n"
            f"  Contract status recorded SHA: {contract_status_data.get('audit_report_sha256')}"
        )

    # Re-parse reports from disk before trusting status JSONs (R3-2)
    from scripts.run_preexec_audits import parse_causal_audit_report, parse_contract_audit_report, AuditArtifactParseError

    try:
        re_c_verdict, re_c_crit, re_c_warn, _ = parse_causal_audit_report(study_dir / causal_report_rel)
    except AuditArtifactParseError as e:
        raise PreexecAuditStaleError(f"PREEXEC_AUDIT_PROVENANCE_INVALID: Causal audit report failed strict V2 parse: {e}")

    try:
        re_k_verdict, re_k_block, re_k_warn, _ = parse_contract_audit_report(study_dir / contract_report_rel)
    except AuditArtifactParseError as e:
        raise PreexecAuditStaleError(f"PREEXEC_AUDIT_PROVENANCE_INVALID: Contract audit report failed strict V2 parse: {e}")

    # Cross-check report parsed results against status.json
    if (
        re_c_verdict != status_data.get("verdict")
        or re_c_crit != status_data.get("critical")
        or re_c_warn != status_data.get("warning")
    ):
        raise PreexecAuditStaleError(
            f"PREEXEC_AUDIT_PROVENANCE_INVALID: status.json fields do not match re-derived causal audit report!\n"
            f"  Re-derived: verdict={re_c_verdict}, crit={re_c_crit}, warn={re_c_warn}\n"
            f"  status.json: verdict={status_data.get('verdict')}, crit={status_data.get('critical')}, warn={status_data.get('warning')}"
        )

    if (
        re_k_verdict != contract_status_data.get("verdict")
        or re_k_block != contract_status_data.get("blocking", contract_status_data.get("critical"))
        or re_k_warn != contract_status_data.get("warning")
    ):
        raise PreexecAuditStaleError(
            f"PREEXEC_AUDIT_PROVENANCE_INVALID: contract_status.json fields do not match re-derived contract audit report!\n"
            f"  Re-derived: verdict={re_k_verdict}, block={re_k_block}, warn={re_k_warn}\n"
            f"  contract_status.json: verdict={contract_status_data.get('verdict')}, crit={contract_status_data.get('critical')}, warn={contract_status_data.get('warning')}"
        )

    # Ensure both verdicts are CLEAR and counts are 0
    if re_c_verdict != "CLEAR" or re_c_crit != 0 or re_c_warn != 0:
        raise PreexecAuditStaleError(f"PREEXEC_AUDIT_STALE: Causal audit is not CLEAR: verdict={re_c_verdict}, crit={re_c_crit}, warn={re_c_warn}")

    if re_k_verdict != "CLEAR" or re_k_block != 0 or re_k_warn != 0:
        raise PreexecAuditStaleError(f"PREEXEC_AUDIT_STALE: Contract audit is not CLEAR: verdict={re_k_verdict}, block={re_k_block}, warn={re_k_warn}")

    causal_audited_sha = status_data.get("audited_execution_composite_sha256")
    contract_audited_sha = contract_status_data.get("audited_execution_composite_sha256")

    if causal_audited_sha != current_composite_sha:
        raise PreexecAuditStaleError(
            f"PREEXEC_AUDIT_STALE: Execution code modified after Causal Audit!\n"
            f"  Current execution composite SHA-256: {current_composite_sha}\n"
            f"  Causal audit reviewed SHA-256:       {causal_audited_sha}\n"
            f"Run a new Causal Audit pass against the updated code before sealing."
        )

    if contract_audited_sha != current_composite_sha:
        raise PreexecAuditStaleError(
            f"PREEXEC_AUDIT_STALE: Execution code modified after Contract Audit!\n"
            f"  Current execution composite SHA-256: {current_composite_sha}\n"
            f"  Contract audit reviewed SHA-256:     {contract_audited_sha}\n"
            f"Run a new Contract Audit pass against the updated code before sealing."
        )

    # 2b. Reviewer provenance must be recorded, and must not overclaim (B2).
    # The seal is where "two independent reviewers cleared this" is asserted, so it is
    # where the strength of that assertion has to be carried rather than assumed.
    provenance_summary = {}
    for label, data in (("causal", status_data), ("contract", contract_status_data)):
        rp = data.get("reviewer_provenance")
        if not isinstance(rp, dict):
            raise PreexecAuditStaleError(
                f"REVIEWER_PROVENANCE_ABSENT: {label} status records no 'reviewer_provenance'. "
                f"Re-issue the status with scripts/run_preexec_audits.py so the strength of the "
                f"reviewer identity is stated explicitly instead of being inferred from a role name."
            )
        if rp.get("independence_proven") is True:
            raise PreexecAuditStaleError(
                f"REVIEWER_PROVENANCE_OVERCLAIM: {label} status asserts independence_proven=True. "
                f"This workflow enforces distinct declared identities; it does not prove human "
                f"independence, and no artifact may claim that it does."
            )
        strength = rp.get("provenance_strength")
        if strength not in ("DECLARED_IDENTITY_ONLY", "SESSION_BOUND"):
            raise PreexecAuditStaleError(
                f"REVIEWER_PROVENANCE_INVALID: {label} status declares unknown "
                f"provenance_strength={strength!r}"
            )
        if strength == "SESSION_BOUND":
            ev = rp.get("session_evidence") or {}
            if not ev.get("transcript_sha256"):
                raise PreexecAuditStaleError(
                    f"REVIEWER_PROVENANCE_INVALID: {label} status claims SESSION_BOUND without a "
                    f"transcript hash."
                )
        provenance_summary[label] = {
            "declared_auditor": rp.get("declared_auditor"),
            "provenance_strength": strength,
            "independence_proven": False,
            "independence_basis": rp.get("independence_basis"),
        }

    # 3. Include audit files in overall sealed file hashes
    all_sealed_hashes = dict(exec_file_hashes)
    all_sealed_hashes["study:audit/status.json"] = _hash_file(status_file)
    all_sealed_hashes["study:audit/contract_status.json"] = _hash_file(contract_status_file)

    for md_rel in _find_latest_audit_pass_files(study_dir):
        all_sealed_hashes[f"study:{md_rel}"] = _hash_file(study_dir / md_rel)

    evidence_dict = {}
    for k, v in all_sealed_hashes.items():
        clean_key = k.replace(":", "_").replace("/", "_").replace(".", "_").replace("\\", "_")
        evidence_dict[clean_key] = {
            "path": k,
            "sha256": v,
        }

    seal_data = {
        "seal_id": f"preexec_seal_{study_dir.name}_{current_composite_sha[:16]}",
        "study_name": study_dir.name,
        "seal_status": "LOCKED",
        "composite_seal_hash": current_composite_sha,
        "reviewer_provenance": provenance_summary,
        "causal_audit_verdict": status_data,
        "contract_audit_verdict": contract_status_data,
        "file_hashes": all_sealed_hashes,
        "evidence": evidence_dict,
    }

    seal_file = study_dir / "artifacts" / "preexec_audit_seal.json"
    seal_file.parent.mkdir(parents=True, exist_ok=True)
    with open(seal_file, "w") as f:
        json.dump(seal_data, f, indent=2)

    return seal_data


def verify_preexec_audit_seal(study_dir: Path, repo_root: Optional[Path] = None) -> bool:
    """Verifies that all files match the cryptographic seal on disk. Raises PreexecAuditStaleError if stale."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]

    seal_file = study_dir / "artifacts" / "preexec_audit_seal.json"
    if not seal_file.exists():
        raise PreexecAuditStaleError(
            f"PREEXEC_AUDIT_STALE: Missing pre-execution audit seal at {seal_file}. "
            f"Generate with 'python scripts/preexec_audit_seal.py --study {study_dir}' after audits pass."
        )

    with open(seal_file, "r") as f:
        seal_data = json.load(f)

    file_hashes = seal_data.get("file_hashes", {})
    if not file_hashes:
        raise PreexecAuditStaleError(f"PREEXEC_AUDIT_STALE: Corrupt audit seal in {seal_file}")

    for key, expected_hash in file_hashes.items():
        scope, rel = key.split(":", 1)
        if scope == "study":
            fp = study_dir / rel
        else:
            fp = repo_root / rel

        if not fp.exists():
            raise PreexecAuditStaleError(f"PREEXEC_AUDIT_STALE: Sealed file missing from disk: {fp}")

        current_hash = _hash_file(fp)
        if current_hash != expected_hash:
            raise PreexecAuditStaleError(
                f"PREEXEC_AUDIT_STALE: File '{rel}' was modified after audit seal! "
                f"(Sealed hash: {expected_hash[:12]}..., Current hash: {current_hash[:12]}...). "
                f"Code changes require re-auditing and re-sealing."
            )

    # Verify current execution composite hash against seal composite hash
    current_composite_sha, _ = compute_execution_files_manifest(study_dir, repo_root)
    if current_composite_sha != seal_data.get("composite_seal_hash"):
        raise PreexecAuditStaleError(
            f"PREEXEC_AUDIT_STALE: Current execution composite hash mismatch!\n"
            f"  Current: {current_composite_sha}\n"
            f"  Sealed:  {seal_data.get('composite_seal_hash')}"
        )

    return seal_data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Manage pre-execution audit seal")
    parser.add_argument("--study", type=str, required=True, help="Path to study directory")
    parser.add_argument("--verify-only", action="store_true", help="Verify without regenerating")
    args = parser.parse_args()

    s_dir = Path(args.study).resolve()
    if args.verify_only:
        verify_preexec_audit_seal(s_dir)
        print("PREEXEC_AUDIT_SEAL_VALID")
    else:
        seal = generate_preexec_audit_seal(s_dir)
        print(f"PREEXEC_AUDIT_SEAL_GENERATED: composite={seal['composite_seal_hash'][:16]}...")

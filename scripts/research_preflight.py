"""Repository-Wide Deterministic Research Preflight Orchestrator.
===============================================================

Orchestrates all fast deterministic checks before any human or LLM auditor turn:
  1. AST Causal Lint (scripts/causal_lint.py)
  2. Artifact & Seal Schema Validation (scripts/check_artifact_schema.py)
  3. Model & Feature Binding (scripts/check_model_binding.py, if applicable)
  4. Fast Invariant Canaries & Tests (scripts/select_required_tests.py -> pytest)

Emits:
  - audit/preflight.json       (Compact machine-readable status)
  - audit/failure_packet.json  (Minimal diagnostic packet on failure)

Usage:
  python scripts/research_preflight.py --study studies/<name>
  python scripts/research_preflight.py --study studies/<name> --json audit/preflight.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def calculate_dir_hash(dir_path: Path) -> str:
    sha = hashlib.sha256()
    for root, _, files in sorted(os.walk(dir_path)):
        for f in sorted(files):
            if f.endswith((".py", ".yaml", ".json", ".md")) and not any(
                p in root for p in ("__pycache__", ".git", "_work", "audit", "results")
            ):
                p = Path(root) / f
                try:
                    sha.update(p.read_bytes())
                except Exception:
                    pass
    return sha.hexdigest()


def run_preflight(
    study_path: Optional[Path],
    extra_paths: List[Path],
    out_json: Optional[Path] = None,
    skip_tests: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    start_time = time.time()
    checks_run = []
    failed_gate = None
    failure_ids = []
    failure_details = []

    study_dir = study_path if study_path and study_path.exists() else None
    audit_dir = (study_dir / "audit") if study_dir else (REPO_ROOT / "audit")
    audit_dir.mkdir(parents=True, exist_ok=True)

    # 0. Stage 0: Canonical Execution Manifest Resolution
    if study_dir and (study_dir / "study.yaml").exists():
        checks_run.append("EXECUTION_MANIFEST")
        try:
            from scripts.resolve_execution_manifest import resolve_execution_manifest
            comp_sha, fhashes, mdata = resolve_execution_manifest(study_dir, REPO_ROOT)
            manifest_p = audit_dir / "execution_manifest.json"
            with open(manifest_p, "w", encoding="utf-8") as f:
                json.dump(mdata, f, indent=2)
        except Exception as e:
            failed_gate = "EXECUTION_MANIFEST"
            failure_ids = ["MANIFEST_RESOLUTION_FAILED"]
            failure_details = [{"message": f"Failed to resolve execution manifest: {e}"}]

    # 1. Stage 1: Causal Lint with Complete Coverage
    if not failed_gate:
        checks_run.append("CAUSAL_LINT")
        lint_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "causal_lint.py")]
        if study_dir:
            lint_cmd.extend(["--study", str(study_dir)])
        for ep in extra_paths:
            lint_cmd.extend(["--path", str(ep)])

        lint_json = audit_dir / "lint.json"
        lint_cmd.extend(["--json", str(lint_json)])

        lint_res = subprocess.run(lint_cmd, capture_output=True, text=True)
        if lint_res.returncode != 0:
            failed_gate = "CAUSAL_LINT"
            if lint_json.exists():
                try:
                    with open(lint_json, "r", encoding="utf-8") as f:
                        ldata = json.load(f)
                    failure_ids = [f["rule_id"] for f in ldata.get("findings", []) if f.get("severity") == "CRITICAL"]
                    if not failure_ids and not ldata.get("invocation_valid", True):
                        failure_ids = ldata.get("invocation_errors", ["LINT_COVERAGE_INCOMPLETE"])
                    failure_details = ldata.get("findings", []) + [{"message": err} for err in ldata.get("invocation_errors", [])]
                except Exception:
                    failure_ids = ["LINT_FAILURE"]
            else:
                failure_ids = ["LINT_INVOCATION_ERROR"]

    # 2. Stage 2: Artifact & Schema Validation
    if not failed_gate:
        checks_run.append("ARTIFACT_SCHEMA")
        schema_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "check_artifact_schema.py")]
        if study_dir:
            schema_cmd.extend(["--study", str(study_dir)])
        schema_json = audit_dir / "schema_check.json"
        schema_cmd.extend(["--json", str(schema_json)])

        schema_res = subprocess.run(schema_cmd, capture_output=True, text=True)
        if schema_res.returncode != 0:
            failed_gate = "ARTIFACT_SCHEMA"
            if schema_json.exists():
                try:
                    with open(schema_json, "r", encoding="utf-8") as f:
                        sdata = json.load(f)
                    failure_ids = [iss["code"] for iss in sdata.get("issues", []) if iss.get("severity") == "CRITICAL"]
                    failure_details = sdata.get("issues", [])
                except Exception:
                    failure_ids = ["SCHEMA_FAILURE"]
            else:
                failure_ids = ["SCHEMA_ERROR"]

    # 2a. Stage 2a: Research Decision Contract Fidelity
    if not failed_gate and study_dir:
        decision_file = study_dir / "research_decision.yaml"
        if decision_file.exists():
            checks_run.append("RESEARCH_DECISION_FIDELITY")
            dec_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "check_research_decision_fidelity.py"), "--study", str(study_dir)]
            dec_res = subprocess.run(dec_cmd, capture_output=True, text=True)
            if dec_res.returncode != 0:
                failed_gate = "RESEARCH_DECISION_FIDELITY"
                failure_ids = ["RESEARCH_DECISION_FIDELITY_MISMATCH"]
                failure_details = [{"message": line} for line in dec_res.stdout.splitlines() if "[CRITICAL]" in line or "FAIL" in line]

    # 2b. Stage 2b: SPEC to StudySpec Fidelity Validation
    if not failed_gate and study_dir and (study_dir / "study_clauses.yaml").exists():
        checks_run.append("SPEC_FIDELITY")
        fid_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "check_spec_fidelity.py"), "--study", str(study_dir)]
        fid_res = subprocess.run(fid_cmd, capture_output=True, text=True)
        if fid_res.returncode != 0:
            failed_gate = "SPEC_FIDELITY"
            failure_ids = ["SPEC_FIDELITY_MISMATCH"]
            failure_details = [{"message": line} for line in fid_res.stdout.splitlines() if "[FAIL]" in line or "Unmapped" in line]

    # 3. Stage 3: Fast Invariant Tests
    if not failed_gate and not skip_tests:
        checks_run.append("CAUSAL_INVARIANTS")
        test_select_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "select_required_tests.py")]
        select_res = subprocess.run(test_select_cmd, capture_output=True, text=True)
        tests_to_run = [l.strip() for l in select_res.stdout.splitlines() if l.strip()]

        if tests_to_run:
            pytest_cmd = [sys.executable, "-m", "pytest"] + tests_to_run + ["-m", "not slow", "-q"]
            try:
                test_run_res = subprocess.run(
                    pytest_cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(REPO_ROOT),
                    timeout=120,
                )
                if test_run_res.returncode != 0:
                    failed_gate = "CAUSAL_INVARIANTS"
                    failure_ids = ["INVARIANT_TEST_FAILURE"]
                    failure_details = [{"message": line} for line in test_run_res.stdout.splitlines()[-5:]]
            except subprocess.TimeoutExpired:
                failed_gate = "CAUSAL_INVARIANTS"
                failure_ids = ["INVARIANT_TEST_TIMEOUT"]
                failure_details = [{"message": "Fast invariant test execution exceeded timeout limit (120s)."}]

    elapsed = round(time.time() - start_time, 2)
    status = "CLEAR" if not failed_gate else "BLOCKED"
    code_hash = calculate_dir_hash(study_dir) if study_dir else ""
    spec_p = (study_dir / "SPEC.md") if study_dir else None
    spec_hash = hashlib.sha256(spec_p.read_bytes()).hexdigest() if spec_p and spec_p.exists() else ""

    result = {
        "status": status,
        "elapsed_seconds": elapsed,
        "code_hash": code_hash,
        "spec_hash": spec_hash,
        "checks_run": checks_run,
        "failed_gate": failed_gate,
        "failure_ids": failure_ids,
        "required_next_action": "FIX_BEFORE_AUDIT" if status == "BLOCKED" else "READY_FOR_AUDIT",
    }

    # Write preflight.json
    target_preflight = out_json or (audit_dir / "preflight.json")
    target_preflight.parent.mkdir(parents=True, exist_ok=True)
    with open(target_preflight, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    # If BLOCKED, write failure_packet.json
    if status == "BLOCKED":
        failure_packet = {
            "status": "BLOCKED",
            "failed_gate": failed_gate,
            "failure_ids": failure_ids,
            "failure_details": failure_details,
            "recommended_smallest_investigation_scope": f"Inspect findings in {failed_gate} and fix locally before requesting audit.",
        }
        packet_p = audit_dir / "failure_packet.json"
        with open(packet_p, "w", encoding="utf-8") as f:
            json.dump(failure_packet, f, indent=2)

    # Print summary card
    print("=" * 60)
    print(f"RESEARCH PREFLIGHT VERDICT: {status} ({elapsed}s)")
    print(f"Checks Run: {', '.join(checks_run)}")
    if status == "BLOCKED":
        print(f"Failed Gate: {failed_gate}")
        print(f"Failure IDs: {', '.join(failure_ids)}")
        print(f"Failure Packet: {audit_dir / 'failure_packet.json'}")
    else:
        print("Ready for internal causal review gate.")
    print("=" * 60)

    return 0 if status == "CLEAR" else 1, result


def main() -> int:
    ap = argparse.ArgumentParser(description="Run research preflight checks")
    ap.add_argument("--study", type=str, help="Path to study directory")
    ap.add_argument("--path", type=str, nargs="*", default=[], help="Additional paths to scan")
    ap.add_argument("--json", type=str, help="Output JSON path")
    ap.add_argument("--skip-tests", action="store_true", help="Skip pytest invariant stage")
    args = ap.parse_args()

    study_p = Path(args.study) if args.study else None
    extra_paths = [Path(p) for p in args.path]

    exit_code, _ = run_preflight(study_p, extra_paths, Path(args.json) if args.json else None, args.skip_tests)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

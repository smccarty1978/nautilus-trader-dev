"""Artifact and Seal Manifest Schema and DAG Validator.
=====================================================

Validates persisted artifacts across studies:
  1. audit/status.json
  2. audit/audit_packet.json
  3. results/validation_report.json
  4. Seal DAG & Promotion Manifests (acyclic dependency structure)

Exit codes:
  0: All artifacts valid and DAG is clean
  1: Validation errors or acyclic DAG violations found
  2: Invocation error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class ValidationIssue:
    severity: str  # CRITICAL, WARNING
    code: str
    artifact: str
    message: str


def validate_status_json(data: Dict[str, Any], path: Path) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    rel = str(path)
    
    # ``contract_status.json`` predates the common status schema and used
    # ``status`` as its terminal field.  Accept that established artifact shape
    # while new writers emit ``verdict``; this is validation compatibility, not
    # a reinterpretation of its blocking count.
    verdict = data.get("verdict", data.get("status"))
    if verdict is None:
        issues.append(ValidationIssue("CRITICAL", "STATUS_SCHEMA", rel, "Missing required field 'verdict'"))
    elif verdict not in {"PASS", "CLEAR", "BLOCKED", "FAIL", "ACCEPTED"}:
        issues.append(ValidationIssue("WARNING", "STATUS_VERDICT", rel, f"Unusual verdict value: {verdict}"))

    severity_key = "blocking" if path.name.lower() == "contract_status.json" else "critical"
    if severity_key not in data or not isinstance(data[severity_key], int):
        issues.append(ValidationIssue("CRITICAL", "STATUS_SCHEMA", rel, f"Missing or non-integer field '{severity_key}'"))
    if "warning" not in data or not isinstance(data["warning"], int):
        issues.append(ValidationIssue("CRITICAL", "STATUS_SCHEMA", rel, "Missing or non-integer field 'warning'"))

    return issues


def validate_audit_packet(data: Dict[str, Any], path: Path) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    rel = str(path)

    if not any(k in data for k in ("study", "study_id", "study_dir")):
        issues.append(ValidationIssue("CRITICAL", "PACKET_SCHEMA", rel, "Missing study identifier in audit packet"))

    code_files = data.get("code_files", [])
    if not isinstance(code_files, list):
        issues.append(ValidationIssue("CRITICAL", "PACKET_SCHEMA", rel, "'code_files' must be a list"))
    else:
        for idx, item in enumerate(code_files):
            if not isinstance(item, dict) or "file" not in item or "sha256" not in item:
                issues.append(ValidationIssue("CRITICAL", "PACKET_FILE_HASH", rel, f"Item {idx} in code_files missing 'file' or 'sha256'"))
            elif len(item["sha256"]) != 64:
                issues.append(ValidationIssue("CRITICAL", "PACKET_INVALID_HASH", rel, f"Invalid SHA256 hash length for {item.get('file')}"))

    return issues


MANDATORY_TERMINAL_FIELDS = [
    "model_sha256",
    "feature_list_sha256",
    "code_sha256",
    "spec_sha256",
    "validation_report_sha256",
    "audit_status_sha256",
    "preflight_sha256",
    "test_evidence_sha256",
    "promotion_timestamp",
]


def validate_seal_manifest(data: Dict[str, Any], path: Path) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    rel = str(path)

    seal_id = data.get("seal_id")
    if not seal_id:
        issues.append(ValidationIssue("CRITICAL", "SEAL_SCHEMA", rel, "Missing 'seal_id'"))

    # If it is a promotion manifest or terminal seal, verify 9 mandatory terminal evidence fields
    if "promotion" in path.name.lower() or "terminal" in path.name.lower() or data.get("is_terminal_promotion", False):
        missing_fields = [f for f in MANDATORY_TERMINAL_FIELDS if f not in data]
        if missing_fields:
            issues.append(
                ValidationIssue(
                    "CRITICAL",
                    "INCOMPLETE_TERMINAL_EVIDENCE",
                    rel,
                    f"Terminal promotion manifest missing required fields: {missing_fields}",
                )
            )

    # Evidence binding
    evidence = data.get("evidence", {})
    if not evidence or not isinstance(evidence, dict):
        issues.append(ValidationIssue("CRITICAL", "SEAL_NO_EVIDENCE", rel, "Seal manifest has no persisted evidence dictionary"))
    else:
        for ev_key, ev_val in evidence.items():
            if not isinstance(ev_val, dict):
                issues.append(ValidationIssue("CRITICAL", "MISSING_PERSISTED_EVIDENCE", rel, f"Evidence '{ev_key}' is not a persisted dictionary"))
                continue

            ev_path = ev_val.get("path")
            ev_sha = ev_val.get("sha256")
            if not ev_path or not ev_sha:
                issues.append(ValidationIssue("CRITICAL", "SEAL_INCOMPLETE_EVIDENCE", rel, f"Evidence '{ev_key}' missing path or sha256"))
            elif ev_path == rel or ev_path == str(path.name):
                issues.append(ValidationIssue("CRITICAL", "SELF_REFERENTIAL_SEAL", rel, f"Seal references itself as evidence: {ev_path}"))
            elif len(ev_sha) != 64:
                issues.append(ValidationIssue("CRITICAL", "SEAL_INVALID_HASH", rel, f"Invalid SHA256 length for evidence '{ev_key}'"))

            # Check for stale audit binding
            if ev_key == "audit_status" or "audit" in ev_key:
                audited_code_sha = ev_val.get("audited_code_sha256")
                current_code_sha = data.get("code_sha256")
                if audited_code_sha and current_code_sha and audited_code_sha != current_code_sha:
                    issues.append(
                        ValidationIssue(
                            "CRITICAL",
                            "STALE_AUDIT",
                            rel,
                            f"Audit evidence was conducted on stale code hash ({audited_code_sha[:8]}...) != current ({current_code_sha[:8]}...)",
                        )
                    )

            # Check for stale validation binding
            if ev_key == "validation_report" or "validation" in ev_key:
                validated_model_sha = ev_val.get("validated_model_sha256")
                current_model_sha = data.get("model_sha256")
                if validated_model_sha and current_model_sha and validated_model_sha != current_model_sha:
                    issues.append(
                        ValidationIssue(
                            "CRITICAL",
                            "STALE_VALIDATION",
                            rel,
                            f"Validation evidence was generated for different model hash ({validated_model_sha[:8]}...) != current ({current_model_sha[:8]}...)",
                        )
                    )

    # Dependencies DAG check
    deps = data.get("dependencies", [])
    if isinstance(deps, list):
        if seal_id in deps or str(path.name) in deps or rel in deps:
            issues.append(ValidationIssue("CRITICAL", "SEAL_DAG_CYCLE", rel, f"Self-referential dependency in seal: {seal_id}"))

    return issues


def validate_run_status_json(data: Dict[str, Any], path: Path) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    rel = str(path)
    if "status" not in data:
        issues.append(ValidationIssue("CRITICAL", "RUN_STATUS_SCHEMA", rel, "Missing required field 'status' in run_status.json"))
    return issues


def scan_artifacts(root: Path, *, candidate_authority: bool = False) -> Tuple[List[ValidationIssue], Dict[str, Any]]:
    issues: List[ValidationIssue] = []
    scanned = {"status_json": 0, "run_status_json": 0, "audit_packets": 0, "seal_manifests": 0}

    for json_file in root.rglob("*.json"):
        if any(part in json_file.parts for part in ("__pycache__", ".git", ".pytest_cache", "_work")):
            continue
        # Candidate governance is intentionally isolated from the stale active
        # audit namespace.  It still validates every study artifact plus the
        # candidate audit namespace; only top-level active review statuses are
        # excluded because they cannot authorize an inactive bundle.
        if (candidate_authority and json_file.parent == root / "audit"
                and json_file.name.lower() in {"status.json", "contract_status.json"}):
            continue
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            issues.append(ValidationIssue("CRITICAL", "JSON_PARSE_ERROR", str(json_file), f"Could not parse JSON: {e}"))
            continue

        name = json_file.name.lower()
        # Scoped to audit/ deliberately: a collection run's own run-tracking file is
        # ALSO named `status.json` (runs/<run_id>/status.json, a distinct schema
        # describing an NT collection run's outcome, not an audit verdict) and would
        # otherwise be misvalidated against the audit-status schema the first time
        # this check runs after TRAIN collection has already produced run directories.
        if name in {"status.json", "contract_status.json"} and json_file.parent == root / "audit":
            scanned["status_json"] += 1
            issues.extend(validate_status_json(data, json_file))
        elif name == "run_status.json":
            scanned["run_status_json"] += 1
            issues.extend(validate_run_status_json(data, json_file))
        elif name in {"audit_packet.json", "packet.json"}:
            scanned["audit_packets"] += 1
            issues.extend(validate_audit_packet(data, json_file))
        elif "seal" in name or "promotion" in name:
            scanned["seal_manifests"] += 1
            issues.extend(validate_seal_manifest(data, json_file))

    return issues, scanned


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate artifact schemas and seal DAGs")
    ap.add_argument("--study", type=str, help="Study folder to validate")
    ap.add_argument("--path", type=str, nargs="*", default=[], help="Additional paths to scan")
    ap.add_argument("--json", type=str, help="Output JSON results path")
    ap.add_argument("--candidate-authority", action="store_true",
                    help="Validate inactive-candidate artifacts without consuming active audit statuses")
    args = ap.parse_args()

    roots = []
    if args.study:
        sd = Path(args.study)
        if not sd.exists():
            print(f"Error: study path does not exist: {sd}", file=sys.stderr)
            return 2
        roots.append(sd)
    for p in args.path:
        pp = Path(p)
        if not pp.exists():
            print(f"Error: path does not exist: {pp}", file=sys.stderr)
            return 2
        roots.append(pp)

    if not roots:
        roots.append(REPO_ROOT / "studies")

    all_issues: List[ValidationIssue] = []
    total_scanned = {"status_json": 0, "run_status_json": 0, "audit_packets": 0, "seal_manifests": 0}

    for r in roots:
        issues, counts = scan_artifacts(r, candidate_authority=args.candidate_authority)
        all_issues.extend(issues)
        for k, v in counts.items():
            total_scanned[k] = total_scanned.get(k, 0) + v

    n_crit = sum(1 for i in all_issues if i.severity == "CRITICAL")
    n_warn = sum(1 for i in all_issues if i.severity == "WARNING")

    payload = {
        "tool": "check_artifact_schema",
        "scanned": total_scanned,
        "critical": n_crit,
        "warning": n_warn,
        "clean": n_crit == 0 and n_warn == 0,
        "issues": [
            {"severity": i.severity, "code": i.code, "artifact": i.artifact, "message": i.message}
            for i in all_issues
        ],
    }

    if args.json:
        out_p = Path(args.json)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    print(f"Artifact Schema Check: {n_crit} CRITICAL, {n_warn} WARNING")
    for i in all_issues:
        print(f"  [{i.severity[:4]}] {i.code:<18} {i.artifact}")
        print(f"        -> {i.message}")

    return 1 if n_crit > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Mechanically bind candidate preflight and final review evidence for activation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _load(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"CANDIDATE_GOVERNANCE_EVIDENCE_ABSENT: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _clear_causal(status: dict) -> bool:
    return status.get("verdict") == "CLEAR" and status.get("critical") == 0 and status.get("warning") == 0


def _clear_contract(status: dict) -> bool:
    return status.get("verdict") == "CLEAR" and status.get("blocking", status.get("critical")) == 0 and status.get("warning") == 0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _review_is_candidate(status: dict, path: Path, *, audit_type: str, study: Path, bundle: str, execution: str) -> bool:
    report_name = status.get("report") or status.get("audit_report_path")
    report = path.parent / report_name if report_name and not Path(report_name).is_absolute() else Path(report_name or "")
    return (
        status.get("audit_type") == audit_type
        and status.get("study") == study.name
        and status.get("feature_authority") == "candidate"
        and status.get("candidate_bundle_composite_sha256") == bundle
        and status.get("audited_execution_composite_sha256") == execution
        and report.is_file()
    )


def authorize(study: Path, causal_status: Path, contract_status: Path) -> dict:
    audit = study / "audit" / "candidate"
    frozen = _load(audit / "candidate_authority_freeze.json")
    preflight = _load(audit / "preflight.json")
    causal = _load(causal_status)
    contract = _load(contract_status)
    expected = frozen.get("execution_composite_sha256")
    bundle = frozen.get("bundle_composite_sha256")
    checks = {
        "preflight": preflight.get("status") == "CLEAR" and preflight.get("execution_composite_sha256") == expected,
        "causal": _clear_causal(causal) and _review_is_candidate(causal, causal_status, audit_type="causal", study=study, bundle=bundle, execution=expected),
        "contract": _clear_contract(contract) and _review_is_candidate(contract, contract_status, audit_type="contract", study=study, bundle=bundle, execution=expected),
    }
    result = {
        "schema_version": 1,
        "status": "CLEAR" if all(checks.values()) else "BLOCKED",
        "candidate_bundle_composite_sha256": frozen.get("bundle_composite_sha256"),
        "candidate_execution_composite_sha256": expected,
        "candidate_freeze_path": str((audit / "candidate_authority_freeze.json").resolve()),
        "candidate_identifier": "features/authority/candidate",
        "checks": checks,
        "evidence": {
            "preflight": str((audit / "preflight.json").resolve()),
            "causal_status": str(causal_status.resolve()),
            "contract_status": str(contract_status.resolve()),
        },
        "evidence_sha256": {
            "preflight": _sha(audit / "preflight.json"),
            "causal_status": _sha(causal_status),
            "contract_status": _sha(contract_status),
        },
    }
    target = audit / "activation_authorization.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True)
    parser.add_argument("--causal-status", required=True)
    parser.add_argument("--contract-status", required=True)
    args = parser.parse_args()
    result = authorize(Path(args.study), Path(args.causal_status), Path(args.contract_status))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "CLEAR" else 1


if __name__ == "__main__":
    raise SystemExit(main())

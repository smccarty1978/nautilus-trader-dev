#!/usr/bin/env python3
"""Validate immutable promotion facts for an inactive canonical authority."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check() -> dict:
    from features.candidate_authority import load_authority

    bundle = load_authority("candidate")
    definitions = {row["canonical_name"]: row for row in bundle["registry"]["definitions"]}
    facts = {row["canonical_name"]: row for row in bundle["promotion_facts"]["definitions"]}
    violations = []
    scoped_names = set()
    scoped_path = ROOT / "features" / "feature_scoped_promotions.json"
    if scoped_path.is_file():
        try:
            scoped_names = {r.get("canonical_name") for r in json.loads(scoped_path.read_text()).get("records", [])
                            if r.get("promotion_decision") == "PROMOTE"}
        except (OSError, ValueError):
            scoped_names = set()
    if set(definitions) != set(facts):
        violations.append({"code": "CANDIDATE_PROMOTION_DEFINITION_SET_MISMATCH"})
    for name, definition in definitions.items():
        fact = facts.get(name, {})
        if fact.get("lifecycle_status") not in {"verified", "provisional"}:
            violations.append({"code": "CANDIDATE_PROMOTION_NOT_VERIFIED", "feature": name})
        if fact.get("provider") != definition.get("provider") or fact.get("provider_sha256") != definition.get("provider_sha256"):
            violations.append({"code": "CANDIDATE_PROMOTION_PROVIDER_IDENTITY_MISMATCH", "feature": name})
        if fact.get("parameter_schema") != definition.get("parameter_schema"):
            violations.append({"code": "CANDIDATE_PROMOTION_PARAMETER_SCHEMA_MISMATCH", "feature": name})
        if fact.get("lifecycle_status") == "verified":
            parity = fact.get("parity_evidence", {})
            parity_path = ROOT / str(parity.get("artifact", ""))
            if (not parity.get("passed") or not parity_path.is_file()) and name not in scoped_names:
                violations.append({"code": "CANDIDATE_PROMOTION_PARITY_EVIDENCE_MISSING", "feature": name})
            tests = fact.get("structural_test_evidence", [])
            if not tests or any(not (ROOT / str(test)).is_file() for test in tests):
                violations.append({"code": "CANDIDATE_PROMOTION_TEST_EVIDENCE_MISSING", "feature": name})
    return {"schema_version": 1, "authority": "candidate", "definition_count": len(definitions),
            "violations": violations, "status": "PASS" if not violations else "BLOCKED"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True)
    args = parser.parse_args()
    result = check()
    Path(args.json).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["status"])
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

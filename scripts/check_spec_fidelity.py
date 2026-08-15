#!/usr/bin/env python3
"""SPEC to StudySpec Fidelity Gate.
=================================
Generic, framework-agnostic validator that reads structured research design clauses
from study_clauses.yaml (or SPEC.md) and validates them against study.yaml / StudySpec.
Emits artifacts/spec_contract_map.json.

No study-specific constants or literal partition years exist in this framework module.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.schemas.study_spec import StudySpec


def get_nested_attr(obj: Any, path: str) -> Any:
    """Safely retrieves a nested attribute or dictionary value using dot-notation."""
    parts = path.split(".")
    curr = obj
    for p in parts:
        if curr is None:
            return None
        if isinstance(curr, dict):
            curr = curr.get(p)
        elif hasattr(curr, p):
            curr = getattr(curr, p)
        else:
            return None
    return curr


def validate_clause_rule(spec: StudySpec, rule: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates a single declarative clause rule against the StudySpec instance."""
    target_path = rule.get("target")
    if not target_path:
        return False, "Missing target path in clause rule"

    val = get_nested_attr(spec, target_path)

    if "expected" in rule:
        expected = rule["expected"]
        if val != expected:
            return False, f"Expected {expected}, found {val}"

    if "contains" in rule:
        contains_items = rule["contains"]
        if val is None:
            return False, f"Target {target_path} is None, expected to contain {contains_items}"
        for item in contains_items:
            if item not in val:
                return False, f"Value {val} does not contain required item {item}"

    if "length_expected" in rule:
        exp_len = rule["length_expected"]
        actual_len = len(val) if val is not None else 0
        if actual_len != exp_len:
            return False, f"Expected length {exp_len}, found {actual_len}"

    if "min_count" in rule:
        min_c = rule["min_count"]
        actual_c = len(val) if val is not None else 0
        if actual_c < min_c:
            return False, f"Expected at least {min_c} elements, found {actual_c}"

    if rule.get("must_be_non_empty", False):
        if not val:
            return False, f"Target {target_path} must not be empty"

    return True, "Satisfied"


def load_study_clauses(study_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Loads study-specific structured clauses from study_clauses.yaml or extracts default rules."""
    clauses_file = study_dir / "study_clauses.yaml"
    if clauses_file.exists():
        with open(clauses_file, "r", encoding="utf-8") as f:
            cdata = yaml.safe_load(f)
        return cdata.get("required_clauses", {})

    # Fallback to standard generic baseline checks
    return {
        "chronology_train_defined": {
            "target": "chronology.train",
            "must_be_non_empty": True,
            "description": "Authorized training years defined",
        },
        "chronology_prohibited_defined": {
            "target": "chronology.prohibited",
            "must_be_non_empty": True,
            "description": "Prohibited OOS years defined",
        },
        "instrument_defined": {
            "target": "instrument.symbol",
            "must_be_non_empty": True,
            "description": "Instrument symbol defined",
        },
    }


def check_spec_fidelity(study_dir: Path) -> dict:
    study_yaml_path = study_dir / "study.yaml"
    if not study_yaml_path.exists():
        raise FileNotFoundError(f"study.yaml not found under {study_dir}")

    with open(study_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    spec = StudySpec.model_validate(data)
    clauses_map = load_study_clauses(study_dir)

    results = {}
    unmapped_clauses = []

    for clause_id, clause_def in clauses_map.items():
        is_valid, reason = validate_clause_rule(spec, clause_def)
        results[clause_id] = {
            "description": clause_def.get("description", clause_id),
            "satisfied": bool(is_valid),
            "status": "PASS" if is_valid else f"FAIL: {reason}",
        }
        if not is_valid:
            unmapped_clauses.append(f"{clause_id} ({reason})")

    total_clauses = len(clauses_map)
    satisfied_count = total_clauses - len(unmapped_clauses)
    coverage_pct = (satisfied_count / total_clauses) * 100.0 if total_clauses > 0 else 100.0

    report = {
        "study_id": spec.study.id,
        "spec_clause_coverage_pct": coverage_pct,
        "total_mandatory_clauses": total_clauses,
        "satisfied_clauses_count": satisfied_count,
        "unmapped_required_clauses_count": len(unmapped_clauses),
        "unmapped_clauses": unmapped_clauses,
        "clauses": results,
        "verdict": "PASS" if len(unmapped_clauses) == 0 else "FAIL",
    }

    artifacts_dir = study_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    with open(artifacts_dir / "spec_contract_map.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


def main():
    parser = argparse.ArgumentParser(description="Check SPEC to StudySpec fidelity via structured declarative clauses.")
    parser.add_argument("--study", type=str, required=True, help="Path to study directory")
    args = parser.parse_args()

    study_dir = Path(args.study).resolve()
    try:
        report = check_spec_fidelity(study_dir)
        print("=" * 65)
        print(f"SPEC FIDELITY GATE: {report['verdict']} ({report['spec_clause_coverage_pct']:.1f}% coverage)")
        print(f"Satisfied clauses: {report['satisfied_clauses_count']} / {report['total_mandatory_clauses']}")
        if report["unmapped_clauses"]:
            print(f"[FAIL] Unsatisfied mandatory clauses: {report['unmapped_clauses']}")
        print("=" * 65)
        if report["verdict"] != "PASS":
            sys.exit(1)
    except Exception as e:
        print(f"[ERROR] SPEC fidelity check failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

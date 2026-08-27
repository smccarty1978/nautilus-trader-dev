"""Executable structured causal review for the public workflow."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def _context(study_path: str | Path) -> tuple[Path, str]:
    study = Path(study_path).resolve()
    frozen = json.loads((study / "audit" / "frozen_execution_manifest.json").read_text(encoding="utf-8"))
    composite = frozen.get("frozen_execution_composite_sha256")
    if not composite:
        raise RuntimeError("FROZEN_COMPOSITE_MISSING")
    from scripts.resolve_execution_manifest import resolve_execution_manifest
    current, _, _ = resolve_execution_manifest(study)
    if current != composite:
        raise RuntimeError(f"STALE_FREEZE: current={current} frozen={composite}")
    return study, composite


def _check_derived_input_availability(compiled: dict[str, Any]) -> dict[str, Any]:
    """Causal audit's own re-derivation of the decision-time ordering check (defense in
    depth against a hand-edited compiled_study.json bypassing the StudySpec validator).

    Never "is it one of the three enum values" alone: an availability_reference/
    decision_reference outside TIMESTAMP_CAUSAL_ORDER is UNRESOLVED_RELATIVE_ORDERING or
    AMBIGUOUS_TIMESTAMP_SEMANTICS, and an input available strictly after the study's own
    decision point is AVAILABILITY_AFTER_DECISION -- three distinct, named failures.
    """
    from research.schemas.study_spec import TIMESTAMP_CAUSAL_ORDER

    spec = compiled.get("spec", {}) or {}
    target = spec.get("target", {}) or {}
    features = spec.get("features", {}) or {}
    decision_reference = target.get("decision_reference", "decision_ts")
    derived_inputs = features.get("derived_inputs") or []

    if decision_reference not in TIMESTAMP_CAUSAL_ORDER:
        return {"name": "derived_input_availability_causal", "passed": False,
                "reason": "AMBIGUOUS_TIMESTAMP_SEMANTICS", "detail": decision_reference}
    decision_idx = TIMESTAMP_CAUSAL_ORDER[decision_reference]

    for di in derived_inputs:
        avail = di.get("availability_reference")
        if avail not in TIMESTAMP_CAUSAL_ORDER:
            return {"name": "derived_input_availability_causal", "passed": False,
                    "reason": "UNRESOLVED_RELATIVE_ORDERING", "detail": {"input": di.get("name"), "availability_reference": avail}}
        if TIMESTAMP_CAUSAL_ORDER[avail] > decision_idx:
            return {"name": "derived_input_availability_causal", "passed": False,
                    "reason": "AVAILABILITY_AFTER_DECISION",
                    "detail": {"input": di.get("name"), "availability_reference": avail, "decision_reference": decision_reference}}
    return {"name": "derived_input_availability_causal", "passed": True, "checked": len(derived_inputs)}


def _check_composite_target_label_only(compiled: dict[str, Any]) -> dict[str, Any]:
    """Proves every column a composite target's excursion/return conditions generate is
    accounted for by the SAME closed taxonomy that already protects forward-outcome
    tables: either a causal identity column, or a genuine outcome-pattern column. Never
    a second, hand-rolled leakage scanner -- reuses forward_outcomes.guard directly.
    """
    from research_workflow.forward_outcomes.guard import CAUSAL_IDENTITY_COLUMNS, is_outcome_column

    target_contract = (compiled.get("contracts", {}) or {}).get("target_contract", {}) or {}
    required_fo = target_contract.get("required_forward_outcomes") or []
    unaccounted: list[str] = []
    total = 0
    for fo in required_fo:
        for col in fo.get("generated_outcome_columns", []):
            total += 1
            if col not in CAUSAL_IDENTITY_COLUMNS and not is_outcome_column(col):
                unaccounted.append(col)
    return {"name": "composite_target_label_only", "passed": not unaccounted,
            "checked_columns": total, "unaccounted": unaccounted}


def _run_checks(study: Path, composite: str) -> list[dict[str, Any]]:
    preflight = json.loads((study / "audit" / "preflight.json").read_text(encoding="utf-8"))
    readiness = json.loads((study / "audit" / "readiness.json").read_text(encoding="utf-8"))
    r10 = readiness.get("r10_real_nonempty_output_parity", {})
    compiled = json.loads((study / "compiled_study.json").read_text(encoding="utf-8"))
    instances = compiled.get("spec", {}).get("features", {}).get("instances", [])
    checks = [
        {"name": "preflight", "passed": preflight.get("status") == "CLEAR" and preflight.get("execution_composite_sha256") == composite},
        {"name": "readiness", "passed": readiness.get("overall_status") == "PASS"},
        {"name": "real_output_parity", "passed": bool(r10.get("passed")) and not r10.get("unexpected_columns")},
        {"name": "canonical_instances", "passed": bool(instances) and all("feature" in i and "parameters" in i for i in instances)},
        {"name": "legacy_runtime_excluded", "passed": all("legacy" not in str(i).lower() for i in instances)},
        _check_derived_input_availability(compiled),
        _check_composite_target_label_only(compiled),
    ]
    from scripts.causal_lint import scan_file
    findings = []
    for root in (study, Path(__file__).resolve().parent):
        for path in root.rglob("*.py"):
            if "_work" in path.parts or "tests" in path.parts:
                continue
            findings.extend(scan_file(path))
    critical = [f for f in findings if getattr(f, "severity", "").upper() == "CRITICAL"]
    checks.append({"name": "causal_lint", "passed": not critical, "critical_findings": len(critical)})
    return checks


def _write_and_issue(study: Path, composite: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    passed = all(c["passed"] for c in checks)
    audit = study / "audit"; audit.mkdir(exist_ok=True)
    payload = {"audit_type": "causal", "auditor": "research_workflow.causal_audit", "study": study.name,
               "verdict": "CLEAR" if passed else "BLOCKED", "critical": 0 if passed else 1,
               "warning": 0, "note": 0, "audited_execution_composite_sha256": composite}
    report = "# Causal Review\n\n" + json.dumps({"checks": checks}, indent=2) + "\n\n" \
        + "<!-- AUDIT_SUMMARY_V2_START -->\n" + json.dumps(payload) \
        + "\n<!-- AUDIT_SUMMARY_V2_END -->\n"
    pass_num = max([int(p.stem.split("_")[-1]) for p in audit.glob("pass_*.md") if p.stem.split("_")[-1].isdigit()] or [0]) + 1
    report_path = audit / f"pass_{pass_num:02d}.md"
    report_path.write_text(report, encoding="utf-8")
    if not passed:
        return {"status": "BLOCKED", "checks": checks, "artifact_path": str(report_path)}
    from scripts.run_preexec_audits import issue_causal_audit_status_from_report
    status = issue_causal_audit_status_from_report(study, pass_num, auditor="research_workflow.causal_audit")
    return {"status": "CLEAR", "checks": checks, "evidence": status,
            "artifact_path": str(study / "audit" / "status.json")}


def run_causal_review(study_path: str | Path, **_: Any) -> dict[str, Any]:
    study = Path(study_path).resolve()
    if (study / "feature_candidate.yaml").is_file() and not (study / "study.yaml").is_file():
        try:
            from research_workflow.feature_candidate_authority import validate
            from scripts.resolve_execution_manifest import resolve_execution_manifest
            authority = validate(study / "feature_candidate.yaml")
            frozen = json.loads((study / "audit" / "frozen_execution_manifest.json").read_text(encoding="utf-8"))
            composite = frozen.get("frozen_execution_composite_sha256")
            current, _, _ = resolve_execution_manifest(study, feature_authority="candidate", authority_type="feature_candidate")
            if not composite or current != composite:
                raise RuntimeError(f"STALE_FREEZE: current={current} frozen={composite}")
            checks = [{"name": "authority_schema", "passed": True},
                      {"name": "completed_availability_declared", "passed": authority["semantics"].get("bar_state") == "completed"},
                      {"name": "promotion_scope_declared", "passed": bool(authority.get("promotion_scope"))},
                      {"name": "future_scope_excluded", "passed": "train_oos_data" in authority.get("prohibited_scope_expansion", [])}]
            passed = all(c["passed"] for c in checks)
            audit_dir = study / "audit"; audit_dir.mkdir(exist_ok=True)
            n = max([int(p.stem.split("_")[-1]) for p in audit_dir.glob("pass_*.md") if p.stem.split("_")[-1].isdigit()] or [0]) + 1
            payload = {"audit_type":"causal", "auditor":"research_workflow.causal_audit", "study":study.name,
                       "feature_authority":"candidate", "authority_type":"feature_candidate", "authority_id":authority["authority_id"],
                       "verdict":"CLEAR" if passed else "BLOCKED", "critical":0 if passed else 1, "warning":0,
                       "audited_execution_composite_sha256":composite}
            report = "# Feature Candidate Causal Review\n\n" + json.dumps({"checks":checks}, indent=2) + "\n\n<!-- AUDIT_SUMMARY_V2_START -->\n" + json.dumps(payload) + "\n<!-- AUDIT_SUMMARY_V2_END -->\n"
            (audit_dir / f"pass_{n:02d}.md").write_text(report, encoding="utf-8")
            from scripts.run_preexec_audits import issue_causal_audit_status_from_report
            evidence = issue_causal_audit_status_from_report(study, n, auditor="research_workflow.causal_audit") if passed else None
            return {"status":"CLEAR" if passed else "BLOCKED", "checks":checks, "frozen_composite":composite, "evidence":evidence}
        except Exception as exc:
            return {"status":"BLOCKED", "study":str(study), "findings":[str(exc)], "artifact_path":None}
    try:
        study, composite = _context(study)
        result = _write_and_issue(study, composite, _run_checks(study, composite))
        result.update({"study": str(study), "frozen_composite": composite})
        return result
    except Exception as exc:
        return {"status": "BLOCKED", "study": str(study), "findings": [str(exc)], "artifact_path": None}


__all__ = ["run_causal_review"]

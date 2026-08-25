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
    try:
        study, composite = _context(study)
        result = _write_and_issue(study, composite, _run_checks(study, composite))
        result.update({"study": str(study), "frozen_composite": composite})
        return result
    except Exception as exc:
        return {"status": "BLOCKED", "study": str(study), "findings": [str(exc)], "artifact_path": None}


__all__ = ["run_causal_review"]

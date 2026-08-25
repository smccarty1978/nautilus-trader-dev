"""Executable structured contract review for the public workflow."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def run_contract_review(study_path: str | Path, **_: Any) -> dict[str, Any]:
    study = Path(study_path).resolve()
    try:
        frozen = json.loads((study / "audit" / "frozen_execution_manifest.json").read_text(encoding="utf-8"))
        composite = frozen.get("frozen_execution_composite_sha256")
        from scripts.resolve_execution_manifest import resolve_execution_manifest
        current, _, _ = resolve_execution_manifest(study)
        if not composite or current != composite:
            raise RuntimeError(f"STALE_FREEZE: current={current} frozen={composite}")
        compiled = json.loads((study / "compiled_study.json").read_text(encoding="utf-8"))
        spec = compiled.get("spec", {})
        features = spec.get("features", {})
        instances = features.get("instances", [])
        checks = [
            {"name": "compiled_spec_present", "passed": bool(spec)},
            {"name": "explicit_feature_instances", "passed": len(instances) == 13 and all("feature" in i and "parameters" in i for i in instances)},
            {"name": "generic_collector_binding", "passed": "research_workflow.generic_collector" in str(spec.get("execution", {}))},
            {"name": "deliverables_contract", "passed": (study / "config" / "deliverables_contract.json").is_file()},
            {"name": "phase0_manifest", "passed": (study / "artifacts" / "phase0_source_manifest.json").is_file()},
            {"name": "legacy_aliases_excluded", "passed": all("legacy" not in str(i).lower() for i in instances)},
            {"name": "population_target_contracts", "passed": all((study / "config" / n).is_file() for n in ("population_contract.json", "target_contract.json"))},
        ]
        passed = all(c["passed"] for c in checks)
        audit = study / "audit"; audit.mkdir(exist_ok=True)
        payload = {"audit_type": "contract", "auditor": "research_workflow.contract_audit", "study": study.name,
                   "verdict": "CLEAR" if passed else "BLOCKED", "blocking": 0 if passed else 1,
                   "critical": 0 if passed else 1, "warning": 0, "not_verified": 0,
                   "audited_execution_composite_sha256": composite}
        report = "# Contract Review\n\n" + json.dumps({"checks": checks}, indent=2) + "\n\n" \
            + "<!-- AUDIT_SUMMARY_V2_START -->\n" + json.dumps(payload) \
            + "\n<!-- AUDIT_SUMMARY_V2_END -->\n"
        pass_num = max([int(p.stem.split("_")[-1]) for p in audit.glob("contract_pass_*.md") if p.stem.split("_")[-1].isdigit()] or [0]) + 1
        report_path = audit / f"contract_pass_{pass_num:02d}.md"
        report_path.write_text(report, encoding="utf-8")
        if not passed:
            return {"status": "BLOCKED", "checks": checks, "artifact_path": str(report_path)}
        from scripts.run_preexec_audits import issue_contract_audit_status_from_report
        status = issue_contract_audit_status_from_report(study, pass_num, auditor="research_workflow.contract_audit")
        return {"status": "CLEAR", "study": str(study), "frozen_composite": composite,
                "checks": checks, "evidence": status,
                "artifact_path": str(study / "audit" / "contract_status.json")}
    except Exception as exc:
        return {"status": "BLOCKED", "study": str(study), "findings": [str(exc)], "artifact_path": None}


__all__ = ["run_contract_review"]

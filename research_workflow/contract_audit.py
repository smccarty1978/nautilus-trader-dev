"""Executable structured contract review for the public workflow."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def _expected_feature_surface(study: Path, features: dict[str, Any]) -> dict[str, Any]:
    """Derive the expected feature surface from the study's own contracts.

    There is no correct constant here. A study declares its cardinality in
    ``features.selection.feature_count`` and its identities in ``features.instances``;
    phase zero records the *authorized* surface those instances resolved to. This
    compares the three against each other and never against a literal — a hardcoded
    count made this audit pass only for the one study it was written against.
    """
    instances = features.get("instances") or []
    declared_count = (features.get("selection") or {}).get("feature_count")

    if declared_count is None:
        count_matches, count_detail = True, "no selection.feature_count declared; cardinality not asserted"
    else:
        count_matches = len(instances) == int(declared_count)
        count_detail = f"declared selection.feature_count={declared_count}, instances={len(instances)}"

    # Resolve the declared instances through the canonical resolver -- the same one
    # phase zero records as the source of the authorized candidate universe.
    try:
        from features.registry import FeatureInstance, resolve_feature_instances
        resolved = resolve_feature_instances(
            features.get("source"),
            tuple(FeatureInstance(str(i["feature"]), dict(i.get("parameters", {})), i.get("physical_alias"))
                  for i in instances),
            legacy_mode=False,
        ) if instances else []
        declared_aliases = {item["physical_alias"] for item in resolved}
    except Exception as exc:  # a non-resolving instance is itself the finding
        return {"count_matches": count_matches, "count_detail": count_detail,
                "surface_matches": False, "surface_detail": f"instances do not resolve: {exc}"}

    if len(declared_aliases) != len(instances):
        return {"count_matches": count_matches, "count_detail": count_detail,
                "surface_matches": False,
                "surface_detail": f"{len(instances)} instances collapsed to {len(declared_aliases)} aliases"}

    manifest = study / "artifacts" / "phase0_source_manifest.json"
    if not manifest.is_file():
        return {"count_matches": count_matches, "count_detail": count_detail,
                "surface_matches": True,
                "surface_detail": f"{len(declared_aliases)} aliases resolved; no phase0 manifest to compare"}

    authorized = set(
        (json.loads(manifest.read_text(encoding="utf-8")).get("candidate_feature_universe") or {})
        .get("candidates") or {}
    )
    missing = sorted(authorized - declared_aliases)
    unexpected = sorted(declared_aliases - authorized)
    return {
        "count_matches": count_matches, "count_detail": count_detail,
        "surface_matches": not missing and not unexpected,
        "surface_detail": (f"declared {len(declared_aliases)} == authorized {len(authorized)}"
                           if not missing and not unexpected
                           else f"missing={missing[:5]} unexpected={unexpected[:5]}"),
    }


def _check_derived_causal_inputs_bound(study: Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Re-runs the provenance verification the compiler recorded; a compiled contract
    that no longer resolves against on-disk parent artifacts is not audit-clean."""
    derived = ((spec.get("features") or {}).get("derived_inputs")) or []
    if not derived:
        return {"name": "derived_causal_inputs_bound", "passed": True, "checked": 0}
    try:
        from research.schemas.study_spec import StudySpec
        from research_workflow.derived_inputs import verify_derived_causal_inputs

        full_spec = StudySpec.model_validate(spec)
        verify_derived_causal_inputs(full_spec, repo_root=study.parents[1])
        return {"name": "derived_causal_inputs_bound", "passed": True, "checked": len(derived)}
    except Exception as exc:
        return {"name": "derived_causal_inputs_bound", "passed": False, "detail": str(exc)}


def _check_required_gates_declared_and_bound(spec: dict[str, Any]) -> dict[str, Any]:
    """Structural check: every declared gate names a schema version and a non-empty,
    typed scope -- a bare-string or unversioned gate can never be verified as fresh."""
    gates = spec.get("required_gates") or []
    bad = [
        g.get("id") for g in gates
        if not g.get("artifact_schema_version") or not g.get("scope_fields") or not g.get("artifact_path")
    ]
    return {"name": "required_gates_declared_and_bound", "passed": not bad,
            "checked": len(gates), "malformed": bad}


def _check_model_selection_binding_present(study: Path, spec: dict[str, Any]) -> dict[str, Any]:
    """When a study declares a hyperparameter search, a selection manifest must exist
    once TRAIN freeze has happened -- checked leniently here (pre-freeze, the manifest
    legitimately does not exist yet); the hard refusal lives in
    modeling.freeze_train_artifacts, which this only cross-references."""
    selection = ((spec.get("model") or {}).get("selection")) or {}
    if selection.get("search_method", "none") == "none":
        return {"name": "model_selection_binding_present", "passed": True, "search_method": "none"}
    freeze_path = study / "artifacts" / "train_experiment_freeze.json"
    if not freeze_path.is_file():
        return {"name": "model_selection_binding_present", "passed": True,
                "detail": "TRAIN not yet frozen; nothing to bind yet"}
    manifest_path = study / "artifacts" / "model_selection_manifest.json"
    present = manifest_path.is_file()
    return {"name": "model_selection_binding_present", "passed": present,
            "detail": None if present else "TRAIN frozen but no model_selection_manifest.json found"}


def run_contract_review(study_path: str | Path, **_: Any) -> dict[str, Any]:
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
            candidates = authority.get("candidate_features") or []
            checks = [{"name":"authority_identity", "passed": authority.get("authority_type") == "feature_candidate" and bool(authority.get("authority_id"))},
                      {"name":"candidate_identities", "passed": bool(candidates) and all((x.get("canonical_name") or x.get("feature")) for x in candidates)},
                      {"name":"implementation_declared", "passed": bool(authority.get("implementation"))},
                      {"name":"evidence_requirements_declared", "passed": bool(authority.get("evidence_requirements"))},
                      {"name":"prohibited_scope_declared", "passed": bool(authority.get("prohibited_scope_expansion"))}]
            passed = all(c["passed"] for c in checks)
            audit = study / "audit"; audit.mkdir(exist_ok=True)
            n = max([int(p.stem.split("_")[-1]) for p in audit.glob("contract_pass_*.md") if p.stem.split("_")[-1].isdigit()] or [0]) + 1
            payload = {"audit_type":"contract", "auditor":"research_workflow.contract_audit", "study":study.name,
                       "feature_authority":"candidate", "authority_type":"feature_candidate", "authority_id":authority["authority_id"],
                       "verdict":"CLEAR" if passed else "BLOCKED", "blocking":0 if passed else 1, "critical":0 if passed else 1, "warning":0,
                       "audited_execution_composite_sha256":composite}
            report = "# Feature Candidate Contract Review\n\n" + json.dumps({"checks":checks}, indent=2) + "\n\n<!-- AUDIT_SUMMARY_V2_START -->\n" + json.dumps(payload) + "\n<!-- AUDIT_SUMMARY_V2_END -->\n"
            (audit / f"contract_pass_{n:02d}.md").write_text(report, encoding="utf-8")
            from scripts.run_preexec_audits import issue_contract_audit_status_from_report
            evidence = issue_contract_audit_status_from_report(study, n, auditor="research_workflow.contract_audit") if passed else None
            return {"status":"CLEAR" if passed else "BLOCKED", "checks":checks, "frozen_composite":composite, "evidence":evidence}
        except Exception as exc:
            return {"status":"BLOCKED", "study":str(study), "findings":[str(exc)], "artifact_path":None}
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
        surface = _expected_feature_surface(study, features)
        checks = [
            {"name": "compiled_spec_present", "passed": bool(spec)},
            {"name": "explicit_feature_instances",
             "passed": bool(instances) and all("feature" in i and "parameters" in i for i in instances)},
            {"name": "declared_instance_count_matches_contract", "passed": surface["count_matches"],
             "detail": surface["count_detail"]},
            {"name": "declared_surface_matches_authorized", "passed": surface["surface_matches"],
             "detail": surface["surface_detail"]},
            {"name": "generic_collector_binding", "passed": "research_workflow.generic_collector" in str(spec.get("execution", {}))},
            {"name": "deliverables_contract", "passed": (study / "config" / "deliverables_contract.json").is_file()},
            {"name": "phase0_manifest", "passed": (study / "artifacts" / "phase0_source_manifest.json").is_file()},
            {"name": "legacy_aliases_excluded", "passed": all("legacy" not in str(i).lower() for i in instances)},
            # Historically checked for standalone config/population_contract.json +
            # config/target_contract.json files; research_workflow.compiler.compile_study
            # no longer writes those (only compiled_study.json + config/
            # deliverables_contract.json) -- both segments are authoritatively present as
            # nested keys inside compiled_study.json's own "contracts" dict, which this
            # audit already loads. A study compiled with the current compiler was failing
            # this check unconditionally, on a convention no current code path produces.
            {"name": "population_target_contracts",
             "passed": bool((compiled.get("contracts") or {}).get("population_contract"))
                       and bool((compiled.get("contracts") or {}).get("target_contract"))},
            _check_derived_causal_inputs_bound(study, spec),
            _check_required_gates_declared_and_bound(spec),
            _check_model_selection_binding_present(study, spec),
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

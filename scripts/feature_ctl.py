#!/usr/bin/env python3
"""Minimal V2 canonical feature governance CLI: check and promote only."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable

from check_feature_promotion import (
    CANONICAL_PROMOTIONS_PATH,
    REPO_ROOT,
    canonical_definition_evidence,
    check_canonical_feature_promotions,
)


AUDIT_EVIDENCE = {
    "structural_regime_geometry": {
        "causal_audit_artifact": "studies/Codex_clean_maturity_flip_rolling_5m_productivity/audit/pass_26.md",
        "audited_execution_composite_sha256": "3be6c8711aad4639263ca26241347d5f9adf17b64dc693b9a89d8ad57788a090",
    },
    "rolling_productivity": {
        "causal_audit_artifact": "studies/Codex_clean_maturity_flip_rolling_5m_productivity/audit/pass_26.md",
        "audited_execution_composite_sha256": "3be6c8711aad4639263ca26241347d5f9adf17b64dc693b9a89d8ad57788a090",
    },
}


_PRIOR_REGIME = re.compile(r"^prior_(?P<timeframe>[1-9][0-9]*[sm])_regime_(?P<metric>.+)$")
_ROLLING = re.compile(r"^rolling_(?P<window>[1-9][0-9]*[sm])_(?P<metric>.+)$")


def missing_feature_yaml(request: str) -> str:
    """Return a copy/paste canonical-definition draft for a genuine miss."""
    return "\n".join((
        f"canonical_name: {request}",
        "family: ",
        "dtype: float64",
        "description: ",
        "formula: ",
        "provider:",
        "  module: ",
        "  callable: ",
        "parameters: []",
        "temporal_semantics:",
        "  supported_bar_states: [completed]",
        "  input_requirements: []",
        "normalization: study_contract",
        "null_policy: ",
        "reset_policy: ",
        "tests: []",
        "causal_requirements: ",
        "",
    ))


def resolve_request(request: str) -> Dict[str, Any]:
    """Resolve an existing canonical definition or a deterministic legacy alias.

    This is intentionally lifecycle-neutral: recognising an existing building
    block never promotes it, and an unknown name receives a YAML draft rather
    than a speculative new registry entry.
    """
    from features.registry import (
        CANONICAL_FEATURE_DEFINITIONS, FeatureInstance,
        LEGACY_FEATURE_INSTANCE_OVERRIDES, validate_feature_instance,
    )
    if request in LEGACY_FEATURE_INSTANCE_OVERRIDES:
        instance = LEGACY_FEATURE_INSTANCE_OVERRIDES[request]
        return {"result": "EXISTING_CANONICAL_FEATURE", "requested": request,
                "feature": instance.canonical_name, "parameters": validate_feature_instance(instance),
                "physical_alias": request, "resolution": "legacy_alias"}
    if request in CANONICAL_FEATURE_DEFINITIONS:
        return {"result": "EXISTING_CANONICAL_FEATURE", "requested": request,
                "feature": request, "parameters": {}, "physical_alias": None,
                "resolution": "canonical_name"}
    match = _PRIOR_REGIME.fullmatch(request)
    if match:
        canonical = f"regime_{match.group('metric')}"
        if canonical in CANONICAL_FEATURE_DEFINITIONS:
            instance = FeatureInstance(canonical, {
                "timeframe": match.group("timeframe"), "context": "prior", "bar_state": "completed",
            })
            try:
                parameters = validate_feature_instance(instance)
            except Exception as exc:
                return {"result": "PENDING_PROVIDER_CUTOVER", "requested": request,
                        "feature": canonical, "parameters": dict(instance.parameters),
                        "reason": str(exc)}
            return {"result": "EXISTING_CANONICAL_FEATURE", "requested": request,
                    "feature": canonical, "parameters": parameters,
                    "physical_alias": request, "resolution": "deterministic_alias"}
    match = _ROLLING.fullmatch(request)
    if match:
        canonical = f"rolling_{match.group('metric')}"
        if canonical in CANONICAL_FEATURE_DEFINITIONS:
            instance = FeatureInstance(canonical, {"window": match.group("window"), "update_every": "1s"})
            return {"result": "EXISTING_CANONICAL_FEATURE", "requested": request,
                    "feature": canonical, "parameters": validate_feature_instance(instance),
                    "physical_alias": request, "resolution": "deterministic_alias"}
    return {"result": "MISSING_CANONICAL_FEATURE", "requested": request,
            "yaml_template": missing_feature_yaml(request)}


def _select(features: Iterable[str] | None, family: str | None) -> Dict[str, Any]:
    from features.registry import CANONICAL_FEATURE_DEFINITIONS
    selected = dict(CANONICAL_FEATURE_DEFINITIONS)
    if features:
        requested = set(features)
        missing = sorted(requested - set(selected))
        if missing:
            raise ValueError(f"UNKNOWN_CANONICAL_FEATURE: {missing}")
        selected = {name: selected[name] for name in requested}
    if family:
        selected = {name: definition for name, definition in selected.items() if definition.family == family}
        if not selected:
            raise ValueError(f"UNKNOWN_FEATURE_FAMILY: {family!r}")
    return selected


def check(features: Iterable[str] | None = None, family: str | None = None) -> Dict[str, Any]:
    from features.registry import validate_canonical_feature_name
    selected = _select(features, family)
    report = check_canonical_feature_promotions(repo_root=REPO_ROOT, require_promoted=False)
    selected_names = set(selected)
    report["features"] = sorted(selected)
    report["violations"] = [v for v in report["violations"] if v.get("feature") in selected_names]
    for name, definition in selected.items():
        try:
            validate_canonical_feature_name(definition)
        except Exception as exc:
            report["violations"].append({"feature": name, "code": "FEATURE_NAME_EMBEDS_TEMPORAL_INSTANCE", "message": str(exc)})
    report["passed"] = not report["violations"]
    return report


def promote(features: Iterable[str] | None = None, family: str | None = None) -> Dict[str, Any]:
    selected = _select(features, family)
    checked = check(selected, None)
    if not checked["passed"]:
        return checked
    existing: Dict[str, Dict[str, Any]] = {}
    if CANONICAL_PROMOTIONS_PATH.exists():
        existing = {r["feature"]: r for r in json.loads(CANONICAL_PROMOTIONS_PATH.read_text(encoding="utf-8")).get("promotions", [])}
    for name, definition in selected.items():
        evidence = canonical_definition_evidence(name, definition, REPO_ROOT)
        audit = AUDIT_EVIDENCE.get(definition.family)
        if audit is None:
            raise ValueError(f"PROMOTION_AUDIT_EVIDENCE_ABSENT: {definition.family}")
        existing[name] = {
            "feature": name,
            "causal_audit_artifact": audit["causal_audit_artifact"],
            "audited_execution_composite_sha256": audit["audited_execution_composite_sha256"],
            "promoted_by": "feature_ctl promote",
            "reviewed_implementation_sha256": evidence["implementation_sha256"],
            "test_evidence": evidence["structural_coverage"],
            "supported_parameter_schema": list(definition.parameter_schema),
        }
    payload = {"schema_version": 2, "promotions": [existing[name] for name in sorted(existing)]}
    CANONICAL_PROMOTIONS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return check_canonical_feature_promotions(repo_root=REPO_ROOT, require_promoted=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Canonical Feature System V2 governance")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "promote"):
        item = sub.add_parser(command)
        item.add_argument("--feature", action="append")
        item.add_argument("--family")
        item.add_argument("--request", action="append", help="Resolve a canonical/legacy/deterministic feature request")
    args = parser.parse_args()
    if args.request:
        if args.command != "check":
            parser.error("--request is supported by feature_ctl check only")
        report = {"passed": True, "requests": [resolve_request(request) for request in args.request]}
    else:
        report = check(args.feature, args.family) if args.command == "check" else promote(args.feature, args.family)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

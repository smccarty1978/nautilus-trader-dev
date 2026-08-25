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


def resolve_request(request: str, *, legacy_mode: bool = False) -> Dict[str, Any]:
    """Resolve an existing canonical definition or a deterministic legacy alias.

    This is intentionally lifecycle-neutral: recognising an existing building
    block never promotes it, and an unknown name receives a YAML draft rather
    than a speculative new registry entry.
    """
    from features.candidate_authority import ACTIVE_POINTER, load_authority
    from features.registry import resolve_feature_request
    if legacy_mode:
        resolved = resolve_feature_request(request, authority="legacy")
        return {"result": "LEGACY_REPLAY_FEATURE", "requested": request,
                "feature": resolved["canonical_name"], "parameters": resolved["parameters"],
                "physical_alias": resolved["physical_alias"], "resolution": "explicit_legacy_replay",
                "legacy_mode": True}
    authority = "active" if ACTIVE_POINTER.is_file() else "candidate"
    bundle = load_authority(authority)
    canonical_names = {item["canonical_name"] for item in bundle["registry"]["definitions"]}
    aliases = bundle["aliases"]["aliases"]
    # Canonical vocabulary is always first: a request for a building block is
    # not rewritten through a historical alias.
    if request in canonical_names:
        return {"result": "EXISTING_CANONICAL_FEATURE", "requested": request,
                "feature": request, "parameters": {}, "physical_alias": None,
                "resolution": "canonical_name"}
    # Explicit V2 legacy overrides carry already-audited compatibility details.
    if request in aliases:
        record = aliases[request]
        return {"result": "LEGACY_ALIAS", "requested": request,
                "feature": record["canonical_feature"], "parameters": record.get("parameters", {}),
                "physical_alias": request, "resolution": "legacy_migration_guidance",
                "error": "LEGACY_FEATURE_ALIAS_NOT_ALLOWED",
                "guidance": "declare the canonical feature and parameters in the study"}
    match = _PRIOR_REGIME.fullmatch(request)
    if match:
        canonical = f"regime_{match.group('metric')}"
        if canonical in canonical_names:
            result = {"result": "EXISTING_CANONICAL_FEATURE", "requested": request,
                    "feature": canonical, "parameters": {"timeframe": match.group("timeframe"),
                    "context": "prior", "bar_state": "completed"},
                    "physical_alias": request, "resolution": "deterministic_alias"}
            if not ACTIVE_POINTER.is_file():
                result["execution_status"] = "STAGED_PROVIDER_PENDING_AUTHORITY_CUTOVER"
            return result
    match = _ROLLING.fullmatch(request)
    if match:
        canonical = f"rolling_{match.group('metric')}"
        if canonical in canonical_names:
            return {"result": "EXISTING_CANONICAL_FEATURE", "requested": request,
                    "feature": canonical, "parameters": {"window": match.group("window"), "update_every": "1s"},
                    "physical_alias": request, "resolution": "deterministic_alias"}
    return {"result": "MISSING_CANONICAL_FEATURE", "requested": request,
            "yaml_template": missing_feature_yaml(request)}


def _select(features: Iterable[str] | None, family: str | None) -> Dict[str, Any]:
    from features.candidate_authority import ACTIVE_POINTER, load_authority
    bundle = load_authority("active" if ACTIVE_POINTER.is_file() else "candidate")
    selected = {item["canonical_name"]: item for item in bundle["registry"]["definitions"]}
    if features:
        requested = set(features)
        missing = sorted(requested - set(selected))
        if missing:
            raise ValueError(f"UNKNOWN_CANONICAL_FEATURE: {missing}")
        selected = {name: selected[name] for name in requested}
    if family:
        selected = {name: definition for name, definition in selected.items() if family in definition.get("family", [])}
        if not selected:
            raise ValueError(f"UNKNOWN_FEATURE_FAMILY: {family!r}")
    return selected


def check(features: Iterable[str] | None = None, family: str | None = None) -> Dict[str, Any]:
    selected = _select(features, family)
    from features.candidate_authority import ACTIVE_POINTER, load_authority
    bundle = load_authority("active" if ACTIVE_POINTER.is_file() else "candidate")
    facts = {item["canonical_name"]: item for item in bundle["promotion_facts"]["definitions"]}
    report = {"features": sorted(selected), "violations": []}
    for name, definition in selected.items():
        if definition.get("status") != "verified" or facts.get(name, {}).get("lifecycle_status") != "verified":
            report["violations"].append({"feature": name, "code": "PROMOTION_FACTS_INCOMPLETE", "message": "canonical definition is not verified"})
        if re.search(r"(?:^|_)(?:[0-9]+[sm]|ema_[0-9]+|atr_[0-9]+|median_[0-9]+)(?:_|$)", name):
            report["violations"].append({"feature": name, "code": "FEATURE_NAME_EMBEDS_TEMPORAL_INSTANCE", "message": "canonical names must be parameterized"})
    report["passed"] = not report["violations"]
    return report


def promote(features: Iterable[str] | None = None, family: str | None = None) -> Dict[str, Any]:
    # Candidate promotion facts are mechanically materialized with the
    # canonical bundle.  This command validates that evidence; it never makes
    # per-alias promotion records or mutates active authority.
    return check(features, family)


def main() -> int:
    parser = argparse.ArgumentParser(description="Canonical Feature System V2 governance")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "promote"):
        item = sub.add_parser(command)
        item.add_argument("--feature", action="append")
        item.add_argument("--family")
        item.add_argument("--request", action="append", help="Resolve a canonical/legacy/deterministic feature request")
        item.add_argument("--legacy-study", action="store_true", help="Explicitly resolve archived legacy aliases for historical replay")
    args = parser.parse_args()
    if args.request:
        if args.command != "check":
            parser.error("--request is supported by feature_ctl check only")
        report = {"passed": True, "requests": [resolve_request(request, legacy_mode=args.legacy_study) for request in args.request]}
    else:
        report = check(args.feature, args.family) if args.command == "check" else promote(args.feature, args.family)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

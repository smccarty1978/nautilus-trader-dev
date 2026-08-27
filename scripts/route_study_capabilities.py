#!/usr/bin/env python3
"""Deterministically route a study capability request.

This utility only reports mechanical registry/authority facts.  It deliberately
does not infer semantic equivalence; unknown concepts are sent to the semantic
capability-router.
"""
from __future__ import annotations

import argparse, json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _load(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return json.loads(path.read_text(encoding="utf-8"))

def route(request: dict[str, Any], *, repo_root: Path = ROOT) -> dict[str, list[dict[str, Any]]]:
    from features.registry import CANONICAL_FEATURE_DEFINITIONS, validate_feature_instance
    requested = request.get("capabilities", request.get("features", request.get("candidate_features", [])))
    if isinstance(requested, dict):
        requested = requested.get("instances", [])
    out = {k: [] for k in (
        "EXISTING_VERIFIED", "FEATURE_PARAMETER_VERIFICATION",
        "NEW_CANONICAL_FEATURE", "GENERIC_PROVIDER_EXTENSION",
        "GENERIC_COLLECTOR_EXTENSION", "STUDY_LOCAL_BESPOKE",
        "SEMANTIC_REVIEW_REQUIRED", "TRUE_CAPABILITY_GAP")}
    for raw in requested:
        item = dict(raw) if isinstance(raw, dict) else {"feature": str(raw)}
        name = item.get("feature") or item.get("canonical_name") or item.get("name")
        params = dict(item.get("parameters") or {})
        fact = {"feature": name, "parameters": params}
        definition = CANONICAL_FEATURE_DEFINITIONS.get(str(name)) if name else None
        if definition is None:
            # A machine-readable request may explicitly identify a reusable
            # extension; otherwise semantic identity cannot be proven here.
            kind = item.get("requested_route")
            out["GENERIC_PROVIDER_EXTENSION" if kind == "generic_provider" else
                "GENERIC_COLLECTOR_EXTENSION" if kind == "generic_collector" else
                "STUDY_LOCAL_BESPOKE" if kind == "study_local_bespoke" else
                "TRUE_CAPABILITY_GAP" if (kind == "true_capability_gap" or item.get("capability_gap")) else
                "SEMANTIC_REVIEW_REQUIRED"].append(fact)
            continue
        try:
            from features.registry import FeatureInstance
            validate_feature_instance(FeatureInstance(str(name), params))
            from features.candidate_authority import load_authority, ACTIVE_POINTER
            is_active_verified = False
            if ACTIVE_POINTER.is_file():
                try:
                    active_bundle = load_authority("active")
                    active_verified = {
                        d.get("canonical_name") for d in active_bundle["registry"].get("definitions", [])
                        if d.get("status") == "verified"
                    }
                    is_active_verified = str(name) in active_verified
                except Exception:
                    pass
            status = "verified" if (is_active_verified or getattr(definition, "status", "provisional") == "verified") else "provisional"
            if status == "verified":
                out["EXISTING_VERIFIED"].append(fact)
            else:
                out["FEATURE_PARAMETER_VERIFICATION" if params else "NEW_CANONICAL_FEATURE"].append(
                    {**fact, "lifecycle_state": status, "provider": definition.implementation})
        except Exception as exc:
            # The name is known, but this exact parameter instance is not
            # currently verified/supported.  Keep the reason deterministic.
            if params:
                out["FEATURE_PARAMETER_VERIFICATION"].append({**fact, "reason": str(exc)})
            else:
                out["NEW_CANONICAL_FEATURE"].append({**fact, "reason": str(exc)})
    return out

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--request", required=True, type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = route(_load(args.request))
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

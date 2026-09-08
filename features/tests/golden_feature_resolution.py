"""Golden feature-resolution snapshot: the proof that the registration-boundary split changed nothing.

Every value a consumer of ``features.registry`` can observe is captured here as data.  The
snapshot is generated from the tree (``python -m features.tests.golden_feature_resolution``)
and compared byte for byte by ``features/tests/test_feature_definition_boundary.py``.

It is deliberately exhaustive rather than representative: the whole point of a registration
boundary is the claim "adding a definition cannot change how an existing binding resolves",
and a sampled fixture cannot carry that claim.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "feature_resolution.json"


def _definition_record(definition: Any) -> Dict[str, Any]:
    from dataclasses import asdict
    return json.loads(json.dumps(asdict(definition), default=str))


def _call(fn, *args, **kwargs) -> Dict[str, Any]:
    """Record either the return value or the exact fail-closed error."""
    try:
        return {"ok": True, "value": json.loads(json.dumps(fn(*args, **kwargs), default=str))}
    except Exception as exc:          # noqa: BLE001 - the error IS the observable behaviour
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def build() -> Dict[str, Any]:
    from features import registry as R
    from features.registry import FeatureInstance

    snapshot: Dict[str, Any] = {"schema_version": 1}

    # ---- the definition catalogues themselves (membership, order, every field) ----------
    snapshot["FEATURE_REGISTRY"] = {name: _definition_record(d) for name, d in R.FEATURE_REGISTRY.items()}
    snapshot["FEATURE_REGISTRY_order"] = list(R.FEATURE_REGISTRY)
    snapshot["CANONICAL_FEATURE_DEFINITIONS"] = {name: _definition_record(d) for name, d in R.CANONICAL_FEATURE_DEFINITIONS.items()}
    snapshot["CANONICAL_FEATURE_DEFINITIONS_order"] = list(R.CANONICAL_FEATURE_DEFINITIONS)
    snapshot["LEGACY_FEATURE_INSTANCE_OVERRIDES"] = {
        alias: {"canonical_name": inst.canonical_name, "parameters": dict(inst.parameters), "physical_alias": inst.physical_alias}
        for alias, inst in R.LEGACY_FEATURE_INSTANCE_OVERRIDES.items()}
    snapshot["LEGACY_FEATURE_INSTANCE_OVERRIDES_order"] = list(R.LEGACY_FEATURE_INSTANCE_OVERRIDES)
    snapshot["_ALIAS_TO_CANONICAL"] = dict(R._ALIAS_TO_CANONICAL)

    # ---- per-canonical-definition resolution ------------------------------------------
    canonical: Dict[str, Any] = {}
    for name in sorted(R.CANONICAL_FEATURE_DEFINITIONS):
        canonical[name] = {
            "status": _call(R.canonical_definition_status, name),
            "request_active": _call(R.resolve_feature_request, name),
            "request_legacy": _call(R.resolve_feature_request, name, authority="legacy"),
            "validate_bare": _call(R.validate_feature_instance, FeatureInstance(name)),
            "alias_bare": _call(R.generate_physical_alias, FeatureInstance(name)),
            "inputs_bare": _call(R.derive_instance_input_requirements, FeatureInstance(name)),
            "compat_keys": _call(R.provider_compatibility_keys, name),
            "runtime_definition": _call(lambda n: _definition_record(R.resolve_runtime_feature_definition(n)), name),
        }
    snapshot["canonical"] = canonical

    # ---- per-legacy-alias resolution (the instance overrides carry real parameters) -----
    legacy: Dict[str, Any] = {}
    for alias in sorted(R.LEGACY_FEATURE_INSTANCE_OVERRIDES):
        inst = R.LEGACY_FEATURE_INSTANCE_OVERRIDES[alias]
        legacy[alias] = {
            "validate": _call(R.validate_feature_instance, inst),
            "alias": _call(R.generate_physical_alias, inst),
            "inputs": _call(R.derive_instance_input_requirements, inst),
            "request_active": _call(R.resolve_feature_request, alias),
            "request_legacy": _call(R.resolve_feature_request, alias, authority="legacy"),
            "instances_active": _call(R.resolve_feature_instances, "canonical_verified_definition_universe", (inst,)),
        }
    snapshot["legacy_instance_overrides"] = legacy

    # ---- every physical-catalogue entry, resolved both ways ----------------------------
    physical: Dict[str, Any] = {}
    for name in sorted(R.FEATURE_REGISTRY):
        physical[name] = {
            "request_active": _call(R.resolve_feature_request, name),
            "request_legacy": _call(R.resolve_feature_request, name, authority="legacy"),
            "resolve_name": _call(R.resolve_feature_name, name),
            "effective_snapshot_anchor": _call(R.effective_snapshot_anchor, name, "golden_study"),
        }
    snapshot["physical_catalogue"] = physical

    # ---- universe / alias surfaces -----------------------------------------------------
    sources = [None, "", "canonical_verified_definition_universe", "verified_registry_numeric_universe", "not_a_source"]
    universes: Dict[str, Any] = {}
    for source in sources:
        for authority in ("active", "candidate", "legacy", "bogus"):
            for legacy_mode in (False, True):
                universes[f"{source!r}|{authority}|{legacy_mode}"] = _call(
                    R.resolve_source_universe, source, authority=authority, legacy_mode=legacy_mode)
    snapshot["source_universes"] = universes
    snapshot["feature_instances"] = {
        f"{source!r}|{legacy_mode}": _call(R.resolve_feature_instances, source, None, legacy_mode=legacy_mode)
        for source in sources for legacy_mode in (False, True)}
    snapshot["runtime_feature_aliases"] = {
        a: _call(R.resolve_runtime_feature_aliases, authority=a) for a in ("active", "candidate", "legacy", "bogus")}
    snapshot["engine_output_aliases"] = {
        a: _call(R.resolve_feature_engine_output_aliases, authority=a) for a in ("active", "candidate", "legacy", "bogus")}

    families = sorted({d.family for d in R.FEATURE_REGISTRY.values() if d.family}
                      | {d.family for d in R.CANONICAL_FEATURE_DEFINITIONS.values() if d.family})
    snapshot["family_aliases"] = {f: _call(R.resolve_runtime_family_aliases, {f}) for f in families}
    snapshot["family_aliases_all"] = _call(R.resolve_runtime_family_aliases, set(families))

    # ---- provider column canonicalisation ---------------------------------------------
    columns = sorted(R.FEATURE_REGISTRY)[:40] + sorted(R.CANONICAL_FEATURE_DEFINITIONS)[:40] + ["not_a_column"]
    snapshot["canonicalize_provider_columns"] = _call(R.canonicalize_provider_columns, columns)

    # ---- the parameterised surface: every declared parameter value of every definition --
    parameterised: Dict[str, Any] = {}
    for name, definition in sorted(R.CANONICAL_FEATURE_DEFINITIONS.items()):
        cases: List[Dict[str, Any]] = [dict(combo) for combo in (definition.supported_parameter_combinations or ())]
        for key, values in sorted((definition.supported_parameter_values or {}).items()):
            for value in values:
                cases.append({key: value})
        for tf in definition.supported_timeframes or ():
            cases.append({"timeframe": tf})
            cases.append({"timeframe": tf, "bar_state": "forming", "update_every": "1s"})
        cases.append({"bogus_parameter": 1})
        seen = set()
        records = []
        for params in cases:
            key = json.dumps(params, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            inst = FeatureInstance(name, params)
            records.append({"parameters": json.loads(json.dumps(params, default=str)),
                            "validate": _call(R.validate_feature_instance, inst),
                            "alias": _call(R.generate_physical_alias, inst),
                            "inputs": _call(R.derive_instance_input_requirements, inst),
                            "request": _call(R.resolve_feature_request, name, params)})
        parameterised[name] = records
    snapshot["parameterised"] = parameterised

    # ---- study-level derivation (what the collector and the compiler actually call) -----
    class _Spec:
        def __init__(self, instances=None, feature_list=None):
            self.instances = instances
            self.feature_list = feature_list

    snapshot["study_derivations"] = {
        "empty": _call(R.derive_study_feature_requirements, _Spec()),
        "legacy_list": _call(R.derive_study_feature_requirements, _Spec(feature_list=sorted(R.LEGACY_FEATURE_INSTANCE_OVERRIDES))),
        "canonical_bare": _call(R.derive_study_feature_requirements,
                                _Spec(instances=[{"feature": n} for n in sorted(R.CANONICAL_FEATURE_DEFINITIONS)])),
        "canonical_parameterised": _call(
            R.derive_study_feature_requirements,
            _Spec(instances=[{"feature": inst.canonical_name, "parameters": dict(inst.parameters),
                              "physical_alias": inst.physical_alias}
                             for inst in R.LEGACY_FEATURE_INSTANCE_OVERRIDES.values()])),
        "unknown": _call(R.derive_study_feature_requirements, _Spec(instances=[{"feature": "not_a_feature"}])),
    }

    # ---- fail-closed cases that are the guard's and the compiler's contract -------------
    snapshot["errors"] = {
        "unknown_canonical": _call(R.resolve_feature_request, "definitely_not_a_feature"),
        "instance_shaped": _call(R.resolve_feature_request, "ema_21_slope"),
        "temporal_shaped": _call(R.resolve_feature_request, "prior_5m_regime_efficiency"),
        "unknown_authority": _call(R.resolve_feature_request, "regime_efficiency", authority="nope"),
        "unknown_parameter": _call(R.validate_feature_instance, FeatureInstance("regime_efficiency", {"nope": 1})),
        "forming_unsupported": _call(R.validate_feature_instance, FeatureInstance("regime_efficiency", {"timeframe": "5m", "bar_state": "forming"})),
        "ambiguous_temporal": _call(R.validate_feature_instance, FeatureInstance("regime_efficiency", {"timeframe": "5m", "update_every": "1s"})),
        "window_and_timeframe": _call(R.validate_feature_instance, FeatureInstance("rolling_giveback_atr", {"window": "300s", "timeframe": "5m", "update_every": "1s"})),
        "bad_duration": _call(R.validate_feature_instance, FeatureInstance("regime_efficiency", {"timeframe": "5x"})),
        "name_embeds_instance": _call(R.validate_canonical_feature_name, R.FeatureDefinition(name="ema_21_slope")),
        "name_clean": _call(R.validate_canonical_feature_name, R.FeatureDefinition(name="regime_efficiency")),
        "bind_unknown_anchor": _call(R.bind_snapshot_anchor, "definitely_not_a_feature", "s", "at_fill_time"),
    }
    return snapshot


def _sha(value: Any) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# Sections small and diagnostic enough to keep verbatim: when one of these moves, the test
# shows the actual before/after rather than a hash.
_VERBATIM = ("schema_version", "errors", "FEATURE_REGISTRY_order", "CANONICAL_FEATURE_DEFINITIONS_order",
             "LEGACY_FEATURE_INSTANCE_OVERRIDES_order", "_ALIAS_TO_CANONICAL", "study_derivations")


def manifest(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """One digest per resolvable name, so a failure names the binding that moved.

    The full snapshot is ~2.7 MB of resolver output; committing digests keyed by the thing
    that was resolved keeps the fixture reviewable while losing none of its coverage --
    ``--full`` regenerates the whole snapshot for diffing when one of them fails.
    """
    out: Dict[str, Any] = {"verbatim": {k: snapshot[k] for k in _VERBATIM if k in snapshot}}
    digests: Dict[str, Dict[str, str]] = {}
    for section, body in snapshot.items():
        if section in _VERBATIM:
            continue
        if isinstance(body, dict):
            digests[section] = {str(k): _sha(v) for k, v in body.items()}
        else:
            digests[section] = {"": _sha(body)}
    out["digests"] = digests
    out["composite_sha256"] = _sha({"verbatim": out["verbatim"], "digests": digests})
    return out


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full", type=Path, help="also write the whole uncompressed snapshot here (for diffing)")
    args = ap.parse_args()
    snapshot = build()
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(manifest(snapshot), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN_PATH} ({GOLDEN_PATH.stat().st_size} bytes)")
    if args.full:
        args.full.parent.mkdir(parents=True, exist_ok=True)
        args.full.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.full} ({args.full.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

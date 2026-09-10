"""Feature resolution boundary: the one API the host, the outcome guard, the output manager,
the collector, the compiler and phase 0 call to turn a requested name into a bound feature.

This module is a **registration boundary** (``docs/RESEARCH_WORKFLOW.md`` §21.14):

* it exposes a stable resolution API that consumers import (``resolve_feature_request``,
  ``resolve_feature_instances``, ``resolve_source_universe``, ``derive_study_feature_requirements``
  and friends), and
* it discovers feature definitions through the declared capability index
  (``research_workflow/capabilities_index.d/feature_definitions.yaml``), importing each
  declared module by dotted path -- it never statically imports one.

The second clause is what makes the boundary a fact rather than a claim: adding a definition
edits a module that no consumer reaches, so it cannot change how an existing binding resolves.
The proof is ``features/tests/test_feature_definition_boundary.py`` (golden resolution across
every registered name, plus the import-graph condition).

Membership, lifecycle and alias identity for ACTIVE resolution still come from the activated
canonical authority bundle (``features/authority/``), exactly as before; the definition modules
are the compatibility catalogue and the canonical declaration source behind it.
"""
from __future__ import annotations

import hashlib
import importlib
import warnings
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from features.feature_types import (FeatureDefinition, FeatureInstance, FeatureInstanceError,
                                    _DURATION_RE, _INSTANCE_NAME_RE, _TEMPORAL_NAME_RE,
                                    _duration_seconds)

_INDEX_PATH = (Path(__file__).resolve().parents[1] / "research_workflow" / "capabilities_index.d"
               / "feature_definitions.yaml")
_KIND = "feature_definitions"
_CANONICAL_PROMOTIONS_PATH = Path(__file__).with_name("feature_definition_promotions.json")

# The three catalogues a definition module may contribute. A module declares any subset of them
# as plain module-level dicts; the resolver merges them in the index's declared order.
_CONTRIBUTIONS = ("FEATURE_REGISTRY", "CANONICAL_FEATURE_DEFINITIONS", "LEGACY_FEATURE_INSTANCE_OVERRIDES")


def declared_definition_modules(index_path: Optional[Path] = None) -> Tuple[str, ...]:
    """Dotted paths of the definition modules the capability index declares, in declared order.

    Fail-closed: an index that declares none is a broken tree, not an empty registry.
    """
    import yaml
    path = Path(index_path) if index_path is not None else _INDEX_PATH
    try:
        seed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise FeatureInstanceError(f"FEATURE_DEFINITION_INDEX_UNREADABLE: {path}: {exc}") from exc
    modules = tuple(str(e["implementation"]) for e in (seed.get(_KIND) or []) if e.get("implementation"))
    if not modules:
        raise FeatureInstanceError(f"FEATURE_DEFINITION_INDEX_EMPTY: {path} declares no {_KIND}")
    return modules


def definition_files(index_path: Optional[Path] = None) -> Tuple[str, ...]:
    """Repo-relative files of the declared definition modules, for the execution closure.

    A dynamically resolved definition module is invisible to the closure's import walk, so the
    compiler seeds these explicitly -- the closure covers exactly what it covered before the
    definitions were split out of this module.
    """
    repo_root = Path(__file__).resolve().parents[1]
    out = []
    for dotted in declared_definition_modules(index_path):
        candidate = repo_root.joinpath(*dotted.split("."))
        for p in (candidate.with_suffix(".py"), candidate / "__init__.py"):
            if p.is_file():
                out.append(p.resolve().relative_to(repo_root.resolve()).as_posix())
                break
        if (candidate / "__init__.py").is_file():
            # A catalogue package holds one record module per definition; each record is
            # data the package loads by filename, invisible to the import walk.
            out.extend(p.resolve().relative_to(repo_root.resolve()).as_posix()
                       for p in sorted(candidate.glob("*.py")) if p.name != "__init__.py")
    # Promotion evidence decides which catalogue definitions resolve as verified, so it is
    # part of what a study binds: the golden fixtures and the promotion records are seeded
    # alongside the definitions they vouch for (features/promotion.py).
    from features.promotion import evidence_files
    out.extend(evidence_files())
    return tuple(sorted(set(out)))


_CATALOGUES: Optional[Dict[str, Dict[str, Any]]] = None


def _catalogues() -> Dict[str, Dict[str, Any]]:
    """Merge every declared definition module, once, on first use.

    Resolution happens on access rather than at import so that a definition module importing
    anything from the feature package can never be a circular import -- the same shape B1 gave
    ``TRACKER_BINDINGS``.
    """
    global _CATALOGUES
    if _CATALOGUES is None:
        merged: Dict[str, Dict[str, Any]] = {name: {} for name in _CONTRIBUTIONS}
        for dotted in declared_definition_modules():
            try:
                module = importlib.import_module(dotted)
            except ImportError as exc:
                raise FeatureInstanceError(f"FEATURE_DEFINITION_MODULE_UNRESOLVED: {dotted}: {exc}") from exc
            contributed = False
            for name in _CONTRIBUTIONS:
                entries = getattr(module, name, None)
                if entries is not None:
                    merged[name].update(entries)
                    contributed = True
            if not contributed:
                raise FeatureInstanceError(
                    f"FEATURE_DEFINITION_MODULE_EMPTY: {dotted} declares none of {list(_CONTRIBUTIONS)}")
        _CATALOGUES = merged
    return _CATALOGUES


def _feature_registry() -> Dict[str, FeatureDefinition]:
    return _catalogues()["FEATURE_REGISTRY"]


def _canonical_definitions() -> Dict[str, FeatureDefinition]:
    return _catalogues()["CANONICAL_FEATURE_DEFINITIONS"]


def _instance_overrides() -> Dict[str, FeatureInstance]:
    return _catalogues()["LEGACY_FEATURE_INSTANCE_OVERRIDES"]


_ALIAS_CACHE: Optional[Dict[str, str]] = None


def _alias_to_canonical() -> Dict[str, str]:
    """Reverse mapping for alias lookup, derived from the merged physical catalogue."""
    global _ALIAS_CACHE
    if _ALIAS_CACHE is None:
        _ALIAS_CACHE = {alias: name for name, definition in _feature_registry().items()
                        for alias in definition.aliases}
    return _ALIAS_CACHE


def __getattr__(name: str) -> Any:
    """``FEATURE_REGISTRY`` & co. as module attributes, resolved on access.

    Existing consumers (and every historical test) read these names off this module; they keep
    working unchanged while the definitions themselves live outside it.
    """
    if name == "FEATURE_REGISTRY":
        return _feature_registry()
    if name == "CANONICAL_FEATURE_DEFINITIONS":
        return _canonical_definitions()
    if name == "LEGACY_FEATURE_INSTANCE_OVERRIDES":
        return _instance_overrides()
    if name == "_ALIAS_TO_CANONICAL":
        return _alias_to_canonical()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")



def canonical_definition_status(name: str) -> str:
    """Effective V2 lifecycle status backed by a generated promotion record."""
    definition = _canonical_definitions()[name]
    if definition.status == "verified":
        return "verified"
    try:
        import json
        records = json.loads(_CANONICAL_PROMOTIONS_PATH.read_text(encoding="utf-8")).get("promotions", [])
    except (OSError, ValueError):
        return definition.status
    record = next((item for item in records if isinstance(item, dict) and item.get("feature") == name), None)
    if record is None:
        return definition.status
    module = definition.implementation.rsplit(".", 1)[0]
    implementation_path = __import__("pathlib").Path(__file__).resolve().parents[1].joinpath(*module.split(".")).with_suffix(".py")
    try:
        implementation_hash = hashlib.sha256(implementation_path.read_bytes()).hexdigest()
    except OSError:
        return definition.status
    audit_path = __import__("pathlib").Path(__file__).resolve().parents[1] / str(record.get("causal_audit_artifact", ""))
    if (not audit_path.is_file() or not record.get("audited_execution_composite_sha256")
            or not record.get("promoted_by")
            or record.get("reviewed_implementation_sha256") != implementation_hash
            or list(record.get("supported_parameter_schema", ())) != list(definition.parameter_schema)):
        return definition.status
    return "verified"


def validate_feature_instance(instance: FeatureInstance) -> Dict[str, Any]:
    """Validate a canonical instance and return normalized parameters.

    The raw parameter membership check is important: a 1m request updated every second
    without an explicit bar_state is ambiguous, rather than silently becoming a completed
    bar request.
    """
    if instance.canonical_name not in _canonical_definitions():
        # The active V2 bundle is authoritative after cutover; the historical
        # Python catalog is intentionally only a compatibility surface.  Keep
        # validation fail-closed while accepting bundle definitions without
        # duplicating a second registry in code.
        bundle = _canonical_bundle("active")
        bundle_def = _canonical_definition_by_name(bundle, instance.canonical_name) if bundle else None
        if bundle_def is None:
            raise FeatureInstanceError(f"UNKNOWN_CANONICAL_FEATURE: {instance.canonical_name!r}")
        params = dict(instance.parameters)
        schema = set(bundle_def.get("parameter_schema", ()))
        unknown = sorted(set(params) - schema)
        if unknown:
            raise FeatureInstanceError(f"UNKNOWN_FEATURE_PARAMETER: {instance.canonical_name}: {unknown}")
        for state_key in ("bar_state", "source_bar_state", "reference_bar_state"):
            if state_key in schema:
                params.setdefault(state_key, "completed")
        for state_key in ("bar_state", "source_bar_state", "reference_bar_state"):
            if params.get(state_key) not in {None, "completed"}:
                raise FeatureInstanceError(
                    f"FORMING_BAR_UNSUPPORTED: {instance.canonical_name} supports completed bar states only"
                )
        return params
    definition = _canonical_definitions()[instance.canonical_name]
    params = dict(instance.parameters)
    if "timeframe" in params and "update_every" in params and "bar_state" not in params:
        raise FeatureInstanceError("AMBIGUOUS_TEMPORAL_SEMANTICS: timeframe plus update_every requires bar_state=forming, or declare a rolling window")
    # Bar-state defaults belong to definitions; a temporal update cadence is
    # separately validated below and cannot silently turn a calendar bar into
    # a forming stream.
    for state_key in ("bar_state", "source_bar_state", "reference_bar_state"):
        if state_key in definition.parameter_schema:
            params.setdefault(state_key, "completed")
    for state_key in ("bar_state", "source_bar_state", "reference_bar_state"):
        requested_bar_state = params.get(state_key)
        if requested_bar_state is None:
            continue
        if requested_bar_state not in {"completed", "forming"}:
            raise FeatureInstanceError("INVALID_BAR_STATE: expected 'completed' or 'forming'")
        if requested_bar_state not in definition.supported_bar_states:
            raise FeatureInstanceError(
                f"FORMING_BAR_UNSUPPORTED: {instance.canonical_name} supports "
                f"{list(definition.supported_bar_states)} bar states only"
            )
    # Reject an unimplemented temporal state before reporting incidental
    # parameter membership. This keeps the causal contract diagnostic exact.
    unknown = sorted(set(params) - set(definition.parameter_schema))
    if unknown:
        raise FeatureInstanceError(f"UNKNOWN_FEATURE_PARAMETER: {instance.canonical_name}: {unknown}")
    for key, allowed in definition.supported_parameter_values.items():
        if key in params and params[key] not in allowed:
            if (key in {"timeframe", "source_timeframe", "reference_timeframe"}
                    and params[key] not in definition.supported_timeframes):
                raise FeatureInstanceError(
                    f"UNSUPPORTED_TIMEFRAME_PARAMETER: {instance.canonical_name} supports "
                    f"{list(definition.supported_timeframes)}, not {params[key]!r}"
                )
            if key == "update_every":
                raise FeatureInstanceError(
                    f"UNSUPPORTED_UPDATE_CADENCE: {instance.canonical_name} supports "
                    f"{list(allowed)}, not {params[key]!r}"
                )
            raise FeatureInstanceError(
                f"UNSUPPORTED_FEATURE_PARAMETER_VALUE: {instance.canonical_name} "
                f"requires {key} in {list(allowed)}, not {params[key]!r}"
            )
    missing_required = [key for key in definition.required_parameters if key not in params]
    if missing_required:
        raise FeatureInstanceError(f"MISSING_REQUIRED_FEATURE_PARAMETER: {instance.canonical_name}: {missing_required}")
    if "timeframe" in params:
        _duration_seconds(str(params["timeframe"]))
        if definition.supported_timeframes and params["timeframe"] not in definition.supported_timeframes:
            raise FeatureInstanceError(
                f"UNSUPPORTED_TIMEFRAME_PARAMETER: {instance.canonical_name} supports "
                f"{list(definition.supported_timeframes)}, not {params['timeframe']!r}"
            )
        # Bar-state only defaults for features whose identity actually carries the
        # completed/forming choice.  Event-anchored geometry (e.g. "since 5s regime
        # flip") labels a timeframe but declares no ``bar_state`` parameter; injecting
        # one here made ``validate_feature_instance`` non-idempotent — re-validating its
        # own output tripped UNKNOWN_FEATURE_PARAMETER in the phase-0 double resolve.
        if "bar_state" in definition.parameter_schema:
            params.setdefault("bar_state", "completed")
        if params.get("bar_state") == "forming":
            if "update_every" not in params:
                raise FeatureInstanceError("FORMING_BAR_UPDATE_REQUIRED: forming calendar bars require update_every")
            if _duration_seconds(str(params["update_every"])) > _duration_seconds(str(params["timeframe"])):
                raise FeatureInstanceError("FORMING_BAR_UPDATE_INVALID: update_every cannot exceed timeframe")
        elif "update_every" in params:
            raise FeatureInstanceError("COMPLETED_BAR_UPDATE_FREQUENCY_INVALID: completed calendar bars update only on completion")
    if "window" in params:
        if "timeframe" in params:
            raise FeatureInstanceError("AMBIGUOUS_TEMPORAL_SEMANTICS: use either calendar timeframe or rolling window")
        _duration_seconds(str(params["window"]))
        if "update_every" not in params:
            raise FeatureInstanceError("ROLLING_WINDOW_UPDATE_REQUIRED: rolling windows require update_every")
        _duration_seconds(str(params["update_every"]))
        if definition.supported_update_every and params["update_every"] not in definition.supported_update_every:
            raise FeatureInstanceError(
                f"UNSUPPORTED_UPDATE_CADENCE: {instance.canonical_name} supports "
                f"{list(definition.supported_update_every)}, not {params['update_every']!r}"
            )
    for key in ("numerator_window", "denominator_window"):
        if key in params:
            _duration_seconds(str(params[key]))
    for key in ("source_timeframe", "reference_timeframe"):
        if key in params:
            _duration_seconds(str(params[key]))
            if definition.supported_timeframes and params[key] not in definition.supported_timeframes:
                raise FeatureInstanceError(
                    f"UNSUPPORTED_TIMEFRAME_PARAMETER: {instance.canonical_name} supports "
                    f"{list(definition.supported_timeframes)}, not {params[key]!r}"
                )
    if definition.supported_parameter_combinations and not any(
            all(params.get(key) == value for key, value in allowed.items())
            for allowed in definition.supported_parameter_combinations):
        raise FeatureInstanceError(
            f"UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: {instance.canonical_name}: {params}"
        )
    return params


# The ohlcv_est_delta family renders its window into the alias. Two-window comparisons
# each have their own historical spelling, so the template is keyed by canonical name;
# everything else in the family is "<name>_<window>". These templates are not invented --
# test_ohlcv_alias_parity asserts they reproduce every committed legacy alias of the
# family byte for byte, which is what makes it safe to extend them to new windows.
_OHLCV_PAIR_ALIAS_TEMPLATES: Dict[str, str] = {
    "vol_sum_vs_ratio": "vol_sum_{a}_vs_{b}_ratio",
    "est_delta_sum_minus_scaled": "est_delta_sum_{a}_minus_{b}_scaled",
    "est_delta_ratio_minus": "est_delta_ratio_{a}_minus_{b}",
}
_OHLCV_CONTEXT_PREFIX: Dict[str, str] = {"regime": "regime_", "RTH": "rth_", "bar": ""}


def _ohlcv_family_alias(name: str, params: Mapping[str, Any]) -> Optional[str]:
    """Render an ``ohlcv_est_delta`` instance, or None if this is not one of its shapes.

    The window IS part of this family's physical identity (``vol_sum_5s`` and
    ``vol_sum_300s`` are different columns), but it was previously dropped: every window
    of ``vol_sum`` rendered as the bare ``vol_sum``, so declaring more than one collapsed
    them into DUPLICATE_PHYSICAL_ALIAS and the family was undeclarable at more than one
    window. Gated on ``context`` so the ``pullback_1s`` spelling of ``range_atr``
    (``{scope: trailing, timeframe: 30s}`` -> ``range_30s_atr``) is untouched.
    """
    context = params.get("context")
    if context is None:
        return None
    if context in _OHLCV_CONTEXT_PREFIX:
        return f"{_OHLCV_CONTEXT_PREFIX[context]}{name}"
    if context != "rolling":
        return None
    timeframe, timeframe_2 = params.get("timeframe"), params.get("timeframe_2")
    if timeframe is None:
        return None
    if timeframe_2 is None:
        return f"{name}_{timeframe}"
    template = _OHLCV_PAIR_ALIAS_TEMPLATES.get(name)
    if template is not None:
        return template.format(a=timeframe, b=timeframe_2)
    # vol_mean / vol_max: "<name>_<bar granularity>_<window>" (vol_mean_1s_300s).
    return f"{name}_{timeframe}_{timeframe_2}"


def generate_physical_alias(instance: FeatureInstance) -> str:
    """Deterministically render a V2 instance, retaining explicit legacy aliases."""
    params = validate_feature_instance(instance)
    if instance.physical_alias:
        return instance.physical_alias
    name = instance.canonical_name
    if name.startswith("regime_") and "timeframe" in params:
        prefix = f"{params.get('context', 'current')}_{params['timeframe']}_"
        return f"{prefix}{name}"
    if name.startswith("rolling_") and "window" in params:
        return f"rolling_{params['window']}_{name[len('rolling_'):]}"
    if name == "trend_normalized_est_delta_sum" and "window" in params:
        return f"trend_normalized_est_delta_sum_{params['window']}"
    if name == "trend_normalized_est_delta_sum_ratio" and "numerator_window" in params:
        return (
            f"trend_normalized_est_delta_sum_ratio_{params['numerator_window']}"
            f"_vs_{params['denominator_window']}"
        )
    if name == "trend_normalized_est_delta_acceleration" and "short_window" in params:
        return f"trend_normalized_est_delta_acceleration_{params['short_window']}"
    ohlcv = _ohlcv_family_alias(name, params)
    if ohlcv is not None:
        return ohlcv
    if name.startswith("distance_to_completed_range_"):
        return f"distance_to_completed_{params['reference_timeframe']}_{name[len('distance_to_completed_range_'):]}"
    if name == "move_outside_completed_range":
        return f"{params.get('context', 'current')}_{params['source_timeframe']}_move_outside_completed_{params['reference_timeframe']}_range"
    return name


def derive_instance_input_requirements(instance: FeatureInstance) -> Dict[str, Any]:
    """Describe the runtime streams/availability contract derived from an instance."""
    params = validate_feature_instance(instance)
    definition = _canonical_definitions()[instance.canonical_name]
    if params.get("bar_state") == "forming":
        return {"provider": definition.implementation, "required_streams": ["completed_1s"],
                "calendar_timeframe": params["timeframe"], "bar_state": "forming",
                "update_every": params["update_every"]}
    rolling_legacy = params.get("context") == "rolling" and "timeframe" in params
    if "window" in params or rolling_legacy:
        window = params.get("window", params.get("timeframe"))
        return {"provider": definition.implementation, "required_streams": ["completed_1s"],
                "window_type": "rolling", "window": window, "update_every": params.get("update_every", "1s")}
    if "source_timeframe" in params or "reference_timeframe" in params:
        streams = []
        for key, state_key in (("source_timeframe", "source_bar_state"), ("reference_timeframe", "reference_bar_state")):
            if key in params:
                state = params.get(state_key, "completed")
                streams.append(f"{state}_{params[key]}")
        return {"provider": definition.implementation, "required_streams": sorted(set(streams)),
                "source_timeframe": params.get("source_timeframe"),
                "reference_timeframe": params.get("reference_timeframe"),
                "source_bar_state": params.get("source_bar_state", "completed"),
                "reference_bar_state": params.get("reference_bar_state", "completed")}
    return {"provider": definition.implementation, "required_streams": [f"completed_{params.get('timeframe', definition.source_timeframe)}"],
            "bar_state": params.get("bar_state", "completed")}


def resolve_feature_instances(source: Optional[str], instances: Optional[Tuple[FeatureInstance, ...]] = None, *, legacy_mode: bool = False) -> List[Dict[str, Any]]:
    """The single collection-time resolver used by compiler, phase0, runtime and output.

    Active resolution returns canonical definitions/instances only.  The historical
    physical universe is available solely through explicit ``legacy_mode``.
    """
    if not source:
        return []
    if source == "canonical_verified_definition_universe":
        bundle = _canonical_bundle("active")
        definitions = _active_definition_records(bundle)
        if instances is not None:
            resolved = []
            for instance in instances:
                params = validate_feature_instance(instance)
                definition = _canonical_definition_by_name(bundle, instance.canonical_name)
                if definition is None or definition.get("status") != "verified":
                    raise FeatureInstanceError(f"UNVERIFIED_CANONICAL_FEATURE: {instance.canonical_name}")
                resolved.append({"canonical_name": instance.canonical_name, "parameters": params,
                                 "physical_alias": generate_physical_alias(instance), "provider": definition.get("provider", ""),
                                 "status": "verified", "causal_input_requirements": definition.get("input_availability_contracts", [])})
            return sorted(resolved, key=lambda item: item["physical_alias"])
        return [{"canonical_name": item["canonical_name"], "parameters": {},
                 "physical_alias": item["canonical_name"], "provider": item.get("provider", ""),
                 "status": item.get("status"), "causal_input_requirements": item.get("input_availability_contracts", [])}
                for item in definitions if item.get("status") == "verified"]
    if source != "verified_registry_numeric_universe":
        raise ValueError(f"UNKNOWN_FEATURE_SOURCE: '{source}' is not a recognized features.source value")
    if not legacy_mode:
        raise FeatureInstanceError("LEGACY_FEATURE_ALIAS_NOT_ALLOWED: use canonical FeatureInstances or explicit legacy replay mode")
    resolved: List[Dict[str, Any]] = []
    if instances is not None:
        for instance in instances:
            params = validate_feature_instance(instance)
            definition = _canonical_definitions()[instance.canonical_name]
            if canonical_definition_status(instance.canonical_name) != "verified":
                raise FeatureInstanceError(f"UNVERIFIED_CANONICAL_FEATURE: {instance.canonical_name}")
            resolved.append({"canonical_name": instance.canonical_name, "parameters": params,
                             "physical_alias": generate_physical_alias(instance), "provider": definition.implementation,
                             "status": "verified", "causal_input_requirements": definition.update_anchor})
        return sorted(resolved, key=lambda item: item["physical_alias"])
    for name, definition in _feature_registry().items():
        if definition.status == "verified" and definition.dtype in _NUMERIC_DTYPES and definition.implementation.startswith("features."):
            resolved.append({"canonical_name": name, "parameters": {}, "physical_alias": name,
                             "provider": definition.implementation, "status": "verified",
                             "causal_input_requirements": definition.update_anchor})
    for alias, instance in _instance_overrides().items():
        canonical = instance.canonical_name
        if canonical_definition_status(canonical) == "verified":
            definition = _canonical_definitions()[canonical]
            resolved.append({"canonical_name": canonical, "parameters": validate_feature_instance(instance),
                             "physical_alias": alias, "provider": definition.implementation, "status": "verified",
                             "causal_input_requirements": definition.update_anchor})
    return sorted(resolved, key=lambda item: item["physical_alias"])



def resolve_feature_name(name: str) -> str:
    """
    Resolves any alias to its canonical target.
    
    If the name is a registered alias, it issues a DeprecationWarning.
    """
    if name in _alias_to_canonical():
        canonical = _alias_to_canonical()[name]
        warnings.warn(
            f"Feature alias {name!r} is deprecated. Use canonical name {canonical!r} instead.",
            category=DeprecationWarning,
            stacklevel=2
        )
        return canonical
    return name


# ---------------------------------------------------------------------------
# Collection-time source universe resolution (Phase 1 Packet D2)
#
# `StudySpec.features.source` names a collection-time candidate feature universe --
# distinct from the later frozen `features.feature_list` (a small, ordered, hash-pinned
# Top-N selection that exists only after TRAIN-stage feature selection). A study whose
# `source` is set but whose `feature_list` is still null is not missing configuration; it
# is correctly declaring "collect from this universe, freeze the model list later."
#
# "verified_registry_numeric_universe" is the exact filter already used to authenticate
# the collection-time candidate set elsewhere in the repo (see
# studies/Codex_clean_maturity_flip_rolling_5m_productivity/implementation/phase0.py
# :verified_numeric_candidates and that study's collector.py:BASELINE_CANDIDATES). This
# function gives the output-contract path (OutputManager, check_feature_surface) the same
# resolution without either of those study-local copies importing framework code, or the
# framework importing study-local code.
# ---------------------------------------------------------------------------
_NUMERIC_DTYPES = {"float64", "float32", "int64", "int32"}


def resolve_source_universe(source: Optional[str], *, authority: str = "active", legacy_mode: bool = False) -> List[str]:
    """Resolves a StudySpec `features.source` name to its collection-time candidate list.

    Returns ``[]`` when `source` is unset (``None``/empty) -- a study that has not
    declared a collection-time source is unaffected, not an error. An explicitly set but
    unrecognized `source` string fails closed rather than silently resolving to nothing.
    """
    if not source:
        return []
    # Candidate authority is explicit and inert by default. Once activation has
    # written the sole active pointer, the exact same resolver reads that
    # reviewed bundle; before then, active preserves the existing authority.
    from features.candidate_authority import ACTIVE_POINTER, resolve_candidate_aliases
    if source == "canonical_verified_definition_universe":
        bundle = _canonical_bundle(authority)
        if bundle is None:
            return sorted(_canonical_definitions())
        return sorted(item["canonical_name"] for item in _active_definition_records(bundle)
                      if item.get("status") == "verified")
    if source != "verified_registry_numeric_universe":
        raise FeatureInstanceError(f"UNKNOWN_FEATURE_SOURCE: {source!r}")
    if not legacy_mode:
        raise FeatureInstanceError(
            "LEGACY_FEATURE_ALIAS_NOT_ALLOWED: verified_registry_numeric_universe is a legacy alias source; "
            "declare canonical FeatureInstances or use explicit legacy replay mode"
        )
    if authority == "legacy":
        return sorted(_instance_overrides())
    if authority == "candidate":
        # Explicit candidate selection is never substitutable.  A malformed or
        # incomplete candidate must surface its own fail-closed authority error.
        return resolve_candidate_aliases(source or "", authority="candidate", legacy_mode=True)
    if authority not in {"active", "legacy"}:
        raise FeatureInstanceError(f"UNKNOWN_FEATURE_AUTHORITY: {authority!r}")
    if ACTIVE_POINTER.is_file():
        # Once cut over, active is the reviewed bundle.  Do not resurrect the
        # legacy registry if its pointer/bundle is damaged.
        return resolve_candidate_aliases(source or "", authority="active", legacy_mode=True)
    return [item["physical_alias"] for item in resolve_feature_instances(source)]


# ---------------------------------------------------------------------------
# Active pipeline resolution API
# ---------------------------------------------------------------------------
# The merged ``FEATURE_REGISTRY`` (declared by the definition modules, reached here
# through ``_feature_registry()``) is retained as a compatibility implementation
# catalog until the old source file can be retired.  It is deliberately not exposed
# to pipeline callers as an authority: membership, lifecycle and alias identity
# below come from the activated canonical bundle (or the explicitly requested
# candidate bundle).  Keeping the compatibility lookup here avoids each caller
# reimplementing a partial alias/verified/provider predicate.

def _canonical_bundle(authority: str) -> Optional[Dict[str, Any]]:
    """Return an explicitly selected canonical bundle when one is authoritative.

    Before the one-shot cutover normal ``active`` continues to use the legacy
    authority so existing studies remain runnable. Candidate is always
    explicit and never falls back. After cutover, active reads exactly the
    bundle selected by the active pointer.
    """
    from features.candidate_authority import ACTIVE_POINTER, load_authority
    if authority == "legacy":
        return None
    if authority == "candidate":
        return load_authority("candidate")
    if authority != "active":
        raise FeatureInstanceError(f"UNKNOWN_FEATURE_AUTHORITY: {authority!r}")
    return load_authority("active") if ACTIVE_POINTER.is_file() else None


_PROMOTED_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def invalidate_promotion_cache() -> None:
    global _PROMOTED_CACHE
    _PROMOTED_CACHE = None


def _promoted_records() -> Dict[str, Dict[str, Any]]:
    """Catalogue definitions verified by their own evidence, in the bundle's record shape.

    A record is included only while its promotion record (``features/definitions/promotions/``)
    exists and still hashes to the definition module, the golden fixture and the provider
    module it was written against -- drift in any of the three demotes the definition to
    provisional and active resolution refuses it (UNVERIFIED_CANONICAL_FEATURE).  Names that
    exist in the authority bundle are never shadowed: the bundle record wins and
    ``features.promotion`` refuses to promote them.
    """
    global _PROMOTED_CACHE
    if _PROMOTED_CACHE is None:
        from features.promotion import content_sha256, promoted_names, read_record, record_binding_errors
        repo_root = Path(__file__).resolve().parents[1]
        out: Dict[str, Dict[str, Any]] = {}
        definitions = _canonical_definitions()
        for name in promoted_names():
            definition = definitions.get(name)
            record = read_record(name)
            if definition is None or record is None or record_binding_errors(name, record):
                continue
            provider_module = repo_root / str(record.get("provider_module") or "")
            out[name] = {
                "canonical_name": name, "family": [definition.family], "dtype": definition.dtype,
                "provider": definition.implementation,
                "provider_sha256": content_sha256(provider_module) if provider_module.is_file() else "",
                "parameter_schema": list(definition.parameter_schema),
                "input_availability_contracts": [t for t in str(definition.source_timeframe).split("+") if t],
                "reset_policies": [definition.reset_policy], "null_policies": [definition.null_policy],
                "legacy_alias_count": 0, "status": "verified",
                "verification": {"kind": "golden_evidence", "record": f"features/definitions/promotions/{name}.json",
                                 "observed_sha256": record.get("observed_sha256")},
            }
        _PROMOTED_CACHE = out
    return _PROMOTED_CACHE


def _promotions_apply(bundle: Optional[Mapping[str, Any]]) -> bool:
    """Evidence promotions extend the ACTIVE authority only: an explicit candidate bundle under
    review, and the legacy (no-bundle) path, keep exactly the membership they had."""
    return bundle is not None and bundle.get("authority") == "active"


def _active_definition_records(bundle: Optional[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Bundle definitions plus evidence-promoted catalogue definitions (bundle names win)."""
    records = list((bundle or {}).get("registry", {}).get("definitions", []))
    if _promotions_apply(bundle):
        present = {r.get("canonical_name") for r in records}
        records.extend(rec for name, rec in sorted(_promoted_records().items()) if name not in present)
    return records


def _canonical_definition_by_name(bundle: Optional[Mapping[str, Any]], name: str) -> Optional[Mapping[str, Any]]:
    for definition in (bundle or {}).get("registry", {}).get("definitions", []):
        if definition.get("canonical_name") == name:
            return definition
    return _promoted_records().get(name) if _promotions_apply(bundle) else None


def resolve_feature_request(
    requested: str,
    parameters: Optional[Mapping[str, Any]] = None,
    *,
    authority: str = "active",
    physical_alias: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve a canonical request or compatibility alias through one API.

    The returned ``physical_alias`` is an output name only.  No caller should
    infer lifecycle, provider, timing or parameters from that spelling.
    """
    bundle = _canonical_bundle(authority)
    supplied = dict(parameters or {})
    if bundle is None:
        if authority == "legacy" and requested in _instance_overrides():
            instance = _instance_overrides()[requested]
            resolved = resolve_feature_request(instance.canonical_name, instance.parameters, authority="active")
            resolved.update({"requested": requested, "physical_alias": requested,
                             "parameters": dict(instance.parameters), "legacy_mode": True})
            return resolved
        # Compatibility path is available only for explicit legacy replay.
        if requested not in _feature_registry():
            raise FeatureInstanceError(f"FEATURE_NOT_REGISTERED: {requested!r}")
        definition = _feature_registry()[requested]
        return {
            "requested": requested, "canonical_name": requested,
            "parameters": supplied, "physical_alias": requested,
            "provider": definition.implementation, "family": definition.family,
            "dtype": definition.dtype, "status": definition.status,
            "input_requirements": {"required_streams": [f"completed_{definition.source_timeframe}"]},
        }

    definition = None
    canonical_definition = _canonical_definition_by_name(bundle, requested)
    # Explicit study instances may retain a historical physical output alias.
    # Resolve it only through the active bundle's deterministic compatibility
    # record; this is not a legacy-universe fallback and never consults the
    # archived registry.
    if canonical_definition is None and requested in bundle.get("aliases", {}).get("aliases", {}):
        record = bundle["aliases"]["aliases"][requested]
        canonical_name = str(record["canonical_feature"])
        definition = _canonical_definition_by_name(bundle, canonical_name)
        supplied = dict(record.get("parameters", {})) | supplied
        physical_alias = physical_alias or requested
        resolved_parameters = validate_feature_instance(FeatureInstance(canonical_name, supplied))
    elif canonical_definition is None and (_INSTANCE_NAME_RE.search(requested) or _TEMPORAL_NAME_RE.search(requested)):
        # Active resolution intentionally does not load or consult the legacy
        # alias map.  Migration guidance is provided by feature_ctl; runtime
        # rejects the instance-shaped request fail-closed.
        raise FeatureInstanceError(
            f"LEGACY_FEATURE_ALIAS_NOT_ALLOWED: {requested!r}; declare canonical "
            "FeatureInstances or invoke explicit legacy replay mode"
        )
    elif definition is None:
        canonical_name = requested
        definition = canonical_definition or _canonical_definition_by_name(bundle, canonical_name)
        if definition is None:
            raise FeatureInstanceError(f"UNKNOWN_CANONICAL_FEATURE: {requested!r}")
        # Canonical instances must be validated at the authority boundary.  A
        # bare canonical name is retained only for collection-universe
        # enumeration (where the caller is asking for definitions, not an
        # executable instance); any request carrying parameters is a real
        # FeatureInstance and must fail closed on unsupported temporal/domain
        # combinations.
        if supplied:
            normalized = validate_feature_instance(
                FeatureInstance(canonical_name, supplied)
            )
            resolved_parameters = normalized
        else:
            resolved_parameters = supplied
        # Active canonical requests never resolve through the historical alias
        # map.  A physical alias is only an explicit legacy-replay concern.
        physical_alias = physical_alias or canonical_name
    if definition is None or definition.get("status") != "verified":
        raise FeatureInstanceError(f"UNVERIFIED_CANONICAL_FEATURE: {canonical_name}")
    return {
        "requested": requested, "canonical_name": canonical_name,
        "parameters": resolved_parameters, "physical_alias": physical_alias,
        "provider": definition.get("provider", ""), "family": definition.get("family", ""),
        "dtype": definition.get("dtype", "float64"), "status": definition.get("status"),
        "input_requirements": derive_resolved_input_requirements(
            canonical_name, resolved_parameters, definition),
    }


def derive_resolved_input_requirements(
    canonical_name: str, parameters: Mapping[str, Any], definition: Mapping[str, Any],
) -> Dict[str, Any]:
    """Derive runtime requirements from instance parameters, never alias text."""
    params = dict(parameters)
    streams: Set[str] = set()
    # OHLCV rolling aliases historically encoded the trailing duration in the
    # `timeframe` parameter.  The provider consumes completed 1s bars; expose
    # that true causal requirement without changing the historical alias or
    # values.  New instances should use `window` explicitly.
    rolling_legacy = params.get("context") == "rolling" and "timeframe" in params
    if "window" in params or rolling_legacy:
        window = params.get("window", params.get("timeframe"))
        streams.add("completed_1s")
        temporal = {"window_type": "rolling", "window": window,
                    "update_every": params.get("update_every", "1s")}
    else:
        temporal = {}
        for key, state_key in (("timeframe", "bar_state"), ("source_timeframe", "source_bar_state"),
                               ("reference_timeframe", "reference_bar_state")):
            if key in params:
                streams.add(f"{params.get(state_key, 'completed')}_{params[key]}")
        if not streams:
            for requirement in definition.get("input_availability_contracts", []):
                streams.add(f"completed_{requirement}")
    return {"canonical_name": canonical_name, "provider": definition.get("provider", ""),
            "required_streams": sorted(streams), **temporal}


def resolve_runtime_feature_definition(requested: str, *, authority: str = "active") -> FeatureDefinition:
    """Return canonical-authorized metadata for a pipeline binding.

    This intentionally constructs the narrow legacy-compatible record required
    by older tracker binders while authorization remains canonical.  Direct
    consumers must call this rather than indexing ``FEATURE_REGISTRY``.
    """
    resolved = resolve_feature_request(requested, authority=authority)
    return FeatureDefinition(
        name=resolved["physical_alias"], status=resolved["status"],
        family=resolved["family"], implementation=resolved["provider"],
        dtype=resolved["dtype"], source_timeframe="1s",
        update_anchor="canonical_instance_contract", null_policy="allow",
    )


def resolve_runtime_feature_aliases(
    source: Optional[str] = "canonical_verified_definition_universe", *, authority: str = "active",
) -> List[str]:
    """Return the physical output aliases permitted by the selected authority."""
    return resolve_source_universe(source, authority=authority)


def resolve_runtime_family_aliases(families: Set[str], *, authority: str = "active") -> List[str]:
    """Filter resolved aliases by canonical family without alias-name parsing."""
    bundle = _canonical_bundle(authority)
    if bundle is None:
        return sorted(name for name, definition in _feature_registry().items() if definition.family in families)
    definitions = {item["canonical_name"]: item for item in _active_definition_records(bundle)}
    return sorted(name for name, definition in definitions.items()
                  if set(definition.get("family", [])) & set(families)
                  and definition.get("status") == "verified")


def resolve_feature_engine_output_aliases(*, authority: str = "active") -> List[str]:
    """Resolve the physical surface implemented by the shared FeatureEngine.

    The canonical universe has 693 compatible aliases, while this particular
    engine deliberately implements the historical 532-column collector
    surface. Its capability is declared once here from compatibility
    implementation metadata and intersected with canonical authority; callers
    neither parse names nor widen a collector merely because an alias exists.
    """
    bundle = _canonical_bundle(authority)
    if bundle is not None:
        implemented = {item["canonical_name"] for item in _active_definition_records(bundle)
                       if item.get("status") == "verified"}
    else:
        implemented = {name for name, definition in _feature_registry().items()
                       if definition.status == "verified" and definition.implementation}
    allowed = set(resolve_runtime_feature_aliases(authority=authority))
    return sorted(implemented & allowed)


def provider_compatibility_keys(canonical_name: str, *, authority: str = "active") -> List[str]:
    """Implementation-only adapter for providers retaining historical field labels."""
    bundle = _canonical_bundle(authority)
    if bundle is None:
        return []
    return sorted(alias for alias, record in bundle.get("aliases", {}).get("aliases", {}).items()
                  if record.get("canonical_feature") == canonical_name)


def canonicalize_provider_columns(columns: Iterable[str], *, authority: str = "active") -> Dict[str, str]:
    """Map provider compatibility labels to canonical output labels at the boundary."""
    bundle = _canonical_bundle(authority)
    if bundle is None:
        return {name: name for name in columns}
    aliases = bundle.get("aliases", {}).get("aliases", {})
    return {name: aliases.get(name, {}).get("canonical_feature", name) for name in columns}


def derive_study_feature_requirements(features_spec: Any, *, authority: str = "active") -> Dict[str, Any]:
    """Derive collector streams/windows exclusively from study-local instances.

    A legacy feature_list is resolved through compatibility mapping.  A source
    universe without explicit instances returns its declared aliases but does
    not guess provider-internal requirements from alias text.
    """
    requests: List[Tuple[str, Mapping[str, Any], Optional[str]]] = []
    for item in (getattr(features_spec, "instances", None) or []):
        requests.append((str(item["feature"]), dict(item.get("parameters", {})), item.get("physical_alias")))
    for alias in (getattr(features_spec, "feature_list", None) or []):
        requests.append((str(alias), {}, None))
    resolved = []
    for name, params, alias in requests:
        item = resolve_feature_request(name, params, authority=authority, physical_alias=alias)
        # Canonical instances receive the deterministic compatibility/output alias
        # generated from their parameters.  A caller-provided physical_alias remains
        # an explicit compatibility override.
        if alias is None and name in _canonical_definitions():
            item["physical_alias"] = generate_physical_alias(
                FeatureInstance(name, params)
            )
        resolved.append(item)
    streams: Set[str] = set()
    rolling_windows: Set[str] = set()
    for item in resolved:
        requirements = item["input_requirements"]
        streams.update(requirements.get("required_streams", []))
        if requirements.get("window"):
            rolling_windows.add(str(requirements["window"]))
    return {"resolved_instances": resolved, "required_streams": sorted(streams),
            "rolling_windows": sorted(rolling_windows),
            "aliases": [item["physical_alias"] for item in resolved]}


def validate_canonical_feature_name(definition: FeatureDefinition) -> None:
    """Reject temporal instance tokens in new canonical names unless documented.

    Existing physical ``FEATURE_REGISTRY`` aliases predate V2 and are intentionally not
    subjected to this rule.  New canonical definitions must keep time/window/context
    in FeatureInstance.parameters, with an explicit exception for a genuinely intrinsic
    temporal formula.
    """
    if (_TEMPORAL_NAME_RE.search(definition.name) or _INSTANCE_NAME_RE.search(definition.name)) and not definition.temporal_identity_exception:
        raise FeatureInstanceError(
            f"FEATURE_NAME_EMBEDS_TEMPORAL_INSTANCE: {definition.name!r}; move timeframe/window to FeatureInstance parameters or document temporal_identity_exception"
        )


# ---------------------------------------------------------------------------
# Snapshot-anchor binding (nt_live_scoring_infra_prereqs Phase 2) -- codifies
# FEATURE_REGISTRY_CONTRACT.md section 6's existing deferral ("Exact snapshot
# timings must remain part of the study-specific contract") as actual data
# instead of leaving it narrative-only. A registry entry's own
# `snapshot_anchor` field stays a shared class-level default
# ('caller_defined' unless set otherwise); a consuming study declares WHEN
# IT snaps a given feature via `bind_snapshot_anchor`, without ever
# mutating the shared `FeatureDefinition` object other studies also read.
# ---------------------------------------------------------------------------
_SNAPSHOT_ANCHOR_BINDINGS: Dict[Tuple[str, str], str] = {}


def bind_snapshot_anchor(feature_name: str, study_name: str, anchor: str) -> None:
    """Declare that `study_name` snaps `feature_name` at `anchor` (e.g.
    'at_signal_decision_ts', 'at_touch_time', 'at_fill_time'). Raises if
    the feature isn't registered -- a study cannot bind a snapshot anchor
    for a feature that doesn't exist."""
    try:
        resolved = resolve_feature_request(feature_name)
    except FeatureInstanceError as exc:
        raise KeyError(f"cannot bind snapshot anchor for unregistered feature {feature_name!r}") from exc
    _SNAPSHOT_ANCHOR_BINDINGS[(resolved["physical_alias"], study_name)] = anchor


def effective_snapshot_anchor(feature_name: str, study_name: str) -> str:
    """The snapshot anchor `study_name` actually uses for `feature_name`:
    its own declared binding if one was made via `bind_snapshot_anchor`,
    else the registry entry's shared class-level default."""
    try:
        resolved = resolve_feature_request(feature_name)
    except FeatureInstanceError as exc:
        raise KeyError(f"unregistered feature {feature_name!r}") from exc
    key = (resolved["physical_alias"], study_name)
    if key in _SNAPSHOT_ANCHOR_BINDINGS:
        return _SNAPSHOT_ANCHOR_BINDINGS[key]
    # Canonical definitions place timing in their instance input contract;
    # legacy pre-cutover records retain their historical default only behind
    # this boundary.
    return "canonical_instance_contract" if _canonical_bundle("active") else _feature_registry()[feature_name].snapshot_anchor

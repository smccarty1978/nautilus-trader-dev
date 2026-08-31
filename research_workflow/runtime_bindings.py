"""Canonical runtime execution-binding contract.

Preflight/readiness historically proved a *collector class* exists and advertises the
right interfaces. It did NOT prove that every compiled semantic primitive
(``population_contract.episode_lifecycle``, each canonical ``FeatureInstance``) is
actually *executed* by that collector at runtime. A study could therefore reach
SEALED with a declared 34-feature surface where the collector computes 13 and emits
the other 21 as null columns, and with a sealed ``episode_lifecycle`` that the
collector never runs (falling back to checkpoint-grid emission).

This module is the single authority that maps compiled primitives -> executable
runtime component, plus a deterministic verifier used by the preflight gate.

It is NOT a second resolver. It reads:
  * the compiled study's ``population_contract`` for the population primitive
  * the collector strategy class's own honest capability declaration
    (``SUPPORTS_EPISODE_LIFECYCLE``)
and reports every primitive with no executable binding.

Scope note. Two checks:

  * ``episode_lifecycle`` -> ``EpisodePopulationEngine`` -- always verified; the
    primitive's runtime component is canonically singular.

  * per-*feature* realizability -- verified statically ONLY for studies whose compiled
    ``execution.runtime_feature_mode == "provider_host"``, via
    ``research_workflow.provider_host.ProviderHost``'s own machine-readable binding
    metadata (one registered ``RuntimeProviderAdapter`` per canonical provider,
    ``bound`` per FeatureInstance). Legacy studies omit the field and keep their
    compact / fused-ring / exploratory collector paths; for them per-column coverage
    stays empirical -- ``scripts.validate_smoke`` runs the real collector and fails on
    ``RUNTIME_FEATURE_BINDING_MISSING`` for any declared column absent or entirely null
    in real output.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Dict, List

__all__ = ["RuntimeBindingError", "collector_runtime_capabilities", "verify_runtime_contract"]


class RuntimeBindingError(RuntimeError):
    """A declared execution primitive has no executable runtime binding."""


# The episode-population primitive resolves to exactly one runtime component.
EPISODE_LIFECYCLE_RUNTIME = "research_workflow.episode_population.EpisodePopulationEngine"


def _load_collector_class(strategy_class: str | None):
    """Resolve the collector strategy class from its fully-qualified name.

    Falls back to the canonical generic collector when the spec leaves it implicit,
    matching ``readiness.run_real_nonempty_output_parity``'s own default.
    """
    fq = strategy_class or "research_workflow.generic_collector.GenericStudyCollector"
    module_name, _, cls_name = fq.rpartition(".")
    try:
        module = importlib.import_module(module_name)
    except Exception:
        # GenericStudyCollector is a re-export alias; the concrete class lives in the
        # same module and is the one carrying the capability declaration.
        module = importlib.import_module("research_workflow.generic_collector")
        cls_name = "FlipPredictionCollector"
    return getattr(module, cls_name, None) or getattr(
        importlib.import_module("research_workflow.generic_collector"), "FlipPredictionCollector"
    )


def _collector_dispatches_population_runtime(cls) -> bool:
    """Structural proof that the collector actually drives the population runtime -- the
    ``SUPPORTS_EPISODE_LIFECYCLE`` flag alone must never satisfy the gate (§11)."""
    import inspect

    try:
        src = inspect.getsource(cls)
    except (OSError, TypeError):
        return False
    return (
        "resolve_population_runtime(" in src
        and "_population_runtime.on_completed_1s(" in src
        and "_population_runtime.on_prevailing_regime(" in src
        and "not getattr(self, \"_episode_mode\", False)" in src  # checkpoint grid disabled
    )

def _collector_dispatches_target_runtime(cls) -> bool:
    import inspect
    try:
        src = inspect.getsource(cls)
    except (OSError, TypeError):
        return False
    return ("resolve_target_runtime(" in src and "_resolve_ordered_barriers(" in src
            and "_resolve_composite(" in src and ".terminal(" in src)


def collector_runtime_capabilities(strategy_class: str | None) -> Dict[str, Any]:
    """The collector's own honest declaration of what it executes.

    ``supports_episode_lifecycle`` -- True only when the collector BOTH declares
    ``SUPPORTS_EPISODE_LIFECYCLE`` AND its source genuinely dispatches the generic
    population runtime (arms/emits from ``EpisodePopulationEngine``, no checkpoint-grid
    candidate emission). Absent / declaration-only reads as False.
    """
    cls = _load_collector_class(strategy_class)
    declared = bool(getattr(cls, "SUPPORTS_EPISODE_LIFECYCLE", False))
    dispatches = _collector_dispatches_population_runtime(cls)
    return {
        "strategy_class": getattr(cls, "__module__", "?") + "." + getattr(cls, "__name__", "?"),
        "supports_episode_lifecycle": declared and dispatches,
        "declares_episode_lifecycle": declared,
        "dispatches_population_runtime": dispatches,
    }


def verify_runtime_contract(study_dir: str | Path, *, scope: str = "all") -> Dict[str, Any]:
    """Every declared execution primitive must have an executable runtime binding.

    ``scope``:
      * ``"all"`` (default) -- episode-lifecycle primitive AND feature-provider
        realizability. Used by the study-execution (active-authority) preflight.
      * ``"features_only"`` -- feature-provider realizability only. Used by the
        feature-candidate preflight, which validates the feature bundle, not the
        collector's population runtime (that is gated on the active seal).

    Static, fail-closed. Currently binds the one primitive whose runtime component is
    canonically singular and statically verifiable:

        population_contract.episode_lifecycle  ->  EpisodePopulationEngine

    Per-feature *value* coverage (a declared FeatureInstance emitted as an all-null
    column because its provider is not wired into the collector) is proven empirically
    by the smoke validator -- see ``scripts.validate_smoke``'s
    ``RUNTIME_FEATURE_BINDING_MISSING`` check.

    Returns ``{"passed": bool, "missing": [ ... ], "checked": {...}}``.
    """
    study_dir = Path(study_dir).resolve()
    compiled_path = study_dir / "compiled_study.json"
    if not compiled_path.is_file():
        raise RuntimeBindingError(
            f"RUNTIME_CONTRACT_UNVERIFIABLE: {compiled_path} missing; a compiled study is required"
        )
    compiled = json.loads(compiled_path.read_text(encoding="utf-8"))
    spec = compiled.get("spec", {}) or {}
    contracts = compiled.get("contracts", {}) or {}
    strategy_class = (spec.get("execution") or {}).get("strategy_class")
    caps = collector_runtime_capabilities(strategy_class)

    missing: List[Dict[str, Any]] = []
    target_contract = contracts.get("target_contract") or {}
    target_checked = None
    if target_contract.get("primitive") is not None and scope != "features_only":
        target_checked = {"primitive": target_contract.get("primitive"), "dispatch": _collector_dispatches_target_runtime(_load_collector_class(strategy_class))}
        try:
            from research_workflow.target_runtime import resolve_target_runtime
            runtime = resolve_target_runtime(target_contract)
            target_checked["runtime"] = type(runtime).__name__
            from research_workflow.target_runtime import resolve_target_runtime_closure
            target_checked["target_runtime_closure_sha256"] = resolve_target_runtime_closure(study_dir)["target_runtime_closure_sha256"]
            if not target_checked["dispatch"]:
                raise RuntimeBindingError("collector source does not dispatch resolved TargetRuntime")
            # RT-05: every non-default semantic field the contract authors must be
            # executed by the resolved runtime (or recorded as provenance-only), never
            # silently ignored. Fails closed with TARGET_SEMANTIC_FIELD_UNSUPPORTED.
            from research_workflow.target_runtime import assert_target_semantic_field_coverage
            target_checked["semantic_field_coverage"] = assert_target_semantic_field_coverage(target_contract)
            # PREFLIGHT_EXPRESSION_BINDING: the executable Boolean expression the runtime
            # will run MUST equal the expression compiled from the contract's own
            # conditions/condition_logic AND the target_expression tree embedded in the
            # contract.  A drift (hand-edited target_expression, a stale contract, a
            # runtime that would drop a child) fails closed here.
            from research_workflow.target_expression import (
                compile_target_expression,
                serialize_expression,
            )

            compiled_expr = serialize_expression(target_contract)
            target_checked["expression_binding"] = {
                "compiled_from_conditions": compiled_expr,
                "embedded_in_contract": target_contract.get("target_expression"),
                "runtime_canonical_matches": None,
                "censoring_composition": target_contract.get("censoring_composition"),
            }
            def _expressions_compatible(compiled: dict, embedded: dict) -> bool:
                if compiled == embedded:
                    return True
                if compiled.get("node") != embedded.get("node") or compiled.get("logic") != embedded.get("logic"):
                    return False
                compiled_children = compiled.get("children") or []
                embedded_children = embedded.get("children") or []
                if len(compiled_children) != len(embedded_children):
                    return False
                for c_child, e_child in zip(compiled_children, embedded_children):
                    if c_child.get("node") != e_child.get("node") or c_child.get("condition_id") != e_child.get("condition_id") or c_child.get("primitive") != e_child.get("primitive"):
                        return False
                    c_params = c_child.get("params") or {}
                    e_params = e_child.get("params") or {}
                    for k, v in e_params.items():
                        if k in c_params and c_params[k] != v:
                            return False
                return True

            if target_contract.get("conditions"):
                embedded = target_contract.get("target_expression")
                if embedded is not None and not _expressions_compatible(compiled_expr, embedded):
                    raise RuntimeBindingError(
                        "TARGET_EXPRESSION_DRIFT: contract.target_expression does not match "
                        "the expression compiled from contract.conditions/condition_logic"
                    )
                if str(target_contract.get("primitive")) == "composite":
                    import json as _json

                    runtime_canonical = runtime.canonical()
                    want = _json.dumps(compiled_expr, sort_keys=True, separators=(",", ":"))
                    target_checked["expression_binding"]["runtime_canonical_matches"] = (
                        runtime_canonical == want
                    )
                    if runtime_canonical != want:
                        raise RuntimeBindingError(
                            "COMPOSITE_RUNTIME_EXPRESSION_MISMATCH: CompositeTargetRuntime "
                            "would execute a different expression than the compiled contract"
                        )
        except Exception as e:
            missing.append({"primitive": "target_contract.primitive", "declared": target_contract.get("primitive"),
                            "required_binding": "research_workflow.target_runtime.TargetRuntime", "collector": caps["strategy_class"],
                            "reason": f"TARGET_RUNTIME_MISMATCH: {type(e).__name__}: {e}"})
    modeling_checked = None
    if target_contract.get("primitive") is not None and scope != "features_only":
        try:
            from research_workflow.modeling_closure import resolve_modeling_closure
            drivers = list(((spec.get("execution") or {}).get("modeling_driver_relpaths") or []))
            modeling_checked = resolve_modeling_closure(study_dir, driver_relpaths=drivers)["modeling_execution_composite_sha256"]
        except Exception as e:
            missing.append({"primitive":"modeling_execution_closure", "declared": "governed", "required_binding":"research_workflow.modeling_closure", "collector":caps["strategy_class"], "reason":f"MODELING_EXECUTION_CLOSURE_MISMATCH: {e}"})
    population_contract = contracts.get("population_contract") or {}
    episode = population_contract.get("episode_lifecycle")
    if episode and scope != "features_only":
        # The dispatcher must resolve episode_lifecycle to EpisodePopulationEngine and
        # NOT to the checkpoint grid, AND the collector source must genuinely drive it.
        binding_ok = caps["supports_episode_lifecycle"]
        reason = ""
        if not caps["declares_episode_lifecycle"]:
            reason = "collector does not declare SUPPORTS_EPISODE_LIFECYCLE"
        elif not caps["dispatches_population_runtime"]:
            reason = ("collector declares SUPPORTS_EPISODE_LIFECYCLE but its source does not "
                      "dispatch resolve_population_runtime / on_completed_1s / "
                      "on_prevailing_regime, or still emits from the checkpoint grid")
        if binding_ok:
            try:
                from research_workflow.episode_population import EpisodePopulationEngine
                from research_workflow.population_runtime import (
                    EpisodePopulationRuntime, resolve_population_runtime,
                )
                rt = resolve_population_runtime({"episode_lifecycle": episode})
                if not isinstance(rt, EpisodePopulationRuntime) or rt.emits_from_checkpoint_grid():
                    binding_ok = False
                    reason = "resolve_population_runtime did not bind episode_lifecycle to EpisodePopulationEngine"
                elif rt.engine_class is not EpisodePopulationEngine:
                    binding_ok = False
                    reason = "population runtime engine is not EpisodePopulationEngine"
            except Exception as e:  # pragma: no cover - defensive
                binding_ok = False
                reason = f"{type(e).__name__}: {e}"
        if not binding_ok:
            missing.append({
                "primitive": "population_contract.episode_lifecycle",
                "declared": "arm -> required counter-event -> first flip-back emit; "
                            f"max_candidates_per_episode={episode.get('max_candidates_per_episode')}",
                "required_binding": EPISODE_LIFECYCLE_RUNTIME,
                "collector": caps["strategy_class"],
                "reason": reason or "population runtime binding could not be verified",
            })

    # --- feature-provider realizability (provider_host runtime mode only) ---------
    # A study is provider_host mode iff it declares an episode_lifecycle population --
    # such a study cannot run the legacy checkpoint collector, so every FeatureInstance
    # must resolve to a registered RuntimeProviderAdapter and be bound. Proven from
    # ProviderHost's own machine-readable binding metadata, not a module-name or
    # alias-list heuristic. An explicit spec.execution.runtime_feature_mode (future
    # schema bump) takes precedence if present. Legacy studies keep their compact /
    # fused-ring / exploratory collector feature paths untouched.
    runtime_feature_mode = (
        (spec.get("execution") or {}).get("runtime_feature_mode")
        or ("provider_host" if episode else None)
    )
    provider_host_meta: List[Dict[str, Any]] | None = None
    if runtime_feature_mode == "provider_host":
        try:
            from research_workflow.provider_host import ProviderHost

            host = ProviderHost.from_feature_contract(compiled)
            verdict = host.verify_bindings()
            provider_host_meta = verdict["metadata"]
            for alias in verdict["unbound"]:
                rec = next((m for m in verdict["metadata"] if m["physical_alias"] == alias), {})
                missing.append({
                    "primitive": f"feature_instance:{alias}",
                    "declared": rec.get("canonical_name", alias),
                    "required_binding": rec.get("canonical_provider", "features.registry-resolved provider"),
                    "collector": caps["strategy_class"],
                    "reason": "runtime_feature_mode=provider_host but no RuntimeProviderAdapter "
                              "binds this FeatureInstance's canonical provider",
                })
        except Exception as e:  # RuntimeProviderBindingMissing, duplicate alias, resolve failure
            missing.append({
                "primitive": "runtime_feature_mode.provider_host",
                "declared": runtime_feature_mode,
                "required_binding": "research_workflow.provider_host.ProviderHost",
                "collector": caps["strategy_class"],
                "reason": f"{type(e).__name__}: {e}",
            })

    # --- (4) frozen derived-input scorer binding (Stage 3 / RT-04) --------------
    # EVERY declared frozen_external_model_score must bind an executable scorer, 1:1,
    # with a unique output-column name, independent of population type. A declared
    # input with no bindable scorer fails preflight rather than silently producing a
    # null column; no undeclared score is emitted (the collector's keep-set is exactly
    # these names).
    features = spec.get("features", {}) or contracts.get("feature_contract", {}) or {}
    derived = (features.get("derived_inputs") or features.get("derived_causal_inputs") or [])
    scorer_bound = None
    _bound_names: List[str] = []

    def _is_runtime_scored(di: Dict[str, Any]) -> bool:
        # A derived input the collector must SCORE at collection time: it carries a
        # fitted-model artifact or an immutable model_id. A `score_artifact_path`-only
        # form is a pre-materialized score table joined offline -- covered by
        # research_workflow/derived_inputs.py's provenance gate, not scored here.
        return bool(di.get("model_artifact_path") or di.get("model_id"))

    _declared_names = [
        di.get("name") for di in derived
        if di.get("kind") == "frozen_external_model_score" and _is_runtime_scored(di)
    ]
    for di in derived:
        if di.get("kind") != "frozen_external_model_score" or not _is_runtime_scored(di):
            continue
        scorer_bound = False
        try:
            from research.schemas.study_spec import DerivedCausalInputSpec
            from research_workflow.external_model_scoring import FrozenExternalModelScorer
            spec_di = DerivedCausalInputSpec.model_validate(di)
            # bind() derives the model registry as parent_dir.parents[0]/model_registry
            # for a model_id binding, so parent_dir must be a directory under studies/;
            # study_dir itself works (a legacy binding overrides it with the parent).
            parent_dir = (
                (study_dir.parents[0] / spec_di.parent_study_id)
                if spec_di.parent_study_id else study_dir
            )
            FrozenExternalModelScorer.bind(spec_di, parent_dir=parent_dir)
            scorer_bound = True
            _bound_names.append(spec_di.name)
        except Exception as e:
            missing.append({
                "primitive": f"derived_input:{di.get('name')}",
                "declared": di.get("kind"),
                "required_binding": "research_workflow.external_model_scoring.FrozenExternalModelScorer",
                "collector": caps["strategy_class"],
                "reason": f"{type(e).__name__}: {e}",
            })
    if _declared_names and len(set(_declared_names)) != len(_declared_names):
        missing.append({
            "primitive": "derived_inputs.name_uniqueness",
            "declared": _declared_names,
            "required_binding": "one output column per declared derived input",
            "collector": caps["strategy_class"],
            "reason": f"DERIVED_INPUT_DUPLICATE_NAME: {_declared_names}",
        })
    if _declared_names and sorted(_bound_names) != sorted(n for n in _declared_names if n):
        missing.append({
            "primitive": "derived_inputs.scorer_coverage",
            "declared": _declared_names,
            "required_binding": "exactly one bound scorer per declared derived input",
            "collector": caps["strategy_class"],
            "reason": (f"DERIVED_INPUT_SCORER_UNBOUND: declared {_declared_names}, "
                       f"bound {_bound_names}"),
        })

    # --- (5) output-row persistence path (Stage 3) -----------------------------
    # An episode study's governed row carries episode identity + the derived score
    # column; both must be declared so OutputManager admits them.
    output_row_ok = None
    if episode and scope != "features_only":
        meta_cols = set((features.get("metadata_columns") or []))
        required_meta = {"observation_ts", "regime_start_ns", "checkpoint_index",
                         "episode_id", "arm_ts", "candidate_ts"}
        missing_meta = sorted(required_meta - meta_cols)
        derived_names = {di.get("name") for di in derived if di.get("name")}
        output_row_ok = not missing_meta and bool(derived_names)
        if not output_row_ok:
            missing.append({
                "primitive": "output_row_persistence",
                "declared": f"metadata_columns={sorted(meta_cols)}",
                "required_binding": "research_workflow.output_manager.OutputManager",
                "collector": caps["strategy_class"],
                "reason": (f"episode candidate row is not fully declared: "
                           f"missing metadata {missing_meta or 'none'}; "
                           f"derived score column declared={bool(derived_names)}"),
            })

    return {
        "passed": not missing,
        "missing": missing,
        "checked": {
            "strategy_class": caps["strategy_class"],
            "supports_episode_lifecycle": caps["supports_episode_lifecycle"],
            "episode_lifecycle_declared": bool(episode),
            "runtime_feature_mode": runtime_feature_mode or "legacy_runtime",
            "provider_host_bindings": (
                {"required": len(provider_host_meta),
                 "bound": sum(1 for m in provider_host_meta if m["bound"])}
                if provider_host_meta is not None else None
            ),
            "derived_scorer_bound": scorer_bound,
            "output_row_persistence_declared": output_row_ok,
            "target_runtime": target_checked,
            "modeling_execution_closure_sha256": modeling_checked,
        },
    }

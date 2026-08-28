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


def collector_runtime_capabilities(strategy_class: str | None) -> Dict[str, Any]:
    """The collector's own honest declaration of what it executes.

    ``supports_episode_lifecycle`` -- whether it runs ``EpisodePopulationEngine`` for a
    ``population_contract.episode_lifecycle`` population. Absent reads as False, which
    is the fail-closed default.
    """
    cls = _load_collector_class(strategy_class)
    return {
        "strategy_class": getattr(cls, "__module__", "?") + "." + getattr(cls, "__name__", "?"),
        "supports_episode_lifecycle": bool(getattr(cls, "SUPPORTS_EPISODE_LIFECYCLE", False)),
    }


def verify_runtime_contract(study_dir: str | Path) -> Dict[str, Any]:
    """Every declared execution primitive must have an executable runtime binding.

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
    population_contract = contracts.get("population_contract") or {}
    episode = population_contract.get("episode_lifecycle")
    if episode and not caps["supports_episode_lifecycle"]:
        missing.append({
            "primitive": "population_contract.episode_lifecycle",
            "declared": "arm -> required counter-event -> first flip-back emit; "
                        f"max_candidates_per_episode={episode.get('max_candidates_per_episode')}",
            "required_binding": EPISODE_LIFECYCLE_RUNTIME,
            "collector": caps["strategy_class"],
            "reason": "collector does not declare SUPPORTS_EPISODE_LIFECYCLE; it would emit on "
                      "the checkpoint grid instead of one candidate per deep-pullback episode",
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
        },
    }

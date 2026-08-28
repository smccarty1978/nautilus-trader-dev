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

Scope note. This module statically verifies the one primitive whose runtime
component is canonically singular and unambiguous: ``episode_lifecycle`` ->
``EpisodePopulationEngine``. Per-*feature* realizability (a declared FeatureInstance
emitted as an all-null column because its provider is not wired into the collector)
is NOT statically verifiable against the current collector -- it serves three
different feature-surface paths (compact / fused-ring / exploratory) and bridges
legacy-tracker outputs to canonical aliases, so there is no hand-maintainable
"emittable alias" set that is both complete and regression-free. That check is
instead empirical: ``scripts.validate_smoke`` runs the real collector and fails on
``RUNTIME_FEATURE_BINDING_MISSING`` for any declared column that is absent or
entirely null in real output. A generic feature-provider host (one bound provider
per FeatureInstance, realizability = "is a provider bound") would make the static
check tractable; that host does not exist yet.
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

    return {
        "passed": not missing,
        "missing": missing,
        "checked": {
            "strategy_class": caps["strategy_class"],
            "supports_episode_lifecycle": caps["supports_episode_lifecycle"],
            "episode_lifecycle_declared": bool(episode),
        },
    }

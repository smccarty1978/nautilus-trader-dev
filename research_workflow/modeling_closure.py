"""Stage-scoped MODELING execution closure.

The collection/runtime closure (``scripts/resolve_execution_manifest.py``) is seeded from
the NT collect entrypoints and answers *"what code produced the candidate/observation
partitions"*. It deliberately does not reach the TRAIN merge / model-selection / fit /
freeze code, because none of that runs inside the collector.

This module answers the complementary question *"what code turned the frozen partitions
into a frozen model"* using the **same** AST-import-closure primitive
(``resolve_execution_manifest.compute_ast_closure``) -- it is not a parallel provenance
system, just a second seed set for the one closure algorithm.

A study's TRAIN freeze then binds BOTH composites:
    collection producer composite  (audit/frozen_execution_manifest.json)
    modeling execution composite   (this module)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from scripts.resolve_execution_manifest import compute_ast_closure

REPO_ROOT = Path(__file__).resolve().parents[1]

# The governed modeling API surface every declarative study composes. A study-local
# driver adds exactly one seed (its own file); the transitive closure pulls the rest.
_MODELING_API_SEEDS = (
    "research_workflow/modeling.py",
    "research_workflow/model_selection.py",
    "research_workflow/partitioning.py",
    "research_workflow/experiment.py",
    "research_workflow/gates.py",
    "research/analysis/modeling.py",
    "research/analysis/spec.py",
    "research/engines/target_engine.py",
)


def resolve_modeling_closure(study_dir: str | Path, *, driver_relpaths: List[str] | None = None) -> Dict[str, Any]:
    """Resolve the modeling execution closure for one study.

    ``driver_relpaths`` are study-relative paths to the study's modeling driver(s)
    (e.g. ``["implementation/train_merge_fit_freeze.py"]``). They are seeded alongside
    the governed modeling API so a driver that hard-codes label inclusion, chronology
    roles, the seed, the fit call or the freeze call is inside the composite.
    """
    study_dir = Path(study_dir).resolve()
    # Declaration is the authority; the detector below is only a fail-safe for
    # undeclared participation / generated subprocess paths.
    from research_workflow.modeling_drivers import assert_declared_modeling_drivers
    declared = list(driver_relpaths or [])
    assert_declared_modeling_drivers(study_dir, declared)
    seeds: List[Path] = [REPO_ROOT / rel for rel in _MODELING_API_SEEDS]
    driver_files = [(study_dir / rel).resolve() for rel in declared]
    # Shell wrappers are direct closure members but not Python AST seeds.
    seeds.extend(p for p in driver_files if p.suffix == ".py")

    closure, unresolved = compute_ast_closure(seeds, REPO_ROOT)
    if unresolved:
        raise RuntimeError(f"MODELING_CLOSURE_UNRESOLVED: {unresolved}")

    file_sha256: Dict[str, str] = {}
    for p in sorted(set(closure) | set(driver_files)):
        try:
            rel = p.relative_to(REPO_ROOT).as_posix()
            key = f"repo:{rel}"
        except ValueError:
            rel = p.relative_to(study_dir).as_posix()
            key = f"study:{rel}"
        file_sha256[key] = hashlib.sha256(p.read_bytes()).hexdigest()

    composite = hashlib.sha256(
        json.dumps(file_sha256, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "modeling_execution_composite_sha256": composite,
        "file_count": len(file_sha256),
        "file_sha256_map": file_sha256,
        "api_seeds": list(_MODELING_API_SEEDS),
        "driver_seeds": sorted(declared),
    }


__all__ = ["resolve_modeling_closure"]

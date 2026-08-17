"""Mode-Specific Deliverables Contract Engine (Finding F1).

The failed acceptance test's ``SPEC.md`` section 4 declared::

    candidates.parquet, scores.parquet, triggers.parquet, metrics.json

for a study that only ever ran in **collect** mode. Collect mode produces
``candidates.parquet``, ``observations.parquet`` and ``collection_manifest.json``, and
cannot produce the other three at all -- ``scores``/``triggers``/``metrics`` belong to
later modes that were never run. So the SPEC simultaneously demanded three unproducible
artifacts and omitted the one deliverable (``observations.parquet``) that carries the
study's labels.

The contract-checker passed anyway, because with no machine-readable deliverable set to
consume it assembled its own checklist and then verified the implementation against that.
A check that derives its own scope cannot detect scope loss.

This module makes the deliverable set:

* **mode-partitioned** -- each mode declares only what that mode can actually emit;
* **machine-readable** -- ``config/deliverables_contract.json``, so the checker consumes
  an authority rather than inventing one;
* **producible-by-construction** -- every declared artifact maps to a producer, and
  declaring one no mode produces is refused at compile time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# The producer registry. An artifact absent from here cannot be declared by any mode:
# that is what makes "unreachable deliverable" a compile-time error rather than a
# discovery made after a run finishes and the artifact simply is not there.
KNOWN_ARTIFACT_PRODUCERS: Dict[str, Dict[str, str]] = {
    "candidates.parquet": {
        "mode": "collect",
        "producer": "backtests/nt_runtime/output_manager.py::persist_collection",
        "relative_to": "run_dir/collection",
    },
    "observations.parquet": {
        "mode": "collect",
        "producer": "backtests/nt_runtime/output_manager.py::persist_collection",
        "relative_to": "run_dir/collection",
    },
    "collection_manifest.json": {
        "mode": "collect",
        "producer": "backtests/nt_runtime/output_manager.py::persist_collection",
        "relative_to": "run_dir/collection",
    },
    # Run-level bookkeeping is emitted by every executing mode, so it is not owned by
    # one of them. `modes` is the general form; `mode` below is the single-owner case.
    "run_manifest.json": {
        "modes": ["collect", "backtest"],
        "producer": "backtests/nt_runtime/output_manager.py::OutputManager",
        "relative_to": "run_dir",
    },
    "status.json": {
        "modes": ["collect", "backtest"],
        "producer": "backtests/nt_runtime/output_manager.py::persist_collection",
        "relative_to": "run_dir",
    },
    "scores.parquet": {
        "mode": "analysis",
        "producer": "model scoring stage",
        "relative_to": "study_dir/results",
    },
    "triggers.parquet": {
        "mode": "backtest",
        "producer": "backtests/run_backtest.py",
        "relative_to": "study_dir/results",
    },
    "metrics.json": {
        "mode": "analysis",
        "producer": "analysis stage",
        "relative_to": "study_dir/results",
    },
}

# What each mode emits when it runs to completion. Collect mode is exhaustive here
# because collect mode is what this study runs.
MODE_DELIVERABLES: Dict[str, List[str]] = {
    "collect": [
        "candidates.parquet",
        "observations.parquet",
        "collection_manifest.json",
        "run_manifest.json",
        "status.json",
    ],
    "backtest": ["triggers.parquet", "run_manifest.json", "status.json"],
    "analysis": ["scores.parquet", "metrics.json"],
}


# Which modes a research operation is authorised to run. Derived rather than declared:
# adding a field to StudySpec would change `compute_sha256` for every study and mark
# every existing compiled_study.json stale, which is a far wider change than this finding.
OPERATION_MODES: Dict[str, List[str]] = {
    "train_evaluate": ["collect"],
    "artifact_reconstruction": ["collect"],
    "runtime_population_parity": ["collect"],
    "score_parity": ["collect"],
    "execution_economics": ["collect", "backtest"],
    "bespoke_operation": ["collect"],
}


def modes_for_operation(operation_kind: str) -> List[str]:
    """Resolves the modes a study of this operation kind is accountable for."""
    return list(OPERATION_MODES.get(operation_kind, ["collect"]))


def artifact_modes(artifact: str) -> List[str]:
    """Modes that produce ``artifact``. Accepts single-owner or shared declarations."""
    meta = KNOWN_ARTIFACT_PRODUCERS[artifact]
    if "modes" in meta:
        return list(meta["modes"])
    return [meta["mode"]]


class DeliverableContractError(ValueError):
    """Raised when a study declares a deliverable set no mode can satisfy."""


def compile_deliverables_contract(
    modes: Optional[List[str]] = None,
    declared_overrides: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Compiles the authoritative, mode-partitioned deliverables contract.

    Args:
        modes: Modes this study is authorised to run. Defaults to ``["collect"]``.
        declared_overrides: Optional explicit per-mode deliverable lists. Every entry is
            validated against ``KNOWN_ARTIFACT_PRODUCERS`` and against the mode that
            actually produces it, so an override can narrow a mode's set but never
            declare something unreachable.
    """
    modes = list(modes or ["collect"])
    unknown_modes = [m for m in modes if m not in MODE_DELIVERABLES]
    if unknown_modes:
        raise DeliverableContractError(
            f"UNKNOWN_MODE: {unknown_modes}; known modes are {sorted(MODE_DELIVERABLES)}"
        )

    by_mode: Dict[str, List[str]] = {}
    for mode in modes:
        declared = (declared_overrides or {}).get(mode, MODE_DELIVERABLES[mode])
        for artifact in declared:
            meta = KNOWN_ARTIFACT_PRODUCERS.get(artifact)
            if meta is None:
                raise DeliverableContractError(
                    f"UNKNOWN_DELIVERABLE: '{artifact}' declared for mode '{mode}' has no known "
                    f"producer. Known artifacts: {sorted(KNOWN_ARTIFACT_PRODUCERS)}"
                )
            producing_modes = artifact_modes(artifact)
            if mode not in producing_modes:
                raise DeliverableContractError(
                    f"UNREACHABLE_DELIVERABLE: '{artifact}' is declared for mode '{mode}' but is "
                    f"produced by {producing_modes} ({meta['producer']}). A mode cannot be "
                    f"held to an artifact it does not produce."
                )
        by_mode[mode] = list(declared)

    return {
        "contract_version": 1,
        "authorized_modes": modes,
        "deliverables_by_mode": by_mode,
        "artifact_metadata": {
            a: KNOWN_ARTIFACT_PRODUCERS[a] for m in modes for a in by_mode[m]
        },
        "note": (
            "Authoritative deliverable set. The contract-checker consumes this and MUST NOT "
            "assemble its own list; a checker that derives its own scope cannot detect scope "
            "loss. Artifacts for modes not listed in authorized_modes are out of scope for "
            "this study and must not be reported as missing."
        ),
    }


def required_deliverables_for_mode(contract: Dict[str, Any], mode: str) -> List[str]:
    """Returns the declared deliverables for one mode, refusing an unauthorized mode."""
    by_mode = contract.get("deliverables_by_mode", {})
    if mode not in by_mode:
        raise DeliverableContractError(
            f"MODE_NOT_AUTHORIZED: '{mode}' is not among this study's authorized modes "
            f"{sorted(by_mode)}"
        )
    return list(by_mode[mode])

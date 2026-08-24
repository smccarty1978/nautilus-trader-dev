"""Small canonical lifecycle API for declarative studies."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from research_workflow.collection import collect_period
from research_workflow.experiment import (
    assert_oos_open,
    authorize_experiment,
    write_train_freeze,
)

from research_workflow.compiler import compile_study
from research_workflow.phase0 import build_phase0_manifest
from research_workflow.readiness import run_readiness
from research_workflow.preflight import run_preflight
from research_workflow.seal import generate_preexec_audit_seal, verify_preexec_audit_seal
from research_workflow.smoke import run_smoke
from research_workflow.prepare import run_prepare_and_freeze


def prepare(study_path: str | Path) -> dict[str, Any]:
    """Compile and materialize generic phase-zero before freezing."""
    study = Path(study_path).resolve()
    compile_study(study)
    build_phase0_manifest(study)
    run_prepare_and_freeze(study)
    frozen = study / "audit" / "frozen_execution_manifest.json"
    payload = __import__("json").loads(frozen.read_text(encoding="utf-8")) if frozen.exists() else {}
    return {
        "stage": "prepare",
        "status": "PASS" if payload.get("frozen_execution_composite_sha256") else "UNKNOWN",
        "artifact": str(frozen),
        "composite": payload.get("frozen_execution_composite_sha256"),
    }


def readiness(study_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    return run_readiness(study_path, **kwargs)


def bounded_preflight(study_path: str | Path, **kwargs: Any):
    if "out_json" in kwargs and kwargs["out_json"] is not None:
        kwargs["out_json"] = Path(kwargs["out_json"])
    return run_preflight(Path(study_path).resolve(), [], **kwargs)


def seal(study_path: str | Path) -> dict[str, Any]:
    study = Path(study_path).resolve()
    artifact = generate_preexec_audit_seal(study)
    verify_preexec_audit_seal(study)
    return artifact


# Generic train/OOS experiment surface.  These wrappers intentionally contain no
# study-specific branching; the study contract and supplied frames are authoritative.
def authorize_experiment_stage(study_path: str | Path):
    return authorize_experiment(study_path)


def collect_experiment_period(study_path: str | Path, period: str, **kwargs: Any):
    return collect_period(study_path, period, **kwargs)


def open_oos(study_path: str | Path):
    return assert_oos_open(study_path)


__all__ = ["prepare", "readiness", "bounded_preflight", "seal", "run_smoke"]

"""Small canonical lifecycle API for declarative studies."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from research_workflow.compiler import compile_study
from research_workflow.phase0 import build_phase0_manifest
from research_workflow.readiness import run_readiness
from research_workflow.preflight import run_preflight
from research_workflow.seal import generate_preexec_audit_seal, verify_preexec_audit_seal
from research_workflow.smoke import main as smoke_cli
from scripts.prepare_and_freeze import run_prepare_and_freeze


def prepare(study_path: str | Path) -> None:
    """Compile and materialize generic phase-zero before freezing."""
    study = Path(study_path).resolve()
    compile_study(study)
    build_phase0_manifest(study)
    run_prepare_and_freeze(study)


def readiness(study_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    return run_readiness(study_path, **kwargs)


def bounded_preflight(study_path: str | Path, **kwargs: Any):
    return run_preflight(Path(study_path).resolve(), [], **kwargs)


def seal(study_path: str | Path) -> dict[str, Any]:
    study = Path(study_path).resolve()
    artifact = generate_preexec_audit_seal(study)
    verify_preexec_audit_seal(study)
    return artifact


__all__ = ["prepare", "readiness", "bounded_preflight", "seal", "smoke_cli"]

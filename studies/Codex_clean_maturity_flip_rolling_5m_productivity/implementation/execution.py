"""Single authorization boundary required before collection, freeze, or fit."""
from __future__ import annotations

from pathlib import Path

from .phase0 import ALLOWED_COLLECTION_INPUTS, authorize_execution


def authorize_stage(manifest_path: Path, stage: str, requested_years: list[int]) -> dict:
    if stage not in {"collection", "feature_freeze", "fit"}:
        raise RuntimeError(f"unrecognized execution stage: {stage}")
    manifest = authorize_execution(manifest_path)
    allowed = set(ALLOWED_COLLECTION_INPUTS["years"])
    if not requested_years or not set(requested_years) <= allowed:
        raise RuntimeError(f"{stage} requested forbidden or empty years: {requested_years}")
    return manifest

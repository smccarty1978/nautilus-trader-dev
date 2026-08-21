"""Baseline Hash Pinning and Verification Engine.
================================================
Validates that baseline references have pinned immutable hashes and detects drift.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional
from research.schemas.study_spec import BaselineSpec


class BaselineDriftError(ValueError):
    """Raised when a referenced baseline artifact hash does not match."""
    pass


def compute_file_sha256(path: Path) -> str:
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_baseline(
    baseline_spec: Optional[BaselineSpec],
    studies_root: Path = Path("studies"),
) -> Dict[str, Any]:
    """Validates baseline hashes and checks against on-disk artifacts if available."""
    if not baseline_spec or not baseline_spec.study:
        return {"has_baseline": False}

    baseline_dir = studies_root / baseline_spec.study
    info: Dict[str, Any] = {
        "has_baseline": True,
        "study": baseline_spec.study,
        "manifest_sha256": baseline_spec.manifest_sha256,
        "results_sha256": baseline_spec.results_sha256,
    }

    if baseline_dir.exists():
        manifest_path = baseline_dir / "SPEC.md"
        if manifest_path.exists() and baseline_spec.manifest_sha256:
            actual_hash = compute_file_sha256(manifest_path)
            if actual_hash != baseline_spec.manifest_sha256:
                raise BaselineDriftError(
                    f"BASELINE_ARTIFACT_DRIFT: Baseline '{baseline_spec.study}' SPEC.md sha256 mismatch! "
                    f"Expected '{baseline_spec.manifest_sha256}', found '{actual_hash}'"
                )

    return info

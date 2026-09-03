"""Repository research policy constants and their enforcement helpers.

OLD_RUNTIME_POLICY = LEGACY_ONLY_FOR_NEW_RESEARCH (recorded 2026-09-02 at tag
baseline/2026-09-platform-v2-proven):

* no new study may target the old runtime (``research_workflow.generic_collector`` and the
  v1 ``study.yaml`` grammar);
* historical sealed studies keep their historical execution authority at their own commit;
* historical runtime implementations are not deleted and historical seals are never rewritten;
* no compatibility migration is required or performed.
"""
from __future__ import annotations

from pathlib import Path

OLD_RUNTIME_POLICY = "LEGACY_ONLY_FOR_NEW_RESEARCH"
POLICY_RECORDED_AT = "baseline/2026-09-platform-v2-proven"

# A v1 study with any of these already holds historical execution authority and stays runnable.
_HISTORICAL_AUTHORITY_MARKERS = (
    "artifacts/preexec_audit_seal.json",
    "audit/frozen_execution_manifest.json",
    "artifacts/study_closure.json",
    "artifacts/train_experiment_freeze.json",
)


class OldRuntimePolicyError(RuntimeError):
    pass


def historical_authority(study_dir: Path) -> list[str]:
    study_dir = Path(study_dir)
    return [m for m in _HISTORICAL_AUTHORITY_MARKERS if (study_dir / m).is_file()]


def assert_old_runtime_allowed(study_dir: Path) -> dict:
    """Raise unless ``study_dir`` is a Platform-v2 study or a v1 study with historical authority."""
    from research_workflow.lifecycle_v2 import is_v2_study
    study_dir = Path(study_dir)
    if is_v2_study(study_dir):
        return {"platform": "v2", "policy": OLD_RUNTIME_POLICY}
    markers = historical_authority(study_dir)
    if markers:
        return {"platform": "v1_historical", "policy": OLD_RUNTIME_POLICY, "authority_markers": markers}
    raise OldRuntimePolicyError(
        f"OLD_RUNTIME_LEGACY_ONLY: {study_dir.name} is a v1 study without historical execution authority; "
        f"policy {OLD_RUNTIME_POLICY} ({POLICY_RECORDED_AT}) -- new research must be a Platform V2 study "
        f"(`python scripts/research.py study new <id>`; see WORKFLOW.md)")


__all__ = ["OLD_RUNTIME_POLICY", "POLICY_RECORDED_AT", "OldRuntimePolicyError", "assert_old_runtime_allowed", "historical_authority"]

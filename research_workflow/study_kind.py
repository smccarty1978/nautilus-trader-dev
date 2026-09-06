"""Leaf predicate: is a study directory a Platform-v2 (declarative) study?

Lives in its own import-free module so that governance code (``research_workflow.policy``) and the
model store can ask the question without importing the V2 controller. Before this split
``policy.assert_old_runtime_allowed`` imported ``lifecycle_v2`` for exactly this function, which put the
whole controller -- and, through it, the compiler, tuning and analysis modules -- on the static import
walk of the frozen-model scoring path and therefore inside the partition-reuse key
(chore/collection_latency, Reading 2, 2026-09-06). Semantics are unchanged.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def is_v2_study(study: Path) -> bool:
    p = Path(study) / "study.yaml"
    if not p.is_file():
        return False
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    return isinstance(data, dict) and "streams" in data and not (isinstance(data.get("study"), dict) and data["study"].get("type"))


__all__ = ["is_v2_study"]

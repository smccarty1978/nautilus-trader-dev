"""Typed, study-independent feature-candidate authority contract."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

REQUIRED = ("authority_id", "authority_type", "candidate_features", "semantics",
            "implementation", "evidence_requirements", "promotion_scope",
            "prohibited_scope_expansion", "terminal_decision")

def load(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8")) if p.suffix.lower() == ".json" else __import__("yaml").safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("authority_type") != "feature_candidate":
        raise ValueError("FEATURE_AUTHORITY_TYPE_INVALID")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise ValueError(f"FEATURE_AUTHORITY_SCHEMA_MISSING: {missing}")
    if data.get("terminal_decision") not in {"PROMOTE", "BLOCK", "DEFER"}:
        raise ValueError("FEATURE_AUTHORITY_TERMINAL_DECISION_INVALID")
    return data

def validate(path: str | Path) -> dict[str, Any]:
    return load(path)

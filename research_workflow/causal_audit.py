"""Structured causal-review API."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def run_causal_review(study_path: str | Path) -> dict[str, Any]:
    study = Path(study_path).resolve()
    artifact = study / "audit" / "status.json"
    if not artifact.is_file():
        return {"status": "NOT_RUN", "study": str(study), "artifact": str(artifact)}
    data = json.loads(artifact.read_text(encoding="utf-8"))
    value = str(data.get("causal", data.get("causal_status", "NOT_RUN"))).upper()
    return {"status": "CLEAR" if value in {"CLEAR", "PASS", "PASSED"} else value,
            "study": str(study), "artifact": str(artifact), "evidence": data}

__all__ = ["run_causal_review"]

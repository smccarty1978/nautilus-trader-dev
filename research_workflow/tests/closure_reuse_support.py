"""Test support: the parent study's CLOSURE is the positive authority for frozen-model reuse.

Since 2026-09-10 (cleanup-and-closure packet, Part C) a registry ``scientific_status`` value never
authorizes reuse as a derived causal input. A child study binds a frozen model only through a
``diagnostic_reuse_policy`` that pins the parent's canonical closure, whose
``model_scientific_assessment`` + ``reuse_policy`` names the model. These helpers write that
closure and build the matching policy for a record persisted with ``persist_models``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping

from research.analysis.identity import canonical_sha256

AUTHORIZING_REUSE_POLICY = ("Discoverable for future GOVERNED derived-input use if a child study's reuse "
                            "policy explicitly permits diagnostic-derived input.")


def write_reuse_closure(study: Path, rec: Mapping[str, Any], *, role: str = "A") -> Path:
    """Write ``<study>/artifacts/study_closure.json`` authorizing ``rec`` for governed reuse."""
    arts = study / "artifacts"
    arts.mkdir(parents=True, exist_ok=True)
    for name in ("causal.md", "contract.md"):
        (arts / name).write_text(name, encoding="utf-8")
    freeze = arts / "train_experiment_freeze.json"
    if not freeze.is_file():
        freeze.write_text(json.dumps({"freeze_sha256": "synthetic-freeze"}), encoding="utf-8")
    closure = {
        "schema_version": 1, "study_id": study.name, "status": "CLOSED",
        "closed_at_utc": "2026-01-01T00:00:00+00:00",
        "outcome": "DIAGNOSTIC", "terminal_decision": "diagnostic",
        "models": {role: {"model_id": rec["model_id"], "artifact_sha256": rec["artifact_sha256"]}},
        "model_scientific_assessment": {"assessment": "VALID_DIAGNOSTIC", "reuse_policy": AUTHORIZING_REUSE_POLICY},
        "bound_evidence": {
            "train_freeze_sha256": hashlib.sha256(freeze.read_bytes()).hexdigest(),
            "causal_audit": {"verdict": "CLEAR", "report": "artifacts/causal.md"},
            "contract_audit": {"verdict": "CLEAR", "report": "artifacts/contract.md"},
        },
    }
    closure["closure_identity_sha256"] = canonical_sha256({k: v for k, v in closure.items() if k != "closed_at_utc"})
    path = arts / "study_closure.json"
    path.write_text(json.dumps(closure), encoding="utf-8")
    return path


def reuse_policy_for(study: Path, rec: Mapping[str, Any]) -> Dict[str, Any]:
    """The child-side ``diagnostic_reuse_policy`` pinning the closure written by ``write_reuse_closure``."""
    closure = study / "artifacts" / "study_closure.json"
    body = json.loads(closure.read_text(encoding="utf-8"))
    return {
        "kind": "diagnostic_derived_causal_input", "model_id": rec["model_id"],
        "parent_study_id": study.name, "parent_closure_path": "artifacts/study_closure.json",
        "parent_closure_sha256": hashlib.sha256(closure.read_bytes()).hexdigest(),
        "parent_closure_identity_sha256": body["closure_identity_sha256"],
        "expected_assessment": "VALID_DIAGNOSTIC", "artifact_sha256": rec["artifact_sha256"],
    }


def refresh_closure_identity(study: Path) -> None:
    path = study / "artifacts" / "study_closure.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["closure_identity_sha256"] = canonical_sha256(
        {k: v for k, v in body.items() if k not in {"closed_at_utc", "closure_identity_sha256"}})
    path.write_text(json.dumps(body), encoding="utf-8")

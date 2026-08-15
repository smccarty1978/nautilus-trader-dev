"""Pure contract, terminal-label, and selected-result seal helpers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PRIMARY_BUCKETS = ("300-600s", "600-900s", "900-1800s")
MATERIAL_AUC_DELTA = 0.001
TERMINAL_LABELS = (
    "S1_STRUCTURAL_GEOMETRY_ADDS_REAL_INFORMATION",
    "S2_YOUNGER_REGIMES_SPECIFICALLY",
    "S3_CLASSIFICATION_ONLY",
    "S4_ECONOMIC_TAIL_ONLY",
    "S5_NO_MATERIAL_INCREMENTAL_INFORMATION",
    "ABORT_CONTRACT_OR_CAUSAL_FAILURE",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify_terminal(*, abort: bool, classification_cells: int,
                      younger_only: bool, economics_nonworse: bool,
                      economic_tail_only: bool) -> str:
    """Reach every frozen terminal label without a hidden discretionary branch."""
    if abort:
        return "ABORT_CONTRACT_OR_CAUSAL_FAILURE"
    classification_improves = classification_cells >= 2
    if classification_improves and economics_nonworse:
        return "S2_YOUNGER_REGIMES_SPECIFICALLY" if younger_only else "S1_STRUCTURAL_GEOMETRY_ADDS_REAL_INFORMATION"
    if classification_improves:
        return "S3_CLASSIFICATION_ONLY"
    if economic_tail_only:
        return "S4_ECONOMIC_TAIL_ONLY"
    return "S5_NO_MATERIAL_INCREMENTAL_INFORMATION"


def write_selection_seal(root: Path, artifacts: list[str]) -> dict[str, Any]:
    """Freeze every decision input/output; the seal file itself is not recursive."""
    missing = [item for item in artifacts if not (root / item).is_file()]
    payload = {"schema_version": 1, "artifacts": {item: sha256(root / item) for item in artifacts if (root / item).is_file()}, "missing": missing}
    payload["artifact_count"] = len(payload["artifacts"])
    payload["seal_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (root / "selection_seal.json").write_text(json.dumps(payload, indent=2))
    return payload


def verify_selection_seal(root: Path) -> dict[str, Any]:
    seal_path = root / "selection_seal.json"
    if not seal_path.is_file():
        return {"pass": False, "reason": "missing_selection_seal"}
    seal = json.loads(seal_path.read_text())
    mismatches = [name for name, expected in seal.get("artifacts", {}).items() if not (root / name).is_file() or sha256(root / name) != expected]
    payload = {key: seal.get(key) for key in ("schema_version", "artifacts", "missing", "artifact_count")}
    recomputed = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    seal_hash_matches = recomputed == seal.get("seal_sha256")
    return {"pass": not seal.get("missing") and not mismatches and seal_hash_matches, "missing_at_seal_time": seal.get("missing", []), "mismatches": mismatches, "seal_hash_matches": seal_hash_matches, "seal_sha256": seal.get("seal_sha256")}

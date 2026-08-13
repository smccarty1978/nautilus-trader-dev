"""Frozen artifact loader and independent NT runtime collector."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import joblib
import numpy as np
import nautilus_trader

from .phase_a_strategy import PhaseABullishCollector


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_frozen_adapter(artifact_dir: Path):
    import json
    dependencies = json.loads(
        (artifact_dir / "dependency_manifest.json").read_text(encoding="utf-8")
    )
    if getattr(nautilus_trader, "__version__", None) != dependencies["nautilus_trader_version"]:
        raise RuntimeError("NautilusTrader runtime version mismatch")
    repo_root = Path(__file__).resolve().parents[3]
    for relative, expected in dependencies["dependencies"].items():
        if sha256_file(repo_root / relative) != expected:
            raise RuntimeError(f"frozen causal dependency mismatch: {relative}")
    path = artifact_dir / "adapter.py"
    spec = importlib.util.spec_from_file_location("frozen_bullish_adapter_v2", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FrozenBullishAdapter()


class FrozenBullishScorer:
    def __init__(self, artifact_dir: Path):
        import json
        self.artifact_dir = artifact_dir
        manifest = json.loads((artifact_dir / "model_manifest.json").read_text(encoding="utf-8"))
        if sha256_file(artifact_dir / "model.joblib") != manifest["model_sha256"]:
            raise RuntimeError("frozen model hash mismatch")
        self.features = list(manifest["features"])
        self.model = joblib.load(artifact_dir / "model.joblib")
        if list(self.model.classes_) != [0, 1]:
            raise RuntimeError("unexpected frozen model classes")

    def probability(self, vector: list[float]) -> float:
        arr = np.asarray(vector, dtype=np.float64).reshape(1, -1)
        if arr.shape[1] != len(self.features):
            raise ValueError("runtime vector width mismatch")
        return float(self.model.predict_proba(arr)[0, 1])


class FrozenRuntimeCollector(PhaseABullishCollector):
    """Same NT event contract, independently initialized frozen adapter state."""

    artifact_dir: Path | None = None

    def __init__(self, config):
        super().__init__(config)
        artifact_dir = Path(self.artifact_dir or "")
        self._features = load_frozen_adapter(artifact_dir)
        self._runtime_scorer = FrozenBullishScorer(artifact_dir)
        self.runtime_scores: dict[tuple[int, int], float | None] = {}

    def _on_checkpoint(self, row: dict) -> None:
        before = len(self.checkpoint_rows)
        super()._on_checkpoint(row)
        if len(self.checkpoint_rows) == before:
            return
        emitted = self.checkpoint_rows[-1]
        key = (emitted["regime_start_ns"], emitted["checkpoint_decision_ns"])
        if emitted["feature_complete"]:
            vector = [emitted[name] for name in self._features.features]
            self.runtime_scores[key] = self._runtime_scorer.probability(vector)
        else:
            self.runtime_scores[key] = None

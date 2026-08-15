"""Authenticated phase-zero source contract for the clean study.

This module is intentionally executed before collection, feature selection, or
model fitting.  It reads the actual frozen config and actual importable feature
definitions; it does not accept a caller-provided assertion about either.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import yaml

from features.registry import FEATURE_REGISTRY


ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "studies" / "Codex_clean_maturity_flip_rolling_5m_productivity"
CONFIG_PATH = STUDY / "config" / "study.yaml"
SPEC_PATH = STUDY / "SPEC.md"
REGISTRY_PATH = ROOT / "features" / "registry.py"
ENGINE_PATH = ROOT / "features" / "engine.py"
FORBIDDEN_LINEAGE_TOKENS = (
    "canonical_regime_scores_all.parquet",
    "F3_top25",
    "frozen_train_only_baselines",
)
ALLOWED_COLLECTION_INPUTS = {
    "catalog_root": "data/catalog",
    "years": [2021, 2022, 2023, 2024],
    "feature_source": "features.registry.FEATURE_REGISTRY",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_numeric_candidates() -> list[str]:
    """Return the clean baseline universe directly from loaded registry state."""
    accepted = {"float64", "float32", "int64", "int32"}
    candidates = [
        name for name, definition in FEATURE_REGISTRY.items()
        if definition.status == "verified"
        and definition.dtype in accepted
        and definition.implementation.startswith("features.")
    ]
    if len(candidates) < 25:
        raise RuntimeError(f"registry has only {len(candidates)} verified numeric candidates")
    return sorted(candidates)


def _read_config() -> dict[str, Any]:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    expected = {
        "study_id": "Codex_clean_maturity_flip_rolling_5m_productivity",
        "instrument_id": "NQ.XCME",
        "session": "RTH",
        "train_years": [2021, 2022, 2023],
        "oos_year": 2024,
        "unused_years": [2025],
        "sealed_years": [2026],
    }
    wrong = {key: {"expected": value, "actual": config.get(key)} for key, value in expected.items() if config.get(key) != value}
    if wrong:
        raise RuntimeError(f"frozen config authentication failed: {wrong}")
    universe = config.get("candidate_universe", {})
    if universe != {
        "source": "features.registry.FEATURE_REGISTRY",
        "allowed_status": "verified",
        "selection_years": [2021, 2022, 2023],
        "feature_count": 25,
        "selection_method": "frozen_train_only_temporal_rank",
    }:
        raise RuntimeError("candidate-universe config does not match frozen contract")
    if config.get("rolling_productivity", {}) != {
        "window_seconds": 300,
        "source_timeframe": "1s_completed",
        "atr_normalizer": "current_1m_regime_start",
    }:
        raise RuntimeError("rolling-productivity config does not match frozen contract")
    return config


def _implementation_path(definition_name: str) -> Path:
    definition = FEATURE_REGISTRY[definition_name]
    module_name = definition.implementation.rpartition(".")[0]
    if not module_name:
        raise RuntimeError(f"{definition_name}: missing implementation module")
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        raise RuntimeError(f"{definition_name}: implementation module is not importable")
    path = Path(spec.origin).resolve()
    features_root = (ROOT / "features").resolve()
    if features_root not in path.parents:
        raise RuntimeError(f"{definition_name}: implementation escapes central features tree: {path}")
    return path


def _assert_no_forbidden_lineage(paths: list[Path]) -> None:
    for path in paths:
        content = path.read_text(encoding="utf-8")
        hits = [token for token in FORBIDDEN_LINEAGE_TOKENS if token in content]
        if hits:
            raise RuntimeError(f"forbidden F3/future lineage token(s) in {path}: {hits}")


def authenticate() -> dict[str, Any]:
    """Authenticate frozen source/config facts and return a persisted manifest body."""
    config = _read_config()
    candidates = verified_numeric_candidates()
    implementation_paths = sorted({_implementation_path(name) for name in candidates})
    collector_path = STUDY / "implementation" / "collector.py"
    phase0_path = Path(__file__).resolve()
    source_paths = [REGISTRY_PATH, ENGINE_PATH, collector_path, *implementation_paths]
    _assert_no_forbidden_lineage(source_paths)
    inventory = {
        name: asdict(FEATURE_REGISTRY[name]) for name in candidates
    }
    return {
        "schema_version": 1,
        "authenticated": True,
        "config": config,
        "candidate_count": len(candidates),
        "candidate_features": candidates,
        "candidate_inventory": inventory,
        "study_yaml_sha256": sha256(CONFIG_PATH),
        "registry_sha256": sha256(REGISTRY_PATH),
        "spec_sha256": sha256(SPEC_PATH),
        "source_code_sha256": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in [phase0_path, *source_paths]
        },
        "forbidden_lineage_tokens": list(FORBIDDEN_LINEAGE_TOKENS),
        "collection_input_allowlist": ALLOWED_COLLECTION_INPUTS,
        "forbidden_collection_years": [2025, 2026],
        "allowed_actions_after_exact_manifest_verification": ["collection", "feature_freeze", "fit"],
    }


def write_manifest(output_path: Path) -> dict[str, Any]:
    """Write the authenticated phase-zero manifest; caller owns the output root."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = authenticate()
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def authorize_execution(manifest_path: Path) -> dict[str, Any]:
    """Fail closed unless the persisted phase-zero manifest is exactly current."""
    if not manifest_path.is_file():
        raise RuntimeError("phase-zero authorization missing; collection and fit are refused")
    observed = json.loads(manifest_path.read_text())
    # Canonicalize tuples in registry metadata exactly as JSON persistence does.
    expected = json.loads(json.dumps(authenticate(), sort_keys=True))
    if observed != expected:
        raise RuntimeError("phase-zero authorization is stale or altered; collection and fit are refused")
    return observed

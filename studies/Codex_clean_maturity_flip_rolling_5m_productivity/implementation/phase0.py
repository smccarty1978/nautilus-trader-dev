"""Authenticated phase-zero source contract for the clean study.

This module is intentionally executed before collection, feature selection, or
model fitting.  It reads the actual frozen config and actual importable feature
definitions; it does not accept a caller-provided assertion about either.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import yaml

from features.registry import resolve_feature_request, resolve_source_universe


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
    "feature_source": "features.registry.resolve_feature_request",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_numeric_candidates(*, feature_authority: str = "active", legacy_mode: bool = False) -> list[str]:
    """Return the clean baseline universe directly from loaded registry state."""
    source = "verified_registry_numeric_universe" if legacy_mode else "canonical_verified_definition_universe"
    candidates = resolve_source_universe(source, authority=feature_authority, legacy_mode=legacy_mode)
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
        "source": "canonical_verified_definition_universe",
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


def _implementation_path(definition_name: str, *, feature_authority: str = "active") -> Path:
    resolved = resolve_feature_request(definition_name, authority=feature_authority)
    module_name = str(resolved["provider"]).rpartition(".")[0]
    if not module_name:
        raise RuntimeError(f"{definition_name}: missing implementation module")
    try:
        spec = importlib.util.find_spec(module_name)
    except ModuleNotFoundError as exc:
        raise RuntimeError(f"{definition_name}: implementation module is not importable") from exc
    if spec is None or spec.origin is None:
        raise RuntimeError(f"{definition_name}: implementation module is not importable")
    path = Path(spec.origin).resolve()
    features_root = (ROOT / "features").resolve()
    if features_root not in path.parents:
        raise RuntimeError(f"{definition_name}: implementation escapes central features tree: {path}")
    return path


def _resolved_definition(definition_name: str, *, feature_authority: str = "active"):
    """Return the lifecycle authority for a resolved physical alias."""
    return resolve_feature_request(definition_name, authority=feature_authority)


def _assert_no_forbidden_lineage(paths: list[Path]) -> None:
    for path in paths:
        content = path.read_text(encoding="utf-8")
        hits = [token for token in FORBIDDEN_LINEAGE_TOKENS if token in content]
        if hits:
            raise RuntimeError(f"forbidden F3/future lineage token(s) in {path}: {hits}")


def authenticate(*, feature_authority: str = "active", legacy_mode: bool = False) -> dict[str, Any]:
    """Authenticate frozen source/config facts and return a persisted manifest body."""
    config = _read_config()
    candidates = verified_numeric_candidates(feature_authority=feature_authority, legacy_mode=legacy_mode)
    implementation_paths = sorted({_implementation_path(name, feature_authority=feature_authority) for name in candidates})
    collector_path = STUDY / "implementation" / "collector.py"
    phase0_path = Path(__file__).resolve()
    source_paths = [REGISTRY_PATH, ENGINE_PATH, collector_path, *implementation_paths]
    _assert_no_forbidden_lineage(source_paths)
    inventory = {}
    for name in candidates:
        definition = _resolved_definition(name, feature_authority=feature_authority)
        inventory[name] = {**definition, "status": "verified"}
    manifest = {
        "schema_version": 1,
        "authenticated": True,
        "config": config,
        "candidate_count": len(candidates),
        "legacy_mode": bool(legacy_mode),
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
    # Preserve the historical active manifest byte contract.  Candidate mode is
    # explicit and self-describing so a collector cannot accidentally re-resolve
    # through active authority while reviewing it.
    if feature_authority != "active":
        manifest["feature_authority"] = feature_authority
    return manifest


def write_manifest(output_path: Path, *, feature_authority: str = "active", legacy_mode: bool = False) -> dict[str, Any]:
    """Write the authenticated phase-zero manifest; caller owns the output root."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = authenticate(feature_authority=feature_authority, legacy_mode=legacy_mode)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def authorize_execution(manifest_path: Path) -> dict[str, Any]:
    """Fail closed unless the persisted phase-zero manifest is exactly current."""
    if not manifest_path.is_file():
        raise RuntimeError("phase-zero authorization missing; collection and fit are refused")
    observed = json.loads(manifest_path.read_text())
    # Canonicalize tuples in registry metadata exactly as JSON persistence does.
    feature_authority = observed.get("feature_authority", "active")
    expected = json.loads(json.dumps(authenticate(
        feature_authority=feature_authority,
        legacy_mode=bool(observed.get("legacy_mode", False)),
    ), sort_keys=True))
    if observed != expected:
        raise RuntimeError("phase-zero authorization is stale or altered; collection and fit are refused")
    return observed

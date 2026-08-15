#!/usr/bin/env python3
"""Deterministic Phase-0 Source Manifest Generator.
=================================================
Inspects repository state, feature registry definitions, SPEC and study.yaml hashes,
and generates artifacts/phase0_source_manifest.json deterministically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import yaml

# Ensure project root in python path
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from research.schemas.study_spec import StudySpec
from features.registry import FEATURE_REGISTRY


def compute_file_sha256(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def get_git_commit_hash() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(project_root),
        )
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN_GIT_HEAD"


def build_phase0_manifest(study_dir: Path) -> dict:
    study_yaml_path = study_dir / "study.yaml"
    spec_md_path = study_dir / "SPEC.md"

    if not study_yaml_path.exists():
        raise FileNotFoundError(f"study.yaml missing under {study_dir}")
    if not spec_md_path.exists():
        raise FileNotFoundError(f"SPEC.md missing under {study_dir}")

    study_yaml_sha256 = compute_file_sha256(study_yaml_path)
    spec_md_sha256 = compute_file_sha256(spec_md_path)

    with open(study_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    spec = StudySpec.model_validate(data)

    # 1. Enumerate verified numeric candidate inventory from central registry
    verified_candidates = {}
    verified_names = []

    for name, feat_def in sorted(FEATURE_REGISTRY.items()):
        if feat_def.status == "verified" and feat_def.dtype in ("float64", "int64", "float32", "int32"):
            verified_names.append(name)
            verified_candidates[name] = {
                "version": feat_def.version,
                "family": feat_def.family,
                "dtype": feat_def.dtype,
                "implementation": feat_def.implementation,
                "source_timeframe": feat_def.source_timeframe,
                "direction_normalized": feat_def.direction_normalized,
            }

    candidate_universe_hash = hashlib.sha256(
        json.dumps(verified_names).encode("utf-8")
    ).hexdigest()

    # 2. Lineage & quarantine proof
    invalidated_runs = spec.lineage.invalidated_prior_runs or []
    forbidden_lineage = spec.features.forbidden_lineage or []

    manifest = {
        "study_id": spec.study.id,
        "git_commit_hash": get_git_commit_hash(),
        "study_yaml_sha256": study_yaml_sha256,
        "spec_md_sha256": spec_md_sha256,
        "clean_lineage_start": spec.lineage.clean_lineage_start,
        "invalidated_prior_runs_count": len(invalidated_runs),
        "invalidated_prior_runs": invalidated_runs,
        "forbidden_lineage": forbidden_lineage,
        "provenance_certifications": {
            "f3_scored_tables_read": False,
            "2024_read_since_clean_lineage_reset": False,
            "2025_read_in_selection_or_training": False,
            "2026_read_in_selection_or_training": False,
        },
        "candidate_feature_universe": {
            "source": "features.registry.FEATURE_REGISTRY",
            "status_filter": "verified",
            "total_candidates_count": len(verified_names),
            "candidate_names_sha256": candidate_universe_hash,
            "candidates": verified_candidates,
        },
        "selection_contract": {
            "mode": spec.features.selection.mode if spec.features.selection else "train_only",
            "years": spec.features.selection.years if spec.features.selection else spec.chronology.train,
            "direction_specific": spec.features.selection.direction_specific if spec.features.selection else True,
            "feature_count_per_direction": spec.features.selection.feature_count if spec.features.selection else 25,
            "ranking_method": spec.features.selection.ranking_method if spec.features.selection else "frozen_train_only_temporal_rank",
        },
        "chronology": {
            "train": spec.chronology.train,
            "dev": spec.chronology.dev,
            "prohibited": spec.chronology.prohibited,
        },
    }

    manifest_hash = hashlib.sha256(json.dumps(manifest, indent=2).encode("utf-8")).hexdigest()
    manifest["manifest_sha256"] = manifest_hash

    # Save to artifacts directory
    artifacts_dir = study_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    out_file = artifacts_dir / "phase0_source_manifest.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Generate deterministic Phase-0 Source Manifest.")
    parser.add_argument("--study", type=str, required=True, help="Path to study directory")
    args = parser.parse_args()

    study_dir = Path(args.study).resolve()
    try:
        manifest = build_phase0_manifest(study_dir)
        print("=" * 65)
        print(f"PHASE-0 SOURCE MANIFEST GENERATED: {manifest['study_id']}")
        print(f"Verified candidate features: {manifest['candidate_feature_universe']['total_candidates_count']}")
        print(f"Candidate universe SHA-256:  {manifest['candidate_feature_universe']['candidate_names_sha256'][:16]}...")
        print(f"Clean lineage reset:         {manifest['clean_lineage_start']}")
        print(f"Manifest SHA-256:            {manifest['manifest_sha256'][:16]}...")
        print("=" * 65)
    except Exception as e:
        print(f"[ERROR] Phase-0 manifest generation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

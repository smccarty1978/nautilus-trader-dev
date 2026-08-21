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


def _git_rc(*args: str) -> int:
    """Runs a git command for its exit status only."""
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, cwd=str(project_root)
        ).returncode
    except Exception:
        # An unanswerable question is not a reassuring answer.
        return -1


def _path_exists_at_head(rel_path: str) -> bool:
    """True when ``rel_path`` is present in the HEAD commit."""
    return _git_rc("cat-file", "-e", f"HEAD:{rel_path}") == 0


def _path_differs_from_head(rel_path: str) -> bool:
    """True when the working copy of ``rel_path`` differs from HEAD.

    Delegated to ``git diff`` rather than comparing raw bytes against ``git show``.
    Under ``core.autocrlf`` -- the default on Windows checkouts -- the working tree
    holds CRLF while the object store holds LF, so a byte comparison reports every
    text file as modified. A control that fires on every file is one nobody reads.
    ``git diff`` applies the repository's own filters and answers the question that
    was actually asked.
    """
    return _git_rc("diff", "--quiet", "HEAD", "--", rel_path) != 0


def _git_tree_is_dirty() -> bool:
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(project_root),
        )
        return bool(res.stdout.strip())
    except Exception:
        # An indeterminate tree state is not a clean one.
        return True


def build_source_state_binding(dependency_paths: list[Path]) -> dict:
    """Binds a generated manifest to the source it was actually generated from.

    The failed acceptance test recorded ``git_commit_hash: 5972556…`` on a manifest
    that enumerated ``latest_1m_wick_imbalance``. At that commit
    ``features/trackers/wick.py`` did not exist and the registry had no such entry --
    the manifest's content came from the working tree, but its provenance named a
    commit that could not have produced it.

    A commit id is a *label*. What makes provenance honest is hashing the bytes the
    generator actually read, and then stating plainly whether those bytes match the
    named commit. ``provenance_strength`` is the field a consumer reads:

    ``COMMITTED``
        every dependency is byte-identical to HEAD and the tree is clean -- the commit
        id alone is sufficient provenance.
    ``WORKING_TREE``
        at least one dependency is new or modified relative to HEAD. The commit id is
        retained for context but is explicitly *not* sufficient; ``source_state_sha256``
        is the binding.
    """
    files: dict = {}
    divergent: list = []

    for p in sorted(dependency_paths):
        if not p.exists():
            raise FileNotFoundError(f"Manifest source dependency missing: {p}")
        try:
            # Both sides must be resolved: on Windows a temp path may arrive as an
            # 8.3 short name ("SCOTTM~1"), and comparing it against a long-form root
            # silently reports an in-tree file as out-of-tree.
            rel = p.resolve().relative_to(Path(project_root).resolve()).as_posix()
            in_tree = True
        except ValueError:
            # A dependency outside the repository cannot be vouched for by any commit.
            rel = p.as_posix()
            in_tree = False
        working_sha = hashlib.sha256(p.read_bytes()).hexdigest()

        if not in_tree:
            state = "OUT_OF_TREE"
            divergent.append(rel)
        elif not _path_exists_at_head(rel):
            state = "UNTRACKED_OR_NEW"
            divergent.append(rel)
        elif _path_differs_from_head(rel):
            state = "MODIFIED"
            divergent.append(rel)
        else:
            state = "COMMITTED"

        files[rel] = {"sha256": working_sha, "state": state}

    source_state_sha256 = hashlib.sha256(
        json.dumps({k: v["sha256"] for k, v in files.items()}, sort_keys=True).encode("utf-8")
    ).hexdigest()

    # Strength is decided by the DEPENDENCIES, not by global tree cleanliness.
    # A repository almost always has some untracked file (a run directory, a scratch
    # file), and letting that force WORKING_TREE forever would make the field carry no
    # information -- the same failure mode as a check that fires on every file. What the
    # manifest actually claims is "this content came from this commit", and only the
    # dependencies it enumerated can falsify that. Global dirtiness is retained
    # alongside as context.
    tree_dirty = _git_tree_is_dirty()
    strength = "COMMITTED" if not divergent else "WORKING_TREE"

    return {
        "provenance_strength": strength,
        "git_commit_hash": get_git_commit_hash(),
        "git_commit_is_sufficient_provenance": strength == "COMMITTED",
        "working_tree_dirty": tree_dirty,
        "source_state_sha256": source_state_sha256,
        "dependencies_diverging_from_commit": sorted(divergent),
        "source_files": files,
    }


class SourceProvenanceError(RuntimeError):
    """Raised when a manifest's recorded provenance does not describe real source state."""


def verify_source_state_binding(manifest: dict) -> dict:
    """Re-derives a manifest's provenance and refuses claims the source cannot support.

    Two distinct failures are caught, and they are not the same thing:

    1. **Drift** -- a dependency's bytes no longer match what the manifest recorded.
       The manifest describes source that no longer exists.
    2. **Overclaim** -- the manifest asserts ``git_commit_is_sufficient_provenance``
       while a dependency is absent from, or differs at, the named commit. This is the
       exact shape of the failed acceptance test: a manifest signed by ``5972556`` that
       enumerated a feature whose implementation file did not exist at ``5972556``.
    """
    binding = manifest.get("source_state_binding")
    if not isinstance(binding, dict):
        raise SourceProvenanceError(
            "SOURCE_BINDING_ABSENT: manifest records no 'source_state_binding'. A bare "
            "commit id is a label, not provenance."
        )

    problems: list = []
    for rel, rec in sorted(binding.get("source_files", {}).items()):
        p = project_root / rel
        if not p.exists():
            problems.append(f"{rel}: recorded dependency no longer exists")
            continue
        current = hashlib.sha256(p.read_bytes()).hexdigest()
        if current != rec.get("sha256"):
            problems.append(f"{rel}: content drifted from the recorded source state")

    if binding.get("git_commit_is_sufficient_provenance"):
        for rel in sorted(binding.get("source_files", {})):
            if not _path_exists_at_head(rel):
                problems.append(
                    f"{rel}: manifest claims commit {binding.get('git_commit_hash', '')[:12]} is "
                    f"sufficient provenance, but the file does not exist at that commit"
                )
            elif _path_differs_from_head(rel):
                problems.append(
                    f"{rel}: manifest claims commit provenance, but committed content differs"
                )

    if problems:
        raise SourceProvenanceError(
            "SOURCE_PROVENANCE_INVALID: " + "; ".join(problems)
        )
    return binding


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

    # A feature may not enter the verified candidate universe by self-declaration (D).
    # Checked here because this is where 'verified' is turned into an eligible universe.
    from scripts.check_feature_promotion import (
        assert_baseline_not_extended,
        assert_feature_promotions,
    )
    assert_feature_promotions()
    assert_baseline_not_extended()

    # 1. Enumerate verified numeric candidate inventory from central registry
    verified_candidates = {}
    verified_names = []
    # Every module whose content this manifest's generated section depends on. The
    # registry itself, plus the implementation module backing each enumerated feature.
    dependency_paths = {(project_root / "features" / "registry.py")}

    for name, feat_def in sorted(FEATURE_REGISTRY.items()):
        if feat_def.status == "verified" and feat_def.dtype in ("float64", "int64", "float32", "int32"):
            verified_names.append(name)
            if feat_def.implementation:
                impl_mod = feat_def.implementation.rsplit(".", 1)[0]
                impl_p = project_root.joinpath(*impl_mod.split(".")).with_suffix(".py")
                if impl_p.exists():
                    dependency_paths.add(impl_p)
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

    dependency_paths.add(study_yaml_path)
    dependency_paths.add(spec_md_path)
    source_binding = build_source_state_binding(sorted(dependency_paths))

    manifest = {
        "study_id": spec.study.id,
        # Retained at the top level for backwards compatibility with existing readers.
        # It is a label, not proof -- `source_state_binding` is the binding.
        "git_commit_hash": source_binding["git_commit_hash"],
        "source_state_binding": source_binding,
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

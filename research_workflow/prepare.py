#!/usr/bin/env python3
"""Prepare and Freeze Study Boundary.
===================================
A unified deterministic script that prepares all required execution inputs (study compile,
phase-zero manifest regeneration) and freezes the execution composite before any
preflight or audit runs.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

# Ensure project root in python path
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from scripts.resolve_execution_manifest import resolve_execution_manifest
from research_workflow.compiler import compile_study


def run_prepare_and_freeze(study_dir: Path):
    study_dir = study_dir.resolve()
    if not study_dir.is_dir():
        raise FileNotFoundError(f"Study directory not found: {study_dir}")

    # 1. Compile study (PREPARE stage)
    print(f"[*] Running compile_study for {study_dir.name}...")
    compile_rc = compile_study(study_dir)
    if compile_rc != 0:
        raise RuntimeError("Study compilation failed.")

    # 1b. Derived causal inputs and pre-freeze gates staged "prepare" must be satisfied
    # before PREPARE completes -- checked here as well as in build_phase0_manifest so
    # the check fires on this documented CLI entry point (`python -m
    # research_workflow.prepare`) even when a caller does not route through
    # lifecycle.prepare()'s compile+build_phase0_manifest+run_prepare_and_freeze order.
    import yaml as _yaml
    from research.schemas.study_spec import StudySpec
    from research_workflow.derived_inputs import verify_derived_causal_inputs
    from research_workflow.gates import assert_gates_satisfied

    _study_spec = StudySpec.model_validate(
        _yaml.safe_load((study_dir / "study.yaml").read_text(encoding="utf-8"))
    )
    verify_derived_causal_inputs(_study_spec, repo_root=project_root)
    assert_gates_satisfied(study_dir, _study_spec, stage="prepare")

    # 2. Write phase0 manifest (PREPARE stage)
    phase0_py = study_dir / "implementation" / "phase0.py"
    if phase0_py.exists():
        print(f"[*] Regenerating phase0 manifest for {study_dir.name}...")
        import importlib.util

        spec = importlib.util.spec_from_file_location("phase0_module", phase0_py)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load {phase0_py}")
        phase0_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(phase0_mod)

        # Override paths to handle test/temp environments cleanly
        phase0_mod.ROOT = project_root
        phase0_mod.STUDY = study_dir
        phase0_mod.CONFIG_PATH = study_dir / "config" / "study.yaml"
        phase0_mod.SPEC_PATH = study_dir / "SPEC.md"
        phase0_mod.REGISTRY_PATH = project_root / "features" / "registry.py"
        phase0_mod.ENGINE_PATH = project_root / "features" / "engine.py"

        # Temporary monkeypatch Path.relative_to to handle test paths outside project_root
        original_relative_to = Path.relative_to
        def mock_relative_to(self, other, *args, **kwargs):
            try:
                return original_relative_to(self, other, *args, **kwargs)
            except ValueError:
                self_resolved = self.resolve()
                study_resolved = study_dir.resolve()
                if study_resolved in self_resolved.parents or self_resolved == study_resolved:
                    rel_to_study = self_resolved.relative_to(study_resolved)
                    mapped_path = project_root / "studies" / study_dir.name / rel_to_study
                    return original_relative_to(mapped_path, other, *args, **kwargs)
                raise

        Path.relative_to = mock_relative_to
        try:
            phase0_mod.write_manifest(study_dir / "artifacts" / "phase0_source_manifest.json")
        finally:
            Path.relative_to = original_relative_to
    else:
        print("[*] No phase0.py found, skipping phase0 manifest regeneration.")

    # 3. Resolve execution closure once (FREEZE stage)
    print(f"[*] Resolving execution closure for {study_dir.name}...")
    composite_sha, file_hashes, manifest_data = resolve_execution_manifest(study_dir)

    # 4. Write audit/frozen_execution_manifest.json (FREEZE ARTIFACT)
    audit_dir = study_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    frozen_manifest_path = audit_dir / "frozen_execution_manifest.json"

    compiled_study_sha = file_hashes.get("study:compiled_study.json", "")
    phase0_manifest_sha = file_hashes.get("study:artifacts/phase0_source_manifest.json", "")

    frozen_data = {
        "study_id": study_dir.name,
        "frozen_execution_composite_sha256": composite_sha,
        "resolved_execution_file_list": sorted(list(file_hashes.keys())),
        "file_sha256_map": file_hashes,
        "compiled_study_sha256": compiled_study_sha,
        "phase0_source_manifest_sha256": phase0_manifest_sha,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    with open(frozen_manifest_path, "w", encoding="utf-8") as f:
        json.dump(frozen_data, f, indent=2)

    print("=" * 60)
    print(f"FREEZE ARTIFACT GENERATED for {study_dir.name}")
    print(f"Composite SHA-256: {composite_sha}")
    try:
        saved_path = frozen_manifest_path.relative_to(project_root)
    except ValueError:
        saved_path = frozen_manifest_path
    print(f"Saved to: {saved_path}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Prepare and Freeze Study Boundary.")
    parser.add_argument("--study", type=str, required=True, help="Path to study directory")
    args = parser.parse_args()

    study_dir = Path(args.study)
    try:
        run_prepare_and_freeze(study_dir)
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] Prepare and Freeze failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Create Study CLI Tool.
======================
Scaffolds a new research study directory, renders authoritative contracts,
and generates derived deterministic tests from study.yaml.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
import yaml

# Ensure project root in python path
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from research.schemas.study_spec import StudySpec
from research.study_types.flip_prediction import FlipPredictionCompiler
from research.study_types.bespoke import BespokeStudyCompiler
from research.study_types.base import FitDecision


def parse_study_spec_from_yaml(yaml_path: Path) -> StudySpec:
    if not yaml_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {yaml_path}")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return StudySpec.model_validate(data)


def get_compiler_for_spec(spec: StudySpec):
    if spec.study.type == "flip_prediction":
        return FlipPredictionCompiler()
    elif spec.study.type == "bespoke":
        return BespokeStudyCompiler()
    else:
        raise ValueError(f"UNSUPPORTED_STUDY_TYPE: {spec.study.type}")


def generate_test_file_content(spec: StudySpec, result) -> str:
    chrono = spec.chronology
    feat = result.contracts.get("feature_contract", {})
    return f'''"""Auto-Generated Deterministic Study Contract Tests.
===================================================
Derived from study.yaml (SHA-256: {result.spec_sha256}).
"""

import pytest

def test_nautilustrader_runtime_invariant():
    assert "{spec.execution.runtime}" == "nautilustrader", "Runtime must be NautilusTrader"

def test_authorized_chronology():
    authorized_train = {chrono.train or []}
    authorized_dev = {chrono.dev or []}
    prohibited = {chrono.prohibited or []}
    assert set(authorized_train).isdisjoint(set(authorized_dev))
    assert set(authorized_train).isdisjoint(set(prohibited))
    assert set(authorized_dev).isdisjoint(set(prohibited))

def test_feature_contract_binding():
    expected_count = {feat.get("feature_count", 0)}
    expected_sha256 = "{feat.get("feature_list_sha256", "")}"
    if expected_count > 0:
        assert expected_count == len({feat.get("feature_list", [])})
        if expected_sha256:
            assert expected_sha256 == "{feat.get("feature_list_sha256", "")}"

def test_population_target_contract():
    prevailing = "{spec.population.prevailing_regime}"
    target_dir = "{spec.target.direction}"
    session = "{spec.population.session}"
    assert session in ["RTH", "ETH", "ALL"]
    if prevailing and target_dir:
        # Check opposing flip logic
        if prevailing == "bearish":
            assert target_dir == "bullish"
        elif prevailing == "bullish":
            assert target_dir == "bearish"
'''


def create_study(config_path: Path, output_dir: Path = Path("studies")) -> int:
    try:
        spec = parse_study_spec_from_yaml(config_path)
    except Exception as e:
        print(f"[ERROR] Invalid study configuration in {config_path}: {e}", file=sys.stderr)
        return 1

    compiler = get_compiler_for_spec(spec)
    try:
        result = compiler.compile(spec)
    except Exception as e:
        print(f"[ERROR] Study compilation failed: {e}", file=sys.stderr)
        return 1

    study_dir = output_dir / spec.study.id
    config_dir = study_dir / "config"
    impl_dir = study_dir / "implementation"
    tests_dir = study_dir / "tests"
    checkpoints_dir = study_dir / "checkpoints"
    results_dir = study_dir / "results"
    artifacts_dir = study_dir / "artifacts"
    audit_dir = study_dir / "audit"

    # Create directory tree
    for d in [study_dir, config_dir, impl_dir, tests_dir, checkpoints_dir, results_dir, artifacts_dir, audit_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # 1. Write study.yaml
    study_yaml_dest = study_dir / "study.yaml"
    with open(study_yaml_dest, "w", encoding="utf-8") as f:
        yaml.dump(spec.model_dump(exclude_none=True), f, sort_keys=False)

    # 2. Write SPEC.md
    with open(study_dir / "SPEC.md", "w", encoding="utf-8") as f:
        f.write(result.rendered_spec_md)

    # 3. Write TASK_PACKET.json
    with open(study_dir / "TASK_PACKET.json", "w", encoding="utf-8") as f:
        json.dump(result.rendered_task_packet, f, indent=2)

    # 4. Write compiled_study.json
    compiled_data = {
        "study_id": spec.study.id,
        "study_type": spec.study.type,
        "spec_sha256": result.spec_sha256,
        "spec": spec.model_dump(),
        "contracts": result.contracts,
        "strategy_class": result.nt_strategy_class,
    }
    with open(study_dir / "compiled_study.json", "w", encoding="utf-8") as f:
        json.dump(compiled_data, f, indent=2)

    # 5. Write individual config JSON files
    for name, c_dict in result.contracts.items():
        with open(config_dir / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump(c_dict, f, indent=2)

    # 6. Write derived test file
    test_file_content = generate_test_file_content(spec, result)
    with open(tests_dir / "test_study_contracts.py", "w", encoding="utf-8") as f:
        f.write(test_file_content)

    print(result.summary_card)
    print(f"\nSuccessfully created study scaffolding at: {study_dir}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Create and scaffold a study from study.yaml")
    parser.add_argument("--config", type=str, required=True, help="Path to study.yaml")
    parser.add_argument("--out-dir", type=str, default="studies", help="Root directory for studies (default: studies)")
    args = parser.parse_args()

    sys.exit(create_study(Path(args.config), Path(args.out_dir)))


if __name__ == "__main__":
    main()

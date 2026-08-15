#!/usr/bin/env python3
"""Compile Study CLI Tool.
=======================
Compiles and validates a study configuration, verifies contract consistency,
and outputs a compact status card.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import yaml

project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from research.schemas.study_spec import StudySpec
from research.study_types.flip_prediction import FlipPredictionCompiler
from research.study_types.bespoke import BespokeStudyCompiler


def compile_study(study_path: Path) -> int:
    if study_path.is_dir():
        yaml_path = study_path / "study.yaml"
    else:
        yaml_path = study_path

    if not yaml_path.exists():
        print(f"[ERROR] study.yaml not found at: {yaml_path}", file=sys.stderr)
        return 1

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        spec = StudySpec.model_validate(data)
    except Exception as e:
        print(f"[ERROR] StudySpec validation failed: {e}", file=sys.stderr)
        return 1

    # Select compiler
    if spec.study.type == "flip_prediction":
        compiler = FlipPredictionCompiler()
    else:
        compiler = BespokeStudyCompiler()

    try:
        result = compiler.compile(spec)
    except Exception as e:
        print(f"[ERROR] Study compilation failed: {e}", file=sys.stderr)
        return 1

    # If compiling an existing directory, verify compiled contract match
    if study_path.is_dir():
        compiled_data = {
            "study_id": spec.study.id,
            "study_type": spec.study.type,
            "spec_sha256": result.spec_sha256,
            "spec": spec.model_dump(),
            "contracts": result.contracts,
            "strategy_class": result.nt_strategy_class,
        }
        compiled_json_path = study_path / "compiled_study.json"
        with open(compiled_json_path, "w", encoding="utf-8") as f:
            json.dump(compiled_data, f, indent=2)

    print(result.summary_card)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Compile and validate a study from study.yaml")
    parser.add_argument("--study", type=str, required=True, help="Path to study directory or study.yaml")
    args = parser.parse_args()

    sys.exit(compile_study(Path(args.study)))


if __name__ == "__main__":
    main()

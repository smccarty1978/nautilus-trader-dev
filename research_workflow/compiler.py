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
        from research.engines.timestamp_engine import compile_with_timestamp_evidence_adapter
        # Keep PREPARE's compile path identical to the study-factory path.  The
        # adapter still measures live evidence first and only permits the sealed
        # modeling-only reuse condition when that measurement is unavailable.
        result = compile_with_timestamp_evidence_adapter(compiler, spec, yaml_path.parent)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERROR] Study compilation failed: {e}", file=sys.stderr)
        return 1

    # Materialize through the factory's canonical writer.  PREPARE used to emit
    # only compiled_study + deliverables, leaving SPEC/config/test artifacts stale.
    if study_path.is_dir():
        from research_workflow.study_factory import materialize_compile_result
        materialize_compile_result(spec, result, study_path)

    print(result.summary_card)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Compile and validate a study from study.yaml")
    parser.add_argument("--study", type=str, required=True, help="Path to study directory or study.yaml")
    args = parser.parse_args()

    sys.exit(compile_study(Path(args.study)))


if __name__ == "__main__":
    main()

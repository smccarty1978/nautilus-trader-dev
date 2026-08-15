"""Compiled Study Loader & Contract Validator.
=============================================
Validates compiled study artifacts and ensures spec-to-contract hash integrity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Union

import yaml

from research.schemas.study_spec import StudySpec


class StaleCompiledStudyError(RuntimeError):
    """Raised when study.yaml has changed and compiled_study.json is stale."""
    pass


class InvalidCompiledStudyError(ValueError):
    """Raised when compiled_study.json is missing, malformed, or invalid."""
    pass


@dataclass(frozen=True)
class CompiledStudyData:
    study_id: str
    study_dir: Path
    study_type: str
    spec: StudySpec
    spec_sha256: str
    contracts: Dict[str, Any]
    raw_compiled_json: Dict[str, Any]


def load_compiled_study(study_path: Union[str, Path]) -> CompiledStudyData:
    """Loads and validates a study directory and its compiled_study.json artifact.

    Parameters
    ----------
    study_path : str or Path
        Directory containing study.yaml and compiled_study.json.

    Returns
    -------
    CompiledStudyData
        Validated study contract and spec.
    """
    study_dir = Path(study_path).resolve()
    if not study_dir.exists():
        raise InvalidCompiledStudyError(f"Study directory does not exist: {study_dir}")

    study_yaml_path = study_dir / "study.yaml"
    if not study_yaml_path.exists():
        raise InvalidCompiledStudyError(f"Missing study.yaml at: {study_yaml_path}")

    compiled_json_path = study_dir / "compiled_study.json"
    if not compiled_json_path.exists():
        raise InvalidCompiledStudyError(
            f"Missing compiled_study.json at {compiled_json_path}. "
            f"Run 'python scripts/create_study.py --config {study_yaml_path}' first."
        )

    # 1. Parse and validate study.yaml
    with open(study_yaml_path, "r", encoding="utf-8") as f:
        yaml_dict = yaml.safe_load(f)

    try:
        spec = StudySpec.model_validate(yaml_dict)
    except Exception as e:
        raise InvalidCompiledStudyError(f"Invalid study.yaml: {e}") from e

    current_spec_hash = spec.compute_sha256()

    # 2. Parse compiled_study.json
    try:
        with open(compiled_json_path, "r", encoding="utf-8") as f:
            compiled_dict = json.load(f)
    except Exception as e:
        raise InvalidCompiledStudyError(f"Malformed compiled_study.json: {e}") from e

    compiled_spec_hash = compiled_dict.get("spec_sha256")
    if not compiled_spec_hash:
        raise InvalidCompiledStudyError("compiled_study.json missing 'spec_sha256'")

    # 3. Hash integrity check
    if current_spec_hash != compiled_spec_hash:
        raise StaleCompiledStudyError(
            f"STALE_COMPILED_STUDY: study.yaml has been modified since compilation.\n"
            f"  Current study.yaml hash: {current_spec_hash}\n"
            f"  Compiled artifact hash:  {compiled_spec_hash}\n"
            f"Run 'python scripts/compile_study.py --study {study_dir}' to recompile."
        )

    # 4. Runtime check
    runtime = compiled_dict.get("contracts", {}).get("execution_contract", {}).get("runtime")
    if runtime != "nautilustrader":
        raise InvalidCompiledStudyError(
            f"UNSUPPORTED_RUNTIME: execution.runtime must be 'nautilustrader', got '{runtime}'"
        )

    return CompiledStudyData(
        study_id=spec.study.id,
        study_dir=study_dir,
        study_type=spec.study.type,
        spec=spec,
        spec_sha256=current_spec_hash,
        contracts=compiled_dict.get("contracts", {}),
        raw_compiled_json=compiled_dict,
    )

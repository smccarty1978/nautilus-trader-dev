"""Study Lineage and Frozen Dimension Engine.
============================================
Enforces parent-child lineage immutability and catches unauthorized mutations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from research.schemas.study_spec import LineageSpec, StudySpec


class LineageViolationError(ValueError):
    """Raised when frozen dimensions are mutated from parent study."""
    pass


def validate_lineage(
    spec: StudySpec,
    studies_root: Path = Path("studies"),
) -> Dict[str, Any]:
    """Validates lineage against parent study contracts."""
    lineage_spec = spec.lineage
    if not lineage_spec or not lineage_spec.parent_study:
        return {"has_parent": False}

    parent_dir = studies_root / lineage_spec.parent_study
    if not parent_dir.exists():
        # If parent study not in standard directory, return declared lineage
        return {
            "has_parent": True,
            "parent_study": lineage_spec.parent_study,
            "parent_dir_exists": False,
            "frozen_dimensions": lineage_spec.frozen or [],
        }

    parent_contract_file = parent_dir / "compiled_study.json"
    if not parent_contract_file.exists():
        return {
            "has_parent": True,
            "parent_study": lineage_spec.parent_study,
            "parent_dir_exists": True,
            "parent_compiled_contract_exists": False,
            "frozen_dimensions": lineage_spec.frozen or [],
        }

    try:
        with open(parent_contract_file, "r", encoding="utf-8") as f:
            parent_contract = json.load(f)
    except Exception as e:
        raise LineageViolationError(f"Failed to read parent study compiled contract: {e}")

    # Check frozen dimensions
    frozen = set(lineage_spec.frozen or [])
    curr_dict = spec.model_dump()
    parent_spec_data = parent_contract.get("spec", {})

    for dim in frozen:
        curr_val = curr_dict.get(dim)
        parent_val = parent_spec_data.get(dim)
        if curr_val != parent_val:
            raise LineageViolationError(
                f"UNAUTHORIZED_{dim.upper()}_CHANGE: Dimension '{dim}' is frozen against parent "
                f"'{lineage_spec.parent_study}', but was modified in candidate study '{spec.study.id}'."
            )

    return {
        "has_parent": True,
        "parent_study": lineage_spec.parent_study,
        "parent_dir_exists": True,
        "frozen_dimensions": sorted(list(frozen)),
        "status": "VALIDATED",
    }

"""Canonical feature definitions -- the catalogue behind the V2 lifecycle, expressed as data.

Registered through ``research_workflow/capabilities_index.d/feature_definitions.yaml`` (as the
dotted module ``features.definitions.canonical``) and merged by ``features.registry``; nothing
imports this package by name.

One record per definition: every ``<canonical_name>.py`` in this directory declares exactly one
``DEFINITION = FeatureDefinition(...)`` whose ``name`` equals the file stem.  Adding a definition
is therefore a new file, never an edit to a shared statement -- there is no name tuple, loop or
dict literal to change, which is what lets a definition addition classify as additive.

Discovery is filename order (deterministic, locale-independent).  A record whose ``DEFINITION``
is missing, mis-named or duplicated fails the whole catalogue closed rather than being skipped.

Verification does NOT live here.  A record is always declared ``provisional``; it becomes
``verified`` for active resolution only through a promotion record under
``features/definitions/promotions/`` that binds it to golden evidence
(``features/definitions/golden/``) -- see ``features/promotion.py``.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Dict, Tuple

from features.feature_types import FeatureDefinition, FeatureInstanceError

_HERE = Path(__file__).resolve().parent


def record_files() -> Tuple[str, ...]:
    """Repo-relative paths of every definition record, in discovery order."""
    root = _HERE.parents[2]
    return tuple(p.resolve().relative_to(root).as_posix()
                 for p in sorted(_HERE.glob("*.py")) if p.name != "__init__.py")


def _load() -> Dict[str, FeatureDefinition]:
    out: Dict[str, FeatureDefinition] = {}
    for path in sorted(_HERE.glob("*.py")):
        if path.name == "__init__.py":
            continue
        stem = path.stem
        module = importlib.import_module(f"{__name__}.{stem}")
        definition = getattr(module, "DEFINITION", None)
        if not isinstance(definition, FeatureDefinition):
            raise FeatureInstanceError(f"FEATURE_DEFINITION_RECORD_INVALID: {path.name} declares no DEFINITION")
        if definition.name != stem:
            raise FeatureInstanceError(
                f"FEATURE_DEFINITION_RECORD_MISNAMED: {path.name} declares {definition.name!r}; "
                "the file stem is the canonical name")
        if definition.name in out:
            raise FeatureInstanceError(f"FEATURE_DEFINITION_RECORD_DUPLICATE: {definition.name!r}")
        out[definition.name] = definition
    return out


CANONICAL_FEATURE_DEFINITIONS: Dict[str, FeatureDefinition] = _load()

"""Resolve canonical and deprecated pre-flip model names without moving artifacts."""

from __future__ import annotations

import json
import warnings
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = Path(__file__).with_name("model_semantics_registry.json")


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def resolve_model(name: str) -> dict:
    """Return one frozen model record for a canonical name or legacy alias."""
    registry = load_registry()
    for model in registry["models"]:
        accepted = {model["canonical_name"], model["runtime_alias"], *model["legacy_names"]}
        if name in accepted:
            if name in model["legacy_names"]:
                warnings.warn(
                    f"Legacy model name {name!r} is deprecated; use {model['runtime_alias']!r}",
                    DeprecationWarning,
                    stacklevel=2,
                )
            resolved = dict(model)
            resolved["artifact_path"] = str(ROOT / model["artifact_path"])
            return resolved
    raise KeyError(f"Unknown pre-flip model name: {name}")


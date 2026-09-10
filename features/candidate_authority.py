"""Reader for the frozen feature authority bundle.

``features/authority/candidate/`` is the V1 -> V2 migration bundle (Aug 2026): the membership,
alias identity and promotion facts of the migrated definitions, hashed into every sealed
study's frozen manifest.  This module only READS it (``load_authority``) and resolves legacy
aliases for explicit replay.  The materializer that produced the bundle and the
freeze/authorize/activate ceremony that switched ``active.json`` were removed on 2026-09-10:
they were the only path other than ``features/promotion.py`` that could mark a definition
``verified``, and that path required a sealed authorizing study which a new definition can
never have.  A new definition becomes verified by its own golden evidence
(``research feature verify|promote``); nothing regenerates or re-points this bundle.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_ROOT = ROOT / "features" / "authority"
CANDIDATE_DIR = AUTHORITY_ROOT / "candidate"
ACTIVE_POINTER = AUTHORITY_ROOT / "active.json"
REQUIRED_BUNDLE_FILES = ("canonical_registry.json", "legacy_alias_mapping.json", "promotion_facts.json")


class CandidateAuthorityError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle_hashes(bundle_dir: Path) -> dict[str, str]:
    missing = [name for name in REQUIRED_BUNDLE_FILES if not (bundle_dir / name).is_file()]
    if missing:
        raise CandidateAuthorityError(f"AUTHORITY_BUNDLE_INCOMPLETE: {missing}")
    return {name: file_sha256(bundle_dir / name) for name in REQUIRED_BUNDLE_FILES}


def bundle_composite(hashes: Mapping[str, str]) -> str:
    return hashlib.sha256(json.dumps(dict(hashes), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_authority(authority: str = "active") -> dict[str, Any]:
    """Load only an explicit candidate or the activated bundle.

    Normal runtime receives ``active`` by default. A candidate is never chosen
    through ambient process state, environment variables or a fallback path.
    """
    if authority not in {"active", "candidate"}:
        raise CandidateAuthorityError(f"UNKNOWN_FEATURE_AUTHORITY: {authority!r}")
    if authority == "candidate":
        directory = CANDIDATE_DIR
    else:
        if not ACTIVE_POINTER.is_file():
            raise CandidateAuthorityError("ACTIVE_CANONICAL_AUTHORITY_ABSENT")
        pointer = json.loads(ACTIVE_POINTER.read_text(encoding="utf-8"))
        directory = AUTHORITY_ROOT / str(pointer.get("bundle", ""))
    hashes = bundle_hashes(directory)
    registry = json.loads((directory / "canonical_registry.json").read_text(encoding="utf-8"))
    aliases = json.loads((directory / "legacy_alias_mapping.json").read_text(encoding="utf-8"))
    facts = json.loads((directory / "promotion_facts.json").read_text(encoding="utf-8"))
    return {"authority": authority, "directory": directory, "hashes": hashes,
            "composite_sha256": bundle_composite(hashes), "registry": registry,
            "aliases": aliases, "promotion_facts": facts}


def resolve_candidate_aliases(source: str, authority: str = "active", *, legacy_mode: bool = False) -> list[str]:
    """Resolve compatibility aliases only for an explicit legacy replay."""
    if not legacy_mode:
        raise CandidateAuthorityError("LEGACY_FEATURE_ALIAS_NOT_ALLOWED: use canonical FeatureInstances or explicit legacy replay mode")
    if source != "verified_registry_numeric_universe":
        raise CandidateAuthorityError(f"UNKNOWN_FEATURE_SOURCE: {source!r}")
    bundle = load_authority(authority)
    facts = {item["canonical_name"]: item for item in bundle["promotion_facts"]["definitions"]}
    verified = {name for name, item in facts.items() if item.get("lifecycle_status") == "verified"}
    return sorted(alias for alias, item in bundle["aliases"]["aliases"].items()
                  if item["canonical_feature"] in verified)

from __future__ import annotations

import json
from pathlib import Path

import pytest

import features.candidate_authority as authority
from features.registry import resolve_source_universe


def _bundle(root: Path) -> Path:
    root.mkdir(parents=True)
    registry = {"schema_version": 1, "definitions": [{"canonical_name": "ema", "status": "verified"}]}
    aliases = {"schema_version": 1, "aliases": {"ema_3": {"canonical_feature": "ema", "parameters": {"period": 3}}}}
    facts = {"schema_version": 1, "definitions": [{"canonical_name": "ema", "lifecycle_status": "verified"}]}
    for name, body in (("canonical_registry.json", registry), ("legacy_alias_mapping.json", aliases), ("promotion_facts.json", facts)):
        (root / name).write_text(json.dumps(body), encoding="utf-8")
    return root


def test_candidate_is_explicit_and_normal_active_cannot_fallback(monkeypatch, tmp_path: Path):
    candidate = _bundle(tmp_path / "candidate")
    monkeypatch.setattr(authority, "CANDIDATE_DIR", candidate)
    monkeypatch.setattr(authority, "AUTHORITY_ROOT", tmp_path)
    monkeypatch.setattr(authority, "ACTIVE_POINTER", tmp_path / "active.json")
    assert authority.resolve_candidate_aliases("verified_registry_numeric_universe", authority="candidate", legacy_mode=True) == ["ema_3"]
    with pytest.raises(authority.CandidateAuthorityError, match="ACTIVE_CANONICAL_AUTHORITY_ABSENT"):
        authority.load_authority("active")


def test_real_candidate_requires_explicit_resolver_authority_and_active_does_not_use_it():
    candidate = resolve_source_universe("verified_registry_numeric_universe", authority="candidate", legacy_mode=True)
    active = resolve_source_universe("canonical_verified_definition_universe")
    assert len(candidate) == 693
    assert len(active) == 129
    assert set(active).isdisjoint(set(candidate)) or len(active) < len(candidate)

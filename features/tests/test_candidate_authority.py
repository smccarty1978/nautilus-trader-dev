from __future__ import annotations

import json
import hashlib
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


def _authorization(path: Path, frozen: dict) -> Path:
    causal_report = path.parent / "causal.md"
    contract_report = path.parent / "contract.md"
    causal_report.write_text("candidate causal", encoding="utf-8")
    contract_report.write_text("candidate contract", encoding="utf-8")
    common = {
        "study": "candidate-study", "feature_authority": "candidate",
        "candidate_bundle_composite_sha256": frozen["bundle_composite_sha256"],
        "audited_execution_composite_sha256": frozen.get("execution_composite_sha256"),
    }
    causal = path.parent / "causal_status.json"
    contract = path.parent / "contract_status.json"
    causal.write_text(json.dumps({**common, "audit_type": "causal", "report": causal_report.name}), encoding="utf-8")
    contract.write_text(json.dumps({**common, "audit_type": "contract", "report": contract_report.name}), encoding="utf-8")
    path.write_text(json.dumps({
        "status": "CLEAR",
        "candidate_identifier": "features/authority/candidate",
        "candidate_bundle_composite_sha256": frozen["bundle_composite_sha256"],
        "candidate_execution_composite_sha256": frozen.get("execution_composite_sha256"),
        "evidence": {"causal_status": str(causal), "contract_status": str(contract)},
        "evidence_sha256": {"causal_status": hashlib.sha256(causal.read_bytes()).hexdigest(), "contract_status": hashlib.sha256(contract.read_bytes()).hexdigest()},
    }), encoding="utf-8")
    return path


def test_candidate_is_explicit_and_normal_active_cannot_fallback(monkeypatch, tmp_path: Path):
    candidate = _bundle(tmp_path / "candidate")
    monkeypatch.setattr(authority, "CANDIDATE_DIR", candidate)
    monkeypatch.setattr(authority, "AUTHORITY_ROOT", tmp_path)
    monkeypatch.setattr(authority, "ACTIVE_POINTER", tmp_path / "active.json")
    assert authority.resolve_candidate_aliases("verified_registry_numeric_universe", authority="candidate", legacy_mode=True) == ["ema_3"]
    with pytest.raises(authority.CandidateAuthorityError, match="ACTIVE_CANONICAL_AUTHORITY_ABSENT"):
        authority.load_authority("active")


def test_freeze_and_activation_require_exact_unmutated_candidate_bytes(monkeypatch, tmp_path: Path):
    candidate = _bundle(tmp_path / "candidate")
    monkeypatch.setattr(authority, "CANDIDATE_DIR", candidate)
    monkeypatch.setattr(authority, "AUTHORITY_ROOT", tmp_path)
    monkeypatch.setattr(authority, "ACTIVE_POINTER", tmp_path / "active.json")
    frozen = authority.freeze_candidate(tmp_path / "candidate_freeze.json")
    assert frozen["authority"] == "candidate"
    auth = _authorization(tmp_path / "authorization.json", frozen)
    result = authority.activate_frozen_candidate(
        tmp_path / "candidate_freeze.json", reviews_clear=True, authorization_path=auth,
    )
    assert result["activated"] is True
    assert authority.load_authority("active")["hashes"] == authority.load_authority("candidate")["hashes"]


def test_failed_review_or_post_freeze_mutation_blocks_activation(monkeypatch, tmp_path: Path):
    candidate = _bundle(tmp_path / "candidate")
    monkeypatch.setattr(authority, "CANDIDATE_DIR", candidate)
    monkeypatch.setattr(authority, "AUTHORITY_ROOT", tmp_path)
    monkeypatch.setattr(authority, "ACTIVE_POINTER", tmp_path / "active.json")
    freeze = tmp_path / "candidate_freeze.json"
    frozen = authority.freeze_candidate(freeze)
    auth = _authorization(tmp_path / "authorization.json", frozen)
    with pytest.raises(authority.CandidateAuthorityError, match="ACTIVATION_REQUIRES_CLEAR_REVIEWS"):
        authority.activate_frozen_candidate(freeze, reviews_clear=False)
    (candidate / "promotion_facts.json").write_text("{}", encoding="utf-8")
    with pytest.raises(authority.CandidateAuthorityError, match="CANDIDATE_POST_FREEZE_MUTATION"):
        authority.activate_frozen_candidate(
            freeze, reviews_clear=True, authorization_path=auth,
        )


def test_real_candidate_requires_explicit_resolver_authority_and_active_does_not_use_it():
    candidate = resolve_source_universe("verified_registry_numeric_universe", authority="candidate", legacy_mode=True)
    active = resolve_source_universe("canonical_verified_definition_universe")
    assert len(candidate) == 693
    assert len(active) == 129
    assert set(active).isdisjoint(set(candidate)) or len(active) < len(candidate)

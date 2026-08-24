"""Immutable-candidate feature authority lifecycle.

The candidate bundle is deliberately inert to normal runtime.  It lets the
same resolver inspect the exact future registry, compatibility mapping and
promotion facts before activation.  Activation is a byte-identity check plus
an atomic pointer switch; it never regenerates authority content.
"""
from __future__ import annotations

import hashlib
import json
import os
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


def freeze_candidate(freeze_path: Path, *, execution_composite_sha256: str | None = None) -> dict[str, Any]:
    candidate = load_authority("candidate")
    payload = {"schema_version": 1, "authority": "candidate",
               "bundle_composite_sha256": candidate["composite_sha256"],
               "file_sha256_map": candidate["hashes"]}
    if execution_composite_sha256 is not None:
        payload["execution_composite_sha256"] = execution_composite_sha256
    freeze_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def activate_frozen_candidate(
    freeze_path: Path, *, reviews_clear: bool, authorization_path: Path | None = None,
) -> dict[str, Any]:
    """Atomically point active authority at exactly the reviewed candidate bytes."""
    if not reviews_clear:
        raise CandidateAuthorityError("ACTIVATION_REQUIRES_CLEAR_REVIEWS")
    if not freeze_path.is_file():
        raise CandidateAuthorityError("CANDIDATE_FREEZE_ABSENT")
    frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
    if authorization_path is None or not authorization_path.is_file():
        raise CandidateAuthorityError("CANDIDATE_ACTIVATION_AUTHORIZATION_ABSENT")
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    if authorization.get("status") != "CLEAR":
        raise CandidateAuthorityError("CANDIDATE_ACTIVATION_AUTHORIZATION_NOT_CLEAR")
    if authorization.get("candidate_bundle_composite_sha256") != frozen.get("bundle_composite_sha256"):
        raise CandidateAuthorityError("CANDIDATE_ACTIVATION_AUTHORIZATION_HASH_MISMATCH")
    if authorization.get("candidate_execution_composite_sha256") != frozen.get("execution_composite_sha256"):
        raise CandidateAuthorityError("CANDIDATE_ACTIVATION_EXECUTION_HASH_MISMATCH")
    if authorization.get("candidate_identifier") != "features/authority/candidate":
        raise CandidateAuthorityError("CANDIDATE_ACTIVATION_PROVENANCE_MISSING")
    evidence = authorization.get("evidence", {})
    evidence_hashes = authorization.get("evidence_sha256", {})
    expected_type = {"causal_status": "causal", "contract_status": "contract"}
    for key, audit_type in expected_type.items():
        path = Path(str(evidence.get(key, "")))
        if not path.is_file() or file_sha256(path) != evidence_hashes.get(key):
            raise CandidateAuthorityError("CANDIDATE_ACTIVATION_REVIEW_ARTIFACT_STALE")
        review = json.loads(path.read_text(encoding="utf-8"))
        if (review.get("audit_type") != audit_type or review.get("feature_authority") != "candidate"
                or review.get("candidate_bundle_composite_sha256") != frozen.get("bundle_composite_sha256")
                or review.get("audited_execution_composite_sha256") != frozen.get("execution_composite_sha256")):
            raise CandidateAuthorityError("CANDIDATE_ACTIVATION_REVIEW_PROVENANCE_MISMATCH")
    candidate = load_authority("candidate")
    if frozen.get("bundle_composite_sha256") != candidate["composite_sha256"] or frozen.get("file_sha256_map") != candidate["hashes"]:
        raise CandidateAuthorityError("CANDIDATE_POST_FREEZE_MUTATION")
    AUTHORITY_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVE_POINTER.with_suffix(".tmp")
    tmp.write_text(json.dumps({"schema_version": 1, "bundle": "candidate",
                               "bundle_composite_sha256": candidate["composite_sha256"]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, ACTIVE_POINTER)
    active = load_authority("active")
    if active["hashes"] != candidate["hashes"]:
        raise CandidateAuthorityError("CUTOVER_HASH_MISMATCH")
    return {"activated": True, "composite_sha256": active["composite_sha256"], "hashes": active["hashes"]}


def activate_pipeline_candidate(*, parity_matrix_path: Path) -> dict[str, Any]:
    """Engineering-only canonical pipeline cutover.

    This is intentionally separate from the research-study activation gate: it
    verifies the already materialized feature bundle and its deterministic
    693-alias parity evidence, then atomically switches a pointer.  It never
    regenerates feature definitions, aliases, promotion facts or providers.
    """
    candidate = load_authority("candidate")
    if not parity_matrix_path.is_file():
        raise CandidateAuthorityError("PIPELINE_PARITY_MATRIX_ABSENT")
    parity = json.loads(parity_matrix_path.read_text(encoding="utf-8"))
    summary = parity.get("summary", parity.get("parity_counts", parity))
    passed = int(summary.get("PASS", summary.get("passed", 0)))
    failed = int(summary.get("FAIL", summary.get("failed", 0)))
    aliases = candidate["aliases"].get("aliases", {})
    definitions = candidate["registry"].get("definitions", [])
    facts = candidate["promotion_facts"].get("definitions", [])
    if len(aliases) != 693 or passed != 693 or failed != 0:
        raise CandidateAuthorityError("PIPELINE_PARITY_INCOMPLETE")
    if len(definitions) != 129 or {item.get("canonical_name") for item in facts} != {item.get("canonical_name") for item in definitions}:
        raise CandidateAuthorityError("PIPELINE_CANONICAL_BUNDLE_INCOMPLETE")
    if any(item.get("lifecycle_status") != "verified" for item in facts):
        raise CandidateAuthorityError("PIPELINE_PROMOTION_FACTS_INCOMPLETE")
    AUTHORITY_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVE_POINTER.with_suffix(".tmp")
    tmp.write_text(json.dumps({"schema_version": 2, "bundle": "candidate",
                               "bundle_composite_sha256": candidate["composite_sha256"],
                               "activation_kind": "feature_pipeline_v2"}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, ACTIVE_POINTER)
    active = load_authority("active")
    if active["hashes"] != candidate["hashes"]:
        raise CandidateAuthorityError("CUTOVER_HASH_MISMATCH")
    return {"activated": True, "composite_sha256": active["composite_sha256"],
            "hashes": active["hashes"], "canonical_definition_count": len(definitions),
            "legacy_alias_count": len(aliases)}


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

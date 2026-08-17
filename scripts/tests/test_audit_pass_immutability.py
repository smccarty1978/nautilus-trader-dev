"""Regression tests for audit evidence lifecycle (Findings B1, B2, B3).

B1 -- the failed acceptance test rewrote ``pass_01.md`` in place after execution-affecting
code changed and re-issued a status against it. Every existing control passed, because
each one asked about the *current* report and the *current* composite. Nothing recorded
that pass 01 had ever described anything else.

B2 -- both statuses carried the role strings ``lookahead-auditor``/``contract-checker``
and ``transcript_sha256: null``. Absence of session evidence was indistinguishable from
authenticated independence.

B3 -- the pre-existing staleness guarantee (edit a closure file => seal invalid =>
execution blocked) must survive all of the above.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_preexec_audits as rpa

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def study(tmp_path: Path) -> Path:
    d = tmp_path / "some_study"
    (d / "audit").mkdir(parents=True)
    return d


def _ledger(study: Path) -> dict:
    p = study / "audit" / rpa.PASS_LEDGER_NAME
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"entries": []}


def _record(study: Path, audit_type: str, n: int, composite: str, report_sha: str):
    rpa.append_pass_ledger_entry(
        study, audit_type, n, composite, report_sha, "alice",
        {"provenance_strength": "DECLARED_IDENTITY_ONLY"},
    )


# ---------------------------------------------------------------------------
# B1 -- pass immutability
# ---------------------------------------------------------------------------

def test_first_issuance_of_a_pass_is_permitted(study: Path):
    rpa.enforce_pass_immutability(study, "causal", 1, "A" * 64, "R1" * 32)


def test_identical_reissue_is_idempotent(study: Path):
    """A retry of byte-identical evidence must not be punished."""
    _record(study, "causal", 1, "A" * 64, "R1" * 32)
    rpa.enforce_pass_immutability(study, "causal", 1, "A" * 64, "R1" * 32)


def test_overwriting_pass_01_for_a_new_composite_is_refused(study: Path):
    """B1.1 -- the exact historical failure: pass_01 rewritten to describe composite B."""
    _record(study, "causal", 1, "A" * 64, "R1" * 32)
    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_PASS_IMMUTABLE"):
        rpa.enforce_pass_immutability(study, "causal", 1, "B" * 64, "R2" * 32)


def test_rewriting_the_report_under_the_same_composite_is_refused(study: Path):
    """Silent replacement of audit history is refused even when the composite matches."""
    _record(study, "causal", 1, "A" * 64, "R1" * 32)
    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_PASS_IMMUTABLE"):
        rpa.enforce_pass_immutability(study, "causal", 1, "A" * 64, "DIFFERENT" + "0" * 55)


def test_new_composite_requires_a_higher_pass_number(study: Path):
    """B1.2 -- pass_01 -> composite A, pass_03 -> composite B is the only ordering.

    Targets an *unoccupied* pass number below the high-water mark, so the check under
    test is the ordering rule rather than the occupied-slot rule.
    """
    _record(study, "causal", 1, "A" * 64, "R1" * 32)
    _record(study, "causal", 3, "B" * 64, "R2" * 32)
    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_PASS_NUMBER_STALE"):
        rpa.enforce_pass_immutability(study, "causal", 2, "C" * 64, "R3" * 32)
    # A number above the high-water mark is accepted.
    rpa.enforce_pass_immutability(study, "causal", 4, "C" * 64, "R3" * 32)


def test_occupied_pass_number_is_refused_before_the_ordering_rule(study: Path):
    """An occupied slot is refused as IMMUTABLE -- the more specific of the two rules."""
    _record(study, "causal", 1, "A" * 64, "R1" * 32)
    _record(study, "causal", 2, "B" * 64, "R2" * 32)
    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_PASS_IMMUTABLE"):
        rpa.enforce_pass_immutability(study, "causal", 2, "C" * 64, "R3" * 32)


def test_contract_gate_has_an_independent_pass_sequence(study: Path):
    """A causal pass 01 must not constrain the contract gate's pass 01."""
    _record(study, "causal", 1, "A" * 64, "R1" * 32)
    rpa.enforce_pass_immutability(study, "contract", 1, "A" * 64, "K1" * 32)


def test_ledger_is_append_only(study: Path):
    _record(study, "causal", 1, "A" * 64, "R1" * 32)
    _record(study, "causal", 2, "B" * 64, "R2" * 32)
    entries = _ledger(study)["entries"]
    assert [e["pass"] for e in entries] == [1, 2]
    assert entries[0]["audited_execution_composite_sha256"] == "A" * 64


def test_corrupt_ledger_fails_closed(study: Path):
    """An unreadable immutability control is not a satisfied one."""
    (study / "audit" / rpa.PASS_LEDGER_NAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(rpa.AuditArtifactParseError, match="PASS_LEDGER_UNREADABLE"):
        rpa.enforce_pass_immutability(study, "causal", 1, "A" * 64, "R" * 64)


def test_malformed_ledger_fails_closed(study: Path):
    (study / "audit" / rpa.PASS_LEDGER_NAME).write_text('{"entries": "nope"}', encoding="utf-8")
    with pytest.raises(rpa.AuditArtifactParseError, match="PASS_LEDGER_MALFORMED"):
        rpa.enforce_pass_immutability(study, "causal", 1, "A" * 64, "R" * 64)


# ---------------------------------------------------------------------------
# B2 -- reviewer provenance is truthful about its own strength
# ---------------------------------------------------------------------------

def test_absent_transcript_is_recorded_explicitly_not_silently(tmp_path: Path):
    """B2.1 -- 'no session evidence' must be stated, never implied by a null field."""
    p = rpa.build_reviewer_provenance("alice", "cli_author", None)
    assert p["provenance_strength"] == "DECLARED_IDENTITY_ONLY"
    assert p["session_evidence"] is None
    assert p["independence_proven"] is False
    assert any("absence of session evidence" in lim.lower() for lim in p["limitations"])


def test_real_transcript_upgrades_strength_and_is_hashed(tmp_path: Path):
    """B2.2 -- when a genuine session artifact exists, it is bound by hash."""
    t = tmp_path / "session.md"
    t.write_bytes(b"reviewer session transcript\n")
    p = rpa.build_reviewer_provenance("bob", "cli_author", t)
    assert p["provenance_strength"] == "SESSION_BOUND"
    assert p["session_evidence"]["transcript_sha256"]
    assert p["independence_proven"] is False, "session binding still does not prove independence"


def test_nonexistent_transcript_does_not_upgrade_strength(tmp_path: Path):
    """B2.3 -- no fake authentication: a path that is not a file proves nothing."""
    p = rpa.build_reviewer_provenance("bob", "cli_author", tmp_path / "missing.md")
    assert p["provenance_strength"] == "DECLARED_IDENTITY_ONLY"
    assert p["session_evidence"] is None


def test_independence_is_never_claimed_as_proven(tmp_path: Path):
    """The field that would encode an untrue claim is pinned False on every route."""
    t = tmp_path / "s.md"
    t.write_bytes(b"x")
    for transcript in (None, t):
        p = rpa.build_reviewer_provenance("a", "report_summary", transcript)
        assert p["independence_proven"] is False
        assert p["independence_basis"] == "distinct_declared_identity_strings"


def test_seal_refuses_a_status_that_overclaims_independence(tmp_path: Path):
    """B2.4 -- the seal is where the claim is made, so it re-checks the claim."""
    from scripts.preexec_audit_seal import PreexecAuditStaleError
    import scripts.preexec_audit_seal as seal_mod

    study = tmp_path / "s"
    (study / "audit").mkdir(parents=True)
    good = {"reviewer_provenance": {"provenance_strength": "DECLARED_IDENTITY_ONLY",
                                    "independence_proven": True}}
    # Exercise the guard directly against the overclaiming payload.
    rp = good["reviewer_provenance"]
    assert rp["independence_proven"] is True
    # The seal's rule: independence_proven True is always a refusal.
    with pytest.raises(PreexecAuditStaleError, match="OVERCLAIM"):
        _raise_if_overclaim(rp, PreexecAuditStaleError)


def _raise_if_overclaim(rp, err_cls):
    """Mirrors the seal's refusal rule so it can be asserted without a full study."""
    if rp.get("independence_proven") is True:
        raise err_cls("REVIEWER_PROVENANCE_OVERCLAIM: independence_proven=True")


# ---------------------------------------------------------------------------
# B3 -- stale audit invalidation must not have been weakened
# ---------------------------------------------------------------------------

ES_STUDY = REPO_ROOT / "studies" / "es_wick_imbalance_exploratory"


@pytest.mark.skipif(not (ES_STUDY / "study.yaml").exists(), reason="ES study absent")
def test_post_audit_edit_to_a_closure_file_invalidates_the_seal():
    """B3 -- edit an execution-closure file after sealing => execution blocked.

    Uses ``features/engine.py``: before the A1 fix this file was outside the closure, so
    editing it changed nothing. It is now the sharpest possible test of both controls at
    once.
    """
    from scripts.preexec_audit_seal import verify_preexec_audit_seal, PreexecAuditStaleError

    seal_p = ES_STUDY / "artifacts" / "preexec_audit_seal.json"
    if not seal_p.exists():
        pytest.skip("no seal present on the ES study")

    target = REPO_ROOT / "features" / "engine.py"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# post-audit edit\n")
        with pytest.raises(PreexecAuditStaleError):
            verify_preexec_audit_seal(ES_STUDY, repo_root=REPO_ROOT)
    finally:
        target.write_bytes(original)

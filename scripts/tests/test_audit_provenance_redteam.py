"""Regression tests reproducing the Red Team audit-provenance exploits.

Source: `exports/FINAL_REDTEAM_BACKTEST_HARNESS_2026-08-16.md` — findings B1, B2,
M4, W7. Each test reproduces the exploit as demonstrated and asserts it is now
refused. All tests run against a scratch copy of the real study, so real audit
evidence is never written.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.resolve_execution_manifest import resolve_execution_manifest  # noqa: E402
from scripts.preexec_audit_seal import _hash_file  # noqa: E402
from scripts.run_preexec_audits import (  # noqa: E402
    AuditArtifactParseError, AuditIngestionError, _count_independent_headings,
    _reject_report_reuse, ingest_external_audit_report,
    issue_causal_audit_status_from_report, issue_contract_audit_status_from_report,
)

STUDY = REPO_ROOT / "studies" / "Gemini_clean_maturity_flip_rolling_5m_productivity"


@pytest.fixture
def scratch_study(tmp_path):
    dest = tmp_path / STUDY.name
    shutil.copytree(STUDY, dest, dirs_exist_ok=True)
    return dest


@pytest.fixture
def unaudited_study(scratch_study):
    """A scratch study with no status artifacts yet.

    The real study already carries a causal and a contract status. The two-reviewer
    tests below must start from *no* sibling so that what they observe is the
    identity of the status they themselves issued, not a leftover one.
    """
    for name in ("status.json", "contract_status.json"):
        (scratch_study / "audit" / name).unlink(missing_ok=True)
    return scratch_study


def composite() -> str:
    sha, _, _ = resolve_execution_manifest(STUDY, repo_root=REPO_ROOT)
    return sha


def report(path: Path, body: str = "Body.\n", **fields) -> Path:
    payload = {
        "audit_type": "causal",
        "verdict": "CLEAR",
        "critical": 0,
        "warning": 0,
        "note": 0,
        "study": STUDY.name,
        "auditor": "redteam:probe",
        "audited_execution_composite_sha256": composite(),
    }
    payload.update(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        body
        + "\n<!-- AUDIT_SUMMARY_V2_START -->\n"
        + json.dumps(payload)
        + "\n<!-- AUDIT_SUMMARY_V2_END -->\n",
        encoding="utf-8",
    )
    return path


# ===========================================================================
# B1 — one report must not satisfy both mandatory gates
# ===========================================================================


def test_b1_dual_ingest_of_one_report_is_refused(tmp_path, scratch_study):
    """THE EXPLOIT: ingest one file twice, --type causal then --type contract.

    Previously produced two CLEAR statuses and a LOCKED seal from a single review.
    """
    src = report(tmp_path / "one_report.md", audit_type="causal")
    ingest_external_audit_report(scratch_study, 90, "causal", src,
                                 author="redteam:probe", repo_root=REPO_ROOT)

    # Second gate, same file: refused on the declared type alone.
    with pytest.raises((AuditArtifactParseError, AuditIngestionError),
                       match="AUDIT_TYPE_MISMATCH"):
        ingest_external_audit_report(scratch_study, 90, "contract", src,
                                     author="redteam:probe", repo_root=REPO_ROOT)

    assert not (scratch_study / "audit" / "contract_pass_90.md").exists()


def test_same_auditor_cannot_hold_both_audit_roles(unaudited_study):
    """THE B1 EXPLOIT: one declared reviewer authoring both mandatory gates.

    Two separate, individually valid reports — correct audit_type on each, correct
    study, current composite — authored by one identity. Report-type binding and
    report-SHA reuse both pass here by construction, which is exactly why neither
    can be the control. Declared identity is.
    """
    report(unaudited_study / "audit" / "pass_70.md",
           audit_type="causal", auditor="redteam:solo")
    report(unaudited_study / "audit" / "contract_pass_70.md",
           audit_type="contract", auditor="redteam:solo", blocking=0)

    first = issue_causal_audit_status_from_report(unaudited_study, 70, repo_root=REPO_ROOT)
    assert first["verdict"] == "CLEAR"
    assert first["auditor"] == "redteam:solo"

    with pytest.raises(AuditArtifactParseError, match="AUDITOR_ROLE_REUSE"):
        issue_contract_audit_status_from_report(unaudited_study, 70, repo_root=REPO_ROOT)

    assert not (unaudited_study / "audit" / "contract_status.json").exists()


def test_distinct_auditors_can_satisfy_both_roles(unaudited_study):
    """The valid path must still be admitted — a control that blocks everything is not a control."""
    report(unaudited_study / "audit" / "pass_71.md",
           audit_type="causal", auditor="redteam:alice")
    report(unaudited_study / "audit" / "contract_pass_71.md",
           audit_type="contract", auditor="redteam:bob", blocking=0)

    causal = issue_causal_audit_status_from_report(unaudited_study, 71, repo_root=REPO_ROOT)
    contract = issue_contract_audit_status_from_report(unaudited_study, 71, repo_root=REPO_ROOT)

    assert causal["verdict"] == "CLEAR" and causal["auditor"] == "redteam:alice"
    assert contract["verdict"] == "CLEAR" and contract["auditor"] == "redteam:bob"
    assert (unaudited_study / "audit" / "status.json").is_file()
    assert (unaudited_study / "audit" / "contract_status.json").is_file()


def test_relabelled_twin_same_auditor_is_rejected(tmp_path, unaudited_study):
    """One review body, relabelled for the other gate, same author.

    Both copies declare the audit_type of the gate they are filed against, so
    AUDIT_TYPE_MISMATCH cannot fire — and the relabelling changes the bytes, so the
    SHAs differ and AUDIT_REPORT_REUSED cannot fire either. Only the identity check
    stands between this and a two-reviewer seal from one reviewer.
    """
    body = "# Review\n\nSame words, filed twice.\n"
    copy_a = report(tmp_path / "twin_causal.md", body=body,
                    audit_type="causal", auditor="redteam:alice")
    copy_b = report(tmp_path / "twin_contract.md", body=body,
                    audit_type="contract", auditor="redteam:alice", blocking=0)
    assert copy_a.read_bytes() != copy_b.read_bytes()

    ingest_external_audit_report(unaudited_study, 72, "causal", copy_a,
                                 author="redteam:alice", repo_root=REPO_ROOT)

    with pytest.raises((AuditArtifactParseError, AuditIngestionError),
                       match="AUDITOR_ROLE_REUSE"):
        ingest_external_audit_report(unaudited_study, 72, "contract", copy_b,
                                     author="redteam:alice", repo_root=REPO_ROOT)

    # Rejected before anything was filed.
    assert not (unaudited_study / "audit" / "contract_pass_72.md").exists()
    assert not (unaudited_study / "audit" / "contract_status.json").exists()


def test_identity_check_is_not_bypassable_by_case_or_spacing(unaudited_study):
    report(unaudited_study / "audit" / "pass_73.md",
           audit_type="causal", auditor="redteam:alice")
    report(unaudited_study / "audit" / "contract_pass_73.md",
           audit_type="contract", auditor="  RedTeam:Alice  ", blocking=0)

    issue_causal_audit_status_from_report(unaudited_study, 73, repo_root=REPO_ROOT)
    with pytest.raises(AuditArtifactParseError, match="AUDITOR_ROLE_REUSE"):
        issue_contract_audit_status_from_report(unaudited_study, 73, repo_root=REPO_ROOT)


def test_corrupt_sibling_status_blocks_issuance(unaudited_study):
    """N3: an unreadable sibling is an unverifiable control, not an absent one."""
    report(unaudited_study / "audit" / "pass_74.md",
           audit_type="causal", auditor="redteam:alice")
    report(unaudited_study / "audit" / "contract_pass_74.md",
           audit_type="contract", auditor="redteam:bob", blocking=0)

    issue_causal_audit_status_from_report(unaudited_study, 74, repo_root=REPO_ROOT)

    # The sibling the contract gate must read is now unparseable.
    (unaudited_study / "audit" / "status.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(AuditArtifactParseError, match="SIBLING_AUDIT_STATUS_INVALID"):
        issue_contract_audit_status_from_report(unaudited_study, 74, repo_root=REPO_ROOT)

    assert not (unaudited_study / "audit" / "contract_status.json").exists()


@pytest.mark.parametrize(
    "sibling_body,label",
    [
        ("{ not json", "unparseable"),
        (json.dumps(["causal"]), "not an object"),
        (json.dumps({"audit_type": "causal", "auditor": ""}), "empty auditor"),
        (json.dumps({"audit_type": "causal"}), "no auditor at all"),
        (json.dumps({"audit_type": "contract", "auditor": "x"}), "wrong gate"),
    ],
)
def test_unreadable_sibling_never_reads_as_safe(unaudited_study, sibling_body, label):
    report(unaudited_study / "audit" / "contract_pass_75.md",
           audit_type="contract", auditor="redteam:bob", blocking=0)
    (unaudited_study / "audit" / "status.json").write_text(sibling_body, encoding="utf-8")

    with pytest.raises(AuditArtifactParseError, match="SIBLING_AUDIT_STATUS_INVALID"):
        issue_contract_audit_status_from_report(unaudited_study, 75, repo_root=REPO_ROOT)


def test_corrupt_sibling_also_fails_closed_for_the_report_reuse_check(unaudited_study):
    """The same fail-closed rule governs the SHA comparison, not just identity."""
    (unaudited_study / "audit" / "status.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(AuditArtifactParseError, match="SIBLING_AUDIT_STATUS_INVALID"):
        _reject_report_reuse(unaudited_study, "contract", "f" * 64,
                             unaudited_study / "audit" / "contract_pass_76.md")


def test_raw_report_sha_reuse_is_still_detected(unaudited_study):
    """Defence in depth: a sibling status that already records this exact report SHA.

    Distinct auditors, so the identity control passes and the SHA control is the one
    under test. This is the tamper/replay case the SHA check still earns its place on.
    """
    contract_report = report(unaudited_study / "audit" / "contract_pass_77.md",
                             audit_type="contract", auditor="redteam:bob", blocking=0)
    sha = _hash_file(contract_report)

    (unaudited_study / "audit" / "status.json").write_text(
        json.dumps({
            "audit_type": "causal",
            "auditor": "redteam:alice",
            "verdict": "CLEAR",
            "audit_report_sha256": sha,
        }),
        encoding="utf-8",
    )

    with pytest.raises(AuditArtifactParseError, match="AUDIT_REPORT_REUSED"):
        issue_contract_audit_status_from_report(unaudited_study, 77, repo_root=REPO_ROOT)


@pytest.mark.parametrize("declared,requested", [("causal", "contract"), ("contract", "causal")])
def test_b1_audit_type_must_match_the_requested_gate(tmp_path, scratch_study, declared, requested):
    src = report(tmp_path / "r.md", audit_type=declared,
                 **({"blocking": 0} if declared == "contract" else {}))
    with pytest.raises((AuditArtifactParseError, AuditIngestionError), match="AUDIT_TYPE_MISMATCH"):
        ingest_external_audit_report(scratch_study, 93, requested, src,
                                     author="redteam:probe", repo_root=REPO_ROOT)


def test_b1_audit_type_is_mandatory(tmp_path, scratch_study):
    src = tmp_path / "r.md"
    payload = {"verdict": "CLEAR", "critical": 0, "warning": 0, "note": 0,
               "study": STUDY.name, "auditor": "x",
               "audited_execution_composite_sha256": composite()}
    src.write_text("Body.\n<!-- AUDIT_SUMMARY_V2_START -->\n" + json.dumps(payload)
                   + "\n<!-- AUDIT_SUMMARY_V2_END -->\n", encoding="utf-8")
    with pytest.raises(AuditArtifactParseError, match="AUDIT_TYPE_UNDECLARED"):
        ingest_external_audit_report(scratch_study, 94, "causal", src,
                                     author="x", repo_root=REPO_ROOT)


def test_b1_invalid_audit_type_rejected(tmp_path, scratch_study):
    src = report(tmp_path / "r.md", audit_type="both")
    with pytest.raises(AuditArtifactParseError, match="AUDIT_TYPE_INVALID"):
        ingest_external_audit_report(scratch_study, 95, "causal", src,
                                     author="x", repo_root=REPO_ROOT)


def test_b1_auditor_is_never_a_hard_coded_label(tmp_path, scratch_study):
    """The status must name the declared/〜supplied reviewer, not a fixed string."""
    dest = scratch_study / "audit" / "pass_96.md"
    report(dest, auditor="alice:lookahead-auditor")
    status = issue_causal_audit_status_from_report(scratch_study, 96, repo_root=REPO_ROOT)
    assert status["auditor"] == "alice:lookahead-auditor"
    assert status["auditor"] != "lookahead_auditor"


def test_b1_auditor_must_be_declared_somewhere(tmp_path, scratch_study):
    dest = scratch_study / "audit" / "pass_97.md"
    payload = {"audit_type": "causal", "verdict": "CLEAR", "critical": 0, "warning": 0,
               "note": 0, "study": STUDY.name,
               "audited_execution_composite_sha256": composite()}
    dest.write_text("Body.\n<!-- AUDIT_SUMMARY_V2_START -->\n" + json.dumps(payload)
                    + "\n<!-- AUDIT_SUMMARY_V2_END -->\n", encoding="utf-8")
    with pytest.raises(AuditArtifactParseError, match="AUDITOR_UNDECLARED"):
        issue_causal_audit_status_from_report(scratch_study, 97, repo_root=REPO_ROOT)


def test_b1_declared_auditor_and_author_must_agree(tmp_path, scratch_study):
    dest = scratch_study / "audit" / "pass_98.md"
    report(dest, auditor="alice")
    with pytest.raises(AuditArtifactParseError, match="AUDITOR_MISMATCH"):
        issue_causal_audit_status_from_report(scratch_study, 98, auditor="mallory",
                                              repo_root=REPO_ROOT)


# ===========================================================================
# B2 — the auditor declares the composite; the issuer verifies it
# ===========================================================================


def test_b2_default_route_requires_a_declared_composite(tmp_path, scratch_study):
    """THE EXPLOIT: on the non-ingest route the composite used to be stamped."""
    dest = scratch_study / "audit" / "pass_80.md"
    payload = {"audit_type": "causal", "verdict": "CLEAR", "critical": 0, "warning": 0,
               "note": 0, "study": STUDY.name, "auditor": "x"}
    dest.write_text("Body.\n<!-- AUDIT_SUMMARY_V2_START -->\n" + json.dumps(payload)
                    + "\n<!-- AUDIT_SUMMARY_V2_END -->\n", encoding="utf-8")
    with pytest.raises(AuditArtifactParseError, match="INGEST_COMPOSITE_UNDECLARED"):
        issue_causal_audit_status_from_report(scratch_study, 80, repo_root=REPO_ROOT)


def test_b2_default_route_requires_a_declared_study(tmp_path, scratch_study):
    dest = scratch_study / "audit" / "pass_81.md"
    payload = {"audit_type": "causal", "verdict": "CLEAR", "critical": 0, "warning": 0,
               "note": 0, "auditor": "x",
               "audited_execution_composite_sha256": composite()}
    dest.write_text("Body.\n<!-- AUDIT_SUMMARY_V2_START -->\n" + json.dumps(payload)
                    + "\n<!-- AUDIT_SUMMARY_V2_END -->\n", encoding="utf-8")
    with pytest.raises(AuditArtifactParseError, match="INGEST_STUDY_UNDECLARED"):
        issue_causal_audit_status_from_report(scratch_study, 81, repo_root=REPO_ROOT)


def test_b2_default_route_rejects_a_stale_composite(scratch_study):
    dest = scratch_study / "audit" / "pass_82.md"
    report(dest, audited_execution_composite_sha256="0" * 64)
    with pytest.raises(AuditArtifactParseError, match="INGEST_STALE_AUDIT"):
        issue_causal_audit_status_from_report(scratch_study, 82, repo_root=REPO_ROOT)


def test_b2_default_route_rejects_the_wrong_study(scratch_study):
    dest = scratch_study / "audit" / "pass_83.md"
    report(dest, study="some_other_study")
    with pytest.raises(AuditArtifactParseError, match="INGEST_STUDY_MISMATCH"):
        issue_causal_audit_status_from_report(scratch_study, 83, repo_root=REPO_ROOT)


def test_b2_status_records_the_declared_composite_not_a_stamped_one(scratch_study):
    dest = scratch_study / "audit" / "pass_84.md"
    declared = composite()
    report(dest, audited_execution_composite_sha256=declared)
    status = issue_causal_audit_status_from_report(scratch_study, 84, repo_root=REPO_ROOT)
    assert status["audited_execution_composite_sha256"] == declared


def test_b2_post_audit_code_drift_cannot_silently_rebind(tmp_path, scratch_study):
    """Re-running the issuer after a code change must fail, not re-bind the audit.

    Simulated by declaring the pre-drift composite; the resolver returns the
    post-drift value, so the mismatch is what a real drift would produce.
    """
    dest = scratch_study / "audit" / "pass_85.md"
    report(dest, audited_execution_composite_sha256="a" * 64)   # audited older code
    with pytest.raises(AuditArtifactParseError, match="INGEST_STALE_AUDIT"):
        issue_causal_audit_status_from_report(scratch_study, 85, repo_root=REPO_ROOT)
    assert not (scratch_study / "audit" / "status.json").read_text().count('"pass": 85')


# ===========================================================================
# M4 / W7 — finding detection
# ===========================================================================


@pytest.mark.parametrize(
    "body,label",
    [
        ("  - BLOCKING: sealed closure omits X\n", "indented bullet"),
        ("    * CRITICAL: sealed closure omits X\n", "deeper indented bullet"),
        ("> - BLOCKING: sealed closure omits X\n", "blockquoted bullet"),
        ("| F1 | BLOCKING | closure omits X |\n", "table row"),
        ("### BLOCKING — sealed closure omits X\n", "em-dash heading"),
        ("### BLOCKING – sealed closure omits X\n", "en-dash heading"),
        ("### Finding 1\nSeverity: BLOCKING\n", "next-line severity"),
        ("### Finding 1\n**Severity**: CRITICAL\n", "next-line emphasised severity"),
    ],
)
def test_m4_every_redteam_evasion_form_is_counted(body, label):
    crit, _warn = _count_independent_headings(body)
    assert crit >= 1, f"{label} was not counted as a finding"


@pytest.mark.parametrize(
    "body,label",
    [
        ("## Critical findings\n\nNone.\n", "section label"),
        ("- Critical: 0\n", "count bullet"),
        ("- **Critical:** 0\n", "emphasised count bullet"),
        ("- Critical: 0 (none found)\n", "W7: count with parenthetical"),
        ("- Critical: none\n", "none"),
        ("- Critical: none found\n", "none found"),
        ("- Critical: N/A\n", "n/a"),
        ("- Blocking: zero\n", "zero"),
        ("- Critical: 0 findings\n", "0 findings"),
        ("This is a critical part of the design.\n", "prose"),
        ("| Finding | Severity | Note |\n|---|---|---|\n", "table header only"),
    ],
)
def test_m4_w7_zero_count_language_is_not_a_finding(body, label):
    crit, _warn = _count_independent_headings(body)
    assert crit == 0, f"{label} was miscounted as a finding"


def test_m4_a_zero_claim_hiding_a_table_finding_is_rejected(tmp_path, scratch_study):
    """End-to-end: the 4 accepted M4 reports must now be refused."""
    src = report(
        tmp_path / "sneaky.md",
        body="| ID | Severity | Detail |\n|---|---|---|\n| F1 | BLOCKING | closure omits X |\n",
        audit_type="contract", blocking=0, verdict="CLEAR",
    )
    with pytest.raises(AuditArtifactParseError, match="FINDING_COUNT_MISMATCH"):
        ingest_external_audit_report(scratch_study, 86, "contract", src,
                                     author="redteam:probe", repo_root=REPO_ROOT)


def test_m4_truthful_zero_finding_report_still_passes(tmp_path, scratch_study):
    """The widened detector must not start rejecting honest reports."""
    src = report(
        tmp_path / "honest.md",
        body=("# Review\n\n## Findings by severity\n\nNone.\n\n"
              "## Counts\n- Critical: 0 (none found)\n- Warning: 0\n"),
        audit_type="contract", blocking=0, warning=0, verdict="CLEAR",
    )
    status = ingest_external_audit_report(scratch_study, 87, "contract", src,
                                          author="redteam:probe", repo_root=REPO_ROOT)
    assert status["verdict"] == "CLEAR"
    assert status["blocking"] == 0

"""Tests for audit report parsing and the independent-audit ingestion path.

Two concerns:

1. **Parsing must count findings, not furniture.** A report saying it has zero
   critical findings previously failed with FINDING_COUNT_MISMATCH because the
   words "Critical" appeared in a section heading and a count bullet.
2. **Ingestion must fail closed.** Malformed, self-asserted, stale, wrong-study
   and summary-mismatched reports must all be rejected, so that an externally
   authored audit can be filed without the orchestrator being able to invent one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests._preflight_fixture import plant_audit_ready_preflight  # noqa: E402
from scripts.run_preexec_audits import (  # noqa: E402
    AuditArtifactParseError,
    AuditIngestionError,
    _count_independent_headings,
    ingest_external_audit_report,
    parse_causal_audit_report,
    parse_contract_audit_report,
)

STUDY = REPO_ROOT / "studies" / "Gemini_clean_maturity_flip_rolling_5m_productivity"


def summary_block(**fields) -> str:
    return (
        "<!-- AUDIT_SUMMARY_V2_START -->\n"
        + json.dumps(fields)
        + "\n<!-- AUDIT_SUMMARY_V2_END -->\n"
    )


def write_report(path: Path, body: str, *, omit=(), **summary) -> Path:
    """Writes a report, injecting the mandatory binding fields unless omitted.

    `audit_type`, `study`, `auditor` and `audited_execution_composite_sha256` are
    mandatory on every route (B1/B2). Tests that assert their absence is rejected
    pass e.g. `omit=("study",)`.
    """
    defaults = {
        "audit_type": "causal",
        "study": STUDY.name,
        "auditor": "test:auditor",
        "audited_execution_composite_sha256": "0" * 64,
    }
    for key, value in defaults.items():
        summary.setdefault(key, value)
    for key in omit:
        summary.pop(key, None)
    path.write_text(body + "\n" + summary_block(**summary), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Heading counting
# ---------------------------------------------------------------------------


def test_section_label_is_not_counted_as_a_finding():
    """`## Critical findings` is a section heading, not a finding."""
    crit, warn = _count_independent_headings("## Critical findings\n\nNone were found.\n")
    assert crit == 0 and warn == 0


def test_count_bullet_is_not_counted_as_a_finding():
    """`- Critical: 0` is a count, not a finding."""
    crit, warn = _count_independent_headings("- Critical: 0\n- Warning: 0\n")
    assert crit == 0 and warn == 0


@pytest.mark.parametrize("title", ["0", "none", "None", "N/A", "zero"])
def test_zero_style_titles_are_not_findings(title):
    crit, _ = _count_independent_headings(f"- CRITICAL: {title}\n")
    assert crit == 0


@pytest.mark.parametrize(
    "line",
    [
        "- **Critical:** 0",      # emphasis wraps the colon (real pass_10.md form)
        "- __Critical:__ 0",
        "- `Critical:` 0",
        "- **Critical**: 0",
        "* **BLOCKING:** none",
    ],
)
def test_emphasised_count_bullets_are_not_findings(line):
    """Regression: `- **Critical:** 0` captured a title of `** 0` and was counted."""
    crit, _ = _count_independent_headings(line + "\n")
    assert crit == 0


def test_emphasised_real_findings_are_still_counted():
    crit, _ = _count_independent_headings("### **CRITICAL:** entry uses a future bar\n")
    assert crit == 1


def test_real_finding_headings_are_counted():
    text = (
        "### CRITICAL: entry price reads the signal bar close\n"
        "Body.\n"
        "### WARNING: warmup dispatch is unpinned\n"
        "Body.\n"
    )
    crit, warn = _count_independent_headings(text)
    assert crit == 1 and warn == 1


def test_blocking_is_counted_as_critical_and_decoration_is_tolerated():
    text = "- **BLOCKING**: deliverable X missing\n#### [CRITICAL]: leak in Y\n"
    crit, _ = _count_independent_headings(text)
    assert crit == 2


def test_severity_word_in_prose_is_not_counted():
    text = "This is a critical part of the design. Warning signs were absent.\n"
    crit, warn = _count_independent_headings(text)
    assert crit == 0 and warn == 0


def test_summary_block_is_excluded_from_heading_scan():
    text = "Body.\n" + summary_block(verdict="CLEAR", critical=0, warning=0, note=0)
    crit, warn = _count_independent_headings(text)
    assert crit == 0 and warn == 0


# ---------------------------------------------------------------------------
# End-to-end report parsing: zero / one / mixed severity
# ---------------------------------------------------------------------------


def test_zero_finding_report_parses_clear(tmp_path):
    """The exact shape that previously failed with FINDING_COUNT_MISMATCH."""
    p = write_report(
        tmp_path / "pass_01.md",
        "# Audit\n\n## Critical findings\n\nNone.\n\n## Summary\n- Critical: 0\n- Warning: 0\n",
        verdict="CLEAR", critical=0, warning=0, note=2,
    )
    verdict, crit, warn, note = parse_causal_audit_report(p)
    assert (verdict, crit, warn, note) == ("CLEAR", 0, 0, 2)


def test_single_finding_report_parses_blocked(tmp_path):
    p = write_report(
        tmp_path / "pass_02.md",
        "# Audit\n\n### CRITICAL: future bar used for entry price\nDetail.\n",
        verdict="BLOCKED", critical=1, warning=0, note=0,
    )
    verdict, crit, warn, _ = parse_causal_audit_report(p)
    assert verdict == "BLOCKED" and crit == 1 and warn == 0


def test_mixed_severity_report_parses(tmp_path):
    p = write_report(
        tmp_path / "pass_03.md",
        "### CRITICAL: leak A\nx\n### WARNING: unpinned B\ny\n### WARNING: unpinned C\nz\n",
        verdict="BLOCKED", critical=1, warning=2, note=0,
    )
    verdict, crit, warn, _ = parse_causal_audit_report(p)
    assert (verdict, crit, warn) == ("BLOCKED", 1, 2)


def test_contract_report_parses_blocking(tmp_path):
    p = write_report(
        tmp_path / "contract_pass_01.md",
        "### BLOCKING: deliverable manifest missing\nDetail.\n",
        verdict="BLOCKED", blocking=1, warning=0, note=0,
    )
    verdict, blocking, _warn, _nv = parse_contract_audit_report(p)
    assert verdict == "BLOCKED" and blocking == 1


def test_clear_verdict_with_a_listed_finding_is_rejected(tmp_path):
    """Self-inconsistent report: claims CLEAR while listing a CRITICAL."""
    p = write_report(
        tmp_path / "pass_04.md",
        "### CRITICAL: something real\nDetail.\n",
        verdict="CLEAR", critical=0, warning=0, note=0,
    )
    with pytest.raises(AuditArtifactParseError, match="FINDING_COUNT_MISMATCH"):
        parse_causal_audit_report(p)


def test_missing_summary_block_is_rejected(tmp_path):
    p = tmp_path / "pass_05.md"
    p.write_text("# Audit\nNo summary here.\n", encoding="utf-8")
    with pytest.raises(AuditArtifactParseError, match="MISSING_AUDIT_SUMMARY_V2"):
        parse_causal_audit_report(p)


def test_duplicate_summary_blocks_are_rejected(tmp_path):
    p = tmp_path / "pass_06.md"
    p.write_text(
        summary_block(verdict="CLEAR", critical=0, warning=0, note=0)
        + summary_block(verdict="BLOCKED", critical=1, warning=0, note=0),
        encoding="utf-8",
    )
    with pytest.raises(AuditArtifactParseError, match="DUPLICATE_AUDIT_SUMMARY_V2"):
        parse_causal_audit_report(p)


def test_invalid_verdict_is_rejected(tmp_path):
    p = write_report(tmp_path / "pass_07.md", "body", verdict="PROBABLY_FINE", critical=0)
    with pytest.raises(AuditArtifactParseError, match="Invalid verdict"):
        parse_causal_audit_report(p)


# ---------------------------------------------------------------------------
# Ingestion of independently authored reports
# ---------------------------------------------------------------------------


def current_composite() -> str:
    from scripts.resolve_execution_manifest import resolve_execution_manifest

    composite, _, _ = resolve_execution_manifest(STUDY, repo_root=REPO_ROOT)
    return composite


@pytest.fixture
def scratch_study(tmp_path):
    """A throwaway copy of the real study.

    Ingestion tests must never write into real audit evidence -- an ordering bug
    in the validator would otherwise leave a rejected report behind in the actual
    study directory (which is exactly what happened once during development).
    """
    import shutil

    dest = tmp_path / STUDY.name
    shutil.copytree(STUDY, dest, dirs_exist_ok=True)
    plant_audit_ready_preflight(dest)
    return dest


def test_ingest_rejects_non_markdown_source(tmp_path, scratch_study):
    src = tmp_path / "contract_status.json"
    src.write_text("{}", encoding="utf-8")
    with pytest.raises(AuditIngestionError, match="INGEST_NOT_A_REPORT"):
        ingest_external_audit_report(scratch_study, 99, "contract", src, author="redteam")


def test_ingest_rejects_missing_source(tmp_path, scratch_study):
    with pytest.raises(AuditIngestionError, match="INGEST_SOURCE_MISSING"):
        ingest_external_audit_report(scratch_study, 99, "contract", tmp_path / "nope.md", author="redteam")


def test_ingest_rejects_empty_report(tmp_path, scratch_study):
    src = tmp_path / "r.md"
    src.write_text("   \n", encoding="utf-8")
    with pytest.raises(AuditIngestionError, match="INGEST_EMPTY_REPORT"):
        ingest_external_audit_report(scratch_study, 99, "contract", src, author="redteam")


def test_ingest_rejects_malformed_summary(tmp_path, scratch_study):
    src = tmp_path / "r.md"
    src.write_text("# no summary block\n", encoding="utf-8")
    with pytest.raises(AuditArtifactParseError, match="MISSING_AUDIT_SUMMARY_V2"):
        ingest_external_audit_report(scratch_study, 99, "contract", src, author="redteam")


def test_ingest_rejects_report_without_study_binding(tmp_path, scratch_study):
    src = write_report(
        tmp_path / "r.md", "body", omit=("study",),
        audit_type="contract", verdict="CLEAR", blocking=0, warning=0, note=0,
        audited_execution_composite_sha256=current_composite(),
    )
    with pytest.raises(AuditArtifactParseError, match="INGEST_STUDY_UNDECLARED"):
        ingest_external_audit_report(scratch_study, 99, "contract", src, author="redteam")


def test_ingest_rejects_wrong_study(tmp_path, scratch_study):
    src = write_report(
        tmp_path / "r.md", "body",
        audit_type="contract", verdict="CLEAR", blocking=0, warning=0, note=0,
        study="some_other_study",
        audited_execution_composite_sha256=current_composite(),
    )
    with pytest.raises(AuditIngestionError, match="INGEST_STUDY_MISMATCH"):
        ingest_external_audit_report(scratch_study, 99, "contract", src, author="redteam")


def test_ingest_rejects_report_without_composite_binding(tmp_path, scratch_study):
    src = write_report(
        tmp_path / "r.md", "body", omit=("audited_execution_composite_sha256",),
        audit_type="contract", verdict="CLEAR", blocking=0, warning=0, note=0, study=STUDY.name,
    )
    with pytest.raises(AuditArtifactParseError, match="INGEST_COMPOSITE_UNDECLARED"):
        ingest_external_audit_report(scratch_study, 99, "contract", src, author="redteam")


def test_ingest_rejects_stale_audit(tmp_path, scratch_study):
    """An audit of older code must not be filed against the current tree."""
    src = write_report(
        tmp_path / "r.md", "body",
        audit_type="contract", verdict="CLEAR", blocking=0, warning=0, note=0, study=STUDY.name,
        audited_execution_composite_sha256="0" * 64,
    )
    with pytest.raises(AuditIngestionError, match="INGEST_STALE_AUDIT"):
        ingest_external_audit_report(scratch_study, 99, "contract", src, author="redteam")


def test_ingest_rejects_self_asserted_report(tmp_path, scratch_study):
    """Pointing --ingest at the destination artifact is not independent evidence."""
    dest = scratch_study / "audit" / "contract_pass_10.md"
    assert dest.is_file(), "expected an existing pass-10 contract report"
    with pytest.raises(AuditIngestionError, match="INGEST_SELF_ASSERTED|INGEST_DESTINATION_EXISTS"):
        ingest_external_audit_report(scratch_study, 10, "contract", dest, author="orchestrator")


def test_ingest_rejects_summary_mismatch(tmp_path, scratch_study):
    """A CLEAR claim that contradicts its own listed findings is refused."""
    src = write_report(
        tmp_path / "r.md",
        "### BLOCKING: deliverable missing\ndetail\n",
        audit_type="contract", verdict="CLEAR", blocking=0, warning=0, note=0, study=STUDY.name,
        audited_execution_composite_sha256=current_composite(),
    )
    with pytest.raises(AuditArtifactParseError, match="FINDING_COUNT_MISMATCH|INVALID_CLEAR_VERDICT"):
        ingest_external_audit_report(scratch_study, 99, "contract", src, author="redteam")


def test_ingest_refuses_to_overwrite_existing_pass(tmp_path, scratch_study):
    src = write_report(
        tmp_path / "r.md", "body",
        audit_type="contract", verdict="CLEAR", blocking=0, warning=0, note=0, study=STUDY.name,
        audited_execution_composite_sha256=current_composite(),
    )
    with pytest.raises(AuditIngestionError, match="INGEST_DESTINATION_EXISTS"):
        ingest_external_audit_report(scratch_study, 10, "contract", src, author="redteam")


def test_ingest_accepts_a_well_formed_independent_report(tmp_path):
    """Happy path, executed against a scratch copy so real evidence is untouched."""
    import shutil

    scratch = tmp_path / STUDY.name
    shutil.copytree(STUDY, scratch, dirs_exist_ok=True)
    plant_audit_ready_preflight(scratch)
    # Remove the target pass so ingestion has a clean destination.
    for stale in (scratch / "audit").glob("contract_pass_99.md"):
        stale.unlink()

    src = write_report(
        tmp_path / "independent.md",
        "# Independent contract review\n\n## Findings by severity\n\nNothing blocking.\n",
        audit_type="contract", verdict="CLEAR", blocking=0, warning=0, note=1, study=STUDY.name,
        auditor="redteam:contract-checker",
        audited_execution_composite_sha256=current_composite(),
    )
    status = ingest_external_audit_report(
        scratch, 99, "contract", src, author="redteam:contract-checker", repo_root=REPO_ROOT
    )

    assert status["verdict"] == "CLEAR"
    assert status["ingested_by"] == "redteam:contract-checker"
    assert status["ingested_from"] == str(src)
    assert status["derived_by_parser"] == "scripts/run_preexec_audits.py"
    assert "execution_composite_freshness" in status["ingestion_validated"]
    # The report was filed, and status was re-derived rather than supplied.
    assert (scratch / "audit" / "contract_pass_99.md").is_file()
    assert json.loads((scratch / "audit" / "contract_status.json").read_text())["pass"] == 99

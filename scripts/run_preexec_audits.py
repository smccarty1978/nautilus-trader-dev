"""Deterministic Audit Provenance and Verification Parser.
==========================================================
Ensures that official audit status artifacts (status.json and contract_status.json)
can ONLY be issued by deterministically parsing actual auditor report/transcript artifacts.

The orchestrator CANNOT declare or override the verdict, critical counts, or warning counts.
All metrics and verdicts are derived directly from the immutable auditor markdown artifact.

Reviewer independence (B1), stated honestly:

    The pre-execution workflow requires distinct declared auditor identities for the
    causal and contract review roles. Identity authenticity remains an external
    workflow responsibility.

This is a mechanical constraint on two strings, not cryptographic proof that two
people reviewed the code. The external independent red team remains the final
verification layer.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.preexec_audit_seal import compute_execution_files_manifest, _hash_file
from scripts.resolve_execution_manifest import resolve_execution_manifest

AUDIT_PROVENANCE_VERSION = 2


class AuditArtifactParseError(RuntimeError):
    """Raised when an audit report or transcript cannot be deterministically parsed."""
    pass


VALID_AUDIT_TYPES = ("causal", "contract")


def _extract_v2_summary(
    text: str,
    report_path: Path,
    *,
    expected_audit_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Extracts and parses the strict V2 audit summary block.

    Four fields are mandatory on **every** route, not just ``--ingest``:

    ``verdict``
        CLEAR or BLOCKED.
    ``audit_type``
        ``causal`` or ``contract``. Without it one report satisfies both mandatory
        independent gates, and the seal names two reviewers that never existed.
    ``study``
        The study the auditor reviewed, so a report cannot be filed against another.
    ``audited_execution_composite_sha256``
        The composite the auditor states they reviewed. The issuer *verifies* this
        against the resolved manifest; it never stamps the current value. A stamped
        composite makes the seal's anti-staleness guarantee self-generated.
    """
    start_tag = "<!-- AUDIT_SUMMARY_V2_START -->"
    end_tag = "<!-- AUDIT_SUMMARY_V2_END -->"

    starts = [m.start() for m in re.finditer(re.escape(start_tag), text)]
    ends = [m.end() for m in re.finditer(re.escape(end_tag), text)]

    if len(starts) == 0:
        raise AuditArtifactParseError(
            f"MISSING_AUDIT_SUMMARY_V2: Audit report {report_path.name} must contain exactly one "
            f"<!-- AUDIT_SUMMARY_V2_START --> ... <!-- AUDIT_SUMMARY_V2_END --> block"
        )
    if len(starts) > 1 or len(ends) > 1:
        raise AuditArtifactParseError(
            f"DUPLICATE_AUDIT_SUMMARY_V2: Multiple summary blocks found in {report_path.name}"
        )

    json_text = text[starts[0] + len(start_tag) : ends[0] - len(end_tag)].strip()
    try:
        data = json.loads(json_text)
    except Exception as e:
        raise AuditArtifactParseError(f"MALFORMED_AUDIT_SUMMARY_V2: Invalid JSON in {report_path.name}: {e}")

    if not isinstance(data, dict):
        raise AuditArtifactParseError(f"MALFORMED_AUDIT_SUMMARY_V2: Summary payload must be a JSON object in {report_path.name}")

    verdict = data.get("verdict")
    if verdict not in ("CLEAR", "BLOCKED"):
        raise AuditArtifactParseError(f"MALFORMED_AUDIT_SUMMARY_V2: Invalid verdict '{verdict}' in {report_path.name}")

    # --- B1: a report belongs to exactly one gate ------------------------
    audit_type = data.get("audit_type")
    if audit_type is None:
        raise AuditArtifactParseError(
            f"AUDIT_TYPE_UNDECLARED: {report_path.name} must declare 'audit_type' in its "
            f"AUDIT_SUMMARY_V2 block, one of {list(VALID_AUDIT_TYPES)}. Without it a single "
            f"report can satisfy both mandatory independent gates."
        )
    if audit_type not in VALID_AUDIT_TYPES:
        raise AuditArtifactParseError(
            f"AUDIT_TYPE_INVALID: {report_path.name} declares audit_type={audit_type!r}; "
            f"valid values are {list(VALID_AUDIT_TYPES)}"
        )
    if expected_audit_type is not None and audit_type != expected_audit_type:
        raise AuditArtifactParseError(
            f"AUDIT_TYPE_MISMATCH: {report_path.name} declares audit_type={audit_type!r} but is "
            f"being processed as {expected_audit_type!r}. A causal report cannot satisfy the "
            f"contract gate, or vice versa."
        )

    # --- B1: a real author, never a hard-coded label ---------------------
    auditor = data.get("auditor") or data.get("author")
    if auditor is not None and (not isinstance(auditor, str) or not auditor.strip()):
        raise AuditArtifactParseError(
            f"AUDITOR_INVALID: {report_path.name} declares an empty 'auditor'"
        )

    # --- B2: the auditor declares what they reviewed ---------------------
    study = data.get("study")
    if not study or not isinstance(study, str):
        raise AuditArtifactParseError(
            f"INGEST_STUDY_UNDECLARED: {report_path.name} must declare 'study' in its "
            f"AUDIT_SUMMARY_V2 block so a report cannot be filed against the wrong study."
        )
    composite = data.get("audited_execution_composite_sha256")
    if not composite or not isinstance(composite, str):
        raise AuditArtifactParseError(
            f"INGEST_COMPOSITE_UNDECLARED: {report_path.name} must declare "
            f"'audited_execution_composite_sha256' identifying the code that was reviewed. "
            f"The issuer verifies this value; it is never stamped from the current tree."
        )

    return data


def _verify_declared_binding(
    summary: Dict[str, Any],
    study_dir: Path,
    report_path: Path,
    repo_root: Path,
    error_cls: type = None,
) -> str:
    """Verifies the auditor's declared study and composite against reality (B2).

    Returns the verified composite. Raises rather than substituting, so freshness
    is always an auditor assertion the tool confirmed, never a value the tool
    generated.
    """
    err = error_cls or AuditArtifactParseError
    declared_study = summary["study"]
    if declared_study != study_dir.name:
        raise err(
            f"INGEST_STUDY_MISMATCH: {report_path.name} declares study {declared_study!r} but is "
            f"being filed under {study_dir.name!r}."
        )
    declared = summary["audited_execution_composite_sha256"]
    current, _file_hashes, _ = resolve_execution_manifest(study_dir, repo_root=repo_root)
    if declared != current:
        raise err(
            f"INGEST_STALE_AUDIT: {report_path.name} reviewed execution composite "
            f"{declared[:12]}… but the current tree resolves to {current[:12]}…. "
            f"Re-audit against the current tree; the composite is never re-stamped."
        )
    return current


# A finding heading is `<marker> SEVERITY: <title>`:
#   - a markdown heading (#..####) or list bullet (-/*) marker,
#   - the severity token, optionally wrapped in [] or markdown emphasis,
#   - a MANDATORY colon,
#   - a non-empty title.
#
# The colon and title requirements are what stop the two false-positive classes
# that previously rejected valid reports:
#   `## Critical findings`  -> section label, no colon        -> not a finding
#   `- Critical: 0`         -> count bullet, numeric title    -> not a finding
# A finding may legitimately be written several ways. Under-inclusive detection is
# the dangerous direction: it lets a report claim zero findings while listing them,
# so each of these forms is recognised.
#
#   ### CRITICAL: title              heading
#     - BLOCKING: title              INDENTED bullet          (M4)
#   > - CRITICAL: title              blockquoted bullet       (M4)
#   ### BLOCKING — title             em/en-dash separator     (M4)
#   | F1 | BLOCKING | title |        table row                (M4)
#   ### Finding 1 / Severity: BLOCKING   next-line severity   (M4)
#
# And each of these is NOT a finding:
#   ## Critical findings             section label, no separator
#   - Critical: 0                    count bullet
#   - **Critical:** 0                emphasis around the colon
#   - Critical: 0 (none found)       count with a parenthetical  (W7)
#   - Critical: none / N/A / zero    zero-count language

_SEPARATOR = r"[:–—-]"          # colon, en dash, em dash, hyphen

_FINDING_HEADING = (
    r"^[ \t]*(?:>[ \t]*)*"                 # optional blockquote / indentation
    r"(?:#{1,4}|[-*+])[ \t]+"              # heading or bullet marker
    r"[\[\*_`]{0,3}[ \t]*"                 # optional [ / ** / __ / ` decoration
    r"(?:%s)"                              # severity token
    r"[ \t]*[\]\*_`]{0,3}"                 # closing decoration
    r"[ \t]*" + _SEPARATOR + r"[ \t]*"     # MANDATORY separator
    r"(?P<title>\S.*)$"                    # non-empty title
)

# `| F1 | BLOCKING | closure omits X |`
_FINDING_TABLE_ROW = (
    r"^[ \t]*\|[^|\n]*\|[ \t]*[\[\*_`]{0,3}[ \t]*(?:%s)[ \t]*[\]\*_`]{0,3}[ \t]*\|"
)

# A standalone `Severity: BLOCKING` line (the severity is on the row below a
# neutral `### Finding 1` heading).
_FINDING_SEVERITY_LINE = (
    r"^[ \t]*(?:>[ \t]*)*(?:[-*+][ \t]+)?(?:\*\*|__)?[ \t]*severity[ \t]*(?:\*\*|__)?"
    r"[ \t]*" + _SEPARATOR + r"[ \t]*(?:\*\*|__|`|\[)?[ \t]*(?:%s)\b"
)

# A title that is only a count is a summary line, not a finding. Trailing
# parentheticals and words are tolerated: `0 (none found)`, `none observed`.
_COUNT_ONLY_TITLE = re.compile(
    r"^(?:\d+|none|n/?a|zero|nil)\b[\s.()\w,'\-/]*$", re.IGNORECASE
)


def _count_severity_headings(text: str, severities: str) -> int:
    """Counts genuine findings of the given severities, excluding summary furniture."""
    count = 0
    seen_lines = set()

    heading_re = re.compile(_FINDING_HEADING % severities, re.MULTILINE | re.IGNORECASE)
    for match in heading_re.finditer(text):
        # Strip markdown emphasis from BOTH ends: a count bullet is often written
        # `- **Critical:** 0`, where the colon sits inside the emphasis and the
        # captured title begins with the closing `**`.
        title = match.group("title").strip().strip("*_`").strip()
        if _COUNT_ONLY_TITLE.match(title):
            continue
        seen_lines.add(match.start())
        count += 1

    table_re = re.compile(_FINDING_TABLE_ROW % severities, re.MULTILINE | re.IGNORECASE)
    for match in table_re.finditer(text):
        if match.start() in seen_lines:
            continue
        # A table header/separator row is not a finding.
        line = text[match.start(): text.find("\n", match.start()) if "\n" in text[match.start():]
                    else len(text)]
        if set(line.replace("|", "").strip()) <= set("-: "):
            continue
        seen_lines.add(match.start())
        count += 1

    severity_re = re.compile(_FINDING_SEVERITY_LINE % severities, re.MULTILINE | re.IGNORECASE)
    for match in severity_re.finditer(text):
        if match.start() in seen_lines:
            continue
        seen_lines.add(match.start())
        count += 1

    return count


def _count_independent_headings(text: str) -> Tuple[int, int]:
    """Independently counts finding headings in report markdown body.

    Returns (critical_headings_count, warning_headings_count).
    """
    # Exclude the summary block from heading regex scan to avoid self-matches
    clean_text = re.sub(r"<!-- AUDIT_SUMMARY_V2_START -->.*?<!-- AUDIT_SUMMARY_V2_END -->", "", text, flags=re.DOTALL)

    crit_matches = _count_severity_headings(clean_text, r"CRITICAL|BLOCKING")
    warn_matches = _count_severity_headings(clean_text, r"WARNING")

    return crit_matches, warn_matches


def parse_causal_audit_report(report_path: Path) -> Tuple[str, int, int, int]:
    """Deterministically extracts verdict and counts from an internal causal review report."""
    if not report_path.exists():
        raise FileNotFoundError(f"Causal audit report missing: {report_path}")

    text = report_path.read_text(encoding="utf-8")
    if not text.strip():
        raise AuditArtifactParseError(f"Causal audit report is empty: {report_path}")

    summary = _extract_v2_summary(text, report_path)
    summary_verdict = summary["verdict"]
    crit_sum = int(summary.get("critical", 0))
    warn_sum = int(summary.get("warning", 0))
    note_sum = int(summary.get("note", 0))

    if crit_sum < 0 or warn_sum < 0 or note_sum < 0:
        raise AuditArtifactParseError(f"MALFORMED_AUDIT_SUMMARY_V2: Negative finding counts in {report_path.name}")

    # Independently count headings in body
    crit_headings, warn_headings = _count_independent_headings(text)

    # Invariant: Summary counts must equal independently parsed heading counts
    if crit_headings > crit_sum:
        raise AuditArtifactParseError(
            f"FINDING_COUNT_MISMATCH: Report contains {crit_headings} CRITICAL headings, but summary claims critical={crit_sum}"
        )
    if warn_headings > warn_sum:
        raise AuditArtifactParseError(
            f"FINDING_COUNT_MISMATCH: Report contains {warn_headings} WARNING headings, but summary claims warning={warn_sum}"
        )

    # Deterministic rule: CLEAR allowed only if summary verdict is CLEAR and critical count == 0 and crit headings == 0
    if summary_verdict == "CLEAR" and (crit_sum > 0 or crit_headings > 0):
        raise AuditArtifactParseError(
            f"INVALID_CLEAR_VERDICT: Summary claims CLEAR but records critical={crit_sum} (headings={crit_headings})"
        )

    derived_verdict = "CLEAR" if (summary_verdict == "CLEAR" and crit_sum == 0 and crit_headings == 0) else "BLOCKED"
    return derived_verdict, crit_sum, warn_sum, note_sum


def parse_contract_audit_report(report_path: Path) -> Tuple[str, int, int, int]:
    """Deterministically extracts verdict and counts from an internal contract review report."""
    if not report_path.exists():
        raise FileNotFoundError(f"Contract audit report missing: {report_path}")

    text = report_path.read_text(encoding="utf-8")
    if not text.strip():
        raise AuditArtifactParseError(f"Contract audit report is empty: {report_path}")

    summary = _extract_v2_summary(text, report_path)
    summary_verdict = summary["verdict"]
    block_sum = int(summary.get("blocking", summary.get("critical", 0)))
    warn_sum = int(summary.get("warning", 0))
    nv_sum = int(summary.get("not_verified", 0))

    if block_sum < 0 or warn_sum < 0 or nv_sum < 0:
        raise AuditArtifactParseError(f"MALFORMED_AUDIT_SUMMARY_V2: Negative finding counts in {report_path.name}")

    crit_headings, warn_headings = _count_independent_headings(text)

    if crit_headings > block_sum:
        raise AuditArtifactParseError(
            f"FINDING_COUNT_MISMATCH: Report contains {crit_headings} BLOCKING/CRITICAL headings, but summary claims blocking={block_sum}"
        )
    if warn_headings > warn_sum:
        raise AuditArtifactParseError(
            f"FINDING_COUNT_MISMATCH: Report contains {warn_headings} WARNING headings, but summary claims warning={warn_sum}"
        )

    if summary_verdict == "CLEAR" and (block_sum > 0 or crit_headings > 0):
        raise AuditArtifactParseError(
            f"INVALID_CLEAR_VERDICT: Summary claims CLEAR but records blocking={block_sum} (headings={crit_headings})"
        )

    derived_verdict = "CLEAR" if (summary_verdict == "CLEAR" and block_sum == 0 and crit_headings == 0) else "BLOCKED"
    return derived_verdict, block_sum, warn_sum, nv_sum


def _resolve_auditor(summary: Dict[str, Any], author: Optional[str], report_path: Path) -> str:
    """The recorded auditor must be a real declared identity (B1).

    Previously this defaulted to a hard-coded label, so a seal could name a
    reviewer that never existed. The identity now comes from the report's own
    `auditor`/`author` field or from an explicit `--author`, and the two must agree
    when both are present.
    """
    declared = summary.get("auditor") or summary.get("author")
    if declared and author and declared.strip() != author.strip():
        raise AuditArtifactParseError(
            f"AUDITOR_MISMATCH: {report_path.name} declares auditor {declared!r} but "
            f"--author was given as {author!r}."
        )
    resolved = (author or declared or "").strip()
    if not resolved:
        raise AuditArtifactParseError(
            f"AUDITOR_UNDECLARED: {report_path.name} declares no 'auditor' and no --author was "
            f"supplied. A status artifact must name a real reviewer; there is no default."
        )
    return resolved


def _sibling_status_name(audit_type: str) -> str:
    return "contract_status.json" if audit_type == "causal" else "status.json"


def _read_sibling_status(study_dir: Path, audit_type: str) -> Tuple[Path, Optional[Dict[str, Any]]]:
    """Reads the *other* gate's status artifact, failing closed (N3).

    Returns ``(path, None)`` only when the sibling genuinely does not exist. If it
    exists but cannot be read, parsed, or does not carry the fields the
    independence controls read, this raises: an unreadable control is not a
    satisfied control. "Could not determine the sibling identity" must never be
    interpreted as "safe to proceed" — that is precisely the state an attacker
    can manufacture by corrupting one byte.
    """
    sibling_name = _sibling_status_name(audit_type)
    sibling = study_dir / "audit" / sibling_name
    if not sibling.is_file():
        return sibling, None

    def _invalid(reason: str) -> AuditArtifactParseError:
        return AuditArtifactParseError(
            f"SIBLING_AUDIT_STATUS_INVALID: {sibling_name} exists but {reason}. The causal and "
            f"contract gates cannot be shown to be independent, so issuance fails closed. "
            f"Repair or remove the sibling status and re-issue it from its report."
        )

    try:
        raw = sibling.read_text(encoding="utf-8")
    except OSError as err:
        raise _invalid(f"could not be read ({err})")
    try:
        data = json.loads(raw)
    except ValueError as err:
        raise _invalid(f"is not valid JSON ({err})")
    if not isinstance(data, dict):
        raise _invalid("does not contain a JSON object")

    expected_type = "contract" if audit_type == "causal" else "causal"
    if data.get("audit_type") != expected_type:
        raise _invalid(
            f"declares audit_type={data.get('audit_type')!r}, expected {expected_type!r}"
        )
    auditor = data.get("auditor")
    if not isinstance(auditor, str) or not auditor.strip():
        raise _invalid("names no auditor, so reviewer independence cannot be checked")
    return sibling, data


def _normalise_identity(identity: str) -> str:
    """Identities compare case- and whitespace-insensitively.

    `Alice` and `alice` are one declared reviewer; treating them as two would make
    the control bypassable by pressing shift.
    """
    return " ".join(identity.split()).casefold()


def _reject_auditor_role_reuse(
    study_dir: Path, audit_type: str, auditor: str, report_path: Path
) -> None:
    """The causal reviewer and the contract reviewer must be different (B1).

    Report-type binding stops one *file* from satisfying both gates, but not one
    *reviewer* from authoring both reports — and two reports by the same author is
    a one-reviewer workflow wearing a two-reviewer seal. Report SHA cannot carry
    this control: two reports that differ only in their declared `audit_type`
    necessarily differ in bytes, so their SHAs differ by construction. Declared
    identity is therefore the primary cross-gate control.

    This enforces *distinct declared identities*. It cannot prove that two strings
    correspond to two different people; that remains an external workflow
    responsibility.
    """
    sibling_name = _sibling_status_name(audit_type)
    _sibling, data = _read_sibling_status(study_dir, audit_type)
    if data is None:
        return
    other = data["auditor"]
    if _normalise_identity(other) == _normalise_identity(auditor):
        raise AuditArtifactParseError(
            f"AUDITOR_ROLE_REUSE: {report_path.name} is authored by {auditor!r}, who is already "
            f"recorded in {sibling_name} as the {data['audit_type']} reviewer. The causal and "
            f"contract reviews are independent roles and require distinct declared auditors; "
            f"there is no override."
        )


def _reject_report_reuse(
    study_dir: Path, audit_type: str, report_sha256: str, report_path: Path
) -> None:
    """One report may not satisfy both mandatory gates (B1, defence in depth).

    Checks the *sibling* status artifact for the same report/source SHA. This
    catches tampering and literal reuse, but it is no longer the primary
    independence control — see `_reject_auditor_role_reuse` for why a relabelled
    twin can never collide on SHA.
    """
    sibling_name = _sibling_status_name(audit_type)
    _sibling, data = _read_sibling_status(study_dir, audit_type)
    if data is None:
        return
    for field in ("audit_report_sha256", "source_sha256"):
        other = data.get(field)
        if other and other == report_sha256:
            raise AuditArtifactParseError(
                f"AUDIT_REPORT_REUSED: {report_path.name} (sha {report_sha256[:12]}…) is already "
                f"recorded in {sibling_name} as {field}. The causal and contract gates are "
                f"independent; one report cannot satisfy both."
            )


def issue_causal_audit_status_from_report(
    study_dir: Path,
    pass_num: int,
    auditor: Optional[str] = None,
    transcript_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Issues official audit/status.json by deterministically parsing the pass report."""
    if repo_root is None:
        repo_root = REPO_ROOT

    study_dir = study_dir.resolve()
    report_file = study_dir / "audit" / f"pass_{pass_num:02d}.md"
    if not report_file.exists():
        raise FileNotFoundError(f"Causal audit report missing: {report_file}")

    summary = _extract_v2_summary(
        report_file.read_text(encoding="utf-8"), report_file, expected_audit_type="causal"
    )
    resolved_auditor = _resolve_auditor(summary, auditor, report_file)
    # B1: the contract reviewer may not also be the causal reviewer.
    _reject_auditor_role_reuse(study_dir, "causal", resolved_auditor, report_file)
    # B2: verify the auditor's declared composite; never stamp the current one.
    composite_sha = _verify_declared_binding(summary, study_dir, report_file, repo_root)
    _, file_hashes, _ = resolve_execution_manifest(study_dir, repo_root=repo_root)

    verdict, critical, warning, note = parse_causal_audit_report(report_file)
    report_sha256 = _hash_file(report_file)
    _reject_report_reuse(study_dir, "causal", report_sha256, report_file)

    transcript_sha = _hash_file(transcript_path) if transcript_path and transcript_path.exists() else None
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    status_data = {
        "audit_type": "causal",
        "auditor": resolved_auditor,
        "pass": pass_num,
        "verdict": verdict,
        "critical": critical,
        "warning": warning,
        "note": note,
        "causal_contract": "ts_avail <= T (latest_source_ts_init <= observation_ts)",
        "audited_execution_composite_sha256": composite_sha,
        "audit_report_sha256": report_sha256,
        "audit_report_path": f"audit/pass_{pass_num:02d}.md",
        "transcript_sha256": transcript_sha,
        "derived_by_parser": "scripts/run_preexec_audits.py",
        "audit_provenance_version": AUDIT_PROVENANCE_VERSION,
        "audited_files": file_hashes,
        "timestamp": now_iso,
    }

    status_file = study_dir / "audit" / "status.json"
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=2)

    return status_data


def issue_contract_audit_status_from_report(
    study_dir: Path,
    pass_num: int,
    auditor: Optional[str] = None,
    transcript_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Issues official audit/contract_status.json by deterministically parsing the contract pass report."""
    if repo_root is None:
        repo_root = REPO_ROOT

    study_dir = study_dir.resolve()
    report_file = study_dir / "audit" / f"contract_pass_{pass_num:02d}.md"
    if not report_file.exists():
        raise FileNotFoundError(f"Contract audit report missing: {report_file}")

    summary = _extract_v2_summary(
        report_file.read_text(encoding="utf-8"), report_file, expected_audit_type="contract"
    )
    resolved_auditor = _resolve_auditor(summary, auditor, report_file)
    # B1: the causal reviewer may not also be the contract reviewer.
    _reject_auditor_role_reuse(study_dir, "contract", resolved_auditor, report_file)
    # B2: verify the auditor's declared composite; never stamp the current one.
    composite_sha = _verify_declared_binding(summary, study_dir, report_file, repo_root)
    _, file_hashes, _ = resolve_execution_manifest(study_dir, repo_root=repo_root)

    verdict, blocking, warning, not_verified = parse_contract_audit_report(report_file)
    report_sha256 = _hash_file(report_file)
    _reject_report_reuse(study_dir, "contract", report_sha256, report_file)

    transcript_sha = _hash_file(transcript_path) if transcript_path and transcript_path.exists() else None
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    status_data = {
        "audit_type": "contract",
        "auditor": resolved_auditor,
        "pass": pass_num,
        "verdict": verdict,
        "critical": blocking,
        "blocking": blocking,
        "warning": warning,
        "not_verified": not_verified,
        "audited_execution_composite_sha256": composite_sha,
        "audit_report_sha256": report_sha256,
        "audit_report_path": f"audit/contract_pass_{pass_num:02d}.md",
        "transcript_sha256": transcript_sha,
        "derived_by_parser": "scripts/run_preexec_audits.py",
        "audit_provenance_version": AUDIT_PROVENANCE_VERSION,
        "audited_files": file_hashes,
        "timestamp": now_iso,
    }

    status_file = study_dir / "audit" / "contract_status.json"
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=2)

    return status_data


class AuditIngestionError(RuntimeError):
    """Raised when an externally authored audit report cannot be safely ingested."""
    pass


REPORT_FILENAMES = {
    "causal": "pass_{n:02d}.md",
    "contract": "contract_pass_{n:02d}.md",
}


def ingest_external_audit_report(
    study_dir: Path,
    pass_num: int,
    audit_type: str,
    source_path: Path,
    author: str,
    repo_root: Optional[Path] = None,
    allow_overwrite: bool = False,
) -> Dict[str, Any]:
    """Validates an independently authored audit report and files it as official evidence.

    This exists so that an auditor which cannot write into the repository (a
    read-only agent, a different toolchain, or a human red team) can still supply
    evidence without the orchestrator hand-authoring an audit verdict. Ingestion
    is deliberately narrow and fails closed:

    1. Only a Markdown **report** may be ingested. A status JSON can never be
       supplied directly -- status is always re-derived by the parser here.
    2. The report must parse under the strict V2 rules, including the
       summary-vs-heading consistency check. A report that claims CLEAR while
       listing findings is rejected.
    3. The report must name the study it audited, and it must match ``study_dir``.
    4. The report must declare the execution composite it reviewed, and that must
       equal the composite of the code as it stands now. This is what makes a
       stale audit unusable after a code change.
    5. The destination must not already exist unless ``allow_overwrite``.

    The recorded status carries ``ingested_from``/``ingested_by``/``source_sha256``
    so a reviewer can always see that this evidence arrived from outside.
    """
    if repo_root is None:
        repo_root = REPO_ROOT
    study_dir = study_dir.resolve()
    source_path = Path(source_path)

    if audit_type not in REPORT_FILENAMES:
        raise AuditIngestionError(
            f"INGEST_BAD_TYPE: audit type must be one of {sorted(REPORT_FILENAMES)}, got '{audit_type}'"
        )
    if not source_path.is_file():
        raise AuditIngestionError(f"INGEST_SOURCE_MISSING: {source_path}")
    if source_path.suffix.lower() != ".md":
        raise AuditIngestionError(
            f"INGEST_NOT_A_REPORT: only a Markdown audit report may be ingested, got "
            f"'{source_path.name}'. Status JSON is always re-derived, never supplied."
        )

    # Independence is a structural precondition, checked before validity: a file
    # that is already the destination artifact is not external evidence at all.
    dest = study_dir / "audit" / REPORT_FILENAMES[audit_type].format(n=pass_num)
    if source_path.resolve() == dest.resolve():
        raise AuditIngestionError(
            "INGEST_SELF_ASSERTED: the source report is already the destination artifact; "
            "there is nothing independent to ingest."
        )
    try:
        source_path.resolve().relative_to((study_dir / "audit").resolve())
        raise AuditIngestionError(
            f"INGEST_SELF_ASSERTED: {source_path} already lives inside the study's audit "
            f"directory. Ingestion is for evidence authored outside it."
        )
    except ValueError:
        pass  # outside audit/ -- this is what we want

    text = source_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise AuditIngestionError(f"INGEST_EMPTY_REPORT: {source_path}")

    # (2) strict parse of the SOURCE, before anything is written. This must include
    # the summary-vs-heading consistency check, otherwise a self-contradictory report
    # would be filed into audit/ and only rejected afterwards, leaving the bad
    # artifact behind.
    # `_extract_v2_summary` now enforces audit_type, study and composite declaration
    # on every route, so the ingest path and the default path share one contract.
    summary = _extract_v2_summary(text, source_path, expected_audit_type=audit_type)
    if audit_type == "causal":
        parse_causal_audit_report(source_path)
    else:
        parse_contract_audit_report(source_path)

    # (3)+(4) study and freshness binding, verified against the resolved manifest.
    _verify_declared_binding(summary, study_dir, source_path, repo_root,
                             error_cls=AuditIngestionError)

    # (4b) the report may not already have satisfied the sibling gate
    source_sha = _hash_file(source_path)
    _reject_report_reuse(study_dir, audit_type, source_sha, source_path)

    # (5) destination
    if dest.exists() and not allow_overwrite:
        raise AuditIngestionError(
            f"INGEST_DESTINATION_EXISTS: {dest} already exists. Use a new pass number rather "
            f"than overwriting existing audit evidence."
        )

    # (6) the author may not already hold the sibling reviewer role. Checked here,
    # after the report's own validity and before it is written into audit/, so a
    # rejected ingest leaves nothing behind.
    _reject_auditor_role_reuse(
        study_dir, audit_type, _resolve_auditor(summary, author, source_path), source_path
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")

    issue = (
        issue_causal_audit_status_from_report
        if audit_type == "causal"
        else issue_contract_audit_status_from_report
    )
    status = issue(study_dir, pass_num, auditor=author, repo_root=repo_root)
    status.update(
        {
            "ingested_from": str(source_path),
            "ingested_by": author,
            "source_sha256": source_sha,
            "ingestion_validated": [
                "markdown_report_only",
                "strict_v2_parse",
                "summary_heading_consistency",
                "study_binding",
                "execution_composite_freshness",
                "distinct_gate_auditors",
                "destination_not_overwritten",
            ],
        }
    )
    status_name = "status.json" if audit_type == "causal" else "contract_status.json"
    with open(study_dir / "audit" / status_name, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse auditor artifacts and issue authenticated audit status.")
    parser.add_argument("--study", "-s", type=str, required=True, help="Path to study directory")
    parser.add_argument("--pass-num", "-p", type=int, required=True, help="Pass number to parse")
    parser.add_argument("--ingest", type=str, default=None,
                        help="Path to an independently authored audit report (.md) to validate and file.")
    parser.add_argument("--author", type=str, default=None,
                        help="Identity of the independent auditor supplying --ingest (required with --ingest).")
    parser.add_argument("--allow-overwrite", action="store_true",
                        help="Permit --ingest to replace an existing pass artifact.")
    parser.add_argument("--type", choices=["causal", "contract", "both"], default="both", help="Audit type")
    args = parser.parse_args()

    study_dir = Path(args.study).resolve()

    if args.ingest:
        if args.type == "both":
            print("[ERROR] --ingest requires an explicit --type (causal|contract).", file=sys.stderr)
            return 2
        if not args.author:
            print("[ERROR] --ingest requires --author identifying the independent auditor.",
                  file=sys.stderr)
            return 2
        try:
            status = ingest_external_audit_report(
                study_dir,
                args.pass_num,
                args.type,
                Path(args.ingest),
                author=args.author,
                allow_overwrite=args.allow_overwrite,
            )
        except (AuditIngestionError, AuditArtifactParseError) as err:
            print(f"[ERROR] {err}", file=sys.stderr)
            return 2
        print(
            f"INGESTED {args.type.upper()} AUDIT (Pass {args.pass_num:02d}) from "
            f"{args.ingest} by {args.author}: Verdict={status['verdict']}"
        )
        return 0

    if args.type == "both" and args.author:
        # --author names one reviewer, and one reviewer cannot hold both roles.
        print(
            "[ERROR] AUDITOR_ROLE_REUSE: --author names a single reviewer, but the causal and "
            "contract gates require distinct auditors. Issue each gate separately with its own "
            "--type and --author, or let each report declare its own 'auditor'.",
            file=sys.stderr,
        )
        return 2

    try:
        if args.type in ("causal", "both"):
            c_status = issue_causal_audit_status_from_report(
                study_dir, args.pass_num, auditor=args.author
            )
            print(f"CAUSAL AUDIT STATUS (Pass {args.pass_num:02d}): Verdict={c_status['verdict']} "
                  f"(Critical: {c_status['critical']}, Warning: {c_status['warning']}) "
                  f"auditor={c_status['auditor']}")

        if args.type in ("contract", "both"):
            k_status = issue_contract_audit_status_from_report(
                study_dir, args.pass_num, auditor=args.author
            )
            print(f"CONTRACT AUDIT STATUS (Pass {args.pass_num:02d}): Verdict={k_status['verdict']} "
                  f"(Blocking: {k_status['blocking']}, Warning: {k_status['warning']}) "
                  f"auditor={k_status['auditor']}")
    except AuditArtifactParseError as err:
        print(f"[ERROR] {err}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

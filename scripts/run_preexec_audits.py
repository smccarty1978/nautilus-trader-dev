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
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

    # NEW: verify frozen execution identity first!
    from scripts.resolve_execution_manifest import verify_frozen_execution_identity
    try:
        frozen_data = verify_frozen_execution_identity(study_dir, repo_root=repo_root)
        current = frozen_data["frozen_execution_composite_sha256"]
    except Exception as e:
        raise err(str(e))

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


PASS_LEDGER_NAME = "pass_ledger.json"

# Durable lineage anchor (RT-3).
#
# The local ledger lives inside the study's own `audit/` directory, so `rm -rf` on that
# directory -- or rebuilding the study -- reset a study's audit history to empty and made
# pass 01 available again. "No ledger" was read as "no history", which is precisely the
# state an attacker (or a careless rebuild) can manufacture.
#
# The anchor therefore lives OUTSIDE any study directory, keyed by study identity, and is
# authoritative for the high-water mark. Deleting the study's audit directory can no
# longer erase the fact that a pass was issued.
LINEAGE_DIR_NAME = "audit_lineage"
LINEAGE_VERSION = 1


# ---------------------------------------------------------------------------
# Where durability actually comes from (RT3-B1)
#
# The previous anchor was an untracked file under an environment-redirectable directory,
# so three attacks reset a study's audit history without a trace: delete the anchor,
# roll anchor and ledger back together, or export NT_AUDIT_LINEAGE_DIR at an empty
# directory. "Durable" was the ephemeral half of the pair -- the ledger was committed;
# the anchor was not.
#
# This repository has exactly one durable, integrity-bound, repository-visible store:
# **git**. So git is the substrate, and the durability boundary is stated plainly rather
# than dressed up:
#
#   * the anchor lives at `audit_lineage/<study_id>.json`, INSIDE the repository, and is
#     committed alongside the audit artifacts it anchors (the workflow already requires
#     committing code together with its audit/pass_NN.md + status.json);
#   * `HEAD`'s copy of the anchor and of the study's pass ledger is consulted on every
#     read. A working-tree file that has gone missing, gone backwards, or dropped an
#     entry that HEAD records is a refusal;
#   * the anchor carries a monotonic `issuance_counter` and a `chain_sha256` hash chain,
#     so an internally valid OLD anchor is distinguishable from the current one -- which
#     is what made rollback undetectable before.
#
# What this does NOT claim: no cryptographic signature, no trusted time, no protection
# against someone who rewrites git history. Those need a key or a server, and this repo
# has neither. Within a git-based workflow, once an issuance is committed, deleting or
# rewinding working-tree files cannot silently restore an earlier high-water mark.
# ---------------------------------------------------------------------------

#: Explicit, in-process, test-only anchor relocation.
#:
#: Deliberately NOT an environment variable. An env var is settable from outside the
#: process, which is exactly how the Red Team removed anchor protection from a production
#: run with no filesystem change and no record in any artifact. A module global can only
#: be set by code running inside the interpreter, it does not cross a subprocess boundary,
#: and `set_test_lineage_dir` refuses unless pytest is loaded. A production entrypoint
#: cannot reach this state without editing this file, which is inside the governance
#: closure and therefore moves the execution composite.
#:
#: Most tests do not need it: see `_lineage_path`, where a study outside the repository
#: already anchors beside itself.
_TEST_LINEAGE_DIR: Optional[Path] = None


def set_test_lineage_dir(path: Optional[Path]) -> None:
    """Redirects anchor storage. Test-only; refuses outside a pytest process."""
    global _TEST_LINEAGE_DIR
    if path is not None and "pytest" not in sys.modules:
        raise RuntimeError(
            "LINEAGE_TEST_OVERRIDE_REFUSED: set_test_lineage_dir is a test-only hook and "
            "may not be used to relocate production audit lineage."
        )
    _TEST_LINEAGE_DIR = Path(path) if path is not None else None


def _lineage_path(study_dir: Path, repo_root: Optional[Path] = None) -> Path:
    """Location of a study's durable anchor, keyed by study identity.

    Outside the study directory (so `rm -rf studies/<id>/audit/` cannot erase history)
    but INSIDE the repository (so git can make it durable). Keyed by study *name*,
    matching every other identity check in the workflow.

    A study that lies OUTSIDE the repository anchors beside itself instead, in
    ``<study>/../audit_lineage/``. This is not an override and takes no input from the
    environment or the command line -- it is derived from the study path alone, so
    production behaviour is fixed and unredirectable: every governed study lives under
    ``<repo>/studies/``, so every governed study anchors in the repository. A scratch
    copy in a temp directory is, by construction, not a governed study, and giving it its
    own anchor directory is what keeps one scratch study from being read as a lineage
    reset of the next. Escaping the repository is not a bypass either: carrying the
    resulting audit artifacts back into `studies/<id>/` produces a local ledger the
    repository anchor never recorded, which is refused as AUDIT_LINEAGE_UNANCHORED.
    """
    if _TEST_LINEAGE_DIR is not None:
        return Path(_TEST_LINEAGE_DIR) / f"{Path(study_dir).name}.json"
    root = Path(repo_root) if repo_root else REPO_ROOT
    study_dir = Path(study_dir)
    try:
        study_dir.resolve().relative_to(Path(root).resolve())
    except ValueError:
        return study_dir.resolve().parent / LINEAGE_DIR_NAME / f"{study_dir.name}.json"
    return Path(root) / LINEAGE_DIR_NAME / f"{study_dir.name}.json"


def _lineage_rel_path(study_dir: Path) -> str:
    """Repo-relative POSIX path of the anchor, as git would name it."""
    return f"{LINEAGE_DIR_NAME}/{Path(study_dir).name}.json"


def _git_show(repo_root: Path, rel_path: str) -> Optional[str]:
    """Contents of ``HEAD:<rel_path>``, or None when git or the path is unavailable.

    Returning None for "not a git repo" / "path not committed" is deliberate: a fresh
    study is legitimately uncommitted, and the suite's temp fixtures are not repos. The
    committed copy is used to STRENGTHEN checks, never as the sole source of truth.
    """
    import subprocess
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"HEAD:{rel_path}"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout


def _committed_entries(repo_root: Path, rel_path: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
    """Parses a committed anchor/ledger blob into (entries, full_payload)."""
    raw = _git_show(repo_root, rel_path)
    if raw is None:
        return None, None
    try:
        data = json.loads(raw)
    except ValueError:
        return None, None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return None, None
    return data["entries"], data


def _lineage_integrity(entries: List[Dict[str, Any]]) -> str:
    """Hash over the anchor's entries, so silent edits are detectable."""
    return hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def read_lineage_anchor(
    study_dir: Path, repo_root: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Reads the durable anchor. Returns None only when none has ever been written."""
    p = _lineage_path(study_dir, repo_root)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise AuditArtifactParseError(
            f"AUDIT_LINEAGE_UNREADABLE: {p} exists but could not be parsed ({err}). "
            f"An unreadable lineage anchor is not a satisfied control."
        )
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise AuditArtifactParseError(
            f"AUDIT_LINEAGE_MALFORMED: {p} must be an object with an 'entries' list."
        )
    expected = data.get("integrity_sha256")
    actual = _lineage_integrity(data["entries"])
    if expected != actual:
        raise AuditArtifactParseError(
            f"AUDIT_LINEAGE_TAMPERED: {p} integrity hash does not match its entries "
            f"(recorded {str(expected)[:12]}..., recomputed {actual[:12]}...). The lineage "
            f"anchor has been edited outside the issuer."
        )
    if data.get("study_id") != Path(study_dir).name:
        raise AuditArtifactParseError(
            f"AUDIT_LINEAGE_IDENTITY_MISMATCH: {p} records study_id "
            f"{data.get('study_id')!r} but is being read for {Path(study_dir).name!r}."
        )
    return data


def _chain_sha256(prev_chain: str, entries: List[Dict[str, Any]], counter: int) -> str:
    """Hash-chains each issuance onto the previous one.

    The old integrity hash covered `entries` alone, so an older internally-valid anchor
    was indistinguishable from the current one and rolling both files back was
    undetectable. Chaining the previous head plus a monotonic counter gives the anchor a
    position in a sequence, not just a content hash.
    """
    return hashlib.sha256(
        json.dumps(
            {"prev": prev_chain, "counter": counter, "entries": entries},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_lineage_anchor(
    study_dir: Path,
    entries: List[Dict[str, Any]],
    repo_root: Optional[Path] = None,
    bootstrapped: bool = False,
) -> None:
    p = _lineage_path(study_dir, repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    high_water: Dict[str, int] = {}
    for e in entries:
        t = e.get("audit_type")
        high_water[t] = max(high_water.get(t, 0), int(e.get("pass", 0)))

    prev_counter = 0
    prev_chain = ""
    if p.is_file():
        try:
            prior = json.loads(p.read_text(encoding="utf-8"))
            prev_counter = int(prior.get("issuance_counter", 0))
            prev_chain = str(prior.get("chain_sha256", ""))
        except (OSError, ValueError, TypeError):
            prev_counter, prev_chain = 0, ""
    counter = prev_counter + 1

    payload = {
        "lineage_version": LINEAGE_VERSION,
        "study_id": Path(study_dir).name,
        "bootstrapped_from_local_ledger": bootstrapped,
        "issuance_counter": counter,
        "prev_chain_sha256": prev_chain,
        "chain_sha256": _chain_sha256(prev_chain, entries, counter),
        "high_water": high_water,
        "entries": entries,
        "integrity_sha256": _lineage_integrity(entries),
        "note": (
            "Durable audit lineage anchor. Lives outside the study directory so that "
            "deleting or rebuilding studies/<id>/audit/ cannot reset the audit "
            "high-water mark, and INSIDE the repository so that committing it makes it "
            "durable. COMMIT THIS FILE with the audit artifacts it anchors -- an "
            "uncommitted anchor is only as durable as the working tree. Authoritative "
            "over the study-local pass_ledger.json."
        ),
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _read_pass_ledger(study_dir: Path) -> List[Dict[str, Any]]:
    """Reads the append-only pass ledger, failing closed on corruption."""
    ledger_p = study_dir / "audit" / PASS_LEDGER_NAME
    if not ledger_p.is_file():
        return []
    try:
        data = json.loads(ledger_p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise AuditArtifactParseError(
            f"PASS_LEDGER_UNREADABLE: {ledger_p} exists but could not be parsed ({err}). "
            f"An unreadable immutability ledger is not a satisfied control."
        )
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise AuditArtifactParseError(
            f"PASS_LEDGER_MALFORMED: {ledger_p} must be an object with an 'entries' list."
        )
    return data["entries"]


def _entry_key(e: Dict[str, Any]) -> Tuple[str, int]:
    return (str(e.get("audit_type")), int(e.get("pass", 0)))


def resolve_effective_lineage(
    study_dir: Path, repo_root: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Returns the authoritative pass history, reconciling anchor against local ledger.

    Three states are distinguished, and two of them are refusals:

    ``AUDIT_LINEAGE_RESET_DETECTED``
        the anchor knows about passes the local ledger does not. The audit directory was
        deleted, rebuilt, or rolled back. History is not erasable by removing a file.
    ``AUDIT_LINEAGE_UNANCHORED``
        the local ledger claims passes the anchor never recorded -- a copied study
        directory, or a hand-edited ledger. Refused rather than silently adopted.

    Otherwise the anchor is authoritative. On first sight of a study that has a local
    ledger but no anchor yet, the anchor is bootstrapped from it: that is the one-time
    migration for studies predating this control, and it is recorded explicitly.
    """
    root = Path(repo_root) if repo_root else REPO_ROOT
    local = _read_pass_ledger(study_dir)
    anchor = read_lineage_anchor(study_dir, repo_root)

    anchor_rel = _lineage_rel_path(study_dir)
    ledger_rel = None
    try:
        ledger_rel = (
            Path(study_dir).resolve().relative_to(root.resolve()).as_posix()
            + f"/audit/{PASS_LEDGER_NAME}"
        )
    except ValueError:
        ledger_rel = None  # study outside the repo (test fixture); no git evidence

    committed_anchor_entries, committed_anchor = _committed_entries(root, anchor_rel)
    committed_ledger_entries = None
    if ledger_rel:
        committed_ledger_entries, _ = _committed_entries(root, ledger_rel)

    if anchor is None:
        # A: a study that has demonstrably issued passes may not silently re-bootstrap.
        # "Demonstrably" means evidence that survives deleting the anchor: a local
        # ledger with entries, or a committed anchor/ledger in git history.
        established = bool(local) or bool(committed_anchor_entries) or bool(
            committed_ledger_entries
        )
        if established:
            raise AuditArtifactParseError(
                f"AUDIT_LINEAGE_ANCHOR_MISSING: {study_dir.name} has issued audit passes "
                f"(local ledger entries: {len(local)}; committed anchor: "
                f"{committed_anchor_entries is not None}; committed ledger: "
                f"{committed_ledger_entries is not None}) but its durable anchor "
                f"{anchor_rel} does not exist. Deleting the anchor does not reset audit "
                f"history. If this is a legitimate first migration or a deliberately "
                f"copied study identity, run "
                f"`python scripts/bootstrap_audit_lineage.py --study {study_dir}` and "
                f"commit the anchor -- bootstrap is an explicit, recorded act, not a "
                f"silent default."
            )
        return local

    anchor_entries = anchor["entries"]

    # D: rollback detection. The committed copy in git HEAD is the durable reference
    # point; a working-tree anchor that has gone backwards from it -- lower issuance
    # counter, or missing entries HEAD already records -- is a rewind, not a state.
    if committed_anchor is not None:
        committed_counter = int(committed_anchor.get("issuance_counter", 0) or 0)
        current_counter = int(anchor.get("issuance_counter", 0) or 0)
        if current_counter < committed_counter:
            raise AuditArtifactParseError(
                f"AUDIT_LINEAGE_ROLLBACK_DETECTED: the working-tree anchor for "
                f"{study_dir.name} is at issuance {current_counter}, but the copy "
                f"committed in HEAD is at issuance {committed_counter}. Anchor and "
                f"ledger were rolled back together to an earlier snapshot. Restore the "
                f"committed anchor ({anchor_rel}) or issue the next pass above the "
                f"recorded high-water mark {committed_anchor.get('high_water')}."
            )
        committed_keys = {_entry_key(e) for e in (committed_anchor_entries or [])}
        dropped = sorted(committed_keys - {_entry_key(e) for e in anchor_entries})
        if dropped:
            raise AuditArtifactParseError(
                f"AUDIT_LINEAGE_ROLLBACK_DETECTED: the anchor committed in HEAD records "
                f"audit passes {dropped} that the working-tree anchor no longer "
                f"contains. Committed audit history is not removable by editing a file."
            )

    # The committed ledger is a second, independent durable witness: it catches the case
    # where anchor and ledger are rewound together but the anchor was never committed.
    if committed_ledger_entries:
        committed_ledger_keys = {_entry_key(e) for e in committed_ledger_entries}
        dropped = sorted(committed_ledger_keys - {_entry_key(e) for e in anchor_entries})
        if dropped:
            raise AuditArtifactParseError(
                f"AUDIT_LINEAGE_ROLLBACK_DETECTED: {study_dir.name}'s committed pass "
                f"ledger records audit passes {dropped} that the durable anchor no "
                f"longer contains. Audit history is not reset by rewinding files."
            )
    anchor_keys = {_entry_key(e) for e in anchor_entries}
    local_keys = {_entry_key(e) for e in local}

    missing_locally = sorted(anchor_keys - local_keys)
    if missing_locally:
        raise AuditArtifactParseError(
            f"AUDIT_LINEAGE_RESET_DETECTED: the durable anchor records audit passes that "
            f"{study_dir.name}'s local ledger no longer contains: {missing_locally}. The "
            f"study's audit directory was deleted, rebuilt or rolled back. Audit history is "
            f"not reset by removing a file -- issue the next pass above the recorded "
            f"high-water mark {anchor.get('high_water')}, or restore the ledger."
        )

    unanchored = sorted(local_keys - anchor_keys)
    if unanchored:
        raise AuditArtifactParseError(
            f"AUDIT_LINEAGE_UNANCHORED: {study_dir.name}'s local ledger claims audit passes "
            f"{unanchored} that the durable anchor never recorded. This is what a copied or "
            f"hand-edited study directory looks like. A pass is only real if the issuer "
            f"wrote it to both."
        )

    return anchor_entries


def enforce_pass_immutability(
    study_dir: Path,
    audit_type: str,
    pass_num: int,
    composite_sha256: str,
    report_sha256: str,
    repo_root: Optional[Path] = None,
) -> None:
    """A pass number, once issued, describes one composite forever (B1).

    The failed acceptance test rewrote ``pass_01.md`` in place after execution-affecting
    code changed, then re-issued a status against it. Every existing control passed: the
    report declared the *new* composite, so the freshness check was satisfied, and the
    status pointed at a real file whose SHA matched. What was lost is that pass 01 had
    ever described anything else. Audit history became a single mutable slot.

    Two rules restore it, both read from an append-only ledger:

    ``AUDIT_PASS_IMMUTABLE``
        (audit_type, pass) is already recorded against different content. Re-issuing the
        *identical* report for the identical composite stays allowed, so a retry is not
        punished; changing either is refused.
    ``AUDIT_PASS_NUMBER_STALE``
        a new composite must take a *new* pass number, higher than every pass already
        issued for that gate. This is what makes `pass_01 -> composite A`,
        `pass_02 -> composite B` the only expressible ordering.
    """
    entries = resolve_effective_lineage(study_dir, repo_root)
    same_gate = [e for e in entries if e.get("audit_type") == audit_type]

    for e in same_gate:
        if e.get("pass") != pass_num:
            continue
        if e.get("audited_execution_composite_sha256") == composite_sha256 and \
                e.get("audit_report_sha256") == report_sha256:
            return  # byte-identical re-issue of the same evidence
        raise AuditArtifactParseError(
            f"AUDIT_PASS_IMMUTABLE: {audit_type} pass {pass_num:02d} is already recorded against "
            f"composite {str(e.get('audited_execution_composite_sha256'))[:12]}... "
            f"(report {str(e.get('audit_report_sha256'))[:12]}...). This issuance carries composite "
            f"{composite_sha256[:12]}... (report {report_sha256[:12]}...). Existing audit evidence is "
            f"immutable - file this review under a new pass number."
        )

    prior_composites = {
        e.get("audited_execution_composite_sha256") for e in same_gate
    }
    if prior_composites and composite_sha256 not in prior_composites:
        max_pass = max(int(e.get("pass", 0)) for e in same_gate)
        if pass_num <= max_pass:
            raise AuditArtifactParseError(
                f"AUDIT_PASS_NUMBER_STALE: composite {composite_sha256[:12]}... has not been audited "
                f"under the {audit_type} gate, and pass {pass_num:02d} is not greater than the "
                f"highest issued pass ({max_pass:02d}). A new audited composite requires a new "
                f"immutable pass artifact; use pass {max_pass + 1:02d}."
            )


def append_pass_ledger_entry(
    study_dir: Path,
    audit_type: str,
    pass_num: int,
    composite_sha256: str,
    report_sha256: str,
    auditor: str,
    reviewer_provenance: Dict[str, Any],
    repo_root: Optional[Path] = None,
) -> None:
    """Appends an issuance record to the local ledger AND the durable anchor.

    Both, always. A pass recorded in only one of them is exactly the inconsistency
    `resolve_effective_lineage` refuses.
    """
    ledger_p = study_dir / "audit" / PASS_LEDGER_NAME
    entries = resolve_effective_lineage(study_dir, repo_root)

    for e in entries:
        if e.get("audit_type") == audit_type and e.get("pass") == pass_num:
            return  # already recorded; enforce_pass_immutability proved it identical

    entries.append({
        "audit_type": audit_type,
        "pass": pass_num,
        "audited_execution_composite_sha256": composite_sha256,
        "audit_report_sha256": report_sha256,
        "audit_report_path": f"audit/{REPORT_FILENAMES[audit_type].format(n=pass_num)}",
        "auditor": auditor,
        "reviewer_provenance_strength": reviewer_provenance.get("provenance_strength"),
        "issued_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })

    ledger_p.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger_p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"ledger_version": 1, "entries": entries}, indent=2), encoding="utf-8"
    )
    os.replace(tmp, ledger_p)

    # Durable anchor, outside the study directory (RT-3).
    _write_lineage_anchor(study_dir, entries, repo_root, bootstrapped=False)


def build_reviewer_provenance(
    auditor: str,
    identity_source: str,
    transcript_path: Optional[Path],
) -> Dict[str, Any]:
    """Records exactly how strongly the reviewer identity is evidenced (B2).

    Distinct-auditor enforcement is, and remains, a comparison of two declared strings.
    It cannot prove two humans. Rather than dress that up, this records the strength
    explicitly so a consumer can never read silence as authentication:

    ``DECLARED_IDENTITY_ONLY``
        a name was declared and is distinct from the sibling gate's. Nothing binds it
        to a session. This is the honest default.
    ``SESSION_BOUND``
        a real transcript artifact was supplied and hashed, so the review is bound to
        a concrete session artifact that exists on disk.

    ``independence_proven`` is always False: neither level proves human independence,
    and a field that sometimes claimed otherwise would be the defect this replaces.
    No fake transcript is ever synthesised to reach the higher level.
    """
    # W5: an arbitrary existing file is not session provenance.
    #
    # Previously any readable path promoted the record to SESSION_BOUND -- `--transcript
    # README.md` would have done it. Hashing a file proves the file existed, not that a
    # review session happened. There is currently no supported audit-session evidence
    # contract in this repository, so rather than invent proof the system does not
    # possess, a supplied transcript is recorded as an *attachment* and the strength
    # stays DECLARED_IDENTITY_ONLY.
    session_evidence = None
    attached_artifact = None
    if transcript_path is not None and Path(transcript_path).is_file():
        attached_artifact = {
            "path": str(transcript_path),
            "sha256": _hash_file(Path(transcript_path)),
            "interpretation": (
                "Operator-supplied file, hashed for reference only. It is NOT treated as "
                "authenticated session provenance: no audit-session evidence contract "
                "exists for this workflow, so nothing distinguishes a genuine transcript "
                "from any other readable file."
            ),
        }

    return {
        "declared_auditor": auditor,
        "identity_source": identity_source,
        # Always DECLARED_IDENTITY_ONLY: this workflow has no mechanism that could earn
        # a stronger level. SESSION_BOUND remains defined for a future evidence contract
        # and is deliberately unreachable until one exists.
        "provenance_strength": "DECLARED_IDENTITY_ONLY",
        "session_evidence": session_evidence,
        "attached_artifact": attached_artifact,
        "independence_basis": "distinct_declared_identity_strings",
        "independence_proven": False,
        "limitations": [
            "A declared identity string is not an authenticated reviewer.",
            "Distinctness across the two gates is enforced; human independence is not proven.",
            "No audit-session evidence contract exists, so no supplied file can raise the "
            "provenance strength above DECLARED_IDENTITY_ONLY.",
        ] + ([] if attached_artifact else [
            "No session/transcript artifact was supplied; absence of session evidence is "
            "recorded explicitly and must not be read as authenticated independence.",
        ]),
    }


class AuditReportMissing(AuditArtifactParseError, FileNotFoundError):
    """The report a gate must parse does not exist.

    Deliberately both an `AuditArtifactParseError` — so the CLI reports it as a
    refusal with the contract's own code and exits 2 instead of printing a traceback
    — and a `FileNotFoundError`, so existing callers that catch the file error keep
    working. A missing report is a policy refusal, not a crash.
    """


def _validate_gate_report(
    study_dir: Path,
    pass_num: int,
    audit_type: str,
    *,
    auditor: Optional[str],
    repo_root: Path,
) -> Dict[str, Any]:
    """Every deterministic check that must pass before a gate's status may be written.

    Both the single-gate issuance path and the `--type both` preflight call this, so
    the preflight cannot validate less than issuance enforces. That drift is exactly
    what let a valid causal status be written before the contract gate failed on a
    stale composite, the wrong study, or a hidden BLOCKING finding.

    Returns the material the issuer needs; writes nothing.
    """
    report_file = study_dir / "audit" / REPORT_FILENAMES[audit_type].format(n=pass_num)
    if not report_file.exists():
        raise AuditReportMissing(
            f"AUDIT_REPORT_MISSING: {audit_type} audit report not found: {report_file}"
        )

    summary = _extract_v2_summary(
        report_file.read_text(encoding="utf-8"), report_file, expected_audit_type=audit_type
    )
    resolved_auditor = _resolve_auditor(summary, auditor, report_file)
    # B1: the two review roles require distinct declared auditors.
    _reject_auditor_role_reuse(study_dir, audit_type, resolved_auditor, report_file)
    # B2: verify the auditor's declared study and composite; never stamp the current one.
    composite_sha = _verify_declared_binding(summary, study_dir, report_file, repo_root)

    parser = parse_causal_audit_report if audit_type == "causal" else parse_contract_audit_report
    verdict, primary, warning, tertiary = parser(report_file)

    # RT-1: an audit may not be issued against incomplete preflight evidence. A
    # diagnostic `--skip-tests` run has no failing gate and therefore used to look
    # indistinguishable from a full pass.
    from scripts.research_preflight import PreflightEvidenceError, assert_preflight_audit_ready
    try:
        assert_preflight_audit_ready(study_dir, repo_root)
    except PreflightEvidenceError as err:
        raise AuditArtifactParseError(str(err))

    report_sha256 = _hash_file(report_file)
    _reject_report_reuse(study_dir, audit_type, report_sha256, report_file)
    # B1: a new audited composite requires a new immutable pass artifact. Checked in
    # validation (not issuance) so `--type both` refuses before either status is written.
    enforce_pass_immutability(
        study_dir, audit_type, pass_num, composite_sha, report_sha256, repo_root
    )

    return {
        "audit_type": audit_type,
        "pass_num": pass_num,
        "report_file": report_file,
        "summary": summary,
        "auditor": resolved_auditor,
        "identity_source": "cli_author" if auditor else "report_summary",
        "composite_sha256": composite_sha,
        "verdict": verdict,
        "primary": primary,        # critical (causal) / blocking (contract)
        "warning": warning,
        "tertiary": tertiary,      # note (causal) / not_verified (contract)
        "report_sha256": report_sha256,
    }


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
    checked = _validate_gate_report(study_dir, pass_num, "causal",
                                    auditor=auditor, repo_root=repo_root)
    resolved_auditor = checked["auditor"]
    composite_sha = checked["composite_sha256"]
    verdict, critical, warning, note = (
        checked["verdict"], checked["primary"], checked["warning"], checked["tertiary"]
    )
    report_sha256 = checked["report_sha256"]
    _, file_hashes, _ = resolve_execution_manifest(study_dir, repo_root=repo_root)

    reviewer_provenance = build_reviewer_provenance(
        resolved_auditor, checked["identity_source"], transcript_path
    )
    transcript_sha = (
        reviewer_provenance["attached_artifact"]["sha256"]
        if reviewer_provenance.get("attached_artifact") else None
    )
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
        "reviewer_provenance": reviewer_provenance,
        "derived_by_parser": "scripts/run_preexec_audits.py",
        "audit_provenance_version": AUDIT_PROVENANCE_VERSION,
        "audited_files": file_hashes,
        "timestamp": now_iso,
    }

    status_file = study_dir / "audit" / "status.json"
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=2)

    append_pass_ledger_entry(
        study_dir, "causal", pass_num, composite_sha, report_sha256,
        resolved_auditor, reviewer_provenance, repo_root,
    )
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
    checked = _validate_gate_report(study_dir, pass_num, "contract",
                                    auditor=auditor, repo_root=repo_root)
    resolved_auditor = checked["auditor"]
    composite_sha = checked["composite_sha256"]
    verdict, blocking, warning, not_verified = (
        checked["verdict"], checked["primary"], checked["warning"], checked["tertiary"]
    )
    report_sha256 = checked["report_sha256"]
    _, file_hashes, _ = resolve_execution_manifest(study_dir, repo_root=repo_root)

    reviewer_provenance = build_reviewer_provenance(
        resolved_auditor, checked["identity_source"], transcript_path
    )
    transcript_sha = (
        reviewer_provenance["attached_artifact"]["sha256"]
        if reviewer_provenance.get("attached_artifact") else None
    )
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
        "reviewer_provenance": reviewer_provenance,
        "derived_by_parser": "scripts/run_preexec_audits.py",
        "audit_provenance_version": AUDIT_PROVENANCE_VERSION,
        "audited_files": file_hashes,
        "timestamp": now_iso,
    }

    status_file = study_dir / "audit" / "contract_status.json"
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=2)

    append_pass_ledger_entry(
        study_dir, "contract", pass_num, composite_sha, report_sha256,
        resolved_auditor, reviewer_provenance, repo_root,
    )
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


def preflight_both_gates(
    study_dir: Path,
    pass_num: int,
    author: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """Proves BOTH gates are individually issuable before either status is written.

    `--type both` is one operation and must not half-succeed. Previously the causal
    status was written first and the contract gate failed afterwards — on role reuse,
    a stale composite, the wrong study, or a hidden BLOCKING finding — leaving a CLEAR
    causal status behind from a command that exited 2. A half-written two-gate
    operation is indistinguishable from a deliberate one to whoever reads it next.

    Every per-gate check runs through the same `_validate_gate_report` the issuers
    use, so this cannot silently validate less than issuance enforces. Nothing here
    writes; the issuers then re-run their own checks unchanged, so this is an ordering
    guard, not a second copy of the policy.

    Returns the validated material keyed by gate.
    """
    if repo_root is None:
        repo_root = REPO_ROOT
    study_dir = study_dir.resolve()

    checked: Dict[str, Dict[str, Any]] = {}
    for audit_type in ("causal", "contract"):
        checked[audit_type] = _validate_gate_report(
            study_dir, pass_num, audit_type, auditor=author, repo_root=repo_root
        )

    causal_auditor = checked["causal"]["auditor"]
    contract_auditor = checked["contract"]["auditor"]
    if _normalise_identity(causal_auditor) == _normalise_identity(contract_auditor):
        raise AuditArtifactParseError(
            f"AUDITOR_ROLE_REUSE: both reports for pass {pass_num:02d} are authored by "
            f"{causal_auditor!r}. The causal and contract reviews are independent roles and "
            f"require distinct declared auditors. No status was issued for either gate."
        )
    return checked


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
    parser.add_argument("--transcript", type=str, default=None,
                        help="Path to a real reviewer session/transcript artifact. When supplied it "
                             "is hashed and the status records provenance_strength=SESSION_BOUND. "
                             "Absent, the status records DECLARED_IDENTITY_ONLY explicitly.")
    parser.add_argument("--type", choices=["causal", "contract", "both"], default="both", help="Audit type")
    args = parser.parse_args()
    transcript_p = Path(args.transcript) if args.transcript else None
    if transcript_p is not None and not transcript_p.is_file():
        print(f"[ERROR] TRANSCRIPT_MISSING: {transcript_p} does not exist. A session artifact "
              f"is never synthesised to satisfy provenance.", file=sys.stderr)
        return 2

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
        if args.type == "both":
            # Decide reviewer independence before anything is written, so a refused
            # combined run leaves no partial status behind.
            preflight_both_gates(study_dir, args.pass_num, args.author)

        if args.type in ("causal", "both"):
            c_status = issue_causal_audit_status_from_report(
                study_dir, args.pass_num, auditor=args.author, transcript_path=transcript_p
            )
            print(f"CAUSAL AUDIT STATUS (Pass {args.pass_num:02d}): Verdict={c_status['verdict']} "
                  f"(Critical: {c_status['critical']}, Warning: {c_status['warning']}) "
                  f"auditor={c_status['auditor']}")

        if args.type in ("contract", "both"):
            k_status = issue_contract_audit_status_from_report(
                study_dir, args.pass_num, auditor=args.author, transcript_path=transcript_p
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

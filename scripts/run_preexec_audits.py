"""Deterministic Audit Provenance and Verification Parser.
==========================================================
Ensures that official audit status artifacts (status.json and contract_status.json)
can ONLY be issued by deterministically parsing actual auditor report/transcript artifacts.

The orchestrator CANNOT declare or override the verdict, critical counts, or warning counts.
All metrics and verdicts are derived directly from the immutable auditor markdown artifact.
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


def _extract_v2_summary(text: str, report_path: Path) -> Dict[str, Any]:
    """Extracts and parses strict V2 audit summary JSON block."""
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

    return data


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
_FINDING_HEADING = (
    r"^(?:#{1,4}|[-*])\s+"                 # heading or bullet marker
    r"[\[\*_`]{0,3}\s*"                    # optional [ / ** / __ / ` decoration
    r"(?:%s)"                              # severity token
    r"\s*[\]\*_`]{0,3}"                    # closing decoration
    r"\s*:\s*"                             # MANDATORY colon
    r"(?P<title>\S.*)$"                    # non-empty title
)

_COUNT_ONLY_TITLE = re.compile(r"^(?:\d+|none|n/?a|zero)\b\.?$", re.IGNORECASE)


def _count_severity_headings(text: str, severities: str) -> int:
    pattern = re.compile(_FINDING_HEADING % severities, re.MULTILINE | re.IGNORECASE)
    count = 0
    for match in pattern.finditer(text):
        # Strip markdown emphasis from BOTH ends: a count bullet is often written
        # `- **Critical:** 0`, where the colon sits inside the emphasis and the
        # captured title begins with the closing `**`.
        title = match.group("title").strip().strip("*_`").strip()
        # `- Critical: 0` / `- Warning: none` are summary counts, not findings.
        if _COUNT_ONLY_TITLE.match(title):
            continue
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


def issue_causal_audit_status_from_report(
    study_dir: Path,
    pass_num: int,
    auditor: str = "lookahead_auditor",
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

    verdict, critical, warning, note = parse_causal_audit_report(report_file)
    report_sha256 = _hash_file(report_file)
    composite_sha, file_hashes, _ = resolve_execution_manifest(study_dir, repo_root=repo_root)

    transcript_sha = _hash_file(transcript_path) if transcript_path and transcript_path.exists() else None
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    status_data = {
        "audit_type": "causal",
        "auditor": auditor,
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
    auditor: str = "contract_checker",
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

    verdict, blocking, warning, not_verified = parse_contract_audit_report(report_file)
    report_sha256 = _hash_file(report_file)
    composite_sha, file_hashes, _ = resolve_execution_manifest(study_dir, repo_root=repo_root)

    transcript_sha = _hash_file(transcript_path) if transcript_path and transcript_path.exists() else None
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    status_data = {
        "audit_type": "contract",
        "auditor": auditor,
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
    summary = _extract_v2_summary(text, source_path)
    if audit_type == "causal":
        parse_causal_audit_report(source_path)
    else:
        parse_contract_audit_report(source_path)

    # (3) study binding
    declared_study = summary.get("study")
    if not declared_study:
        raise AuditIngestionError(
            "INGEST_STUDY_UNDECLARED: the AUDIT_SUMMARY_V2 block must carry a 'study' field "
            "naming the audited study, so a report cannot be filed against the wrong study."
        )
    if declared_study != study_dir.name:
        raise AuditIngestionError(
            f"INGEST_STUDY_MISMATCH: report declares study '{declared_study}' but is being "
            f"filed under '{study_dir.name}'."
        )

    # (4) freshness binding
    declared_composite = summary.get("audited_execution_composite_sha256")
    if not declared_composite:
        raise AuditIngestionError(
            "INGEST_COMPOSITE_UNDECLARED: the AUDIT_SUMMARY_V2 block must carry "
            "'audited_execution_composite_sha256' identifying the code that was reviewed."
        )
    current_composite, _file_hashes, _ = resolve_execution_manifest(study_dir, repo_root=repo_root)
    if declared_composite != current_composite:
        raise AuditIngestionError(
            f"INGEST_STALE_AUDIT: report reviewed execution composite {declared_composite[:12]}… "
            f"but current code is {current_composite[:12]}…. Re-audit against the current tree."
        )

    # (5) destination
    if dest.exists() and not allow_overwrite:
        raise AuditIngestionError(
            f"INGEST_DESTINATION_EXISTS: {dest} already exists. Use a new pass number rather "
            f"than overwriting existing audit evidence."
        )

    source_sha = _hash_file(source_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")

    issue = (
        issue_causal_audit_status_from_report
        if audit_type == "causal"
        else issue_contract_audit_status_from_report
    )
    status = issue(study_dir, pass_num, repo_root=repo_root)
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

    if args.type in ("causal", "both"):
        c_status = issue_causal_audit_status_from_report(study_dir, args.pass_num)
        print(f"CAUSAL AUDIT STATUS (Pass {args.pass_num:02d}): Verdict={c_status['verdict']} (Critical: {c_status['critical']}, Warning: {c_status['warning']})")

    if args.type in ("contract", "both"):
        k_status = issue_contract_audit_status_from_report(study_dir, args.pass_num)
        print(f"CONTRACT AUDIT STATUS (Pass {args.pass_num:02d}): Verdict={k_status['verdict']} (Blocking: {k_status['blocking']}, Warning: {k_status['warning']})")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

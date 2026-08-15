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


def _count_independent_headings(text: str) -> Tuple[int, int]:
    """Independently counts finding headings in report markdown body.

    Returns (critical_headings_count, warning_headings_count).
    """
    # Exclude the summary block from heading regex scan to avoid self-matches
    clean_text = re.sub(r"<!-- AUDIT_SUMMARY_V2_START -->.*?<!-- AUDIT_SUMMARY_V2_END -->", "", text, flags=re.DOTALL)

    crit_pattern = re.compile(r"^(?:#{1,4}\s*|[-*]\s*)\[?(?:CRITICAL|BLOCKING)\]?[\s:]+", re.MULTILINE | re.IGNORECASE)
    warn_pattern = re.compile(r"^(?:#{1,4}\s*|[-*]\s*)\[?(?:WARNING)\]?[\s:]+", re.MULTILINE | re.IGNORECASE)

    crit_matches = len(crit_pattern.findall(clean_text))
    warn_matches = len(warn_pattern.findall(clean_text))

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse auditor artifacts and issue authenticated audit status.")
    parser.add_argument("--study", "-s", type=str, required=True, help="Path to study directory")
    parser.add_argument("--pass-num", "-p", type=int, required=True, help="Pass number to parse")
    parser.add_argument("--type", choices=["causal", "contract", "both"], default="both", help="Audit type")
    args = parser.parse_args()

    study_dir = Path(args.study).resolve()

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

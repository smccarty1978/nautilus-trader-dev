"""Bounded auditor brief: the smallest packet sufficient to verify the CHANGED executable surface.

The first real Supervisor V1 validation (2026-09-05) showed the read-only auditors re-discovering the repository on
every pass: 68 / 54 turns and $5.65 / $4.27 for two causal passes, 48 / 42 turns and $2.80 / $2.62 for two contract
passes, most of it spent reading WORKFLOW.md, AGENTS.md, docs/RESEARCH_WORKFLOW.md, compiled_plan.json and every
closure file, then trying (and being denied) to run Python to compute closure membership. Everything they needed was
mechanically derivable. This module derives it ONCE per audit launch and writes ``packets/<task_id>.brief.md``:

* the facts the gates already proved (preflight / readiness / tests / controller state), one line each
* the audit packet reference (path, sha256, bytes) -- the compiled semantic contract, unchanged
* the executable surface: closure size per stage, the closure files that CHANGED since the prior audited composite
  (per-file hash diff against the manifest snapshot taken at the prior launch) and the closure files the study branch
  changed against ``main``; unchanged files need no re-read
* the prior pass's findings to adjudicate first (pass 2+), extracted from the ingested report
* the auditor's exact checklist subset, VERBATIM from ``docs/CAUSAL_CHECKLIST.md`` (never restated by hand, so it
  cannot drift; the split is the one the checklist declares)
* the runtime guarantees the platform already provides (``docs/RESEARCH_WORKFLOW.md`` section 17 / 6.2, verbatim)
* the bounded procedure (no unchanged-file re-reads, packet references first, source only for claims the packet
  cannot prove, stop when the checklist subset is satisfied, no speculative architecture findings)

Coverage is not weakened: the rule text is the checklist's own, the packet is the same compiled packet, and the
auditor may still open any closure file for a claim the packet cannot prove.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from research_workflow.supervisor.packets import sha256_file
from research_workflow.supervisor.state import read_json

CAUSAL_SECTIONS = ("A", "B", "C", "F", "G", "H")
CONTRACT_SECTIONS = ("C", "D", "E")
CAUSAL_RULE_FILTER = {"C": ("C1", "C2", "C3")}
CONTRACT_RULE_FILTER = {"C": ("C4",)}
MAX_PRIOR_FINDING_LINES = 40
PRE_AUDIT_STAGES = ("compile", "prepare", "readiness", "preflight", "tests")
_SECTION_RE = re.compile(r"^## ([A-H])\. (.+)$")
_RULE_RE = re.compile(r"^- \*\*([A-H]\d+)\.\*\*")
_FINDING_RE = re.compile(r"^(#{2,4} .*\b(CRITICAL|WARNING|NOTE)\b.*|#{3,4} \[[A-H]\d+\].*|#{2,4} [CWN]-?\d+\b.*|[-*] \*{0,2}\[?(CRITICAL|WARNING|NOTE)\]?:?\*{0,2}.*"
                          r"|\| *[CWN]-?\d+ *\|.*|\|.*\| *(FAIL|WARNING|NOT VERIFIED|CRITICAL) *\|.*)$")


def _git(args: Sequence[str], cwd: Path) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout.strip() if r.returncode == 0 else ""
    except OSError:
        return ""


# ---------------------------------------------------------------------------- checklist / doc excerpts
def checklist_subset(text: str, kind: str) -> str:
    """The owned sections of docs/CAUSAL_CHECKLIST.md, verbatim, plus the severity definitions. Section C is split by
    rule id exactly as the checklist's SCOPE SPLIT declares (C1-C3 causal, C4 contract)."""
    sections = CAUSAL_SECTIONS if kind == "causal" else CONTRACT_SECTIONS
    rule_filter = CAUSAL_RULE_FILTER if kind == "causal" else CONTRACT_RULE_FILTER
    out: List[str] = []
    current: Optional[str] = None
    keep_bullet = True
    in_severity = False
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            current = m.group(1) if m.group(1) in sections else None
            in_severity = False
            if current:
                out.append(line)
            continue
        if line.startswith("## "):
            in_severity = line.strip().lower().startswith("## severity")
            current = None
            if in_severity:
                out.append(line)
            continue
        if in_severity:
            out.append(line)
            continue
        if current is None:
            continue
        rm = _RULE_RE.match(line)
        if rm:
            allowed = rule_filter.get(current)
            keep_bullet = (allowed is None) or (rm.group(1) in allowed)
        elif not line.startswith("  ") and line.strip():
            keep_bullet = True
        if keep_bullet:
            out.append(line)
    return "\n".join(out).strip() + "\n"


def doc_section(text: str, heading_prefix: str) -> str:
    """One `## N. Title` (or `### N.N Title`) section of a Markdown document, verbatim, up to the next heading of the
    same or higher level."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith(heading_prefix)), None)
    if start is None:
        return ""
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    out = [lines[start]]
    for l in lines[start + 1:]:
        if l.startswith("#") and (len(l) - len(l.lstrip("#"))) <= level:
            break
        out.append(l)
    return "\n".join(out).strip() + "\n"


# ---------------------------------------------------------------------------- closure delta
def closure_delta(current: Dict[str, Any], prior: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cur = dict(current.get("files") or {})
    if not prior:
        return {"prior_composite": None, "changed": [], "added": [], "removed": [], "comparable": False}
    old = dict(prior.get("files") or {})
    changed = [{"file": f, "prior": str(old[f])[:12], "current": str(cur[f])[:12]} for f in sorted(cur) if f in old and old[f] != cur[f]]
    return {"prior_composite": prior.get("frozen_execution_composite_sha256"), "changed": changed,
            "added": sorted(f for f in cur if f not in old), "removed": sorted(f for f in old if f not in cur), "comparable": True}


def closure_changed_vs_main(worktree: Path, files: Sequence[str]) -> List[str]:
    """Closure files the study branch changed against main (a study normally changes none)."""
    if not files:
        return []
    out = _git(["diff", "--name-only", "main...HEAD", "--", *files], worktree)
    return sorted(l.strip().replace("\\", "/") for l in out.splitlines() if l.strip())


# ---------------------------------------------------------------------------- prior findings
def prior_findings(report_text: str) -> List[str]:
    lines = [l.rstrip() for l in report_text.splitlines() if _FINDING_RE.match(l.strip())]
    return lines[:MAX_PRIOR_FINDING_LINES]


def summary_block(report_text: str) -> Dict[str, Any]:
    m = re.search(r"<!-- AUDIT_SUMMARY_V2_START -->\s*(\{.*?\})\s*<!-- AUDIT_SUMMARY_V2_END -->", report_text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except ValueError:
        return {}


def latest_prior_report(study_dir: Path, kind: str) -> Optional[Path]:
    prefix = "pass_" if kind == "causal" else "contract_pass_"
    reports = sorted((Path(study_dir) / "audit").glob(f"{prefix}[0-9][0-9].md"))
    return reports[-1] if reports else None


# ---------------------------------------------------------------------------- gate facts
def _preflight_line(study_dir: Path) -> str:
    p = read_json(Path(study_dir) / "audit" / "preflight.json")
    if not p:
        return "preflight: MISSING"
    outcomes = p.get("check_outcomes") or {}
    passed = sum(1 for v in outcomes.values() if v == "PASSED")
    return (f"preflight: {p.get('status')} ({passed}/{len(p.get('required_checks') or outcomes)} required checks PASSED; "
            f"leaked_outcome_columns={p.get('leaked_outcome_columns')}; composite {str(p.get('execution_composite_sha256'))[:12]})")


def _readiness_line(study_dir: Path) -> str:
    r = read_json(Path(study_dir) / "audit" / "readiness.json")
    if not r:
        return "readiness: MISSING"
    checks = r.get("checks") or []
    ids = ", ".join(f"{c.get('id')}={'pass' if c.get('passed') else 'FAIL'}" for c in checks)
    return f"readiness: {r.get('overall_status')} ({ids}; composite {str(r.get('execution_composite_sha256'))[:12]})"


def _tests_line(study_dir: Path) -> str:
    t = read_json(Path(study_dir) / "_work" / "controller" / "test_summary.json")
    if not t:
        return "tests: MISSING"
    c = t.get("counts") or {}
    return f"tests: {t.get('status') or 'n/a'} {c.get('passed')} passed / {c.get('failed')} failed @ composite {str(t.get('execution_composite_sha256'))[:12]} ({len(t.get('files') or [])} files)"


def _controller_line(study_dir: Path) -> str:
    c = read_json(Path(study_dir) / "_work" / "controller" / "status.json")
    fp = c.get("fingerprints") or {}
    return (f"controller: STATUS={c.get('STATUS')} state={c.get('state')} stage={c.get('stage')} blocker={c.get('blocker_code')}; "
            f"fingerprints execution_composite={str(fp.get('execution_composite'))[:12]} current={str(fp.get('current_execution_composite'))[:12]} "
            f"plan={str(fp.get('plan_sha256'))[:12]} spec={str(fp.get('study_spec'))[:12]}")


def _authorization_line(study_dir: Path) -> str:
    a = read_json(Path(study_dir) / "artifacts" / "experiment_authorization.json")
    if not a:
        return "experiment_authorization.json: MISSING"
    keys = [k for k in ("train_years", "dev_years", "oos_years", "prohibited_years", "authorized_dates", "chronology", "status", "execution_composite_sha256") if k in a]
    return "experiment_authorization.json: " + json.dumps({k: a[k] for k in keys}, default=str)[:600]


def _deliverable_table(study_dir: Path, packet: Dict[str, Any]) -> List[str]:
    """Mechanical existence check of every deliverable declared for the stages that have already run."""
    by_stage = packet.get("deliverables_by_stage") or {}
    rows: List[str] = ["| stage | deliverable | present | bytes |", "|---|---|---|---|"]
    for stage in PRE_AUDIT_STAGES:
        for rel in by_stage.get(stage) or []:
            p = Path(study_dir) / rel
            rows.append(f"| {stage} | `{rel}` | {'yes' if p.is_file() else 'NO'} | {p.stat().st_size if p.is_file() else '-'} |")
    return rows


def _audit_identity_lines(study_dir: Path) -> List[str]:
    out = []
    for name in ("status.json", "contract_status.json"):
        s = read_json(Path(study_dir) / "audit" / name)
        if s:
            out.append(f"- audit/{name}: verdict={s.get('verdict')} auditor=`{s.get('auditor')}` composite {str(s.get('audited_execution_composite_sha256'))[:12]} "
                       f"(critical {s.get('critical')} / warning {s.get('warning')} / note {s.get('note')})")
    return out


# ---------------------------------------------------------------------------- the brief
def build_audit_brief(*, kind: str, study_id: str, study_dir: Path, worktree: Path, task_id: str, audit_packet: Optional[Path],
                      report_path: Path, auditor: str, frozen_composite: Optional[str], out_path: Path, manifest_snapshot: Path,
                      prior_manifest: Optional[Path] = None, prior_source_commit: Optional[str] = None) -> Dict[str, Any]:
    """Write the brief to ``out_path``, snapshot the frozen manifest to ``manifest_snapshot`` and return metrics."""
    study_dir = Path(study_dir); worktree = Path(worktree)
    manifest = read_json(study_dir / "audit" / "frozen_execution_manifest.json")
    if manifest:
        manifest_snapshot.parent.mkdir(parents=True, exist_ok=True)
        manifest_snapshot.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    packet = read_json(audit_packet) if audit_packet and Path(audit_packet).is_file() else {}
    prior = read_json(prior_manifest) if prior_manifest and Path(prior_manifest).is_file() else None
    delta = closure_delta(manifest, prior)
    files = sorted((manifest.get("files") or {}).keys())
    vs_main = closure_changed_vs_main(worktree, files)
    prior_report = latest_prior_report(study_dir, kind)
    prior_text = prior_report.read_text(encoding="utf-8", errors="replace") if prior_report else ""
    prior_summary = summary_block(prior_text) if prior_text else {}
    findings = prior_findings(prior_text) if prior_text else []
    pass_no = (int(re.search(r"(\d+)\.md$", prior_report.name).group(1)) + 1) if prior_report else 1
    checklist_path = worktree / "docs" / "CAUSAL_CHECKLIST.md"
    rw_path = worktree / "docs" / "RESEARCH_WORKFLOW.md"
    checklist = checklist_subset(checklist_path.read_text(encoding="utf-8"), kind) if checklist_path.is_file() else "(docs/CAUSAL_CHECKLIST.md missing in the worktree: read it from the repository)\n"
    rw_text = rw_path.read_text(encoding="utf-8") if rw_path.is_file() else ""
    guarantees = doc_section(rw_text, "## 17.") if kind == "causal" else doc_section(rw_text, "### 6.2")
    stages = (manifest.get("stages") or {})
    stage_counts = ", ".join(f"{s} {len((v or {}).get('files') or [])}" for s, v in sorted(stages.items()))
    packet_bytes = Path(audit_packet).stat().st_size if audit_packet and Path(audit_packet).is_file() else 0
    role = "lookahead-auditor" if kind == "causal" else "contract-checker"
    other = "contract-checker" if kind == "causal" else "lookahead-auditor"
    owned = "A, B, C1-C3, F, G, H" if kind == "causal" else "C4, D, E + deliverables, lifecycle state, model-integrity declarations"

    L: List[str] = []
    L += [f"# AUDIT BRIEF {task_id} -- {kind.upper()} audit, pass {pass_no:02d}, study `{study_id}`", "",
          f"You are `{role}` (owns {owned}). This brief is the SMALLEST packet sufficient to verify the changed executable surface.",
          "Read it, then the audit packet it names, then your role file. Do NOT re-discover the repository.", ""]
    L += ["## 1. Facts the deterministic gates already proved (do not re-derive; cite them)", "",
          f"- audited execution composite (declare exactly this): `{frozen_composite}`",
          f"- plan_sha256 `{manifest.get('plan_sha256')}`  spec_sha256 `{manifest.get('spec_sha256')}`  closure files {manifest.get('file_count')} (hash {manifest.get('hash_algorithm')})",
          f"- {_preflight_line(study_dir)}", f"- {_readiness_line(study_dir)}", f"- {_tests_line(study_dir)}", f"- {_controller_line(study_dir)}",
          f"- worktree `{worktree}` branch `{_git(['rev-parse', '--abbrev-ref', 'HEAD'], worktree)}` @ `{_git(['rev-parse', 'HEAD'], worktree)}`; "
          f"dirty paths: {len(packet.get('worktree_dirty_paths') or [])} (listed in the packet; all under studies/ unless noted)"]
    if kind == "contract":
        L += [f"- {_authorization_line(study_dir)}", *_audit_identity_lines(study_dir), "",
              "Deliverables declared for the stages that already ran (mechanical existence check). A V2 study has no per-study "
              "`config/deliverables_contract.json` (that is the V1 artifact): `packet.deliverables_by_stage` IS the contract, so its absence is not a finding:",
              "", *_deliverable_table(study_dir, packet)]
    L += ["", "## 2. Audit packet = the compiled semantic contract (primary surface)", "",
          f"- `{audit_packet}` ({packet_bytes} bytes, sha256 `{sha256_file(Path(audit_packet)) if audit_packet else None}`, packet_version {packet.get('packet_version')})",
          "- Its `instructions` field describes the MANUAL flow (audit/pass_NN.md + `research audit ingest`); under the supervisor the report path and result card in "
          "your worker packet take precedence. Never write under studies/<id>/.",
          "- `packet.closure.stages` lists every closure file per stage; `audit/frozen_execution_manifest.json` carries the per-file hashes. Open it only to verify a "
          "membership claim -- never compute closure membership yourself (Python is not on your allowlist).", ""]
    L += ["## 3. Executable surface: what changed", "", f"- closure per stage: {stage_counts or 'n/a'}; composite `{str(frozen_composite)[:12]}`"]
    if delta["comparable"]:
        L += [f"- prior audited composite `{str(delta['prior_composite'])[:12]}` -> current `{str(frozen_composite)[:12]}`: "
              f"{len(delta['changed'])} changed, {len(delta['added'])} added, {len(delta['removed'])} removed closure files"]
        L += [f"  - changed: `{c['file']}` {c['prior']} -> {c['current']}" for c in delta["changed"]]
        L += [f"  - added: `{f}`" for f in delta["added"]] + [f"  - removed: `{f}`" for f in delta["removed"]]
        if prior_source_commit:
            L += [f"- prior audited source commit `{prior_source_commit}`; `git diff {prior_source_commit[:12]}..HEAD -- <closure files>` is the exact source delta"]
    else:
        L += ["- first pass of this kind under the supervisor: no prior manifest snapshot; the surface is the full closure named in the packet"]
    L += [f"- closure files the STUDY BRANCH changed against `main`: {vs_main if vs_main else 'none (the platform under audit is main\'s)'}",
          "- Every other closure file is unchanged since the last audit / since main and needs NO re-read. Open a source file only for a claim the packet cannot prove, "
          "and cite `file:line`.", ""]
    L += [f"## 4. Prior findings to adjudicate FIRST (pass {pass_no:02d})", ""]
    if prior_report:
        L += [f"- prior report `{prior_report.relative_to(study_dir).as_posix()}`: verdict {prior_summary.get('verdict')} (critical {prior_summary.get('critical')} / "
              f"warning {prior_summary.get('warning')} / note {prior_summary.get('note')}) by `{prior_summary.get('auditor')}` at composite `{str(prior_summary.get('audited_execution_composite_sha256'))[:12]}`",
              "- Adjudicate every prior finding FIXED / NOT FIXED / WITHDRAWN with ONE line of evidence before raising anything new; never re-raise an addressed finding "
              "under new framing; at most 3 new blocking findings this pass.", "- extracted finding lines:", ""]
        L += [f"    {l}" for l in findings] if findings else ["    (no finding lines detected -- read the prior report's findings sections)"]
    else:
        L += ["- none: this is pass 01. Adjudication table not required."]
    L += ["", f"## 5. Your checklist subset (verbatim from docs/CAUSAL_CHECKLIST.md; `{other}` owns the rest -- refer, never report)", "", checklist.rstrip(), ""]
    if guarantees:
        title = "docs/RESEARCH_WORKFLOW.md section 17 -- runtime guarantees already provided (do not re-derive)" if kind == "causal" \
            else "docs/RESEARCH_WORKFLOW.md section 6.2 -- which model-integrity controls are gates, diagnostics, recommendations"
        L += [f"## 6. {title}", "", guarantees.rstrip(), ""]
    L += ["## 7. Bounded procedure (mandatory)", "",
          "1. Do not reopen unchanged files. Section 3 names what changed; everything else was audited at the prior composite or is main's platform.",
          "2. Use packet references first: streams/visibility, trackers, outcome kernel, chronology, closure membership, deliverables all come from the packet and this brief.",
          "3. Inspect source only for a claim the packet cannot prove (state flow, callback order, a write site). Read the smallest range; cite `file:line`.",
          "4. Stop when every rule id in section 5 is under `Clean checks`, a finding, or `Not applicable`. Then write the report and the result card.",
          "5. No speculative architecture findings. A finding needs a concrete failure path (CRITICAL) or a real defect (WARNING); hygiene is a NOTE.",
          "6. Do NOT read WORKFLOW.md, AGENTS.md, docs/RESEARCH_WORKFLOW.md, docs/CAUSAL_CHECKLIST.md, PLATFORM_STATE.json or compiled_plan.json: this brief carries the "
          "subset you need. compiled_plan.json only for a specific field the packet omits.",
          "7. Do not run Python (`python -c`, heredocs), PowerShell variable assignments or recursive listings: the read-only allowlist denies them and every denial "
          "costs a turn. The only commands you need are `python scripts/research.py study result ...` and, if useful, `git diff`/`git log`/`git status`.",
          "8. Keep `--notes` / `--next-action` free of `;`, `|`, `&`, `>` characters (compound commands are refused by the allowlist); keep them under 300 characters.",
          f"9. Report budget: causal 1,500 words / contract 1,000 words. Write the report to `{report_path}` and declare auditor `{auditor}`.", ""]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(L), encoding="utf-8")
    return {"brief_path": str(out_path), "brief_bytes": out_path.stat().st_size, "audit_packet_bytes": packet_bytes, "pass": pass_no,
            "closure_changed": [c["file"] for c in delta["changed"]], "closure_added": delta["added"], "closure_removed": delta["removed"],
            "closure_changed_vs_main": vs_main, "prior_report": str(prior_report) if prior_report else None, "prior_composite": delta.get("prior_composite"),
            "manifest_snapshot": str(manifest_snapshot) if manifest else None}


__all__ = ["build_audit_brief", "checklist_subset", "doc_section", "closure_delta", "closure_changed_vs_main", "prior_findings", "summary_block",
           "latest_prior_report", "CAUSAL_SECTIONS", "CONTRACT_SECTIONS"]

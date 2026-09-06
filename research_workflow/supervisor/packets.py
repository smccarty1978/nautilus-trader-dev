"""Worker pointer packets and result cards (packet sections 3 and 11.B).

A packet is a SMALL file (``packets/<task_id>.md``: a Markdown pointer with one embedded JSON body) that a
fresh worker process reads instead of a conversation replay. A result card is a JSON FILE the worker
MUST write (``results/<task_id>.result.json``); prose in the model's stdout is non-authoritative.

Staleness binding: every packet carries ``task_id, packet_sha256, study_id, study_contract_sha256,
compiled_plan_sha256, source_commit, platform_commit, expected_branch, expected_worktree``; every result
card repeats them and the supervisor validates ALL before consuming. Any mismatch is
``STALE_WORKER_RESULT`` (never ingested, merged or advanced from; counts as a failed attempt).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PACKET_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
RESULT_STATUSES = ("DONE", "BLOCKED", "FAILED")
BINDING_FIELDS = ("task_id", "packet_sha256", "study_id", "study_contract_sha256", "compiled_plan_sha256", "source_commit",
                  "platform_commit", "expected_branch", "expected_worktree")
_BODY_START = "<!-- SUPERVISOR_PACKET_START -->"
_BODY_END = "<!-- SUPERVISOR_PACKET_END -->"

# Session type -> canonical role (docs/AI_AGENTS.md; .claude/agents/*.md). No parallel role set.
ROLES: Dict[str, Dict[str, Any]] = {
    "STUDY_DESIGN_COMPILE":      {"role": "primary-owner", "role_file": None, "read_only": False, "phase": "A",
                                  "write_surface": "studies/<id>/research_decision.yaml, study.yaml, SPEC.md, compiled_plan.json, CAPABILITY_GAP_HANDOFF.*, _work/handoff/"},
    "CAPABILITY_IMPLEMENTATION": {"role": "implementer", "role_file": ".claude/agents/implementer.md", "read_only": False, "phase": "A",
                                  "write_surface": "the claimed chore write paths only (chore worktree)"},
    "PREPARE_SEAL":              {"role": "primary-owner", "role_file": None, "read_only": False, "phase": "B",
                                  "write_surface": "studies/<id>/ via the controller only"},
    "CAUSAL_AUDIT":              {"role": "lookahead-auditor", "role_file": ".claude/agents/lookahead-auditor.md", "read_only": True, "phase": "B",
                                  "write_surface": "the audit report under the supervisor results dir ONLY (never studies/<id>/)"},
    "CONTRACT_AUDIT":            {"role": "contract-checker", "role_file": ".claude/agents/contract-checker.md", "read_only": True, "phase": "B",
                                  "write_surface": "the audit report under the supervisor results dir ONLY (never studies/<id>/)"},
    "EXECUTION_TRIAGE":          {"role": "results-triager", "role_file": ".claude/agents/results-triager.md", "read_only": True, "phase": "C",
                                  "write_surface": "the result card only (reads cards/logs; never re-runs stages by hand)"},
    "ANALYSIS_DECISION":         {"role": "analysis-decider", "role_file": ".claude/agents/analysis-decider.md", "read_only": False, "phase": "D",
                                  "write_surface": "studies/<id>/artifacts/analysis_decision.json + analysis_decision.md ONLY"},
    "DETERMINISTIC_REPAIR":      {"role": "implementer", "role_file": ".claude/agents/implementer.md", "read_only": False, "phase": "B",
                                  "write_surface": "studies/<id>/ (study.yaml / research_decision.yaml) for a study-side defect; NEVER research_workflow/ or features/"},
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> Optional[str]:
    p = Path(path)
    return sha256_bytes(p.read_bytes()) if p.is_file() else None


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def study_contract_sha256(study_dir: Path) -> Optional[str]:
    """sha256 over research_decision.yaml + study.yaml bytes (the study's declared contract)."""
    parts = []
    for name in ("research_decision.yaml", "study.yaml"):
        p = Path(study_dir) / name
        if p.is_file():
            parts.append(p.read_bytes())
    return sha256_bytes(b"\n".join(parts)) if parts else None


def compiled_plan_sha256(study_dir: Path) -> Optional[str]:
    return sha256_file(Path(study_dir) / "compiled_plan.json")


def git(args: Sequence[str], cwd: Path) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout.strip() if r.returncode == 0 else ""
    except OSError:
        return ""


def packet_body_sha256(body: Dict[str, Any]) -> str:
    stripped = {k: v for k, v in body.items() if k != "packet_sha256"}
    return sha256_bytes(canonical_json(stripped).encode("utf-8"))


def build_packet(*, task_id: str, session_type: str, study_id: str, study_dir: Path, study_worktree: Path, repo_root: Path,
                 provider: str, identity: Dict[str, Any], result_path: Path, results_dir: Path, task: str, read_files: List[str],
                 stop_conditions: List[str], extra: Optional[Dict[str, Any]] = None, worktree_override: Optional[Path] = None,
                 auditor: Optional[str] = None) -> Dict[str, Any]:
    if session_type not in ROLES:
        raise ValueError(f"UNKNOWN_SESSION_TYPE: {session_type}")
    role = ROLES[session_type]
    wt = Path(worktree_override or study_worktree)
    body: Dict[str, Any] = {
        "schema_version": PACKET_SCHEMA_VERSION, "task_id": task_id, "session_type": session_type, "role": role["role"],
        "role_file": role["role_file"], "read_only": bool(role["read_only"]), "phase": role["phase"],
        "study_id": study_id, "study_dir": str(study_dir), "study_worktree": str(study_worktree), "repo_root": str(repo_root),
        "expected_worktree": str(wt), "expected_branch": git(["rev-parse", "--abbrev-ref", "HEAD"], wt) or None,
        "source_commit": git(["rev-parse", "HEAD"], wt) or None, "platform_commit": git(["rev-parse", "main"], repo_root) or None,
        "study_contract_sha256": study_contract_sha256(study_dir), "compiled_plan_sha256": compiled_plan_sha256(study_dir),
        "provider": provider, "identity": {"agent": identity.get("agent"), "session_id": identity.get("session_id")},
        "auditor": auditor,
        "task": task, "read_files": read_files, "write_surface": role["write_surface"], "stop_conditions": stop_conditions,
        "result_path": str(result_path), "results_dir": str(results_dir),
        "result_command": (f"python scripts/research.py study result --packet <this packet path> --status DONE|BLOCKED|FAILED "
                           f"[--blocker-code X] [--next-state X] [--next-action '...'] [--artifact P]... [--changed-file P]... [--commit SHA]... "
                           f"[--tests-json J] [--report P] [--notes '...']"),
        "extra": extra or {},
    }
    body["packet_sha256"] = packet_body_sha256(body)
    return body


def render_packet(body: Dict[str, Any], path: Path) -> Path:
    lines = [f"# WORKER PACKET {body['task_id']} -- {body['session_type']} ({body['role']}) -- study {body['study_id']}", "",
             "You are a FRESH, DISPOSABLE worker process launched by the research supervisor. Do exactly this task, write the",
             "result card FILE named below, and EXIT. Never continue into another role. Never replay a conversation.", "",
             f"- identity: agent={body['identity']['agent']} session={body['identity']['session_id']} (NT_RESEARCH_AGENT / NT_RESEARCH_AGENT_SESSION are set)",
             f"- worktree: `{body['expected_worktree']}` on branch `{body['expected_branch']}` @ `{body['source_commit']}`",
             f"- read-only: {body['read_only']}   phase: {body['phase']}", "",
             "## Task", "", body["task"], "",
             "## Read first (in this order; do not re-discover the repository)", "", *[f"- `{f}`" for f in body["read_files"]], "",
             "## Allowed write surface", "", body["write_surface"], "",
             "## Stop conditions", "", *[f"- {s}" for s in body["stop_conditions"]], "",
             "## Result card (MANDATORY; your stdout is not read)", "",
             f"Write `{body['result_path']}` through the CLI (it copies the binding fields from this packet):", "",
             "```", body["result_command"].replace("<this packet path>", str(path)), "```", "",
             "A missing or invalid card means FAILED. `protected_data_accessed` must stay false unless the packet's stage authorizes it.",
             "Keep `--notes` / `--next-action` free of `;` `|` `&` `>` characters and under 300 characters: the read-only allowlist refuses compound",
             "commands and every refused attempt costs a turn. Run the command exactly once, as a plain single command (no variable assignments).", "",
             _BODY_START, json.dumps(body, indent=2, sort_keys=True, default=str), _BODY_END, ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def read_packet(path: Path) -> Dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    m = re.search(re.escape(_BODY_START) + r"\s*(\{.*\})\s*" + re.escape(_BODY_END), text, re.DOTALL)
    if not m:
        raise ValueError(f"PACKET_BODY_MISSING: {path}")
    body = json.loads(m.group(1))
    if packet_body_sha256(body) != body.get("packet_sha256"):
        raise ValueError(f"PACKET_HASH_MISMATCH: {path}")
    return body


def write_result_card(packet: Dict[str, Any], *, status: str, blocker_code: Optional[str] = None, changed_files: Sequence[str] = (),
                      commits: Sequence[str] = (), tests: Optional[Dict[str, Any]] = None, artifacts: Sequence[str] = (),
                      scientific_decisions_changed: Sequence[str] = (), protected_data_accessed: bool = False, next_state: Optional[str] = None,
                      next_exact_action: Optional[str] = None, notes: Optional[str] = None, session_id: Optional[str] = None,
                      report: Optional[str] = None, extra: Optional[Dict[str, Any]] = None, out_path: Optional[Path] = None) -> Path:
    """Write the versioned result card for ``packet`` (binding fields copied verbatim; source_commit re-read from the worktree)."""
    if status not in RESULT_STATUSES:
        raise ValueError(f"RESULT_STATUS_INVALID: {status}")
    wt = Path(packet["expected_worktree"])
    card: Dict[str, Any] = {"schema_version": RESULT_SCHEMA_VERSION, **{k: packet.get(k) for k in BINDING_FIELDS},
                            "worker_role": packet["role"], "session_type": packet["session_type"], "provider": packet["provider"],
                            "session_id": session_id or packet["identity"].get("session_id"),
                            "branch": git(["rev-parse", "--abbrev-ref", "HEAD"], wt) or None, "head_commit": git(["rev-parse", "HEAD"], wt) or None,
                            "status": status, "blocker_code": blocker_code, "changed_files": list(changed_files), "commits": list(commits),
                            "tests": tests or {"command": None, "new_failures": None, "known": None, "fixed": None}, "artifacts": list(artifacts),
                            "report": report, "scientific_decisions_changed": list(scientific_decisions_changed),
                            "protected_data_accessed": bool(protected_data_accessed), "next_state": next_state, "next_exact_action": next_exact_action,
                            "notes": notes, "extra": extra or {}}
    out = Path(out_path or packet["result_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(card, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(out)
    return out


def validate_result(card: Dict[str, Any], packet: Dict[str, Any], *, current_contract_sha256: Optional[str] = None,
                    current_plan_sha256: Optional[str] = None, current_branch: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
    """(ok, reason, field). Every binding field must equal the packet's; a read-only worker's study contract and compiled
    plan must still be the ones it was launched against; the branch must be the expected one."""
    if not isinstance(card, dict):
        return False, "RESULT_CARD_INVALID: not an object", None
    if card.get("schema_version") != RESULT_SCHEMA_VERSION:
        return False, f"RESULT_CARD_INVALID: schema_version={card.get('schema_version')}", "schema_version"
    if card.get("status") not in RESULT_STATUSES:
        return False, f"RESULT_CARD_INVALID: status={card.get('status')}", "status"
    for f in BINDING_FIELDS:
        if card.get(f) != packet.get(f):
            return False, f"STALE_WORKER_RESULT: {f} mismatch (card={card.get(f)!r} packet={packet.get(f)!r})", f
    if card.get("session_id") != packet["identity"].get("session_id"):
        return False, f"STALE_WORKER_RESULT: session_id mismatch (card={card.get('session_id')!r} packet={packet['identity'].get('session_id')!r})", "session_id"
    if packet.get("read_only"):
        if current_contract_sha256 is not None and current_contract_sha256 != packet.get("study_contract_sha256"):
            return False, "STALE_WORKER_RESULT: study_contract_sha256 changed while a read-only worker ran", "study_contract_sha256"
        if current_plan_sha256 is not None and current_plan_sha256 != packet.get("compiled_plan_sha256"):
            return False, "STALE_WORKER_RESULT: compiled_plan_sha256 changed while a read-only worker ran", "compiled_plan_sha256"
    if current_branch is not None and packet.get("expected_branch") and current_branch != packet.get("expected_branch"):
        return False, f"STALE_WORKER_RESULT: expected_branch {packet.get('expected_branch')!r} but worktree is on {current_branch!r}", "expected_branch"
    if card.get("protected_data_accessed") and not (packet.get("extra") or {}).get("protected_stage_authorized"):
        return False, "RESULT_CARD_INVALID: protected_data_accessed without an authorized stage", "protected_data_accessed"
    return True, "OK", None


__all__ = ["ROLES", "BINDING_FIELDS", "RESULT_STATUSES", "PACKET_SCHEMA_VERSION", "RESULT_SCHEMA_VERSION", "build_packet", "render_packet",
           "read_packet", "write_result_card", "validate_result", "study_contract_sha256", "compiled_plan_sha256", "sha256_file", "git",
           "canonical_json", "packet_body_sha256"]

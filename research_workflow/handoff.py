"""Compact session handoffs so research sessions stay short, resumable and cheap.

Two artifacts, both written by the CLI (``research study compile`` / ``research study handoff``):

* ``studies/<id>/CAPABILITY_GAP_HANDOFF.json`` (+ ``.md``) -- written the moment a compile returns a
  typed CapabilityGap that needs shared Platform V2 work. The study owner STOPS: it does not modify
  ``research_workflow/``, the grammar/compiler or build the capability. A separate short capability
  session consumes the handoff, implements exactly that capability on ``chore/<capability>``, merges
  to ``main`` and writes a ``CAPABILITY_COMPLETE`` card. A fresh study session then merges ``main``,
  recompiles and resumes. See WORKFLOW.md §N.

* ``studies/<id>/_work/handoff/SESSION_HANDOFF.json`` (+ ``.md``) -- the phase-boundary card. Every
  owner session ends by writing it; the next session reads it instead of rediscovering the study.
  Phases (WORKFLOW.md §N): A design/compile, B prepare/seal, C execution, D analysis/closure.

Handoffs are process-local research bookkeeping, not scientific authority: nothing here changes a
plan, a seal or a closure.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PHASES: Dict[str, Dict[str, Any]] = {
    "A": {"name": "design / compile", "stages": ["intake", "capability discovery", "research_decision", "study.yaml", "compile"],
          "end_when": "compiled_plan.json written, or CAPABILITY_GAP_HANDOFF emitted",
          "next_command": "python scripts/run_governed_study.py --study studies/{id} --through seal --execute-authorized"},
    "B": {"name": "prepare / seal", "stages": ["readiness", "preflight", "tests", "causal audit", "contract audit", "seal"],
          "end_when": "READY_TO_SMOKE",
          "next_command": "nohup python -u scripts/run_governed_study.py --study studies/{id} --through analyze --execute-authorized --max-runtime 14400 > studies/{id}/_work/run_analyze.log 2>&1 & disown"},
    "C": {"name": "execution", "stages": ["smoke", "authorized collection", "reconcile", "merge", "pre-fit gates", "fit/score", "freeze", "oos (only if authorized)"],
          "end_when": "deterministic execution artifacts exist (the controller card names the last completed stage)",
          "next_command": "python scripts/research.py study status --study studies/{id}"},
    "D": {"name": "analysis / decision", "stages": ["analysis", "scientific interpretation", "study report", "closure"],
          "end_when": "STUDY_CLOSED (artifacts/study_closure.json)",
          "next_command": "git switch main && git merge --no-ff study/{id}"},
}

PROHIBITED_FOR_STUDY_OWNER = [
    "modifying research_workflow/ (grammar, compiler, host, controller, outcomes, provider bindings)",
    "modifying features/ or the capability registry seeds from the study branch",
    "building the missing capability inside the study session",
    "patching around the gap with study Python",
    "continuing to accumulate context after this handoff: END THE SESSION",
]

# where-prefix -> the platform modules a capability session most likely touches (a hint, not a rule)
_SUGGESTED_FILES = [
    ("context.", ["features/trackers/host_bindings.py", "features/trackers/", "research_workflow/capabilities_index.yaml", "research_workflow/grammar/compiler.py"]),
    ("features.", ["features/library.py", "features/library_mtf.py", "features/registry.py", "features/trackers/host_bindings.py", "research_workflow/provider_host.py"]),
    ("outcome", ["research_workflow/host/outcomes.py", "research_workflow/target_replay_oracle.py", "research_workflow/grammar/spec.py"]),
    ("triggers", ["research_workflow/host/triggers.py", "research_workflow/grammar/spec.py"]),
    ("population", ["research_workflow/grammar/compiler.py", "research_workflow/grammar/predicates.py", "research_workflow/host/predicate_eval.py"]),
    ("chronology", ["research_workflow/grammar/compiler.py", "research_workflow/grammar/spec.py"]),
    ("model", ["research/analysis/modeling.py", "research_workflow/grammar/spec.py"]),
    ("streams", ["research/datasets/", "research_workflow/roots.py", "research_workflow/dataset_v2.py"]),
    ("analysis", ["research_workflow/analysis_v2.py", "research/analysis/"]),
]


def _git(args: List[str], cwd: Path) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout.strip() if r.returncode == 0 else ""
    except OSError:
        return ""


def _yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _yaml_at(doc: Any, where: str) -> Any:
    """Best-effort lookup of a spec path such as ``features.instances[1]`` / ``context.imbalance``."""
    cur = doc
    for part in where.replace("]", "").replace("[", ".").split("."):
        if part == "":
            continue
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def _suggest_files(where: str) -> List[str]:
    out: List[str] = []
    for prefix, files in _SUGGESTED_FILES:
        if where.startswith(prefix):
            out.extend(files)
    return out or ["research_workflow/grammar/compiler.py"]


def _identity() -> Dict[str, Any]:
    try:
        from research_workflow.workspace import writer_identity
        i = writer_identity()
        return {"owner": i["owner"], "agent": i["agent"], "session_id": i["session_id"]}
    except Exception:
        return {}


def _md_list(items: List[Any]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none)"


def write_capability_gap_handoff(study_dir: Path, gap_card: Dict[str, Any], *, repo_root: Path) -> Dict[str, Any]:
    """Write ``CAPABILITY_GAP_HANDOFF.json`` + ``.md`` next to the study spec and return the JSON document."""
    study_dir = Path(study_dir).resolve(); repo_root = Path(repo_root).resolve()
    spec = _yaml(study_dir / "study.yaml")
    decision = _yaml(study_dir / "research_decision.yaml")
    study_id = str((spec.get("study") or {}).get("id") or decision.get("study_id") or study_dir.name)
    gaps = list(gap_card.get("gaps") or [])
    capability_ids = sorted({str(g.get("closest")) for g in gaps if g.get("closest")})
    affected = sorted({str(g.get("where")) for g in gaps})
    suggested = sorted({f for g in gaps for f in _suggest_files(str(g.get("where", "")))})
    requested = []
    for g in gaps:
        node = _yaml_at(spec, str(g.get("where", "")))
        requested.append({"where": g.get("where"), "kind": g.get("kind"), "requested": node if node is not None else g.get("message"),
                          "message": g.get("message"), "detail": g.get("detail") or {}})
    topic = f"{study_id}-{gaps[0].get('kind', 'gap').lower()}" if gaps else f"{study_id}-gap"
    doc: Dict[str, Any] = {
        "schema_version": 1, "kind": "CAPABILITY_GAP_HANDOFF", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "study_id": study_id,
        "study_branch": _git(["rev-parse", "--abbrev-ref", "HEAD"], study_dir) or None,
        "study_worktree": str(_git(["rev-parse", "--show-toplevel"], study_dir) or repo_root),
        "source_platform_commit": _git(["rev-parse", "HEAD"], repo_root) or None,
        "research_question": decision.get("research_question") or (spec.get("study") or {}).get("question"),
        "gap_kinds": gap_card.get("kinds") or sorted({str(g.get("kind")) for g in gaps}),
        "gaps": gaps,
        "requested_semantics": requested,
        "compiler_evidence": {k: gap_card.get(k) for k in ("STATUS", "study_id", "kinds", "count")},
        "affected_yaml_fields": affected,
        "existing_nearest_capabilities": capability_ids,
        "capability_lookup": "python scripts/research.py cap search <term>; python scripts/research.py cap describe <id>",
        "scientific_decisions_already_resolved": {"terminal_decisions": decision.get("terminal_decisions") or {},
                                                  "autonomy_decisions": decision.get("autonomy_decisions") or {}},
        "prohibited_changes": PROHIBITED_FOR_STUDY_OWNER,
        "suggested_platform_files": suggested,
        "proposed_chore_topic": topic,
        "written_by": _identity(),
        "next_action": {
            "study_owner": "END THIS SESSION. Do not implement. Commit study.yaml + research_decision.yaml + this handoff on the study branch first.",
            "capability_session": [
                f"python scripts/research.py ws chore claim {topic} --paths {' '.join(suggested[:3])} --surface \"<one line>\" --as <agent>",
                f"git worktree add \"../<repo>-{topic}\" -b chore/{topic} main",
                "implement ONLY the capability named above; targeted tests; research cap generate --check; audit/promotion if the capability flow requires it",
                "git switch main && git merge --no-ff chore/<topic>; write CAPABILITY_COMPLETE card (research study handoff --study <study> --phase A --note CAPABILITY_COMPLETE:<topic>)",
                f"python scripts/research.py ws chore release {topic}",
            ],
            "resume_session": [
                f"git -C <study worktree> merge --no-ff main",
                f"python scripts/research.py ws claim {study_id} --as <agent>",
                f"python scripts/research.py study compile --study studies/{study_id}",
            ],
        },
    }
    (study_dir / "CAPABILITY_GAP_HANDOFF.json").write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    md = [f"# CAPABILITY_GAP_HANDOFF — {study_id}", "",
          f"Generated {doc['generated_at_utc']} on platform commit `{doc['source_platform_commit']}`, branch `{doc['study_branch']}`.", "",
          "**STUDY OWNER: STOP. Do not implement this capability in the study session. Commit this file and END THE SESSION.**", "",
          "## Research question", "", str(doc["research_question"] or "").strip(), "",
          "## Gaps (compiler evidence)", "",
          _md_list([f"`{g.get('kind')}` at `{g.get('where')}`: {g.get('message')}" + (f" (closest: `{g.get('closest')}`)" if g.get('closest') else "") for g in gaps]), "",
          "## Requested semantics (from study.yaml at each gap)", "",
          _md_list([f"`{r['where']}` -> `{json.dumps(r['requested'], default=str)[:300]}`" for r in requested]), "",
          "## Affected YAML fields", "", _md_list(affected), "",
          "## Existing nearest capabilities", "", _md_list(capability_ids or ["none named by the compiler; use `research cap search`"]), "",
          "## Scientific decisions already resolved", "", "```json", json.dumps(doc["scientific_decisions_already_resolved"], indent=2, default=str), "```", "",
          "## Prohibited for the study owner", "", _md_list(PROHIBITED_FOR_STUDY_OWNER), "",
          "## Suggested platform files (hint)", "", _md_list(suggested), "",
          "## Next action", "", f"Study owner: {doc['next_action']['study_owner']}", "",
          "Capability session (fresh, short):", "", _md_list(doc["next_action"]["capability_session"]), "",
          "Resume session (fresh):", "", _md_list(doc["next_action"]["resume_session"]), ""]
    (study_dir / "CAPABILITY_GAP_HANDOFF.md").write_text("\n".join(md), encoding="utf-8")
    return doc


def _controller_status(study_dir: Path) -> Dict[str, Any]:
    try:
        from research_workflow.governed_controller_v2 import controller_for
        card = controller_for(study_dir).run(through="close", inspect=True)
        keep = ("state", "stage", "blocker", "blocker_code", "reason", "last", "artifact", "next", "STATUS")
        return {k: card.get(k) for k in keep if k in card}
    except Exception as exc:  # status is best-effort: a handoff must never fail because inspection did
        return {"error": f"{type(exc).__name__}: {exc}"}


def write_session_handoff(study_dir: Path, phase: str, *, repo_root: Path, note: Optional[str] = None) -> Dict[str, Any]:
    """Write the phase-boundary card ``_work/handoff/SESSION_HANDOFF.json`` (+ ``.md``) and return it."""
    phase = str(phase).upper()
    if phase not in PHASES:
        raise ValueError(f"UNKNOWN_PHASE: {phase!r} (expected one of {sorted(PHASES)})")
    study_dir = Path(study_dir).resolve(); repo_root = Path(repo_root).resolve()
    spec = _yaml(study_dir / "study.yaml"); decision = _yaml(study_dir / "research_decision.yaml")
    study_id = str((spec.get("study") or {}).get("id") or decision.get("study_id") or study_dir.name)
    art = study_dir / "artifacts"; aud = study_dir / "audit"
    artifacts = sorted(p.name for p in art.iterdir()) if art.is_dir() else []
    audits = sorted(p.name for p in aud.iterdir()) if aud.is_dir() else []
    gap = study_dir / "CAPABILITY_GAP_HANDOFF.json"
    p = PHASES[phase]
    doc: Dict[str, Any] = {
        "schema_version": 1, "kind": "SESSION_HANDOFF", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "study_id": study_id, "phase": phase, "phase_name": p["name"], "phase_stages": p["stages"], "phase_end_condition": p["end_when"],
        "study_branch": _git(["rev-parse", "--abbrev-ref", "HEAD"], study_dir) or None,
        "study_head": _git(["rev-parse", "HEAD"], study_dir) or None,
        "dirty_files": len([l for l in _git(["status", "--porcelain"], study_dir).splitlines() if l.strip()]),
        "platform_main": _git(["rev-parse", "main"], repo_root) or None,
        "datasets": [s.get("dataset") for s in (spec.get("streams") or []) if isinstance(s, dict)],
        "compiled_plan_present": (study_dir / "compiled_plan.json").is_file(),
        "capability_gap_handoff_present": gap.is_file(),
        "controller_status": _controller_status(study_dir),
        "artifacts_present": artifacts, "audits_present": audits,
        "decisions": {"status": decision.get("status"), "terminal_decisions": decision.get("terminal_decisions") or {},
                      "autonomy_decisions": decision.get("autonomy_decisions") or {}},
        "written_by": _identity(), "note": note,
        "next_command": p["next_command"].format(id=study_id),
        "resume": [f"python scripts/research.py ws claim {study_id} --as <agent>", "read this card; do NOT re-discover the repository",
                   p["next_command"].format(id=study_id)],
    }
    out = study_dir / "_work" / "handoff"; out.mkdir(parents=True, exist_ok=True)
    (out / "SESSION_HANDOFF.json").write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    md = [f"# SESSION_HANDOFF — {study_id} — phase {phase} ({p['name']})", "",
          f"Generated {doc['generated_at_utc']}; branch `{doc['study_branch']}` @ `{doc['study_head']}` ({doc['dirty_files']} dirty); main @ `{doc['platform_main']}`.", "",
          f"**Phase ends when:** {p['end_when']}", "",
          "## Controller status", "", "```json", json.dumps(doc["controller_status"], indent=2, default=str), "```", "",
          "## Present", "", f"compiled_plan: {doc['compiled_plan_present']} · capability gap handoff: {doc['capability_gap_handoff_present']}", "",
          "artifacts:", _md_list(artifacts), "", "audits:", _md_list(audits), "",
          "## Decisions", "", "```json", json.dumps(doc["decisions"], indent=2, default=str), "```", "",
          "## Note", "", str(note or "(none)"), "",
          "## Resume (fresh session)", "", _md_list(doc["resume"]), ""]
    (out / "SESSION_HANDOFF.md").write_text("\n".join(md), encoding="utf-8")
    return doc


__all__ = ["PHASES", "PROHIBITED_FOR_STUDY_OWNER", "write_capability_gap_handoff", "write_session_handoff"]

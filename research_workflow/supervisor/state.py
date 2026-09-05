"""Machine-local supervisor state: ``<home>/supervisor/<study_id>/{state.json,events.jsonl,packets/,results/,logs/,pid}``.

``<home>`` is ``~/.nt_research`` (override: ``NT_RESEARCH_SUPERVISOR_HOME``, used by tests). The state
holds ONLY what artifacts cannot tell the supervisor (attempt counters, active worker/job identity, task
ids, timestamps, user-decision cards, bookkeeping hashes); every scientific fact lives in the study.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1
HOME_ENV = "NT_RESEARCH_SUPERVISOR_HOME"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def home() -> Path:
    return Path(os.environ.get(HOME_ENV) or "~/.nt_research").expanduser().resolve()


def supervisor_root() -> Path:
    return home() / "supervisor"


def locks_root() -> Path:
    return home() / "locks"


def study_state_dir(study_id: str) -> Path:
    return supervisor_root() / study_id


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def new_state(*, study_id: str, question_path: Optional[str], question_sha256: Optional[str], platform_commit: Optional[str],
              provider: str, study_branch: Optional[str], study_worktree: Optional[str], repo_root: str, execute_authorized: bool,
              supervisor_session_id: Optional[str] = None, controller_command: Optional[List[str]] = None,
              options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "study_id": study_id, "question_path": question_path, "question_sha256": question_sha256,
        "platform_commit_at_start": platform_commit, "provider": provider, "study_branch": study_branch, "study_worktree": study_worktree,
        "repo_root": repo_root, "execute_authorized": bool(execute_authorized),
        "supervisor_session_id": supervisor_session_id or str(uuid.uuid4()),
        # controller invocation template (tests substitute a synthetic-controller script); placeholders {study} {through}
        "controller_command": controller_command,
        "options": options or {},
        "derived_state": None, "derived_from": {}, "current_phase": None, "last_completed_deterministic_artifact": None,
        "active_worker": None, "active_job": None, "active_capability": None,
        "attempts": {}, "last_blocker_code": None, "blocker_streak": 0,
        "user_intervention_required": False, "user_decision": None,
        "consumed_handoffs": [], "consumed_results": [], "worker_history": [],
        "counters": {"workers_launched": 0, "jobs_launched": 0, "user_interventions": 0, "ticks": 0, "max_packet_bytes": 0},
        "stopped": False, "next_action": None, "created_at_utc": now_utc(), "updated_at_utc": now_utc(),
    }


def load_state(study_id: str) -> Dict[str, Any]:
    p = study_state_dir(study_id) / "state.json"
    if not p.is_file():
        raise FileNotFoundError(f"SUPERVISOR_STATE_MISSING: {p}")
    return read_json(p)


def save_state(state: Dict[str, Any]) -> Path:
    state["updated_at_utc"] = now_utc()
    p = study_state_dir(state["study_id"]) / "state.json"
    atomic_write_json(p, state)
    return p


def append_event(study_id: str, kind: str, **fields: Any) -> Dict[str, Any]:
    d = study_state_dir(study_id); d.mkdir(parents=True, exist_ok=True)
    ev = {"ts_utc": now_utc(), "kind": kind, **fields}
    with (d / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ev, sort_keys=True, default=str) + "\n")
    return ev


def read_events(study_id: str) -> List[Dict[str, Any]]:
    p = study_state_dir(study_id) / "events.jsonl"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def list_study_ids() -> List[str]:
    root = supervisor_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "state.json").is_file())


__all__ = ["SCHEMA_VERSION", "HOME_ENV", "home", "supervisor_root", "locks_root", "study_state_dir", "atomic_write_json", "read_json",
           "new_state", "load_state", "save_state", "append_event", "read_events", "list_study_ids", "now_utc"]

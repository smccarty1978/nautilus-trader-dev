"""``research supervise ...`` and ``research study result`` (packet section 2). Every verb prints one compact JSON card."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_workflow.supervisor import state as S


def _card(payload: Dict[str, Any], *, ok: bool = True) -> int:
    print(json.dumps({"STATUS": "OK" if ok else "FAIL", **payload}, sort_keys=True, default=str))
    return 0 if ok else 2


def _options(ns: argparse.Namespace) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in ("max_workers", "max_heavy_jobs", "worker_timeout_s", "job_timeout_s"):
        v = getattr(ns, k, None)
        if v is not None:
            out[k] = v
    return out


LOOP_LIVENESS_GRACE_S = 2.0


def _detach_loop(repo_root: Path, study_id: str, *, command: Optional[List[str]] = None, grace_s: float = LOOP_LIVENESS_GRACE_S) -> Dict[str, Any]:
    """Spawn the persistent loop detached and PROVE it survived its first seconds (DEV-01b): a loop that dies at
    startup (bad argv, import error) is reported as ``LOOP_DIED`` with the log tail instead of a dead ``loop_pid``."""
    import time
    from research_workflow.supervisor.procs import pid_alive, spawn_detached
    log = S.study_state_dir(study_id) / "logs" / "supervisor.log"
    cmd = list(command) if command else [sys.executable, str(repo_root / "scripts" / "research_supervisor.py"), "supervise", "loop", "--study", study_id]
    pid = spawn_detached(cmd, cwd=repo_root, log_path=log)
    (S.study_state_dir(study_id) / "pid").write_text(str(pid), encoding="utf-8")
    deadline = time.monotonic() + max(0.0, float(grace_s))
    alive = pid_alive(pid)
    while alive and time.monotonic() < deadline:
        time.sleep(0.1)
        alive = pid_alive(pid)
    out: Dict[str, Any] = {"loop_pid": pid, "log": str(log), "loop_alive": alive, "command": cmd}
    if not alive:
        tail = ""
        try:
            tail = log.read_text(encoding="utf-8", errors="replace")[-1200:]
        except OSError:
            pass
        out.update({"blocker_code": "LOOP_DIED", "error": f"LOOP_DIED: the detached supervisor loop (pid {pid}) exited within {grace_s}s; see {log}", "log_tail": tail})
    return out


def cmd_supervise(ns: argparse.Namespace, repo_root: Path) -> int:
    from research_workflow.supervisor.core import Supervisor, SupervisorError, run_loop
    try:
        if ns.cmd == "start":
            sup = Supervisor.start(question=Path(ns.question), repo_root=repo_root, study_id=ns.study_id, provider=ns.provider,
                                   execute_authorized=bool(ns.execute_authorized), options=_options(ns))
            payload: Dict[str, Any] = {"study_id": sup.study_id, "provider": sup.state["provider"], "branch": sup.state["study_branch"],
                                       "worktree": sup.state["study_worktree"], "state_dir": str(sup.dir), "execute_authorized": sup.state["execute_authorized"],
                                       "provider_probe": {k: v for k, v in (sup.state.get("providers") or {}).get(sup.state["provider"], {}).items()
                                                          if k in ("AVAILABLE", "HEADLESS_SUPPORTED", "WRITE_SUPPORTED", "READ_ONLY_SUPPORTED", "CLI_VERSION")}}
            if ns.no_detach:
                payload["first_tick"] = sup.tick()
            else:
                payload.update(_detach_loop(repo_root, sup.study_id))
            payload["next"] = f"python scripts/research.py supervise status {sup.study_id}"
            return _card(payload, ok=payload.get("loop_alive", True))
        if ns.cmd == "adopt":
            sup = Supervisor.adopt(study_dir=Path(ns.study), repo_root=repo_root, provider=ns.provider, execute_authorized=bool(ns.execute_authorized), options=_options(ns))
            payload = {"study_id": sup.study_id, "derived_state": sup.state["derived_state"], "next_action": sup.state["next_action"], "state_dir": str(sup.dir)}
            if not ns.no_detach:
                payload.update(_detach_loop(repo_root, sup.study_id))
            return _card(payload, ok=payload.get("loop_alive", True))
        if ns.cmd == "resume":
            sup = Supervisor(ns.study_id)
            sup.state["stopped"] = False; S.save_state(sup.state); S.append_event(sup.study_id, "RESUME")
            payload = {"study_id": sup.study_id}
            if ns.no_detach:
                payload["tick"] = sup.tick()
            else:
                payload.update(_detach_loop(repo_root, sup.study_id))
            return _card(payload, ok=payload.get("loop_alive", True))
        if ns.cmd == "status":
            return _card(Supervisor(ns.study_id).status())
        if ns.cmd == "list":
            rows = []
            for sid in S.list_study_ids():
                try:
                    st = Supervisor(sid).status()
                    rows.append({k: st.get(k) for k in ("study_id", "provider", "derived_state", "phase", "next_action", "user_intervention_required", "terminal", "loop_alive")})
                except Exception as exc:
                    rows.append({"study_id": sid, "error": str(exc)[:200]})
            return _card({"studies": rows, "root": str(S.supervisor_root())})
        if ns.cmd == "stop":
            return _card(Supervisor(ns.study_id).stop())
        if ns.cmd == "tick":
            ids = [ns.study_id] if ns.study_id else S.list_study_ids()
            return _card({"ticks": {sid: Supervisor(sid).tick() for sid in ids}})
        if ns.cmd == "decide":
            answer = json.loads(Path(ns.answer).read_text(encoding="utf-8"))
            return _card(Supervisor(ns.study_id).decide(answer))
        if ns.cmd == "providers":
            from research_workflow.supervisor.providers import probe_all
            return _card({"providers": probe_all()})
        if ns.cmd == "loop":
            return _card(run_loop(ns.study or None, once=bool(ns.once)))
    except SupervisorError as exc:
        return _card({"error": str(exc), "blocker_code": str(exc).split(":", 1)[0]}, ok=False)
    except FileNotFoundError as exc:
        return _card({"error": str(exc), "blocker_code": "SUPERVISOR_STATE_MISSING"}, ok=False)
    return _card({"error": f"unknown supervise verb {ns.cmd}"}, ok=False)


def cmd_study_result(ns: argparse.Namespace) -> int:
    """Workers write their result card through this verb; the results dir and binding fields come from the packet."""
    from research_workflow.supervisor.packets import read_packet, write_result_card
    try:
        packet = read_packet(Path(ns.packet))
    except (OSError, ValueError) as exc:
        return _card({"error": str(exc), "blocker_code": "PACKET_INVALID"}, ok=False)
    tests = None
    if ns.tests_json:
        raw = ns.tests_json
        tests = json.loads(Path(raw).read_text(encoding="utf-8")) if Path(raw).is_file() else json.loads(raw)
    extra = json.loads(ns.extra_json) if ns.extra_json else None
    session_id = os.environ.get("NT_RESEARCH_AGENT_SESSION") or packet["identity"].get("session_id")
    out = write_result_card(packet, status=ns.status, blocker_code=ns.blocker_code, changed_files=ns.changed_file or [], commits=ns.commit or [], tests=tests,
                            artifacts=ns.artifact or [], scientific_decisions_changed=ns.scientific_decision or [], protected_data_accessed=bool(ns.protected_data_accessed),
                            next_state=ns.next_state, next_exact_action=ns.next_action, notes=ns.notes, session_id=session_id, report=ns.report, extra=extra)
    return _card({"result": str(out), "task_id": packet["task_id"], "status": ns.status, "session_id": session_id})


def add_supervise_parser(sub: argparse._SubParsersAction, repo_root: Path) -> None:
    sv = sub.add_parser("supervise", help="Research Supervisor V1: one prompt -> chain of disposable worker sessions + detached controller jobs (WORKFLOW.md section O)")
    ss = sv.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--provider", choices=["claude", "codex", "gemini", "antigravity", "human", "scripted"], help="default: this shell's writer identity")
        p.add_argument("--execute-authorized", action="store_true", help="the ONLY way post-seal stages ever run (forwarded to the controller; persisted per study)")
        p.add_argument("--no-detach", action="store_true", help="run one tick in the foreground instead of detaching the loop")
        p.add_argument("--max-workers", type=int, dest="max_workers"); p.add_argument("--max-heavy-jobs", type=int, dest="max_heavy_jobs")
        p.add_argument("--worker-timeout", type=float, dest="worker_timeout_s"); p.add_argument("--job-timeout", type=float, dest="job_timeout_s")

    p = ss.add_parser("start"); p.add_argument("--question", required=True); p.add_argument("--study-id"); common(p)
    p = ss.add_parser("adopt"); p.add_argument("--study", required=True, help="studies/<id> of an EXISTING study (position derived from artifacts; nothing re-run)"); common(p)
    p = ss.add_parser("resume"); p.add_argument("study_id"); p.add_argument("--no-detach", action="store_true")
    p = ss.add_parser("status"); p.add_argument("study_id")
    ss.add_parser("list")
    p = ss.add_parser("stop"); p.add_argument("study_id")
    p = ss.add_parser("tick"); p.add_argument("study_id", nargs="?")
    p = ss.add_parser("decide"); p.add_argument("study_id"); p.add_argument("--answer", required=True, help="JSON file with the answer to the pending USER_DECISION card")
    ss.add_parser("providers", help="probe the installed provider CLIs (--version/--help) and print their capability records")
    p = ss.add_parser("loop", help="the persistent loop (what --detach launches)"); p.add_argument("--study", action="append"); p.add_argument("--once", action="store_true")
    for name, sp in ss.choices.items():
        sp.set_defaults(fn=lambda ns, _root=repo_root: cmd_supervise(ns, _root))


def add_study_result_parser(study_sub: argparse._SubParsersAction) -> None:
    r = study_sub.add_parser("result", help="write a worker result card from a supervisor packet (workers never write cards by hand)")
    r.add_argument("--packet", required=True); r.add_argument("--status", required=True, choices=["DONE", "BLOCKED", "FAILED"])
    r.add_argument("--blocker-code"); r.add_argument("--next-state"); r.add_argument("--next-action"); r.add_argument("--notes"); r.add_argument("--report")
    r.add_argument("--artifact", action="append"); r.add_argument("--changed-file", action="append"); r.add_argument("--commit", action="append")
    r.add_argument("--scientific-decision", action="append"); r.add_argument("--tests-json", help="JSON (inline or file): {command, new_failures, known, fixed}")
    r.add_argument("--extra-json"); r.add_argument("--protected-data-accessed", action="store_true")
    r.set_defaults(fn=cmd_study_result)


__all__ = ["add_supervise_parser", "add_study_result_parser", "cmd_supervise", "cmd_study_result"]

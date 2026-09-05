"""Provider adapters (packet sections 3 and 11.F): ``launch_worker`` / ``poll`` / ``kill`` for ONE provider per
supervisor run, plus ``probe_provider`` which records what the INSTALLED binary actually prints.

Adapters: ``claude`` (Claude Code print mode), ``codex`` (``codex exec``), ``gemini`` (``gemini -p``), ``antigravity``
and ``human`` (ATTENDED: the packet is prepared and an instruction file is printed; the supervisor waits for the
result card), ``scripted`` (test-only: runs a Python script that writes a prescribed result card).

No flag is assumed from documentation: a flag is used only when the installed CLI's ``--help`` output names it;
a required flag that is absent fails BEFORE launch with ``PROVIDER_CAPABILITY_UNAVAILABLE``.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_workflow.supervisor.procs import kill_tree, pid_alive, spawn_detached
from research_workflow.supervisor.state import now_utc

PROVIDERS = ("claude", "codex", "gemini", "antigravity", "human", "scripted")
ATTENDED_PROVIDERS = ("antigravity", "human")
_CLI_NAME = {"claude": "claude", "codex": "codex", "gemini": "gemini"}


class ProviderError(RuntimeError):
    pass


@dataclass
class LaunchHandle:
    task_id: str
    provider: str
    pid: Optional[int]
    started_at_utc: str
    deadline_utc: str
    result_path: str
    packet_path: str
    attended: bool = False
    command: List[str] = field(default_factory=list)
    log_path: Optional[str] = None
    session_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _run(cmd: List[str], timeout: float = 20.0) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, shell=False)
        return (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _flag_present(help_text: str, flag: str) -> bool:
    import re
    return re.search(r"(^|\s)" + re.escape(flag) + r"(\s|,|$|=)", help_text, re.MULTILINE) is not None


def probe_provider(provider: str) -> Dict[str, Any]:
    """Probe the installed CLI for ``provider``; never assume a flag. Returns the capability record."""
    rec: Dict[str, Any] = {"provider": provider, "AVAILABLE": False, "HEADLESS_SUPPORTED": False, "ATTENDED_SUPPORTED": True,
                           "WRITE_SUPPORTED": False, "READ_ONLY_SUPPORTED": False, "SESSION_IDENTITY_SOURCE": "NT_RESEARCH_AGENT_SESSION (launcher env)",
                           "CLI_VERSION": None, "probe_output_sha256": None, "binary": None, "flags": {}, "probed_at_utc": now_utc()}
    if provider == "scripted":
        rec.update({"AVAILABLE": True, "HEADLESS_SUPPORTED": True, "WRITE_SUPPORTED": True, "READ_ONLY_SUPPORTED": True, "binary": sys.executable,
                    "CLI_VERSION": sys.version.split()[0], "note": "test-only provider: a Python script writes a prescribed result card"})
        return rec
    if provider in ATTENDED_PROVIDERS:
        rec.update({"AVAILABLE": True, "HEADLESS_SUPPORTED": False, "WRITE_SUPPORTED": True, "READ_ONLY_SUPPORTED": True,
                    "note": "attended only: no headless interface exists on this machine; the supervisor prints the instruction and waits for the result card"})
        if provider == "antigravity":
            exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Antigravity IDE" / "Antigravity IDE.exe"
            rec["binary"] = str(exe) if exe.is_file() else os.environ.get("NT_ANTIGRAVITY_EXE")
        return rec
    name = _CLI_NAME.get(provider)
    if not name:
        rec["error"] = f"UNKNOWN_PROVIDER: {provider}"
        return rec
    binary = shutil.which(name)
    rec["binary"] = binary
    if not binary:
        rec["error"] = f"PROVIDER_CAPABILITY_UNAVAILABLE: {name} not on PATH"
        return rec
    version = _run([binary, "--version"]).strip()
    help_text = _run([binary, "exec", "--help"]) if provider == "codex" else _run([binary, "--help"])
    rec.update({"AVAILABLE": True, "CLI_VERSION": version.splitlines()[0] if version else None,
                "probe_output_sha256": hashlib.sha256((version + "\n" + help_text).encode("utf-8", "replace")).hexdigest()})
    if provider == "claude":
        flags = {f: _flag_present(help_text, f) for f in ("-p", "--print", "--output-format", "--permission-mode", "--dangerously-skip-permissions",
                                                            "--allowedTools", "--disallowedTools", "--add-dir", "--session-id", "--max-turns",
                                                            "--no-session-persistence", "--tools", "--bare")}
        rec["flags"] = flags
        rec["HEADLESS_SUPPORTED"] = bool(flags["-p"] or flags["--print"])
        rec["WRITE_SUPPORTED"] = rec["HEADLESS_SUPPORTED"] and bool(flags["--dangerously-skip-permissions"] or flags["--permission-mode"])
        rec["READ_ONLY_SUPPORTED"] = rec["HEADLESS_SUPPORTED"] and bool(flags["--allowedTools"] or flags["--tools"] or flags["--disallowedTools"])
        rec["SESSION_IDENTITY_SOURCE"] = "NT_RESEARCH_AGENT_SESSION (launcher env) + --session-id when supported"
    elif provider == "codex":
        flags = {f: _flag_present(help_text, f) for f in ("--sandbox", "-s", "--cd", "-C", "--json", "--output-last-message", "-o",
                                                            "--skip-git-repo-check", "--add-dir", "--dangerously-bypass-approvals-and-sandbox", "--ephemeral")}
        rec["flags"] = flags
        rec["HEADLESS_SUPPORTED"] = "exec" in help_text.lower() or bool(flags["--json"])
        rec["WRITE_SUPPORTED"] = rec["HEADLESS_SUPPORTED"] and bool(flags["--sandbox"] or flags["-s"] or flags["--dangerously-bypass-approvals-and-sandbox"])
        rec["READ_ONLY_SUPPORTED"] = rec["HEADLESS_SUPPORTED"] and bool(flags["--sandbox"] or flags["-s"])
        rec["sandbox_modes_in_help"] = [m for m in ("read-only", "workspace-write", "danger-full-access") if m in help_text]
    elif provider == "gemini":
        flags = {f: _flag_present(help_text, f) for f in ("-p", "--prompt", "--yolo", "--approval-mode", "--sandbox", "--output-format", "--include-directories")}
        rec["flags"] = flags
        rec["HEADLESS_SUPPORTED"] = bool(flags["-p"] or flags["--prompt"])
        rec["WRITE_SUPPORTED"] = rec["HEADLESS_SUPPORTED"] and bool(flags["--yolo"] or flags["--approval-mode"])
        rec["READ_ONLY_SUPPORTED"] = rec["HEADLESS_SUPPORTED"] and bool(flags["--sandbox"] or flags["--approval-mode"])
    return rec


def probe_all() -> Dict[str, Dict[str, Any]]:
    return {p: probe_provider(p) for p in PROVIDERS if p != "scripted"}


def _prompt(packet_path: Path, read_only: bool) -> str:
    return (f"You are a disposable research worker. Read the packet file {packet_path} and follow it exactly. "
            f"{'You are READ-ONLY with respect to the repository: write nothing except the report/result files the packet names. ' if read_only else ''}"
            f"When done, write the result card with the command the packet gives, then stop.")


def build_command(provider: str, *, packet_path: Path, worktree: Path, read_only: bool, results_dir: Path, session_id: str,
                  probe: Optional[Dict[str, Any]] = None, scripted_command: Optional[List[str]] = None) -> List[str]:
    """The launch command, using only flags the installed binary printed in --help."""
    if provider == "scripted":
        if not scripted_command:
            raise ProviderError("PROVIDER_CAPABILITY_UNAVAILABLE: scripted provider needs options.scripted_worker (a Python script path)")
        return [*scripted_command, str(packet_path)]
    if provider in ATTENDED_PROVIDERS:
        return []
    rec = probe or probe_provider(provider)
    if not rec.get("AVAILABLE"):
        raise ProviderError(rec.get("error") or f"PROVIDER_CAPABILITY_UNAVAILABLE: {provider}")
    if not rec.get("HEADLESS_SUPPORTED"):
        raise ProviderError(f"PROVIDER_CAPABILITY_UNAVAILABLE: {provider} has no headless mode in --help")
    need = "READ_ONLY_SUPPORTED" if read_only else "WRITE_SUPPORTED"
    if not rec.get(need):
        raise ProviderError(f"PROVIDER_CAPABILITY_UNAVAILABLE: {provider} lacks {need} in --help")
    flags = rec.get("flags") or {}
    binary = rec["binary"]
    prompt = _prompt(packet_path, read_only)
    if provider == "claude":
        cmd = [binary, "-p" if flags.get("-p") else "--print", prompt]
        if flags.get("--output-format"):
            cmd += ["--output-format", "json"]
        if flags.get("--no-session-persistence"):
            cmd += ["--no-session-persistence"]
        if flags.get("--add-dir"):
            cmd += ["--add-dir", str(results_dir)]
        if read_only:
            if flags.get("--allowedTools"):
                # both shell tools: Claude Code on Windows routes commands through its PowerShell tool (DEV-04)
                cmd += ["--allowedTools", "Read", "Grep", "Glob", "Write",
                        "Bash(python scripts/research.py:*)", "Bash(git status:*)", "Bash(git log:*)", "Bash(git diff:*)",
                        "PowerShell(python scripts/research.py:*)", "PowerShell(git status:*)", "PowerShell(git log:*)", "PowerShell(git diff:*)"]
            if flags.get("--disallowedTools"):
                cmd += ["--disallowedTools", "Edit", "NotebookEdit"]
        else:
            if flags.get("--dangerously-skip-permissions"):
                cmd += ["--dangerously-skip-permissions"]
            elif flags.get("--permission-mode"):
                cmd += ["--permission-mode", "acceptEdits"]
        return cmd
    if provider == "codex":
        cmd = [binary, "exec"]
        if flags.get("--cd") or flags.get("-C"):
            cmd += ["--cd" if flags.get("--cd") else "-C", str(worktree)]
        modes = rec.get("sandbox_modes_in_help") or []
        if flags.get("--sandbox") or flags.get("-s"):
            mode = "read-only" if read_only else "workspace-write"
            if mode in modes or not modes:
                cmd += ["--sandbox" if flags.get("--sandbox") else "-s", mode]
        if flags.get("--add-dir"):
            cmd += ["--add-dir", str(results_dir)]
        if flags.get("--skip-git-repo-check"):
            cmd += ["--skip-git-repo-check"]
        if flags.get("--json"):
            cmd += ["--json"]
        cmd += [prompt]
        return cmd
    if provider == "gemini":
        cmd = [binary, "-p" if flags.get("-p") else "--prompt", prompt]
        if not read_only and flags.get("--yolo"):
            cmd += ["--yolo"]
        if flags.get("--include-directories"):
            cmd += ["--include-directories", str(results_dir)]
        return cmd
    raise ProviderError(f"UNKNOWN_PROVIDER: {provider}")


def launch_worker(provider: str, *, role: str, worktree: Path, packet_path: Path, identity: Dict[str, Any], result_path: Path,
                  read_only: bool, timeout_s: float, log_path: Path, results_dir: Path, task_id: str,
                  probe: Optional[Dict[str, Any]] = None, scripted_command: Optional[List[str]] = None) -> LaunchHandle:
    """Start ONE fresh worker process (or prepare an attended packet). ``identity['session_id']`` is a fresh uuid per worker
    so the v3 writer lease is per worker; read-only auditors get the identity but never claim."""
    session_id = str(identity.get("session_id") or uuid.uuid4())
    started = datetime.now(timezone.utc)
    deadline = (started + timedelta(seconds=float(timeout_s))).isoformat()
    env: Dict[str, Optional[str]] = {"NT_RESEARCH_AGENT": str(identity.get("agent") or provider), "NT_RESEARCH_AGENT_SESSION": session_id,
                                     "NT_RESEARCH_SUPERVISOR_TASK": task_id, "NT_RESEARCH_SUPERVISOR_PACKET": str(packet_path),
                                     "NT_RESEARCH_WORKER_READ_ONLY": "1" if read_only else "0"}
    # a worker is a NEW session: never inherit the launching harness's own session markers (they would mis-identify the
    # writer and, for Claude Code, block a nested launch)
    for k in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "GEMINI_CLI_SESSION_ID", "ANTIGRAVITY_SESSION_ID"):
        env[k] = None
    if provider in ATTENDED_PROVIDERS:
        instr = Path(packet_path).with_suffix(".INSTRUCTIONS.md")
        instr.write_text("\n".join([f"# ATTENDED WORKER INSTRUCTION ({provider}) -- task {task_id} ({role})", "",
                                    f"1. Open an attended {provider} session in worktree `{worktree}`.",
                                    f"2. Set NT_RESEARCH_AGENT={env['NT_RESEARCH_AGENT']} and NT_RESEARCH_AGENT_SESSION={session_id} in that session (the Antigravity launcher does this).",
                                    f"3. Tell it: read `{packet_path}` and follow it; it MUST write `{result_path}` via the CLI command in the packet.",
                                    f"4. The supervisor is waiting for that result card (deadline {deadline}).", ""]), encoding="utf-8")
        print(f"ATTENDED_WORKER_REQUIRED {provider} task={task_id} instructions={instr}", flush=True)
        return LaunchHandle(task_id, provider, None, started.isoformat(), deadline, str(result_path), str(packet_path), attended=True, command=[],
                            log_path=str(log_path), session_id=session_id)
    cmd = build_command(provider, packet_path=packet_path, worktree=worktree, read_only=read_only, results_dir=results_dir, session_id=session_id,
                        probe=probe, scripted_command=scripted_command)
    pid = spawn_detached(cmd, cwd=worktree, log_path=log_path, env=env)
    return LaunchHandle(task_id, provider, pid, started.isoformat(), deadline, str(result_path), str(packet_path), attended=False, command=cmd,
                        log_path=str(log_path), session_id=session_id)


def poll(handle: Dict[str, Any]) -> str:
    """'running' | 'exited' | 'attended_waiting' | 'attended_done' -- by pid liveness and result-card presence (restart-safe)."""
    result_exists = Path(handle["result_path"]).is_file()
    if handle.get("attended"):
        return "attended_done" if result_exists else "attended_waiting"
    pid = int(handle.get("pid") or 0)
    return "running" if pid_alive(pid) else "exited"


def kill(handle: Dict[str, Any]) -> bool:
    pid = int(handle.get("pid") or 0)
    return kill_tree(pid) if pid else False


__all__ = ["PROVIDERS", "ATTENDED_PROVIDERS", "ProviderError", "LaunchHandle", "probe_provider", "probe_all", "build_command", "launch_worker",
           "poll", "kill"]

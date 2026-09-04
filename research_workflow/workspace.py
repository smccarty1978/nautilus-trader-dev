"""Study workspaces: one writer, one branch, one sibling worktree, one lease.

``study_new(study_id)``
    * refuses an existing study id / branch / worktree,
    * creates ``study/<id>`` from the current HEAD and a sibling worktree
      ``<worktree_root>/<repo-name>-<id>`` (no junctions: datasets and models resolve through
      the machine-local roots of ``research_workflow.roots``),
    * allocates the run namespace ``studies/<id>/runs/`` and ``_work/`` (gitignored),
    * scaffolds ``studies/<id>/{research_decision.yaml,study.yaml,SPEC.md}`` skeletons,
    * writes a writer lease ``<leases_dir>/<id>.json`` (schema v3, see below) naming the initiating
      writer identity, and refuses if a live lease already names that worktree.

``ws_list()``
    branches, worktrees, owners, leases (live / stale / dead / released), dirty state -- one JSON card.

Leases are process-local facts, never scientific artifacts, but ownership of an active
workspace must outlive the short-lived ``study new`` CLI process that created it: durability
comes from a TTL-bounded renewal window, not from the creator's PID alone.

Lease schema v3 (current)::

    {schema_version: 3, study_id, branch, worktree,
     owner: "<user>@<host>", owner_user, owner_host, owner_agent, owner_session_id,
     created_at_utc, renewed_at_utc,
     holder: {pid, kind: "cli"|"controller", renewed_at_utc}, ttl_seconds, released_at_utc}

Writer identity (``writer_identity()``) is ``owner_user@owner_host`` + ``owner_agent`` +
``owner_session_id``. Several coding agents (Claude, Codex, Antigravity) run under the same OS
user on one machine, so ``user@host`` alone cannot tell writers apart: the agent and the
per-session id do. Resolution order, documented in ``docs/AI_AGENTS.md``:

    NT_RESEARCH_AGENT / NT_RESEARCH_AGENT_SESSION       explicit (set by the agent launcher)
    harness-native environment                          CLAUDECODE + CLAUDE_CODE_SESSION_ID, CODEX_*, ANTIGRAVITY_* / GEMINI_*
    process-tree anchor                                 the harness/terminal process at the top of this shell's ancestry
                                                        (name:pid:create_time) -- stable for one interactive session

Claim rule (``claim_worktree`` / ``check_writer_access``): a ``live`` lease held by a different
writer identity fails closed with ``STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT`` -- a matching
``user@host`` is never enough. The same writer re-entering is idempotent (renews). ``stale`` /
``dead`` / ``released`` leases may be claimed; the claim is serialized by an O_EXCL claim lock so
two simultaneous claims have exactly one winner. Legacy (schema 1/2) leases carry no agent or
session and are therefore never "the same writer": they are cleared by ``ws release --force``
(same OS user; recorded on the lease) or by ``ws list --reclaim`` once stale/dead/released.

The writer lease answers "who may edit this study worktree"; the controller run lock
(``_work/controller/run.lock``, :mod:`research_workflow.governed_controller_v2`) answers "is an
execution of this study already running". Both must pass independently.

States:
  * ``dead``     -- the lease's worktree no longer exists.
  * ``released`` -- ``released_at_utc`` is set (``research ws release <study_id>``).
  * ``live``     -- worktree exists AND (holder pid alive OR now < holder.renewed_at_utc + ttl_seconds).
  * ``stale``    -- worktree exists, holder pid dead AND the ttl window has expired.

``research_workflow.governed_controller_v2.V2StudyController.run()`` renews the lease (kind
``controller``) on every run while it owns the worktree, so a long controller run keeps the
lease ``live`` long after the creating CLI process has exited. Schema-v1 lease files (flat
``pid`` field, no ``holder``) are still read transparently: normalized in memory to
``holder={pid, kind:"cli", renewed_at_utc:created_at_utc}``.
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_workflow.roots import load_config

DEFAULT_LEASE_TTL_SECONDS = 259200   # 72h


class WorkspaceError(RuntimeError):
    pass


def _host() -> str:
    return os.environ.get("COMPUTERNAME") or (os.uname().nodename if hasattr(os, "uname") else "")


def current_owner() -> str:
    return f"{getpass.getuser()}@{_host()}"


# ---------------------------------------------------------------------------
# writer identity: user@host + agent + session
# ---------------------------------------------------------------------------
AGENT_ENV = "NT_RESEARCH_AGENT"                 # claude | codex | antigravity | gemini | human | <any label>
AGENT_SESSION_ENV = "NT_RESEARCH_AGENT_SESSION"  # unique per active coding-agent session (uuid or harness session id)
_HARNESS_SESSION_ENVS = {
    "claude": ("CLAUDE_CODE_SESSION_ID",),
    "codex": ("CODEX_THREAD_ID", "CODEX_SESSION_ID"),
    "antigravity": ("ANTIGRAVITY_SESSION_ID",),
    "gemini": ("GEMINI_CLI_SESSION_ID", "GEMINI_SESSION_ID"),
}
_HARNESS_MARKERS = {
    "claude": ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT"),
    "codex": ("CODEX_SANDBOX", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_SANDBOX_NETWORK_DISABLED"),
    "antigravity": ("ANTIGRAVITY_SESSION_ID", "ANTIGRAVITY_AGENT"),
    "gemini": ("GEMINI_CLI", "GEMINI_CLI_SESSION_ID", "GEMINI_SESSION_ID"),
}
_ANCESTRY_ROOTS = {"explorer.exe", "services.exe", "wininit.exe", "svchost.exe", "systemd", "init", "launchd", "sshd", "sshd.exe"}


def _process_anchor() -> Optional[Dict[str, Any]]:
    """The top-most ancestor of this process below the OS/session root: for a coding agent's shell
    that is the harness (claude.exe, codex, antigravity, ...) or the terminal it runs in. Its
    name:pid:create_time is stable for exactly one interactive session."""
    try:
        import psutil
    except Exception:
        return None
    try:
        chain = []
        p = psutil.Process()
        while p is not None:
            try:
                name = (p.name() or "").lower()
            except Exception:
                break
            if name in _ANCESTRY_ROOTS:
                break
            chain.append((name, int(p.pid), int(p.create_time())))
            p = p.parent()
        if not chain:
            return None
        name, pid, created = chain[-1]
        names = [c[0] for c in chain]
        return {"name": name, "pid": pid, "create_time": created, "ancestry": names}
    except Exception:
        return None


def writer_identity() -> Dict[str, Any]:
    """Resolve the writer identity of the current process: ``{user, host, owner, agent, session_id,
    agent_source, session_source}``. Never raises; always yields a non-empty agent and session_id."""
    user, host = getpass.getuser(), _host()
    agent = (os.environ.get(AGENT_ENV) or "").strip().lower()
    agent_source = "env" if agent else None
    anchor = None
    if not agent:
        for name, markers in _HARNESS_MARKERS.items():
            if any(os.environ.get(m) for m in markers):
                agent, agent_source = name, "harness_env"
                break
    if not agent:
        anchor = _process_anchor()
        if anchor:
            for name in ("claude", "codex", "antigravity", "gemini"):
                if any(name in a for a in anchor["ancestry"]):
                    agent, agent_source = name, "process_tree"
                    break
    if not agent:
        agent, agent_source = "human", "default"
    session = (os.environ.get(AGENT_SESSION_ENV) or "").strip()
    session_source = "env" if session else None
    if not session:
        for var in _HARNESS_SESSION_ENVS.get(agent, ()):
            if os.environ.get(var):
                session, session_source = os.environ[var].strip(), f"harness_env:{var}"
                break
    if not session:
        anchor = anchor or _process_anchor()
        if anchor:
            session, session_source = f"{anchor['name']}:{anchor['pid']}:{anchor['create_time']}", "process_tree"
    if not session:
        session, session_source = f"pid:{os.getpid()}", "pid_fallback"
    return {"user": user, "host": host, "owner": f"{user}@{host}", "agent": agent, "session_id": session,
            "agent_source": agent_source, "session_source": session_source}


AMBIGUOUS_AGENTS = frozenset({"human", "unknown", ""})


def require_agent(identity: Dict[str, Any], expected: Optional[str]) -> Dict[str, Any]:
    """Fail closed when a write-capable agent's identity is not what its instructions require.

    ``expected`` is the agent label the caller claims to be (``--as antigravity``). Raises
    ``WRITER_IDENTITY_AMBIGUOUS`` when the resolved agent is ``human``/``unknown`` (no launcher env, no
    harness marker, no recognizable harness process in the ancestry) and ``WRITER_IDENTITY_MISMATCH``
    when it resolved to a different agent. ``expected=None`` disables the check (humans at a terminal)."""
    if expected is None:
        return identity
    exp = str(expected).strip().lower()
    got = str(identity.get("agent") or "").lower()
    if got in AMBIGUOUS_AGENTS:
        raise WorkspaceError(f"WRITER_IDENTITY_AMBIGUOUS: this shell resolves as agent={got or 'unknown'!r} "
                              f"(agent_source={identity.get('agent_source')}); a write-capable {exp} session must be launched with "
                              f"{AGENT_ENV}={exp} (and {AGENT_SESSION_ENV}=<unique per session>) -- see docs/AI_AGENTS.md 'Writer identity'. Not writing.")
    if got != exp:
        raise WorkspaceError(f"WRITER_IDENTITY_MISMATCH: this shell resolves as agent={got!r} (agent_source={identity.get('agent_source')}), "
                              f"not {exp!r}; refusing to write under another agent's identity.")
    return identity


def _identity_from(owner: Optional[str], identity: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge an explicit legacy ``owner`` string (user@host) with a resolved identity."""
    ident = dict(identity or writer_identity())
    if owner:
        ident["owner"] = owner
        if "@" in owner:
            ident["user"], ident["host"] = owner.split("@", 1)
    return ident


def same_writer(lease: Dict[str, Any], identity: Dict[str, Any]) -> bool:
    """True iff the lease is held by exactly this writer: same user@host AND agent AND session.
    Legacy leases (no session) are never the same writer -- fail closed."""
    if not lease.get("owner_session_id"):
        return False
    return (str(lease.get("owner")) == str(identity["owner"]) and str(lease.get("owner_agent")) == str(identity["agent"])
            and str(lease.get("owner_session_id")) == str(identity["session_id"]))


def _writer_label(rec: Dict[str, Any]) -> str:
    return f"{rec.get('owner')} agent={rec.get('owner_agent')} session={rec.get('owner_session_id')}"


def _git(args: List[str], cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:
        try:
            os.kill(int(pid), 0)
            return True
        except Exception:
            return False


def _worktrees(repo_root: Path) -> List[Dict[str, Any]]:
    out, cur = [], {}
    for line in _git(["worktree", "list", "--porcelain"], repo_root).splitlines() + [""]:
        if not line:
            if cur:
                out.append({"path": cur.get("worktree"), "head": cur.get("HEAD"), "branch": (cur.get("branch") or "").replace("refs/heads/", "") or "(detached)"})
            cur = {}
            continue
        k, _, v = line.partition(" ")
        cur[k] = v
    return out


def leases_dir(config=None) -> Path:
    cfg = config if config is not None else load_config()
    return Path(cfg.leases_dir)


def _normalize(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a lease record (on-disk schema v1 or v2) to an in-memory v2 shape. Never
    rewrites the file -- callers that mutate call ``_atomic_write`` explicitly."""
    out = dict(rec)
    if not isinstance(out.get("holder"), dict):
        # schema v1: flat {pid, owner, created_at_utc, ...} -- treat pid as the holder, kind "cli"
        out["schema_version"] = out.get("schema_version", 1)
        out["holder"] = {"pid": out.get("pid"), "kind": "cli", "renewed_at_utc": out.get("created_at_utc")}
    else:
        out.setdefault("schema_version", 2)
    out.setdefault("ttl_seconds", DEFAULT_LEASE_TTL_SECONDS)
    out.setdefault("released_at_utc", None)
    # schema v3 identity fields; legacy (v1/v2) leases carry no agent/session -> never "the same writer"
    owner = str(out.get("owner") or "")
    user, _, host = owner.partition("@")
    out.setdefault("owner_user", user or None)
    out.setdefault("owner_host", host or None)
    out.setdefault("owner_agent", "legacy" if int(out.get("schema_version") or 1) < 3 else None)
    out.setdefault("owner_session_id", None)
    out.setdefault("renewed_at_utc", (out.get("holder") or {}).get("renewed_at_utc") or out.get("created_at_utc"))
    return out


def lease_state(rec: Dict[str, Any]) -> str:
    """dead (worktree gone) > released (released_at_utc set) > live (holder pid alive, or the
    ttl-bounded renewal window has not yet expired) > stale (neither)."""
    wt = Path(str(rec.get("worktree", "")))
    if not wt.is_dir():
        return "dead"
    if rec.get("released_at_utc"):
        return "released"
    holder = rec.get("holder") or {}
    pid = int(holder.get("pid") or 0)
    alive = _pid_alive(pid) if pid else False
    if alive:
        return "live"
    ttl = int(rec.get("ttl_seconds") or DEFAULT_LEASE_TTL_SECONDS)
    renewed_raw = holder.get("renewed_at_utc") or rec.get("created_at_utc")
    try:
        renewed = datetime.fromisoformat(str(renewed_raw))
    except (TypeError, ValueError):
        return "stale"
    now = datetime.now(timezone.utc)
    if renewed.tzinfo is None:
        renewed = renewed.replace(tzinfo=timezone.utc)
    return "live" if now < renewed + timedelta(seconds=ttl) else "stale"


def read_leases(config=None) -> List[Dict[str, Any]]:
    d = leases_dir(config)
    rows = []
    if not d.is_dir():
        return rows
    for p in sorted(d.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rec = _normalize(rec)
        rec["state"] = lease_state(rec)
        rec["lease_path"] = str(p)
        rows.append(rec)
    return rows


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _lease_payload(study_id: str, branch: str, worktree: Path, ident: Dict[str, Any], cfg, *, kind: str = "cli") -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    ttl = int(getattr(cfg, "lease_ttl_seconds", DEFAULT_LEASE_TTL_SECONDS) or DEFAULT_LEASE_TTL_SECONDS)
    return {"schema_version": 3, "study_id": study_id, "branch": branch, "worktree": str(Path(worktree).resolve()),
            "owner": ident["owner"], "owner_user": ident["user"], "owner_host": ident["host"],
            "owner_agent": ident["agent"], "owner_session_id": ident["session_id"],
            "created_at_utc": now, "renewed_at_utc": now,
            "holder": {"pid": os.getpid(), "kind": kind, "renewed_at_utc": now},
            "ttl_seconds": ttl, "released_at_utc": None}


def _write_lease(study_id: str, branch: str, worktree: Path, config=None, owner: Optional[str] = None,
                 identity: Optional[Dict[str, Any]] = None) -> Path:
    """Create the writer lease for a NEW study worktree. A live lease already naming that worktree is
    refused (``WRITER_LEASE_HELD``) unless it is this same writer's lease for this same study
    (idempotent re-entry). Use ``claim_worktree`` for an existing study."""
    from research_workflow.locks import acquire_exclusive
    cfg = config if config is not None else load_config()
    ident = _identity_from(owner, identity)
    d = leases_dir(cfg); d.mkdir(parents=True, exist_ok=True)
    worktree = Path(worktree)
    for lease in read_leases(cfg):
        if Path(str(lease.get("worktree", ""))).resolve() == worktree.resolve() and lease["state"] == "live":
            if lease.get("study_id") == study_id and same_writer(lease, ident):
                return Path(lease["lease_path"])
            raise WorkspaceError(f"WRITER_LEASE_HELD: worktree {worktree} already has a live writer lease "
                                  f"({_writer_label(lease)}, pid {(lease.get('holder') or {}).get('pid')})")
    p = d / f"{study_id}.json"
    payload = _lease_payload(study_id, branch, worktree, ident, cfg)
    # a leftover lease file for this exact study_id (e.g. a prior failed/reclaimed attempt) is
    # always safe to overwrite here: uniqueness of the *worktree* was just checked above.
    result = acquire_exclusive(p, payload, is_stale=lambda existing, mtime: True, max_attempts=1)
    if not result.acquired:
        raise WorkspaceError(f"LEASE_FILE_EXISTS: {p}")
    return p


def renew_lease(worktree: Path, *, owner: str, pid: int, kind: str = "controller", config=None,
                identity: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Refresh ``holder`` + ``renewed_at_utc`` on the lease naming ``worktree``, if any.

    Raises ``WorkspaceError`` if a lease exists for that worktree but is held by another writer
    (``STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT``; also a legacy lease, which has no session identity
    and can only be released/reclaimed); returns ``None`` if no lease names that worktree."""
    cfg = config if config is not None else load_config()
    ident = _identity_from(owner, identity)
    worktree = Path(worktree).resolve()
    for lease in read_leases(cfg):
        if Path(str(lease.get("worktree", ""))).resolve() != worktree:
            continue
        if not same_writer(lease, ident):
            raise WorkspaceError(f"STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT (WRITER_LEASE_HELD_BY_OTHER): {worktree} is leased to "
                                  f"{_writer_label(lease)}, not {ident['owner']} agent={ident['agent']} session={ident['session_id']}")
        p = Path(lease["lease_path"])
        raw = _normalize(json.loads(p.read_text(encoding="utf-8")))
        now = datetime.now(timezone.utc).isoformat()
        raw["schema_version"] = 3
        raw["holder"] = {"pid": pid, "kind": kind, "renewed_at_utc": now}
        raw["renewed_at_utc"] = now
        raw["released_at_utc"] = None
        raw.setdefault("ttl_seconds", int(getattr(cfg, "lease_ttl_seconds", DEFAULT_LEASE_TTL_SECONDS) or DEFAULT_LEASE_TTL_SECONDS))
        _atomic_write(p, raw)
        out = dict(raw); out["state"] = lease_state(raw); out["lease_path"] = str(p)
        return out
    return None


def release_lease(study_id: str, *, owner: str, config=None, identity: Optional[Dict[str, Any]] = None, force: bool = False) -> Dict[str, Any]:
    """Explicit release (``research ws release <study_id>``): allowed for the same writer identity.
    ``force`` (``--force``) lets the same OS user release a lease held by another agent/session or a
    legacy lease (e.g. a dead session that never released); the forced release is recorded on the lease."""
    cfg = config if config is not None else load_config()
    ident = _identity_from(owner, identity)
    p = leases_dir(cfg) / f"{study_id}.json"
    if not p.is_file():
        raise WorkspaceError(f"LEASE_NOT_FOUND: {study_id}")
    raw = _normalize(json.loads(p.read_text(encoding="utf-8")))
    if not same_writer(raw, ident):
        if not force:
            raise WorkspaceError(f"LEASE_RELEASE_REFUSED: {study_id} is leased to {_writer_label(raw)}, not "
                                  f"{ident['owner']} agent={ident['agent']} session={ident['session_id']} (same user may pass --force)")
        if str(raw.get("owner_user") or str(raw.get("owner", "")).partition("@")[0]) != str(ident["user"]):
            raise WorkspaceError(f"LEASE_RELEASE_REFUSED: {study_id} is leased to {raw.get('owner')}, not {ident['owner']} (--force needs the same OS user)")
        raw["forced_release_by"] = {"owner": ident["owner"], "agent": ident["agent"], "session_id": ident["session_id"]}
    raw["schema_version"] = 3
    raw["released_at_utc"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(p, raw)
    out = dict(raw); out["state"] = "released"; out["lease_path"] = str(p)
    return out


def _find_study_worktree(study_id: str, repo_root: Path, cfg) -> Optional[Path]:
    """The worktree of ``study/<study_id>`` from ``git worktree list``, else the conventional path."""
    try:
        for wt in _worktrees(repo_root):
            if wt.get("branch") == f"study/{study_id}" and wt.get("path"):
                return Path(wt["path"]).resolve()
    except WorkspaceError:
        pass
    wt_root = Path(cfg.worktree_root) if getattr(cfg, "worktree_root", None) else Path(repo_root).parent
    cand = wt_root / f"{Path(repo_root).name}-{study_id}"
    return cand.resolve() if cand.is_dir() else None


def claim_worktree(study_id: str, *, repo_root: Path, config=None, identity: Optional[Dict[str, Any]] = None,
                   expect_agent: Optional[str] = None) -> Dict[str, Any]:
    """``research ws claim <study_id>``: take writer ownership of an existing study worktree.

    * live lease, same writer identity      -> idempotent (renewed), ``result: "already_owner"``
    * live lease, another writer            -> ``STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT`` (never a same-user takeover)
    * stale / released lease, or no lease   -> claimed, ``result: "claimed"`` (``reclaimed_from`` names the prior writer)
    * dead lease (worktree gone)            -> ``WORKTREE_MISSING``

    Serialized per study by an O_EXCL claim lock (``<leases_dir>/<study_id>.claim``): of two simultaneous
    claims exactly one wins; the loser re-reads and sees the winner's live lease."""
    from research_workflow.locks import acquire_exclusive
    cfg = config if config is not None else load_config()
    ident = require_agent(dict(identity or writer_identity()), expect_agent)
    repo_root = Path(repo_root).resolve()
    d = leases_dir(cfg); d.mkdir(parents=True, exist_ok=True)
    lock = d / f"{study_id}.claim"
    lock_payload = {"pid": os.getpid(), "owner": ident["owner"], "agent": ident["agent"], "session_id": ident["session_id"],
                    "at_utc": datetime.now(timezone.utc).isoformat()}

    def _lock_stale(existing: Optional[dict], mtime: float) -> bool:
        pid = int((existing or {}).get("pid") or 0)
        return (time.time() - mtime) > 30 or not (pid and _pid_alive(pid))

    got = acquire_exclusive(lock, lock_payload, is_stale=_lock_stale, max_attempts=2)
    if not got.acquired:
        raise WorkspaceError(f"STUDY_CLAIM_IN_PROGRESS: {study_id} is being claimed by {(got.payload or {}).get('agent')} "
                              f"session={(got.payload or {}).get('session_id')}; retry")
    try:
        p = d / f"{study_id}.json"
        existing = next((l for l in read_leases(cfg) if l.get("study_id") == study_id), None)
        worktree = Path(str(existing["worktree"])).resolve() if existing else _find_study_worktree(study_id, repo_root, cfg)
        if worktree is None or not worktree.is_dir():
            raise WorkspaceError(f"WORKTREE_MISSING: no worktree for study/{study_id} (create it with `research study new`)")
        if existing is not None and str(existing.get("study_id")) != study_id:
            raise WorkspaceError(f"STUDY_ID_MISMATCH: lease {p} names {existing.get('study_id')!r}")
        branch = (existing or {}).get("branch") or f"study/{study_id}"
        if existing is not None and existing["state"] == "live":
            if same_writer(existing, ident):
                out = renew_lease(worktree, owner=ident["owner"], pid=os.getpid(), kind="cli", config=cfg, identity=ident)
                return {"result": "already_owner", "study_id": study_id, "worktree": str(worktree), "lease": out}
            raise WorkspaceError(f"STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT: {study_id} ({worktree}) has a live writer lease held by "
                                  f"{_writer_label(existing)}; you are {ident['owner']} agent={ident['agent']} session={ident['session_id']}. "
                                  "A matching user@host is not ownership. Wait, take another study, or have the owner run `research ws release`.")
        # another live lease on the same worktree under a different study id is a hard conflict too
        for other in read_leases(cfg):
            if other.get("study_id") != study_id and Path(str(other.get("worktree", ""))).resolve() == worktree and other["state"] == "live":
                raise WorkspaceError(f"STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT: {worktree} is leased for study {other.get('study_id')!r} by {_writer_label(other)}")
        payload = _lease_payload(study_id, branch, worktree, ident, cfg)
        if existing is not None:
            payload["reclaimed_from"] = {"owner": existing.get("owner"), "agent": existing.get("owner_agent"), "session_id": existing.get("owner_session_id"),
                                         "state": existing["state"], "released_at_utc": existing.get("released_at_utc")}
        _atomic_write(p, payload)
        out = dict(payload); out["state"] = lease_state(payload); out["lease_path"] = str(p)
        return {"result": "claimed", "study_id": study_id, "worktree": str(worktree), "lease": out,
                "reclaimed_from": payload.get("reclaimed_from")}
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def check_writer_access(worktree: Path, *, config=None, identity: Optional[Dict[str, Any]] = None, renew: bool = True,
                        pid: Optional[int] = None, kind: str = "controller") -> Optional[Dict[str, Any]]:
    """Gate every WRITE-capable operation on an existing study worktree.

    Returns ``None`` when no lease names the worktree (main checkout, ad-hoc worktree: unaffected) or the
    lease is not live; returns the (renewed) lease when this writer holds it; raises
    ``STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT`` when a live lease belongs to another writer identity."""
    cfg = config if config is not None else load_config()
    ident = dict(identity or writer_identity())
    worktree = Path(worktree).resolve()
    lease = next((l for l in read_leases(cfg) if Path(str(l.get("worktree", ""))).resolve() == worktree), None)
    if lease is None or lease["state"] != "live":
        return None
    if not same_writer(lease, ident):
        raise WorkspaceError(f"STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT: {worktree} is leased to {_writer_label(lease)}; "
                              f"you are {ident['owner']} agent={ident['agent']} session={ident['session_id']}")
    if renew:
        return renew_lease(worktree, owner=ident["owner"], pid=pid or os.getpid(), kind=kind, config=cfg, identity=ident)
    return lease


def _skeletons(study_dir: Path, study_id: str, dataset_id: str, question: str) -> List[Path]:
    study_dir.mkdir(parents=True, exist_ok=True)
    (study_dir / "runs").mkdir(exist_ok=True); (study_dir / "_work").mkdir(exist_ok=True)
    decision = study_dir / "research_decision.yaml"
    decision.write_text(f"""# Authoritative decision contract (research_decision.yaml > SPEC.md > study.yaml > compiled_study.json > code)
study_id: {study_id}
research_question: {json.dumps(question)}
status: DRAFT
dataset_id: {dataset_id}
terminal_decisions: {{}}
""", encoding="utf-8")
    spec = study_dir / "SPEC.md"
    spec.write_text(f"# {study_id}\n\nDerived from `research_decision.yaml`. Question: {question}\n\n## Population\n\n## Target\n\n## Features\n\n## Chronology\n\n## Deliverables Manifest\n", encoding="utf-8")
    study_yaml = study_dir / "study.yaml"
    study_yaml.write_text(f"""# Platform-v2 study: a composition of registered primitives (see `research cap list`).
# Sections: study, streams, population, context, triggers, features, outcome, chronology, model.
# Compile with `research study compile --study studies/{study_id}`; a typed CapabilityGap names what is missing.
study:
  id: {study_id}
  tier: 2
  question: {json.dumps(question)}
streams:
  - {{dataset: {dataset_id}, timeframes: [1s, 1m]}}
context:
  regime_1m:     {{tracker: regime.dual_ema, timeframe: 1m}}
  excursion:     {{tracker: regime.excursion, bars: 1s, regime: regime_1m}}
  regime_bar_5m: {{tracker: regime_bar.calendar_bucket, bucket: 5m, bars: 1m, regime: regime_1m}}
population:
  session: RTH
  cadence: {{every: 5s, anchor: regime_1m.start_ns, max_age: 1800s}}
  qualify: "excursion.frozen_atr > 0 and regime_1m.age_s >= 120s and excursion.mfe_atr >= 1.0 and features.structural_snapshot_ready"
  direction: regime_1m.dir
  anchor_identity: regime_1m.start_ns
triggers: every_candidate
features:
  instances:
    - {{feature: regime_efficiency, over: {{timeframe: [1m, 5m]}}, context: prior}}
    - {{feature: rolling_giveback_atr, window: 300s, update_every: 1s}}
  metadata:
    regime_age_seconds: regime_1m.age_s
    triggering_1s_ts_init: epoch.T
  bindings:
    completed_5m: {{tracker: regime_bar_5m, ready_gate: false}}
    snapshot: {{atr: regime_1m.atr, family_a_atr: excursion.frozen_atr, episode_state: {{prevailing_direction: regime_1m.dir}}}}
outcome:
  kind: label
  event: regime_1m.flipped
  horizon: 300s
  direction: regime_1m.dir
  session_end: censor
chronology:
  train: [2021, 2022, 2023]
  dev: [2024]
  prohibited: [2025, 2026]
  authorized_dates: []        # smoke day(s), e.g. ['2023-10-02']
model: none
""", encoding="utf-8")
    return [decision, spec, study_yaml]


def study_new(study_id: str, *, repo_root: Path, question_file: Optional[str] = None, dataset_id: str = "NQ_1S_V2_GLOBEX",
              config=None, owner: Optional[str] = None, expect_agent: Optional[str] = None) -> Dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    require_agent(_identity_from(owner, None), expect_agent)
    if not study_id or any(ch in study_id for ch in " /\\:") or study_id.startswith("."):
        raise WorkspaceError(f"STUDY_ID_INVALID: {study_id!r}")
    cfg = config if config is not None else load_config()
    branch = f"study/{study_id}"
    if (repo_root / "studies" / study_id).exists():
        raise WorkspaceError(f"STUDY_EXISTS: studies/{study_id}")
    if subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=str(repo_root)).returncode == 0:
        raise WorkspaceError(f"BRANCH_EXISTS: {branch}")
    wt_root = Path(cfg.worktree_root) if cfg.worktree_root else repo_root.parent
    worktree = wt_root / f"{repo_root.name}-{study_id}"
    if worktree.exists():
        raise WorkspaceError(f"WORKTREE_EXISTS: {worktree}")
    if _git(["status", "--porcelain"], repo_root).strip():
        raise WorkspaceError("SOURCE_WORKTREE_DIRTY: commit or stash before creating a study workspace")
    head = _git(["rev-parse", "HEAD"], repo_root).strip()
    question = Path(question_file).read_text(encoding="utf-8").strip() if question_file else f"Research question for {study_id} (edit research_decision.yaml)"
    ident = _identity_from(owner, None)
    _git(["worktree", "add", "-b", branch, str(worktree), head], repo_root)
    files = _skeletons(worktree / "studies" / study_id, study_id, dataset_id, question)
    lease = _write_lease(study_id, branch, worktree, cfg, owner=owner, identity=ident)
    return {"study_id": study_id, "branch": branch, "worktree": str(worktree), "base_commit": head, "dataset_id": dataset_id,
            "writer": {"owner": ident["owner"], "agent": ident["agent"], "session_id": ident["session_id"],
                       "agent_source": ident["agent_source"], "session_source": ident["session_source"]},
            "catalog_resolution": "configured_roots" if cfg.active else "legacy_repo_relative (no ~/.nt_research/config.yaml; a manual junction to data/catalog/<id> is the documented fallback)",
            "model_root": str(cfg.model_root) if cfg.model_root else None, "lease": str(lease), "scaffold": [str(f.relative_to(worktree)).replace("\\", "/") for f in files],
            "next": f"cd \"{worktree}\" && python scripts/research.py study compile --study studies/{study_id}"}


def ws_list(*, repo_root: Path, config=None, reclaim: bool = False) -> Dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    cfg = config if config is not None else load_config()
    leases = read_leases(cfg)
    worktrees = _worktrees(repo_root)
    by_wt = {Path(str(l.get("worktree", ""))).resolve(): l for l in leases}
    rows = []
    for wt in worktrees:
        path = Path(wt["path"]).resolve()
        dirty = _git(["status", "--porcelain"], path).strip().splitlines() if path.is_dir() else []
        lease = by_wt.get(path)
        rows.append({"worktree": str(path), "branch": wt["branch"], "head": (wt["head"] or "")[:12], "dirty_files": len(dirty),
                     "owner": lease.get("owner") if lease else None, "lease_state": lease.get("state") if lease else None,
                     "lease_study": lease.get("study_id") if lease else None,
                     "owner_agent": lease.get("owner_agent") if lease else None,
                     "owner_session_id": lease.get("owner_session_id") if lease else None})
    reclaimed = []
    if reclaim:
        for l in leases:
            if l["state"] in {"stale", "dead", "released"}:
                Path(l["lease_path"]).unlink(missing_ok=True); reclaimed.append(l["study_id"])
    branches = [b.strip().lstrip("* ").strip() for b in _git(["branch", "--list"], repo_root).splitlines() if b.strip()]
    me = writer_identity()
    return {"repo": str(repo_root), "identity": {"owner": me["owner"], "agent": me["agent"], "session_id": me["session_id"]},
            "worktrees": rows,
            "leases": [{k: l.get(k) for k in ("study_id", "branch", "worktree", "owner", "owner_agent", "owner_session_id", "state", "created_at_utc", "renewed_at_utc")} for l in leases],
            "stale_or_dead_leases": [l["study_id"] for l in leases if l["state"] != "live"], "reclaimed": reclaimed,
            "branches": {"count": len(branches), "study": sorted(b for b in branches if b.startswith("study/")), "other": sorted(b for b in branches if not b.startswith("study/"))}}


__all__ = ["WorkspaceError", "study_new", "ws_list", "read_leases", "leases_dir", "renew_lease", "release_lease", "current_owner", "lease_state",
           "writer_identity", "same_writer", "claim_worktree", "check_writer_access", "require_agent", "AGENT_ENV", "AGENT_SESSION_ENV"]

"""Study workspaces: one writer, one branch, one sibling worktree, one lease.

``study_new(study_id)``
    * refuses an existing study id / branch / worktree,
    * creates ``study/<id>`` from the current HEAD and a sibling worktree
      ``<worktree_root>/<repo-name>-<id>`` (no junctions: datasets and models resolve through
      the machine-local roots of ``research_workflow.roots``),
    * allocates the run namespace ``studies/<id>/runs/`` and ``_work/`` (gitignored),
    * scaffolds ``studies/<id>/{research_decision.yaml,study.yaml,SPEC.md}`` skeletons,
    * writes a writer lease ``<leases_dir>/<id>.json`` (schema v2, see below) and refuses if a
      live lease already names that worktree.

``ws_list()``
    branches, worktrees, owners, leases (live / stale / dead / released), dirty state -- one JSON card.

Leases are process-local facts, never scientific artifacts, but ownership of an active
workspace must outlive the short-lived ``study new`` CLI process that created it: durability
comes from a TTL-bounded renewal window, not from the creator's PID alone.

Lease schema v2 (current)::

    {schema_version: 2, study_id, branch, worktree, owner, created_at_utc,
     holder: {pid, kind: "cli"|"controller", renewed_at_utc}, ttl_seconds, released_at_utc}

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_workflow.roots import load_config

DEFAULT_LEASE_TTL_SECONDS = 259200   # 72h


class WorkspaceError(RuntimeError):
    pass


def current_owner() -> str:
    host = os.environ.get("COMPUTERNAME") or (os.uname().nodename if hasattr(os, "uname") else "")
    return f"{getpass.getuser()}@{host}"


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
    if isinstance(out.get("holder"), dict):
        out.setdefault("schema_version", 2)
        out.setdefault("ttl_seconds", DEFAULT_LEASE_TTL_SECONDS)
        out.setdefault("released_at_utc", None)
        return out
    # schema v1: flat {pid, owner, created_at_utc, ...} -- treat pid as the holder, kind "cli"
    out["schema_version"] = out.get("schema_version", 1)
    out["holder"] = {"pid": out.get("pid"), "kind": "cli", "renewed_at_utc": out.get("created_at_utc")}
    out.setdefault("ttl_seconds", DEFAULT_LEASE_TTL_SECONDS)
    out.setdefault("released_at_utc", None)
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


def _write_lease(study_id: str, branch: str, worktree: Path, config=None, owner: Optional[str] = None) -> Path:
    from research_workflow.locks import acquire_exclusive
    cfg = config if config is not None else load_config()
    d = leases_dir(cfg); d.mkdir(parents=True, exist_ok=True)
    for lease in read_leases(cfg):
        if Path(str(lease.get("worktree", ""))).resolve() == worktree.resolve() and lease["state"] == "live":
            raise WorkspaceError(f"WRITER_LEASE_HELD: worktree {worktree} already has a live writer lease "
                                  f"({lease.get('owner')}, pid {(lease.get('holder') or {}).get('pid')})")
    p = d / f"{study_id}.json"
    now = datetime.now(timezone.utc).isoformat()
    ttl = int(getattr(cfg, "lease_ttl_seconds", DEFAULT_LEASE_TTL_SECONDS) or DEFAULT_LEASE_TTL_SECONDS)
    payload = {"schema_version": 2, "study_id": study_id, "branch": branch, "worktree": str(worktree.resolve()),
               "owner": owner or current_owner(), "created_at_utc": now,
               "holder": {"pid": os.getpid(), "kind": "cli", "renewed_at_utc": now},
               "ttl_seconds": ttl, "released_at_utc": None}
    # a leftover lease file for this exact study_id (e.g. a prior failed/reclaimed attempt) is
    # always safe to overwrite here: uniqueness of the *worktree* was just checked above.
    result = acquire_exclusive(p, payload, is_stale=lambda existing, mtime: True, max_attempts=1)
    if not result.acquired:
        raise WorkspaceError(f"LEASE_FILE_EXISTS: {p}")
    return p


def renew_lease(worktree: Path, *, owner: str, pid: int, kind: str = "controller", config=None) -> Optional[Dict[str, Any]]:
    """Refresh ``holder`` + ``renewed_at_utc`` on the lease naming ``worktree``, if any.

    Raises ``WorkspaceError`` if a lease exists for that worktree but is owned by someone else;
    returns ``None`` if no lease names that worktree (nothing to renew, proceed unchanged)."""
    cfg = config if config is not None else load_config()
    worktree = Path(worktree).resolve()
    for lease in read_leases(cfg):
        if Path(str(lease.get("worktree", ""))).resolve() != worktree:
            continue
        if lease.get("owner") != owner:
            raise WorkspaceError(f"WRITER_LEASE_HELD_BY_OTHER: {worktree} is leased to {lease.get('owner')}, not {owner}")
        p = Path(lease["lease_path"])
        raw = _normalize(json.loads(p.read_text(encoding="utf-8")))
        raw["schema_version"] = 2
        raw["holder"] = {"pid": pid, "kind": kind, "renewed_at_utc": datetime.now(timezone.utc).isoformat()}
        raw["released_at_utc"] = None
        raw.setdefault("ttl_seconds", int(getattr(cfg, "lease_ttl_seconds", DEFAULT_LEASE_TTL_SECONDS) or DEFAULT_LEASE_TTL_SECONDS))
        _atomic_write(p, raw)
        out = dict(raw); out["state"] = lease_state(raw); out["lease_path"] = str(p)
        return out
    return None


def release_lease(study_id: str, *, owner: str, config=None) -> Dict[str, Any]:
    """Explicit release (``research ws release <study_id>``): allowed only for the owner."""
    cfg = config if config is not None else load_config()
    p = leases_dir(cfg) / f"{study_id}.json"
    if not p.is_file():
        raise WorkspaceError(f"LEASE_NOT_FOUND: {study_id}")
    raw = _normalize(json.loads(p.read_text(encoding="utf-8")))
    if raw.get("owner") != owner:
        raise WorkspaceError(f"LEASE_RELEASE_REFUSED: {study_id} is leased to {raw.get('owner')}, not {owner}")
    raw["schema_version"] = 2
    raw["released_at_utc"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(p, raw)
    out = dict(raw); out["state"] = "released"; out["lease_path"] = str(p)
    return out


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


def study_new(study_id: str, *, repo_root: Path, question_file: Optional[str] = None, dataset_id: str = "NQ_v0_2020_2026",
              config=None, owner: Optional[str] = None) -> Dict[str, Any]:
    repo_root = Path(repo_root).resolve()
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
    _git(["worktree", "add", "-b", branch, str(worktree), head], repo_root)
    files = _skeletons(worktree / "studies" / study_id, study_id, dataset_id, question)
    lease = _write_lease(study_id, branch, worktree, cfg, owner=owner)
    return {"study_id": study_id, "branch": branch, "worktree": str(worktree), "base_commit": head, "dataset_id": dataset_id,
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
                     "lease_study": lease.get("study_id") if lease else None})
    reclaimed = []
    if reclaim:
        for l in leases:
            if l["state"] in {"stale", "dead", "released"}:
                Path(l["lease_path"]).unlink(missing_ok=True); reclaimed.append(l["study_id"])
    branches = [b.strip().lstrip("* ").strip() for b in _git(["branch", "--list"], repo_root).splitlines() if b.strip()]
    return {"repo": str(repo_root), "worktrees": rows, "leases": [{k: l.get(k) for k in ("study_id", "branch", "worktree", "owner", "pid", "state", "created_at_utc")} for l in leases],
            "stale_or_dead_leases": [l["study_id"] for l in leases if l["state"] != "live"], "reclaimed": reclaimed,
            "branches": {"count": len(branches), "study": sorted(b for b in branches if b.startswith("study/")), "other": sorted(b for b in branches if not b.startswith("study/"))}}


__all__ = ["WorkspaceError", "study_new", "ws_list", "read_leases", "leases_dir", "renew_lease", "release_lease", "current_owner", "lease_state"]

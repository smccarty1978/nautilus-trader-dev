"""Study workspaces: one writer, one branch, one sibling worktree, one lease.

``study_new(study_id)``
    * refuses an existing study id / branch / worktree,
    * creates ``study/<id>`` from the current HEAD and a sibling worktree
      ``<worktree_root>/<repo-name>-<id>`` (no junctions: datasets and models resolve through
      the machine-local roots of ``research_workflow.roots``),
    * allocates the run namespace ``studies/<id>/runs/`` and ``_work/`` (gitignored),
    * scaffolds ``studies/<id>/{research_decision.yaml,study.yaml,SPEC.md}`` skeletons,
    * writes a writer lease ``<leases_dir>/<id>.json`` {study, branch, worktree, pid, owner, created}
      and refuses if a live lease already names that worktree.

``ws_list()``
    branches, worktrees, owners, leases (live / stale / dead), dirty state -- one JSON card.

Leases are process-local facts, never scientific artifacts. A lease whose PID is dead is
``stale`` and may be reclaimed by ``study_new``/``ws_list --reclaim``; a lease is ``dead`` when
its worktree no longer exists.
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_workflow.roots import load_config


class WorkspaceError(RuntimeError):
    pass


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
        alive = _pid_alive(int(rec.get("pid", -1)))
        wt = Path(str(rec.get("worktree", "")))
        rec["state"] = "dead" if not wt.is_dir() else ("live" if alive else "stale")
        rec["lease_path"] = str(p)
        rows.append(rec)
    return rows


def _write_lease(study_id: str, branch: str, worktree: Path, config=None, owner: Optional[str] = None) -> Path:
    d = leases_dir(config); d.mkdir(parents=True, exist_ok=True)
    for lease in read_leases(config):
        if Path(str(lease.get("worktree", ""))).resolve() == worktree.resolve() and lease["state"] == "live":
            raise WorkspaceError(f"WRITER_LEASE_HELD: worktree {worktree} already has a live writer lease ({lease.get('owner')}, pid {lease.get('pid')})")
    p = d / f"{study_id}.json"
    payload = {"schema_version": 1, "study_id": study_id, "branch": branch, "worktree": str(worktree.resolve()), "pid": os.getpid(),
               "owner": owner or f"{getpass.getuser()}@{os.environ.get('COMPUTERNAME') or os.uname().nodename if hasattr(os, 'uname') else getpass.getuser()}",
               "created_at_utc": datetime.now(timezone.utc).isoformat()}
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p


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
            if l["state"] in {"stale", "dead"}:
                Path(l["lease_path"]).unlink(missing_ok=True); reclaimed.append(l["study_id"])
    branches = [b.strip().lstrip("* ").strip() for b in _git(["branch", "--list"], repo_root).splitlines() if b.strip()]
    return {"repo": str(repo_root), "worktrees": rows, "leases": [{k: l.get(k) for k in ("study_id", "branch", "worktree", "owner", "pid", "state", "created_at_utc")} for l in leases],
            "stale_or_dead_leases": [l["study_id"] for l in leases if l["state"] != "live"], "reclaimed": reclaimed,
            "branches": {"count": len(branches), "study": sorted(b for b in branches if b.startswith("study/")), "other": sorted(b for b in branches if not b.startswith("study/"))}}


__all__ = ["WorkspaceError", "study_new", "ws_list", "read_leases", "leases_dir"]

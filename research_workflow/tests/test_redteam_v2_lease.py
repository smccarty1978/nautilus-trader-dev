"""Red-team packet C2: the writer lease must record durable *ownership* of an active workspace,
not the short-lived ``study new`` CLI process's PID. Before this fix, ``read_leases`` treated
a lease as dead the instant the creating CLI exited, so ``ws list --reclaim`` deleted it and a
second writer could take the same worktree while the first was still working."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from research_workflow.roots import RootConfig
from research_workflow.workspace import (WorkspaceError, _write_lease, read_leases, release_lease, renew_lease)


def _cfg(tmp_path: Path, ttl: int = 300) -> RootConfig:
    leases = tmp_path / "leases"
    leases.mkdir()
    return RootConfig(None, (), None, leases, None, ttl)


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _mk_worktree(tmp_path: Path, name: str = "wt") -> Path:
    wt = tmp_path / name
    wt.mkdir()
    return wt


def _lease_path(cfg: RootConfig, study_id: str) -> Path:
    return cfg.leases_dir / f"{study_id}.json"


def _set_holder(cfg: RootConfig, study_id: str, *, pid: int, renewed_at_utc: str) -> None:
    p = _lease_path(cfg, study_id)
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["holder"]["pid"] = pid
    raw["holder"]["renewed_at_utc"] = renewed_at_utc
    p.write_text(json.dumps(raw), encoding="utf-8")


def test_live_ownership_survives_creator_pid_death_within_ttl(tmp_path):
    cfg = _cfg(tmp_path, ttl=300)
    wt = _mk_worktree(tmp_path)
    _write_lease("s1", "study/s1", wt, cfg, owner="alice@host")
    dead = _dead_pid()
    _set_holder(cfg, "s1", pid=dead, renewed_at_utc=datetime.now(timezone.utc).isoformat())
    rows = read_leases(cfg)
    assert len(rows) == 1 and rows[0]["state"] == "live"   # dead holder pid, but well within the ttl window


def test_stale_after_ttl_expiry_with_dead_pid(tmp_path):
    cfg = _cfg(tmp_path, ttl=1)
    wt = _mk_worktree(tmp_path)
    _write_lease("s1", "study/s1", wt, cfg, owner="alice@host")
    dead = _dead_pid()
    _set_holder(cfg, "s1", pid=dead, renewed_at_utc=(datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat())
    rows = read_leases(cfg)
    assert rows[0]["state"] == "stale"


def test_dead_when_worktree_removed(tmp_path):
    cfg = _cfg(tmp_path)
    wt = _mk_worktree(tmp_path)
    _write_lease("s1", "study/s1", wt, cfg, owner="alice@host")
    shutil.rmtree(wt)
    rows = read_leases(cfg)
    assert rows[0]["state"] == "dead"


def test_second_writer_different_owner_blocked_while_live(tmp_path):
    cfg = _cfg(tmp_path, ttl=300)
    wt = _mk_worktree(tmp_path)
    _write_lease("s1", "study/s1", wt, cfg, owner="alice@host")
    with pytest.raises(WorkspaceError, match="WRITER_LEASE_HELD"):
        _write_lease("s2", "study/s2", wt, cfg, owner="bob@host")


def test_same_owner_renews_and_pushes_the_ttl_window_forward(tmp_path):
    cfg = _cfg(tmp_path, ttl=2)
    wt = _mk_worktree(tmp_path)
    _write_lease("s1", "study/s1", wt, cfg, owner="alice@host")
    dead = _dead_pid()
    _set_holder(cfg, "s1", pid=dead, renewed_at_utc=(datetime.now(timezone.utc) - timedelta(seconds=1.5)).isoformat())
    assert read_leases(cfg)[0]["state"] == "live"   # not yet expired
    updated = renew_lease(wt, owner="alice@host", pid=os.getpid(), kind="controller", config=cfg)
    assert updated is not None and updated["state"] == "live" and updated["holder"]["kind"] == "controller"
    time.sleep(1.5)
    rows = read_leases(cfg)
    assert rows[0]["state"] == "live"   # renewal reset the clock; the pre-renewal deadline would have expired by now


def test_renew_by_other_owner_refused(tmp_path):
    cfg = _cfg(tmp_path, ttl=300)
    wt = _mk_worktree(tmp_path)
    _write_lease("s1", "study/s1", wt, cfg, owner="alice@host")
    with pytest.raises(WorkspaceError, match="WRITER_LEASE_HELD_BY_OTHER"):
        renew_lease(wt, owner="bob@host", pid=os.getpid(), kind="controller", config=cfg)


def test_renew_no_lease_for_worktree_returns_none(tmp_path):
    cfg = _cfg(tmp_path)
    wt = tmp_path / "unleased"; wt.mkdir()
    assert renew_lease(wt, owner="alice@host", pid=os.getpid(), kind="controller", config=cfg) is None


def test_reclaim_removes_only_stale_dead_released_never_live(tmp_path):
    cfg = _cfg(tmp_path, ttl=1)
    live_wt = _mk_worktree(tmp_path, "live"); _write_lease("live1", "study/live1", live_wt, cfg, owner="alice@host")

    stale_wt = _mk_worktree(tmp_path, "stale"); _write_lease("stale1", "study/stale1", stale_wt, cfg, owner="alice@host")
    dead = _dead_pid()
    _set_holder(cfg, "stale1", pid=dead, renewed_at_utc=(datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat())

    dead_wt = _mk_worktree(tmp_path, "deadwt"); _write_lease("dead1", "study/dead1", dead_wt, cfg, owner="alice@host")
    shutil.rmtree(dead_wt)

    released_wt = _mk_worktree(tmp_path, "released"); _write_lease("rel1", "study/rel1", released_wt, cfg, owner="alice@host")
    release_lease("rel1", owner="alice@host", config=cfg)

    rows = read_leases(cfg)
    assert {r["study_id"]: r["state"] for r in rows} == {"live1": "live", "stale1": "stale", "dead1": "dead", "rel1": "released"}
    # exactly the reclaim predicate `research ws list --reclaim` applies (workspace.ws_list)
    for r in rows:
        if r["state"] in {"stale", "dead", "released"}:
            Path(r["lease_path"]).unlink()
    remaining = {r["study_id"] for r in read_leases(cfg)}
    assert remaining == {"live1"}


def test_release_by_non_owner_refused(tmp_path):
    cfg = _cfg(tmp_path)
    wt = _mk_worktree(tmp_path)
    _write_lease("s1", "study/s1", wt, cfg, owner="alice@host")
    with pytest.raises(WorkspaceError, match="LEASE_RELEASE_REFUSED"):
        release_lease("s1", owner="bob@host", config=cfg)


def test_release_by_owner_sets_released_state(tmp_path):
    cfg = _cfg(tmp_path)
    wt = _mk_worktree(tmp_path)
    _write_lease("s1", "study/s1", wt, cfg, owner="alice@host")
    out = release_lease("s1", owner="alice@host", config=cfg)
    assert out["state"] == "released"
    assert read_leases(cfg)[0]["state"] == "released"


def test_v1_schema_lease_still_readable(tmp_path):
    cfg = _cfg(tmp_path, ttl=300)
    wt = _mk_worktree(tmp_path)
    p = _lease_path(cfg, "legacy")
    p.write_text(json.dumps({"study_id": "legacy", "branch": "study/legacy", "worktree": str(wt.resolve()),
                             "owner": "alice@host", "pid": os.getpid(), "created_at_utc": datetime.now(timezone.utc).isoformat()}),
                 encoding="utf-8")
    rows = read_leases(cfg)
    assert len(rows) == 1
    assert rows[0]["state"] == "live"
    assert rows[0]["holder"]["pid"] == os.getpid()
    assert rows[0]["holder"]["kind"] == "cli"

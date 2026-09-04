"""Multi-agent writer ownership: ONE WRITING AGENT = ONE STUDY WORKTREE, even when Claude, Codex and
Antigravity all run under the same OS user on one machine.

Writer identity = user@host + owner_agent + owner_session_id (research_workflow.workspace.writer_identity).
A live lease held by another identity fails closed (STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT); a matching
user@host is never enough. All fixtures are throwaway git repos and tmp lease dirs.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from research_workflow import workspace as ws
from research_workflow.locks import acquire_exclusive
from research_workflow.roots import CONFIG_ENV, load_config


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "src" / "nt-repo"; repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("x"); (repo / ".gitignore").write_text("**/runs/\n**/_work/\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True); subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"catalog_roots": [str(tmp_path / "roots")], "model_root": str(tmp_path / "models"),
                                   "leases_dir": str(tmp_path / "leases"), "worktree_root": str(tmp_path / "wts")}), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV, str(cfg))
    monkeypatch.delenv("NT_RESEARCH_MODEL_ROOT", raising=False)
    (tmp_path / "wts").mkdir()
    return _repo(tmp_path)


def _ident(agent: str, session: str) -> dict:
    base = ws.writer_identity()                       # same user@host for every agent on this machine
    return {**base, "agent": agent, "session_id": session, "agent_source": "test", "session_source": "test"}


CLAUDE = _ident("claude", "claude-session-1")
CLAUDE_AGAIN = _ident("claude", "claude-session-1")   # same session re-entering
CLAUDE_2 = _ident("claude", "claude-session-2")       # a second Claude session is a different writer
CODEX = _ident("codex", "codex-session-1")
ANTIGRAVITY = _ident("antigravity", "antigravity-session-1")


def _study_new_as(env: Path, study_id: str, ident: dict) -> dict:
    """study new under a given agent/session identity (what each launcher's env produces)."""
    os.environ[ws.AGENT_ENV] = ident["agent"]
    os.environ[ws.AGENT_SESSION_ENV] = ident["session_id"]
    try:
        return ws.study_new(study_id, repo_root=env)
    finally:
        os.environ.pop(ws.AGENT_ENV, None); os.environ.pop(ws.AGENT_SESSION_ENV, None)


def _lease(card: dict) -> dict:
    return json.loads(Path(card["lease"]).read_text(encoding="utf-8"))


# 1. Claude claims Study A -> PASS
def test_01_claude_claims_study_a(env: Path):
    card = _study_new_as(env, "study_a", CLAUDE)
    lease = _lease(card)
    assert lease["schema_version"] == 3 and lease["owner_agent"] == "claude" and lease["owner_session_id"] == "claude-session-1"
    assert lease["owner_user"] and lease["owner_host"] and lease["owner"] == f"{lease['owner_user']}@{lease['owner_host']}"
    assert card["writer"]["agent"] == "claude"
    out = ws.check_writer_access(Path(card["worktree"]), identity=CLAUDE)
    assert out is not None and out["state"] == "live" and out["holder"]["kind"] == "controller"


# 2./3. Codex and Antigravity attempt Study A while Claude is live -> REFUSED (same user@host!)
@pytest.mark.parametrize("other", [CODEX, ANTIGRAVITY, CLAUDE_2], ids=["codex", "antigravity", "second-claude-session"])
def test_02_03_foreign_writer_refused_while_claude_live(env: Path, other: dict):
    card = _study_new_as(env, "study_a", CLAUDE)
    assert other["owner"] == _lease(card)["owner"]          # identical user@host: the old check would have allowed this
    with pytest.raises(ws.WorkspaceError, match="STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT"):
        ws.claim_worktree("study_a", repo_root=env, identity=other)
    with pytest.raises(ws.WorkspaceError, match="STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT"):
        ws.check_writer_access(Path(card["worktree"]), identity=other)
    with pytest.raises(ws.WorkspaceError, match="STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT"):
        ws.renew_lease(Path(card["worktree"]), owner=other["owner"], pid=os.getpid(), identity=other)
    with pytest.raises(ws.WorkspaceError, match="LEASE_RELEASE_REFUSED"):
        ws.release_lease("study_a", owner=other["owner"], identity=other)
    assert _lease(card)["owner_agent"] == "claude"          # nothing was taken over


# 4. Claude same session re-enters Study A -> PASS / idempotent
def test_04_same_session_reentry_is_idempotent(env: Path):
    card = _study_new_as(env, "study_a", CLAUDE)
    before = _lease(card)
    out = ws.claim_worktree("study_a", repo_root=env, identity=CLAUDE_AGAIN)
    assert out["result"] == "already_owner" and out["lease"]["owner_session_id"] == "claude-session-1"
    again = ws.claim_worktree("study_a", repo_root=env, identity=CLAUDE_AGAIN)
    assert again["result"] == "already_owner"
    after = _lease(card)
    assert after["created_at_utc"] == before["created_at_utc"] and after["owner_session_id"] == before["owner_session_id"]
    assert after["renewed_at_utc"] >= before["renewed_at_utc"]
    assert ws._write_lease("study_a", "study/study_a", Path(card["worktree"]), identity=CLAUDE_AGAIN) == Path(card["lease"])


# 5. Claude Study A + Codex Study B + Antigravity Study C -> all PASS concurrently
def test_05_three_agents_three_studies_concurrently(env: Path):
    a = _study_new_as(env, "study_a", CLAUDE)
    b = _study_new_as(env, "study_b", CODEX)
    c = _study_new_as(env, "study_c", ANTIGRAVITY)
    listing = ws.ws_list(repo_root=env)
    by_study = {l["study_id"]: l for l in listing["leases"]}
    assert {k: (v["state"], v["owner_agent"]) for k, v in by_study.items()} == {
        "study_a": ("live", "claude"), "study_b": ("live", "codex"), "study_c": ("live", "antigravity")}
    assert len({v["owner"] for v in by_study.values()}) == 1              # one OS user, three writers
    # each writer passes its own gate and fails every other study's gate
    for card, me in ((a, CLAUDE), (b, CODEX), (c, ANTIGRAVITY)):
        assert ws.check_writer_access(Path(card["worktree"]), identity=me) is not None
    for card, other in ((a, CODEX), (b, ANTIGRAVITY), (c, CLAUDE)):
        with pytest.raises(ws.WorkspaceError, match="STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT"):
            ws.check_writer_access(Path(card["worktree"]), identity=other)
    rows = {r["lease_study"]: r for r in listing["worktrees"] if r["lease_study"]}
    assert rows["study_b"]["owner_agent"] == "codex" and rows["study_c"]["owner_session_id"] == "antigravity-session-1"


# 6. stale lease -> reclaim + new claim succeeds
def test_06_stale_lease_can_be_claimed_by_another_agent(env: Path):
    card = _study_new_as(env, "study_a", CLAUDE)
    p = Path(card["lease"]); rec = json.loads(p.read_text())
    rec["holder"]["pid"] = 999999; rec["holder"]["renewed_at_utc"] = "2000-01-01T00:00:00+00:00"; rec["renewed_at_utc"] = rec["holder"]["renewed_at_utc"]
    p.write_text(json.dumps(rec))
    assert next(l for l in ws.read_leases() if l["study_id"] == "study_a")["state"] == "stale"
    out = ws.claim_worktree("study_a", repo_root=env, identity=CODEX)
    assert out["result"] == "claimed" and out["lease"]["owner_agent"] == "codex" and out["lease"]["state"] == "live"
    assert out["reclaimed_from"]["agent"] == "claude" and out["reclaimed_from"]["state"] == "stale"
    # the original session is now the foreign writer
    with pytest.raises(ws.WorkspaceError, match="STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT"):
        ws.check_writer_access(Path(card["worktree"]), identity=CLAUDE)
    # `ws list --reclaim` also clears a stale lease without touching a live one
    b = _study_new_as(env, "study_b", ANTIGRAVITY)
    pb = Path(b["lease"]); rb = json.loads(pb.read_text()); rb["holder"]["pid"] = 999999; rb["holder"]["renewed_at_utc"] = "2000-01-01T00:00:00+00:00"
    pb.write_text(json.dumps(rb))
    after = ws.ws_list(repo_root=env, reclaim=True)
    assert after["reclaimed"] == ["study_b"] and Path(card["lease"]).exists()
    assert ws.claim_worktree("study_b", repo_root=env, identity=CLAUDE)["result"] == "claimed"


# 7. released lease -> new agent claim succeeds
def test_07_released_lease_can_be_claimed(env: Path):
    card = _study_new_as(env, "study_a", CLAUDE)
    rel = ws.release_lease("study_a", owner=CLAUDE["owner"], identity=CLAUDE)
    assert rel["state"] == "released"
    out = ws.claim_worktree("study_a", repo_root=env, identity=ANTIGRAVITY)
    assert out["result"] == "claimed" and out["lease"]["owner_agent"] == "antigravity" and out["reclaimed_from"]["state"] == "released"
    # a legacy (schema 2) lease has no session identity: never "the same writer"; cleared only by --force / reclaim
    legacy = _study_new_as(env, "study_l", CLAUDE)
    pl = Path(legacy["lease"]); rl = json.loads(pl.read_text())
    for k in ("owner_user", "owner_host", "owner_agent", "owner_session_id", "renewed_at_utc"):
        rl.pop(k, None)
    rl["schema_version"] = 2; pl.write_text(json.dumps(rl))
    with pytest.raises(ws.WorkspaceError, match="STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT"):
        ws.claim_worktree("study_l", repo_root=env, identity=CLAUDE)
    with pytest.raises(ws.WorkspaceError, match="LEASE_RELEASE_REFUSED"):
        ws.release_lease("study_l", owner=CLAUDE["owner"], identity=CLAUDE)
    forced = ws.release_lease("study_l", owner=CLAUDE["owner"], identity=CLAUDE, force=True)
    assert forced["state"] == "released" and forced["forced_release_by"]["agent"] == "claude"
    assert ws.claim_worktree("study_l", repo_root=env, identity=CODEX)["result"] == "claimed"


# 8. read-only auditor can inspect without claim
def test_08_read_only_auditor_inspects_without_writer_claim(env: Path):
    card = _study_new_as(env, "study_a", CLAUDE)
    wt = Path(card["worktree"]); before = Path(card["lease"]).read_bytes()
    # an auditor running as another agent reads source, study spec, lease listing -- no claim, no gate
    auditor = ANTIGRAVITY
    assert (wt / "studies/study_a/study.yaml").read_text(encoding="utf-8").startswith("# Platform-v2 study")
    (wt / "studies/study_a/audit").mkdir(exist_ok=True)     # its own audit report directory is the only thing it writes
    listing = ws.ws_list(repo_root=env)
    row = next(r for r in listing["worktrees"] if r["lease_study"] == "study_a")
    assert row["lease_state"] == "live" and row["owner_agent"] == "claude"
    assert [l["study_id"] for l in ws.read_leases()] == ["study_a"]
    assert Path(card["lease"]).read_bytes() == before        # inspection mutated no lease
    # only a WRITE-capable operation consults the gate
    with pytest.raises(ws.WorkspaceError, match="STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT"):
        ws.check_writer_access(wt, identity=auditor)


# 9. controller lock remains independent of the writer lease
def test_09_controller_run_lock_is_independent(env: Path):
    card = _study_new_as(env, "study_a", CLAUDE)
    wt = Path(card["worktree"]); lock = wt / "studies/study_a/_work/controller/run.lock"
    payload = {"pid": os.getpid(), "started_at_utc": datetime.now(timezone.utc).isoformat(), "through": "compile"}

    def is_stale(existing, mtime):                          # the controller's predicate: live pid blocks
        pid = int((existing or {}).get("pid") or 0)
        return not (pid and ws._pid_alive(pid))

    # writer gate passes for Claude, run lock acquired
    assert ws.check_writer_access(wt, identity=CLAUDE) is not None
    first = acquire_exclusive(lock, payload, is_stale=is_stale, max_attempts=1)
    assert first.acquired
    # the SAME writer cannot start a second live run: run lock blocks independently of the lease
    second = acquire_exclusive(lock, payload, is_stale=is_stale, max_attempts=1)
    assert not second.acquired and second.payload["pid"] == os.getpid()
    # a foreign writer is blocked by the lease even though it never reaches the run lock
    with pytest.raises(ws.WorkspaceError, match="STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT"):
        ws.check_writer_access(wt, identity=CODEX)
    lock.unlink()
    # releasing the lease does not release a live run lock and vice versa
    ws.release_lease("study_a", owner=CLAUDE["owner"], identity=CLAUDE)
    third = acquire_exclusive(lock, payload, is_stale=is_stale, max_attempts=1)
    assert third.acquired and ws.check_writer_access(wt, identity=CODEX) is None   # released lease: no gate; run lock is its own thing
    src = (Path(__file__).resolve().parents[2] / "research_workflow" / "governed_controller_v2.py").read_text(encoding="utf-8")
    run_lock_src = src[src.index("def _acquire_run_lock"):src.index("def ", src.index("def _acquire_run_lock") + 10)]
    assert "run.lock" in run_lock_src and "lease" not in run_lock_src.lower()
    assert "check_writer_access" in src and 'card["blocker_code"] = "STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT"' in src


# 10. two simultaneous claims -> exactly one winner
def test_10_simultaneous_claims_have_exactly_one_winner(env: Path):
    card = _study_new_as(env, "study_a", CLAUDE)
    ws.release_lease("study_a", owner=CLAUDE["owner"], identity=CLAUDE)
    barrier = threading.Barrier(2)
    results: dict = {}

    def go(name: str, ident: dict) -> None:
        barrier.wait()
        try:
            results[name] = ws.claim_worktree("study_a", repo_root=env, identity=ident)["result"]
        except ws.WorkspaceError as exc:
            results[name] = str(exc).split(":", 1)[0].split(" ")[0]

    ts = [threading.Thread(target=go, args=("codex", CODEX)), threading.Thread(target=go, args=("antigravity", ANTIGRAVITY))]
    [t.start() for t in ts]; [t.join(timeout=30) for t in ts]
    winners = [k for k, v in results.items() if v == "claimed"]
    assert len(winners) == 1, results
    loser = next(k for k in results if k not in winners)
    assert results[loser] in {"STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT", "STUDY_CLAIM_IN_PROGRESS"}, results
    lease = _lease(card)
    assert lease["owner_agent"] == winners[0] and lease["released_at_utc"] is None
    # a retry by the loser is refused (the winner is live); the claim lock was released
    with pytest.raises(ws.WorkspaceError, match="STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT"):
        ws.claim_worktree("study_a", repo_root=env, identity=CODEX if loser == "codex" else ANTIGRAVITY)
    assert not (Path(card["lease"]).parent / "study_a.claim").exists()


# identity resolution: launcher env wins, harness env is inferred, session never falls back to a bare pid when a harness is present
def test_identity_resolution_from_launcher_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(ws.AGENT_ENV, "antigravity"); monkeypatch.setenv(ws.AGENT_SESSION_ENV, "ag-42")
    ident = ws.writer_identity()
    assert ident["agent"] == "antigravity" and ident["session_id"] == "ag-42" and ident["agent_source"] == "env" and ident["session_source"] == "env"
    monkeypatch.delenv(ws.AGENT_ENV); monkeypatch.delenv(ws.AGENT_SESSION_ENV)
    for var in list(os.environ):
        if var.startswith(("CLAUDE", "CODEX", "ANTIGRAVITY", "GEMINI")):
            monkeypatch.delenv(var)
    monkeypatch.setenv("CLAUDECODE", "1"); monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-claude-7")
    ident = ws.writer_identity()
    assert ident["agent"] == "claude" and ident["session_id"] == "sess-claude-7" and ident["session_source"] == "harness_env:CLAUDE_CODE_SESSION_ID"
    monkeypatch.delenv("CLAUDECODE"); monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    ident = ws.writer_identity()
    assert ident["agent"] == "codex" and ident["session_id"] and ident["session_source"] in {"process_tree", "pid_fallback"}

"""research study new / research ws list (research_workflow.workspace) on a throwaway git repo."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from research_workflow import workspace as ws
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


def test_study_new_creates_branch_worktree_scaffold_and_lease(env: Path, tmp_path: Path):
    card = ws.study_new("demo_alpha", repo_root=env)
    wt = Path(card["worktree"])
    assert wt.is_dir() and card["branch"] == "study/demo_alpha" and wt.name == "nt-repo-demo_alpha"
    assert (wt / "studies/demo_alpha/study.yaml").is_file() and (wt / "studies/demo_alpha/research_decision.yaml").is_file()
    assert (wt / "studies/demo_alpha/runs").is_dir() and (wt / "studies/demo_alpha/_work").is_dir()
    assert not any(p.is_symlink() for p in wt.rglob("*"))  # no junction/symlink plumbing in the normal path
    lease = json.loads(Path(card["lease"]).read_text())
    assert lease["study_id"] == "demo_alpha" and lease["pid"] == os.getpid() and Path(lease["worktree"]) == wt.resolve()
    branches = subprocess.run(["git", "branch", "--list"], cwd=env, capture_output=True, text=True).stdout
    assert "study/demo_alpha" in branches
    assert card["catalog_resolution"] == "configured_roots"


def test_second_writer_for_same_worktree_is_refused(env: Path, tmp_path: Path):
    card = ws.study_new("demo_beta", repo_root=env)
    with pytest.raises(ws.WorkspaceError, match="WRITER_LEASE_HELD"):
        ws._write_lease("demo_beta_again", "study/x", Path(card["worktree"]))


def test_duplicate_study_branch_or_worktree_refused(env: Path):
    ws.study_new("demo_gamma", repo_root=env)
    with pytest.raises(ws.WorkspaceError, match="BRANCH_EXISTS|WORKTREE_EXISTS|STUDY_EXISTS"):
        ws.study_new("demo_gamma", repo_root=env)


def test_dirty_source_worktree_refused(env: Path):
    (env / "dirty.txt").write_text("x")
    with pytest.raises(ws.WorkspaceError, match="SOURCE_WORKTREE_DIRTY"):
        ws.study_new("demo_delta", repo_root=env)


def test_ws_list_reports_worktrees_owners_and_lease_states(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    card = ws.study_new("demo_eps", repo_root=env)
    listing = ws.ws_list(repo_root=env)
    row = next(r for r in listing["worktrees"] if r["branch"] == "study/demo_eps")
    assert row["lease_state"] == "live" and row["owner"] and row["dirty_files"] >= 0
    # kill the lease's pid -> stale; remove the worktree dir -> dead; reclaim removes both
    lease_path = Path(card["lease"]); rec = json.loads(lease_path.read_text()); rec["pid"] = 999999; lease_path.write_text(json.dumps(rec))
    assert next(l for l in ws.ws_list(repo_root=env)["leases"] if l["study_id"] == "demo_eps")["state"] == "stale"
    after = ws.ws_list(repo_root=env, reclaim=True)
    assert "demo_eps" in after["reclaimed"] and not lease_path.exists()


def test_invalid_study_id(env: Path):
    with pytest.raises(ws.WorkspaceError, match="STUDY_ID_INVALID"):
        ws.study_new("bad id/with slash", repo_root=env)


def test_v2_skeleton_compiles_statically_without_study_python(env: Path):
    """`research study new` yields a grammar-v2 study.yaml that the static compiler binds with no gaps."""
    from research_workflow.grammar import compile_study, load_spec
    from research_workflow.lifecycle_v2 import is_v2_study
    card = ws.study_new("demo_zeta", repo_root=env)
    study = Path(card["worktree"]) / "studies" / "demo_zeta"
    assert is_v2_study(study)
    out = compile_study(load_spec(study / "study.yaml"), repo_root=Path(__file__).resolve().parents[2])
    assert out.ok, out.card()
    assert out.plan.card()["catalog_opened"] is False and all(b["bound"] for b in out.plan.binding_proof)
    assert not list(study.glob("**/*.py"))


def test_ws_list_reclaim_clears_only_stale_and_dead_leases(env: Path):
    """`research ws list --reclaim` deletes stale/dead lease records and never a live one."""
    live = ws.study_new("demo_live", repo_root=env)
    stale = ws.study_new("demo_stale", repo_root=env)
    p = Path(stale["lease"]); rec = json.loads(p.read_text()); rec["pid"] = 999999; p.write_text(json.dumps(rec))
    states = {l["study_id"]: l["state"] for l in ws.ws_list(repo_root=env)["leases"]}
    assert states["demo_live"] == "live" and states["demo_stale"] == "stale"
    after = ws.ws_list(repo_root=env, reclaim=True)
    assert after["reclaimed"] == ["demo_stale"] and Path(live["lease"]).exists() and not p.exists()
    with pytest.raises(ws.WorkspaceError, match="WRITER_LEASE_HELD"):
        ws._write_lease("demo_live", "study/demo_live", Path(live["worktree"]))

"""Session efficiency mechanics (WORKFLOW.md §N): stop-at-capability-gap handoff, phase handoff cards,
chore-worktree ownership, and the committed test-failure baseline (scripts/test_delta.py).

Synthetic dry run only: a tiny study that intentionally names an unregistered tracker, a throwaway git
repo/lease dir, and a throwaway pytest scope. No data replay, no real study is touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

from research_workflow import workspace as ws
from research_workflow.grammar.compiler import compile_study, load_spec
from research_workflow.handoff import PHASES, PROHIBITED_FOR_STUDY_OWNER, write_capability_gap_handoff, write_session_handoff
from research_workflow.roots import CONFIG_ENV

ROOT = Path(__file__).resolve().parents[2]
GAP_EXAMPLE = ROOT / "docs" / "examples" / "registry_blind_draft.yaml"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "src" / "nt-repo"; repo.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    (repo / "README.md").write_text("x"); (repo / ".gitignore").write_text("**/runs/\n**/_work/\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True); subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"catalog_roots": [str(tmp_path / "roots")], "model_root": str(tmp_path / "models"),
                                   "leases_dir": str(tmp_path / "leases"), "worktree_root": str(tmp_path / "wts")}), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV, str(cfg)); monkeypatch.delenv("NT_RESEARCH_MODEL_ROOT", raising=False)
    (tmp_path / "wts").mkdir()
    return _repo(tmp_path)


def _ident(agent: str, session: str) -> dict:
    return {**ws.writer_identity(), "agent": agent, "session_id": session}


CLAUDE = _ident("claude", "s-claude"); CODEX = _ident("codex", "s-codex"); ANTI = _ident("antigravity", "s-anti")


# --------------------------------------------------------------------------- #
# 1. stop-at-capability-gap: compile -> typed gap -> handoff -> study work stops
# --------------------------------------------------------------------------- #
def _synthetic_gap_study(tmp_path: Path) -> Path:
    study = tmp_path / "studies" / "synthetic_gap_study"; study.mkdir(parents=True)
    spec = yaml.safe_load(GAP_EXAMPLE.read_text(encoding="utf-8"))
    spec["study"]["id"] = "synthetic_gap_study"
    (study / "study.yaml").write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    (study / "research_decision.yaml").write_text(yaml.safe_dump({
        "study_id": "synthetic_gap_study", "research_question": "Does a 60s volume-imbalance tracker add information?", "status": "DRAFT",
        "dataset_id": "NQ_1S_V2_GLOBEX", "terminal_decisions": {"direction": "regime_1m.dir"},
        "autonomy_decisions": {"on_capability_gap": "stop_and_handoff", "platform_change_required": "chore_branch_and_fresh_session"}}, sort_keys=False), encoding="utf-8")
    return study


def test_session_step_1_compile_gap_writes_handoff_and_stops(tmp_path: Path):
    study = _synthetic_gap_study(tmp_path)
    out = compile_study(load_spec(study / "study.yaml"), repo_root=ROOT)
    assert not out.ok and "MISSING_CAPABILITY" in out.gaps.kinds()
    doc = write_capability_gap_handoff(study, out.gaps.to_dict(), repo_root=ROOT)
    for key in ("study_id", "source_platform_commit", "research_question", "gap_kinds", "gaps", "requested_semantics", "compiler_evidence",
                "affected_yaml_fields", "existing_nearest_capabilities", "scientific_decisions_already_resolved", "prohibited_changes",
                "suggested_platform_files", "study_branch", "study_worktree", "next_action", "proposed_chore_topic"):
        assert key in doc, key
    assert doc["study_id"] == "synthetic_gap_study" and doc["research_question"].startswith("Does a 60s")
    assert "context.imbalance" in doc["affected_yaml_fields"]
    assert doc["scientific_decisions_already_resolved"]["terminal_decisions"] == {"direction": "regime_1m.dir"}
    assert doc["scientific_decisions_already_resolved"]["autonomy_decisions"]["on_capability_gap"] == "stop_and_handoff"
    assert doc["prohibited_changes"] == PROHIBITED_FOR_STUDY_OWNER and any("research_workflow/" in p for p in doc["prohibited_changes"])
    assert any(f.startswith("features/trackers") for f in doc["suggested_platform_files"])
    assert "END THIS SESSION" in doc["next_action"]["study_owner"]
    assert (study / "CAPABILITY_GAP_HANDOFF.json").is_file() and (study / "CAPABILITY_GAP_HANDOFF.md").is_file()
    md = (study / "CAPABILITY_GAP_HANDOFF.md").read_text(encoding="utf-8")
    assert "STUDY OWNER: STOP" in md and "MISSING_CAPABILITY" in md
    # the study owner's work stops here: no compiled plan, nothing under research_workflow/ was touched by the handoff
    assert not (study / "compiled_plan.json").exists()


def test_cli_compile_emits_handoff_card(tmp_path: Path):
    """The operator CLI writes the handoff itself on a gap and tells the owner to stop."""
    study = _synthetic_gap_study(tmp_path)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "research.py"), "study", "compile", "--study", str(study)],
                       cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    card = json.loads([l for l in r.stdout.strip().splitlines() if l.startswith("{")][-1])
    assert card["STATUS"] == "CAPABILITY_GAP" and r.returncode == 2 and "MISSING_CAPABILITY" in card["kinds"]
    assert card["handoff"] and Path(card["handoff"]).name == "CAPABILITY_GAP_HANDOFF.json"
    assert card["next"].startswith("STOP") and "END THE SESSION" in card["next"]
    assert (study / "CAPABILITY_GAP_HANDOFF.json").is_file()
    # --dry-run never writes a handoff
    shutil.rmtree(study); study = _synthetic_gap_study(tmp_path)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "research.py"), "study", "compile", "--study", str(study), "--dry-run"], cwd=str(ROOT), capture_output=True)
    assert not (study / "CAPABILITY_GAP_HANDOFF.json").exists()


# --------------------------------------------------------------------------- #
# 2. capability step: separate chore ownership; disjoint chores proceed, overlaps are refused
# --------------------------------------------------------------------------- #
def test_capability_step_chore_ownership_overlap_refused_disjoint_ok(env: Path):
    a = ws.claim_chore("volume-imbalance-tracker", repo_root=env, write_paths=["features/trackers/", "research_workflow/capabilities_index.yaml"],
                       semantic_surface="60s buy/sell volume imbalance tracker", capability_ids=["tracker.volume_imbalance"], identity=CLAUDE)
    assert a["result"] == "claimed" and a["state"] == "live" and a["owner_agent"] == "claude"
    # a second writer touching the compiler while nobody owns it: disjoint -> proceeds concurrently
    b = ws.claim_chore("chronology-windows", repo_root=env, write_paths=["research_workflow/grammar/compiler.py", "research_workflow/grammar/spec.py"],
                       semantic_surface="date-bounded partitions", identity=CODEX)
    assert b["result"] == "claimed"
    # a third writer proposing an overlapping surface (a file inside features/trackers/) is refused BEFORE implementing
    with pytest.raises(ws.WorkspaceError, match="PLATFORM_SURFACE_OWNED_BY_ANOTHER_AGENT"):
        ws.claim_chore("delta-tracker", repo_root=env, write_paths=["features/trackers/ohlcv_delta.py"], semantic_surface="delta", identity=ANTI)
    # ... and so is the whole grammar directory while Codex owns two files in it
    with pytest.raises(ws.WorkspaceError, match="PLATFORM_SURFACE_OWNED_BY_ANOTHER_AGENT"):
        ws.claim_chore("grammar-refactor", repo_root=env, write_paths=["research_workflow/grammar/"], semantic_surface="refactor", identity=ANTI)
    # same writer re-claiming its own topic is idempotent; another writer taking the topic name is refused
    assert ws.claim_chore("volume-imbalance-tracker", repo_root=env, write_paths=["features/trackers/"], semantic_surface="x", identity=CLAUDE)["result"] == "already_owner"
    with pytest.raises(ws.WorkspaceError, match="PLATFORM_SURFACE_OWNED_BY_ANOTHER_AGENT"):
        ws.claim_chore("volume-imbalance-tracker", repo_root=env, write_paths=["features/trackers/"], semantic_surface="x", identity=CODEX)
    listing = ws.list_chores()
    assert {c["topic"]: c["owner_agent"] for c in listing["chores"]} == {"volume-imbalance-tracker": "claude", "chronology-windows": "codex"}
    # release -> the surface is free; a foreign release without --force is refused
    with pytest.raises(ws.WorkspaceError, match="CHORE_RELEASE_REFUSED"):
        ws.release_chore("volume-imbalance-tracker", identity=ANTI)
    assert ws.release_chore("volume-imbalance-tracker", identity=CLAUDE)["state"] == "released"
    assert ws.claim_chore("delta-tracker", repo_root=env, write_paths=["features/trackers/ohlcv_delta.py"], semantic_surface="delta", identity=ANTI)["result"] == "claimed"
    assert ws.list_chores(reclaim=True)["reclaimed"] == ["volume-imbalance-tracker"]
    assert ws._paths_overlap("features/library.py", "research_workflow/host/") is False


# --------------------------------------------------------------------------- #
# 3. resume: a fresh owner consumes the handoff cards without reconstructing the prior session
# --------------------------------------------------------------------------- #
def test_resume_from_handoff_cards_without_rediscovery(tmp_path: Path):
    study = _synthetic_gap_study(tmp_path)
    out = compile_study(load_spec(study / "study.yaml"), repo_root=ROOT)
    write_capability_gap_handoff(study, out.gaps.to_dict(), repo_root=ROOT)
    card = write_session_handoff(study, "A", repo_root=ROOT, note="stopped at MISSING_CAPABILITY; capability session owns tracker.volume_imbalance")
    assert card["phase"] == "A" and card["capability_gap_handoff_present"] is True and card["compiled_plan_present"] is False
    assert card["decisions"]["autonomy_decisions"]["on_capability_gap"] == "stop_and_handoff"
    assert card["next_command"].endswith("--through seal --execute-authorized") and "ws claim synthetic_gap_study" in card["resume"][0]
    p = study / "_work" / "handoff" / "SESSION_HANDOFF.json"
    assert p.is_file() and (p.with_suffix(".md")).is_file()
    # a fresh process reads BOTH cards and knows: what stopped it, what to build, where, and what to run next
    fresh = json.loads(p.read_text(encoding="utf-8")); gap = json.loads((study / "CAPABILITY_GAP_HANDOFF.json").read_text(encoding="utf-8"))
    assert fresh["study_id"] == gap["study_id"] == "synthetic_gap_study"
    assert gap["proposed_chore_topic"].startswith("synthetic_gap_study-missing_capability")
    assert any("ws chore claim" in step for step in gap["next_action"]["capability_session"])
    assert any("study compile" in step for step in gap["next_action"]["resume_session"])
    for ph in PHASES:
        assert PHASES[ph]["end_when"] and PHASES[ph]["next_command"]
    with pytest.raises(ValueError, match="UNKNOWN_PHASE"):
        write_session_handoff(study, "Z", repo_root=ROOT)


# --------------------------------------------------------------------------- #
# 4. test_delta: one known baseline failure, one synthetic new failure, one fixed, one environmental
# --------------------------------------------------------------------------- #
def test_test_delta_classifies_against_committed_baseline(tmp_path: Path):
    scope = ROOT / "scratch" / f"_delta_scope_{uuid.uuid4().hex[:8]}"
    scope.mkdir(parents=True)
    try:
        (scope / "test_delta_fixture.py").write_text(
            "def test_known_failure():\n    assert 1 == 2\n\n"
            "def test_new_failure():\n    assert 'new' == 'regression'\n\n"
            "def test_now_fixed():\n    assert True\n\n"
            "def test_environmental():\n    open('C:/definitely/missing/artifact.parquet')\n\n"
            "def test_passes():\n    assert True\n", encoding="utf-8")
        rel = scope.relative_to(ROOT).as_posix()
        node = lambda name: f"{rel}/test_delta_fixture.py::{name}"
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"schema_version": 1, "platform_commit": "deadbeef", "scopes": [rel],
                                        "expected_failures": [{"node_id": node("test_known_failure"), "classification": "pre_existing", "reason": "fixture"},
                                                              {"node_id": node("test_now_fixed"), "classification": "pre_existing", "reason": "fixed since"}]}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "test_delta.py"), rel, "--baseline", str(baseline), "--json"],
                           cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
        card = json.loads(r.stdout)
        assert r.returncode == 1 and card["STATUS"] == "NEW_FAILURES", card
        assert [e["node_id"] for e in card["NEW_FAILURE"]] == [node("test_new_failure")]
        assert card["KNOWN_BASELINE_FAILURE"] == [node("test_known_failure")]
        assert card["BASELINE_FAILURE_NOW_FIXED"] == [node("test_now_fixed")]
        assert card["ENVIRONMENTAL_MISSING_ARTIFACT"] == [node("test_environmental")]
        assert card["ran"] == 5 and card["passed"] == 2
        # a failure outside every baselined scope is never silently allowed
        narrow = tmp_path / "narrow.json"
        narrow.write_text(json.dumps({"schema_version": 1, "scopes": ["research_workflow/tests"], "expected_failures": []}), encoding="utf-8")
        r2 = subprocess.run([sys.executable, str(ROOT / "scripts" / "test_delta.py"), rel, "--baseline", str(narrow), "--json"], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
        c2 = json.loads(r2.stdout)
        assert c2["STATUS"] == "NEW_FAILURES" and {e["node_id"] for e in c2["NEW_FAILURE_OUTSIDE_BASELINE_SCOPE"]} == {node("test_known_failure"), node("test_new_failure")}
        # the baseline changes only through an explicit, reasoned update; the reason is recorded per node
        r3 = subprocess.run([sys.executable, str(ROOT / "scripts" / "test_delta.py"), rel, "--baseline", str(baseline), "--update-baseline"], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
        assert json.loads(r3.stdout)["STATUS"] == "FAIL"
        r4 = subprocess.run([sys.executable, str(ROOT / "scripts" / "test_delta.py"), rel, "--baseline", str(baseline), "--update-baseline", "--reason", "fixture baseline"], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
        assert json.loads(r4.stdout)["action"] == "BASELINE_UPDATED"
        doc = json.loads(baseline.read_text(encoding="utf-8"))
        ids = {e["node_id"]: e for e in doc["expected_failures"]}
        assert set(ids) == {node("test_known_failure"), node("test_new_failure"), node("test_environmental")}
        assert ids[node("test_known_failure")]["reason"] == "fixture" and ids[node("test_new_failure")]["reason"] == "fixture baseline"
        assert ids[node("test_environmental")]["classification"] == "environmental" and doc["platform_commit"]
        r5 = subprocess.run([sys.executable, str(ROOT / "scripts" / "test_delta.py"), rel, "--baseline", str(baseline)], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
        assert json.loads(r5.stdout)["STATUS"] == "OK" and r5.returncode == 0
    finally:
        shutil.rmtree(scope, ignore_errors=True)


def test_committed_baseline_exists_and_is_well_formed():
    p = ROOT / "config" / "test_failure_baseline.json"
    assert p.is_file(), "config/test_failure_baseline.json must be committed (scripts/test_delta.py --update-baseline --reason ...)"
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["platform_commit"] and doc["scopes"] and isinstance(doc["expected_failures"], list)
    for e in doc["expected_failures"]:
        assert "::" in e["node_id"] and e["classification"] in {"pre_existing", "environmental", "expected_change"} and e.get("reason")


def test_study_skeleton_declares_autonomy_decisions(env: Path):
    os.environ[ws.AGENT_ENV] = "claude"; os.environ[ws.AGENT_SESSION_ENV] = "skel"
    try:
        card = ws.study_new("skel_study", repo_root=env)
    finally:
        os.environ.pop(ws.AGENT_ENV, None); os.environ.pop(ws.AGENT_SESSION_ENV, None)
    dec = yaml.safe_load((Path(card["worktree"]) / "studies" / "skel_study" / "research_decision.yaml").read_text(encoding="utf-8"))
    ad = dec["autonomy_decisions"]
    assert ad["on_capability_gap"] == "stop_and_handoff" and ad["platform_change_required"] == "chore_branch_and_fresh_session"
    assert ad["deterministic_defect"] == "auto_fix" and ad["calendar_reference_parity"] == "common_interval_exact"
    assert ad["frozen_parent_model"] == "rescore_if_authenticated" and ad["protected_period"] == "never_expand_authority"

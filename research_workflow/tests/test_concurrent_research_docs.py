"""Concurrent-research documentation and mechanism checks.

The mechanism itself (branch + sibling worktree + lease + skeleton, second writer refused, ws list
states) is exercised on a throwaway git repo by scripts/tests/test_workspace.py; this file makes sure
the manuals, the agent entry points and the role definitions carry the canonical procedure, that the
agent sync roster includes every active role, and that no document offers manual branch creation or
work on main as the path.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WRITE_CAPABLE = ("implementer", "research-executor", "analysis-decider")
READ_ONLY = ("repo-scout", "Explore", "results-triager", "capability-router", "lookahead-auditor", "contract-checker")
ENTRYPOINTS = ("CLAUDE.md", "CODEX.md", "AGENTS.md", "GEMINI.md")


def _t(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_workflow_has_the_canonical_concurrent_procedure():
    w = _t("WORKFLOW.md")
    assert "## M. Concurrent research projects" in w
    for phrase in ("EVERY NEW RESEARCH PROJECT GETS ITS OWN BRANCH + WORKTREE", "ONE WRITING AGENT = ONE WORKTREE",
                   "NEVER START A NEW RESEARCH STUDY BY EDITING MAIN DIRECTLY", "git switch main", "python scripts/research.py study new",
                   "python scripts/research.py ws list", "ws list --reclaim", "git merge --no-ff study/", "current checkout's HEAD",
                   "### M.2 What is shared and what is isolated", "### M.3 Platform change vs research change", "### M.4 Lease semantics",
                   "run.lock", "STUDY_RUN_ALREADY_LIVE", "WRITER_LEASE_HELD", "`live`", "`stale`", "`dead`", "`released`", "chore/<topic>",
                   "regime_breakout_context", "pullback_quality_target", "cross_market_context", "### M.6 Closure and merge back",
                   # multi-agent writer ownership: user@host + agent + session; three independent mechanisms
                   "STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT", "owner_agent", "owner_session_id", "ws claim", "ws whoami",
                   "WRITER LEASE", "CONTROLLER RUN LOCK", "branch + worktree isolation", "NT_RESEARCH_AGENT"):
        assert phrase in w, phrase


def test_lease_states_documented_match_the_implementation():
    src = _t("research_workflow/workspace.py")
    assert "def lease_state(rec: Dict[str, Any]) -> str:" in src
    assert 'if l["state"] in {"stale", "dead", "released"}' in src   # reclaim touches only stale/dead/released, never live
    assert "WRITER_LEASE_HELD" in src                                 # live lease refused
    assert "def renew_lease(" in src and "def release_lease(" in src
    assert "def writer_identity(" in src and "def claim_worktree(" in src and "def check_writer_access(" in src
    assert "STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT" in src and "def same_writer(" in src
    cli = _t("scripts/research.py")
    assert '"--reclaim"' in cli
    assert 'ws.add_parser("release")' in cli and 'ws.add_parser("claim"' in cli and 'ws.add_parser("whoami"' in cli and '"--force"' in cli
    ctrl = _t("research_workflow/governed_controller_v2.py")
    assert "check_writer_access" in ctrl and "_acquire_run_lock" in ctrl   # writer lease gate and run lock are both present and separate


def test_entrypoints_and_quickstart_point_to_the_procedure():
    for rel in ENTRYPOINTS:
        t = _t(rel)
        assert "FOR A NEW RESEARCH PROJECT" in t and "study new <id>" in t and "WORKFLOW.md" in t, rel
    q = _t("docs/QUICKSTART.md")
    assert "## Starting a new concurrent study" in q and "study new <id>" in q and "ws list" in q
    a = _t("docs/AI_AGENTS.md")
    assert "## Starting a research project" in a and "DO NOT manually create a study branch or worktree" in a and "ws list" in a
    for phrase in ("### Writer identity", "NT_RESEARCH_AGENT", "NT_RESEARCH_AGENT_SESSION", "CLAUDE_CODE_SESSION_ID", "ws claim",
                   "STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT", "Read-only roles", "writer lease", "controller run", "worktree isolation"):
        assert phrase in a, phrase
    for rel in ENTRYPOINTS:
        assert "ws claim" in _t(rel) and "STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT" in _t(rel), rel
    for rel in (".claude/AGENT_WORKFLOW.md", ".codex/AGENT_WORKFLOW.md", ".agents/AGENT_WORKFLOW.md"):
        assert "## Writer identity" in _t(rel) and "NT_RESEARCH_AGENT" in _t(rel), rel
    assert 'NT_RESEARCH_AGENT = "codex"' in _t(".codex/config.toml")


def test_agent_role_files_carry_worktree_rules():
    for name in WRITE_CAPABLE:
        t = _t(f".claude/agents/{name}.md")
        for phrase in ("Never write from `main`", "Never share a writer worktree", "study new <id>", "ws list", "`live` lease", "chore/*",
                       "ws whoami", "ws claim <id>", "STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT", "run lock"):
            assert phrase in t, (name, phrase)
    for name in READ_ONLY:
        t = _t(f".claude/agents/{name}.md")
        assert "READ-ONLY" in t and "NO writer claim" in t, name


def test_agent_sync_roster_includes_every_active_role_and_is_current():
    for name in WRITE_CAPABLE + READ_ONLY:
        if name == "Explore":
            continue                                   # Claude-only built-in model pin by design
        assert (ROOT / ".codex" / "agents" / f"{name}.toml").is_file(), name
        assert (ROOT / ".agents" / "agents_staging" / f"{name}.md").is_file(), name
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_agents.py"), "--check"], cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_document_prefers_manual_study_branches_or_work_on_main():
    docs = ["WORKFLOW.md", "docs/QUICKSTART.md", "docs/AI_AGENTS.md", "GEMINI.md", "README.md"]
    for rel in docs:
        for line in _t(rel).splitlines():
            if re.search(r"git (checkout -b|switch -c|branch) study/", line) or (re.search(r"git worktree add", line) and "study/" in line):
                raise AssertionError(f"{rel}: manual study branch creation offered: {line.strip()}")
    w = _t("WORKFLOW.md")
    assert "NEVER START A NEW RESEARCH STUDY BY EDITING MAIN DIRECTLY" in w


def test_mechanism_tests_exist():
    src = _t("scripts/tests/test_workspace.py")
    for name in ("test_study_new_creates_branch_worktree_scaffold_and_lease", "test_second_writer_for_same_worktree_is_refused",
                 "test_dirty_source_worktree_refused", "test_ws_list_reports_worktrees_owners_and_lease_states", "test_ws_list_reclaim_clears_only_stale_and_dead_leases"):
        assert f"def {name}(" in src, name
    race = _t("scripts/tests/test_multi_agent_ownership.py")
    for name in ("test_01_claude_claims_study_a", "test_02_03_foreign_writer_refused_while_claude_live", "test_04_same_session_reentry_is_idempotent",
                 "test_05_three_agents_three_studies_concurrently", "test_06_stale_lease_can_be_claimed_by_another_agent", "test_07_released_lease_can_be_claimed",
                 "test_08_read_only_auditor_inspects_without_writer_claim", "test_09_controller_run_lock_is_independent", "test_10_simultaneous_claims_have_exactly_one_winner"):
        assert f"def {name}(" in race, name

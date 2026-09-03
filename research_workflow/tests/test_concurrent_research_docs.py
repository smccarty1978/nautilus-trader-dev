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
                   "regime_breakout_context", "pullback_quality_target", "cross_market_context", "### M.6 Closure and merge back"):
        assert phrase in w, phrase


def test_lease_states_documented_match_the_implementation():
    src = _t("research_workflow/workspace.py")
    assert "def lease_state(rec: Dict[str, Any]) -> str:" in src
    assert 'if l["state"] in {"stale", "dead", "released"}' in src   # reclaim touches only stale/dead/released, never live
    assert "WRITER_LEASE_HELD" in src                                 # live lease refused
    assert "def renew_lease(" in src and "def release_lease(" in src
    cli = _t("scripts/research.py")
    assert '"--reclaim"' in cli
    assert 'ws.add_parser("release")' in cli


def test_entrypoints_and_quickstart_point_to_the_procedure():
    for rel in ENTRYPOINTS:
        t = _t(rel)
        assert "FOR A NEW RESEARCH PROJECT" in t and "study new <id>" in t and "WORKFLOW.md" in t, rel
    q = _t("docs/QUICKSTART.md")
    assert "## Starting a new concurrent study" in q and "study new <id>" in q and "ws list" in q
    a = _t("docs/AI_AGENTS.md")
    assert "## Starting a research project" in a and "DO NOT manually create a study branch or worktree" in a and "ws list" in a


def test_agent_role_files_carry_worktree_rules():
    for name in WRITE_CAPABLE:
        t = _t(f".claude/agents/{name}.md")
        for phrase in ("Never write from `main`", "Never share a writer worktree", "study new <id>", "ws list", "`live` lease", "chore/*"):
            assert phrase in t, (name, phrase)
    for name in READ_ONLY:
        t = _t(f".claude/agents/{name}.md")
        assert "READ-ONLY" in t, name


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

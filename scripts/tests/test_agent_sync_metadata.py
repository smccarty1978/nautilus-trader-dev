"""W5: the generated Codex agent metadata must match the agent's instructions.

Red Team W5: `.codex/agents/contract-checker.toml` carried
`sandbox_mode = "read-only"` while its own body asserted *"You have `Write` for
exactly this reason."* The value came from a hand-maintained table that was not
updated when the agent gained `Write`.

`sandbox_mode` is now derived from the Claude definition's declared tools, so the
two cannot drift apart again.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sync_agents import (  # noqa: E402
    CODEX_DIR, CODEX_META, CLAUDE_DIR, WRITE_TOOLS, derive_sandbox_mode, load_model_profiles,
    parse_claude_agent, resolve_model,
)

GENERATED = sorted(CODEX_META)


def claude_tools(stem: str) -> set:
    fm, _ = parse_claude_agent(CLAUDE_DIR / f"{stem}.md")
    raw = fm.get("tools", "")
    return {t.strip().strip("[]'\"") for t in raw.replace("[", "").replace("]", "").split(",") if t.strip()}


def codex_value(stem: str, key: str) -> str:
    text = (CODEX_DIR / f"{stem}.toml").read_text(encoding="utf-8")
    m = re.search(rf'^{key} = "([^"]*)"', text, re.MULTILINE)
    assert m, f"{stem}.toml has no {key}"
    return m.group(1)


@pytest.mark.parametrize("stem", GENERATED)
def test_generated_sandbox_mode_matches_declared_tools(stem):
    tools = claude_tools(stem)
    expected = "workspace-write" if tools & set(WRITE_TOOLS) else "read-only"
    assert codex_value(stem, "sandbox_mode") == expected, (
        f"{stem}: Codex sandbox_mode disagrees with the Claude tool declaration {sorted(tools)}"
    )


def test_contract_checker_is_not_rendered_read_only():
    """The exact W5 exploit: instructions assert Write, metadata denied it."""
    body = (CODEX_DIR / "contract-checker.toml").read_text(encoding="utf-8")
    assert "You have `Write` for exactly this reason" in body
    assert 'sandbox_mode = "read-only"' not in body
    assert codex_value("contract-checker", "sandbox_mode") == "workspace-write"


def test_lookahead_auditor_is_not_rendered_read_only():
    """Same latent defect: it writes its own pass report and status.json."""
    assert "Write" in claude_tools("lookahead-auditor")
    assert codex_value("lookahead-auditor", "sandbox_mode") == "workspace-write"


@pytest.mark.parametrize("stem", GENERATED)
def test_no_generated_agent_claims_write_while_declared_read_only(stem):
    text = (CODEX_DIR / f"{stem}.toml").read_text(encoding="utf-8")
    if codex_value(stem, "sandbox_mode") != "read-only":
        return
    for phrase in ("You have `Write`", "Write your report to", "you may write"):
        assert phrase not in text, f"{stem} is read-only but its body says {phrase!r}"


def test_sandbox_mode_is_not_hand_maintained_anymore():
    """One source of truth: the table that drifted must no longer carry the value."""
    for stem, meta in CODEX_META.items():
        assert "sandbox_mode" not in meta, (
            f"{stem}: sandbox_mode is back in CODEX_META; it must be derived from tools"
        )


@pytest.mark.parametrize(
    "tools,expected",
    [
        ("[Read, Grep, Glob]", "read-only"),
        ("[Read, Grep, Glob, Write]", "workspace-write"),
        ("[Read, Grep, Glob, Bash]", "workspace-write"),   # can run pytest -> writes
        ("[Read, Edit]", "workspace-write"),
        ("", "read-only"),
    ],
)
def test_derive_sandbox_mode_rules(tools, expected):
    assert derive_sandbox_mode("x", {"tools": tools}) == expected


def test_generator_reports_in_sync():
    """`--check` must be clean, i.e. the committed artifacts are freshly generated."""
    import subprocess

    proc = subprocess.run(
        [sys.executable, "scripts/sync_agents.py", "--check"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"agent artifacts are out of sync:\n{proc.stdout}\n{proc.stderr}"


def test_codex_models_resolve_from_portable_capability_tiers():
    profiles = load_model_profiles()
    assert resolve_model(harness="codex", capability_tier="balanced_coding", profiles=profiles) == (
        "gpt-5.6-terra", "medium"
    )
    assert resolve_model(harness="codex", capability_tier="fast_discovery", profiles=profiles) == (
        "gpt-5.6-luna", "low"
    )


def test_generated_codex_agents_do_not_use_foreign_provider_models():
    for path in CODEX_DIR.glob("*.toml"):
        text = path.read_text(encoding="utf-8")
        assert 'model = "gemini-' not in text

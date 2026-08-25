"""Generate the Antigravity and Codex agent definitions from the Claude ones.

`.claude/agents/*.md` is the single canonical source. This script emits:

    .agents/agents_staging/<agent>.md   (Antigravity -- body only, no frontmatter)
    .codex/agents/<agent>.toml          (Codex -- TOML with developer_instructions)

Why this exists
---------------
In July 2026 the three harnesses had drifted: the Codex auditor was silently
missing 14 checklist rules, including C4 and D4 -- the #2 and #4 most frequent
finding categories in the repository. An audit that passed under Codex would
fail under Claude, causing rework whenever the user switched harnesses.

Usage
-----
    python scripts/sync_agents.py           # regenerate
    python scripts/sync_agents.py --check   # verify in sync (CI / pre-audit)

Exit codes: 0 in sync, 1 out of sync (--check), 2 invocation error.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_DIR = REPO_ROOT / ".claude" / "agents"
ANTIGRAVITY_DIR = REPO_ROOT / ".agents" / "agents_staging"
CODEX_DIR = REPO_ROOT / ".codex" / "agents"

BANNER = (
    "GENERATED FILE -- DO NOT EDIT.\n"
    "Source of truth: .claude/agents/{stem}.md\n"
    "Regenerate with: python scripts/sync_agents.py"
)

# Per-harness metadata that is NOT derived from the Claude definition.
# Codex/Antigravity run different models, so only the instructions are shared.
# NOTE: `sandbox_mode` is deliberately absent -- it is DERIVED from the Claude
# definition's declared tools by `derive_sandbox_mode`. It used to live here and
# drifted out of sync when contract-checker gained Write (Red Team W5).
CODEX_META: dict[str, dict[str, str]] = {
    "lookahead-auditor": {
        "name": "lookahead_auditor",
        # GPT-5.6 Sol is Codex's frontier model for complex professional work;
        # it replaces the unavailable Gemini 3.5 Pro target for causal audits.
        "model": "gpt-5.6-sol",
        "model_reasoning_effort": "high",
        "approval_policy": "never",
    },
    "contract-checker": {
        "name": "contract_checker",
        "model": "gpt-5.6-sol",
        "model_reasoning_effort": "medium",
        "approval_policy": "never",
    },
    "repo-scout": {
        "name": "repo_scout",
        "model": "gemini-3.6-flash",
        "model_reasoning_effort": "low",
        "approval_policy": "never",
    },
    "implementer": {
        "name": "implementer",
        "model": "gemini-3.5-pro",
        "model_reasoning_effort": "medium",
        "approval_policy": "on-request",
    },
    "research-executor": {
        "name": "research_executor",
        "model": "gpt-5.6-sol",
        "model_reasoning_effort": "medium",
        "approval_policy": "on-request",
    },
    "analysis-decider": {
        "name": "analysis_decider",
        "model": "gpt-5.6-sol",
        "model_reasoning_effort": "high",
        "approval_policy": "never",
    },
}

# Codex agents with no Claude counterpart -- left untouched by this script.
# `implementation-worker` was retired in the 2026-08 agent redesign; the
# `implementer` role is now generated from the Claude definition like every other.
CODEX_ONLY: set[str] = set()

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def parse_claude_agent(path: Path) -> tuple[dict[str, str], str]:
    """Return (frontmatter dict, body) for a Claude agent definition."""
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"{path} has no YAML frontmatter")
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, text[m.end():].lstrip("\n")


def render_antigravity(stem: str, body: str) -> str:
    comment = "\n".join(f"<!-- {ln} -->" for ln in BANNER.format(stem=stem).splitlines())
    return f"{comment}\n\n{body.rstrip()}\n"


# Tools that make an agent capable of changing the workspace. `Bash` counts: an
# agent that can run arbitrary commands is not read-only in any meaningful sense --
# even running pytest writes caches and artifacts.
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit", "MultiEdit", "Bash")


def derive_sandbox_mode(stem: str, fm: dict[str, str]) -> str:
    """Derives the Codex sandbox from the Claude definition's declared tools.

    This must not come from a hand-maintained table. It previously did, and the
    table was not updated when `contract-checker` gained `Write`, so the generated
    Codex artifact asserted `sandbox_mode = "read-only"` while its own instructions
    said *"You have `Write` for exactly this reason."* An agent that writes its own
    audit artifact cannot be rendered read-only, or the harness that runs it will
    silently be unable to comply with its instructions.
    """
    tools_raw = fm.get("tools", "")
    tools = {t.strip().strip("[]'\"") for t in tools_raw.replace("[", "").replace("]", "").split(",")}
    return "workspace-write" if tools & set(WRITE_TOOLS) else "read-only"


def render_codex(stem: str, fm: dict[str, str], body: str) -> str:
    meta = CODEX_META[stem]
    desc = fm.get("description", "").replace('"', r"\"")
    comment = "\n".join(f"# {ln}" for ln in BANNER.format(stem=stem).splitlines())
    sandbox_mode = derive_sandbox_mode(stem, fm)

    # Codex reads Read/Grep/Glob natively; the body references a "Read tool"
    # generically, which is accurate on all three harnesses.
    if "'''" in body:
        raise ValueError(f"{stem}: body contains ''' and cannot be TOML-quoted")

    return (
        f"{comment}\n\n"
        f'name = "{meta["name"]}"\n'
        f'description = "{desc}"\n'
        f'model = "{meta["model"]}"\n'
        f'model_reasoning_effort = "{meta["model_reasoning_effort"]}"\n'
        f'sandbox_mode = "{sandbox_mode}"\n'
        f'approval_policy = "{meta["approval_policy"]}"\n'
        f"\n"
        f"developer_instructions = '''\n"
        f"{body.rstrip()}\n"
        f"'''\n"
    )


def restates_ruleset(body: str) -> list[str]:
    """Detect an agent definition that inlines checklist rules instead of
    referencing docs/CAUSAL_CHECKLIST.md. Inlining is how the harnesses drifted."""
    hits = re.findall(r"^\s*[-*]?\s*\**([A-H]\d{1,2})\.\**\s", body, re.MULTILINE)
    return sorted(set(hits))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="Verify generated files match; do not write")
    args = ap.parse_args()

    if not CLAUDE_DIR.is_dir():
        print(f"error: {CLAUDE_DIR} not found", file=sys.stderr)
        return 2

    ANTIGRAVITY_DIR.mkdir(parents=True, exist_ok=True)
    CODEX_DIR.mkdir(parents=True, exist_ok=True)

    drift: list[str] = []
    checked = 0

    for src in sorted(CLAUDE_DIR.glob("*.md")):
        stem = src.stem
        if stem not in CODEX_META:
            print(f"  skip {stem} (no Codex mapping)")
            continue

        fm, body = parse_claude_agent(src)

        inlined = restates_ruleset(body)
        if inlined:
            drift.append(
                f"{src}: restates checklist rules {inlined} inline. "
                f"Reference docs/CAUSAL_CHECKLIST.md instead -- inlined rules drift."
            )

        targets = {
            ANTIGRAVITY_DIR / f"{stem}.md": render_antigravity(stem, body),
            CODEX_DIR / f"{stem}.toml": render_codex(stem, fm, body),
        }

        for path, want in targets.items():
            checked += 1
            have = path.read_text(encoding="utf-8") if path.exists() else ""
            if have == want:
                continue
            if args.check:
                diff = "\n".join(list(difflib.unified_diff(
                    have.splitlines(), want.splitlines(),
                    fromfile=f"{path} (on disk)", tofile=f"{path} (expected)",
                    lineterm="", n=1,
                ))[:25])
                drift.append(f"{path} is out of sync:\n{diff}")
            else:
                path.write_text(want, encoding="utf-8")
                print(f"  wrote {path.relative_to(REPO_ROOT)}")

    for stem in sorted(CODEX_ONLY):
        p = CODEX_DIR / f"{stem}.toml"
        if p.exists():
            print(f"  kept {p.relative_to(REPO_ROOT)} (Codex-only, not generated)")

    if args.check:
        if drift:
            print(f"\nAGENT PARITY: FAIL ({len(drift)} problem(s))\n")
            for d in drift:
                print(f"- {d}\n")
            print("Run: python scripts/sync_agents.py")
            return 1
        print(f"AGENT PARITY: OK ({checked} generated files match canonical source)")
        return 0

    if drift:
        print(f"\nWARNING: {len(drift)} definition(s) inline checklist rules:\n")
        for d in drift:
            print(f"- {d}\n")
    print(f"\nSynced {checked} files from {CLAUDE_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

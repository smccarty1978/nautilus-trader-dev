# Claude Code — Harness Launch Notes

**This file is deliberately thin.** It holds only the Claude-Code-specific launch mechanics.
Everything else moved to where it can be maintained once:

| You want | Read |
|---|---|
| How the research system works | `docs/RESEARCH_WORKFLOW.md` — **authoritative** |
| The shared agent operating core | `AGENTS.md` |
| Claude-specific guidance | `CLAUDE.md` |
| Subagent roster and why it is this set | `AGENTS.md` §11, `docs/SUBAGENT_ROSTER.md` |
| The audit ruleset | `docs/CAUSAL_CHECKLIST.md` |

This file, `.agents/AGENT_WORKFLOW.md` and `.codex/AGENT_WORKFLOW.md` were three
hand-maintained near-copies of the same content, and they drifted. Do not re-expand them.

---

## Model routing

Agent model ids live in the frontmatter of `.claude/agents/*.md` (canonical) and in
`CODEX_META` in `scripts/sync_agents.py` (per-harness).

> **Do NOT set `CLAUDE_CODE_SUBAGENT_MODEL` to a fixed model.** Leave it unset or set it to
> `inherit`, so each agent file's `model:` frontmatter controls routing. Pinning it globally
> silently overrides the tiering.

`.claude/agents/Explore.md` exists **only** to pin the built-in `Explore` agent to Haiku —
without it, `Explore` inherits the orchestrator's model. Deleting that file restores
Opus-cost discovery.

---

## Launch commands by risk tier

Tiers are defined in `CLAUDE.md` §7.

**Tier 1 — small fix, diagnostic, docs**

```bash
claude --model claude-sonnet-5 --dangerously-skip-permissions
```

**Tier 2 — normal research study**

```bash
claude --model claude-sonnet-5 --dangerously-skip-permissions
```

**Tier 3 — model freeze / deployment / cross-timeframe strategy**

Planning:

```bash
claude --model opusplan --permission-mode plan --allow-dangerously-skip-permissions
```

Implementation, after the plan is approved:

```bash
claude --model claude-sonnet-5 --dangerously-skip-permissions
```

---

## Agent definition parity

`.claude/agents/*.md` is canonical. The other harnesses are generated:

```bash
python scripts/sync_agents.py           # regenerate Codex + Antigravity
python scripts/sync_agents.py --check   # verify in sync (CI / pre-audit)
```

Do not hand-edit `.agents/agents_staging/*.md` or `.codex/agents/*.toml`. The harnesses
previously drifted far enough that the Codex auditor was silently missing 14 checklist rules,
including C4 and D4 — the #2 and #4 most frequent finding categories in this repository.

`.codex/agents/implementation-worker.toml` is Codex-only and is not generated; edit it
directly.

---

## Hooks

`.claude/hooks/validate-results-triager-command.py` — a `PreToolUse` hook scoped to
`results-triager`, restricting its Bash to pytest with no chaining, pipes, redirection, or
command substitution.

---

## Required delegation packet

Every subagent prompt must be self-contained — children do not inherit the parent
conversation:

exact objective · exact subsystem or paths · relevant symbols · applicable spec sections ·
required output format and word cap · explicit prohibitions · known facts vs. open questions.

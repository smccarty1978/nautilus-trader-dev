# Antigravity — Harness Launch Notes

**This file is deliberately thin.** It holds only Antigravity-specific harness mechanics.
Everything else moved to where it can be maintained once:

| You want | Read |
|---|---|
| How the research system works | `docs/RESEARCH_WORKFLOW.md` — **authoritative** |
| The shared agent operating core | `AGENTS.md` |
| Subagent roster and why it is this set | `AGENTS.md` §11, `docs/SUBAGENT_ROSTER.md` |
| The audit ruleset | `docs/CAUSAL_CHECKLIST.md` |

This file, `.claude/AGENT_WORKFLOW.md` and `.codex/AGENT_WORKFLOW.md` were three
hand-maintained near-copies of the same content, and they drifted. Do not re-expand them.

---

## Model mapping

Antigravity runs these subagents natively on Gemini models. The portable capability tiers and
all harness mappings are defined in `config/agent_model_profiles.json`.

| Agent | Claude tier | Gemini equivalent | Flag |
|---|---|---|---|
| `repo-scout` | fast discovery / low | Gemini 3.6 Flash / Flash Lite | `flash` / `flash_lite` |
| `lookahead-auditor` | high assurance / high | Gemini Pro | `pro` |
| `contract-checker` | governance review / medium | Gemini Pro / 3.6 Flash | `pro` / `flash` |
| `implementer` | balanced coding / medium | Gemini Pro | `pro` |
| `research-executor` | balanced coding / medium | Gemini Pro | `pro` |
| `analysis-decider` | high assurance / high | Gemini Pro | `pro` |

Tiering rule: the cheapest model that can be trusted with the decision. **Never put a
research-blessing gate on a Flash-tier model.** Do not escalate a model because a task is
long.

---

## Agent definition parity

`.claude/agents/*.md` is canonical. `.agents/agents_staging/*.md` is generated — body only,
no frontmatter:

```bash
python scripts/sync_agents.py           # regenerate
python scripts/sync_agents.py --check   # verify in sync
```

Do not hand-edit the staged Markdown. The harnesses previously drifted far enough that one
auditor was silently missing 14 checklist rules, including C4 and D4 — the #2 and #4 most
frequent finding categories in this repository.

`Explore` is a Claude-only model pin and has no Antigravity counterpart. Every other agent is
generated for all three harnesses.

---

## Writer identity (multi-agent ownership)

The writer lease identifies a writer as `user@host` + agent + session
(`research_workflow.workspace.writer_identity`). The Antigravity launcher must export
`NT_RESEARCH_AGENT=antigravity` and `NT_RESEARCH_AGENT_SESSION=<uuid unique to this session>` into
the shells it spawns (the harness's own `ANTIGRAVITY_SESSION_ID`, if present, is accepted as the
session; otherwise the process-tree anchor of the Antigravity process is used and the agent name
is inferred from that process's name). Verify with `python scripts/research.py ws whoami`; claim an
existing study with `ws claim <id>` before writing. A live lease of another agent refuses with
`STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT` even though the OS user matches.

---

## Required delegation packet

Every subagent prompt must be self-contained — children do not inherit the parent
conversation:

exact objective · exact subsystem or paths · relevant symbols · applicable spec sections ·
required output format and word cap · explicit prohibitions · known facts vs. open questions.

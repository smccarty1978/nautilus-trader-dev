# Codex — Harness Launch Notes

**This file is deliberately thin.** It holds only Codex-specific harness mechanics.
Everything else moved to where it can be maintained once:

| You want | Read |
|---|---|
| How the research system works | `docs/RESEARCH_WORKFLOW.md` — **authoritative** |
| The shared agent operating core | `AGENTS.md` |
| Codex-specific guidance | `CODEX.md` |
| Subagent roster and why it is this set | `AGENTS.md` §11, `docs/SUBAGENT_ROSTER.md` |
| The audit ruleset | `docs/CAUSAL_CHECKLIST.md` |

This file, `.claude/AGENT_WORKFLOW.md` and `.agents/AGENT_WORKFLOW.md` were three
hand-maintained near-copies of the same content, and they drifted. Do not re-expand them.

---

## Agent identifiers

Codex `agent_type` values use **underscores**; Claude names are hyphenated. Filenames stay
hyphenated for easy cross-harness comparison.

| Claude | Codex `agent_type` | Model | Reasoning | Access |
|---|---|---|---|---|
| — (main session) | — | session model | session effort | user-selected permission mode |
| `repo-scout` | `repo_scout` | `gpt-5.6-luna` | low | read-only |
| `lookahead-auditor` | `lookahead_auditor` | `gpt-5.6-sol` | high | read-only + own audit artifacts |
| `contract-checker` | `contract_checker` | `gpt-5.6-sol` | medium | read-only + own audit artifacts |
| `implementer` | `implementer` | `gpt-5.6-terra` | medium | workspace-write |
| `research-executor` | `research_executor` | `gpt-5.6-terra` | medium | workspace-write |
| `analysis-decider` | `analysis_decider` | `gpt-5.6-sol` | high | workspace-write (reports only) |

Model ids are resolved from portable capability tiers in
`config/agent_model_profiles.json` by `scripts/sync_agents.py`. `sandbox_mode` is **derived**
from the Claude definition's declared tools, not set in the model profile.

---

## Agent definition parity

`.claude/agents/*.md` is canonical. `.codex/agents/*.toml` is generated:

```bash
python scripts/sync_agents.py           # regenerate
python scripts/sync_agents.py --check   # verify in sync
```

Do not hand-edit the generated TOML. The harnesses previously drifted far enough that the
Codex auditor was silently missing 14 checklist rules, including C4 and D4 — the #2 and #4
most frequent finding categories in this repository.

**Every agent is generated.** There are no Codex-only agents; `implementation-worker` was
retired in the 2026-08 redesign and replaced by the generated `implementer`.

---

## Config and hooks

- `.codex/config.toml` — agents enabled, `max_concurrent_threads_per_session = 4`.
- `.codex/hooks/deny-subagent-tool.py` — enforces the boundary that worker and coding agents
  cannot spawn subagents. Only the main orchestrator invokes the named gates.

---

## Writer identity (multi-agent ownership)

The writer lease identifies a writer as `user@host` + agent + session
(`research_workflow.workspace.writer_identity`). `.codex/config.toml` sets
`NT_RESEARCH_AGENT = "codex"` for every Codex shell (`[shell_environment_policy]`). The session id
comes from `NT_RESEARCH_AGENT_SESSION` when the launcher exports one (recommended: a uuid per Codex
session), else from `CODEX_THREAD_ID` / `CODEX_SESSION_ID` if the harness exports them, else from the
process-tree anchor (the Codex process at the top of the shell's ancestry -- stable for one
session). Verify with `python scripts/research.py ws whoami`; claim an existing study with
`ws claim <id>` before writing. A live lease of another agent refuses with
`STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT` even though the OS user matches.

---

## Required delegation packet

Every subagent prompt must be self-contained — children do not inherit the parent
conversation:

exact objective · exact subsystem or paths · relevant symbols · applicable spec sections ·
required output format and word cap · explicit prohibitions · known facts vs. open questions.

`implementer` additionally requires a **frozen task packet**: exact objective, root cause or
approved interpretation, exact files allowed to change, required behaviour, forbidden semantic
changes, acceptance tests, and stop-and-escalate conditions.

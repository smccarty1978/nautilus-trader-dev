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
| `repo-scout` | `repo_scout` | `gemini-3.6-flash` | low | read-only |
| `contract-checker` | `contract_checker` | `gpt-5.6-sol` | medium | read-only + own audit artifacts |
| `lookahead-auditor` | `lookahead_auditor` | `gpt-5.6-sol` | high | read-only + own audit artifacts |
| `results-triager` | `results_triager` | `gemini-3.6-flash` | low | guarded pytest only |
| — | `implementation_worker` | `gemini-3.5-pro` | medium | workspace-write |

Model ids are declared in `CODEX_META` in `scripts/sync_agents.py`. `sandbox_mode` is
**derived** from the Claude definition's declared tools, not set here — it used to live in
`CODEX_META` and drifted out of sync when `contract-checker` gained `Write`.

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

**`.codex/agents/implementation-worker.toml` is Codex-only and is NOT generated.** It has no
Claude counterpart; `sync_agents.py` leaves it alone. Edit it directly.

---

## Config and hooks

- `.codex/config.toml` — agents enabled, `max_concurrent_threads_per_session = 4`.
- `.codex/hooks/deny-subagent-tool.py` — enforces the boundary that worker and coding agents
  cannot spawn subagents. Only the main orchestrator invokes the named gates.
- `.codex/hooks/validate-results-triager-command.py` — restricts `results_triager` Bash to
  pytest with no chaining, pipes, redirection, or command substitution.

---

## Required delegation packet

Every subagent prompt must be self-contained — children do not inherit the parent
conversation:

exact objective · exact subsystem or paths · relevant symbols · applicable spec sections ·
required output format and word cap · explicit prohibitions · known facts vs. open questions.

`implementation_worker` additionally requires a **frozen task packet**: exact objective, root
cause or approved interpretation, exact files allowed to change, required behaviour,
forbidden semantic changes, acceptance tests, and stop-and-escalate conditions.

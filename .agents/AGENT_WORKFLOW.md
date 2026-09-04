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
(`research_workflow.workspace.writer_identity`). Antigravity IDE is a VS Code fork: its terminals
export only the generic `vscode` variables (`TERM_PROGRAM=vscode`, `VSCODE_*`), so nothing native names
the agent or a per-session id, and Antigravity IDE is single-instance (a second launch opens a window
inside the running instance and inherits its environment). The sanctioned launcher therefore supplies
the identity -- **one command, no manual UUID**:

```bat
scripts\launch_antigravity.cmd -Study <study_id>        REM opens that study's worktree in a fresh instance
scripts\launch_antigravity.cmd -Path <folder>           REM any folder (e.g. a chore worktree)
```

It generates a fresh UUID per launch and starts `Antigravity IDE.exe` with
`NT_RESEARCH_AGENT=antigravity` and `NT_RESEARCH_AGENT_SESSION=<uuid>` in its environment; every
terminal and agent command inside that instance inherits them. If an instance is already running it
refuses (`ANTIGRAVITY_INSTANCE_ALREADY_RUNNING`): `-Force` opens a window of the running instance
(shares its session), `-Isolated` starts an independent second instance with its own
`--user-data-dir` (own UUID; fresh sign-in). The agent label alone is also inferred automatically
from the process tree (`antigravity ide.exe` in the shell's ancestry) -- the launcher is what makes the
**session** unique.

**Fail closed.** Before writing, every write-capable Antigravity role runs

```bash
python scripts/research.py ws whoami --expect antigravity
```

and continues only on `STATUS: OK`. `WRITER_IDENTITY_AMBIGUOUS` (resolved as `human`/unknown) or
`WRITER_IDENTITY_MISMATCH` means the session was not launched through the wrapper: stop, do not
write. `study new <id> --as antigravity` and `ws claim <id> --as antigravity` enforce the same check
mechanically. Read-only reviewers need no writer ownership and skip all of this.

---

## Required delegation packet

Every subagent prompt must be self-contained — children do not inherit the parent
conversation:

exact objective · exact subsystem or paths · relevant symbols · applicable spec sections ·
required output format and word cap · explicit prohibitions · known facts vs. open questions.

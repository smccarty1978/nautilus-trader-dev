# Claude Code Agent Workflow

## Purpose

This project uses bounded subagents to keep repository exploration, contract checking, test triaging, and causal auditing out of the flagship model's main context while keeping API costs and execution errors low.

These agents share access to the project filesystem, but each subagent begins with its own prompt context. Every delegated prompt must therefore be self-contained.

---

## Agent Roster & Pinned Model Routing

| Agent | Pinned Model | Tools | Output Budget | Purpose |
|---|---|---|---|---|
| `repo-scout` | `claude-haiku-4-5` | Read, Grep, Glob | Max 700 words | Locate code and trace execution paths |
| `contract-checker` | `claude-sonnet-5` | Read, Grep, Glob | Max 1,000 words | Check explicit contracts and invariants |
| `results-triager` | `claude-haiku-4-5` | Read, Grep, Glob, Bash | Max 500 words | Run bounded pytest commands and summarize failures |
| `lookahead-auditor` | `claude-sonnet-5` | Read, Grep, Glob, Bash, Write | Max 1,500 words | Independent pre-execution causal audit |

> **Note on Model Configuration:**
> Do NOT set `CLAUDE_CODE_SUBAGENT_MODEL` to a fixed model in your environment (leave it unset or set to `inherit`). This allows each agent file's frontmatter `model:` field to control the exact routing (`claude-haiku-4-5` or `claude-sonnet-5`).

---

## Risk Tiering & Launch Policies

Not every task requires the full agent ceremony. Launch sessions according to risk tier:

### Tier 1: Small Diagnostic / Minor Utility / Docs
* **Workflow**: Main session $\rightarrow$ run deterministic tests $\rightarrow$ 1-day/local smoke run.
* **Subagents**: None by default. No auditor unless causal/timing logic changed.
* **Launch Command**:
  ```bash
  claude --model claude-sonnet-5 --dangerously-skip-permissions
  ```

### Tier 2: Normal Research Study
* **Workflow**: `research_decision.yaml` (create/verify) $\rightarrow$ `SPEC.md` $\rightarrow$ `study.yaml` $\rightarrow$ `python scripts/create_study.py --config study.yaml` $\rightarrow$ `python scripts/compile_study.py` $\rightarrow$ deterministic preflight (`scripts/research_preflight.py` CLEAR) $\rightarrow$ split pre-execution audit $\rightarrow$ Staged runner (`scripts/run_bounded_study.py`) $\rightarrow$ completion contract check. Re-audit causality only after an audited-surface change.
* **Contract Checker**: Optional; invoke only when causal contracts or timeframe rules changed.
* **Launch Command**:
  ```bash
  claude --model claude-sonnet-5 --dangerously-skip-permissions
  ```

### Tier 3: Model Freeze / Deployment / Cross-Timeframe Strategy
* **Workflow**: `research_decision.yaml` (create/verify) $\rightarrow$ `SPEC.md` $\rightarrow$ `study.yaml` $\rightarrow$ `python scripts/create_study.py` $\rightarrow$ deterministic preflight $\rightarrow$ split pre-execution audit $\rightarrow$ Staged runner $\rightarrow$ completion contract check. Re-audit causality only after an audited-surface change.
* **Planning Launch**:
  ```bash
  claude --model opusplan --permission-mode plan --allow-dangerously-skip-permissions
  ```
* **Implementation Launch** (after plan is approved):
  ```bash
  claude --model claude-sonnet-5 --dangerously-skip-permissions
  ```

---

## Token-Minimization & Execution Rules

1. **Deterministic Preflight First**: Run `python scripts/research_preflight.py --study studies/<name>` before calling any subagent. If preflight is `BLOCKED`, read `audit/failure_packet.json` and fix locally.
2. **Worker Subagent Boundary**: Worker and coding agents cannot spawn additional subagents. Only the main orchestrator may invoke named mandatory repository gates.
3. **Deterministic Runner over Agent Monitoring**: Use `scripts/run_bounded_study.py` to monitor execution runtime, memory, stale log updates, and timeouts. Do not spawn subagents to watch background process logs.
4. **Contextual Diff-First Auditing**: Auditors must review the contextual diff (`git diff -U20`) inside `audit_packet.json` first. Full files are read only when structural dependencies or state flow are unresolved in the diff.
5. **No Unchanged File Re-discovery**: Do not reopen unchanged files to repeat discovery. Read an unchanged file only when its full context is required to resolve a current causal/audit question.
6. **Structured & Compact Outputs**: Subagents must use concise tables, file:line citations, and paths instead of narrative explanations or repeated SPEC summaries.
7. **No Automatic Stage Expansion**: Always run bounded stages (synthetic $\rightarrow$ 1-day $\rightarrow$ 1-week $\rightarrow$ 1-month) and verify metrics before expanding.
8. **Parity Failure First-Divergence Rule**: For any parity failure, no broad repository exploration is permitted until `scripts/find_first_parity_divergence.py` is executed to pinpoint the exact timestamp, stage, and field difference.
9. **Research Decision Contract Authority**: Never improve, broaden, clean up, or make a study more statistically pure by changing a fixed baseline or adding feature discovery unless `research_decision.yaml` explicitly permits it. If a design concern exists, surface it as a caveat; do not silently alter the experiment.

---

## The Split Audit Gate

Rules live in `docs/CAUSAL_CHECKLIST.md` — the single source of truth shared by
Claude, Codex, and Antigravity. Agent definitions reference it; they never
restate it.

### Order of operations (cheapest first)

| # | Step | Cost | Catches |
|---|---|---|---|
| 0 | `python scripts/research_preflight.py --study studies/<name>` | free | AST causal linting, schema validation, model binding, and fast causal canaries |
| 1 | `contract-checker` on the Deliverables Manifest | 1,000w | missing artifacts, unreachable terminal labels, seal integrity, C4/D/E |
| 2 | `lookahead-auditor` on the causal contract | 1,500w | state flow, callback ordering, cross-file convention conflicts, train/serve divergence |

Preflight must be `CLEAR` before Steps 1 and 2 may run. If preflight is `BLOCKED`, the agent must inspect `audit/failure_packet.json` and fix locally.
Steps 1 and 2 have **disjoint scope** and may run in parallel. Never let one report the other's category.

### Why the split exists

Across ~100 historical audit reports, ~60% of blocking findings were
completeness issues (`D1` 22, `C4` 22, `C3` 12, `D4` 9) rather than look-ahead.
The causal checklist has no natural stopping point for completeness, so the
auditor invented new findings each pass —
`studies/codex_5.6_short_rth_enriched_volume_level_retrain/` ran **18 passes**.

### Re-audit protocol

Pass 2+ must:

1. Adjudicate **every** prior finding (`FIXED` / `NOT FIXED` / `WITHDRAWN`) with
   one line of evidence, *before* raising anything new.
2. Raise **at most 3 new CRITICAL findings per pass.**
3. Never re-raise an addressed finding under new framing — mark the original
   `NOT FIXED` instead.

### Artifacts

* `audit/pass_<NN>.md` — a **new** file per pass. Never append.
* `audit/status.json` / `audit/contract_status.json` — machine-readable verdict.

Gates read the JSON. Prose is for humans. A gate that greps a 1,240-line
append-only report for "critical" and "0" passes on a failing audit that merely
contains an earlier clean summary — this actually happened.

---

## Agent Definition Parity

`.claude/agents/*.md` is **canonical**. The other harnesses are generated:

```bash
python scripts/sync_agents.py           # regenerate Codex + Antigravity
python scripts/sync_agents.py --check   # verify in sync
```

Do not hand-edit `.agents/agents_staging/*.md` or `.codex/agents/*.toml`. The
harnesses previously drifted far enough that the Codex auditor was missing 14
checklist rules, including `C4` and `D4` — the #2 and #4 most frequent finding
categories in the repository.

---

## Required Delegation Packet

Every subagent prompt must include:

* Exact objective
* Exact subsystem or paths
* Relevant symbols
* Applicable specification sections
* Required output format & word cap
* Explicit prohibitions
* Known facts vs. unresolved questions

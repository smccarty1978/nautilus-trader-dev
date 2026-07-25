# Antigravity Agent Workflow

This workspace supports delegating tasks to specialized subagents to optimize context usage and control API costs. 

When running in **Antigravity**, these subagents run natively using Google Gemini models, which offer massive context windows and high execution speeds.

---

## Agent Roster and Gemini Model Mapping

| Subagent Name | Claude Model (Original) | Gemini Equivalent Model | Antigravity Model Flag | Purpose |
|---|---|---|---|---|
| `repo-scout` | Haiku | Gemini 3.6 Flash / Flash Lite | `flash` / `flash_lite` | Locate code and trace execution paths |
| `contract-checker` | Sonnet | Gemini Pro / 3.6 Flash | `pro` / `flash` | Verify specifications and invariant compliance |
| `results-triager` | Haiku | Gemini 3.6 Flash / Flash Lite | `flash` / `flash_lite` | Run test commands and triage results |
| `lookahead-auditor` | Sonnet | Gemini Pro | `pro` | Deep causal audit for look-ahead bias |


---

## Invoking Subagents in Antigravity

Antigravity handles subagent registration and calling natively via its model orchestration loop.

### How to Invoke
Simply request the flagship model to run the task on a subagent. For example:
> *"Invoke lookahead-auditor on strategies/short_rth_entry_surface_backfill/"*

The flagship model will use the `invoke_subagent` tool with the corresponding prompt template and target model flag.

### Coordination Rules
* **Parallel Checks**: Multiple read-only subagents (`repo-scout`, `contract-checker`) can run in parallel safely.
* **Context Preservation**: Subagents return condensed Markdown summaries rather than raw code dumps to keep the main conversation context clean.
* **Audit Enforcement**: The `lookahead-auditor` must be run on any modified strategy or data-loading script before declaring a study complete.

---

## Lean Workflow, Token Budgets, and Standing Authorization

These rules are harness-independent and are maintained in one place. See:

* `AGENTS.md` § Subagent Routing & Lean Workflow — risk tiers, per-agent output
  word caps, diff-first auditing, deterministic run bounding via
  `scripts/run_bounded_study.py`.
* `AGENTS.md` § Standing Authorization for Named Mandatory Agent Gates — which
  gates may be invoked without asking, and the limits on that authorization.

Antigravity-specific note: the Gemini model mapping above determines which model
backs each agent, but the output caps and gate scoping are identical to the
Claude and Codex harnesses.

---

## The Split Audit Gate (harness-neutral protocol)

Rules live in `docs/CAUSAL_CHECKLIST.md` — the single source of truth shared by
Claude, Codex, and Antigravity. Agent definitions reference it; they never
restate it. This file previously drifted: the Codex auditor was missing 14
checklist rules including `C4` and `D4`, the #2 and #4 most frequent finding
categories in the repository, so an audit passing on one harness failed on
another.

### Order of operations (cheapest first)

| # | Step | Cost | Catches |
|---|---|---|---|
| 0 | `python scripts/causal_lint.py --study studies/<name>` | free | H4 trigger-price fills, `ts_event` session gates, `center=True`, `.shift(-N)`, `bfill`, bare `merge_asof`, random CV, non-`*.v.0` symbols |
| 1 | `contract_checker` on the Deliverables Manifest | 1,000w | missing artifacts, unreachable terminal labels, seal integrity, C4/D/E |
| 2 | `lookahead_auditor` on the causal contract | 1,500w | state flow, callback ordering, cross-file convention conflicts, train/serve divergence |

Steps 1 and 2 have **disjoint scope** (see `docs/CAUSAL_CHECKLIST.md` § SCOPE
SPLIT) and may run in parallel. Never let one report the other's category.

### Why the split exists

Across ~100 historical audit reports, ~60% of blocking findings were
completeness issues rather than look-ahead. The causal checklist has no natural
stopping point for completeness, so the auditor invented new findings each pass
— `studies/codex_5.6_short_rth_enriched_volume_level_retrain/` ran **18 passes**
and produced a 1,240-line append-only `audit.md`.

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

Gates read the JSON, never the prose. A gate that greps a long append-only
report for "critical" and "0" passes on a failing audit that merely contains an
earlier clean summary — this actually happened.

---

## Agent Definition Parity

`.claude/agents/*.md` is **canonical**. Codex (`.codex/agents/*.toml`) and
Antigravity (`.agents/agents_staging/*.md`) definitions are **generated** — do
not hand-edit them.

```bash
python scripts/sync_agents.py           # regenerate
python scripts/sync_agents.py --check   # verify in sync
```

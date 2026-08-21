# Codex Multi-Agent Workflow

## Agent roster

| Agent | Model | Reasoning | Default access | Purpose |
|---|---|---|---|---|
| Main session | Current session model | Current session effort | User-selected permission mode | Plan, orchestrate, integrate, approve |
| `repo_scout` | `gemini-3.6-flash` | Low | Read-only | Repository discovery (Max 700w) |
| `contract_checker` | `gpt-5.6-sol` | Medium | Read-only | Specification compliance (Max 1000w) |
| `implementation_worker` | `gemini-3.5-pro` | Medium | Workspace write | Bounded implementation |
| `results_triager` | `gemini-3.6-flash` | Low | Guarded pytest only | Test-output reduction (Max 500w) |
| `lookahead_auditor` | `gpt-5.6-sol` | High | Read-only | Independent pre-execution audit; parent persists report (Max 1500w, diff-first) |

---

## Risk Tiering & Gates

Before running subagents, classify the task into a risk tier:

* **Tier 1 (Diagnostic / Utility)**: Main session $\rightarrow$ run deterministic tests $\rightarrow$ local smoke check. No planning or audit agents.
* **Tier 2 (Normal Research Study)**: Main-session planning (`repo_scout` only if discovery is needed) $\rightarrow$ Main implementation + tests $\rightarrow$ split pre-execution audit $\rightarrow$ Staged runner (`scripts/run_bounded_study.py`) $\rightarrow$ completion contract check. Re-audit causality only after an audited-surface change.
* **Tier 3 (Model Freeze / Deployment)**: `repo_scout` $\rightarrow$ Frozen task packet $\rightarrow$ Main-session implementation (or one bounded `implementation_worker`) + tests $\rightarrow$ split pre-execution audit $\rightarrow$ Staged runner $\rightarrow$ completion contract check. Re-audit causality only after an audited-surface change.

---

## Token-Efficiency & Process Rules

1. **Deterministic Runner**: Use `scripts/run_bounded_study.py` to monitor runtime execution, timeouts, and stale log updates. Do not spend LLM tokens monitoring process state.
2. **Contextual Diff-First Audits**: `lookahead_auditor` reviews the contextual diff (`git diff -U20`) inside `audit_packet.json` first. Full source files are read only when structural dependencies or state flow are unresolved in the diff. It returns the complete report; the main session writes that response to the packet's requested audit path.
3. **Strict Word Caps**:
   * `repo_scout`: Max 700 words. Paths, symbols, and line numbers only.
   * `contract_checker`: Max 1,000 words. Compliance table and blocking verdict only.
   * `results_triager`: Max 500 words. Root cause test failures only.
   * `lookahead_auditor`: Max 1,500 words. Findings sorted by severity only.

---

## Standing Authorization for Named Mandatory Agent Gates

Named mandatory gates in this repository constitute standing user authorization for the main orchestrator to invoke the specifically named agent when that gate condition is reached.

This authorization applies only to:

- `repo_scout` where the selected risk tier requires it
- `contract_checker` where the selected risk tier requires it
- `results_triager` for exact approved test commands
- `lookahead_auditor` at mandatory causal or look-ahead audit gates

The invocation must remain limited to the scope of the named gate.

This standing authorization does not permit:

- discretionary agent use
- unnamed or general-purpose agents
- broad parallel fan-out
- nested delegation
- workers spawning subagents
- expanding the audit into implementation work
- code modifications by an audit-only agent

Session-level instructions prohibiting discretionary agent spawning remain in force. They do not prevent execution of a specifically named mandatory repository gate covered by this standing authorization.

If a mandatory gate and a session-level restriction appear to conflict, the orchestrator should:

1. invoke only the specifically named mandatory gate;
2. keep the scope limited to the gate’s defined responsibilities;
3. avoid all additional agent delegation; and
4. have the main session persist the read-only auditor's returned report and verdict in the study artifacts.

Passing criteria remain governed by the applicable frozen contract or SPEC. Standing authorization to invoke an auditor does not relax the audit acceptance standard. Do not mark the work finalized unless the audit satisfies the acceptance gate defined by the applicable frozen SPEC. At minimum, any CRITICAL finding blocks finalization. Any WARNING must either be remediated or explicitly adjudicated according to the SPEC; do not silently treat an unresolved WARNING as cleared.

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

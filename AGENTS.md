# AGENTS.md — Shared Agent Operating Core

This is the **common core** every agent in this repository inherits, regardless of harness.

- **Claude** also reads `CLAUDE.md`.
- **Codex** also reads `CODEX.md`.
- **The authoritative description of the system is `docs/RESEARCH_WORKFLOW.md`.**
  This file does not restate it. When you need a path, a stage, a script, an error code, or
  a contract, go there.

---

## 1. Mission

Produce quantitative research results that are **causally sound, reproducible, and honestly
reported**. Every rule below exists because a specific defect once produced a plausible
wrong number that nobody caught.

The two failure modes to fear, in order:

1. A result that is wrong in a way that looks right.
2. A result nobody can reproduce through the contracts.

Slowness is not in the top two.

---

## 2. Repository architecture (one screen)

| Directory | Owns |
|---|---|
| `features/` | Canonical feature definitions, providers, resolver, authority bundle |
| `research_workflow/` | The reusable governed research lifecycle, the generic collector, modeling, analysis, forward outcomes |
| `research/` | Analysis harness, schemas, engines, study types |
| `studies/<id>/` | One study's hypothesis, contracts, decisions, audits, results, and all execution run outputs (`runs/`, `_work/`). Small hooks only |
| `strategies/` | Executable trading strategies only |
| `backtests/` | NT runtime (`nt_runtime/`) and the two supported entrypoints |
| `scripts/` | Operational, audit, lifecycle and diagnostic CLIs. Reusable tooling only — no study-specific scripts |
| `archive/`, `scratch/`, `features/archive/` | Historical or generated. Never an active implementation |
| `runs/` (root) | Legacy run outputs from pre-migration studies only. New studies write to `studies/<id>/runs/` |

```
NEW STUDY != NEW INFRASTRUCTURE
```

Full map: `docs/RESEARCH_WORKFLOW.md` §1.

---

## 3. Mandatory lifecycle

```
PREPARE+FREEZE -> READINESS -> PREFLIGHT -> CAUSAL REVIEW -> CONTRACT REVIEW -> SEAL
   -> NT SMOKE -> RECONCILE -> AUTHORIZE -> TRAIN COLLECT (partitioned) -> MERGE
   -> FIT -> TRAIN FREEZE -> OOS OPEN -> OOS -> ANALYSIS -> DECISION
```

Detail, entry points and outputs: `docs/RESEARCH_WORKFLOW.md` §3.

Non-negotiable properties of that order:

- **No execution before the seal.** No collection, label build, training, backtest or staged
  run happens before preflight is `CLEAR` and both reviews have issued a status.
- **The freeze goes stale on any execution-affecting change.** Re-run PREPARE, then redo
  preflight → reviews → seal. `research_workflow/__init__.py` is inside the execution
  closure; even a cosmetic `__all__` edit stales a sealed study.
- **Gates read JSON.** `audit/status.json`, `audit/contract_status.json`,
  `audit/preflight.json`. Never prose. A gate that greps a long report for "critical" and
  "0" passes on a failing audit that happens to contain an earlier clean summary — that has
  actually happened here.
- **The two reviews have disjoint scope** and neither may report the other's category
  (`docs/CAUSAL_CHECKLIST.md`). That boundary is what stopped 18-pass audit loops.
- **Re-audits are bounded.** Pass 2+ adjudicates every prior finding before raising new
  ones; at most 3 new CRITICALs per pass; a **new** `audit/pass_NN.md` file, never an append.

---

## 4. Causality and TRAIN/OOS

**Contract authority:** `research_decision.yaml > SPEC.md > study.yaml > compiled_study.json > code`.

- NautilusTrader is the **only** execution environment for signal detection, validation and
  backtesting. Pandas loads raw data and post-analyses NT outputs. Nothing else.
- Indicators compute on **completed bars only**.
- Bar timestamps: catalog `ts_event` is OPEN-stamped; `ts_init = ts_event + bar_duration_ns`.
  1s bars arrive **before** their parent 1m bar — buffer and replay them retroactively from
  fill time or you will miss the first minute of price action.
- **OOS may not influence** feature selection, preprocessing, model class, hyperparameters,
  calibration, thresholds, or deciles. Those are frozen into
  `artifacts/train_experiment_freeze.json` *before* OOS opens.
- `research_workflow.experiment.assert_oos_open` is the only door. Do not route around it.
- **Forward outcomes are labels, never inputs.** `research_workflow/forward_outcomes/guard.py` fails closed at
  fit time and at freeze time. Never loosen it — its patterns are anchored precisely so that
  `rolling_300s_giveback_atr` (causal) passes while `max_mfe_atr` (post-event) is caught.
- **Never improve a study.** Do not broaden a baseline, clean up a population, or add feature
  discovery to make a study more statistically pure unless the decision contract explicitly
  permits it. Surface the concern as a caveat; do not silently alter the experiment.
- **A baseline must include the losers the entry rule pays for.** Excluding them is a sign
  flip, not a smaller sample.

---

## 5. Feature System V2

**The runtime is canonical-only.** Read `docs/RESEARCH_WORKFLOW.md` §2 before touching a
feature.

A canonical feature names a formula, a provider, and causal/reset/null semantics.
**Timeframe, window, lookback, period, context, bar_state and cadence are PARAMETERS.**

```yaml
- feature: regime_efficiency
  parameters: {timeframe: 5m, context: prior, bar_state: completed}
```

- "1m EMA" is not a separately named feature.
- `timeframe: 1m, bar_state: completed` / `bar_state: forming, update_every: 5s` /
  `window: 300s, update_every: 1s` are three different things and must stay different.
- Ambiguous temporal semantics **fail closed**. Fix the declaration; do not add a default.
- Physical aliases are output column names, generated from the instance. Never a study input.
- Legacy alias resolution requires an explicit `legacy_mode=True` historical replay. There is
  no active fallback and none may be added.
- Do not add a provider to support another timeframe/window/period. That is a parameter.

---

## 6. Autonomy policy

**A gate failure means: do not advance past the gate. It does not mean: stop and report
`BLOCKED`.**

Autonomously, without asking: diagnose the deterministic defect, fix it at the owning layer,
add or update a targeted test, re-run the affected bounded check, regenerate stale
deterministic artifacts, and resume from the correct lifecycle stage.

**Terminal stop only for:** genuine semantic ambiguity · data safety risk · authorization
ambiguity · inability to preserve causality or TRAIN/OOS correctness · a real capability gap
· prohibited data access risk. Say which one.

Full policy and failure routing: `docs/RESEARCH_WORKFLOW.md` §12.

---

## 7. Data safety — DESTRUCTIVE FILESYSTEM SAFETY (mandatory)

Before any recursive deletion: inspect every descendant for symlinks, **junctions**, mount
points and Windows reparse points; resolve paths (`Path.resolve()`, not string prefixes);
confirm the target is inside repository-owned storage; **fail closed** if anything escapes —
do not delete "the safe part". Use `scripts/safe_cleanup.py::assert_safe_to_delete`.

`os.path.islink()` returns `False` for a Windows directory junction. A cleanup of a
"throwaway" worktree once followed a junction out of it and destroyed 179 GB of live data.

**Never junction live `data/` into a disposable worktree.**
**Never silently substitute a dataset.** If the authorized source is unavailable, fail closed.

---

## 8. Testing policy

- **Targeted over global.** `python scripts/select_required_tests.py` picks the tests a change
  actually requires. Running the whole suite repeatedly is latency, not diligence.
- **Bounded before expensive.** Synthetic fixture → 1 day → 1 week → 1 month → full. Verify
  metrics before expanding. Never auto-expand a stage.
- A repair needs a test that **fails before it and passes after it**. A fix with no test is a
  fix that will come back.
- Deterministic checks before LLM reasoning. `research_workflow.preflight` costs zero tokens.
- **Parity failures:** run `scripts/find_first_parity_divergence.py` **first**. No broad
  investigation before first-divergence localization has pinpointed the earliest failing
  timestamp, stage and field.

---

## 9. Documentation and artifacts

- Detailed evidence goes to **artifacts** (`audit/*.json`, `audit/pass_NN.md`,
  `validation_report.json`). Chat responses stay short.
- Report exact paths, exact SHAs, exact row counts. "It worked" is not a report.
- Scratch pandas output is **NON-AUTHORITATIVE** and must be labelled so. It may not be
  quoted as a result or used to close a research question.
- Report outcomes faithfully. If tests fail, say so with the output. If a step was skipped,
  say that.
- If a study reports a delta between model arms, it must state which integrity checks it
  verified (`docs/RESEARCH_WORKFLOW.md` §6.2). An unverified arm delta is a hypothesis.
- **Never commit generated data** — `runs/`, `canonical_*/`, `_work/`, `*.parquet`,
  `*.joblib`, `*.onnx`. Commit the manifests.
- **Output placement** — study-owned run outputs belong under `studies/<id>/runs/` and
  `studies/<id>/_work/`. Reusable tooling belongs in `scripts/`. Historical material belongs
  in `archive/`. Scratch output must not land in the repository root.

---

## 10. Commit protocol

- Branch: `study/<name>` or `chore/<topic>`. **Never commit on `main`.**
- Commit code together with the `audit/pass_NN.md` + `status.json` that audited it, so the
  scope hash matches the tree.
- Commit at every phase gate.
- Never skip hooks (`--no-verify`) or bypass signing unless explicitly asked.
- Commit or push only when asked.

---

## 11. Subagents

`.claude/agents/*.md` is **canonical**. `.agents/agents_staging/*.md` and
`.codex/agents/*.toml` are **generated**:

```bash
python scripts/sync_agents.py           # regenerate
python scripts/sync_agents.py --check   # verify in sync
```

Do not hand-edit the generated files. The harnesses previously drifted far enough that the
Codex auditor was silently missing 14 checklist rules including C4 and D4 — the #2 and #4
most frequent finding categories in this repository.

### Roster — six roles

| Agent | Codex `agent_type` | Owns | Tier | Cap |
|---|---|---|---|---|
| `repo-scout` | `repo_scout` | Inventory; locating the authoritative implementation; stale/duplicate paths; execution-closure and dependency reasoning; where a change belongs | Haiku / low | 700w — paths, symbols, line ranges |
| `lookahead-auditor` | `lookahead_auditor` | Causality: look-ahead, timestamp legality, event order. Checklist **A, B, C1–C3, F, G, H** | Sonnet / high | 1,500w report |
| `contract-checker` | `contract_checker` | Governance: TRAIN/OOS separation, authorization, freeze/seal freshness, provenance, deliverables, model-integrity declarations. Checklist **C4, D, E** | Sonnet / medium | 1,000w compliance table |
| `implementer` | `implementer` | Deterministic fixes, wiring, targeted tests, bounded fixtures, integration, first-broken-stage tracing | Sonnet / medium | — |
| `research-executor` | `research_executor` | Governed collection, partitioned TRAIN, reconciliation, fitting, TRAIN freeze, OOS opening and scoring, artifact production | Sonnet / medium | — |
| `analysis-decider` | `analysis_decider` | Reading generated artifacts, model comparison, forward-outcome interpretation, the research conclusion | Sonnet / high | — |

`Explore` (`.claude/agents/Explore.md`, Claude-only) is **a model pin, not a role** — it stops
the built-in fan-out search agent inheriting the orchestrator's model. Prefer `repo-scout`.

**Ownership is exclusive.** Causality belongs to `lookahead-auditor` and governance to
`contract-checker`; neither may report the other's category. Code changes belong to
`implementer`, lifecycle execution to `research-executor`, and conclusions to
`analysis-decider` — an agent that finds work outside its own column refers it in one line
and moves on.

Why this set, and why there is deliberately no separate performance agent:
`docs/SUBAGENT_ROSTER.md`.

### Shared audit protocol

Both audit gates obey this. It is stated **here only**; the agent cards do not restate it.

- **Distinct declared identities.** The causal and contract reviews are independent roles and
  must be authored by different declared reviewers. `scripts/run_preexec_audits.py` enforces
  this (`AUDITOR_ROLE_REUSE`) — one reviewer authoring both reports is a one-reviewer workflow
  wearing a two-reviewer seal. The agent name is the **role**, not the identity; do not
  substitute it unless it is genuinely the externally declared identity for the invocation.
- **The reviewer declares the audited composite**; tooling verifies it against
  `scripts/resolve_execution_manifest.py` and never self-generates or stamps it. If the
  composite has moved, the freeze is stale — report `INCOMPLETE` and stop rather than auditing
  a moving target.
- **One new file per pass.** `audit/pass_NN.md` (causal) / `audit/contract_pass_NN.md`
  (contract). Never append — append-only reports reached 1,240 lines and became unparseable.
- **Bounded re-audit.** Pass 2+ adjudicates every prior finding (`FIXED` / `NOT FIXED` /
  `WITHDRAWN`, one line of evidence) *before* raising anything new, then at most **3 new
  blocking findings per pass**. Never re-raise an addressed finding under new framing — mark
  the original `NOT FIXED`.
- **Every report carries exactly one machine-parsed summary block**, which is what
  `run_preexec_audits.py` reads to issue the official status:

  ```
  <!-- AUDIT_SUMMARY_V2_START -->
  {"verdict": "CLEAR", "audit_type": "causal|contract", "auditor": "<declared reviewer>", "critical": 0, "warning": 0, "note": 0, "study": "<study_id>", "audited_execution_composite_sha256": "<declared composite>"}
  <!-- AUDIT_SUMMARY_V2_END -->
  ```

  `verdict` is strictly `CLEAR`, `BLOCKED` or `INCOMPLETE`. A line counts as a finding only
  when it is a heading or bullet of the form `SEVERITY: <title>`. Gates read this block, never
  prose.
- **Filing path** when the agent cannot write its own report:

  ```
  python scripts/run_preexec_audits.py --study <study_dir> --pass-num <NN>       --type causal|contract --ingest <report.md> --author "<who you are>"
  ```

  It validates and re-derives the status itself, so filing never requires anyone to author a
  verdict on another reviewer's behalf.

### Shared subagent principles

Every subagent inherits these:

1. **Authoritative implementation first.** Find what exists before proposing anything.
2. **No duplicate infrastructure.** No second collector, auditor, analysis loader, or runner.
3. **Feature V2 canonical semantics.** Never rewrite feature identity around timeframes.
4. **Causal and TRAIN/OOS correctness above all.**
5. **Deterministic defects are fixable** — diagnose and repair rather than reporting `BLOCKED`.
6. **Targeted tests.**
7. **Bounded before expensive.**
8. **No silent dataset substitution.**
9. **No unsafe recursive cleanup.**
10. **Exact artifact and provenance reporting.**

### Coordination rules

- Worker and coding agents **cannot spawn subagents**. Only the main orchestrator invokes the
  named gates.
- Spawn `repo-scout` and `contract-checker` in parallel only when their assignments are
  independent.
- Never run two writing agents in the same worktree concurrently.
- **Never use an agent for process monitoring.** Use `scripts/run_bounded_study.py` and read
  its JSON status card.
- Subagent prompts must be self-contained — children do not inherit the parent conversation.
- **Model tiering: the cheapest model that can be trusted with the decision.** Never put a
  research-blessing gate on Haiku; never route discovery through a parent-model agent. Do not
  escalate a model because a task is long — a 5,000-line test log does not need Opus; a
  three-line timestamp question might. Changing a gate's model is a framework change and
  needs the escalation justification in `docs/RESEARCH_WORKFLOW.md` §1.

### Standing authorization

The named gates above may be invoked without asking, scoped strictly to the gate. No
discretionary, general-purpose, nested, or fan-out agent use beyond that.

### Required delegation packet

Exact objective · exact paths/subsystem · relevant symbols · applicable spec sections ·
required output format and word cap · explicit prohibitions · known facts vs. open questions.

---

## 12. Documentation index

| Topic | Document |
|---|---|
| **The workflow (authoritative)** | `docs/RESEARCH_WORKFLOW.md` |
| Causal/contract audit ruleset A1–H4 | `docs/CAUSAL_CHECKLIST.md` |
| Which docs are current, which are stale | `docs/DOCUMENT_MAP.md` |
| Feature lifecycle and promotion | `features/FEATURE_REGISTRY_CONTRACT.md` |
| Canonical feature vocabulary | `features/CANONICAL_FEATURE_REFERENCE.yaml` |
| Catalog and data | `docs/DATA_CATALOG.md` |
| Backtest execution and configs | `docs/BACKTEST_EXECUTION.md` |
| Study methodology, MFE/MAE replay | `docs/STUDY_METHODOLOGY.md` |
| SPEC templates, Deliverables Manifest | `docs/TEMPLATES.md` |
| Reporting and tearsheets | `docs/ANALYSIS_REPORTING.md` |
| Profiling and ONNX | `docs/PERFORMANCE.md` |
| Error registry | `docs/ERROR_REGISTRY.md` |
| Subagent roster rationale | `docs/SUBAGENT_ROSTER.md` |

Do not guess implementation details. Read the spec before writing code.

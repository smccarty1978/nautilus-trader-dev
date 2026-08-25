# CLAUDE.md — Claude Operating Manual

**Read in this order:**

1. `AGENTS.md` — the shared agent core. Every rule there applies to you.
2. `docs/RESEARCH_WORKFLOW.md` — the authoritative description of the system.
3. This file — what Claude specifically is here to do, and what Claude specifically gets
   wrong.

This file adds Claude-specific guidance. It does not repeat the workflow.

---

## 1. Mission

Claude is used here for the work that needs breadth: architecture, repository-wide
reasoning, refactoring, documentation, debugging complex cross-file interactions, and
multi-file implementation. You are usually the orchestrator.

That means your characteristic failure is not writing bad code. It is **building a second
version of something that already exists** because you started editing before you finished
looking.

---

## 2. Inspect broadly before editing

Before writing a line:

- Locate the **authoritative** implementation, not the first plausible one. `grep` finds
  four collectors in this repository; exactly one of them is current
  (`research_workflow/generic_collector.py`).
- Check whether the thing you are about to build exists under a different name. Consult
  `docs/RESEARCH_WORKFLOW.md` §1 and §11 first, then `repo-scout`.
- Read `docs/DOCUMENT_MAP.md` before trusting any Markdown file that is not
  `docs/RESEARCH_WORKFLOW.md`. Roughly thirty root-level documents describe systems that no
  longer exist; they carry a `[STALE]` or `[HISTORICAL]` banner.
- Prefer `git diff -U20` as the primary review surface. Open full files only to resolve
  causality, state flow, base classes, or imports.
- Do not reopen unchanged files to repeat discovery you already did.

**Discovery belongs on Haiku.** Use `repo-scout` for evidence gathering. `Explore` exists in
`.claude/agents/` only to pin the built-in agent's model — it is not a distinct role.

---

## 3. Understand the execution closure before touching a shared file

A study's execution closure is resolved by `scripts/resolve_execution_manifest.py` and
hashed into `audit/frozen_execution_manifest.json`. Editing anything inside it stales the
freeze and invalidates the seal of every study sealed against it.

`research_workflow/__init__.py` is inside that closure. A cosmetic `__all__` edit is enough.

Before editing anything under `research_workflow/`, `research/`, `features/`,
`backtests/nt_runtime/` or `utils/`:

```bash
python scripts/resolve_execution_manifest.py --study studies/<in-flight-study>
```

If a sealed study is in flight and your change is not required by it, do the change on a
separate branch or after that study completes. If it *is* required, expect to re-run PREPARE
and stages 3–6 and say so up front.

Sealed studies also fix their strategy: `--strategy` must never override a sealed study's
declared `strategy_class`.

---

## 4. Trace defects to the first broken stage

When something is wrong, find the **earliest** point at which it became wrong. Do not patch
the symptom at the surface where you noticed it.

- Parity failure → `scripts/find_first_parity_divergence.py` **before** any investigation.
  This is a hard rule, not a suggestion.
- Wrong numbers in a report → check the population and the join before the metric. Three of
  the worst defects found here were scope losses at a join, not arithmetic errors.
- A model arm that behaves like another arm → check whether the added feature block is
  actually populated and has variance, before theorising about the model.
- A gate that passes when it should not → check whether it covers the deliverable it is
  vouching for. A check that derives its own scope cannot detect scope loss.

---

## 5. Explicit prohibitions

These are the specific things Claude has done here that cost real time.

- **Don't stop at the first deterministic defect.** A `BLOCKED` preflight is an instruction
  to fix, not to report. Fix it, add a targeted test, re-run the bounded check, continue.
  See `AGENTS.md` §6 for the six terminal stop conditions.
- **Don't build a bespoke collector.** Generic extension points exist: declared
  `FeatureInstance`s, `research_workflow/hooks/` protocols, and small declarative hooks in
  `studies/<id>/implementation/`. Copying, subclassing or wrapping a historical study
  collector is prohibited. So is `sys.path.insert` into a sibling study directory.
- **Don't create a duplicate auditor.** The lookahead/causal system already exists
  (`scripts/causal_lint.py`, `docs/CAUSAL_CHECKLIST.md`, `lookahead-auditor`,
  `contract-checker`, `research_workflow/causal_audit.py`). If it misses something, extend
  the checklist and the lint — do not write a second "leakage scanner".
- **Don't rewrite canonical feature identity around timeframes.** `prior_5m_regime_efficiency`
  is an output alias. The identity is `regime_efficiency` with `timeframe: 5m`. Adding a
  provider "for the 5m case" is the same mistake in code.
- **Don't loosen the outcome guard.** If `forward_outcomes/guard.py` rejects something,
  either it is a genuine leak or the column is misnamed. An unanchored substring match would
  reject `rolling_300s_giveback_atr`, which is a legitimate causal input.
- **Don't wrap a canonical runner** to retry, monitor or babysit it. Use
  `scripts/run_bounded_study.py` and read its JSON status card. A wrapper becomes a second
  runner with none of the governance.
- **Don't launch a second identical run** while one is `RUNNING`. Confirm terminal state with
  `scripts/reconcile_runs.py` — it classifies `RUNNING` only when the recorded PID is alive.
- **Don't route around the analysis harness.** If `research/analysis/` cannot express the
  analysis, report `ANALYSIS_HARNESS_GAP` naming the missing capability.
- **Don't add a new `run_*.py`.** A standard backtest is
  `python backtests/run_backtest.py --strategy <id> --param k=v`. Legacy `backtests/run_*.py`
  scripts are frozen references, not templates.

---

## 6. Import, don't regenerate

| Concern | Canonical import |
|---|---|
| Engine + venue + instrument | `backtests/nt_runtime/engine_builder.py` → `build_engine`, `create_futures_instrument` |
| Catalog bar loading | `utils/runner/data.py` → `CausalDataLoader.load_bars` (never open `ParquetDataCatalog` inline) |
| 1s-before-1m dispatch order | `utils/causal_registration.py` → `add_bars_causal_order` |
| Study / stage / run plan / telemetry | `backtests/nt_runtime/{compiled_study_loader,data_plan,run_plan,telemetry}.py` |
| Output persistence + surface enforcement | `research_workflow/output_manager.py` |
| Collect entrypoint | `backtests/run_nt_study.py --mode collect` |
| Standalone backtest entrypoint | `backtests/run_backtest.py` |
| Strategy registration | `STRATEGY_REGISTRY` in `backtests/nt_runtime/strategy_binding.py` |

`resolve_catalog_plan(...)` is the generic catalog/instrument/warmup resolver.
`resolve_data_plan(...)` is the study-bound wrapper that additionally applies collector
chronology and OOS gates — do not call it for a non-collector backtest.

Shared helpers go in `research_workflow/`, `backtests/nt_runtime/`, `utils/runner/` or
`features/`.

---

## 7. Risk tiers

| Tier | Work | Process |
|---|---|---|
| **1** | Small fix, diagnostic, docs | Main session → targeted tests → local smoke. No agents, no auditor unless causal or timing logic changed |
| **2** | Normal research study | `research_decision.yaml` → `SPEC.md` → `study.yaml` → compile → PREPARE+FREEZE → READINESS → preflight `CLEAR` → split pre-execution audit → seal → staged runner → completion contract check |
| **3** | Model freeze / deployment / cross-timeframe strategy | Tier 2, preceded by `repo-scout` for execution-closure and dependency evidence |

Re-audit causality only when the audited surface actually changes. Re-run `contract-checker`
on materialized outputs before acceptance.

---

## 8. When you write documentation

- Update the authoritative doc. Do not create a parallel one.
- Link instead of duplicating.
- If you mark something stale, add it to `docs/DOCUMENT_MAP.md` in the same change.
- Describe what the code does today, not what it was designed to do.

---

## 9. Delivering

Concise chat, detailed artifacts. Exact paths, exact SHAs, exact counts. State what you
verified and what you did not. If you left part of a task undone, say which part and why —
scaling the work down is the user's call.

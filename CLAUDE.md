# CLAUDE.md — Claude Operating Manual

**Read in this order:**

0. `WORKFLOW.md` — the current way to work (Platform V2). Read it first; `docs/QUICKSTART.md`,
   `docs/RESEARCH_YAML_REFERENCE.md`, `docs/RESEARCH_DISCUSSION_TO_YAML.md` and `docs/AI_AGENTS.md` hang off it.
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
- **Don't loosen the outcome guard.** If `research_workflow/forward_outcomes/guard.py` rejects something,
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
- **Don't write a multi-call protocol into `research_decision.yaml` before it has been run.**
  When a described protocol composes existing governed APIs across a chronological split
  (e.g., "phase 1 uses years X, phase 2 uses years Y"), write and run a bounded
  synthetic-fixture test proving it *first*, then write the description. A `random_state`
  duplicate-kwarg crash and a silent hyperparameter-default fallback both sat in an
  already-sealed `study.yaml` because the prose was written, reviewed, and frozen before any
  code exercised it — both were only caught once a test suite was finally written, one freeze
  cycle later than it should have been.
- **Don't describe a chronological split in prose only.** Before presenting any protocol that
  touches more than one year-role (TRAIN/tuning/final-validation/OOS), write out — literally,
  as a table, one row per governed call — which years and which role each call touches. A
  2023 double-use (used simultaneously as the architecture-comparison evaluation year and the
  declared reject-only final-validation year) passed self-review and was only caught by the
  researcher; a call-by-call year table would have surfaced it before it was ever presented.
- **Don't resolve findings from the same category one at a time across separate freeze
  cycles.** A stale baseline-manifest pin, a stale `config/baseline.json` mirror, and a
  missing lineage disclosure were all "provenance" findings surfaced across three separate
  re-freeze/re-audit cycles on the same study. Sweep the whole category — grep for every other
  place the same stale value or the same undisclosed fact could be hiding — before
  re-freezing, not after the next review pass finds the next instance of it.

---

## 6. Three imports Claude keeps re-typing

The full canonical-import map is `docs/RESEARCH_WORKFLOW.md` §1 and §8. These three are here
because they are the ones that have actually been re-implemented inline in this repository:

- **Catalog loading** — `utils/runner/data.py` → `CausalDataLoader.load_bars`. Never open a
  `ParquetDataCatalog` inline; readiness R9 fails the study if you do.
- **`resolve_data_plan` vs. `resolve_catalog_plan`** — the first is study-bound and applies
  collector chronology plus OOS gates. Do not call it for a non-collector backtest.
- **Strategy registration** — `STRATEGY_REGISTRY` lives in
  `backtests/nt_runtime/strategy_binding.py`, not in `strategies/`.

Shared helpers go in `research_workflow/`, `backtests/nt_runtime/`, `utils/runner/` or
`features/`.

---

## 7. Risk tiers

The lifecycle itself is `docs/RESEARCH_WORKFLOW.md` §3 — do not restate it. Tiers only decide
**how much ceremony** wraps it.

| Tier | Work | Ceremony |
|---|---|---|
| **1** | Small fix, diagnostic, docs | Main session → targeted tests → local smoke. No agents, and no auditor unless causal or timing logic changed |
| **2** | Normal research study | The full lifecycle (§3), every stage |
| **3** | Model freeze / deployment / cross-timeframe strategy | Tier 2, preceded by `repo-scout` for execution-closure and dependency evidence |

Claude-specific: re-audit causality only when the audited surface actually changes, and
re-run `contract-checker` on materialized outputs before acceptance.

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

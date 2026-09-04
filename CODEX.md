# CODEX.md — Codex Operating Manual

**Read in this order:**

0. `WORKFLOW.md` — the current way to work (Platform V2). Read it first; then `docs/QUICKSTART.md` and `docs/AI_AGENTS.md`.
**FOR A NEW RESEARCH PROJECT:** read `WORKFLOW.md` → §M *Concurrent research projects*, then use `python scripts/research.py study new <id>` and work only in the generated worktree. Never start a study by editing `main`.
**BEFORE WRITING IN A STUDY WORKTREE:** `python scripts/research.py ws whoami` (agent = `codex`, a session id) then `ws claim <id>`; a live lease of another agent is refused (`STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT`) -- same OS user or not. Read-only roles skip the claim.
1. `AGENTS.md` — the shared agent core. Every rule there applies to you.
2. `docs/RESEARCH_WORKFLOW.md` — the authoritative description of the system.
3. This file — what Codex specifically is here to do, and what Codex specifically gets wrong.

This file adds Codex-specific guidance. It does not repeat the workflow.

---

## 1. Mission

Codex is used here for focused implementation: bounded code changes, tests, scripts,
diagnostics, lifecycle execution and artifact generation. You usually arrive with a defined
task, not an open question.

That means your characteristic failure is not scope creep in design. It is **cost**: rerunning
a full-year collection to test a two-line repair, or running the whole test suite because it
was easier than selecting the right tests.

---

## 2. Inspect the existing implementation first

Before writing anything:

- Find the authoritative implementation. `docs/RESEARCH_WORKFLOW.md` §1 (architecture) and
  §11 (every script, what it does, what it mutates, whether it is safe during a sealed run).
- Check `docs/DOCUMENT_MAP.md` before trusting any other Markdown file. Roughly thirty
  root-level docs describe systems that no longer exist and carry a `[STALE]` or
  `[HISTORICAL]` banner.
- **Prefer the authoritative entry point over a compatibility shim.** Several `scripts/*.py`
  and `backtests/nt_runtime/*.py` files are one-line redirects into `research_workflow`; §11
  classifies every script as authoritative / shim / diagnostic / historical. A shim's docstring
  names its target — edit and invoke the target, never the shim.
- Read the failure artifact before re-deriving the failure. `audit/failure_packet.json`,
  `audit/preflight.json`, `validation_report.json`, the run's `lifecycle.json`.

---

## 3. Make minimal deterministic edits

- Smallest change that satisfies the required behaviour.
- Modify only the files the task actually requires.
- No broad cleanup, reformatting, renaming, or dependency upgrades along the way.
- **Preserve exactly:** numerical precision, tick rounding, sign conventions, ATR
  denominators, state ownership, callback order, event populations, and entry/fill/stop/exit
  timing — unless the task explicitly requires changing one.
- Do not reinterpret an approved timestamp, execution, causal, or population contract.
  `research_decision.yaml > SPEC.md > study.yaml > compiled_study.json > code`.

---

## 4. Bounded before expensive

This is the rule that matters most for Codex.

```
synthetic fixture  ->  1 day  ->  1 week  ->  1 month  ->  full
```

- **Do not rerun an expensive stage if a smaller fixture can validate the repair.** A
  one-day NT smoke, `scripts/run_vertical_slice.py`, or a synthetic fixture under
  `scripts/tests/` validates most deterministic repairs.
- **Do not run broad CI repeatedly.** `python scripts/select_required_tests.py` selects the
  tests a change actually requires. Run those.
- Never auto-expand a stage. Verify the metrics at the current stage first.
- For long runs use `scripts/run_bounded_study.py` — it enforces time, memory and
  stale-progress limits and emits a JSON status card. Read the card, not the raw log.
- Before relaunching anything, run `scripts/reconcile_runs.py`. It classifies a run as
  `RUNNING` only when its recorded PID is genuinely alive; everything else is `ABANDONED`,
  `FAILED`, `ABORTED` or `SUCCESS`. Two concurrent identical runs produce two run
  directories competing for one identity and make the evidence ambiguous.
- **Benchmarking:** `tracemalloc` is opt-in (`NT_TELEMETRY_TRACEMALLOC=1`) because it costs
  ~6–7x replay wall time. Never benchmark with it on and report the number as replay cost.

---

## 5. Fix deterministic failures automatically

A gate failure means **do not advance past the gate**. It does not mean stop.

Do this yourself, without asking:

1. Read the failure artifact.
2. Route the error code to its owning layer (`docs/RESEARCH_WORKFLOW.md` §12).
3. Fix it there — the canonical feature bundle, `study.yaml`, `STRATEGY_REGISTRY`, the
   tracker, the contract. Not with a one-off script that bypasses the check.
4. Add or update a **targeted** test that fails before the fix and passes after it.
5. Re-run the affected bounded check.
6. Regenerate stale deterministic artifacts — recompile, re-run PREPARE to re-freeze,
   regenerate the phase-zero manifest or the canonical feature reference.
7. Resume from the correct lifecycle stage, not from the beginning.

Stop terminally only for the six conditions in `AGENTS.md` §6, and say which one.

**Parity failures:** run `scripts/find_first_parity_divergence.py` first. No broad
investigation before first-divergence localization.

---

## 6. Preserve TRAIN/OOS and freeze semantics

The policy itself is `docs/RESEARCH_WORKFLOW.md` §3 (TRAIN/OOS discipline) — what is frozen,
when OOS opens, and what a stale freeze means. Do not restate it; read it.

Codex-specific behaviour around that policy:

- **Do not open OOS early.** `experiment.assert_oos_open` is the only door. If a stage appears
  to need OOS data before stage 14, you have the wrong stage.
- **Do not tune on OOS.** If a fix would require changing anything frozen at stage 13 *after*
  OOS was seen, stop — that is a terminal stop, not a defect to repair.
- **Declare closure impact.** If your edit lands inside a study's execution closure, say so
  up front: the freeze is stale and stages 3–6 must be redone before execution resumes.
- **Report exact artifacts** — paths and hashes, per §8.

---

## 7. Explicit prohibitions

- **Do not create parallel script paths.** If a script exists for the job, use it. A new
  `run_*.py` for an ordinary parameter, date range, or strategy variation is prohibited — a
  standard backtest is `python backtests/run_backtest.py --strategy <id> --param k=v`.
- **Do not build a bespoke collector.** `research_workflow/generic_collector.py` executes
  declared `FeatureInstance`s. Do not copy, subclass, wrap, or `sys.path.insert` into a
  historical study collector.
- **Do not write a second auditor, analysis loader, engine bootstrap, or catalog opener.**
  Ungoverned catalog opens under a study tree are caught by
  `scripts/scan_alternate_catalog_openers.py` (readiness R9).
- **Do not add a feature name that encodes a timeframe.** Timeframe, window, lookback and
  period are instance parameters. `arrival_vel_20s` is an output alias, not an identity.
- **Do not use destructive git commands.** No reset, clean, force-push, or branch surgery.
  Do not commit, push or rebase unless asked.
- **Do not install dependencies** without explicit authorization.
- **Do not spawn subagents.** Worker agents cannot delegate.
- **Do not hand-edit generated files** — `.codex/agents/*.toml` and
  `.agents/agents_staging/*.md` come from `.claude/agents/*.md` via
  `python scripts/sync_agents.py`.

---

## 8. Report exactly

Every completed task reports:

- **Files changed** — exact paths.
- **Behaviour implemented** — what now happens that did not before.
- **Tests added or modified** — exact node ids, and the pass/fail result.
- **Commands run** — verbatim.
- **Artifacts produced** — exact paths and SHA-256 where the artifact is hashed
  (`frozen_execution_composite_sha256`, `authorization_sha256`, `freeze_sha256`,
  `spec_sha256`, `preexec_audit_seal.json`).
- **Remaining uncertainty** — what you did not verify.
- **Diff-risk summary** — what could have broken elsewhere.

"It worked" is not a report. Neither is a pasted 5,000-line log — that belongs in an
artifact, summarized here.

If a test failed, say so and include the failing output. If you skipped a step, say which.

---

## 9. Agent roster

Codex agent identifiers use underscores: `repo_scout`, `lookahead_auditor`,
`contract_checker`, `implementer`, `research_executor`, `analysis_decider`. Roster, models and
caps are in `AGENTS.md` §11; rationale is in `docs/SUBAGENT_ROSTER.md`.

`implementer` is the agent this file's §3–§8 describe most directly. It requires a frozen task
packet: exact objective, root cause or approved interpretation, exact files allowed to change,
required behaviour, forbidden semantic changes, acceptance tests, and stop-and-escalate
conditions.

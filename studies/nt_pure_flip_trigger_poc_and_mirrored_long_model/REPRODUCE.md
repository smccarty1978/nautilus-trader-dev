# Reproduce

All commands run from the repo root
(`C:\Users\Scott McCarty\Projects\Nautilus Trader`) with the project's
Python environment active. Phase 3 was descoped — see `STUDY_REPORT.md`
— so only Phase 0-2 are reproducible from this study's own code.

## Phase 0 — freeze inputs

```bash
python -m studies.nt_pure_flip_trigger_poc_and_mirrored_long_model.phase0_freeze_inputs
```

Writes `results/phase0_frozen_inputs_manifest.json`. Asserts frozen
cutoffs match `short_rth_pure_flip_score_entry_policy/_work/cutoffs.json`
exactly and hashes every upstream script/parquet consumed.

## Phase 1 — month selection

```bash
python -m studies.nt_pure_flip_trigger_poc_and_mirrored_long_model.phase1_month_selection
```

Writes `phase2/month_selection.csv` and
`phase2/month_selection_manifest.json`. Selects March 2025.

## Phase 2 — unit tests (run before the real NT backtest, per the
project's pre-execution-audit discipline)

```bash
python -m pytest studies/nt_pure_flip_trigger_poc_and_mirrored_long_model/tests/test_trade_state.py -v
```

21 tests, all pass.

## Phase 2 — build per-variant schedules

```bash
python -m studies.nt_pure_flip_trigger_poc_and_mirrored_long_model.phase2.build_schedules
```

Extracts March-2025 rows from the three existing entry-policy schedule
files into `_work/schedules/{T1,T2,T3}.parquet`. Expect T1=55, T2=75,
T3=75 rows.

## Phase 2 — run the NT BacktestEngine (all 3 variants)

```bash
python -m studies.nt_pure_flip_trigger_poc_and_mirrored_long_model.phase2.run_nt --variant ALL
```

Takes ~210s per variant (full year of 1s+1m NQ bars loaded three times,
one per independent strategy instance — do not pool before all three
complete). Writes `_work/nt_runs/{T1,T2,T3}/{trades,flips,skips,raw_paths}.parquet`
+ `meta.json` per variant. Expect exactly 55/75/75 trades, 0 skips.

Can also be run for a single variant via `--variant T1` / `T2` / `T3`.

## Phase 2 — parity checks (must all be exact; raises `SystemExit` on any
mismatch)

```bash
python -m studies.nt_pure_flip_trigger_poc_and_mirrored_long_model.phase2.reconcile
```

Writes `phase2/regime_runtime_parity.csv`, `phase2/trigger_runtime_parity.csv`,
`phase2/score_runtime_parity.csv`. Expect `exact_match=True` for every
variant on all three checks.

## Phase 2 — summarize variants

```bash
python -m studies.nt_pure_flip_trigger_poc_and_mirrored_long_model.phase2.summarize_variants
```

Writes `phase2/variant_summary.csv`, `phase2/exit_reason_summary.csv`,
`phase2/winner_giveback_counts.csv`, `phase2/equity_curve_by_variant.csv`,
per-variant trade parquets, and pooled `phase2/raw_trade_paths.parquet`.

## Phase 2 — apply the gate

```bash
python -m studies.nt_pure_flip_trigger_poc_and_mirrored_long_model.phase2.apply_gate
```

Writes `phase2/manifest.json`. Expect
`phase2_nt_poc_decision = "NT_POC_PROMISING_LONG_MODEL_NOT_RUN"`.

## Audits

Two audit passes are recorded in `audit/audit.md`:
1. Pre-execution audit of `trade_state.py`/`strategy.py`/`build_schedules.py`
   /tests (before the real BacktestEngine run) — found and fixed 1
   CRITICAL (manual stop-touch polling instead of a genuine
   `stop_market` order).
2. Completion-gate audit of the full Phase 2 pipeline post-execution — 0
   CRITICAL.

Both were run via the `lookahead-auditor` subagent; re-running them
requires re-invoking that agent against the current code, not a script.

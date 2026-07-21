# Reproduce — Pure Flip Score Entry-Trigger Policy Test

Final decision: `FLIP_SCORE_POLICY_WEAK_BUT_USEFUL`. All commands below
assume `cd studies/short_rth_pure_flip_score_entry_policy`.

## 0. Prerequisites

- `studies/short_rth_pure_flip_prediction_enriched/_work/scored_dev_2025.parquet`
  (198,255 rows) and `scored_test_2026.parquet` (63,021 rows) — the pure-flip
  study's own full prepared surfaces with model scores attached.
- `studies/fable5_short_rth_threshold_ladder/run_ladder.py` (reused for
  Baseline A regeneration) and its raw-bar/policy dependencies.
- `studies/fable5_nt_short_rth_policy_a/_work/short_rth_schedule_{2025,2026}.parquet`
  (Baseline B fixed-807 schedules).
- `data/raw/NQ_v0_1s_{2025,2026}.parquet`.

## 1. Pre-execution tests (run BEFORE the trigger grid)

```bash
python -m pytest tests/test_trigger_logic.py -v
```

6 hand-computed tests covering positional vs. time-based lookback, exact
crossing semantics, and persistence-window edge cases. Expected: 6 passed.

## 2. Trigger grid (25 variants × 2 splits)

```bash
python trigger_grid.py
```

Freezes percentile cutoffs (top 20/15/10/5/2.5%) on the 2025 raw-score
distribution only; builds all 25 trigger-family variants; one-entry-per-
regime schedules; economics per variant per split.

Writes: `_work/cutoffs.json`, `_work/tagged_{2025,2026}.parquet`,
`_work/schedule_{trigger}_{split}.parquet` (50 files),
`results/trigger_grid_results.csv`.

Expected: top-MAR 2025 variant `trig_B_top2.5` (596 trades, +$22,184,
+$37.22/tr, PF 1.196). Runtime ~20s.

## 3. Pre-execution tests for path-scanning logic (run BEFORE step 4)

```bash
python -m pytest tests/test_path_logic.py -v
```

15 hand-computed tests (short AND long direction, exact-match and
raw-data-gap fallback, year-boundary truncation guards). Expected: 15
passed. Two real bugs were caught and fixed during this study by this
step: a "direction applied twice" sign error, and an overly strict
exact-match requirement in `align_open_price` that spuriously rejected
legitimate single-second raw-data gaps.

## 4. Selection + viability gate

```bash
python select_and_gate.py
```

Selects on highest 2025 MAR-like score (net_pnl / max_closed_trade_dd);
applies the signal-to-policy viability gate (2025 minimums + 2026
minimums + winner-clipping check).

Writes: `results/selected_trades_{2025,2026}.parquet`,
`results/monthly_results.csv`, `results/exit_reason_attribution.csv`,
`results/selected_trigger_summary.json`.

Expected: `DECISION: FLIP_SCORE_POLICY_WEAK_BUT_USEFUL`.

## 5. Path diagnostics (diagnostic only, no exit optimization)

```bash
python path_diagnostics.py
```

Per-trade raw-bar path scan (max favorable/adverse excursion, ever-up-X-
ATR-then-loser counts, post-flip giveback) for the selected trigger's
trades only (~596 + ~181 = 777 trades total, fast).

Writes: `results/path_diagnostics.csv`, `results/winner_giveback_counts.csv`.

Expected: 2025 — 311/596 trades (52.2%) ever reach ≥1.0 ATR favorable
excursion; 146 of those (46.9%) still close as losers.

## 6. Baseline mapping attribution

```bash
python baseline_mapping_attribution.py
```

Regenerates Baseline A's exact 650/222 W4-threshold candidates via the
already-audited `run_ladder.generate_entries` (not reimplemented) and
compares regime-set overlap with the selected trigger's schedule, and
separately with Baseline B's fixed-807 schedule.

Writes: `results/baseline_mapping_attribution.csv`.

## 7. Manifest

```bash
python build_manifest.py
```

Writes: `results/manifest.json`.

## 8. Audit

Run the `lookahead-auditor` agent twice: once pre-execution (on
`path_logic.py` + its tests, before step 3 wires it into real data), once
completion-gate (full pipeline, after step 7). Both must reach 0 CRITICAL.
Result: `audit/audit.md`, two dated sections, 0 CRITICAL in both, all
actionable WARNINGs fixed post-audit with the pipeline re-run to confirm no
change to the selected trigger or final decision.

## Full pipeline (in order)

```bash
python -m pytest tests/test_trigger_logic.py -v
python trigger_grid.py
python -m pytest tests/test_path_logic.py -v
python select_and_gate.py
python path_diagnostics.py
python baseline_mapping_attribution.py
python build_manifest.py
```

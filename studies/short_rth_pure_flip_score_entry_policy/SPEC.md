# Pure Flip Score Entry-Trigger Policy Test

## Status

**COMPLETE. Final decision: `FLIP_SCORE_POLICY_WEAK_BUT_USEFUL`.** See
`STUDY_REPORT.md` for the full write-up. Selected trigger (`trig_B_top2.5`,
Family B strict-crossing at the top-2.5% threshold): 2025 +$37.22/tr (PF
1.196, beats Baseline A decisively); 2026 +$14.80/tr (PF 1.071, stays
positive — does not collapse like prior studies — but well below Baseline
A's 2026 $31.01/tr, and fails the winner-clipping check). Actual
flip-within-300s rate for triggered trades: 62-68%, well above the ~25%
population base rate, confirming the trigger does its stated job. Path
diagnostics show ~47-65% of trades reaching 0.25-1.0 ATR favorable
excursion still close as losers — the clear next study is profit-
protection/giveback exit design, not further entry-trigger iteration.
Audit: 2 passes (pre-execution + completion-gate), 0 CRITICAL, all
actionable warnings fixed and re-verified not to change the outcome.

## Decision to inform

Whether the pure bearish-flip probability model
(`[[pure_flip_prediction_inconclusive]]`, selected: F3 combined features +
GBT, row-level AUC ~0.671/0.670) can be converted into a profitable
short-RTH entry trigger under frozen Policy A trade management — a
signal-to-policy bridge, not a new signal or new management study.

## Primary hypothesis

The flip model doesn't need regime-level early-warning power (which it
lacks, per the prior study) to be useful — used as a **within-regime
timing trigger**, it may still improve entries versus the old W4 threshold.

Null hypothesis: row-level signal exists but does not monetize under frozen
Policy A.

## Scout-pass findings (grounds this SPEC in verified fact, not assumption)

1. **Canonical input is the pure-flip study's own `_work/scored_{split}.parquet`,
   not the trimmed `results/selected_model_predictions_{year}.parquet`
   the brief names.** Verified directly: the predictions parquet has only
   19 columns (score + a handful of diagnostic labels) and is missing
   `entry_ts`, `entry_px`, `atr_at_entry`, `exit_ts`, `exit_px`,
   `alignment_ts`, `pre_align_mae_atr`, `pre_align_mfe_atr`,
   `post_align_mae_atr`, `post_align_mfe_atr` — all required for the
   path-diagnostics section. `studies/short_rth_pure_flip_prediction_enriched/_work/scored_dev_2025.parquet`
   (198,255 rows) and `scored_test_2026.parquet` (63,021 rows) are the full
   `prepared_{year}.parquet` frames (every original `full_{year}.parquet`
   column + all label/gate columns) with the 8 combos' scores already
   attached as `score_{feature_set}__{model}_{raw,isotonic,sigmoid}` columns
   — confirmed all needed columns present by direct schema read. Row counts
   match the pure-flip study's own reported figures exactly (198,255 /
   63,021). This SPEC uses these files as the actual input; the predictions
   parquets remain valid as a lighter-weight cross-check.
2. **Raw vs. calibrated score is immaterial to every trigger family in this
   study.** All four trigger families are defined by **percentile
   thresholds** (top 20/15/10/5/2.5%) or **rank comparisons** (crossing,
   rising, persistence) computed on the 2025 score distribution. Isotonic
   and sigmoid calibration (`[[pure_flip_prediction_inconclusive]]` found
   both nearly identical to the raw model, Brier difference ≤0.0005) are
   monotonic transforms of the same underlying ranking — a monotonic
   transform cannot change which rows fall in the top-K% or which row has a
   higher score than another. **This study uses the raw score
   (`score_F3_volume_delta_plus_price_levels__gbt_raw`) throughout**; using
   isotonic or sigmoid would select the identical set of triggered
   checkpoints.
3. **"Per-regime one-entry" and "global one-position" are proven identical
   for this population, not merely assumed.** Checked directly on
   `scored_dev_2025.parquet`: across all 1,678 regimes, `regime_end_ns`
   (`confirm_flip_ns`) of every regime is strictly ≤ `regime_start_ns` of
   the next — **0 overlaps**. `canonical_regime_timeline`'s alternating
   bullish/bearish construction guarantees this structurally (a new regime
   only starts when the prior one is confirmed to end). Since regimes never
   overlap in wall-clock time, restricting to one entry per regime already
   IS the global one-position constraint — there is no separate "global"
   computation needed; both are reported as the same numbers, with this
   proof stated rather than re-derived at runtime.
4. **Path-diagnostic columns split into "already computed, reuse" vs.
   "genuinely new."** `pre_align_mae_atr`/`pre_align_mfe_atr` (MAE/MFE
   before alignment-or-Policy-A's-own-exit, whichever first) and
   `post_align_mae_atr`/`post_align_mfe_atr` (after alignment, to Policy
   A's own exit) are already computed and audited — reused directly, no
   raw-bar rescan. But **"maximum adverse excursion before bearish flip"**
   (as literally worded — bounded by the actual `confirm_flip_ns`, not by
   Policy A's own exit, which can be earlier for a stopped-out or timed-out
   trade) and the four **"ever up ≥X ATR then closed loser"** winner-
   giveback counts require a genuinely new raw-1s-bar path scan from
   `entry_ts` to `exit_ts` (Policy A's own exit — the giveback question is
   about the REALIZED trade's path, not the regime's full lifetime),
   tracking running favorable excursion in ATR units. This is new causal
   logic — see "Process note" below.
5. **Trigger-family causality is straightforward but must be checked
   explicitly**: Family B (crossing) and Family C (score-change) need the
   PRIOR checkpoint's score within the SAME regime, strictly earlier in
   `observation_time` — a simple `groupby(regime_start_ns).shift(1)` after
   sorting by `observation_time`, which by construction only ever looks
   backward. Family D (persistence) needs a trailing rolling window (3/6/12
   checkpoints on the 5s grid for 15s/30s/60s) fully within the same
   regime — computed via `groupby(...).rolling(...)`, also backward-only.
   No future information enters any trigger definition.
6. **Baselines reused verbatim as fixed constants** from
   `[[short_rth_enriched_retrain_overfits_2025]]`'s `select_and_attribute.py`
   (Baseline A/B/C) — not recomputed.

## Population

Same full-checkpoint 120s-gate surface as the pure-flip study (`NQ`, short
setup, qualified bullish RTH regime, RTH only). 2025 for selection, 2026
for sealed test only (per SPEC's split discipline — 2021-2024 is the
already-fixed model's training data, not re-touched here).

## Frozen trade management

Policy A unchanged (1.25×ATR pre-alignment stop, 300s confirmation
deadline, 1.50×ATR post-alignment stop, opposing-flip exit, $20/pt, $10/trade,
1 contract) — every triggered checkpoint's outcome is read directly from
that row's own already-computed, already-audited Policy A simulation
columns (`net_pnl`, `exit_reason`, `hit_*`, MAE/MFE columns) — **no new
trade simulation is run**; this study only changes WHICH checkpoint gets
selected as the entry, never how that checkpoint's hypothetical trade plays
out (identical to how `[[short_rth_enriched_retrain_overfits_2025]]`'s
Layer 2 policy consumed pre-computed row labels).

## Entry trigger variants (25 total, all percentile cutoffs frozen on 2025)

- **Family A — threshold**: first checkpoint per regime with
  `score >= cutoff`. 5 thresholds (top 20/15/10/5/2.5%).
- **Family B — strict crossing from below**: first checkpoint per regime
  where `prev_score < cutoff <= score` (regime's first checkpoint can never
  qualify, since it has no `prev_score`). Same 5 thresholds.
- **Family C — rising confirmation**: `score >= cutoff AND score_change_last_{30,60}s > 0`.
  2 windows × 3 thresholds (top 20/10/5%) = 6 variants.
- **Family D — persistence**: `score >= cutoff` for every checkpoint in the
  trailing {15,30,60}s window (3/6/12 consecutive 5s-grid checkpoints, all
  within the same regime). 3 durations × 3 thresholds = 9 variants.

## Selection criterion

Highest 2025 MAR-like score (`net_pnl / max_closed_trade_dd`); ties broken
by higher $/trade, then higher PF, then lower pre-alignment-stop rate, then
fewer trades. Also report best-by-$/trade and best-by-PF separately
(diagnostic only, not used to select). Never uses 2026.

## Signal-to-policy viability gate

2025 minimums: net PnL positive, PF > 1.129 (Baseline A combined) or
clearly >1.10, max DD ≤ Baseline A's $18,686, $/trade ≥ Baseline A 2025's
$23.64. 2026 minimums: net PnL positive, PF > 1.05, $/trade not materially
worse than Baseline A 2026's $31.01, monthly shape not clearly worse, not
dominated by one month, opposing-flip winners not clipped enough to erase
stop savings.

```text
2025 improves + 2026 fails      -> FLIP_SCORE_POLICY_OVERFITS_2025
Row-level signal, no 2025 edge  -> FLIP_SCORE_SIGNAL_NOT_MONETIZED
Both years pass, beats baselines -> FLIP_SCORE_POLICY_PROMISING
Both pass but modestly           -> FLIP_SCORE_POLICY_WEAK_BUT_USEFUL
Neither beats baseline           -> FLIP_SCORE_POLICY_BASELINE_STILL_BEST
```

## Required artifacts

```text
studies/short_rth_pure_flip_score_entry_policy/
  SPEC.md
  results/trigger_grid_results.csv
  results/selected_trigger_summary.json
  results/selected_trades_2025.parquet
  results/selected_trades_2026.parquet
  results/monthly_results.csv
  results/exit_reason_attribution.csv
  results/path_diagnostics.csv
  results/winner_giveback_counts.csv
  results/baseline_mapping_attribution.csv
  results/manifest.json
  audit/audit.md
  STUDY_REPORT.md
  REPRODUCE.md
```

## Process note (per standing project feedback)

`[[feedback_preexecution_audit_gate]]`: finding 4's new raw-bar path-scan
logic (max-adverse-excursion-before-flip, ever-up-X-ATR-then-loser counts)
is genuinely new causal code. A hand-computed pytest suite will be written
and passed, and a pre-execution audit of that logic run, before it's
applied to the (small, ~1,600-1,700 trade) selected-trigger population.

## Forbidden

No changes to Policy A, RTH definition, direction, session, sizing; no
stop/exit optimization or profit-protection design (path diagnostics are
descriptive only); no 2026 threshold/family/stop/exit/model/calibration
selection.

## Final report must answer

1. Can the pure flip score monetize as an entry trigger under frozen Policy
A? 2. Which trigger family worked best on 2025? 3. Did it survive sealed
2026? 4. Does it beat the W4 baseline? 5. Does it beat/approach fixed-807?
6. Actual flip-within-300s rate for triggered trades? 7. Exit reason
counts/PnL? 8. How many selected trades were winners before becoming
losers? 9. Does the path suggest a future profit-protection exit could
help? 10. Next study: stop/exit design, symmetric exit-flip model, or
reject?

## Guardrails

Mandatory `lookahead-auditor` pass, 0 CRITICAL required before accepting
results.

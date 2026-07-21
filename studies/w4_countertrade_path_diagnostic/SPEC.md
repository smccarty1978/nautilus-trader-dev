# W4 Countertrade Path Diagnostic

## Purpose

Exploratory diagnostic on the frozen CODEX 5.X repaired-W4 established-regime
fade trades (2025 development, 2026 final test). Understand how price
excursion and W4 evolve after entry so we can attribute the policy's failure
to entry timing, stop management, or exit/giveback. **No threshold
optimization, no new policy backtest, no 2026-driven parameter selection.**

## Inputs (read-only, frozen)

- `studies/CODEX_5_X_weakness_atlas_repair/results/CODEX_5_X_established_fade_{year}_trades.parquet`
- `studies/CODEX_5_X_weakness_atlas_repair/results/CODEX_5_X_repaired_w4_scores_{year}.parquet`
- `data/raw/NQ_v0_1s_{year}.parquet` (2026 uses `_ytd`)

## Causality contract

- Databento 1s bars are open-labelled: bar at `ts_event=t` covers `[t, t+1s)`
  and is fully known only at `t+1s`. All timestamps are whole seconds, so a
  bar with `ts_event < cp` is complete at checkpoint `cp`.
- W4 score at `observation_time=t` uses only data strictly before `t`
  (upstream contract). The latest score with `observation_time <= cp` is
  therefore causal at `cp`. Staleness `(cp - obs)/1s` is recorded; W4-based
  flags are analysed only where staleness <= 30s.
- Price mark at `cp` = open of the first raw 1s bar with `ts_event >= cp`
  (identical to the frozen runner's fill semantics).
- Running MFE/MAE at `cp` use bars with `ts_event` in `[entry_fill_ts, cp)`.
- The exit bar is EXCLUDED from all MFE/peak computations (conservative: at
  1s granularity we cannot know whether the favorable extreme inside the
  stop-touch bar occurred before the stop). The exit fill price itself is
  included as a final mark.
- The `peak_mfe` checkpoint and all capture/giveback quantities are
  RETROSPECTIVE descriptors, flagged `retrospective=True`. They measure what
  was available, not what any causal rule could have taken.

## Excursion units

All excursions are normalized by the trade's frozen `atr_at_checkpoint`
(the decision-time ATR that anchors the 1.5-ATR stop). USD figures use the
NQ $20/pt multiplier; net = gross - $10 round trip (frozen policy cost).

## Checkpoints per trade

entry, +30s, +60s, +90s, +120s, +180s, +300s (from `entry_fill_ts`),
aligned_flip (`confirm_flip_ns`), flip+60s, flip+120s, peak_mfe
(retrospective), exit. A checkpoint row exists only while the trade is alive
(`cp <= exit_fill_ts`).

Per checkpoint: unrealized PnL (pts/USD/ATR), running MFE/MAE (ATR), W4 score
of the currently-prevailing regime (faded regime pre-flip, aligned regime
post-flip), W4 change from the entry trigger score (faded regime only), W4
slope over 15/30/60s where two distinct observations exist, above-threshold
flag, old-prevailing-regime new-favorable-extreme flag, aligned-flip-occurred
flag, time since entry, time since aligned flip.

## Outcome groups

`stop_before_aligned_flip`, `stop_after_aligned_flip`,
`opposite_flip_exit_winner` (net > 0), `opposite_flip_exit_loser` (net <= 0).
Splits: year, entry direction (long fade / short fade), session (RTH/ETH).

## Outputs

`results/path_checkpoints.parquet`, `results/trade_diagnostics.parquet`,
`results/outcome_group_summary.parquet`, `results/early_window_summary.parquet`,
`results/post_flip_exit_diagnostic.parquet`, `results/final_report.md`.

Final decision label is one of `NO_MANAGEMENT_EDGE_VISIBLE`,
`EARLY_EXIT_DIAGNOSTIC_PROMISING`, `POST_FLIP_EXIT_DIAGNOSTIC_PROMISING`,
`BOTH_EARLY_AND_POST_FLIP_MANAGEMENT_PROMISING`.

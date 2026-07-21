# Population definition — Fable 5 Pre-Flip D10 Reversal Entry

## Regime universe

- Instrument: NQ volume-continuous (`NQ.v.0`), raw 1s Databento bars
  (`data/raw/NQ_v0_1s_2025.parquet`, `data/raw/NQ_v0_1s_2026_ytd.parquet`),
  NT catalog `data/catalog/NQ_v0_2020_2026` (verified bit-identical to raw
  aggregation on a 1-week smoke: max abs OHLCV diff 0.0).
- Regime engine: EMA3/EMA9 sticky regime on completed 1m H/L/C bars, Wilder
  ATR(14), exact port of `regime_sequence_chop_context/reproduce_regimes.py`.
  Engine seeded fresh at Jan 1 of each year (matches atlas construction).
- A regime is the interval between consecutive flips, identified by
  `(direction, start_close_ts)`. Both flip endpoints are 1m bar CLOSE times.
- **Explicit exclusion**: the regime engine's initial regime of each year
  (the first non-zero regime out of warmup) is not flip-born, has no atlas
  checkpoints or scores by construction, and is excluded from the regime
  table (1 regime per year). The trailing regime open at data end IS
  retained, flagged `end_censored`.
- Sessions: ETH + RTH both included; RTH tagged as 08:30-15:00 America/Chicago
  for segmentation only.

## Score universe

- Checkpoints every 5 s (2025/2026) from `flip_ts + 5s` to
  `min(next_flip_ts, flip_ts + 1800s)` inclusive — inherited from
  `weakness_checkpoint_atlas.parquet`.
- Known structural gaps in score coverage, all measured in the coverage
  report rather than silently dropped:
  - `age_gt_1800s`: regime alive longer than 1800 s → no checkpoints beyond.
  - `warmup_or_features_nan`: rows dropped by the upstream
    `aligned_price_minus_center_5m` NaN filter or engine warmup.
  - `no_checkpoint_rows`: regimes too short to reach the first 5 s checkpoint
    or without 1s bars in range.
- Every regime in 2025/2026 is classified into exactly one of: validly scored
  and reached D10 before end / validly scored and reached D10 only at end /
  validly scored and never reached D10 / not validly scored (with reason).

## Entry event universe (P1/P3/P4)

- All first causal D10 crossings per regime (definition in SPEC.md) with
  `observation_time` strictly before the regime's end `close_ts`, within the
  economics windows (2025-03-01..2025-12-30, 2026-01-01..2026-04-29).
- Crossings at `observation_time == regime_end_close_ts` are excluded from
  entries (flip causally known 1 s before the score) and logged to the
  same-timestamp audit.
- Actionability in NT additionally requires: strategy flat at signal
  processing, originating regime's attempt unused, and a 1s bar available to
  fill on. Signals skipped for these reasons are logged with skip reasons —
  the offline event universe and the NT-actioned universe are reconciled in
  `audit/entry_timing_audit.parquet`.

## Trade population accounting

- Every NT trade carries exactly one final status:
  `stop_before_flip | stop_after_flip | d10_exit | opposite_regime_flip_exit |
  data_end_censored`. A fail-fast completeness audit halts reporting on any
  violation (missing/duplicate reason, exit before entry, D10 exit keyed to a
  regime id other than the confirmed regime).
- `data_end_censored` trades are excluded from completed-trade economics and
  reported by count.
- No trade filtering of any other kind (no dropna on outcomes, no
  resolved-only cohorting).

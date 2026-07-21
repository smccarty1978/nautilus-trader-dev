# 2024 5s-Cadence Short-RTH Entry Surface — Backfill

## Atlas rebuild (Option A: 5s cadence, no legacy parity)

- Runtime: 258.2s
- Checkpoints: 3,934,542 across 27,489 regimes
- Causal audit: 0 negative excursion cells, 0 MFE monotonicity violations, 0 MAE monotonicity violations
- Feature columns present: 149 (expected 149)

## Score-independent surface funnel (checkpoints / distinct regimes)

| Stage | Checkpoints | Distinct regimes |
|--|--:|--:|
| all | 3,934,542 | 27,489 |
| bullish_regime | 2,045,236 | 13,743 |
| established | 715,847 | 5,873 |
| rth | 204,612 | 1,672 |
| valid_fill | 204,611 | 1,672 |
| rth_boundary_divergence | 62 | 2 |

Surface build runtime: 50.3s

## RTH boundary diagnostic (decision-time vs fill-time)

- Diverging checkpoints: 62
- Affected regimes: 2
- Final surface uses fill-time classification (remediated convention, matches `run_ladder.py`).
- These checkpoints are counted, not silently dropped or misclassified -- divergence does not change candidate eligibility because RTH is evaluated once, on `fill_ts`, at the point the row is (or isn't) admitted to the surface.

## Missing-data gap scan (>300s)

- Total gaps: 258
- Classification: {'weekend_or_holiday': 52, 'multi_day_holiday_likely': 1, 'SUSPICIOUS_INTRADAY': 8, 'daily_maintenance_break': 197}
- **SUSPICIOUS_INTRADAY gaps found: 8** -- review before trusting this year:
  - 2024-01-15 17:59:59+00:00 -> 2024-01-15 23:00:00+00:00 (18001s)
  - 2024-02-19 17:59:59+00:00 -> 2024-02-19 23:00:00+00:00 (18001s)
  - 2024-05-27 16:59:59+00:00 -> 2024-05-27 22:00:00+00:00 (18001s)
  - 2024-06-19 16:59:59+00:00 -> 2024-06-19 22:00:00+00:00 (18001s)
  - 2024-07-04 16:59:59+00:00 -> 2024-07-04 22:00:00+00:00 (18001s)
  - 2024-09-02 16:59:59+00:00 -> 2024-09-02 22:00:00+00:00 (18001s)
  - 2024-11-28 17:59:59+00:00 -> 2024-11-28 23:00:00+00:00 (18001s)
  - 2024-07-03 17:14:59+00:00 -> 2024-07-03 22:00:00+00:00 (17101s)

Top 10 gaps by duration:

  - 2024-03-28 20:59:59+00:00 -> 2024-03-31 22:00:00+00:00 (262801s) [weekend_or_holiday]
  - 2024-11-29 18:14:59+00:00 -> 2024-12-01 23:00:00+00:00 (189901s) [weekend_or_holiday]
  - 2024-11-01 20:59:59+00:00 -> 2024-11-03 23:00:00+00:00 (180001s) [weekend_or_holiday]
  - 2024-03-01 21:59:58+00:00 -> 2024-03-03 23:00:00+00:00 (176402s) [weekend_or_holiday]
  - 2024-03-22 20:59:58+00:00 -> 2024-03-24 22:00:00+00:00 (176402s) [weekend_or_holiday]
  - 2024-04-12 20:59:58+00:00 -> 2024-04-14 22:00:00+00:00 (176402s) [weekend_or_holiday]
  - 2024-06-21 20:59:58+00:00 -> 2024-06-23 22:00:00+00:00 (176402s) [weekend_or_holiday]
  - 2024-07-05 20:59:58+00:00 -> 2024-07-07 22:00:00+00:00 (176402s) [weekend_or_holiday]
  - 2024-08-23 20:59:58+00:00 -> 2024-08-25 22:00:00+00:00 (176402s) [weekend_or_holiday]
  - 2024-09-27 20:59:58+00:00 -> 2024-09-29 22:00:00+00:00 (176402s) [weekend_or_holiday]

## Feature completeness

- Expected feature columns: 149, present: 149
- Missing columns: none
- Overall NaN rate (all checkpoints): 0.0002
- Surface-row NaN rate: 0.0000
- Top-NaN columns: {'activity_duration_median_30m': 0.0006475976111069598, 'seq_12r_position_pct': 0.00046358635897138727, 'seq_12r_dist_to_high_atr': 0.00046358635897138727, 'seq_12r_dist_to_low_atr': 0.00046358635897138727, 'seq_12r_range_atr': 0.00046358635897138727, 'seq_12r_perfect_alternation': 0.00046358635897138727, 'seq_12r_efficiency': 0.00046358635897138727, 'seq_12r_disp_atr': 0.00046358635897138727, 'seq_12r_mean_overlap': 0.00046358635897138727, 'seq_12r_median_overlap': 0.00046358635897138727}

## Policy A label availability (seq-1-per-regime feasibility check)

- Seq-1 candidates: 1,672
- Labeled successfully: 1,672
- Label errors: 0
- Exit-reason counts: {'confirmation_timeout_exit': 848, 'preflip_policy_stop': 566, 'original_opposing_flip_exit': 251, 'original_stop_after_aligned_flip': 7}
- Exit-reason PnL: {'confirmation_timeout_exit': 33740.0, 'original_opposing_flip_exit': 114630.0, 'original_stop_after_aligned_flip': -1390.4069806843472, 'preflip_policy_stop': -157065.9139860837}
- pre_alignment_stop_rate: 0.3385, timeout_rate: 0.5072, post_alignment_stop_rate: 0.0042, opposing_flip_rate: 0.1501
- Net PnL sum / mean (sanity check only, NOT a claimed result): $-10,086 / $-6.03
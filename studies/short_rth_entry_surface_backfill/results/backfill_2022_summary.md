# 2022 5s-Cadence Short-RTH Entry Surface — Backfill

## Atlas rebuild (Option A: 5s cadence, no legacy parity)

- Runtime: 263.3s
- Checkpoints: 3,954,384 across 27,111 regimes
- Causal audit: 0 negative excursion cells, 0 MFE monotonicity violations, 0 MAE monotonicity violations
- Feature columns present: 149 (expected 149)

## Score-independent surface funnel (checkpoints / distinct regimes)

| Stage | Checkpoints | Distinct regimes |
|--|--:|--:|
| all | 3,954,384 | 27,111 |
| bullish_regime | 1,992,673 | 13,554 |
| established | 672,400 | 5,804 |
| rth | 192,378 | 1,711 |
| valid_fill | 192,378 | 1,711 |
| rth_boundary_divergence | 0 | 0 |

Surface build runtime: 48.8s

## RTH boundary diagnostic (decision-time vs fill-time)

- Diverging checkpoints: 0
- Affected regimes: 0
- Final surface uses fill-time classification (remediated convention, matches `run_ladder.py`).
- These checkpoints are counted, not silently dropped or misclassified -- divergence does not change candidate eligibility because RTH is evaluated once, on `fill_ts`, at the point the row is (or isn't) admitted to the surface.

## Missing-data gap scan (>300s)

- Total gaps: 257
- Classification: {'weekend_or_holiday': 51, 'SUSPICIOUS_INTRADAY': 7, 'daily_maintenance_break': 199}
- **SUSPICIOUS_INTRADAY gaps found: 7** -- review before trusting this year:
  - 2022-06-20 16:59:58+00:00 -> 2022-06-20 22:00:00+00:00 (18002s)
  - 2022-01-17 17:59:59+00:00 -> 2022-01-17 23:00:00+00:00 (18001s)
  - 2022-02-21 17:59:59+00:00 -> 2022-02-21 23:00:00+00:00 (18001s)
  - 2022-05-30 16:59:59+00:00 -> 2022-05-30 22:00:00+00:00 (18001s)
  - 2022-07-04 16:59:59+00:00 -> 2022-07-04 22:00:00+00:00 (18001s)
  - 2022-09-05 16:59:59+00:00 -> 2022-09-05 22:00:00+00:00 (18001s)
  - 2022-11-24 17:59:59+00:00 -> 2022-11-24 23:00:00+00:00 (18001s)

Top 10 gaps by duration:

  - 2022-04-14 20:59:58+00:00 -> 2022-04-17 22:00:00+00:00 (262802s) [weekend_or_holiday]
  - 2022-12-23 21:59:59+00:00 -> 2022-12-26 23:00:00+00:00 (262801s) [weekend_or_holiday]
  - 2022-11-25 18:14:59+00:00 -> 2022-11-27 23:00:00+00:00 (189901s) [weekend_or_holiday]
  - 2022-11-04 20:59:58+00:00 -> 2022-11-06 23:00:00+00:00 (180002s) [weekend_or_holiday]
  - 2022-02-25 21:59:57+00:00 -> 2022-02-27 23:00:00+00:00 (176403s) [weekend_or_holiday]
  - 2022-03-04 21:59:57+00:00 -> 2022-03-06 23:00:00+00:00 (176403s) [weekend_or_holiday]
  - 2022-04-01 20:59:58+00:00 -> 2022-04-03 22:00:00+00:00 (176402s) [weekend_or_holiday]
  - 2022-04-22 20:59:58+00:00 -> 2022-04-24 22:00:00+00:00 (176402s) [weekend_or_holiday]
  - 2022-06-10 20:59:58+00:00 -> 2022-06-12 22:00:00+00:00 (176402s) [weekend_or_holiday]
  - 2022-08-05 20:59:58+00:00 -> 2022-08-07 22:00:00+00:00 (176402s) [weekend_or_holiday]

## Feature completeness

- Expected feature columns: 149, present: 149
- Missing columns: none
- Overall NaN rate (all checkpoints): 0.0002
- Surface-row NaN rate: 0.0000
- Top-NaN columns: {'activity_duration_median_30m': 0.0005975646270063808, 'seq_12r_position_pct': 0.000554827249958527, 'seq_12r_dist_to_high_atr': 0.000554827249958527, 'seq_12r_dist_to_low_atr': 0.000554827249958527, 'seq_12r_range_atr': 0.000554827249958527, 'seq_12r_perfect_alternation': 0.000554827249958527, 'seq_12r_efficiency': 0.000554827249958527, 'seq_12r_disp_atr': 0.000554827249958527, 'seq_12r_mean_overlap': 0.000554827249958527, 'seq_12r_median_overlap': 0.000554827249958527}

## Policy A label availability (seq-1-per-regime feasibility check)

- Seq-1 candidates: 1,711
- Labeled successfully: 1,711
- Label errors: 0
- Exit-reason counts: {'confirmation_timeout_exit': 798, 'preflip_policy_stop': 645, 'original_opposing_flip_exit': 261, 'original_stop_after_aligned_flip': 7}
- Exit-reason PnL: {'confirmation_timeout_exit': 75510.0, 'original_opposing_flip_exit': 126110.0, 'original_stop_after_aligned_flip': -2816.6498976882212, 'preflip_policy_stop': -225845.09454196197}
- pre_alignment_stop_rate: 0.3770, timeout_rate: 0.4664, post_alignment_stop_rate: 0.0041, opposing_flip_rate: 0.1525
- Net PnL sum / mean (sanity check only, NOT a claimed result): $-27,042 / $-15.80
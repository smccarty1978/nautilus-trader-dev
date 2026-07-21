# 2023 5s-Cadence Short-RTH Entry Surface — Backfill

## Atlas rebuild (Option A: 5s cadence, no legacy parity)

- Runtime: 270.9s
- Checkpoints: 3,956,507 across 27,996 regimes
- Causal audit: 0 negative excursion cells, 0 MFE monotonicity violations, 0 MAE monotonicity violations
- Feature columns present: 149 (expected 149)

## Score-independent surface funnel (checkpoints / distinct regimes)

| Stage | Checkpoints | Distinct regimes |
|--|--:|--:|
| all | 3,956,507 | 27,996 |
| bullish_regime | 2,027,211 | 13,998 |
| established | 689,542 | 5,911 |
| rth | 204,742 | 1,732 |
| valid_fill | 204,742 | 1,732 |
| rth_boundary_divergence | 0 | 0 |

Surface build runtime: 49.8s

## RTH boundary diagnostic (decision-time vs fill-time)

- Diverging checkpoints: 0
- Affected regimes: 0
- Final surface uses fill-time classification (remediated convention, matches `run_ladder.py`).
- These checkpoints are counted, not silently dropped or misclassified -- divergence does not change candidate eligibility because RTH is evaluated once, on `fill_ts`, at the point the row is (or isn't) admitted to the surface.

## Missing-data gap scan (>300s)

- Total gaps: 257
- Classification: {'weekend_or_holiday': 51, 'SUSPICIOUS_INTRADAY': 8, 'daily_maintenance_break': 198}
- **SUSPICIOUS_INTRADAY gaps found: 8** -- review before trusting this year:
  - 2023-11-23 17:59:56+00:00 -> 2023-11-23 23:00:00+00:00 (18004s)
  - 2023-05-29 16:59:57+00:00 -> 2023-05-29 22:00:00+00:00 (18003s)
  - 2023-01-16 17:59:59+00:00 -> 2023-01-16 23:00:00+00:00 (18001s)
  - 2023-02-20 17:59:59+00:00 -> 2023-02-20 23:00:00+00:00 (18001s)
  - 2023-06-19 16:59:59+00:00 -> 2023-06-19 22:00:00+00:00 (18001s)
  - 2023-07-04 16:59:59+00:00 -> 2023-07-04 22:00:00+00:00 (18001s)
  - 2023-09-04 16:59:59+00:00 -> 2023-09-04 22:00:00+00:00 (18001s)
  - 2023-07-03 17:14:58+00:00 -> 2023-07-03 22:00:00+00:00 (17102s)

Top 10 gaps by duration:

  - 2023-12-22 21:59:59+00:00 -> 2023-12-25 23:00:00+00:00 (262801s) [weekend_or_holiday]
  - 2023-04-07 13:14:59+00:00 -> 2023-04-09 22:00:00+00:00 (204301s) [weekend_or_holiday]
  - 2023-11-24 18:14:59+00:00 -> 2023-11-26 23:00:00+00:00 (189901s) [weekend_or_holiday]
  - 2023-11-03 20:59:59+00:00 -> 2023-11-05 23:00:00+00:00 (180001s) [weekend_or_holiday]
  - 2023-07-14 20:59:56+00:00 -> 2023-07-16 22:00:00+00:00 (176404s) [weekend_or_holiday]
  - 2023-05-05 20:59:57+00:00 -> 2023-05-07 22:00:00+00:00 (176403s) [weekend_or_holiday]
  - 2023-05-12 20:59:57+00:00 -> 2023-05-14 22:00:00+00:00 (176403s) [weekend_or_holiday]
  - 2023-06-09 20:59:57+00:00 -> 2023-06-11 22:00:00+00:00 (176403s) [weekend_or_holiday]
  - 2023-02-10 21:59:58+00:00 -> 2023-02-12 23:00:00+00:00 (176402s) [weekend_or_holiday]
  - 2023-05-26 20:59:58+00:00 -> 2023-05-28 22:00:00+00:00 (176402s) [weekend_or_holiday]

## Feature completeness

- Expected feature columns: 149, present: 149
- Missing columns: none
- Overall NaN rate (all checkpoints): 0.0002
- Surface-row NaN rate: 0.0000
- Top-NaN columns: {'activity_duration_median_30m': 0.0005714636673206947, 'seq_12r_position_pct': 0.00044913354127769774, 'seq_12r_dist_to_high_atr': 0.00044913354127769774, 'seq_12r_dist_to_low_atr': 0.00044913354127769774, 'seq_12r_range_atr': 0.00044913354127769774, 'seq_12r_perfect_alternation': 0.00044913354127769774, 'seq_12r_efficiency': 0.00044913354127769774, 'seq_12r_disp_atr': 0.00044913354127769774, 'seq_12r_mean_overlap': 0.00044913354127769774, 'seq_12r_median_overlap': 0.00044913354127769774}

## Policy A label availability (seq-1-per-regime feasibility check)

- Seq-1 candidates: 1,732
- Labeled successfully: 1,732
- Label errors: 0
- Exit-reason counts: {'confirmation_timeout_exit': 822, 'preflip_policy_stop': 610, 'original_opposing_flip_exit': 292, 'original_stop_after_aligned_flip': 8}
- Exit-reason PnL: {'confirmation_timeout_exit': 34310.0, 'original_opposing_flip_exit': 101975.0, 'original_stop_after_aligned_flip': -1609.603350173602, 'preflip_policy_stop': -139439.46410009067}
- pre_alignment_stop_rate: 0.3522, timeout_rate: 0.4746, post_alignment_stop_rate: 0.0046, opposing_flip_rate: 0.1686
- Net PnL sum / mean (sanity check only, NOT a claimed result): $-4,764 / $-2.75
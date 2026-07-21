# v2 Collector Parity Harness Report

- Collector features: `studies/1m_regime_collector_v2/results/v2_feature_snapshots_SMOKE_20250407_20250411.parquet`
- Collector labels:   `studies/1m_regime_collector_v2/results/v2_outcome_labels_SMOKE_20250407_20250411.parquet`
- Sample size: 1000 (RTH 500, ETH 500)
- Random seed: 123
- Harness elapsed: 9.9s

========================================================================
Gate 2/3 — Fillability + fill_time/fill_price parity
========================================================================
  Total checkpoints: 1000
  All-match: 1000 / 1000  (100.00%)
  Mismatches by kind:
    fillable: 0
    fill_time_actual: 0
    fill_price: 0
  RTH: n=500  all-match 500/500 (100.00%)
  ETH: n=500  all-match 500/500 (100.00%)


========================================================================
Gate 4 — Label-origin parity (MFE/MAE + brackets)
========================================================================
  Total fillable checkpoints: 956
  All-match: 956 / 956  (100.00%)
  Mismatches by kind:
    MFE grid: 0 rows (max delta 0.00e+00)
    MAE grid: 0 rows (max delta 0.00e+00)
    Bracket: 0 rows
  RTH: n=477  all-match 477/477 (100.00%)
  ETH: n=479  all-match 479/479 (100.00%)


========================================================================
Gate 1 — Feature parity (spot)
========================================================================
  Spot-checked features: is_rth_checkpoint, minutes_since_rth_open_checkpoint
  Total sampled: 1000
  is_rth_checkpoint match: 1000 / 1000 (100.00%)
  minutes_since_rth match: 1000 / 1000 (100.00%)
  All-match: 1000 / 1000

  NOTE: full 189-feature re-derivation is out of scope for
  phase-1. Determinism (run-twice hash equality) is the
  primary feature-parity gate — see next section.


========================================================================
Gate 1 — Determinism (run-twice)
========================================================================
  Features shape: (7353, 203)  match: True
  Labels   shape: (7353, 59)  match: True
  Features hash match: True
  Labels   hash match: True


========================================================================
OVERALL VERDICT
========================================================================
  Gate 2/3 (fill parity):       PASS
  Gate 4 (label-origin parity): PASS
  Gate 1 (spot feature parity): PASS
  Gate 1 (determinism):         PASS

  Overall: PASS — clear to run full 6y collection

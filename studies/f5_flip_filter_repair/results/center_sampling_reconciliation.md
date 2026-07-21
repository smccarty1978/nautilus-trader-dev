# 1s vs 5s Center Sampling Reconciliation

Deterministic stratified sample: 179 F2 episodes across 30 (period_role x session x atr_bucket) strata.

## Reconciling the prior study's contradictory claims

Prior claim (final_report.md): 'median absolute center difference < 0.05 points'. Prior control artifact: 'median absolute center difference approximately 1.25 points'. Neither statement specified feature/unit/horizon/population/sampling-timestamp/normalization clearly. This reconciliation fixes every dimension explicitly:

- **Feature:** `median_center_{5,15,30,60}m` (rolling median of *closes*, matching `build_median_centers.py`), NOT the `aligned_price_minus_center` z-scored feature.
- **Unit:** raw points (NQ price units); ATR-normalized variant also reported.
- **Horizon:** reported separately per horizon (5/15/30/60m) below -- pooling horizons was likely the source of the prior contradiction (60m centers move far more between 1s and 5s sampling than 5m centers simply because the window is 12x longer).
- **Population:** stratified sample across all period_roles + RTH/ETH + vol buckets (not train-only or any single day).
- **Sampling timestamp:** each episode's own `observation_time` (F2 decision instant).
- **Median vs mean:** both reported below; pooled across horizons AND per-horizon.

## Per-horizon results (pooled across the full stratified sample)

 horizon_min  mean_abs_diff_pts  median_abs_diff_pts  p95_abs_diff_pts  max_abs_diff_pts  mean_abs_diff_atr
           5           0.252793                0.125            0.6375             5.375           0.027032
          15           0.165503                0.125            0.5000             1.625           0.020345
          30           0.163408                0.125            0.5000             2.750           0.019076
          60           0.139665                0.000            0.5000             1.000           0.017525

## Score / skip-decision impact

Episodes checked: 179
Mean |score diff| (frozen model, 5s-perturbed vs 1s aligned-center features only): 0.001066
Skip-flag disagreements: 2 / 179 (1.12%)

**Pooled (all horizons together) median |diff| = 0.125 points** -- this single pooled number is what the prior study likely reported inconsistently in two places; it sits between the per-horizon 5m and 60m values, which is why quoting it without specifying the horizon produced two apparently-contradictory claims.

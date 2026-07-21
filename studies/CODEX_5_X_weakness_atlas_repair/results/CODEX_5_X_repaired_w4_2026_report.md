# CODEX 5.X — Repaired W4 2026 Final Test

The frozen structure, calibrators, and thresholds were loaded without change.
No 2026 value altered the manifest.

## Directional model metrics

| model            | segment          |   count |   base_rate |   roc_auc |   pr_auc |    brier | window          | calibrated   |
|:-----------------|:-----------------|--------:|------------:|----------:|---------:|---------:|:----------------|:-------------|
| directional_pair | prevailing_long  |  653438 |    0.388927 |  0.772371 | 0.675266 | 0.186595 | 2026_final_test | True         |
| directional_pair | prevailing_short |  636402 |    0.392925 |  0.768587 | 0.672727 | 0.188604 | 2026_final_test | True         |

## Score distributions and strict crossings

| window          |   direction |   threshold |   checkpoint_count |   finite_score_rate |   score_mean |   score_std |   score_p01 |   score_p10 |   score_p50 |   score_p90 |   score_p99 |   checkpoint_at_or_above_rate |   strict_cross_count |   regime_count |   crossed_regime_count |   strict_cross_regime_rate |
|:----------------|------------:|------------:|-------------------:|--------------------:|-------------:|------------:|------------:|------------:|------------:|------------:|------------:|------------------------------:|---------------------:|---------------:|-----------------------:|---------------------------:|
| 2026_final_test |          -1 |    0.718365 |             636402 |                   1 |     0.393046 |    0.226939 |    0.041952 |    0.103686 |    0.367573 |    0.718365 |    0.902259 |                      0.102944 |                11794 |           4458 |                   3854 |                   0.864513 |
| 2026_final_test |           1 |    0.68835  |             653438 |                   1 |     0.378989 |    0.225078 |    0.037508 |    0.085733 |    0.360762 |    0.700211 |    0.888062 |                      0.112594 |                12873 |           4463 |                   4042 |                   0.905669 |

# CODEX 5.X — Repaired W4 Freeze Report

Selected structure: `directional_pair`

Pre-2026 W4 gate: `PASS`

## Structure comparison (2025-H1)

| model               | segment          |   count |   base_rate |   roc_auc |   pr_auc |    brier | window            |
|:--------------------|:-----------------|--------:|------------:|----------:|---------:|---------:|:------------------|
| pooled              | all              | 1940932 |    0.378854 |  0.772222 | 0.670323 | 0.185103 | 2025_H1_selection |
| pooled              | prevailing_long  |  991452 |    0.365043 |  0.773225 | 0.658952 | 0.182368 | 2025_H1_selection |
| pooled              | prevailing_short |  949480 |    0.393275 |  0.770553 | 0.681245 | 0.187959 | 2025_H1_selection |
| pooled_interactions | all              | 1940932 |    0.378854 |  0.772029 | 0.670008 | 0.185183 | 2025_H1_selection |
| pooled_interactions | prevailing_long  |  991452 |    0.365043 |  0.772957 | 0.658239 | 0.182486 | 2025_H1_selection |
| pooled_interactions | prevailing_short |  949480 |    0.393275 |  0.770454 | 0.681114 | 0.188    | 2025_H1_selection |
| directional_pair    | all              | 1940932 |    0.378854 |  0.771551 | 0.669083 | 0.185365 | 2025_H1_selection |
| directional_pair    | prevailing_long  |  991452 |    0.365043 |  0.772405 | 0.657758 | 0.182673 | 2025_H1_selection |
| directional_pair    | prevailing_short |  949480 |    0.393275 |  0.770096 | 0.679958 | 0.188176 | 2025_H1_selection |
| long_only           | prevailing_long  |  991452 |    0.365043 |  0.772405 | 0.657758 | 0.182673 | 2025_H1_selection |
| short_only          | prevailing_short |  949480 |    0.393275 |  0.770096 | 0.679958 | 0.188176 | 2025_H1_selection |

## Candidate selection summary

| model               |   macro_direction_auc |   direction_auc_gap |   auc_long |   auc_short |   complexity_rank |
|:--------------------|----------------------:|--------------------:|-----------:|------------:|------------------:|
| pooled              |              0.771889 |            0.002672 |   0.773225 |    0.770553 |                 0 |
| pooled_interactions |              0.771706 |            0.002503 |   0.772957 |    0.770454 |                 1 |
| directional_pair    |              0.77125  |            0.002309 |   0.772405 |    0.770096 |                 2 |

## H1/H2 regime-boundary purge

`{"boundary_ns": 1751328000000000000, "calibration_regime_count": 13971, "purged_regime_count": 1, "purged_regime_start_ns": [1751327880000000000], "selection_regime_count": 13165}`

## Calibrated score distributions and crossings (2025-H2)

| window              |   direction |   threshold |   checkpoint_count |   finite_score_rate |   score_mean |   score_std |   score_p01 |   score_p10 |   score_p50 |   score_p90 |   score_p99 |   checkpoint_at_or_above_rate |   strict_cross_count |   regime_count |   crossed_regime_count |   strict_cross_regime_rate |
|:--------------------|------------:|------------:|-------------------:|--------------------:|-------------:|------------:|------------:|------------:|------------:|------------:|------------:|------------------------------:|---------------------:|---------------:|-----------------------:|---------------------------:|
| 2025_H2_calibration |          -1 |    0.718365 |             970118 |                   1 |     0.397737 |    0.226038 |     0.04926 |    0.108935 |    0.367573 |    0.718365 |    0.897849 |                      0.103567 |                17755 |           6990 |                   5915 |                   0.846209 |
| 2025_H2_calibration |           1 |    0.68835  |            1023184 |                   1 |     0.364262 |    0.223211 |     0.03804 |    0.085733 |    0.324712 |    0.68835  |    0.888062 |                      0.101802 |                18456 |           6981 |                   6122 |                   0.876952 |

## Frozen-model score distributions and crossings (full 2025 development year)

| window                |   direction |   threshold |   checkpoint_count |   finite_score_rate |   score_mean |   score_std |   score_p01 |   score_p10 |   score_p50 |   score_p90 |   score_p99 |   checkpoint_at_or_above_rate |   strict_cross_count |   regime_count |   crossed_regime_count |   strict_cross_regime_rate |
|:----------------------|------------:|------------:|-------------------:|--------------------:|-------------:|------------:|------------:|------------:|------------:|------------:|------------:|------------------------------:|---------------------:|---------------:|-----------------------:|---------------------------:|
| 2025_full_development |          -1 |    0.718365 |            1919630 |                   1 |     0.400064 |    0.227016 |     0.04926 |    0.108935 |    0.367573 |    0.718365 |    0.902259 |                      0.106641 |                35624 |          13571 |                  11627 |                   0.856753 |
| 2025_full_development |           1 |    0.68835  |            2014636 |                   1 |     0.36824  |    0.225118 |     0.03804 |    0.085733 |    0.346529 |    0.700211 |    0.888062 |                      0.10691  |                36662 |          13566 |                  11994 |                   0.884122 |

Thresholds: prevailing long `0.688349871371`, prevailing short
`0.718365337272`.

No 2026 atlas, label, score, or metric was accessed during this freeze.

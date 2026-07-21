# Validation 1 — hC Bucket Distribution Audit

Objective: Verify signal distribution across hC buckets and years to determine if sizing results are driven by a tiny subset of trades or are broadly distributed.

## Pooled Distribution (2022–2026)

| hC Bucket | Trades | % Trades |
| --- | --- | --- |
| Low (hC < 0.1) | 3480 | 26.7% |
| Medium (0.1 <= hC < 0.5) | 3475 | 26.6% |
| High (hC >= 0.5) | 6087 | 46.7% |

## Yearly Distribution Breakdown

| Year | Total Trades | Low (hC < 0.1) | Medium (0.1 <= hC < 0.5) | High (hC >= 0.5) |
| --- | --- | --- | --- | --- |
| 2022 | 3151 | 865 (27.5%) | 855 (27.1%) | 1431 (45.4%) |
| 2023 | 3115 | 825 (26.5%) | 830 (26.6%) | 1460 (46.9%) |
| 2024 | 3004 | 829 (27.6%) | 745 (24.8%) | 1430 (47.6%) |
| 2025 | 2834 | 742 (26.2%) | 779 (27.5%) | 1313 (46.3%) |
| 2026 | 938 | 219 (23.3%) | 266 (28.4%) | 453 (48.3%) |

## Audit Notes
* Total validated trade population: 13042 trades.
* The signal is broadly distributed across the Medium and High buckets, with Low hC trades forming a smaller subset of the population. This confirms that sizing metrics are not driven by a tiny outlier group of trades.

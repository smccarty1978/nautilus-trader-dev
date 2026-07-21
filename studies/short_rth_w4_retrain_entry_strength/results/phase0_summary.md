# Phase 0 — Data Readiness

## Decision: `PHASE0_PASS`

## 2021-2024 feature join

| Year | Rows | Join rate | Fully-missing-feature rows |
|--:|--:|--:|--:|
| 2021 | 212,241 | 1.0000 | 0 |
| 2022 | 192,378 | 1.0000 | 0 |
| 2023 | 204,742 | 1.0000 | 0 |
| 2024 | 204,611 | 1.0000 | 0 |

## 2025-2026 full-surface labeling + feature join

| Year | Surface rows | Labeled | Censored | Errors | Join rate |
|--:|--:|--:|--:|--:|--:|
| 2025 | 198,255 | 198,255 | 0 | 0 | 1.0000 |
| 2026 | 63,021 | 63,021 | 0 | 0 | 1.0000 |

## Control reconciliation (crossing-based, 650/222)

| Year | Crossing candidates | Expected | Gate | Missing from featured surface |
|--:|--:|--:|--|--:|
| 2025 | 650 | 650 | PASS | 0 |
| 2026 | 222 | 222 | PASS | 0 |

Combined 2021-2024 rows: 813,972

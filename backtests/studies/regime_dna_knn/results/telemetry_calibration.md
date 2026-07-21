# Telemetry Calibration — Phase 1 (raw features, IS 2021–2024)

Each raw telemetry feature is decile-sorted on IS; we report the LOCAL forward outcomes (next-3-bar new-extreme %, next-3-bar opposite-flip %, next-5-bar MFE/MAE in ATR). GATE 1: a feature is informative only if it sorts an outcome MONOTONICALLY (|Spearman(decile, outcome)| high) across deciles.

## bar_index  — Spearman(decile→): expansion -1.00, oppflip +0.19, MAE -0.52
| Decile | n | Next3 Expansion% | Next3 OppFlip% | Next5 MFE | Next5 MAE |
| --- | --- | --- | --- | --- | --- |
| 1 | 210,011 | 79% | 22% | 1.17 | 1.01 |
| 2 | 93,562 | 75% | 24% | 1.16 | 0.99 |
| 3 | 85,765 | 74% | 24% | 1.16 | 0.98 |
| 4 | 149,999 | 72% | 24% | 1.17 | 0.98 |
| 5 | 125,185 | 72% | 23% | 1.18 | 0.98 |
| 6 | 104,841 | 71% | 23% | 1.19 | 0.98 |
| 7 | 87,920 | 70% | 23% | 1.18 | 0.98 |
| 8 | 135,018 | 69% | 24% | 1.18 | 0.98 |
| 9 | 113,014 | 67% | 23% | 1.19 | 0.98 |
| 10 | 111,020 | 65% | 24% | 1.10 | 0.92 |

## current_pullback_from_peak  — Spearman(decile→): expansion -0.99, oppflip +1.00, MAE -0.42
| Decile | n | Next3 Expansion% | Next3 OppFlip% | Next5 MFE | Next5 MAE |
| --- | --- | --- | --- | --- | --- |
| 1 | 121,634 | 92% | 10% | 1.14 | 1.09 |
| 2 | 121,633 | 86% | 12% | 1.13 | 1.03 |
| 3 | 121,634 | 81% | 15% | 1.14 | 1.00 |
| 4 | 121,633 | 76% | 18% | 1.14 | 0.97 |
| 5 | 121,634 | 71% | 21% | 1.14 | 0.95 |
| 6 | 121,633 | 67% | 25% | 1.13 | 0.93 |
| 7 | 121,633 | 64% | 28% | 1.14 | 0.91 |
| 8 | 121,634 | 61% | 32% | 1.14 | 0.91 |
| 9 | 121,633 | 60% | 35% | 1.18 | 0.92 |
| 10 | 121,634 | 61% | 35% | 1.41 | 1.09 |

## consecutive_non_continuation_bars  — Spearman(decile→): expansion -1.00, oppflip +1.00, MAE -1.00
| Decile | n | Next3 Expansion% | Next3 OppFlip% | Next5 MFE | Next5 MAE |
| --- | --- | --- | --- | --- | --- |
| 1 | 658,391 | 78% | 17% | 1.22 | 1.06 |
| 2 | 151,274 | 67% | 28% | 1.14 | 0.93 |
| 3 | 108,167 | 66% | 30% | 1.12 | 0.91 |
| 4 | 78,055 | 65% | 31% | 1.11 | 0.89 |
| 5 | 129,275 | 63% | 31% | 1.10 | 0.86 |
| 6 | 91,173 | 61% | 31% | 1.07 | 0.83 |

## progress_efficiency_so_far  — Spearman(decile→): expansion +1.00, oppflip -0.96, MAE +0.93
| Decile | n | Next3 Expansion% | Next3 OppFlip% | Next5 MFE | Next5 MAE |
| --- | --- | --- | --- | --- | --- |
| 1 | 121,648 | 63% | 40% | 1.06 | 0.83 |
| 2 | 121,627 | 64% | 36% | 1.08 | 0.85 |
| 3 | 121,667 | 66% | 31% | 1.10 | 0.89 |
| 4 | 121,631 | 68% | 26% | 1.14 | 0.93 |
| 5 | 121,597 | 70% | 22% | 1.17 | 0.97 |
| 6 | 122,493 | 72% | 19% | 1.21 | 1.03 |
| 7 | 121,645 | 75% | 16% | 1.25 | 1.06 |
| 8 | 120,761 | 77% | 14% | 1.27 | 1.10 |
| 9 | 121,825 | 81% | 13% | 1.23 | 1.10 |
| 10 | 121,441 | 83% | 15% | 1.17 | 1.04 |

## distance_from_flip_open  — Spearman(decile→): expansion +0.66, oppflip -1.00, MAE +1.00
| Decile | n | Next3 Expansion% | Next3 OppFlip% | Next5 MFE | Next5 MAE |
| --- | --- | --- | --- | --- | --- |
| 1 | 121,634 | 63% | 40% | 1.05 | 0.81 |
| 2 | 121,634 | 70% | 33% | 1.05 | 0.84 |
| 3 | 121,633 | 72% | 28% | 1.07 | 0.88 |
| 4 | 121,633 | 73% | 24% | 1.10 | 0.92 |
| 5 | 121,636 | 74% | 22% | 1.11 | 0.95 |
| 6 | 121,631 | 73% | 20% | 1.13 | 0.97 |
| 7 | 121,633 | 73% | 19% | 1.15 | 0.99 |
| 8 | 121,634 | 73% | 18% | 1.19 | 1.02 |
| 9 | 121,633 | 73% | 16% | 1.26 | 1.07 |
| 10 | 121,634 | 74% | 14% | 1.58 | 1.34 |

## GATE 1 verdict
> [!TIP]
> **GATE 1 PASS.** 5 feature(s) sort a local outcome monotonically (|Spearman|>=0.80): bar_index(max ρ 1.00), current_pullback_from_peak(max ρ 1.00), consecutive_non_continuation_bars(max ρ 1.00), progress_efficiency_so_far(max ρ 1.00), distance_from_flip_open(max ρ 1.00). Proceed to Phase 2 (KNN component diagnostics) — but note monotonic LOCAL calibration is necessary, not sufficient; Phase 3 Oracle is the real ceiling test.
## Phase 2 — telemetry component calibration (OOS 2025–2026)
| Component | Spearman(decile→actual) | D1 actual | D10 actual |
| --- | --- | --- | --- |
| P_velocity | +1.00 | 54% | 94% |
| P_pullback_risk | +1.00 | 34% | 80% |
| P_flip_risk | +1.00 | 6% | 43% |
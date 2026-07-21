# Audit — pQF mapping (Model B P(QuickFailure))

- Records: **100,868** (alive-at-bar-4 regimes 2022-2026)
- regime_start_ts duplicates (live key collisions): **0** PASS
- Feature window: `P.feats_through(df, M, 3)` = bars 0..3 only (leak-corrected k=Nbar). Decision_ts = bar-3 close < bar-4 entry. PASS
- Target: QuickFailure among bar-4 survivors. Walk-forward train IS<Y (OOS capped IS<2025). No same-year/future training. PASS
- Thresholds: IS-derived percentiles of in-sample IS pQF (portable, not OOS-rank). PASS

## pQF coverage by year
| Year | n (alive@bar4, scored) | mean pQF | QF base rate |
| --- | ---: | ---: | ---: |
| 2022 | 23,056 | 0.317 | 8.3% |
| 2023 | 23,723 | 0.343 | 8.4% |
| 2024 | 23,359 | 0.359 | 8.6% |
| 2025 | 23,098 | 0.355 | 8.2% |
| 2026 | 7,632 | 0.351 | 8.3% |

## IS-derived reject thresholds (reject pQF >= threshold)
| Year | worst 10% | worst 20% | worst 30% | worst 40% | worst 50% |
| --- | --- | --- | --- | --- | --- |
| 2022 | 0.723 | 0.626 | 0.511 | 0.377 | 0.251 |
| 2023 | 0.738 | 0.656 | 0.554 | 0.429 | 0.298 |
| 2024 | 0.745 | 0.664 | 0.561 | 0.444 | 0.325 |
| 2025 | 0.750 | 0.674 | 0.570 | 0.448 | 0.331 |
| 2026 | 0.750 | 0.674 | 0.570 | 0.448 | 0.331 |

> NOTE: universe = early_health_capsule. Phase 3 MUST verify the live NT regime-engine flip set joins to this mapping on regime_start_ts at a high rate; if the capsule is the bar1-confirmed filtered subset, 'all-flips' coverage is incomplete and pQF gating only applies to the covered subset.
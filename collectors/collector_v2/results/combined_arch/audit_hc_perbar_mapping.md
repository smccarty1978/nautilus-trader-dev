# Audit — per-bar hC management-state mapping

- Records: **968,197** (regime,bar) rows, 92,435 distinct regimes
- (regime_start_ts, bars_in_regime) duplicate keys: **0** PASS
- Feature window bars 4..k only (build_states H[i,4:k+1]); action at bar-k close. PASS
- hC_pk cummax & dhC diff(3) on (rid,k)-sorted frame -> backward-looking. PASS
- Walk-forward IS<Y (OOS IS<2025); neighbor targets IS realized. No OOS path leak. PASS
- bars_in_regime = k+1 (k=4 <-> bar-4 close <-> bars_in_regime=5). PASS

## State distribution by year (OOS-relevant)
| Year | n rows | Healthy | SoftStall | HardStall | DETER |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2022 | 225,652 | 16% | 5% | 66% | 13% |
| 2023 | 222,889 | 18% | 5% | 63% | 15% |
| 2024 | 222,840 | 18% | 5% | 62% | 15% |
| 2025 | 223,586 | 18% | 5% | 62% | 14% |
| 2026 | 73,230 | 19% | 5% | 61% | 15% |

## hC by bar (mean), sanity
| bars_in_regime (=k+1) | n | mean hC | mean dd |
| --- | ---: | ---: | ---: |
| 5 | 92,435 | 0.415 | 5854.337 |
| 6 | 84,589 | 0.333 | 3986.967 |
| 7 | 77,224 | 0.289 | 2743.651 |
| 8 | 70,516 | 0.264 | 1832.523 |
| 9 | 64,602 | 0.242 | 1216.245 |
| 10 | 59,098 | 0.230 | 742.330 |
| 11 | 54,156 | 0.213 | 565.333 |
| 12 | 49,625 | 0.201 | 420.263 |
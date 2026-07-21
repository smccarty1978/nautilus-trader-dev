# Causal Collector vs Buggy vs NT — Pullback OOS

**Bug fixed**: collector now uses `next_flip.flip_bar_ts_init` (= 1m bar CLOSE) for regime exit timing and the 1m bar's close price for regime exit price. No more dropping trades based on `fill_ts >= regime_end_ts` (future knowledge). Decisions only filtered if regime already known to be flipped at decision time.

**Comparison**: BUGGY = original `oos_pullback_1atr_<year>.parquet`. CAUSAL = new `causal_pullback_1atr_<year>.parquet`. NT = real runtime trades from `nt_runtime_<year>/nt_trades.parquet`.

## 2024 (OOS)

Confirmed regimes: 5,313. Pullback survivors: 5,064 (95.3%). Buggy version had 4,179 pullback rows.

| Population | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| CAUSAL confirmed-entry baseline (all) | 5,313 | 42.6% | 52.8% | 4.4% | $-8.99 | $-105.57 | 0.91 | $-47,758 | $-54,194 |
| CAUSAL matched baseline | 5,064 | 44.4% | 53.1% | 2.4% | $-3.68 | $-104.68 | 0.96 | $-18,642 | $-33,896 |
| BUGGY pullback | 4,179 | 46.6% | 36.3% | 17.1% | $29.17 | $26.06 | 1.39 | $121,909 | $-3,495 |
| CAUSAL pullback | 5,064 | 38.5% | 46.7% | 14.6% | $-10.53 | $-80.00 | 0.89 | $-53,309 | $-58,649 |
| NT runtime (actual fills) | 5,122 | 38.2% | 46.4% | 15.3% | $-11.31 | $-80.00 | 0.88 | $-57,930 | $-61,605 |

- **Δ CAUSAL pullback vs CAUSAL matched baseline**: **$-6.85/trade** (this is the methodology-corrected pullback edge)
- Δ BUGGY pullback vs CAUSAL pullback (bug impact): **$39.70/trade** (amount of inflation the bug introduced)
- Δ NT actual vs CAUSAL pullback (real-world drag): **$-0.78/trade**

Trade pairing NT vs CAUSAL: 5,058 matched, 64 NT-only, 6 causal-only.
Outcome agreement on matched: 4,917 (97.2%).

Outcome cross-tab (rows = NT, cols = CAUSAL):

```
bracket_100_75_outcome    pt  regime    sl  timeout   All
exit_reason                                              
pt                      1897       5    35        0  1937
regime                     9     723    32        7   771
sl                        45       7  2296        1  2349
timeout                    0       0     0        1     1
All                     1951     735  2363        9  5058
```

On 5,058 matched: NT mean $-11.37, CAUSAL mean $-10.53, Δ **$-0.84**.

## 2025 (in-sample reference)

Confirmed regimes: 5,558. Pullback survivors: 5,248 (94.4%). Buggy version had 4,271 pullback rows.

| Population | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| CAUSAL confirmed-entry baseline (all) | 5,558 | 42.6% | 52.4% | 4.9% | $-11.38 | $-108.98 | 0.92 | $-63,234 | $-79,642 |
| CAUSAL matched baseline | 5,248 | 44.7% | 52.7% | 2.6% | $-3.53 | $-104.36 | 0.97 | $-18,504 | $-42,795 |
| BUGGY pullback | 4,271 | 45.8% | 34.0% | 20.2% | $46.99 | $37.66 | 1.51 | $200,705 | $-6,468 |
| CAUSAL pullback | 5,248 | 37.4% | 45.6% | 16.9% | $-12.01 | $-87.88 | 0.90 | $-63,018 | $-72,524 |

- **Δ CAUSAL pullback vs CAUSAL matched baseline**: **$-8.48/trade** (this is the methodology-corrected pullback edge)
- Δ BUGGY pullback vs CAUSAL pullback (bug impact): **$59.00/trade** (amount of inflation the bug introduced)

## 2026 (OOS)

Confirmed regimes: 1,539. Pullback survivors: 1,453 (94.4%). Buggy version had 1,200 pullback rows.

| Population | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| CAUSAL confirmed-entry baseline (all) | 1,539 | 40.7% | 55.0% | 4.1% | $-27.44 | $-150.30 | 0.83 | $-42,232 | $-44,177 |
| CAUSAL matched baseline | 1,453 | 42.7% | 55.0% | 2.2% | $-17.07 | $-143.59 | 0.89 | $-24,807 | $-30,473 |
| BUGGY pullback | 1,200 | 46.0% | 34.8% | 19.2% | $56.98 | $57.50 | 1.55 | $68,371 | $-7,663 |
| CAUSAL pullback | 1,453 | 38.3% | 45.1% | 16.4% | $-14.66 | $-95.00 | 0.90 | $-21,295 | $-25,893 |
| NT runtime (actual fills) | 1,488 | 37.9% | 45.0% | 17.1% | $-17.01 | $-95.00 | 0.88 | $-25,310 | $-30,725 |

- **Δ CAUSAL pullback vs CAUSAL matched baseline**: **$2.42/trade** (this is the methodology-corrected pullback edge)
- Δ BUGGY pullback vs CAUSAL pullback (bug impact): **$71.63/trade** (amount of inflation the bug introduced)
- Δ NT actual vs CAUSAL pullback (real-world drag): **$-2.35/trade**

Trade pairing NT vs CAUSAL: 1,449 matched, 39 NT-only, 4 causal-only.
Outcome agreement on matched: 1,404 (96.9%).

Outcome cross-tab (rows = NT, cols = CAUSAL):

```
bracket_100_75_outcome   pt  regime   sl  timeout   All
exit_reason                                            
pt                      538       1   10        0   549
regime                    2     231   11        2   246
sl                       16       2  635        1   654
All                     556     234  656        3  1449
```

On 1,449 matched: NT mean $-17.54, CAUSAL mean $-14.65, Δ **$-2.89**.

## Cross-year summary

| Year | Tag | n CAUSAL | n NT | CAUSAL mean | CAUSAL matched mean | NT mean | **Δ CAUSAL vs matched** | Δ BUGGY vs CAUSAL | Δ NT vs CAUSAL | CAUSAL PF | NT PF |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2024 | OOS | 5,064 | 5,122 | $-10.53 | $-3.68 | $-11.31 | **$-6.85** | $39.70 | $-0.78 | 0.89 | 0.88 |
| 2025 | in-sample reference | 5,248 | 0 | $-12.01 | $-3.53 | — | **$-8.48** | $59.00 | — | 0.90 | nan |
| 2026 | OOS | 1,453 | 1,488 | $-14.66 | $-17.07 | $-17.01 | **$2.42** | $71.63 | $-2.35 | 0.90 | 0.88 |

## Outcome mix: CAUSAL vs NT

| Year | CAUSAL PT% | NT PT% | CAUSAL SL% | NT SL% | CAUSAL Reg% | NT Reg% |
|---|--:|--:|--:|--:|--:|--:|
| 2024 | 38.5% | 38.2% | 46.7% | 46.4% | 14.6% | 15.3% |
| 2025 | 37.4% | — | 45.6% | — | 16.9% | — |
| 2026 | 38.3% | 37.9% | 45.1% | 45.0% | 16.4% | 17.1% |

## Verdict

**CAUSAL pullback Δ vs matched baseline**:
- 2024 (OOS): $-6.85/trade (was $32.85 in BUGGY)
- 2025 (in-sample reference): $-8.48/trade (was $50.52 in BUGGY)
- 2026 (OOS): $2.42/trade (was $74.05 in BUGGY)

**Pullback edge MIXED** — 1/3 years positive after fix.

**NT vs CAUSAL drag**: average $-1.57/trade. Small drag = causal collector is a faithful proxy for NT runtime. Large drag = residual systematic difference (e.g., entry slip, different bracket race resolution).

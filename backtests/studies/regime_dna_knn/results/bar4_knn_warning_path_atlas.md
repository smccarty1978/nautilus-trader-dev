# KNN Warning Path Atlas (by horizon) + Blind-Exit Control

Warning states 6,477 vs age-matched healthy 6,477. Forward metrics by HORIZON h bars after the (warning / current) bar — reveals if the warning's remaining MFE is front-loaded or spread out. ACTUAL outcomes, causal.

## Part A — Warning vs healthy, by horizon (warn / healthy)
| h bars | P(new high) | MFE within h | MAE within h | giveback-from-peak | P(flip ≤h) |
| --- | --- | --- | --- | --- | --- |
| 1 | 14% / 47% | 0.47 / 0.56 | 0.48 / 0.50 | 1.48 / 1.07 | 17% / 5% |
| 2 | 27% / 59% | 0.69 / 0.80 | 0.64 / 0.70 | 1.65 / 1.27 | 28% / 11% |
| 3 | 34% / 65% | 0.85 / 0.99 | 0.72 / 0.85 | 1.74 / 1.41 | 36% / 17% |
| 5 | 43% / 71% | 1.07 / 1.27 | 0.84 / 1.02 | 1.85 / 1.59 | 48% / 29% |

**Path-shape read:** warning MFE within 3 bars = **0.85 ATR** (healthy 0.99); within 5 bars = 1.07 (healthy 1.27). Lifetime warning remaining-MFE ≈ 1.50. → the warning's remaining MFE is SPREAD OUT / near-horizon is quiet (immediate post-warning path is dead — exit/mode-switch well-timed).

## Part B — Blind-exit control (full exit, warning-count trades, matched bars)
| Strategy | avg/tr | 2025 | 2026 | maxDD | p5 trade |
| --- | --- | --- | --- | --- | --- |
| baseline (no exit) | $+0 | $+6 | $-16 | $189,308 | $-552 |
| WARNING full-exit | $+3 | $+7 | $-9 | $130,992 | $-472 |
| BLIND full-exit (5-seed avg) | $-7 | $-2 | $-21 | $289,898 | $-522 |

## Verdict

Warning full-exit: avg lift +2.6/tr, DD cut 31%. Blind: avg lift -7.1/tr, DD cut -53%.
> [!TIP]
> **The warning is SKILL, not just reduced exposure.** It beats a blind exit of the same trades/bars on avg AND 2026 — random exits cut DD too (less exposure), but only the warning IMPROVES expectancy while doing so. The deterioration signal genuinely selects bad-to-hold trades. Combined with Part A's path-shape, KNN survives again. Next: warning as a mode-switch gate (Part A tells which mode), and order-flow only as the exit/ignore arbiter.
# KNN Runner Cohort Exit Atlas (P(Run) top10 & P(Fail) bot20)

Cohort 2,632 trades, entered bar-5 open (causal after bar-4 signal). 1s PT triggers. PT = limit (no fav slip); no PT → flip; no SL. Costs $20/pt, $5 RT, 0.5t/1.0t slip. Cohort avg MFE = **2.08 ATR**.

## Remaining-MFE distribution from bar-5 entry (the meat left, not the mean)
| p10 | p25 | p50 | p75 | p90 | mean |
| --- | --- | --- | --- | --- | --- |
| 0.21 | 0.69 | 1.46 | 2.46 | 4.17 | 2.08 | (ATR)

## Exit comparison
| Exit | n | win% | avg $/tr | PF | 2025 | 2026 | captured MFE % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hold-to-flip | 2,632 | 35% | $+3 | 1.02 | $+16 | $-36 | 5% |
| PT @ 1.0 ATR | 2,632 | 66% | $-13 | 0.89 | $-10 | $-23 | -3% |
| PT @ 1.5 ATR | 2,632 | 55% | $-18 | 0.88 | $-16 | $-25 | -3% |
| PT @ 2.0 ATR | 2,632 | 47% | $-17 | 0.90 | $-13 | $-30 | -4% |
| PT @ 2.5 ATR | 2,632 | 42% | $-15 | 0.91 | $-11 | $-30 | -2% |
| PT @ 3.0 ATR | 2,632 | 39% | $-14 | 0.92 | $-8 | $-33 | -2% |
| scale 50% @ 1.0 + flip | 2,632 | 47% | $-7 | 0.95 | $+0 | $-32 | 15% |
| scale 50% @ 1.5 + flip | 2,632 | 49% | $-10 | 0.94 | $-3 | $-33 | 20% |
| scale 50% @ 2.0 + flip | 2,632 | 45% | $-9 | 0.95 | $-1 | $-36 | 22% |

## Verdict

> [!WARNING]
> **No exit makes the cohort net-positive in BOTH years.** Even harvesting the 2.53-ATR MFE with fixed PTs, 2026 stays negative — the runner IDENTIFICATION does not hold across regimes (2025 vs 2026), so it is not the exit, it is the signal failing out-of-period. The cohort's MFE is real but the WHICH-trades-run is a 2025 phenomenon. KNN cohort = dead on year-robustness. [[bar4_knn_calibrated_wrong_dimensions]]
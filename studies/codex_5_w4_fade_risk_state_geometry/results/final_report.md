# CODEX 5.X W4 Fade Risk-State Geometry Study

## Executive summary

**Decision: `NO_POLICY_IMPROVEMENT`**

The descriptive geometry showed real post-flip giveback, but the single causal protection rule frozen from 2025 geometry did not improve the 2025 development sample or the combined result. It improved the selection-isolated 2026 final policy test, but that favorable 2026 result cannot be used to rescue, select, or retune a rule that failed its development sample.

The tighter pre-flip-stop branch was closed before policy simulation. A 1.25 ATR stop—the least restrictive candidate—would have preserved only 93.1% of 2025 trades that reached the aligning flip, below the predeclared 95% preservation requirement. No tighter-stop policy was tested.

The only policy tested was frozen before the 2026 Stage 2 policy replay; no 2026 metric altered its selection:

- Continue the original trade after the aligning flip.
- Arm after entry-anchored post-flip MFE reaches +1.00 ATR.
- Activate protection on the next 1-second bar.
- Exit at a +0.25 ATR retained-profit floor if subsequently touched; otherwise retain the original stop and opposing-flip exit.
- On the arm-reaching bar, the original 1.50 ATR stop is evaluated first.

This is a **1-second OHLC research simulation**, not NT-native executable validation. It does not claim exact intrabar touch ordering.

## Study controls

- Repaired CODEX 5.X W4 scores and the existing 4,383-entry trade set were unchanged.
- W4 was not retrained and no entry signal was changed.
- Stage 1 was descriptive hindsight geometry only.
- Stage 2 contained one frozen policy; the pre-flip branch remained closed.
- Selection used 2025 only. The 2026 run was sealed until the 2025 replay reconciled with zero blocking errors.
- Baseline replay matched all 2,907 reached-flip exits and PnL values exactly; the original 1.50 ATR stop matched all 4,383 trades.
- Pre-execution audit: PASS, 0 CRITICAL / 0 WARNING.

## Stage 1: pre-flip MAE geometry

| Outcome group | N | Median | P75 | P90 | P95 | P99 | >=0.50 | >=0.75 | >=1.00 | >=1.25 | >=1.50 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Planned-exit winner | 1,360 | 0.345 | 0.731 | 1.095 | 1.261 | 1.456 | 38.5% | 24.5% | 13.2% | 5.3% | 0.0% |
| Planned-exit loser | 1,172 | 0.366 | 0.803 | 1.170 | 1.314 | 1.454 | 40.7% | 27.5% | 16.3% | 7.3% | 0.0% |
| Stop after aligned flip | 375 | 0.320 | 0.711 | 1.221 | 1.374 | 1.470 | 34.7% | 23.7% | 16.5% | 9.1% | 0.3% |
| Stop before aligned flip | 1,476 | 1.500 | 1.500 | 1.524 | 1.558 | 1.642 | 100.0% | 100.0% | 100.0% | 100.0% | 57.8% |

MAE values are ATR units. For reached-flip trades, the compact stability view was:

| Split | N | Median MAE | P95 MAE | Preserved by 1.25 ATR stop |
|---|---:|---:|---:|---:|
| 2025 | 2,139 | 0.340 | 1.317 | 93.1% |
| 2026 | 768 | 0.364 | 1.282 | 94.4% |
| Long fade | 1,239 | 0.340 | 1.314 | 93.5% |
| Short fade | 1,668 | 0.349 | 1.311 | 93.3% |
| ETH | 1,996 | 0.338 | 1.298 | 93.9% |
| RTH | 911 | 0.382 | 1.330 | 92.4% |

The 2025 preservation rates for the three descriptive candidates were 74.4% at 0.75 ATR, 85.0% at 1.00 ATR, and 93.1% at 1.25 ATR. None passed the frozen 95% gate.

## Stage 1: pre-stop MFE of current stop-before trades

Among 1,476 stop-before-flip trades, median pre-stop MFE was 0.317 ATR; P75/P90/P95 were 0.615/0.986/1.242 ATR. Before stopping, 56.6% reached +0.25 ATR, 33.7% reached +0.50 ATR, 18.2% reached +0.75 ATR, and 9.8% reached +1.00 ATR.

| Split | N | Median pre-stop MFE | Reached +0.50 | Reached +1.00 |
|---|---:|---:|---:|---:|
| 2025 | 1,107 | 0.331 | 34.3% | 10.4% |
| 2026 | 369 | 0.254 | 31.7% | 7.9% |
| Long fade | 632 | 0.322 | 33.9% | 9.5% |
| Short fade | 844 | 0.310 | 33.5% | 10.0% |
| ETH | 941 | 0.293 | 32.9% | 9.2% |
| RTH | 535 | 0.352 | 35.0% | 10.7% |

This is evidence that stop-before trades were not uniformly dead on arrival; a material minority first produced usable favorable excursion.

## Stage 1: post-flip giveback geometry

| Outcome group | N | Median PnL at flip | Median post-flip peak | Median seconds to peak | Median giveback | Median capture | Revisited entry | Revisited BE after peak | Revisited +0.25 after peak* | Revisited +0.50 after peak* | Revisited 25% of MFE | Revisited 50% of MFE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Planned-exit winner | 1,360 | 0.833 | 3.846 | 639 | 2.150 | 0.412 | 39.6% | 7.1% | 17.1% | 26.3% | 35.7% | 69.5% |
| Planned-exit loser | 1,172 | 0.581 | 1.378 | 75 | 1.951 | -0.408 | 99.6% | 99.4% | 100.0% | 100.0% | 100.0% | 100.0% |
| Stop after aligned flip | 375 | 0.325 | 0.827 | 24 | 2.352 | -1.640 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |

All PnL/excursion values are ATR units. `*` The +0.25 and +0.50 statistics are conditional on the respective level first being achieved.

The hindsight geometry clearly separated loser giveback from the runner population, so it passed the predeclared Stage 2 gate. It did not prove that a fixed causal floor would preserve enough right-tail winners; Stage 2 tested that question.

## Stage 2: frozen causal policy result

| Sample | Trades | Baseline net PnL | Policy net PnL | Change | Baseline PF | Policy PF |
|---|---:|---:|---:|---:|---:|---:|
| 2025 development/validation | 3,246 | -$17,608.99 | -$22,885.25 | **-$5,276.26** | 0.9668 | 0.9484 |
| 2026 selection-isolated final policy test | 1,137 | $7,595.77 | $10,416.80 | **+$2,821.03** | 1.0363 | 1.0629 |
| Combined, descriptive only | 4,383 | -$10,013.22 | -$12,468.45 | **-$2,455.23** | 0.9865 | 0.9795 |

The policy raised combined win rate from 31.0% to 52.1%, but lower average win/capture outweighed that improvement.

### Direction and session stability

| Split | Baseline net PnL | Policy net PnL | Change | PF change |
|---|---:|---:|---:|---:|
| Long fade | -$28,571.49 | -$41,754.27 | **-$13,182.78** | 0.9180 -> 0.8557 |
| Short fade | $18,558.27 | $29,285.82 | **+$10,727.55** | 1.0473 -> 1.0916 |
| ETH | -$17,725.71 | -$11,715.00 | **+$6,010.70** | 0.9527 -> 0.9613 |
| RTH | $7,712.49 | -$753.44 | **-$8,465.93** | 1.0211 -> 0.9975 |

The direction instability persisted in both years: long fades changed by -$6,852 in 2025 and -$6,330 in 2026, while short fades changed by +$1,576 and +$9,151. Session behavior was also unstable: ETH improved in 2025 but weakened in 2026; RTH did the reverse.

### Trade-level conversion and clipping

| Metric | 2025 | 2026 | Total |
|---|---:|---:|---:|
| Policy armed | 1,718 | 630 | 2,348 |
| Planned losers converted to winners | 571 | 221 | 792 |
| Stop-after-flip losses reduced | 110 | 45 | 155 |
| Planned winners clipped | 303 | 117 | 420 |
| Planned winners converted to losses | 15 | 2 | 17 |

Among planned winners, mean runner MFE lost was 1.017 ATR in 2025 and 0.892 ATR in 2026. For winners actually clipped, the mean lost runner MFE was 3.301 ATR in 2025 and 2.663 ATR in 2026. The fixed floor successfully monetized many loser paths but cut off enough large runners to make the 2025 and combined economics worse.

## Evidence versus speculation

**Evidence:** the tested 1.00/0.25 rule failed 2025, succeeded in 2026, failed combined, harmed long fades, and helped short fades. The tighter-stop candidates failed the predeclared preservation gate and were never simulated as policies.

**Speculation, not a tested policy:** direction-specific or state-adaptive protection might explain the asymmetry, but testing it now would be a new policy study and would risk using the observed 2026 pattern for selection. No such policy is recommended or claimed here.

## Conclusion

There is visible post-flip giveback geometry, but no robust management edge from the one permitted frozen rule. The proper decision is `NO_POLICY_IMPROVEMENT`. Do not promote this retained-profit floor or a tighter pre-flip stop into the established-regime fade policy on the basis of this study.

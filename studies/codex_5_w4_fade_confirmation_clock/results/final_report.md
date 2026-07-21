# CODEX 5.X W4 Fade Confirmation-Clock Study

## Executive summary

**Decision: `TIMEOUT_EXIT_PROMISING`**

The frozen Policy A package (1.25 ATR pre-flip stop plus a five-minute confirmation timeout) improved net PnL versus the repaired baseline in both years:

- 2025 development/validation: **+$9,494**, from -$17,609 to -$8,115; PF improved from 0.9668 to 0.9816.
- Selection-isolated 2026 final policy test: **+$10,392**, from $7,596 to $17,988; PF improved from 1.0363 to 1.1050.
- Combined descriptive view: **+$19,886**, with PF 1.0161 versus 0.9865.

Policy B's +0.75 ATR MFE-qualified continuation did not improve on A in 2025: it was $131 worse. It was $618 better than A in 2026, but that selection-isolated reversal cannot be used to select B. Policy C's 1.00 ATR stop improved 2025 but lost $1,394 versus baseline in 2026, so the aggressive-stop variant did not validate.

This result supports the exact Policy A package as promising research, not production readiness. Its 2025 PF remains below 1.0, 2025 ETH weakens, and the design does not separately identify the timeout effect from the simultaneous change from a 1.50 to 1.25 ATR pre-flip stop.

All results are **1-second OHLC research simulation**, not NT-native executable validation. Stop touches identify a containing one-second bar and do not claim tick-exact intrabar ordering.

## Frozen execution contract

- W4 was not retrained. The original trigger and all 4,383 repaired entries were fixed.
- A flip at exactly entry +300 seconds counts as confirmed.
- Timeout MFE uses only completed bars with `ts_event < entry + 300s`.
- Policy A/C timeout market decisions fill at the first raw one-second open strictly after the timeout. The active stop remains live until that fill.
- Policy B evaluates +0.75 ATR MFE only at the timeout; reaching +0.75 earlier is not a profit target.
- A qualified Policy B trade activates an entry +0.75 ATR stop at the timeout. If price is already through that level, the fill is the available open, so +0.75 ATR is not falsely guaranteed.
- Stops are loss-first versus favorable excursion within an ambiguous one-second OHLC bar.
- A/C revert to the original 1.50 ATR stop after alignment. B's timeout-qualified stop persists after a later aligning flip; it is a continuation of the pre-flip state, not a separately armed post-flip rule.
- Opposing-flip exits use the stored next available one-second open, including documented raw-bar gaps.
- Round-trip cost is $10; multiplier is $20 per NQ point; all stop/MFE levels use stored checkpoint ATR, consistent with the repaired baseline.

## Causal policy results

### Overall and yearly

| Policy | Sample | Trades | Mean net | Total net | PF | Win rate | Stop rate |
|---|---|---:|---:|---:|---:|---:|---:|
| Baseline 1.50 | Combined | 4,383 | -$2.28 | -$10,013 | 0.9865 | 31.03% | 42.23% |
| Policy A: 1.25 + timeout | Combined | 4,383 | $2.25 | $9,873 | 1.0161 | 31.51% | 37.83% |
| Policy B: A + MFE continuation | Combined | 4,383 | $2.36 | $10,361 | 1.0169 | 31.58% | 45.29% |
| Policy C: 1.00 + timeout | Combined | 4,383 | $0.10 | $436 | 1.0007 | 29.27% | 44.86% |
| Baseline 1.50 | 2025 | 3,246 | -$5.42 | -$17,609 | 0.9668 | 30.84% | 42.67% |
| Policy A | 2025 | 3,246 | -$2.50 | -$8,115 | 0.9816 | 31.27% | 38.45% |
| Policy B | 2025 | 3,246 | -$2.54 | -$8,245 | 0.9813 | 31.33% | 45.72% |
| Policy C | 2025 | 3,246 | -$1.78 | -$5,766 | 0.9861 | 29.14% | 45.38% |
| Baseline 1.50 | 2026 | 1,137 | $6.68 | $7,596 | 1.0363 | 31.57% | 40.99% |
| Policy A | 2026 | 1,137 | $15.82 | $17,988 | 1.1050 | 32.19% | 36.06% |
| Policy B | 2026 | 1,137 | $16.36 | $18,606 | 1.1086 | 32.28% | 44.06% |
| Policy C | 2026 | 1,137 | $5.45 | $6,202 | 1.0370 | 29.64% | 43.36% |

### Required event counts

| Policy/year | Timeout exits | Later signal flip | Baseline later reached flip | MFE-qualified continuations | Protected-stop exits | Planned winners clipped | Planned losers avoided | Stop-before losses reduced |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A / 2025 | 528 | 528 | 310 | 0 | 0 | 181 | 79 | 1,105 |
| A / 2026 | 187 | 187 | 118 | 0 | 0 | 60 | 29 | 369 |
| B / 2025 | 283 | 283 | 158 | 246 | 237 | 176 | 79 | 1,105 |
| B / 2026 | 94 | 94 | 56 | 93 | 91 | 61 | 28 | 369 |
| C / 2025 | 371 | 371 | 227 | 0 | 0 | 214 | 66 | 1,107 |
| C / 2026 | 132 | 132 | 88 | 0 | 0 | 79 | 24 | 369 |

"Later signal flip" means the stored aligning flip occurred after the timeout decision. "Baseline later reached flip" is the stricter subset whose original trade survived to that flip. "Planned loser avoided" means an original planned-exit loser became non-negative after costs. "Stop-before loss reduced" means PnL improved versus its original stop-before outcome.

### Direction and session

| Policy | Split | Baseline total | Policy total | Change | Baseline PF | Policy PF |
|---|---|---:|---:|---:|---:|---:|
| A | Long fade | -$28,571 | -$18,991 | +$9,581 | 0.9180 | 0.9352 |
| A | Short fade | $18,558 | $28,864 | +$10,306 | 1.0473 | 1.0903 |
| A | ETH | -$17,726 | -$14,056 | +$3,670 | 0.9527 | 0.9542 |
| A | RTH | $7,712 | $23,929 | +$16,217 | 1.0211 | 1.0782 |
| B | Long fade | -$28,571 | -$17,946 | +$10,625 | 0.9180 | 0.9387 |
| B | Short fade | $18,558 | $28,307 | +$9,749 | 1.0473 | 1.0886 |
| B | ETH | -$17,726 | -$15,414 | +$2,312 | 0.9527 | 0.9497 |
| B | RTH | $7,712 | $25,775 | +$18,062 | 1.0211 | 1.0843 |
| C | Long fade | -$28,571 | -$7,434 | +$21,137 | 0.9180 | 0.9727 |
| C | Short fade | $18,558 | $7,870 | -$10,688 | 1.0473 | 1.0252 |
| C | ETH | -$17,726 | -$20,463 | -$2,737 | 0.9527 | 0.9311 |
| C | RTH | $7,712 | $20,899 | +$13,187 | 1.0211 | 1.0729 |

Policy A improved both directions in aggregate. Its year-level weakness is 2025 ETH (-$1,349 change) and 2025 long-fade PF (0.9161 to 0.9087 despite a +$1,559 total-PnL change). In 2026, A improved both directions and both sessions. Policy C's apparent combined gain is unstable: 2026 short fades lost $11,796 versus baseline and 2026 ETH lost $2,394.

## Retrospective path diagnostics

The following section is hindsight description, not a policy simulation.

### Time to aligning flip for original planned winners

| Split | Winners | P25 | Median | P75 | P90 | Flipped within 5m |
|---|---:|---:|---:|---:|---:|---:|
| All | 1,360 | 50s | 112s | 254s | 445s | 80.3% |
| 2025 | 1,001 | 50s | 110s | 255s | 463s | 79.9% |
| 2026 | 359 | 55s | 115s | 244s | 420s | 81.3% |
| Long fade | 593 | 55s | 110s | 235s | 423s | 81.8% |
| Short fade | 767 | 50s | 115s | 270s | 464s | 79.1% |
| ETH | 894 | 50s | 110s | 249s | 450s | 80.6% |
| RTH | 466 | 55s | 115s | 259s | 435s | 79.6% |

The clock hypothesis has descriptive support: about four-fifths of planned winners aligned within five minutes. However, 268 planned winners aligned later, so a hard timeout necessarily clips a real runner subset.

### PnL and MFE at five minutes

Values below include only baseline trades still open at the five-minute decision instant. MFE uses completed bars strictly before the timeout.

| Original outcome | Total trades | Alive at 5m | Mean PnL | Median PnL | Mean MFE | Median MFE | No flip at 5m | Reached +0.75 | Qualification rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Planned winner | 1,360 | 1,360 | 1.319 | 1.201 | 1.991 | 1.751 | 268 | 135 | 50.4% |
| Planned loser | 1,172 | 962 | 0.374 | 0.314 | 1.261 | 1.152 | 215 | 79 | 36.7% |
| Stop after aligned flip | 375 | 208 | 0.151 | 0.000 | 1.129 | 1.014 | 44 | 12 | 27.3% |
| Stop before aligned flip | 1,476 | 412 | -0.387 | -0.447 | 0.656 | 0.597 | 412 | 145 | 35.2% |

Across all 939 no-flip-at-five-minute baseline survivors, 371 (39.5%) had reached +0.75 ATR. Their baseline outcomes were 135 planned winners, 79 planned losers, 12 stop-after-flip trades, and 145 stop-before-flip trades. Their baseline total PnL was approximately +$3,730, driven by the winner right tail: winners averaged +$515 while stop-before trades averaged -$364.

## Does Policy B rescue the qualified cohort?

Policy B actually allowed 339 trades to continue; the remaining descriptively qualified trades had already been removed by the tighter 1.25 ATR pre-flip stop. On those 339 continuations:

| Sample | Trades | Baseline total | Policy A total | Policy B total | B minus A |
|---|---:|---:|---:|---:|---:|
| 2025 | 246 | $6,213 | $16,050 | $15,919 | **-$131** |
| 2026 | 93 | $1,482 | $3,075 | $3,693 | **+$618** |
| Combined, descriptive | 339 | $7,695 | $19,125 | $19,613 | +$488 |

The combined gain over A is entirely dependent on 2026. On the 2025 development sample, continuing qualified trades with the protected stop did not beat simply exiting them. It also did not preserve true runners cleanly: 90 of the 128 baseline planned winners in the continued cohort were still clipped versus baseline, and their aggregate PnL fell by $47,424 versus baseline. B recovered $2,221 of that winner PnL relative to A, but gave back value in planned-loser and stop-before cohorts.

Therefore the evidence does **not** support `MFE_PROTECTED_TIMEOUT_PROMISING`. B is an informative near-tie, not the selected rule.

## Interpretation and limitations

**Evidence:** Policy A improves total PnL in both years, both directions in aggregate, and both 2026 sessions. Its 2025 result is better than Policy B, while Policy C fails the selection-isolated 2026 confirmation. The five-minute clock meaningfully separates many failures, but it also clips 241 planned winners across both years.

**Limitation:** A changes both the pre-flip stop and timeout. There is no 1.25 ATR stop-only arm, so the causal contribution of the clock cannot be isolated from the tighter stop. Much of the gross improvement comes from reducing stop-before losses, offset by clipped winner tails. Also, raw one-second gaps mean "next available open" can be later than one wall-clock second; those fills use the frozen stored/replayed raw series exactly.

**Not tested:** no other timeout, MFE threshold, protection level, stop grid, W4 retraining, entry change, or post-flip retained-profit policy was evaluated. Retuning from the observed 2026 differences would violate the study guardrails.

## Conclusion

The five-minute confirmation-clock package merits a narrowly scoped next validation step, so the decision is `TIMEOUT_EXIT_PROMISING`. The exact candidate is Policy A, not B or C. It should not be called production-ready or NT-validated; a later study would need to isolate 1.25-stop-only versus timeout-only effects without using 2026 for parameter selection.

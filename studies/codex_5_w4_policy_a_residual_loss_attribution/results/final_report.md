# CODEX 5.X W4 Policy A Residual-Loss Attribution

## Executive summary

**Decision: `LONG_FADE_DRAG_DOMINATES`**

Policy A's remaining combined loss is concentrated in long fades:

- Long fades: **-$18,991 combined**, -$19,436 in 2025 and only +$445 in 2026.
- Short fades: **+$28,864 combined**, positive in both years.
- ETH: -$14,056 combined, but it reverses from -$21,135 in 2025 to +$7,079 in 2026.
- RTH: +$23,929 combined.

The most stable specific interaction is long-fade ETH: **-$12,152 in 2025 and -$3,755 in 2026**. Long-fade RTH was also negative in 2025 but became positive in 2026. Short-fade ETH reversed from negative to strongly positive. This makes long direction the broader persistent weakness and ETH an important 2025 amplifier rather than a stand-alone stable drag.

The residual loss mechanism is still dominated by trades stopped before alignment. In 2025 they contributed $270,638 of gross losses, or 61.3% of all Policy A gross losses. Timeout exits were not the main net problem: all timeout exits produced +$2,970 in 2025 and -$3,135 in 2026, nearly flat combined.

This is descriptive attribution only. No filter or policy was tested. Results remain labeled as **1-second OHLC research simulation**, not NT-native executable validation.

## Policy A headline attribution

| Bucket | Trades | Total net | Mean | Win rate | PF | Avg winner | Avg loser | Bucket-only max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025 | 3,246 | -$8,115 | -$2.50 | 31.27% | 0.9816 | $426.86 | -$199.81 | $34,574 |
| 2026 | 1,137 | $17,988 | $15.82 | 32.19% | 1.1050 | $517.17 | -$225.69 | $13,030 |
| Long fade | 1,871 | -$18,991 | -$10.15 | 31.53% | 0.9352 | $464.58 | -$230.78 | $40,223 |
| Short fade | 2,512 | $28,864 | $11.49 | 31.49% | 1.0903 | $440.51 | -$188.21 | $20,717 |
| ETH | 2,937 | -$14,056 | -$4.79 | 31.12% | 0.9542 | $320.16 | -$153.26 | $27,965 |
| RTH | 1,446 | $23,929 | $16.55 | 32.30% | 1.0782 | $706.47 | -$316.43 | $29,143 |

Bucket drawdown is the peak-to-trough decline of bucket-only cumulative net PnL in original entry order. It is non-additive and not marked-to-market portfolio drawdown.

## Year, direction, and session interaction

| Bucket | Trades | Total net | Mean | Win rate | PF | Avg winner | Avg loser | Bucket-only max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025 long ETH | 918 | -$12,152 | -$13.24 | 32.46% | 0.8783 | $294.40 | -$162.41 | $17,509 |
| 2025 short ETH | 1,252 | -$8,983 | -$7.17 | 29.71% | 0.9235 | $291.30 | -$134.73 | $17,142 |
| 2025 long RTH | 472 | -$7,284 | -$15.43 | 30.72% | 0.9356 | $729.41 | -$350.00 | $19,363 |
| 2025 short RTH | 604 | $20,304 | $33.62 | 33.11% | 1.1828 | $657.00 | -$277.74 | $14,331 |
| 2026 long ETH | 314 | -$3,755 | -$11.96 | 28.66% | 0.9108 | $426.17 | -$188.83 | $9,831 |
| 2026 short ETH | 453 | $10,834 | $23.92 | 34.00% | 1.2289 | $377.76 | -$162.13 | $5,669 |
| 2026 long RTH | 167 | $4,200 | $25.15 | 34.13% | 1.1104 | $741.23 | -$349.08 | $9,290 |
| 2026 short RTH | 203 | $6,709 | $33.05 | 32.02% | 1.1532 | $777.00 | -$324.41 | $11,144 |

Only long-fade ETH is negative in both years. It is a clear descriptive concentration, but excluding it has not been backtested and is not a policy recommendation.

## Where Policy A losers exit

### Mutually exclusive residual loss modes

| Loss mode | Trades | Total net | Mean | Gross loss | Share of gross losses | Bucket-only max DD |
|---|---:|---:|---:|---:|---:|---:|
| Stopped before alignment | 1,336 | -$367,789 | -$275.29 | $367,789 | 60.0% | $367,789 |
| Timed out before alignment | 403 | -$40,580 | -$100.69 | $40,580 | 6.6% | $40,580 |
| Reached alignment, then stopped | 322 | -$84,543 | -$262.55 | $84,543 | 13.8% | $84,543 |
| Reached alignment, planned exit loss | 907 | -$119,760 | -$132.04 | $119,760 | 19.5% | $119,760 |
| Policy non-loss | 1,415 | $622,545 | $439.96 | $0 | 0.0% | $0 |

For 2025 alone, gross losses were:

- stopped before alignment: $270,638, 61.3%;
- planned opposing-flip losses after alignment: $83,070, 18.8%;
- stop-after-alignment losses: $59,092, 13.4%;
- losing timeout exits: $28,575, 6.5%.

Pre-alignment failures therefore dominate. Post-alignment losses remain material at 33.3% of combined gross losses, but they are not the leading residual bucket.

### Final Policy A exit reason

| Exit reason | Trades | Total net | Mean | Win rate | PF | Avg winner | Avg loser | Bucket-only max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Pre-flip policy stop | 1,336 | -$367,789 | -$275.29 | 0.00% | 0.0000 | - | -$275.29 | $367,789 |
| Confirmation timeout | 715 | -$165 | -$0.23 | 42.10% | 0.9959 | $134.27 | -$100.69 | $4,760 |
| Original stop after alignment | 322 | -$84,543 | -$262.55 | 0.00% | 0.0000 | - | -$262.55 | $84,543 |
| Original opposing-flip exit | 2,010 | $462,370 | $230.03 | 53.73% | 4.8608 | $539.01 | -$132.04 | $2,865 |

Timeout exits are close to breakeven combined. Their year split is unstable: +$2,970 with PF 1.1039 in 2025 versus -$3,135 with PF 0.7389 in 2026.

## Original baseline outcome attribution

| Original outcome | Trades | Policy A total | Mean | Win rate | PF | Avg winner | Avg loser | Bucket-only max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline stop-before | 1,476 | -$341,697 | -$231.50 | 5.56% | 0.0227 | $96.89 | -$251.72 | $341,757 |
| Baseline planned loser | 1,172 | -$136,651 | -$116.60 | 7.08% | 0.0550 | $95.84 | -$135.91 | $136,651 |
| Baseline stop-after | 375 | -$92,000 | -$245.33 | 2.67% | 0.0079 | $73.50 | -$254.07 | $92,000 |
| Baseline planned winner | 1,360 | $580,221 | $426.63 | 88.68% | 23.5866 | $502.41 | -$171.26 | $1,517 |

These are retrospective outcome groups, not entry-time filters.

## Time to aligning flip

| Align-time bucket | Trades | Total net | Mean | Win rate | PF | Avg winner | Avg loser | Bucket-only max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| No flip before exit | 2,050 | -$367,959 | -$179.49 | 14.63% | 0.0990 | $134.70 | -$234.83 | $368,134 |
| 0-60s | 1,082 | $111,146 | $102.72 | 39.19% | 1.9865 | $527.87 | -$174.41 | $7,596 |
| 60-120s | 569 | $116,776 | $205.23 | 52.20% | 3.8038 | $533.42 | -$155.99 | $2,779 |
| 120-300s | 681 | $149,905 | $220.12 | 52.72% | 3.9990 | $556.80 | -$158.18 | $3,100 |
| >300s before pending fill | 1 | $5 | $5.00 | 100.00% | - | $5.00 | - | $0 |

The no-flip bucket is the central path failure. The `>300s` bucket is deliberately tiny because a five-minute timeout decision remains binding; most later flips occur after the Policy A exit and are classified as no flip before exit.

## Entry-time regime age and W4 score

### Regime age at actual entry

| Bucket | Trades | Total net | Mean | Win rate | PF | Avg winner | Avg loser | Bucket-only max DD | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| <15m | 1,058 | $21,856 | $20.66 | 34.31% | 1.1435 | $479.90 | -$221.44 | $9,814 | $15,828 | $6,028 |
| 15-30m | 3,322 | -$12,213 | -$3.68 | 30.61% | 0.9735 | $440.32 | -$201.94 | $41,737 | -$23,638 | $11,425 |
| 30-60m | 3 | $231 | $76.88 | 33.33% | 1.7578 | $535.00 | -$152.18 | $304 | -$304 | $535 |

The main 15-30m bucket reverses sign by year, so regime age does not present a stable negative entry bucket.

### W4 score

| Bucket | Trades | Total net | Mean | Win rate | PF | Avg winner | Avg loser | Bucket-only max DD | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| <0.70 | 267 | -$1,684 | -$6.31 | 29.96% | 0.9493 | $394.13 | -$180.51 | $12,461 | $4,929 | -$6,613 |
| 0.70-0.75 | 2,286 | $33,166 | $14.51 | 32.59% | 1.1093 | $451.88 | -$199.27 | $16,622 | $11,468 | $21,699 |
| 0.75-0.80 | 1,645 | -$20,578 | -$12.51 | 30.46% | 0.9168 | $452.36 | -$218.00 | $26,923 | -$21,251 | $674 |
| >=0.80 | 185 | -$1,032 | -$5.58 | 29.73% | 0.9641 | $504.27 | -$226.51 | $8,770 | -$3,260 | $2,228 |

Every negative W4 band changes sign or becomes positive in the other year. There is no clear stable W4-score exclusion in this attribution.

## State at five-minute timeout

Timeout metrics use completed bars strictly before entry +300 seconds. Trades already exited are explicitly separated.

### MFE observed by timeout

| MFE bucket | Trades | Total net | Mean | Win rate | PF | Avg winner | Avg loser | Bucket-only max DD | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Not alive | 1,710 | -$446,720 | -$261.24 | 0.00% | 0.0000 | - | -$261.24 | $446,720 | -$321,845 | -$124,874 |
| <0.25 | 93 | -$8,318 | -$89.44 | 10.75% | 0.1140 | $107.00 | -$114.49 | $8,318 | -$5,148 | -$3,170 |
| 0.25-0.50 | 181 | -$14,101 | -$77.91 | 18.78% | 0.2380 | $129.56 | -$130.33 | $14,240 | -$11,810 | -$2,292 |
| 0.50-0.75 | 284 | -$9,476 | -$33.37 | 33.45% | 0.6360 | $174.26 | -$139.20 | $11,325 | -$6,975 | -$2,501 |
| 0.75-1.00 | 318 | $4,218 | $13.26 | 38.36% | 1.1367 | $287.46 | -$160.69 | $9,275 | $3,394 | $824 |
| >=1.00 | 1,797 | $484,270 | $269.49 | 62.33% | 6.9657 | $504.86 | -$123.93 | $2,077 | $334,269 | $150,000 |

Low MFE at five minutes is consistently negative, but it is a post-entry state, not a pre-entry do-not-trade bucket. Policy A already exits unconfirmed survivors at the timeout.

### PnL at timeout

| PnL bucket | Trades | Total net | Mean | Win rate | PF | Avg winner | Avg loser | Bucket-only max DD | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Not alive | 1,710 | -$446,720 | -$261.24 | 0.00% | 0.0000 | - | -$261.24 | $446,720 | -$321,845 | -$124,874 |
| <-1.00 | 39 | -$10,388 | -$266.35 | 2.56% | 0.0203 | $215.00 | -$279.02 | $10,388 | -$7,422 | -$2,966 |
| -1.00--0.50 | 230 | -$31,965 | -$138.98 | 8.70% | 0.1971 | $392.25 | -$189.57 | $31,965 | -$21,230 | -$10,735 |
| -0.50-0.00 | 420 | -$25,883 | -$61.63 | 10.95% | 0.3681 | $327.72 | -$111.00 | $27,440 | -$21,252 | -$4,631 |
| 0.00-0.50 | 568 | $43,389 | $76.39 | 49.30% | 2.2636 | $277.59 | -$124.86 | $3,462 | $35,954 | $7,435 |
| 0.50-1.00 | 439 | $63,955 | $145.68 | 58.31% | 4.0418 | $331.95 | -$118.79 | $2,895 | $47,558 | $16,397 |
| >=1.00 | 977 | $417,485 | $427.31 | 79.63% | 22.7216 | $561.32 | -$101.69 | $626 | $280,123 | $137,363 |

Negative PnL at timeout is negative in both years, but that relationship is contemporaneous and descriptive. It cannot be presented as a newly tested management rule.

## Late-aligning baseline winners clipped by timeout

There were 219 baseline planned winners that aligned after five minutes and exited under Policy A's timeout:

| Sample | Trades | Baseline total | Policy A total | Change |
|---|---:|---:|---:|---:|
| 2025 | 165 | $88,535 | $13,595 | -$74,940 |
| 2026 | 54 | $31,285 | $2,080 | -$29,205 |
| Combined | 219 | $119,820 | $15,675 | **-$104,145** |

This is the clearest right-tail cost. Across all 715 timeout exits, Policy A improved total PnL by $10,213 versus baseline but reduced positive-PnL capture by $79,405. The timeout sharply reduces drawdown exposure in this path cohort, but it pays for that protection by truncating late winners.

## Answers to the specific questions

1. **What explains the remaining 2025 loss?** Pre-alignment stops dominate gross losses at 61.3%. At the tradable-context level, 2025 ETH loses $21,135 and long fades lose $19,436, offset by profitable RTH and short fades.
2. **Long, ETH, or interaction?** Long fades are the broader residual weakness. ETH is the larger 2025 session drag, but ETH becomes profitable in 2026. Long-fade ETH is the only direction-session interaction negative in both years.
3. **How do Policy A losers fail?** Mostly by stopping before alignment. Planned losses after alignment are second, stop-after-alignment third, and losing timeout exits fourth.
4. **Obvious do-not-trade buckets?** No entry bucket is established as a filter. Long-fade ETH is descriptively negative in both years, but no exclusion was tested. W4-score and regime-age bands are unstable. Low MFE/negative PnL at timeout are stable path diagnostics, not entry filters.
5. **Drawdown versus right-tail capture?** Yes. The timeout cohort improves by $10,213 versus baseline and has only $4,760 bucket drawdown, but late baseline winners lose $104,145 of net capture under Policy A.
6. **Filterable or diffuse?** The direction/session residual is concentrated enough to motivate a future long-fade-ETH hypothesis, but feature-level evidence is diffuse and unstable. This study does not validate a filter.

## Conclusion

The supported decision is `LONG_FADE_DRAG_DOMINATES`. The remaining Policy A loss is concentrated in long fades, with long-fade ETH the only stable negative direction-session interaction. The loss-path anatomy is dominated by pre-alignment stops, not timeout exits or post-alignment giveback. No W4-score, regime-age, or other entry bucket is stable enough here to call an obvious do-not-trade rule.


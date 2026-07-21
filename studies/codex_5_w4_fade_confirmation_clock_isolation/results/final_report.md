# CODEX 5.X W4 Fade Confirmation-Clock Isolation

## Executive summary

**Decision: `COMBINATION_ADDITIVE`**

Both components contributed independently and survived the year split:

- The 1.25 ATR stop alone added **$3,734 in 2025** and **$8,967 in selection-isolated 2026**.
- The five-minute timeout alone added **$4,703 in 2025** and **$2,397 in 2026**.
- The combined Policy A added **$9,494 in 2025** and **$10,392 in 2026**.
- The interaction residual was +$1,057 in 2025, -$972 in 2026, and only **+$85 combined**. Under the frozen 5% tolerance, that residual is approximately zero.

The prior improvement therefore did not come from only one component. Stop-only was the larger combined contributor, timeout-only was slightly larger in 2025, and the package was better than either component in both years. The effects are approximately additive rather than synergistic or redundant.

This remains a **1-second OHLC research simulation**, not NT-native executable validation. It uses the exact repaired 4,383-entry set with no W4 retraining or entry changes.

## Component attribution

| Component | 2025 net change | 2026 net change | Combined net change | Interpretation |
|---|---:|---:|---:|---|
| 1.25 stop only | +$3,734 | +$8,967 | +$12,702 | Positive in both years; larger combined main effect |
| 5-minute timeout only | +$4,703 | +$2,397 | +$7,100 | Positive in both years; larger 2025 main effect |
| Combined 1.25 + timeout | +$9,494 | +$10,392 | +$19,886 | Better than either component in both years |
| Interaction effect | +$1,057 | -$972 | +$85 | Approximately zero; additive |

```text
interaction = combined change - stop-only change - timeout-only change
```

The interaction label was frozen before the final replay: absolute interaction no greater than 5% of the smaller absolute main-component change is considered approximately zero. The combined residual is 1.2% of the timeout-only contribution.

## Overall and yearly policy results

Maximum drawdown is peak-to-trough drawdown of cumulative net PnL in original entry-time trade sequence. It is not marked-to-market portfolio drawdown.

| Sample | Policy | Trades | Mean net | Total net | PF | Win rate | Stop rate | Timeout exits | Reached flip | Lost reached-flip trades | Avg winner | Avg loser | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Combined | Baseline | 4,383 | -$2.28 | -$10,013 | 0.9865 | 31.03% | 42.23% | 0 | 2,907 | 0 | $536.96 | -$247.09 | $45,699 |
| Combined | Stop-only S | 4,383 | $0.61 | $2,688 | 1.0039 | 29.39% | 45.81% | 0 | 2,717 | 190 | $540.53 | -$225.90 | $43,443 |
| Combined | Timeout-only T | 4,383 | -$0.66 | -$2,913 | 0.9954 | 32.42% | 31.90% | 936 | 2,380 | 527 | $444.58 | -$216.98 | $34,553 |
| Combined | Combined A | 4,383 | $2.25 | $9,873 | 1.0161 | 31.51% | 37.83% | 715 | 2,332 | 575 | $450.79 | -$206.43 | $34,574 |
| 2025 | Baseline | 3,246 | -$5.42 | -$17,609 | 0.9668 | 30.84% | 42.67% | 0 | 2,139 | 0 | $512.93 | -$238.35 | $45,699 |
| 2025 | Stop-only S | 3,246 | -$4.27 | -$13,875 | 0.9722 | 29.08% | 46.46% | 0 | 1,992 | 147 | $513.36 | -$218.06 | $43,443 |
| 2025 | Timeout-only T | 3,246 | -$3.98 | -$12,906 | 0.9716 | 32.29% | 32.22% | 699 | 1,751 | 388 | $421.71 | -$209.13 | $34,553 |
| 2025 | Combined A | 3,246 | -$2.50 | -$8,115 | 0.9816 | 31.27% | 38.45% | 528 | 1,713 | 426 | $426.86 | -$199.81 | $34,574 |
| 2026 | Baseline | 1,137 | $6.68 | $7,596 | 1.0363 | 31.57% | 40.99% | 0 | 768 | 0 | $603.96 | -$272.43 | $18,462 |
| 2026 | Stop-only S | 1,137 | $14.57 | $16,563 | 1.0849 | 30.26% | 43.98% | 0 | 725 | 43 | $615.09 | -$248.76 | $17,303 |
| 2026 | Timeout-only T | 1,137 | $8.79 | $9,993 | 1.0556 | 32.81% | 30.96% | 237 | 629 | 139 | $508.85 | -$239.74 | $14,667 |
| 2026 | Combined A | 1,137 | $15.82 | $17,988 | 1.1050 | 32.19% | 36.06% | 187 | 619 | 149 | $517.17 | -$225.69 | $13,030 |

All three policies improved 2025 and did not materially fail 2026. The combined package produced the highest total PnL in each year. Stop-only increased the stop rate and lowered win rate while improving loss size. Timeout-only reduced stop rate and drawdown but materially reduced average winner size.

## Outcome-change counts

| Policy | Stop-before losses reduced | Planned winners clipped | Planned losers avoided | Stop-after improved | Stop-after worsened | Stop-after net change |
|---|---:|---:|---:|---:|---:|---:|
| Stop-only S | 1,474 | 72 | 0 | 33 | 0 | +$1,849 |
| Timeout-only T | 409 | 227 | 90 | 44 | 0 | +$13,579 |
| Combined A | 1,474 | 241 | 84 | 53 | 0 | +$10,622 |

"Planned loser avoided" strictly requires an originally negative planned-exit trade to become non-negative after costs; unchanged breakevens are excluded.

## Direction and session

| Policy | Split | Baseline total | Policy total | Change | Baseline PF | Policy PF |
|---|---|---:|---:|---:|---:|---:|
| Stop-only S | Long fade | -$28,571 | -$23,592 | +$4,979 | 0.9180 | 0.9278 |
| Stop-only S | Short fade | $18,558 | $26,281 | +$7,723 | 1.0473 | 1.0716 |
| Stop-only S | ETH | -$17,726 | -$9,226 | +$8,500 | 0.9527 | 0.9737 |
| Stop-only S | RTH | $7,712 | $11,914 | +$4,202 | 1.0211 | 1.0348 |
| Timeout-only T | Long fade | -$28,571 | -$28,157 | +$414 | 0.9180 | 0.9081 |
| Timeout-only T | Short fade | $18,558 | $25,244 | +$6,685 | 1.0473 | 1.0769 |
| Timeout-only T | ETH | -$17,726 | -$18,368 | -$643 | 0.9527 | 0.9421 |
| Timeout-only T | RTH | $7,712 | $15,455 | +$7,742 | 1.0211 | 1.0487 |
| Combined A | Long fade | -$28,571 | -$18,991 | +$9,581 | 0.9180 | 0.9352 |
| Combined A | Short fade | $18,558 | $28,864 | +$10,306 | 1.0473 | 1.0903 |
| Combined A | ETH | -$17,726 | -$14,056 | +$3,670 | 0.9527 | 0.9542 |
| Combined A | RTH | $7,712 | $23,929 | +$16,217 | 1.0211 | 1.0782 |

Stop-only is the more stable standalone component across these aggregate splits. Timeout-only is concentrated in short fades and RTH; it weakens combined ETH and long-fade PF. The package offsets that weakness with the stop component.

Year-level split checks show remaining instability: stop-only was -$93 for 2025 long fades but +$5,072 in 2026; timeout-only was -$2,240 for 2025 long fades and -$258 for 2026 short fades. Combined A weakened 2025 ETH by $1,349 but improved both sessions in 2026. These do not overturn the paired year-level attribution, but they argue against calling the package universally stable.

## Trade-level diff classes

Class flags overlap by design; they do not sum to the trade count. Every trade-policy row and every flag is available in `isolation_trade_diffs.parquet`.

| Policy | Class | Count | Baseline total | Policy total | Net change | Avg change |
|---|---|---:|---:|---:|---:|---:|
| S | Unchanged | 2,719 | $466,381 | $466,381 | $0 | $0.00 |
| S | Stopped earlier/tighter by 1.25 | 1,664 | -$476,394 | -$463,693 | +$12,702 | +$7.63 |
| S | Reached flip under baseline but not policy | 190 | $9,947 | -$55,250 | -$65,197 | -$343.14 |
| S | Baseline stop-before loss reduced | 1,474 | -$486,341 | -$408,443 | +$77,898 | +$52.85 |
| S | Baseline planned winner clipped | 72 | $34,060 | -$21,943 | -$56,003 | -$777.81 |
| S | Baseline planned loser improved | 4 | -$1,180 | -$1,061 | +$119 | +$29.63 |
| S | Baseline stop-after improved | 33 | -$11,403 | -$9,554 | +$1,849 | +$56.03 |
| T | Unchanged | 3,447 | $28,932 | $28,932 | $0 | $0.00 |
| T | Exited by five-minute timeout | 936 | -$38,945 | -$31,845 | +$7,100 | +$7.59 |
| T | Reached flip under baseline but not policy | 527 | $99,156 | $6,445 | -$92,711 | -$175.92 |
| T | Baseline stop-before loss reduced | 409 | -$138,101 | -$38,290 | +$99,811 | +$244.04 |
| T | Baseline planned winner clipped | 227 | $136,790 | $1,175 | -$135,615 | -$597.42 |
| T | Baseline planned loser improved | 169 | -$23,150 | $3,950 | +$27,100 | +$160.36 |
| T | Baseline planned loser avoided | 90 | -$11,255 | $8,740 | +$19,995 | +$222.17 |
| T | Baseline stop-after improved | 44 | -$15,179 | -$1,600 | +$13,579 | +$308.61 |
| A | Unchanged | 2,334 | $377,437 | $377,437 | $0 | $0.00 |
| A | Stopped earlier/tighter by 1.25 | 1,334 | -$377,073 | -$367,399 | +$9,674 | +$7.25 |
| A | Exited by five-minute timeout | 715 | -$10,378 | -$165 | +$10,213 | +$14.28 |
| A | Reached flip under baseline but not policy | 575 | $98,890 | -$26,257 | -$125,148 | -$217.65 |
| A | Baseline stop-before loss reduced | 1,474 | -$486,341 | -$341,307 | +$145,034 | +$98.40 |
| A | Baseline planned winner clipped | 241 | $143,520 | -$11,779 | -$155,299 | -$644.39 |
| A | Baseline planned loser improved | 148 | -$19,880 | $4,256 | +$24,136 | +$163.08 |
| A | Baseline planned loser avoided | 84 | -$10,270 | $7,935 | +$18,205 | +$216.73 |
| A | Baseline stop-after improved | 53 | -$18,080 | -$7,458 | +$10,622 | +$200.41 |

No policy worsened a baseline stop-after trade. "Stopped earlier/tighter" is one-second OHLC language: for a gap through both stop levels, both may share the same containing timestamp and open fill; tick-exact ordering is not claimed.

## Interpretation

The stop component mainly improves the large stop-before cohort while sacrificing 190 reached-flip trades and 72 planned winners. The timeout component rescues fewer stop-before trades but at much larger average savings, while clipping 227 planned winners and lowering average winner size. Their strengths cover different parts of the path distribution, which explains why A exceeds either standalone policy.

The interaction itself is not stable by year and is economically negligible combined. Policy A is therefore an additive package, not evidence of a special stop-clock synergy.

## Conclusion

The supported label is `COMBINATION_ADDITIVE`. Both stop-only and timeout-only improve 2025 and remain positive versus baseline in selection-isolated 2026. The combined policy is best in both years, while the frozen interaction residual is approximately zero. The prior Policy A improvement came from both components, with the 1.25 stop contributing more combined and the timeout adding a separate, smaller edge.

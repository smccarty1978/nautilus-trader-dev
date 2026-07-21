# CODEX 5.X Original W4 Symmetric Bracket Race

## Decision

**`BRACKET_RACE_UNSTABLE_BY_YEAR`**

The primary conservative 1.25A/1.25A race wins **2,175 of 4,383 trades
(49.62%)**. That is below both 50% and the ATR-aware cost-adjusted breakeven
estimate of **51.67%**, producing **-$10.67 per trade** and PF **0.921**.

The year sign reverses: 2025 wins 49.32% and loses $14.80/trade, while the
selection-isolated 2026 sample wins 50.48% and earns only $1.14/trade. The
combined bracket is not an edge, and the small 2026 advantage is not stable.

This is a **1-second OHLC first-touch research simulation**, not NT-native or
tick-level executable validation. The primary rule classifies a same-bar PT/SL
touch as SL-first.

## Direct answer and requested win-rate breakdown

| Split | Trades | PT first | SL first | Win rate | Cost BE | Edge vs BE | $/trade | PF |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| Combined | 4,383 | 2,175 | 2,208 | **49.62%** | 51.67% | -2.05 pp | -$10.67 | .921 |
| 2025 | 3,246 | 1,601 | 1,645 | **49.32%** | 52.28% | -2.95 pp | -$14.80 | .889 |
| 2026 | 1,137 | 574 | 563 | **50.48%** | 50.29% | +0.20 pp | $1.14 | 1.008 |
| Long fade | 1,871 | 917 | 954 | **49.01%** | 52.07% | -3.06 pp | -$17.36 | .885 |
| Short fade | 2,512 | 1,258 | 1,254 | **50.08%** | 51.25% | -1.17 pp | -$5.68 | .954 |
| ETH | 2,937 | 1,477 | 1,460 | **50.29%** | 52.49% | -2.20 pp | -$8.56 | .916 |
| RTH | 1,446 | 698 | 748 | **48.27%** | 50.16% | -1.89 pp | -$14.94 | .927 |
| Long ETH | 1,232 | 622 | 610 | **50.49%** | 53.14% | -2.65 pp | -$11.18 | .899 |
| Long RTH | 639 | 295 | 344 | **46.17%** | 49.60% | -3.43 pp | -$29.28 | .871 |
| Short ETH | 1,705 | 855 | 850 | **50.15%** | 51.97% | -1.82 pp | -$6.67 | .930 |
| Short RTH | 807 | 403 | 404 | **49.94%** | 50.42% | -0.48 pp | -$3.59 | .981 |

Key interpretation:

- Shorts outperform longs by 1.07 percentage points, but still fail their
  cost-adjusted breakeven rate.
- ETH exceeds 50% by 0.29 percentage point, but its smaller ATR-adjusted payouts
  require a 52.49% estimated hit rate after costs.
- RTH is below 50%, driven primarily by long RTH at 46.17%.
- No direction/session intersection has positive expectancy.

## Full primary race metrics

All 4,383 races resolve; there are no unresolved trades. The single same-bar tie
is 0.023% of the population and occurs in short RTH/2025. The decisive-overshoot
sensitivity also classifies it SL-first, so the headline is unchanged.

| Split | Avg winner | Avg loser | Median sec | P25/P75 sec | Median favorable before loss | Median adverse before win |
|:--|--:|--:|--:|--:|--:|--:|
| Combined | $251.97 | -$269.38 | 166 | 85.5 / 322 | .412A | .396A |
| 2025 | $239.24 | -$262.05 | 162 | 84 / 318 | .417A | .387A |
| 2026 | $287.49 | -$290.80 | 177 | 89 / 332 | .401A | .440A |
| Long fade | $272.31 | -$295.79 | 159 | 86 / 304.5 | .420A | .379A |
| Short fade | $237.15 | -$249.29 | 173 | 85 / 335.25 | .405A | .410A |
| ETH | $184.88 | -$204.26 | 170 | 87 / 331 | .401A | .395A |
| RTH | $393.94 | -$396.49 | 157 | 81.25 / 297.75 | .432A | .398A |
| Long ETH | $197.55 | -$224.01 | 165 | 89 / 318.25 | .411A | .399A |
| Long RTH | $429.92 | -$423.07 | 149 | 80 / 280.5 | .441A | .333A |
| Short ETH | $175.67 | -$190.09 | 177 | 85 / 343 | .398A | .390A |
| Short RTH | $367.59 | -$373.86 | 166 | 85 / 323.5 | .426A | .456A |

The cost-adjusted breakeven calculation uses conditional average gross bracket
values for winners and losers: `(average loss magnitude + $10) / (average win
magnitude + average loss magnitude)`. This handles the observed ATR difference
between winning and losing cohorts. It explains why 2026 is marginally positive
at 50.48%, while long ETH loses money despite a 50.49% hit rate.

## Fixed bracket sensitivity

No bracket was selected; the table is descriptive.

| PT / SL | Split | PT-first rate | $/trade | PF |
|:--|:--|--:|--:|--:|
| 1.00 / 1.00 | Combined | 49.69% | -$9.79 | .910 |
| 1.00 / 1.00 | 2025 | 49.54% | -$12.09 | .886 |
| 1.00 / 1.00 | 2026 | 50.13% | -$3.21 | .973 |
| 1.25 / 1.25 | Combined | 49.62% | -$10.67 | .921 |
| 1.25 / 1.25 | 2025 | 49.32% | -$14.80 | .889 |
| 1.25 / 1.25 | 2026 | 50.48% | $1.14 | 1.008 |
| 1.50 / 1.50 | Combined | 49.44% | -$13.48 | .917 |
| 1.50 / 1.50 | 2025 | 49.20% | -$17.04 | .893 |
| 1.50 / 1.50 | 2026 | 50.13% | -$3.32 | .981 |

All three fixed brackets are negative combined and negative in 2025. Only the
primary 1.25A bracket is marginally positive in 2026. This is instability, not a
robust bracket edge.

## Policy A alignment comparison

| Diagnostic | Count | Rate |
|:--|--:|--:|
| Policy A reached alignment before stop/timeout | 2,332 / 4,383 | 53.20% |
| Symmetric 1.25A PT before 1.25A SL | 2,175 / 4,383 | 49.62% |
| Difference | -157 trades | -3.58 pp |

**The known 53.2% alignment-before-stop behavior does not convert into a >50%
symmetric PT-before-SL race.** Alignment is a regime-state event, not evidence
that price has already traveled +1.25 ATR in the countertrade direction.

## Runner-tail diagnostic

Of the 2,175 PT-first trades, 2,101 resolve before the frozen original
opposing-regime-flip horizon and therefore have an observable post-resolution
tail. The remaining 74 PT wins resolve after that horizon and are not assigned
post-resolution labels.

Among the 2,101 observable PT-first tails:

- 1,491 (**70.97%**) reach +2A total MFE.
- 968 (**46.07%**) reach +3A.
- 640 (**30.46%**) reach +4A.
- Median additional MFE after the PT bar is **+1.58A**.
- Holding to the original opposing-flip horizon produces mean **+$270.46**, but
  median only **+$70**; 61.45% finish positive.
- Median giveback from maximum MFE to the horizon exit is **2.28A**.
- 772 of 2,100 unambiguous paths (**36.76%**) return to entry before reaching
  +2A. One path touches both levels in the same bar and remains ambiguous.

For SL-first trades resolving before the tail horizon, 727 of 1,954 (**37.21%**)
later recover to the original +1.25A PT. This is retrospective and does not
change the primary SL-first classification.

The PT-first cohort does contain a meaningful runner tail, but with substantial
giveback and right-skew. That supports one narrow follow-up diagnostic; it does
not rescue the symmetric all-in/all-out bracket.

## Answers to the required questions

1. **PT-first percentage:** 49.62% under the conservative primary rule.
2. **Above 50%?** No, combined. Shorts and ETH are barely above 50%, but longs,
   RTH, and the total population are below.
3. **Above cost-adjusted breakeven?** No combined and no direction/session
   split. Only 2026 overall is marginally above its conditional breakeven rate.
4. **Stable across years?** No. 2025 is clearly negative; 2026 is marginally
   positive.
5. **Long/short and ETH/RTH difference:** shorts beat longs; ETH beats RTH. The
   largest drag is long RTH.
6. **Does 53.2% alignment translate?** No. The bracket rate is 3.58 percentage
   points lower.
7. **Runner tail?** Yes diagnostically: 71% of observable PT-first trades later
   reach 2A, but median giveback is 2.28A.
8. **Cleanest next test:** predeclare a two-unit diagnostic that exits one unit
   at +1.25A and holds one unit to the already-frozen original opposing-flip
   horizon, with no new trailing, breakeven, or score rules. Compare it directly
   with full PT and full hold in 2025, leaving 2026 selection-isolated.

## Guardrail confirmation

No W4 retraining, threshold change, specialized model, delayed entry, re-entry,
portfolio lifecycle rule, timeout, or regime exit entered the primary race. No
2026 result selected a bracket or subgroup. Tail labels unavailable before the
frozen horizon remain missing rather than being forced false, and ambiguous
entry-versus-2A bars remain explicitly unresolved.

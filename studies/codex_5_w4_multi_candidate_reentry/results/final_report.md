# CODEX 5.X W4 Multi-Candidate Entry Study

## Decision

**`REENTRY_RECOVERS_FIRST_CROSSING_DAMAGE`**

Allowing later candidates materially repairs the artificial "reject once, skip forever" damage in the prior PR10 replay. R10 improves combined net PnL versus Policy A/R0 by **$4,527** and improves the prior skip-forever PR10 result by **$25,319**. It is not ready for promotion: the improvement versus R0 is **+$15,793 in 2025** but **-$11,265 in the selection-isolated 2026 test**. R30 fails globally.

This is a **1-second OHLC research simulation**, not NT-native executable validation. Entry and exit paths use the frozen explicit 1-second replay contract; no exact intrabar touch ordering is claimed.

## Executive findings

- The frozen Policy A baseline reconciles exactly: 4,383 old trades, 4,383 regenerated R0 trades, 4,383 matched entries, zero unmatched entries, zero timestamp mismatches, and $0 PnL difference.
- The collector generated **11,812 strict crossing candidates in 4,767 eligible opportunities**: 4,767 sequence-1 crossings and 7,045 later recrosses. The opportunity split is 3,530 in 2025 and 1,237 in 2026.
- R10 executes 2,703 trades and earns **$14,401**, versus R0's 4,383 trades and **$9,873**. Profit factor rises from 1.016 to 1.037; executed-trade win rate is essentially unchanged at 31.59% versus 31.51%.
- R10 recovers 1,044 opportunities with later accepted candidates. Those later trades earn **$13,803 combined**, but split sharply: **+$21,046 in 2025** and **-$7,242 in 2026**.
- R30 executes 1,782 trades and loses **$8,529**. Its later candidates lose $8,864 combined.
- R10's combined improvement is attributable to: **+$21,623** from no-trade opportunities that were losing under R0, **+$35,393** from later-candidate opportunities, and **-$52,488** from delayed first-candidate opportunities. The net is +$4,527.
- Delayed fills are not the source of the edge. Among R10 acceptances, 2,204 fills worsened, 450 improved, and 160 were unchanged relative to the immediate candidate fill.
- Long ETH improves from **-$15,907 under R0 to +$3,651 under R10**, and is positive in both years. This is descriptive only; no direction/session rule was selected.

## Causal contract and leakage controls

- W4 was not retrained; direction-specific thresholds and score stream were frozen.
- Candidate generation is a strict below-to-above recross state machine. A score remaining above threshold cannot emit duplicates.
- R10/R30 decisions use only the candidate's would-be fill and the causal +10s/+30s observation. Accepted entries fill at the first available 1-second open strictly after confirmation.
- A rejected candidate does not terminate the opportunity. Scanning continues until acceptance or a causally observable opportunity-ending condition.
- Policy A management is anchored to the actual delayed fill: 1.25 ATR pre-flip stop, five-minute timeout, then the original post-alignment 1.50 ATR stop and opposing-flip exit.
- 2025 is development/validation; 2026 is selection-isolated final test. No 2026-driven parameter selection was performed.
- The pre-execution lookahead audit passed with zero CRITICAL and zero WARNING findings before the authorized full replay. A separate completion audit is recorded in the run manifest.

## Main performance table

Rates are fractions. `WR/Trade` uses executed trades; `WR/Opp` includes no-trade opportunities as zero-PnL non-winners. `$/Opp` likewise includes no-trade opportunities at zero. `MaxDD` is closed-trade-sequence drawdown.

| P | Split | Opp | Trades | NoTrade | Net$ | $/Opp | $/Trade | PF | WR/Trade | WR/Opp | Stop | Timeout | AvgWin | AvgLoss | MaxDD |
|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| R0 | ALL | 4767 | 4383 | 384 | 9873.22 | 2.07 | 2.25 | 1.02 | 0.32 | 0.29 | 0.38 | 0.16 | 450.79 | -206.43 | 34574.02 |
| R0 | 2025 | 3530 | 3246 | 284 | -8114.84 | -2.30 | -2.50 | 0.98 | 0.31 | 0.29 | 0.38 | 0.16 | 426.86 | -199.81 | 34574.02 |
| R0 | 2026 | 1237 | 1137 | 100 | 17988.06 | 14.54 | 15.82 | 1.11 | 0.32 | 0.30 | 0.36 | 0.16 | 517.17 | -225.69 | 13030.08 |
| R0 | long_fade | 2075 | 1871 | 204 | -18990.81 | -9.15 | -10.15 | 0.94 | 0.32 | 0.28 | 0.40 | 0.14 | 464.58 | -230.78 | 40223.20 |
| R0 | short_fade | 2692 | 2512 | 180 | 28864.03 | 10.72 | 11.49 | 1.09 | 0.31 | 0.29 | 0.36 | 0.18 | 440.51 | -188.21 | 20716.98 |
| R0 | ETH | 3173 | 2937 | 236 | -14055.99 | -4.43 | -4.79 | 0.95 | 0.31 | 0.29 | 0.37 | 0.16 | 320.16 | -153.26 | 27965.04 |
| R0 | RTH | 1594 | 1446 | 148 | 23929.21 | 15.01 | 16.55 | 1.08 | 0.32 | 0.29 | 0.39 | 0.16 | 706.47 | -316.43 | 29142.97 |
| R0 | long_ETH | 1353 | 1232 | 121 | -15906.92 | -11.76 | -12.91 | 0.89 | 0.31 | 0.29 | 0.38 | 0.15 | 324.96 | -169.44 | 25926.63 |
| R0 | short_ETH | 1820 | 1705 | 115 | 1850.93 | 1.02 | 1.09 | 1.01 | 0.31 | 0.29 | 0.37 | 0.18 | 316.62 | -141.61 | 18507.20 |
| R0 | long_RTH | 722 | 639 | 83 | -3083.89 | -4.27 | -4.83 | 0.98 | 0.32 | 0.28 | 0.43 | 0.14 | 732.75 | -349.77 | 19362.84 |
| R0 | short_RTH | 872 | 807 | 65 | 27013.10 | 30.98 | 33.47 | 1.17 | 0.33 | 0.30 | 0.36 | 0.18 | 686.43 | -289.52 | 14331.16 |
| R10 | ALL | 4767 | 2703 | 2064 | 14400.67 | 3.02 | 5.33 | 1.04 | 0.32 | 0.18 | 0.36 | 0.15 | 476.99 | -215.20 | 29285.48 |
| R10 | 2025 | 3530 | 1997 | 1533 | 7677.96 | 2.18 | 3.84 | 1.03 | 0.32 | 0.18 | 0.36 | 0.15 | 456.82 | -207.83 | 29285.48 |
| R10 | 2026 | 1237 | 706 | 531 | 6722.72 | 5.43 | 9.52 | 1.06 | 0.32 | 0.18 | 0.35 | 0.17 | 534.06 | -236.08 | 12441.63 |
| R10 | long_fade | 2075 | 1153 | 922 | 3229.63 | 1.56 | 2.80 | 1.02 | 0.34 | 0.19 | 0.36 | 0.15 | 489.79 | -247.10 | 27930.18 |
| R10 | short_fade | 2692 | 1550 | 1142 | 11171.04 | 4.15 | 7.21 | 1.05 | 0.30 | 0.17 | 0.36 | 0.16 | 466.33 | -192.65 | 23691.35 |
| R10 | ETH | 3173 | 1786 | 1387 | -1860.97 | -0.59 | -1.04 | 0.99 | 0.31 | 0.18 | 0.35 | 0.16 | 335.73 | -158.13 | 15645.51 |
| R10 | RTH | 1594 | 917 | 677 | 16261.64 | 10.20 | 17.73 | 1.08 | 0.32 | 0.18 | 0.38 | 0.15 | 748.87 | -325.94 | 24440.21 |
| R10 | long_ETH | 1353 | 747 | 606 | 3651.24 | 2.70 | 4.89 | 1.04 | 0.35 | 0.19 | 0.35 | 0.16 | 353.46 | -183.11 | 11923.53 |
| R10 | short_ETH | 1820 | 1039 | 781 | -5512.20 | -3.03 | -5.31 | 0.95 | 0.29 | 0.17 | 0.36 | 0.16 | 320.58 | -141.58 | 11161.03 |
| R10 | long_RTH | 722 | 406 | 316 | -421.61 | -0.58 | -1.04 | 1.00 | 0.32 | 0.18 | 0.40 | 0.14 | 763.53 | -358.39 | 18944.08 |
| R10 | short_RTH | 872 | 511 | 361 | 16683.25 | 19.13 | 32.65 | 1.16 | 0.32 | 0.19 | 0.36 | 0.16 | 737.27 | -299.98 | 14993.18 |
| R30 | ALL | 4767 | 1782 | 2985 | -8529.44 | -1.79 | -4.79 | 0.97 | 0.31 | 0.12 | 0.35 | 0.15 | 471.12 | -218.64 | 40879.63 |
| R30 | 2025 | 3530 | 1299 | 2231 | -14949.93 | -4.24 | -11.51 | 0.92 | 0.31 | 0.12 | 0.35 | 0.15 | 424.46 | -213.78 | 40879.63 |
| R30 | 2026 | 1237 | 483 | 754 | 6420.49 | 5.19 | 13.29 | 1.08 | 0.29 | 0.11 | 0.34 | 0.16 | 606.13 | -231.12 | 10180.08 |
| R30 | long_fade | 2075 | 764 | 1311 | -12968.42 | -6.25 | -16.97 | 0.90 | 0.33 | 0.12 | 0.34 | 0.15 | 460.30 | -255.78 | 26223.16 |
| R30 | short_fade | 2692 | 1018 | 1674 | 4438.98 | 1.65 | 4.36 | 1.03 | 0.29 | 0.11 | 0.35 | 0.16 | 480.37 | -192.39 | 18899.43 |
| R30 | ETH | 3173 | 1198 | 1975 | 1925.89 | 0.61 | 1.61 | 1.01 | 0.31 | 0.12 | 0.34 | 0.16 | 359.26 | -163.78 | 18371.54 |
| R30 | RTH | 1594 | 584 | 1010 | -10455.33 | -6.56 | -17.90 | 0.92 | 0.30 | 0.11 | 0.36 | 0.14 | 714.25 | -327.68 | 25548.28 |
| R30 | long_ETH | 1353 | 500 | 853 | 5650.31 | 4.18 | 11.30 | 1.09 | 0.36 | 0.13 | 0.33 | 0.16 | 364.11 | -187.78 | 8911.49 |
| R30 | short_ETH | 1820 | 698 | 1122 | -3724.42 | -2.05 | -5.34 | 0.95 | 0.28 | 0.11 | 0.34 | 0.16 | 354.85 | -148.45 | 16670.66 |
| R30 | long_RTH | 722 | 264 | 458 | -18618.74 | -25.79 | -70.53 | 0.73 | 0.28 | 0.10 | 0.37 | 0.13 | 692.97 | -369.83 | 23257.97 |
| R30 | short_RTH | 872 | 320 | 552 | 8163.41 | 9.36 | 25.51 | 1.13 | 0.31 | 0.11 | 0.36 | 0.14 | 730.15 | -291.46 | 8966.06 |

## Candidate accounting

| Gate | Generated | Evaluated | Accepted | Rejected | Adverse | Regime ended | Align before fill | Score unavailable | Opportunity ended | Seq 1 | Seq 2 | Seq 3 | Seq 4+ |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| R0 | 11,812 | 4,767 | 4,760 | 7 | 0 | 0 | 7 | 0 | 0 | 4,760 | 0 | 0 | 0 |
| R10 | 11,812 | 7,353 | 2,814 | 4,539 | 3,377 | 257 | 16 | 44 | 845 | 1,730 | 659 | 275 | 150 |
| R30 | 11,812 | 7,114 | 1,836 | 5,278 | 3,059 | 763 | 10 | 103 | 1,343 | 1,116 | 344 | 204 | 172 |

R0 has 4,760 candidate acceptances but only the 4,383 frozen Policy A executable entries are replayed as baseline trades. The remaining accepted observations are retained for transparent collector accounting and cannot silently expand the frozen baseline population.

Fill movement uses directional points, where positive means a worse accepted fill. R10: 450 improved (mean -0.976 points), 2,204 worsened (mean +2.548), and 160 unchanged. R30: 212 improved (mean -0.835), 1,524 worsened (mean +3.575), and 100 unchanged.

## Opportunity-level attribution

| Class | R10 count | R10 change vs R0 | R30 count | R30 change vs R0 |
|:--|--:|--:|--:|--:|
| No trade | 2,064 | +$21,622.73 | 2,985 | +$4,983.05 |
| Trade on first candidate | 1,659 | -$52,488.21 | 1,086 | -$67,172.36 |
| Trade on later candidate | 1,044 | +$35,392.93 | 696 | +$43,786.65 |
| Opportunity improved | 1,932 | +$367,066.99 | 2,328 | +$488,748.64 |
| Opportunity worsened | 2,103 | -$362,539.54 | 1,912 | -$507,151.30 |
| First-entry loser replaced by later winner | 96 | +$54,379.77 | 84 | +$57,995.85 |
| First-entry winner missed | 593 | -$251,312.36 | 868 | -$396,483.04 |
| Stop-before loss avoided | 854 | +$215,171.91 | 1,070 | +$288,659.55 |
| Planned winner lost | 517 | -$238,159.41 | 752 | -$382,449.69 |
| Planned winner clipped | 441 | -$24,960.00 | 279 | -$19,595.00 |
| Later winner created | 341 | policy PnL +$170,555.00 | 208 | policy PnL +$99,290.00 |
| Later loser created | 694 | policy PnL -$156,751.58 | 480 | policy PnL -$108,153.88 |

The later-candidate class is profitable under R10, but not stable: 741 later R10 trades earn +$21,045.64 in 2025; 303 lose $7,242.22 in 2026. R30 later entries lose $5,670.42 in 2025 and $3,193.45 in 2026.

## Comparison with the prior skip-forever PR replay

| Gate | Prior approved | New accepted opps | New trades | Prior skipped forever | Later recoveries | Prior net | New net | Net recovery | Prior WR | New WR | Short PnL recovery | Long-ETH retention change |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| R10 | 2,105 | 2,814 | 2,703 | 2,278 | 1,044 | -$10,918.30 | $14,400.67 | +$25,318.98 | 30.12% | 31.59% | +$23,878.58 | +$7,637.05 |
| R30 | 1,811 | 1,836 | 1,782 | 2,572 | 696 | $4,299.20 | -$8,529.44 | -$12,828.64 | 31.25% | 30.81% | +$1,531.86 | +$1,283.49 |

R10 changes the prior short-fade result from -$12,707.53 to +$11,171.04, although it remains below R0's +$28,864.03. The earlier negative PR10 global result was therefore materially caused by the skip-forever assumption. R30's failure is not repaired by recandidate collection.

## Answers to the study questions

1. **Win rate:** R10 improves executed-trade win rate only marginally, from 31.51% to 31.59% (+0.09 percentage point). R30 lowers it to 30.81%. Opportunity win rate falls because the gates deliberately create many no-trade opportunities.
2. **PnL versus quality:** R10 improves both combined total PnL (+$4,527 versus R0) and executed-trade EV ($5.33 versus $2.25), but the gain is not temporally stable. R30 improves neither.
3. **Replacement frequency:** R10 takes a later candidate in 1,044 opportunities: 21.9% of all opportunities and 38.6% of R10 trades. R30 does so in 696 opportunities: 14.6% and 39.1%, respectively.
4. **Later-candidate profitability:** R10 later candidates earn +$13,803 combined; R30 later candidates lose $8,864. R10's sign reverses from positive in 2025 to negative in 2026.
5. **Opportunity-cost recovery:** Later R10 trades improve their opportunities by $35,393 versus R0, but do not fully recover the $251,312 opportunity change attached to missed first-entry winners. Loss avoidance and exposure reduction are also necessary for the small net improvement.
6. **Short-fade preservation:** R10 preserves short-fade upside much better than prior PR10: +$11,171 versus -$12,708, a $23,879 recovery. It still trails R0. R30 provides only a $1,532 recovery versus prior PR30.
7. **Long ETH:** Yes descriptively. R10 long ETH is +$3,651 combined and positive in both years (+$2,379 in 2025; +$1,272 in 2026), compared with R0's -$15,907 combined. This was not used to select a new policy.
8. **Source of benefit:** The evidence supports a mixture of skipping bad first entries and replacing some with later entries. Better fills are contradicted by the fill distribution. Pure exposure reduction contributes +$21,623; later-candidate substitution contributes +$35,393; delayed first-candidate execution costs $52,488.
9. **Stability:** No. R10's change versus R0 is +$15,793 in 2025 and -$11,265 in 2026. R30 underperforms R0 in both years. This blocks promotion despite the combined R10 result.

## Evidence boundary and next decision

The causal evidence is sufficient to reject the skip-forever replay as a faithful representation of the intended strategy. It is not sufficient to approve R10 as a new leading policy. The main reusable result is the audited multi-candidate collector and the finding that recross recovery is real but unstable. Any follow-up should predeclare one narrow hypothesis from 2025 and leave 2026 untouched; no such follow-up policy is tested here.

The Parquet files are the authoritative machine-readable records for every candidate, opportunity, trade diff, split metric, and reconciliation row.

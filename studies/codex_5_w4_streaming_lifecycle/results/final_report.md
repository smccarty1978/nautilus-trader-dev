# CODEX 5.X W4 Streaming Lifecycle Study

## Decision

**`REENTRY_ADDS_CHURN`**

None of the fixed streaming policies improves the audited Policy A baseline.
Immediate streaming re-entry (S1) changes combined net PnL from **+$9,873** to
**-$36,646**, worsens both 2025 and the selection-isolated 2026 test, and raises
closed-trade drawdown from **$34,574** to **$58,718**. W4Exit and W4Reverse are
worse. The optional frozen R10S arm reduces exposure and drawdown but remains
negative in both years.

This is a **Contract-2 1-second OHLC research simulation**, not NT-native
executable validation. A touched stop fills at the trigger unless the bar opens
adversely beyond it; no exact intrabar ordering or NT stop-market accuracy is
claimed.

## Executive findings

- The frozen population reconciles exactly: 11,812 candidates, 4,767
  opportunities, and 4,383 Policy A baseline trades with zero PnL difference.
- The old framework can observe a later W4 candidate while a baseline position
  is open: **5,060** such candidates, including **801** opposite-direction
  candidates. Current audited accounting suppresses overlaps; it does not book
  independent simultaneous trades.
- Independent first-candidate accounting would permit at most two simultaneous
  positions. The opposing overlaps net to at most one absolute unit. It produces
  **-$7,684**, versus **+$9,873** under the existing one-position baseline, a
  **-$17,557** difference.
- S1 takes 5,395 trades. Attempt 1 earns **+$19,218**, while attempts 2+ lose
  **$55,865**. Only 103 opportunities cumulatively recover above zero after an
  early stop and a later attempt.
- Later attempts do contain aligned reversals and winners, but not enough:
  attempt 2 loses $44,041, attempt 3 loses $8,935, and attempt 4+ loses $2,889.
- S2 exits 392 aligned positions on opposite W4 signals. Those exits directly
  lose **$8,861** versus the same trades' original counterfactual exits, and S2
  loses another **$30,542** versus S1 after the full lifecycle is replayed.
- S3 performs 410 same-signal reversals. Reverse entries lose **$23,172** in
  aggregate: 114 winners, 292 losers, and four flat outcomes. S3 loses $5,294
  more than S2 overall.
- S4/R10S is the least damaging streaming arm at **-$5,668**, but it is negative
  in both 2025 (-$3,444) and 2026 (-$2,223) and trails the baseline by $15,541.
- No policy is rescued by direction or session. S4 remains positive in RTH but
  loses more in ETH; that descriptive split was not used to select a rule.

## Part 0 — overlap and portfolio-state audit

| Measure | 2025 | 2026 | Combined |
|:--|--:|--:|--:|
| Candidate appears while baseline trade open | 3,655 | 1,405 | 5,060 |
| Candidate is opposite existing position | 558 | 243 | 801 |
| Independent first-candidate trades | 3,524 | 1,236 | 4,760 |
| Existing one-position baseline trades | 3,246 | 1,137 | 4,383 |
| Maximum simultaneous independent positions | 2 | 2 | 2 |
| Maximum absolute position after netting | 1 | 1 | 1 |
| Offsetting-exposure events | 254 | 90 | 344 |
| Independent-accounting net PnL | -$14,985.51 | $7,301.26 | -$7,684.24 |
| One-position baseline net PnL | -$8,114.84 | $17,988.06 | $9,873.22 |
| Independent minus one-position | -$6,870.67 | -$10,686.80 | -$17,557.46 |

The current frozen Policy A collector suppresses 377 first-candidate trades
through its overlap/busy-state rules. The prior multi-candidate R10/R30 replay
also used a global busy boundary. It did not book simultaneous opposing trades.

## Main policy results

Rates are fractions. Opportunity metrics include untraded opportunities at zero.
`AvgAlignAttempt` is evaluated among opportunities that reach alignment.

| Policy | Split | Opp | Trades | Net $ | $/Opp | $/Trade | PF | WR/trade | WR/opp | Stop | Timeout | W4Exit | Reverse | Avg win | Avg loss | Max DD | Trades/Opp | AvgAlignAttempt | Max attempts | Costs |
|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| BASELINE | ALL | 4,767 | 4,383 | 9,873 | 2.07 | 2.25 | 1.016 | .315 | .290 | .378 | .163 | 0 | 0 | 450.79 | -206.43 | 34,574 | .919 | 1.000 | 1 | 43,830 |
| BASELINE | 2025 | 3,530 | 3,246 | -8,115 | -2.30 | -2.50 | .982 | .313 | .288 | .384 | .163 | 0 | 0 | 426.86 | -199.81 | 34,574 | .920 | 1.000 | 1 | 32,460 |
| BASELINE | 2026 | 1,237 | 1,137 | 17,988 | 14.54 | 15.82 | 1.105 | .322 | .296 | .361 | .164 | 0 | 0 | 517.17 | -225.69 | 13,030 | .919 | 1.000 | 1 | 11,370 |
| S1 | ALL | 4,767 | 5,395 | -36,646 | -7.69 | -6.79 | .953 | .314 | .309 | .383 | .161 | 0 | 0 | 440.44 | -213.75 | 58,718 | 1.132 | 1.211 | 5 | 53,950 |
| S1 | 2025 | 3,530 | 4,008 | -41,776 | -11.83 | -10.42 | .926 | .311 | .308 | .388 | .161 | 0 | 0 | 422.12 | -207.89 | 58,718 | 1.135 | 1.210 | 4 | 40,080 |
| S1 | 2026 | 1,237 | 1,387 | 5,129 | 4.15 | 3.70 | 1.024 | .322 | .314 | .369 | .162 | 0 | 0 | 491.67 | -231.02 | 18,391 | 1.121 | 1.213 | 5 | 13,870 |
| S2 | ALL | 4,767 | 5,662 | -67,188 | -14.09 | -11.87 | .919 | .311 | .322 | .386 | .165 | 392 | 0 | 433.74 | -215.62 | 81,649 | 1.188 | 1.211 | 5 | 56,620 |
| S2 | 2025 | 3,530 | 4,186 | -47,505 | -13.46 | -11.35 | .920 | .310 | .320 | .388 | .165 | 287 | 0 | 422.76 | -208.18 | 65,211 | 1.186 | 1.210 | 4 | 41,860 |
| S2 | 2026 | 1,237 | 1,476 | -19,683 | -15.91 | -13.34 | .917 | .316 | .329 | .379 | .167 | 105 | 0 | 464.29 | -236.99 | 25,386 | 1.193 | 1.212 | 5 | 14,760 |
| S3 | ALL | 4,767 | 5,881 | -72,482 | -15.20 | -12.32 | .916 | .310 | .334 | .386 | .166 | 410 | 410 | 435.56 | -216.52 | 80,412 | 1.234 | 1.211 | 5 | 58,810 |
| S3 | 2025 | 3,530 | 4,355 | -54,969 | -15.57 | -12.62 | .912 | .309 | .333 | .389 | .165 | 300 | 300 | 421.53 | -209.33 | 63,071 | 1.234 | 1.210 | 4 | 43,550 |
| S3 | 2026 | 1,237 | 1,526 | -17,513 | -14.16 | -11.48 | .929 | .314 | .337 | .379 | .168 | 110 | 110 | 475.02 | -237.22 | 22,415 | 1.234 | 1.215 | 5 | 15,260 |
| S4 | ALL | 4,767 | 3,072 | -5,668 | -1.19 | -1.84 | .988 | .311 | .184 | .364 | .155 | 0 | 0 | 474.46 | -219.20 | 32,438 | .644 | 1.130 | 4 | 30,720 |
| S4 | 2025 | 3,530 | 2,275 | -3,444 | -.98 | -1.51 | .990 | .312 | .184 | .367 | .151 | 0 | 0 | 459.06 | -212.78 | 32,438 | .644 | 1.130 | 4 | 22,750 |
| S4 | 2026 | 1,237 | 797 | -2,223 | -1.80 | -2.79 | .983 | .307 | .184 | .356 | .166 | 0 | 0 | 519.08 | -237.43 | 13,238 | .644 | 1.129 | 4 | 7,970 |

The authoritative 55-row policy Parquet contains these same fields for every
required direction, session, and direction/session split. Their net PnL is
shown compactly below.

| Policy | ALL | 2025 | 2026 | Long | Short | ETH | RTH | Long ETH | Long RTH | Short ETH | Short RTH |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| BASELINE | 9,873 | -8,115 | 17,988 | -18,991 | 28,864 | -14,056 | 23,929 | -15,907 | -3,084 | 1,851 | 27,013 |
| S1 | -36,646 | -41,776 | 5,129 | -37,080 | 434 | -35,232 | -1,414 | -30,280 | -6,800 | -4,952 | 5,386 |
| S2 | -67,188 | -47,505 | -19,683 | -54,266 | -12,922 | -53,351 | -13,837 | -41,275 | -12,991 | -12,077 | -846 |
| S3 | -72,482 | -54,969 | -17,513 | -56,335 | -16,147 | -55,785 | -16,697 | -42,246 | -14,090 | -13,540 | -2,607 |
| S4 | -5,668 | -3,444 | -2,223 | -1,406 | -4,261 | -15,124 | 9,457 | -1,784 | 377 | -13,341 | 9,080 |

## Attempt-level accounting

| Policy | Attempt | Count | Net $ | WR | Pre-align stops | Reached alignment | Alignment rate | Prior-attempt PnL before first alignment | Recovered opps on this attempt | Recovered total |
|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| S1 | 1 | 4,379 | 19,218 | .316 | 1,331 | 2,341 | .535 | 0 | 0 | 103 |
| S1 | 2 | 823 | -44,041 | .307 | 275 | 424 | .515 | -91,566 | 92 | 103 |
| S1 | 3 | 162 | -8,935 | .272 | 62 | 64 | .395 | -33,806 | 11 | 103 |
| S1 | 4+ | 31 | -2,889 | .387 | 11 | 16 | .516 | -16,825 | 0 | 103 |
| S2 | 1 | 4,594 | -608 | .314 | 1,409 | 2,423 | .527 | 0 | 0 | 109 |
| S2 | 2 | 867 | -52,313 | .303 | 294 | 439 | .506 | -95,993 | 98 | 109 |
| S2 | 3 | 169 | -11,311 | .272 | 66 | 67 | .396 | -36,694 | 10 | 109 |
| S2 | 4+ | 32 | -2,955 | .375 | 12 | 16 | .500 | -16,825 | 1 | 109 |
| S3 | 1 | 4,760 | -12,395 | .312 | 1,468 | 2,504 | .526 | 0 | 0 | 114 |
| S3 | 2 | 909 | -44,735 | .306 | 307 | 456 | .502 | -100,477 | 103 | 114 |
| S3 | 3 | 180 | -12,397 | .272 | 71 | 70 | .389 | -38,984 | 10 | 114 |
| S3 | 4+ | 32 | -2,955 | .375 | 12 | 16 | .500 | -16,825 | 1 | 114 |
| S4 | 1 | 2,685 | 16,665 | .316 | 719 | 1,552 | .578 | 0 | 0 | 38 |
| S4 | 2 | 341 | -27,145 | .264 | 112 | 174 | .510 | -43,135 | 32 | 38 |
| S4 | 3 | 41 | 5,459 | .366 | 10 | 24 | .585 | -15,200 | 6 | 38 |
| S4 | 4+ | 5 | -647 | .200 | 3 | 2 | .400 | -1,911 | 0 | 38 |

The long-tail reversal outcome exists mechanically—S1 has 504 successful
alignments on attempts 2+—but its cohort loses $55,865. Later alignment is not
equivalent to a monetizable later entry.

## W4 lifecycle-exit accounting

| Measure | S2 W4Exit | S3 W4Reverse |
|:--|--:|--:|
| Aligned trades exited by opposite W4 | 392 | 410 |
| PnL at W4 exit | $362,830 | $383,440 |
| Same-trade counterfactual PnL | $371,691 | $391,546 |
| Direct exit change | -$8,861 | -$8,106 |
| Winners protected | 258 | 271 |
| Runners clipped | 127 | 132 |
| Planned losers avoided | 2 | 2 |
| Reverse entries | 0 | 410 |
| Reverse winners / losers / flat | 0 / 0 / 0 | 114 / 292 / 4 |
| Reverse-entry total PnL | — | -$23,172 |

The opposite W4 signal is not a superior lifecycle exit in this test. It often
locks a positive result, but the original exit is better in aggregate. More
importantly, freeing the portfolio earlier admits additional losing trades: S2
is $30,542 worse than S1, much more than the $8,861 direct exit difference.
Same-signal reversal adds cost and churn rather than edge.

## Reconciliation and attribution

- Policy A baseline: 4,383 trades and $9,873.22 exactly; zero timestamp, price,
  reason, or PnL reconciliation difference inherited from the frozen audited
  source.
- Candidate collector: 8,682 rows/3,530 opportunities in 2025 and 3,130
  rows/1,237 opportunities in 2026, exactly matching the prior collector.
- S1 versus prior R0: -$33,660.70 in 2025 and -$12,858.78 in 2026. The change is
  attributable to chronological one-position streaming and re-entry after exits.
- S4 versus prior multi-candidate R10: -$11,122.24 in 2025 and -$8,946.04 in
  2026. The prior R10 accepted only one candidate per opportunity; S4 continues
  scanning after completed trades and obeys a single global portfolio state.
- All policies use the same frozen W4 scores, thresholds, candidates, ATR
  denominator, Policy A stops/timeouts, costs, and year isolation.

## Answers to the study questions

1. **Re-enter after a pre-alignment stop?** No. The fixed immediate rule adds
   1,012 trades versus baseline and loses $46,519 of combined PnL. S1 attempts
   2+ are collectively negative in both development and final-test economics.
2. **Do eventual winners occur on attempts 2+?** Yes, but they are outweighed by
   losses. S1 has 424/64/16 successful alignments on attempts 2/3/4+, and 103
   opportunities cumulatively recover above zero after an early stop.
3. **Does one-position accounting matter?** Yes. Independent first-candidate
   accounting permits two concurrent positions and is $17,557 worse than the
   existing one-position baseline. Portfolio state materially changes results.
4. **Should opposite W4 exit the aligned trade?** No. W4Exit loses $8,861 on the
   paired same-trade comparison and produces a much worse full lifecycle.
5. **Should the signal reverse the trade?** No. The 410 reverse entries lose
   $23,172 and S3 is the worst policy tested.
6. **Does R10S rescue re-entry?** No. S4 is less damaging, but negative in both
   years and materially below baseline.

## Evidence boundary

No thresholds, delays, direction/session rules, or W4 model parameters were
selected from 2026. The positive S4 RTH and attempt-3 observations are
retrospective diagnostics, not new policies. No new policy is authorized by
this study.

The machine-readable Parquets are authoritative for every trade, attempt,
lifecycle exit, overlap case, reconciliation row, and all 55 required policy
split rows.

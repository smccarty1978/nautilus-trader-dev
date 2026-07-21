# CODEX 5.X W4 Price-Response Delayed Entry Replay

## Executive conclusion

**Final decision: `LONG_ETH_IMPROVES_BUT_NOT_GLOBAL`**

Neither fixed price-response gate improves Policy A in both years after causal
delayed fills. PR10 loses $20,791.52 versus Policy A combined. PR30 is much
better than PR10 and lowers trade-sequence drawdown, but it still loses
$5,574.02 versus Policy A combined and gives back $6,781.47 in the isolated
2026 year.

The useful signal is narrow: both gates reduce long-fade ETH drag in both
years. PR30 changes combined long ETH from -$15,906.92 to +$4,366.82 and its
bucket-only drawdown from $25,926.63 to $7,420.40. That improvement does not
generalize to the whole entry stream because the delay removes most of the
existing short-fade upside, especially short RTH.

This is a causal one-second OHLC research replay, not NT-native executable
validation or tick-level fill validation.

## Contract and denominators

- The opportunity set is the exact repaired 4,383-entry W4 stream.
- Policy A is the exact audited 1.25 ATR pre-flip stop plus five-minute timeout
  baseline.
- PR10/PR30 use only the latest fully completed one-second close at the fixed
  gate instant. Approved entries fill at the first available one-second open
  strictly after that instant.
- A regime ending by the gate or delayed fill rejects the trade. Raw gaps are
  not imputed.
- The five-minute timeout restarts at the delayed fill. The 1.25/1.50 ATR stops
  use `atr_at_checkpoint`, are anchored to the delayed fill, and are active on
  its entry bar.
- Skips contribute zero to policy total PnL and drawdown. Mean, PF, win rate,
  stop rate, timeout rate, and average win/loss use executed trades. The
  opportunity-set mean is reported separately as Mean/candidate.
- Drawdown is chronological closed-trade-sequence drawdown, not intratrade or
  portfolio marked-to-market drawdown.

## Full required policy results

| Split | Policy | Cand | Exec | Skip | Net $ | Mean exec $ | Mean/cand $ | PF | WR | Stop | Timeout | Avg win $ | Avg loss $ | DD $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| combined | Policy A | 4383 | 4383 | 0 | 9,873.22 | 2.25 | 2.25 | 1.016 | 31.5% | 37.8% | 16.3% | 450.79 | -206.43 | 34,574.02 |
| combined | PR10 | 4383 | 2105 | 2278 | -10,918.30 | -5.19 | -2.49 | 0.964 | 30.1% | 37.2% | 13.9% | 462.03 | -208.83 | 43,756.88 |
| combined | PR30 | 4383 | 1811 | 2572 | 4,299.20 | 2.37 | 0.98 | 1.016 | 31.3% | 36.8% | 13.1% | 486.89 | -219.31 | 23,743.63 |
| 2025 | Policy A | 3246 | 3246 | 0 | -8,114.84 | -2.50 | -2.50 | 0.982 | 31.3% | 38.4% | 16.3% | 426.86 | -199.81 | 34,574.02 |
| 2025 | PR10 | 3246 | 1596 | 1650 | -30,678.16 | -19.22 | -9.45 | 0.864 | 29.5% | 38.5% | 13.5% | 414.81 | -203.10 | 43,756.88 |
| 2025 | PR30 | 3246 | 1341 | 1905 | -6,907.39 | -5.15 | -2.13 | 0.964 | 31.5% | 37.4% | 13.0% | 437.49 | -210.01 | 23,743.63 |
| 2026 | Policy A | 1137 | 1137 | 0 | 17,988.06 | 15.82 | 15.82 | 1.105 | 32.2% | 36.1% | 16.4% | 517.17 | -225.69 | 13,030.08 |
| 2026 | PR10 | 1137 | 509 | 628 | 19,759.86 | 38.82 | 17.38 | 1.254 | 32.0% | 33.0% | 15.3% | 598.50 | -227.47 | 11,902.30 |
| 2026 | PR30 | 1137 | 470 | 667 | 11,206.59 | 23.84 | 9.86 | 1.141 | 30.6% | 35.3% | 13.6% | 631.67 | -245.40 | 8,595.03 |
| long_fade | Policy A | 1871 | 1871 | 0 | -18,990.81 | -10.15 | -10.15 | 0.935 | 31.5% | 39.7% | 14.4% | 464.58 | -230.78 | 40,223.20 |
| long_fade | PR10 | 1871 | 905 | 966 | 1,789.23 | 1.98 | 0.96 | 1.012 | 32.3% | 37.6% | 13.6% | 496.40 | -236.24 | 23,447.12 |
| long_fade | PR30 | 1871 | 814 | 1057 | 1,392.08 | 1.71 | 0.74 | 1.011 | 32.9% | 36.5% | 12.2% | 494.01 | -240.37 | 14,279.15 |
| short_fade | Policy A | 2512 | 2512 | 0 | 28,864.03 | 11.49 | 11.49 | 1.090 | 31.5% | 36.4% | 17.7% | 440.51 | -188.21 | 20,716.98 |
| short_fade | PR10 | 2512 | 1200 | 1312 | -12,707.53 | -10.59 | -5.06 | 0.921 | 28.5% | 36.9% | 14.2% | 432.69 | -189.27 | 27,704.77 |
| short_fade | PR30 | 2512 | 997 | 1515 | 2,907.12 | 2.92 | 1.16 | 1.021 | 29.9% | 37.1% | 13.9% | 480.49 | -202.71 | 16,630.23 |
| ETH | Policy A | 2937 | 2937 | 0 | -14,055.99 | -4.79 | -4.79 | 0.954 | 31.1% | 37.1% | 16.3% | 320.16 | -153.26 | 27,965.04 |
| ETH | PR10 | 2937 | 1395 | 1542 | -21,784.06 | -15.62 | -7.42 | 0.855 | 29.5% | 36.1% | 13.9% | 311.35 | -154.22 | 27,278.35 |
| ETH | PR30 | 2937 | 1210 | 1727 | 7,513.13 | 6.21 | 2.56 | 1.056 | 31.9% | 34.9% | 13.5% | 365.09 | -163.49 | 11,164.75 |
| RTH | Policy A | 1446 | 1446 | 0 | 23,929.21 | 16.55 | 16.55 | 1.078 | 32.3% | 39.3% | 16.3% | 706.47 | -316.43 | 29,142.97 |
| RTH | PR10 | 1446 | 710 | 736 | 10,865.75 | 15.30 | 7.51 | 1.071 | 31.4% | 39.3% | 13.9% | 739.75 | -318.39 | 30,094.25 |
| RTH | PR30 | 1446 | 601 | 845 | -3,213.93 | -5.35 | -2.22 | 0.977 | 30.0% | 40.8% | 12.5% | 748.08 | -327.48 | 18,872.36 |
| long_ETH | Policy A | 1232 | 1232 | 0 | -15,906.92 | -12.91 | -12.91 | 0.888 | 31.5% | 37.8% | 14.5% | 324.96 | -169.44 | 25,926.63 |
| long_ETH | PR10 | 1232 | 584 | 648 | -3,985.82 | -6.83 | -3.24 | 0.942 | 32.0% | 35.6% | 13.7% | 348.74 | -176.98 | 14,341.58 |
| long_ETH | PR30 | 1232 | 527 | 705 | 4,366.82 | 8.29 | 3.54 | 1.072 | 34.5% | 34.0% | 12.5% | 357.36 | -176.38 | 7,420.40 |
| long_RTH | Policy A | 639 | 639 | 0 | -3,083.89 | -4.83 | -4.83 | 0.980 | 31.6% | 43.3% | 14.2% | 732.75 | -349.77 | 19,362.84 |
| long_RTH | PR10 | 639 | 321 | 318 | 5,775.04 | 17.99 | 9.04 | 1.078 | 32.7% | 41.1% | 13.4% | 759.38 | -344.00 | 16,199.25 |
| long_RTH | PR30 | 639 | 287 | 352 | -2,974.74 | -10.36 | -4.66 | 0.958 | 30.0% | 41.1% | 11.5% | 783.20 | -349.90 | 10,569.17 |
| short_ETH | Policy A | 1705 | 1705 | 0 | 1,850.93 | 1.09 | 1.09 | 1.011 | 30.9% | 36.6% | 17.7% | 316.62 | -141.61 | 18,507.20 |
| short_ETH | PR10 | 1705 | 811 | 894 | -17,798.24 | -21.95 | -10.44 | 0.779 | 27.6% | 36.5% | 14.1% | 280.13 | -138.88 | 19,125.63 |
| short_ETH | PR30 | 1705 | 683 | 1022 | 3,146.31 | 4.61 | 1.85 | 1.043 | 29.9% | 35.6% | 14.2% | 371.99 | -154.11 | 9,365.53 |
| short_RTH | Policy A | 807 | 807 | 0 | 27,013.10 | 33.47 | 33.47 | 1.174 | 32.8% | 36.1% | 17.8% | 686.43 | -289.52 | 14,331.16 |
| short_RTH | PR10 | 807 | 389 | 418 | 5,090.71 | 13.09 | 6.31 | 1.064 | 30.3% | 37.8% | 14.4% | 722.29 | -297.92 | 18,933.82 |
| short_RTH | PR30 | 807 | 314 | 493 | -239.19 | -0.76 | -0.30 | 0.996 | 29.9% | 40.4% | 13.4% | 715.96 | -307.00 | 12,456.18 |

## Year-by-direction/session stability

| Policy | Year | Direction/session | Cand | Exec | Policy A $ | Delayed $ | Change $ |
|---|---:|---|---:|---:|---:|---:|---:|
| PR10 | 2025 | long ETH | 918 | 441 | -12,151.72 | -5,639.62 | 6,512.09 |
| PR10 | 2025 | short ETH | 1252 | 608 | -8,983.05 | -18,206.03 | -9,222.98 |
| PR10 | 2025 | long RTH | 472 | 246 | -7,284.08 | -5,184.89 | 2,099.19 |
| PR10 | 2025 | short RTH | 604 | 301 | 20,304.00 | -1,647.62 | -21,951.63 |
| PR10 | 2026 | long ETH | 314 | 143 | -3,755.20 | 1,653.81 | 5,409.01 |
| PR10 | 2026 | short ETH | 453 | 203 | 10,833.98 | 407.79 | -10,426.19 |
| PR10 | 2026 | long RTH | 167 | 75 | 4,200.19 | 10,959.93 | 6,759.74 |
| PR10 | 2026 | short RTH | 203 | 88 | 6,709.10 | 6,738.33 | 29.23 |
| PR30 | 2025 | long ETH | 918 | 394 | -12,151.72 | -1,292.97 | 10,858.74 |
| PR30 | 2025 | short ETH | 1252 | 504 | -8,983.05 | -5,373.20 | 3,609.84 |
| PR30 | 2025 | long RTH | 472 | 214 | -7,284.08 | -2,865.02 | 4,419.06 |
| PR30 | 2025 | short RTH | 604 | 229 | 20,304.00 | 2,623.81 | -17,680.19 |
| PR30 | 2026 | long ETH | 314 | 133 | -3,755.20 | 5,659.80 | 9,415.00 |
| PR30 | 2026 | short ETH | 453 | 179 | 10,833.98 | 8,519.51 | -2,314.47 |
| PR30 | 2026 | long RTH | 167 | 73 | 4,200.19 | -109.72 | -4,309.91 |
| PR30 | 2026 | short RTH | 203 | 85 | 6,709.10 | -2,863.00 | -9,572.10 |

Long ETH is the only compelling stable improvement: PR10 improves it by
$6,512.09 in 2025 and $5,409.01 in 2026; PR30 improves it by $10,858.74 and
$9,415.00. This is descriptive subgroup evidence, not authorization for a new
long-ETH-only policy.

## Removal benefit versus delayed-entry damage

| Policy | Year | Skipped-candidate benefit $ | Approved-trade change $ | Total change $ |
|---|---:|---:|---:|---:|
| PR10 | 2025 | 42,670.74 | -65,234.06 | -22,563.32 |
| PR10 | 2026 | 25,942.91 | -24,171.11 | 1,771.80 |
| PR10 | combined | 68,613.65 | -89,405.18 | -20,791.52 |
| PR30 | 2025 | 101,400.94 | -100,193.49 | 1,207.45 |
| PR30 | 2026 | 31,899.75 | -38,681.22 | -6,781.47 |
| PR30 | combined | 133,300.69 | -138,874.70 | -5,574.02 |

The non-adverse response condition does remove net-negative candidate sets.
The problem is implementation delay: approved PR10 fills move an average 2.18
directional points against the entry, while PR30 moves 3.74 points against it.
Only 284 of 2,105 PR10 executions and 164 of 1,811 PR30 executions improve the
fill. Thus the apparent original-entry morphology separation was real enough
to identify bad candidates, but it was not globally monetizable after waiting
and refilling.

## Complete overlapping trade-diff accounting

Positive directional fill change is worse; negative is better. Accounting
classes overlap and must not be summed across rows.

| Policy | Accounting class | N | Policy A $ | Delayed $ | Change $ | Avg change $ | Mean fill change pts |
|---|---|---:|---:|---:|---:|---:|---:|
| PR10 | skipped original stop-before losses | 919 | -224,157.03 | 0.00 | 224,157.03 | 243.91 | - |
| PR10 | skipped original planned winners | 616 | 269,145.26 | 0.00 | -269,145.26 | -436.92 | - |
| PR10 | skipped original planned losers | 550 | -67,868.14 | 0.00 | 67,868.14 | 123.40 | - |
| PR10 | skipped original stop-after trades | 193 | -45,733.75 | 0.00 | 45,733.75 | 236.96 | - |
| PR10 | aligning flip before delayed entry | 151 | 8,447.96 | 0.00 | -8,447.96 | -55.95 | - |
| PR10 | all approved delayed-entry slippage | 2105 | 78,486.87 | -10,918.30 | -89,405.18 | -42.47 | 2.18 |
| PR10 | approved improved fill | 284 | -4,701.47 | -441.98 | 4,259.49 | 15.00 | -0.99 |
| PR10 | approved worsened fill | 1714 | 80,518.17 | -13,541.49 | -94,059.66 | -54.88 | 2.84 |
| PR10 | approved unchanged fill | 107 | 2,670.16 | 3,065.16 | 395.00 | 3.69 | 0.00 |
| PR10 | approved later timed out | 293 | 7,029.41 | -1,560.00 | -8,589.41 | -29.32 | 1.56 |
| PR10 | approved stopped before alignment | 554 | -136,852.06 | -157,832.30 | -20,980.24 | -37.87 | 2.10 |
| PR10 | approved reached alignment | 1258 | 208,309.53 | 148,473.99 | -59,835.53 | -47.56 | 2.36 |
| PR30 | skipped original stop-before losses | 1047 | -253,434.85 | 0.00 | 253,434.85 | 242.06 | - |
| PR30 | skipped original planned winners | 653 | 258,745.73 | 0.00 | -258,745.73 | -396.24 | - |
| PR30 | skipped original planned losers | 627 | -78,852.16 | 0.00 | 78,852.16 | 125.76 | - |
| PR30 | skipped original stop-after trades | 245 | -59,759.40 | 0.00 | 59,759.40 | 243.92 | - |
| PR30 | aligning flip before delayed entry | 522 | 39,620.62 | 0.00 | -39,620.62 | -75.90 | - |
| PR30 | all approved delayed-entry slippage | 1811 | 143,173.91 | 4,299.20 | -138,874.70 | -76.68 | 3.74 |
| PR30 | approved improved fill | 164 | 1,642.14 | 6,167.43 | 4,525.29 | 27.59 | -0.97 |
| PR30 | approved worsened fill | 1581 | 142,252.75 | -714.59 | -142,967.34 | -90.43 | 4.39 |
| PR30 | approved unchanged fill | 66 | -720.99 | -1,153.64 | -432.65 | -6.56 | 0.00 |
| PR30 | approved later timed out | 238 | 7,974.09 | -3,280.00 | -11,254.09 | -47.29 | 2.58 |
| PR30 | approved stopped before alignment | 436 | -92,188.71 | -125,524.43 | -33,335.73 | -76.46 | 2.96 |
| PR30 | approved reached alignment | 1137 | 227,388.52 | 133,103.64 | -94,284.88 | -82.92 | 4.29 |

## Answers to the study questions

1. **PR10 does not improve Policy A.** It worsens 2025 by $22,563.32 and the
   combined sample by $20,791.52. Its $1,771.80 improvement in 2026 cannot
   rescue a rule that failed development.
2. **PR30 gives up too much edge globally.** It improves 2025 by only $1,207.45
   after removing $101,400.94 from skipped candidates because delayed executed
   trades lose $100,193.49 versus their Policy A paths. It then trails Policy A
   by $6,781.47 in 2026.
3. **PR30 is better than PR10, but neither qualifies globally.** PR30 has higher
   combined PnL and materially lower drawdown; this is not enough to overcome
   its lower total PnL and isolated-year failure versus Policy A.
4. **Neither improves both years.** PR10 improves only 2026; PR30 improves only
   2025.
5. **Long ETH improves under both gates in both years.** PR30 is the strongest
   descriptive case, although its 2025 long-ETH PnL remains -$1,292.97.
6. **Short-fade upside is not preserved.** Policy A's +$28,864.03 short-fade
   total falls to -$12,707.53 under PR10 and +$2,907.12 under PR30. PR30 short
   RTH falls from +$27,013.10 to -$239.19.
7. **The useful effect is bad-trade removal, not better fills.** Both gates
   skip net-negative cohorts, but most approved fills are directionally worse
   and the approved paths surrender more than the exclusions save globally.

## Guardrails and evidence limits

PR10 and PR30 were fixed before replay. No W4 retraining, trigger change,
threshold search, added filter, confirmation grid, MFE continuation, or
post-flip rule was run. The 2025 artifact was completed and hash-sealed before
2026 was opened. The long-ETH result is a retrospective subgroup finding; it
is not a newly tested or approved trading policy.

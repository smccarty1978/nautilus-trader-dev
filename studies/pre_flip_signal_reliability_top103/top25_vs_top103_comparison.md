# Top103 Pre-Flip Signal Reliability Study

> **Semantic correction:** This report compares two **Bearish Fade** models on bearish-regime candidates forecasting confirmed bullish flips (expected trade direction: long). It does not validate the separate **Bullish Fade** model, which remains `REQUIRES_TARGET_AND_DIRECTION_SEMANTICS_REAUDIT`.

## Recommendation

**Continue using the Top25 pre-flip reliability study as the canonical reference.**

Top103 remains the production scoring model, but the older Top25 reliability study remains the better canonical *timing reference*: Top103 fails the predeclared replacement gate because flip-within-300s probability is lower at all three operating thresholds.

## Threshold comparison

| Top % | signals/day 25→103 | flip≤300 25→103 | flip≤600 25→103 | median sec 25→103 | p90 / p95 sec 25→103 | rem MFE ATR 25→103 | path MAE ATR 25→103 | mark PnL pts 25→103 | captured % 25→103 |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | 1.01→0.99 | 0.718→0.699 | 0.824→0.833 | 80.0→105.0 | 1002.0/1480.5→1064.0/1515.2 | 0.492→0.620 | 0.492→0.620 | 2.50→3.75 | 56.9→58.8 |
| 2.5 | 1.73→1.73 | 0.614→0.594 | 0.762→0.758 | 172.5→205.0 | 1185.0/1632.7→1195.0/1572.2 | 0.836→0.869 | 0.836→0.869 | 3.88→5.00 | 55.4→56.7 |
| 5 | 2.40→2.46 | 0.538→0.533 | 0.712→0.714 | 260.0→270.0 | 1280.0/1695.0→1300.0/1710.2 | 1.006→1.039 | 1.006→1.039 | 5.00→5.75 | 54.8→55.9 |

`mark PnL` is the explicitly non-executable last-close mark at the confirmed-flip boundary, not a fill.

## Signal overlap and reliability
- Top 1%: shared 126, Top25-only 381, Top103-only 372, Jaccard 0.143.
- Top 2.5%: shared 192, Top25-only 678, Top103-only 680, Jaccard 0.124.
- Top 5%: shared 286, Top25-only 923, Top103-only 954, Jaccard 0.132.
- Common-checkpoint rank correlation: 0.884.
- Top25 reliability: bottom decile flip≤300 0.095, top decile 0.525; bottom/top flip≤600 0.342/0.710.
- Top103 reliability: bottom decile flip≤300 0.080, top decile 0.545; bottom/top flip≤600 0.319/0.731.

## False positives and buckets
- Top 1% Top25→Top103: no flip≤300 143→150; no flip≤600 89→83; never flip 0→0; A/B/C 314/50/143→317/31/150.
- Top 2.5% Top25→Top103: no flip≤300 336→354; no flip≤600 207→211; never flip 0→0; A/B/C 514/20/336→505/13/354.
- Top 5% Top25→Top103: no flip≤300 559→579; no flip≤600 348→355; never flip 0→0; A/B/C 641/9/559→658/3/579.

## Paired statistical evidence

Paired bootstrap is by common regime with seed 42; intervals below are Top103−Top25.

| Top % | Metric | n | Delta | 95% CI |
|---:|---|---:|---:|---|
| 1 | time_to_flip_s | 366 | 30.000 | [0.000, 45.000] |
| 1 | rem_mfe_atr | 366 | 0.077 | [-0.015, 0.230] |
| 1 | path_mae_atr | 366 | 0.077 | [-0.015, 0.230] |
| 1 | flip_exit_pnl_pts | 366 | 0.750 | [0.250, 1.500] |
| 1 | captured_mfe_pct | 366 | 1.232 | [0.270, 2.048] |
| 1 | flip_le_300 | 366 | -0.022 | [-0.052, 0.008] |
| 1 | flip_le_600 | 366 | 0.016 | [-0.003, 0.038] |
| 2.5 | time_to_flip_s | 693 | 30.000 | [0.000, 50.000] |
| 2.5 | rem_mfe_atr | 693 | -0.003 | [-0.096, 0.137] |
| 2.5 | path_mae_atr | 693 | -0.003 | [-0.096, 0.137] |
| 2.5 | flip_exit_pnl_pts | 693 | 1.000 | [0.250, 1.250] |
| 2.5 | captured_mfe_pct | 693 | 1.521 | [0.646, 2.543] |
| 2.5 | flip_le_300 | 693 | -0.022 | [-0.048, 0.003] |
| 2.5 | flip_le_600 | 693 | -0.003 | [-0.022, 0.016] |
| 5 | time_to_flip_s | 1054 | 15.000 | [-7.500, 42.500] |
| 5 | rem_mfe_atr | 1054 | -0.007 | [-0.093, 0.066] |
| 5 | path_mae_atr | 1054 | -0.007 | [-0.093, 0.066] |
| 5 | flip_exit_pnl_pts | 1054 | 0.125 | [-0.125, 0.750] |
| 5 | captured_mfe_pct | 1054 | 0.723 | [-0.039, 1.528] |
| 5 | flip_le_300 | 1054 | -0.012 | [-0.033, 0.008] |
| 5 | flip_le_600 | 1054 | 0.002 | [-0.014, 0.018] |

## Executive answers

1. **Materially stronger reliability?** No. Flip≤300 is lower at Top 1%, 2.5%, and 5%; paired intervals do not establish improvement.
2. **Earlier flips?** No. Median warnings are 25s, 32.5s, and 10s later in the aggregate tables; paired median deltas are nonnegative.
3. **Less remaining prevailing movement?** No consistent improvement; changes are small and paired intervals cross zero.
4. **Less adverse excursion?** No consistent improvement; path-MAE changes mirror remaining-MFE changes and intervals cross zero.
5. **Higher confirmed-flip probability within 300s?** No, it is lower at every tested threshold.
6. **Only highest scores or all thresholds?** The lack of improvement spans all Top 1/2.5/5% thresholds. Reliability still rises with percentile, but Top103 does not dominate the original timing population.
7. **Replace canonical reference?** No. Retain Top25 as the canonical pre-flip reliability reference while Top103 remains the production scoring artifact.

## Frozen replacement gate

| Clause | Result |
|---|---|
| Flip≤300 non-worse at all thresholds | FAIL |
| Strictly better at two thresholds | FAIL |
| At least one paired flip≤300 CI above zero | FAIL |
| Median time no later at two thresholds | FAIL |
| Never >60s later | PASS |
| Remaining MFE never >0.10 ATR worse | FAIL |
| Path MAE never >0.10 ATR worse | FAIL |

Overall gate: **FAIL — retain Top25 canonical reference.**

PRE-FLIP D10 REVERSAL STUDY

BEST POLICY:
NONE

2025 EV LIFT VS FLIP-TO-FLIP BASELINE:
$-7.90 per trade  (representative P3 @ 1.00 ATR; no policy qualified)

2026 EV LIFT VS FLIP-TO-FLIP BASELINE:
$13.24 per trade  (representative P3 @ 1.00 ATR; no policy qualified)

2025 STOP-OUT BEFORE FLIP RATE:
37.3%

2026 STOP-OUT BEFORE FLIP RATE:
36.9%

2025 NEW-REGIME D10 EXIT RATE:
35.2%

2026 NEW-REGIME D10 EXIT RATE:
36.9%

2025 OPPOSITE-FLIP FALLBACK EXIT RATE:
14.8%

2026 OPPOSITE-FLIP FALLBACK EXIT RATE:
13.8%

PERCENT OF VALIDLY SCORED REGIMES THAT EVER REACH D10:
96.3%

AVERAGE PRE-FLIP PNL:
$-0.26

AVERAGE POST-FLIP PNL:
$-9.23

D10 FRONT-RUN ENTRY ADVANTAGE VS WAITING FOR FLIP:
mean $-3.16 / -0.024 ATR (gross of costs)

MATCHED PLACEBO P-VALUE:
2025: 0.0000 (real WORSE than placebo by $33.21/tr), 2026: 0.0000 (real WORSE than placebo by $37.00/tr)  (Welch, P3 @ 1.00)

VERDICT:
CLOSE


---

## 1. Executive summary

- Frozen D10 threshold 0.618328 (P90 of Jan-Feb 2025 val W4 scores; absolute threshold; val AUC 0.8161).
- 24,805 pre-flip D10 entry events (17,726 in 2025 econ window, 7,079 in 2026).
- 96.3% of validly scored regimes ever reach D10; the opposite flip is the required fallback for the remainder.
- **Key mechanistic finding**: every pre-flip policy is net negative in both years, and the covariate-matched placebo beats the real D10 entries by ~$35-50/trade with the ENTIRE gap in the pre-flip leg (P1@1.0 pre-flip mean ~$-1 vs placebo ~+$39; conditional on confirmation +$108 vs +$240). A regime flip is by definition a move against the old regime, so ANY counter-regime entry that survives to the flip harvests mechanical drift — and D10 fires only after the deterioration has largely run (median 49s entry-to-flip vs 99s for placebo), capturing the least of it. The D10 signal is therefore WORSE-than-random entry timing: it chases the reversion move it is trying to anticipate.
- Placebo absolute profitability (+$15-30/tr net) is NOT a deployable claim: both arms fill counter-trend at the last traded 1s close, a convention known to flatter fade entries (bar-mode fade inflation, see project memory); it is valid only as the relative control, which the real signal decisively loses.
- Verdict: **CLOSE** (rules in section 17).

## 2/3. Strategy, policy and threshold definitions

See SPEC.md (checked in beside this report) for the full frozen definitions: policies P0-P4B, one-attempt-per-regime, stop-only pre-confirmation, D10-or-flip exit priority, NT-native fill conventions (fixture-verified), and the absolute validation-frozen threshold.

## 4/5. Entry timing and stop execution audits

- Pre-flip entries submit exactly 1s after observation (fail-fast checked in analyze.py; see audit/entry_timing_audit.parquet and audit/entry_event_reconciliation.parquet).
- Stop fills: NT fills at trigger; gap-through fills conservatively repriced to fill-bar open (primary economics). Raw NT economics carried alongside (`net_usd_raw`).

## 6. Score / regime-ID reset audit

See audit/score_regime_id_audit.parquet (fail-fast: zero orphan score regimes) and the d10_exit_wrong_regime invariant in audit/exit_reason_completeness_audit.parquet.

## 7. Regime-level D10 coverage

|   year |   n_regimes |   validly_scored |   ever_d10 |   d10_before_end |   d10_at_end_only |   truncated_1800s |
|-------:|------------:|-----------------:|-----------:|-----------------:|------------------:|------------------:|
|   2025 |       22910 |            22888 |      22002 |            17726 |              4276 |              1928 |
|   2026 |        8935 |             8922 |       8624 |             7079 |              1545 |               728 |

Full breakdowns: results/regime_d10_coverage_summary.parquet (economics window only; calibration window tagged separately in the row-level file).

## 8. D10 entry diagnostics & front-run advantage

- n with both executable prices: 24,805
- mean $-3.16, median $35.00, p25 $-10.00, p75 $110.00, p10 $-220.00, p90 $235.00, % positive 68.1% (gross)
- median seconds D10 -> flip: 130s

## 9. Pre-flip vs post-flip PnL decomposition (NT trades)

| policy   |   stop |   year |   n_trades |   stop_before_flip_rate |   flip_confirmation_rate |   avg_pre_flip_pnl_usd |   avg_post_flip_pnl_usd |   avg_preflip_mae_atr |   p90_preflip_mae_atr |   ev_per_trade |
|:---------|-------:|-------:|-----------:|------------------------:|-------------------------:|-----------------------:|------------------------:|----------------------:|----------------------:|---------------:|
| P1       |    0.5 |   2025 |      15124 |                    0.52 |                     0.48 |                  -2.26 |                   -7.24 |                  0.27 |                  0.46 |         -19.5  |
| P1       |    0.5 |   2026 |       6052 |                    0.52 |                     0.48 |                  -2.39 |                   -9.6  |                  0.28 |                  0.47 |         -21.99 |
| P1       |    1   |   2025 |      13044 |                    0.37 |                     0.63 |                  -1.39 |                   -6.59 |                  0.5  |                  0.95 |         -17.99 |
| P1       |    1   |   2026 |       5160 |                    0.37 |                     0.63 |                   2.59 |                  -14.18 |                  0.51 |                  0.96 |         -21.59 |
| P1       |    1.5 |   2025 |      11990 |                    0.29 |                     0.71 |                  -0.93 |                   -2.74 |                  0.68 |                  1.44 |         -13.67 |
| P1       |    1.5 |   2026 |       4704 |                    0.28 |                     0.72 |                   4.4  |                  -12.58 |                  0.69 |                  1.44 |         -18.18 |
| P3       |    0.5 |   2025 |      15124 |                    0.52 |                     0.48 |                  -2.26 |                   -6.35 |                  0.27 |                  0.46 |         -18.61 |
| P3       |    0.5 |   2026 |       6052 |                    0.52 |                     0.48 |                  -2.39 |                   -8.06 |                  0.28 |                  0.47 |         -20.45 |
| P3       |    1   |   2025 |      13044 |                    0.37 |                     0.63 |                  -1.39 |                   -7.73 |                  0.5  |                  0.95 |         -19.12 |
| P3       |    1   |   2026 |       5160 |                    0.37 |                     0.63 |                   2.59 |                  -13.03 |                  0.51 |                  0.96 |         -20.44 |
| P3       |    1.5 |   2025 |      11990 |                    0.29 |                     0.71 |                  -0.93 |                   -6.62 |                  0.68 |                  1.44 |         -17.55 |
| P3       |    1.5 |   2026 |       4704 |                    0.28 |                     0.72 |                   4.4  |                   -8.99 |                  0.69 |                  1.44 |         -14.59 |

## 10. Stop sensitivity (all stops always shown; none test-selected)

| policy   |   stop |   year |   n_trades |   n_censored |   stop_before_flip_rate |   flip_confirmation_rate |   stop_after_flip_rate |   d10_exit_rate |   opposite_flip_exit_rate |   win_rate |   gross_usd |   net_usd |   ev_per_trade |   profit_factor |   max_drawdown_usd |   median_trade_usd |   p10_trade_usd |   p90_trade_usd |   monthly_positive_rate |   n_stop_gap_repriced |
|:---------|-------:|-------:|-----------:|-------------:|------------------------:|-------------------------:|-----------------------:|----------------:|--------------------------:|-----------:|------------:|----------:|---------------:|----------------:|-------------------:|-------------------:|----------------:|----------------:|------------------------:|----------------------:|
| P1       |    0.5 |   2025 |      15124 |            0 |                    0.52 |                     0.48 |                   0.29 |            0    |                      0.19 |       0.15 |     -143670 |   -294910 |         -19.5  |            0.76 |            -306635 |                -65 |            -170 |           105   |                    0.1  |                  2260 |
| P1       |    0.5 |   2026 |       6052 |            0 |                    0.52 |                     0.48 |                   0.29 |            0    |                      0.19 |       0.15 |      -72540 |   -133060 |         -21.99 |            0.78 |            -139080 |                -85 |            -195 |           160   |                    0    |                   986 |
| P1       |    1   |   2025 |      13044 |            0 |                    0.37 |                     0.63 |                   0.23 |            0    |                      0.4  |       0.24 |     -104185 |   -234625 |         -17.99 |            0.85 |            -280835 |                -90 |            -280 |           265   |                    0.1  |                  1142 |
| P1       |    1   |   2026 |       5160 |            0 |                    0.37 |                     0.63 |                   0.24 |            0    |                      0.39 |       0.25 |      -59790 |   -111390 |         -21.59 |            0.86 |            -127150 |               -120 |            -330 |           375   |                    0    |                   504 |
| P1       |    1.5 |   2025 |      11990 |            0 |                    0.29 |                     0.71 |                   0.13 |            0    |                      0.58 |       0.3  |      -43955 |   -163855 |         -13.67 |            0.91 |            -202865 |                -95 |            -350 |           340   |                    0.1  |                   504 |
| P1       |    1.5 |   2026 |       4704 |            0 |                    0.28 |                     0.72 |                   0.13 |            0    |                      0.59 |       0.3  |      -38485 |    -85525 |         -18.18 |            0.9  |            -100640 |               -125 |            -440 |           485   |                    0.25 |                   235 |
| P3       |    0.5 |   2025 |      15124 |            0 |                    0.52 |                     0.48 |                   0.23 |            0.17 |                      0.08 |       0.18 |     -130285 |   -281525 |         -18.61 |            0.76 |            -285775 |                -60 |            -165 |           120   |                    0    |                  2176 |
| P3       |    0.5 |   2026 |       6052 |            0 |                    0.52 |                     0.48 |                   0.24 |            0.17 |                      0.07 |       0.18 |      -63215 |   -123735 |         -20.45 |            0.78 |            -128675 |                -80 |            -190 |           170   |                    0    |                   949 |
| P3       |    1   |   2025 |      13044 |            0 |                    0.37 |                     0.63 |                   0.13 |            0.35 |                      0.15 |       0.27 |     -118955 |   -249395 |         -19.12 |            0.82 |            -291495 |                -80 |            -255 |           230   |                    0.1  |                   981 |
| P3       |    1   |   2026 |       5160 |            0 |                    0.37 |                     0.63 |                   0.12 |            0.37 |                      0.14 |       0.27 |      -53875 |   -105475 |         -20.44 |            0.85 |            -111940 |               -105 |            -310 |           330.5 |                    0    |                   436 |
| P3       |    1.5 |   2025 |      11990 |            0 |                    0.29 |                     0.71 |                   0.03 |            0.47 |                      0.2  |       0.31 |      -90560 |   -210460 |         -17.55 |            0.86 |            -240610 |                -75 |            -310 |           285   |                    0    |                   396 |
| P3       |    1.5 |   2026 |       4704 |            0 |                    0.28 |                     0.72 |                   0.03 |            0.5  |                      0.18 |       0.32 |      -21570 |    -68610 |         -14.59 |            0.9  |             -72700 |                -95 |            -395 |           410   |                    0    |                   179 |

## 11. Policy comparison (all policies)

| policy   |   stop |   year |   n_trades |   ev_per_trade |   net_usd |   win_rate |   profit_factor |   max_drawdown_usd |   monthly_positive_rate |   n_censored |
|:---------|-------:|-------:|-----------:|---------------:|----------:|-----------:|----------------:|-------------------:|------------------------:|-------------:|
| P0       |    0   |   2025 |      22909 |         -11.22 |   -256965 |       0.31 |            0.93 |            -353425 |                    0.2  |            1 |
| P0       |    0   |   2026 |       8933 |         -33.68 |   -300840 |       0.32 |            0.83 |            -312715 |                    0    |            1 |
| P1       |    0.5 |   2025 |      15124 |         -19.5  |   -294910 |       0.15 |            0.76 |            -306635 |                    0.1  |            0 |
| P1       |    0.5 |   2026 |       6052 |         -21.99 |   -133060 |       0.15 |            0.78 |            -139080 |                    0    |            0 |
| P1       |    1   |   2025 |      13044 |         -17.99 |   -234625 |       0.24 |            0.85 |            -280835 |                    0.1  |            0 |
| P1       |    1   |   2026 |       5160 |         -21.59 |   -111390 |       0.25 |            0.86 |            -127150 |                    0    |            0 |
| P1       |    1.5 |   2025 |      11990 |         -13.67 |   -163855 |       0.3  |            0.91 |            -202865 |                    0.1  |            0 |
| P1       |    1.5 |   2026 |       4704 |         -18.18 |    -85525 |       0.3  |            0.9  |            -100640 |                    0.25 |            0 |
| P2       |    0   |   2025 |      22909 |         -17.36 |   -397680 |       0.29 |            0.85 |            -433095 |                    0    |            1 |
| P2       |    0   |   2026 |       8933 |         -24.78 |   -221340 |       0.29 |            0.83 |            -236220 |                    0    |            1 |
| P3       |    0.5 |   2025 |      15124 |         -18.61 |   -281525 |       0.18 |            0.76 |            -285775 |                    0    |            0 |
| P3       |    0.5 |   2026 |       6052 |         -20.45 |   -123735 |       0.18 |            0.78 |            -128675 |                    0    |            0 |
| P3       |    1   |   2025 |      13044 |         -19.12 |   -249395 |       0.27 |            0.82 |            -291495 |                    0.1  |            0 |
| P3       |    1   |   2026 |       5160 |         -20.44 |   -105475 |       0.27 |            0.85 |            -111940 |                    0    |            0 |
| P3       |    1.5 |   2025 |      11990 |         -17.55 |   -210460 |       0.31 |            0.86 |            -240610 |                    0    |            0 |
| P3       |    1.5 |   2026 |       4704 |         -14.59 |    -68610 |       0.32 |            0.9  |             -72700 |                    0    |            0 |
| P4A      |    0.5 |   2025 |      14204 |          11.89 |    168815 |       0.21 |            1.16 |             -22245 |                    0.6  |            0 |
| P4A      |    0.5 |   2026 |       5665 |          11.33 |     64175 |       0.21 |            1.12 |             -17350 |                    0.75 |            0 |
| P4A      |    1   |   2025 |      12816 |          17.81 |    228315 |       0.31 |            1.16 |             -29615 |                    0.7  |            0 |
| P4A      |    1   |   2026 |       5088 |          17.63 |     89685 |       0.31 |            1.13 |             -23580 |                    0.75 |            0 |
| P4A      |    1.5 |   2025 |      12166 |          18.36 |    223370 |       0.36 |            1.14 |             -25500 |                    0.7  |            0 |
| P4A      |    1.5 |   2026 |       4789 |          29.19 |    139790 |       0.37 |            1.19 |             -18970 |                    1    |            0 |
| P4B      |    0.5 |   2025 |      14970 |          10.24 |    153355 |       0.25 |            1.15 |             -14300 |                    0.6  |            0 |
| P4B      |    0.5 |   2026 |       5949 |          12.51 |     74440 |       0.24 |            1.14 |             -14370 |                    1    |            0 |
| P4B      |    1   |   2025 |      13897 |          14.09 |    195775 |       0.34 |            1.14 |             -24460 |                    0.7  |            0 |
| P4B      |    1   |   2026 |       5542 |          16.56 |     91780 |       0.34 |            1.14 |             -18525 |                    0.75 |            0 |
| P4B      |    1.5 |   2025 |      13402 |          14.42 |    193190 |       0.39 |            1.12 |             -31170 |                    0.8  |            0 |
| P4B      |    1.5 |   2026 |       5321 |          22.78 |    121210 |       0.4  |            1.16 |             -18405 |                    1    |            0 |

## 12. D10 exit vs opposite-flip fallback

| run_policy   |   run_stop |   run_year | category                    |     n |   mean_incremental_usd |   total_incremental_usd |
|:-------------|-----------:|-----------:|:----------------------------|------:|-----------------------:|------------------------:|
| P2           |        0   |       2025 | d10_exit                    | 17642 |                  -7.98 |                 -140715 |
| P2           |        0   |       2025 | no_d10_before_flip          |  5246 |                   0    |                       0 |
| P2           |        0   |       2025 | score_unavailable           |    21 |                   0    |                       0 |
| P2           |        0   |       2026 | d10_exit                    |  7063 |                  11.26 |                   79500 |
| P2           |        0   |       2026 | no_d10_before_flip          |  1859 |                   0    |                       0 |
| P2           |        0   |       2026 | score_unavailable           |    11 |                   0    |                       0 |
| P3           |        0.5 |       2025 | d10_exit                    |  2518 |                   4.87 |                   12270 |
| P3           |        0.5 |       2025 | no_d10_before_flip          |  1174 |                   0    |                       0 |
| P3           |        0.5 |       2025 | stopped_after_confirmation  |  3547 |                  -4.86 |                  -17255 |
| P3           |        0.5 |       2025 | stopped_before_confirmation |  7885 |                 nan    |                       0 |
| P3           |        0.5 |       2026 | d10_exit                    |  1011 |                  -2.1  |                   -2125 |
| P3           |        0.5 |       2026 | no_d10_before_flip          |   444 |                   0    |                       0 |
| P3           |        0.5 |       2026 | score_unavailable           |     2 |                   0    |                       0 |
| P3           |        0.5 |       2026 | stopped_after_confirmation  |  1444 |                   6.2  |                    8960 |
| P3           |        0.5 |       2026 | stopped_before_confirmation |  3151 |                 nan    |                       0 |
| P3           |        1   |       2025 | d10_exit                    |  4598 |                  -3.24 |                  -14875 |
| P3           |        1   |       2025 | no_d10_before_flip          |  1932 |                   0    |                       0 |
| P3           |        1   |       2025 | score_unavailable           |     1 |                   0    |                       0 |
| P3           |        1   |       2025 | stopped_after_confirmation  |  1646 |                 -25.1  |                  -41315 |
| P3           |        1   |       2025 | stopped_before_confirmation |  4867 |                 nan    |                       0 |
| P3           |        1   |       2026 | d10_exit                    |  1903 |                   0.14 |                     275 |
| P3           |        1   |       2026 | no_d10_before_flip          |   710 |                   0    |                       0 |
| P3           |        1   |       2026 | score_unavailable           |     3 |                   0    |                       0 |
| P3           |        1   |       2026 | stopped_after_confirmation  |   641 |                 -12.34 |                   -7910 |
| P3           |        1   |       2026 | stopped_before_confirmation |  1903 |                 nan    |                       0 |
| P3           |        1.5 |       2025 | d10_exit                    |  5652 |                  -7.92 |                  -44765 |
| P3           |        1.5 |       2025 | no_d10_before_flip          |  2410 |                   0    |                       0 |
| P3           |        1.5 |       2025 | score_unavailable           |     2 |                   0    |                       0 |
| P3           |        1.5 |       2025 | stopped_after_confirmation  |   408 |                 -75.39 |                  -30760 |
| P3           |        1.5 |       2025 | stopped_before_confirmation |  3518 |                 nan    |                       0 |
| P3           |        1.5 |       2026 | d10_exit                    |  2359 |                  10.05 |                   23710 |
| P3           |        1.5 |       2026 | no_d10_before_flip          |   861 |                   0    |                       0 |
| P3           |        1.5 |       2026 | score_unavailable           |     4 |                   0    |                       0 |
| P3           |        1.5 |       2026 | stopped_after_confirmation  |   143 |                  22.34 |                    3195 |
| P3           |        1.5 |       2026 | stopped_before_confirmation |  1337 |                 nan    |                       0 |
| P4B          |        0.5 |       2025 | d10_exit                    |  3250 |                 -11.44 |                  -37165 |
| P4B          |        0.5 |       2025 | no_d10_before_flip          |  1593 |                   0    |                       0 |
| P4B          |        0.5 |       2025 | score_unavailable           |     1 |                   0    |                       0 |
| P4B          |        0.5 |       2025 | stopped_after_confirmation  |  1653 |                  -4.27 |                   -7065 |
| P4B          |        0.5 |       2025 | stopped_before_confirmation |  8473 |                 nan    |                       0 |
| P4B          |        0.5 |       2026 | d10_exit                    |  1293 |                   7.71 |                    9975 |
| P4B          |        0.5 |       2026 | no_d10_before_flip          |   602 |                   0    |                       0 |
| P4B          |        0.5 |       2026 | score_unavailable           |     1 |                   0    |                       0 |
| P4B          |        0.5 |       2026 | stopped_after_confirmation  |   650 |                  11.71 |                    7610 |
| P4B          |        0.5 |       2026 | stopped_before_confirmation |  3403 |                 nan    |                       0 |
| P4B          |        1   |       2025 | d10_exit                    |  5197 |                 -12.1  |                  -62900 |
| P4B          |        1   |       2025 | no_d10_before_flip          |  2326 |                   0    |                       0 |
| P4B          |        1   |       2025 | score_unavailable           |     1 |                   0    |                       0 |
| P4B          |        1   |       2025 | stopped_after_confirmation  |   522 |                   0.01 |                       5 |
| P4B          |        1   |       2025 | stopped_before_confirmation |  5851 |                 nan    |                       0 |
| P4B          |        1   |       2026 | d10_exit                    |  2132 |                   3.93 |                    8380 |
| P4B          |        1   |       2026 | no_d10_before_flip          |   868 |                   0    |                       0 |
| P4B          |        1   |       2026 | score_unavailable           |     2 |                   0    |                       0 |
| P4B          |        1   |       2026 | stopped_after_confirmation  |   200 |                  22.95 |                    4590 |
| P4B          |        1   |       2026 | stopped_before_confirmation |  2340 |                 nan    |                       0 |
| P4B          |        1.5 |       2025 | d10_exit                    |  6130 |                  -6.37 |                  -39065 |
| P4B          |        1.5 |       2025 | no_d10_before_flip          |  2776 |                   0    |                       0 |
| P4B          |        1.5 |       2025 | score_unavailable           |     1 |                   0    |                       0 |
| P4B          |        1.5 |       2025 | stopped_after_confirmation  |   144 |                  11.32 |                    1630 |
| P4B          |        1.5 |       2025 | stopped_before_confirmation |  4351 |                 nan    |                       0 |
| P4B          |        1.5 |       2026 | d10_exit                    |  2556 |                   2.9  |                    7410 |
| P4B          |        1.5 |       2026 | no_d10_before_flip          |  1030 |                   0    |                       0 |
| P4B          |        1.5 |       2026 | score_unavailable           |     2 |                   0    |                       0 |
| P4B          |        1.5 |       2026 | stopped_after_confirmation  |    47 |                  59.15 |                    2780 |
| P4B          |        1.5 |       2026 | stopped_before_confirmation |  1686 |                 nan    |                       0 |

Runner truncation: results/runner_capture.parquet.

## 13. Same-timestamp events

audit/same_timestamp_exit_audit.parquet — flips process at ts_init==close while a same-nominal-timestamp D10 score is only available 1s later, so flips always causally precede; all coincidences logged with callback ordering.

## 14. Matched placebo controls

| real_policy   | placebo_policy   |   stop |   year |   n_real |   n_placebo |   real_ev |   placebo_ev |   ev_diff |   welch_t |   welch_p |   mannwhitney_p |
|:--------------|:-----------------|-------:|-------:|---------:|------------:|----------:|-------------:|----------:|----------:|----------:|----------------:|
| P1            | P4A              |    0.5 |   2025 |    15124 |       14204 |  -19.4995 |      11.885  |  -31.3845 |   -7.3937 |    0      |               0 |
| P1            | P4A              |    0.5 |   2026 |     6052 |        5665 |  -21.9861 |      11.3283 |  -33.3145 |   -4.4394 |    0      |               0 |
| P1            | P4A              |    1   |   2025 |    13044 |       12816 |  -17.9872 |      17.8148 |  -35.802  |   -5.8659 |    0      |               0 |
| P1            | P4A              |    1   |   2026 |     5160 |        5088 |  -21.5872 |      17.6268 |  -39.214  |   -3.7504 |    0.0002 |               0 |
| P1            | P4A              |    1.5 |   2025 |    11990 |       12166 |  -13.666  |      18.3602 |  -32.0262 |   -4.4906 |    0      |               0 |
| P1            | P4A              |    1.5 |   2026 |     4704 |        4789 |  -18.1813 |      29.1898 |  -47.3711 |   -3.7452 |    0.0002 |               0 |
| P3            | P4B              |    0.5 |   2025 |    15124 |       14970 |  -18.6145 |      10.2442 |  -28.8586 |   -7.7237 |    0      |               0 |
| P3            | P4B              |    0.5 |   2026 |     6052 |        5949 |  -20.4453 |      12.513  |  -32.9583 |   -4.9203 |    0      |               0 |
| P3            | P4B              |    1   |   2025 |    13044 |       13897 |  -19.1195 |      14.0876 |  -33.2071 |   -6.329  |    0      |               0 |
| P3            | P4B              |    1   |   2026 |     5160 |        5542 |  -20.4409 |      16.5608 |  -37.0017 |   -4.1535 |    0      |               0 |
| P3            | P4B              |    1.5 |   2025 |    11990 |       13402 |  -17.553  |      14.415  |  -31.968  |   -5.3085 |    0      |               0 |
| P3            | P4B              |    1.5 |   2026 |     4704 |        5321 |  -14.5855 |      22.7796 |  -37.365  |   -3.562  |    0.0004 |               0 |

## 15. Tail dependence

| run_policy   |   run_stop |   run_year |     n |   net_total |   net_excl_top1 |   net_excl_top5 |   net_excl_top10 |   net_excl_top_decile |   top_decile_share |
|:-------------|-----------:|-----------:|------:|------------:|----------------:|----------------:|-----------------:|----------------------:|-------------------:|
| P1           |        0.5 |       2025 | 15124 |     -294910 |         -301705 |         -325715 |          -348570 |          -1.19964e+06 |              -3.07 |
| P1           |        0.5 |       2026 |  6052 |     -133060 |         -141815 |         -163330 |          -181800 |     -575775           |              -3.33 |
| P1           |        1   |       2025 | 13044 |     -234625 |         -249435 |         -283285 |          -312170 |          -1.40263e+06 |              -4.98 |
| P1           |        1   |       2026 |  5160 |     -111390 |         -120145 |         -145875 |          -168580 |     -658515           |              -4.91 |
| P1           |        1.5 |       2025 | 11990 |     -163855 |         -178665 |         -216865 |          -247925 |          -1.43423e+06 |              -7.75 |
| P1           |        1.5 |       2026 |  4704 |      -85525 |          -94280 |         -120025 |          -143655 |     -659650           |              -6.71 |
| P3           |        0.5 |       2025 | 15124 |     -281525 |         -288320 |         -311070 |          -331215 |          -1.09962e+06 |              -2.91 |
| P3           |        0.5 |       2026 |  6052 |     -123735 |         -132490 |         -150300 |          -166515 |     -533130           |              -3.31 |
| P3           |        1   |       2025 | 13044 |     -249395 |         -264205 |         -298055 |          -325395 |          -1.23184e+06 |              -3.94 |
| P3           |        1   |       2026 |  5160 |     -105475 |         -114230 |         -136425 |          -155710 |     -576450           |              -4.47 |
| P3           |        1.5 |       2025 | 11990 |     -210460 |         -225270 |         -258905 |          -286245 |          -1.24312e+06 |              -4.91 |
| P3           |        1.5 |       2026 |  4704 |      -68610 |          -77365 |         -100060 |          -120685 |     -564410           |              -7.23 |

## 16. Failure modes

- Regimes never reaching D10 (measured in §7) make the opposite flip the load-bearing fallback exit.
- Score coverage stops at regime age 1800s (upstream atlas cap): long regimes cannot produce D10 entries or exits beyond 30 minutes (`truncated_1800s` counts).
- NT stop fills are optimistic on gap-through bars; primary economics reprice them (counts per cell in §10).

## 17. Decision recommendation

**CLOSE** under the pre-registered rules: CONTINUE requires positive EV lift vs P0 in BOTH years AND beating the matched placebo (Welch p<0.05) in both years AND surviving top-decile removal, for at least one policy/stop cell. Qualification scan:
| policy   |   stop |   lift_2025 |   lift_2026 |   ev_2025 |   ev_2026 | lift_both_years_positive   | net_ev_positive_both_years   | beats_placebo_both_years   | survives_top_decile_removal   | qualifies   |   min_year_lift |
|:---------|-------:|------------:|------------:|----------:|----------:|:---------------------------|:-----------------------------|:---------------------------|:------------------------------|:------------|----------------:|
| P1       |    0.5 |       -8.28 |       11.69 |    -19.5  |    -21.99 | False                      | False                        | False                      | False                         | False       |           -8.28 |
| P1       |    1   |       -6.77 |       12.09 |    -17.99 |    -21.59 | False                      | False                        | False                      | False                         | False       |           -6.77 |
| P1       |    1.5 |       -2.45 |       15.5  |    -13.67 |    -18.18 | False                      | False                        | False                      | False                         | False       |           -2.45 |
| P3       |    0.5 |       -7.4  |       13.23 |    -18.61 |    -20.45 | False                      | False                        | False                      | False                         | False       |           -7.4  |
| P3       |    1   |       -7.9  |       13.24 |    -19.12 |    -20.44 | False                      | False                        | False                      | False                         | False       |           -7.9  |
| P3       |    1.5 |       -6.34 |       19.09 |    -17.55 |    -14.59 | False                      | False                        | False                      | False                         | False       |           -6.34 |
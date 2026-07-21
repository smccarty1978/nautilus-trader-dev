# Established Regime Weakness Fade — Final Report

## Decisions

- Stage 1: `ESTABLISHED_REGIME_FILTER_FOUND`
- Stage 2: `NO_MONETIZABLE_WEAKNESS_FADE`

This is a **1-second OHLC research simulation**, not NT-native executable validation and not deployable.

Stage 1 found a causal persistence signature (`ESTABLISHED_REGIME_FILTER_FOUND`). Winner-versus-failed-runner duration ratios were 2.30x in discovery and 2.30x in 2025; peak-MFE ratios were 2.70x and 2.71x; retained-MFE differences at flip-minus-60s were 0.457 and 0.449; paired terminal W4 rises were 0.133 and 0.201. That justified this one frozen monetization test; it did not make the retrospective cohort label tradable.

## Frozen policy

- Established regime: age >= 120s, running MFE >= 1.0 ATR, at least 2 distinct progress windows, retained MFE ratio >= 0.50.
- Trigger: first valid W4 crossing from below 0.618327857739 while the filter is true.
- Entry: fade prevailing regime at explicit next available 1s open after score availability.
- Stop: exactly 1.5 ATR from fill, active on the entry bar.
- Exit: hold through the aligning flip; exit at the next flip against the countertrade.
- Costs: $10.00 round trip; net is decisive.

## Results

| segment        | segment_value   |   trade_count |   censored_count |   mean_gross_pnl_usd |   mean_net_pnl_usd |   total_net_pnl_usd |   win_rate |   profit_factor |   stop_out_rate |   median_hold_s |
|:---------------|:----------------|--------------:|-----------------:|---------------------:|-------------------:|--------------------:|-----------:|----------------:|----------------:|----------------:|
| year           | 2025            |          2103 |                0 |               15.111 |              5.111 |           10748.746 |      0.308 |           1.034 |           0.429 |         498.000 |
| 2025_direction | short           |          2080 |                0 |               13.114 |              3.114 |            6477.056 |      0.307 |           1.021 |           0.431 |         493.500 |
| 2025_direction | long            |            23 |                0 |              195.726 |            185.726 |            4271.689 |      0.391 |           2.161 |           0.261 |         904.000 |
| 2025_session   | ETH             |          1422 |                0 |                2.314 |             -7.686 |          -10929.562 |      0.295 |           0.933 |           0.439 |         473.500 |
| 2025_session   | RTH             |           681 |                0 |               41.833 |             31.833 |           21678.307 |      0.336 |           1.142 |           0.408 |         535.000 |
| year           | 2026            |           876 |                0 |               -2.429 |            -12.429 |          -10887.435 |      0.329 |           0.931 |           0.425 |         534.000 |
| 2026_direction | short           |           846 |                0 |                2.157 |             -7.843 |           -6634.794 |      0.332 |           0.956 |           0.424 |         539.000 |
| 2026_direction | long            |            30 |                0 |             -131.755 |           -141.755 |           -4252.641 |      0.233 |           0.487 |           0.433 |         441.000 |
| 2026_session   | ETH             |           599 |                0 |               12.783 |              2.783 |            1667.158 |      0.339 |           1.020 |           0.426 |         520.000 |
| 2026_session   | RTH             |           277 |                0 |              -35.323 |            -45.323 |          -12554.593 |      0.307 |           0.832 |           0.422 |         554.000 |

## Exit reasons

|   year | exit_reason                        |   count |
|-------:|:-----------------------------------|--------:|
|   2025 | opposite_flip_against_countertrade |    1201 |
|   2025 | stop_after_flip                    |     124 |
|   2025 | stop_before_flip                   |     778 |
|   2026 | opposite_flip_against_countertrade |     504 |
|   2026 | stop_after_flip                    |      56 |
|   2026 | stop_before_flip                   |     316 |

## Candidate skips

|   year | reason                                |   count |
|-------:|:--------------------------------------|--------:|
|   2025 | decision_while_position_open          |      16 |
|   2025 | next_open_at_or_after_confirming_flip |       4 |
|   2026 | decision_while_position_open          |       8 |
|   2026 | next_open_at_or_after_confirming_flip |       1 |

## Explicit next-open delays

|   year | delay_class         |   count |   max_delay_s |
|-------:|:--------------------|--------:|--------------:|
|   2025 | exact_boundary_open |    1514 |           0.0 |
|   2025 | short_gap_1_to_60s  |     589 |          39.0 |
|   2026 | exact_boundary_open |     667 |           0.0 |
|   2026 | short_gap_1_to_60s  |     209 |          21.0 |

The longest 2025 delay was 39s across a documented data/session gap; the entry still preceded the confirming flip or it would have been skipped by contract. 2026's maximum was 21s.

## Scheduled exit next-open delays

|   year |   scheduled_exit_count |   exact_boundary_count |   delayed_count |   max_exit_delay_s |
|-------:|-----------------------:|-----------------------:|----------------:|-------------------:|
| 2025.0 |                 1201.0 |                  900.0 |           301.0 |           189900.0 |
| 2026.0 |                  504.0 |                  389.0 |           115.0 |           176400.0 |

Flip exits use the **next available** 1-second open after the exit decision, not a guaranteed same-timestamp boundary bar. Weekend/session closures delayed 301 scheduled exits in 2025 (maximum 189,900s) and 115 in 2026 (maximum 176,400s); these delayed fills are included in the reported PnL.

## Reconciliation

- Policy hash: `e290fe0726a309295b930eaeeba6cc491fd68cb21c186fd05cb4d55529fc8e7d`
- Candidate accounting residual: 0 in both years; blocking errors: 0.
- Gross and net PnL reconciliation maximum absolute error: 0.
- No 2026 value altered the filter, W4 trigger, 1.5 ATR stop, exit, or costs.
- The immutable policy rationale text recorded a preliminary 2025 time-to-1-ATR median of 139s before the audited regime-direction source repair; the corrected value is 142s. The 120s rule was derived from the unchanged 2021-2024 median of 137s, so no policy parameter changed.

## Contract limitations

Intrabar touch ordering is not claimed. There is no profit target, so no same-bar stop/target tie exists. A scheduled flip exit fills at the next available 1-second open after its decision; on that fill bar the market exit has priority before the bar's intrabar range. All earlier bars, including the entry bar, are stop-active. Tick/quote fill accuracy is not claimed.

---

## Post-completion-audit disclosure: direction asymmetry attribution

Entries are ~99% short (2025: 2,080 short vs 23 long; 2026: 846 vs 30).
The completion audit traced this to the frozen W4 model, NOT the
established-trend filter: the filter-qualifying regime population is
roughly balanced (~50/50; ~58/42 under a near-filter proxy), but W4 scores
are strongly direction-asymmetric (2025 mean checkpoint score 0.366 for
long-prevailing regimes vs 0.190 for short-prevailing), so the
threshold-crossing trigger fires overwhelmingly inside bullish prevailing
regimes. The strategy as frozen is therefore effectively a systematic
"short NQ after established strength" policy. Long-side cells (n=23, n=30)
are unpowered — PF swings 2.16 -> 0.49 across years — and support no
directional claim. This asymmetry is a property of the reused weakness
model's calibration and should be treated as a design input for any future
weakness-model work, not as evidence of a short edge.

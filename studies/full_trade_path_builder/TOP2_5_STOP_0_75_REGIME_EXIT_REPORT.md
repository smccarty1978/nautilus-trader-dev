# Top 2.5% First-Signal Entries With 0.75 ATR Stop

## Executive summary

This study covers **5,836 canonical selected first signals**, one Top-2.5%
entry per qualifying regime. It does not represent all 69,432 qualifying model
observations because 63,596 later observations do not have entry-anchored paths.

- Stopped before confirmation: **2,528 (43.32%)**
- Reached confirmation: **3,299 (56.53% of all entries)**
- Stopped after confirmation: **1,511 (25.89%)**
- Opposing-flip profit: **1,215 (20.82%)**
- Opposing-flip loss: **504 (8.64%)**
- Opposing-flip flat: **15 (0.26%)**
- Censored or ambiguous: **63 (1.08%)**

## Methodology

The population is the builder's frozen selected first signal using probability
threshold 0.5697449423968936 for bullish-fade shorts and 0.5641320087327389
for bearish-fade longs. Entry is `checkpoint_reference_price`; risk
normalization is frozen `atr_at_entry`.

A stop touch is detected from the completed one-second bar high/low through
`adverse_intrabar_extreme_atr <= -0.75`. The exit fills at the following path
bar's open, with that bar's open timestamp. The trigger price is not credited.
Same-bar competing stop and regime events are ambiguous. A final-bar stop touch
without a following open is censored. The stop remains active after
confirmation. Survivors use the canonical opposing confirmed flip mark.
Returns within 0.125 NQ points of zero are flat.

MFE and MAE are directionally normalized by entry ATR. Stopped-trade excursion
ends on the touch bar; its OHLC cannot reveal whether the favorable or adverse
extreme happened first within that second.

## Pooled results

| Outcome | N | % all | Mean return ATR | Median return ATR | Median MFE ATR | MFE p90 ATR |
| --- | --- | --- | --- | --- | --- | --- |
| AMBIGUOUS EVENT ORDER | 9 | 0.154 | — | — | 1.304 | 1.617 |
| CENSORED / UNRESOLVED | 54 | 0.925 | — | — | 3.798 | 10.462 |
| REGIME-FLIP EXIT FLAT | 15 | 0.257 | 0.000 | -0.000 | 2.179 | 3.431 |
| REGIME-FLIP EXIT FOR LOSS | 504 | 8.636 | -0.336 | -0.330 | 1.611 | 2.456 |
| REGIME-FLIP EXIT FOR PROFIT | 1215 | 20.819 | 2.238 | 1.442 | 3.735 | 7.928 |
| STOPPED AFTER CONFIRMATION | 1511 | 25.891 | -0.755 | -0.747 | 0.833 | 1.690 |
| STOPPED BEFORE CONFIRMATION | 2528 | 43.317 | -0.761 | -0.755 | 0.212 | 0.728 |

## Model and direction

| Model | Direction | Outcome | N | % population | Mean return ATR | Median MFE ATR |
| --- | --- | --- | --- | --- | --- | --- |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | AMBIGUOUS EVENT ORDER | 4 | 0.069 | — | 1.211 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | CENSORED / UNRESOLVED | 19 | 0.326 | — | 3.972 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | REGIME-FLIP EXIT FLAT | 8 | 0.137 | 0.000 | 2.417 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | REGIME-FLIP EXIT FOR LOSS | 297 | 5.089 | -0.336 | 1.627 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | REGIME-FLIP EXIT FOR PROFIT | 670 | 11.480 | 2.320 | 4.004 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | STOPPED AFTER CONFIRMATION | 891 | 15.267 | -0.758 | 0.815 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | STOPPED BEFORE CONFIRMATION | 1440 | 24.674 | -0.760 | 0.212 |
| LONG_STRICT_top25_gbt_v2 | LONG | AMBIGUOUS EVENT ORDER | 5 | 0.086 | — | 1.304 |
| LONG_STRICT_top25_gbt_v2 | LONG | CENSORED / UNRESOLVED | 35 | 0.600 | — | 3.574 |
| LONG_STRICT_top25_gbt_v2 | LONG | REGIME-FLIP EXIT FLAT | 7 | 0.120 | 0.000 | 1.806 |
| LONG_STRICT_top25_gbt_v2 | LONG | REGIME-FLIP EXIT FOR LOSS | 207 | 3.547 | -0.335 | 1.580 |
| LONG_STRICT_top25_gbt_v2 | LONG | REGIME-FLIP EXIT FOR PROFIT | 545 | 9.339 | 2.138 | 3.495 |
| LONG_STRICT_top25_gbt_v2 | LONG | STOPPED AFTER CONFIRMATION | 620 | 10.624 | -0.749 | 0.870 |
| LONG_STRICT_top25_gbt_v2 | LONG | STOPPED BEFORE CONFIRMATION | 1088 | 18.643 | -0.762 | 0.212 |

The complete machine-readable evidence also contains separate year, model, and
direction tables.

## Confirmation and post-confirmation funnels

Of all entries, 2,528 stopped before
confirmation. Among resolved confirmation survivors, 1,511
later stopped, while 1,215 exited profitably,
504 exited at a loss, and
15 exited flat.

## Interpretation

The fixed stop prevented 43.32% of the
first-signal population from reaching confirmation. Another
25.89% stopped after confirmation. Profitable opposing
flip exits were more frequent than losing opposing flip exits, but losing exits
still commonly experienced favorable movement first; their pooled median MFE
was 1.611 ATR.
Profitable flip exits had pooled median MFE
3.735 ATR.
These are descriptive results and do not select or recommend a policy.

## Validation and limitations

- 5,836 unique summaries and mutually exclusive outcomes reconciled exactly.
- All path timestamps and sequences passed ordering checks.
- Fixed-seed independent replay: 100 trades, 0 classification mismatches.
- Causal lint: 0 critical, 0 warnings.
- Results apply only to the first qualifying signal per regime.
- One-second OHLC cannot resolve intrabar extreme ordering.
- Transaction costs are not included.
- Censored and ambiguous trades are excluded from realized-outcome inference.

## Final verdict

RESULTS VALID WITH LIMITATIONS

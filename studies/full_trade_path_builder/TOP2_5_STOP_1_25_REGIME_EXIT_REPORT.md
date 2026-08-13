# Top 2.5% First-Signal Entries With 1.25 ATR Stop

## Executive summary

This study covers **5,836 canonical selected first signals**, one Top-2.5%
entry per qualifying regime. It does not represent all 69,432 qualifying model
observations because 63,596 later observations do not have entry-anchored paths.

- Stopped before confirmation: **1,855 (31.79%)**
- Reached confirmation: **3,967 (67.97% of all entries)**
- Stopped after confirmation: **861 (14.75%)**
- Opposing-flip profit: **1,631 (27.95%)**
- Opposing-flip loss: **1,357 (23.25%)**
- Opposing-flip flat: **20 (0.34%)**
- Censored or ambiguous: **112 (1.92%)**

## Methodology

The population is the builder's frozen selected first signal using probability
threshold 0.5697449423968936 for bullish-fade shorts and 0.5641320087327389
for bearish-fade longs. Entry is `checkpoint_reference_price`; risk
normalization is frozen `atr_at_entry`.

A stop touch is detected from the completed one-second bar high/low through
`adverse_intrabar_extreme_atr <= -1.25`. The exit fills at the following path
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
| AMBIGUOUS EVENT ORDER | 14 | 0.240 | — | — | 1.066 | 1.894 |
| CENSORED / UNRESOLVED | 98 | 1.679 | — | — | 3.233 | 8.813 |
| REGIME-FLIP EXIT FLAT | 20 | 0.343 | 0.000 | -0.000 | 2.222 | 3.431 |
| REGIME-FLIP EXIT FOR LOSS | 1357 | 23.252 | -0.591 | -0.588 | 1.360 | 2.332 |
| REGIME-FLIP EXIT FOR PROFIT | 1631 | 27.947 | 2.239 | 1.471 | 3.757 | 7.928 |
| STOPPED AFTER CONFIRMATION | 861 | 14.753 | -1.273 | -1.252 | 0.770 | 1.667 |
| STOPPED BEFORE CONFIRMATION | 1855 | 31.785 | -1.258 | -1.254 | 0.252 | 0.801 |

## Model and direction

| Model | Direction | Outcome | N | % population | Mean return ATR | Median MFE ATR |
| --- | --- | --- | --- | --- | --- | --- |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | AMBIGUOUS EVENT ORDER | 8 | 0.137 | — | 1.214 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | CENSORED / UNRESOLVED | 48 | 0.822 | — | 3.318 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | REGIME-FLIP EXIT FLAT | 10 | 0.171 | 0.000 | 2.524 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | REGIME-FLIP EXIT FOR LOSS | 823 | 14.102 | -0.597 | 1.352 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | REGIME-FLIP EXIT FOR PROFIT | 907 | 15.541 | 2.281 | 3.990 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | STOPPED AFTER CONFIRMATION | 490 | 8.396 | -1.271 | 0.732 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | STOPPED BEFORE CONFIRMATION | 1043 | 17.872 | -1.253 | 0.254 |
| LONG_STRICT_top25_gbt_v2 | LONG | AMBIGUOUS EVENT ORDER | 6 | 0.103 | — | 0.787 |
| LONG_STRICT_top25_gbt_v2 | LONG | CENSORED / UNRESOLVED | 50 | 0.857 | — | 3.233 |
| LONG_STRICT_top25_gbt_v2 | LONG | REGIME-FLIP EXIT FLAT | 10 | 0.171 | 0.000 | 2.131 |
| LONG_STRICT_top25_gbt_v2 | LONG | REGIME-FLIP EXIT FOR LOSS | 534 | 9.150 | -0.581 | 1.362 |
| LONG_STRICT_top25_gbt_v2 | LONG | REGIME-FLIP EXIT FOR PROFIT | 724 | 12.406 | 2.187 | 3.540 |
| LONG_STRICT_top25_gbt_v2 | LONG | STOPPED AFTER CONFIRMATION | 371 | 6.357 | -1.276 | 0.801 |
| LONG_STRICT_top25_gbt_v2 | LONG | STOPPED BEFORE CONFIRMATION | 812 | 13.914 | -1.263 | 0.250 |

The complete machine-readable evidence also contains separate year, model, and
direction tables.

## Confirmation and post-confirmation funnels

Of all entries, 1,855 stopped before
confirmation. Among resolved confirmation survivors, 861
later stopped, while 1,631 exited profitably,
1,357 exited at a loss, and
20 exited flat.

## Interpretation

The fixed stop prevented 31.79% of the first-signal population from reaching
confirmation. Another 14.75% stopped after confirmation. Profitable opposing
flip exits were more frequent than losing opposing flip exits, but losing exits
still commonly experienced favorable movement first; their pooled median MFE
was 1.360 ATR.
Profitable flip exits had pooled median MFE
3.757 ATR.
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

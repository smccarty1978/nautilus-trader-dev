# Top 2.5% First-Signal Entries With 1.00 ATR Stop

## Executive summary

This study covers **5,836 canonical selected first signals**, one Top-2.5%
entry per qualifying regime. It does not represent all 69,432 qualifying model
observations because 63,596 later observations do not have entry-anchored paths.

- Stopped before confirmation: **2,149 (36.82%)**
- Reached confirmation: **3,673 (62.94% of all entries)**
- Stopped after confirmation: **1,209 (20.72%)**
- Opposing-flip profit: **1,464 (25.09%)**
- Opposing-flip loss: **905 (15.51%)**
- Opposing-flip flat: **17 (0.29%)**
- Censored or ambiguous: **92 (1.58%)**

## Methodology

The population is the builder's frozen selected first signal using probability
threshold 0.5697449423968936 for bullish-fade shorts and 0.5641320087327389
for bearish-fade longs. Entry is `checkpoint_reference_price`; risk
normalization is frozen `atr_at_entry`.

A stop touch is detected from the completed one-second bar high/low through
`adverse_intrabar_extreme_atr <= -1.00`. The exit fills at the following path
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
| AMBIGUOUS EVENT ORDER | 14 | 0.240 | — | — | 0.822 | 1.462 |
| CENSORED / UNRESOLVED | 78 | 1.337 | — | — | 3.528 | 8.963 |
| REGIME-FLIP EXIT FLAT | 17 | 0.291 | 0.000 | 0.000 | 2.193 | 3.153 |
| REGIME-FLIP EXIT FOR LOSS | 905 | 15.507 | -0.466 | -0.468 | 1.494 | 2.409 |
| REGIME-FLIP EXIT FOR PROFIT | 1464 | 25.086 | 2.221 | 1.418 | 3.727 | 7.943 |
| STOPPED AFTER CONFIRMATION | 1209 | 20.716 | -1.013 | -0.998 | 0.808 | 1.658 |
| STOPPED BEFORE CONFIRMATION | 2149 | 36.823 | -1.007 | -1.001 | 0.234 | 0.764 |

## Model and direction

| Model | Direction | Outcome | N | % population | Mean return ATR | Median MFE ATR |
| --- | --- | --- | --- | --- | --- | --- |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | AMBIGUOUS EVENT ORDER | 7 | 0.120 | — | 1.295 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | CENSORED / UNRESOLVED | 35 | 0.600 | — | 3.570 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | REGIME-FLIP EXIT FLAT | 8 | 0.137 | 0.000 | 2.417 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | REGIME-FLIP EXIT FOR LOSS | 543 | 9.304 | -0.469 | 1.501 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | REGIME-FLIP EXIT FOR PROFIT | 807 | 13.828 | 2.264 | 3.972 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | STOPPED AFTER CONFIRMATION | 713 | 12.217 | -1.009 | 0.810 |
| BULLISH_STRICT_top25_gbt_v2 | SHORT | STOPPED BEFORE CONFIRMATION | 1216 | 20.836 | -1.003 | 0.238 |
| LONG_STRICT_top25_gbt_v2 | LONG | AMBIGUOUS EVENT ORDER | 7 | 0.120 | — | 0.539 |
| LONG_STRICT_top25_gbt_v2 | LONG | CENSORED / UNRESOLVED | 43 | 0.737 | — | 3.419 |
| LONG_STRICT_top25_gbt_v2 | LONG | REGIME-FLIP EXIT FLAT | 9 | 0.154 | 0.000 | 2.123 |
| LONG_STRICT_top25_gbt_v2 | LONG | REGIME-FLIP EXIT FOR LOSS | 362 | 6.203 | -0.462 | 1.482 |
| LONG_STRICT_top25_gbt_v2 | LONG | REGIME-FLIP EXIT FOR PROFIT | 657 | 11.258 | 2.168 | 3.502 |
| LONG_STRICT_top25_gbt_v2 | LONG | STOPPED AFTER CONFIRMATION | 496 | 8.499 | -1.018 | 0.804 |
| LONG_STRICT_top25_gbt_v2 | LONG | STOPPED BEFORE CONFIRMATION | 933 | 15.987 | -1.013 | 0.233 |

The complete machine-readable evidence also contains separate year, model, and
direction tables.

## Confirmation and post-confirmation funnels

Of all entries, 2,149 stopped before
confirmation. Among resolved confirmation survivors, 1,209
later stopped, while 1,464 exited profitably,
905 exited at a loss, and
17 exited flat.

## Interpretation

The fixed stop prevented 36.82% of the
first-signal population from reaching confirmation. Another
20.72% stopped after confirmation. Profitable opposing
flip exits were more frequent than losing opposing flip exits, but losing exits
still commonly experienced favorable movement first; their pooled median MFE
was 1.494 ATR.
Profitable flip exits had pooled median MFE
3.727 ATR.
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

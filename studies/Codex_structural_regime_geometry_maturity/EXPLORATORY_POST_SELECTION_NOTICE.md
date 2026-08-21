# Exploratory-only result notice

This document labels the currently materialized A/B results as **exploratory
only**. They must not be treated as an untouched 2024 out-of-sample result,
used for model selection, promoted, or exported as accepted research.

Reason: both baseline feature lists resolve to `F3_top25_gbt_v1`, whose
candidate universe was selected using 2025 outcome labels. The 2024 score
comparison is consequently post-selection contaminated. Causal Pass 11 and
Contract Pass 10 block the accepted-study workflow.

The corrected RTH-only structural collection, timestamp handling, and the
directional A/B mechanics remain useful implementation evidence. A valid
acceptance study requires an independently constructed pre-2024 candidate
feature universe, a new train-only Top-25 freeze, and fresh audited fitting.

## Diagnostic readout only

The contaminated comparison shows no broad, stable classification improvement:

| Direction | 300-600s | 600-900s | 900-1800s | >=1800s |
|---|---:|---:|---:|---:|
| SHORT B-A AUC | +0.0040 | +0.0008 | -0.0019 | -0.0032 |
| LONG B-A AUC | -0.0016 | +0.0057 | -0.0013 | -0.0050 |

This pattern is a weak research lead—possibly localized to SHORT 300-600s and
LONG 600-900s—not evidence that the structural family is useful. Crossing
economics are mixed, so this notice makes no deployment recommendation.

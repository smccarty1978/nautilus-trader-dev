# STUDY REPORT -- clean_maturity_flip_model_180s_horizon

**Stage 17 research decision.**  Execution composite `09b5c66db8ec72bbf05f539c6a877dc8c9198774f4c4b7117fdea72fd618f48a` ·
seal LOCKED · causal pass 17 + contract pass
16 CLEAR.

## Lineage

| | |
|---|---|
| refreshed TRAIN freeze | `26c1b0c958155b8edb403312a61518e720a7f1b96981b064c788dc9ebfafe7a7` |
| LONG_C model_id | `ccd587dfed77d1c87029bcd779abb1f6b70fa63beab5c99f5439653746963b0c` |
| SHORT_C model_id | `209da0ff0c922e02ab02f78408d0591bd0b2e762a71ecd3ed010856ca45051e6` |
| modeling execution closure | `fb4183e49b1223fb5511e92f9b6977a3e1f19f697311ba5b0d3fb637a20d9bda` |
| authorization | `19534de9bec8932da8b5b690c892bb4ea4324741865cae208c0270c8c0dd30fb` (unchanged) |
| OOS reconciliation identity | `9a713d1a11b3e8471ef0fc72fedad5baa840f79700534f630fc4830ee7bc277b` |
| OOS reconciled authority identity | `7174bd6885ddef470374c80a03b7a758735b884424e6e720acecb1df820ac21e` |
| Stage-16 analysis identity | `9f4c29e30699bb496575b5488191a944f7e0d6155c69a35e1e91332d5c625382` (FRESH) |

The 2024 OOS run predates the Red-Team Pass 1 framework merge / driver declaration. Its
outputs were proven **numerically identical** under the refreshed lineage (predict_proba
delta 0.0 over all 450,973 rows; identical model bytes, thresholds, features, target,
authorization) and reused via `oos_lineage_reconciliation.json` -- no recollection, no
rescoring. Historical OOS artifacts were not mutated.

## Result

**Selection:** LONG and SHORT both PASS at arm C
(`BASELINE_PLUS_STRUCTURAL_PLUS_ROLLING_5M`); concordant; neither hit the 2023 reject-only
D gate.

**Classification (primary axis) -- IMPROVED, OOS-replicated.** 2024 checkpoint-level:
LONG_C ROC-AUC 0.6915 / PR-AUC 0.2958
(1.82x base) vs frozen 300s parent 0.6398 /
0.4046; SHORT_C 0.6746 / 0.2441
(1.77x base) vs 0.6282 /
0.3415. ROC-AUC delta 180s-300s: LONG +0.0517,
SHORT +0.0464; the TRAIN->OOS relationship replicates.
Calibration ECE < 0.01 (LONG).

**Economics / actionable signal (secondary axis) -- NOT ESTABLISHED.** At the frozen P90
tail the 2024 forward-path `return_atr` is ~0 for both 180s and 300s; the 180s window
truncates ~0.25 ATR of eventual favourable excursion. The regime-level / first-fire signal
(March 2024, first-eligible-per-regime) is at chance: LONG ROC-AUC
0.4954.

## Terminal decision: **MIXED**

The 180s horizon delivers a real, out-of-sample-replicated **classifier** improvement but
**no economic or actionable improvement**. The compound research question (better classifier
*and* better economics) is not satisfied.

**Not promoted.** High checkpoint-level AUC != PnL discrimination; the frozen 180s models
are a non-monetizable diagnostic result. Any pursuit of the economic axis needs a separate,
separately-frozen Study 2/3 against an economic-quality target -- not a change to this
classifier.

## Not done (prohibited)

No new 2024 collection, no new 2024 scoring, no model / threshold / feature / target change,
no new OOS optimization. 2025/2026 not accessed.

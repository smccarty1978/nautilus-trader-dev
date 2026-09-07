# ES 180s Model C portability — analysis decision

**Terminal decision: `PORTABILITY_CONFIRMED_TAIL_AND_STRUCTURE_UNPROVEN`**

The frozen NQ 180s Model C architecture — the same 13 semantic features, the same
direction-specific LightGBM hyperparameters, no tuning, no feature selection — was trained
natively on ES 2020–2023 and evaluated once on untouched ES 2024.

## It transfers, in both directions

| cell | rows | base rate | ROC-AUC | PR-AUC | PR/base lift | Brier |
|---|---|---|---|---|---|---|
| LONG  | 287,264 | 0.1569 | 0.6687 | 0.2742 | 1.75 | 0.1258 |
| SHORT | 226,160 | 0.1761 | 0.6764 | 0.3030 | 1.72 | 0.1367 |

Against the TRAIN expanding-year folds (mean ROC 0.686 LONG / 0.694 SHORT), OOS retains
**97.5% / 97.4%** of ROC-AUC and **96.9% / 94.8%** of PR-lift. SHORT holds marginally better
than LONG. The two cells partition the scored population exactly (287,264 + 226,160 = 513,424
= 516,609 rows − 3,185 censored), and each was authenticated against the canonical model bytes
recorded in the TRAIN freeze before it scored anything.

`NO_MEANINGFUL_PORTABILITY` is excluded outright. `PARTIAL_PORTABILITY` is contradicted by its
own declared text — the transfer is neither materially weaker nor one-sided.

## Why not STRONG_PORTABILITY

`STRONG_PORTABILITY` is a conjunction of four clauses. Two hold (two-sided retained
discrimination; retention comparable to the NQ parent). Two were **never produced**:

* stable lift at the frozen ES TRAIN P90/P95/P97.5 thresholds;
* a learned feature structure of the same character as NQ.

Neither is a negative finding. Neither was measured. Asserting STRONG would overclaim; asserting
PARTIAL would record a two-sided transfer under a label that says it was weak or one-sided. The
vocabulary was widened at close time to state the evidential position exactly.

## What was not established, and why

Platform V2 cannot currently express two things this contract required:

1. **Freeze-time TRAIN percentile thresholds.** `freeze()` writes `thresholds: {}`
   unconditionally. The fit stage derives p90/p95 only on the `month_folds` path, per fold,
   applied to that fold's own validation window — not frozen once over the TRAIN population and
   applied unchanged to OOS, which is what §10/§13 specify. P97.5 is not derived anywhere.
2. **Native feature importance.** No implementation exists in the analysis harness. This leaves
   the study's *secondary* question — whether ES independently learns NQ's structure around
   `ema_slope`, `arrival_velocity` and the rolling retention/giveback/progress family — entirely
   unanswered.

Maturity buckets (§11/§13) and the first-P90 diagnostic (§14) are expressible
(`analysis.decomposition.buckets`, `analysis.anchor.first_threshold_crossing`) but the compiled
plan declared `analysis: null`, so no declarative pipeline ran. Expected calibration error was
not produced; only Brier.

Both platform items are routed as a typed `ANALYSIS_HARNESS_GAP`. Any repair changes the
execution closure and therefore forces recollection, refit, reseal and both audits again.

## Integrity

`new_models_trained: true`; both cells keyed and byte-bound in the freeze
(`primary:LONG` `167f9b5d…`, `primary:SHORT` `230b745e…`), each re-authenticated at OOS against
those exact bytes. No tuning, no feature change, no refit after the freeze. 2024 opened only
through the governed `oos` stage after the freeze; 2025 and 2026 never touched. Every partition
verified against `ES_1S_V2_GLOBEX` digest `9f38a41e`; no NQ row entered ES model fitting.

## Recommended next step

Build the two missing analysis capabilities and re-run, if the tail behaviour and learned feature
structure matter for a deployment decision. The primary portability question does not need it:
the architecture transfers to ES.

# clean_tradable_reversal — Final Study Report

**Status: CLOSED_NOT_SUPPORTED**

## 1. Research question

Among high-confidence Stage-1 flip predictions (frozen `clean_maturity_flip_model_rolling_productivity`
Model C, TRAIN P90 threshold), does information available at the decision timestamp T distinguish
economically clean reversals (target T1) from ugly, weak, or failed ones?

## 2. Target

Composite AND target, `decision_reference: decision_ts`:
- `flip_within_300s` — accepted opposite prevailing 1m regime flip within (T, T+300s]
- `mfe_ge_1p0_atr` — MFE >= 1.0 ATR over the same 300s horizon (`NEXT_BAR_OPEN` entry, `FULLY_FORWARD`, ATR frozen at entry, session-end censored)
- `mae_le_0p5_atr` — MAE <= 0.5 ATR, same horizon

Three-valued AND semantics: any definite-false component short-circuits to NEGATIVE even when
another component is censored; only fully-resolved-positive rows are POSITIVE, unresolved rows
are CENSORED (never coerced negative).

## 3. Population — STAGE2_P90_UPCROSS_V1

Per (direction, regime): strict below→above upcross of the frozen Stage-1 score against its
TRAIN-only P90 threshold (LONG 0.43654834666810594, SHORT 0.4214933537606981), first upcross per
regime, no persistence rule, no cadence resampling. A regime whose first eligible checkpoint is
already at/above threshold is `LEFT_CENSORED_ABOVE_THRESHOLD` and excluded. Defined and frozen
before any TRAIN outcome was seen (git commit `96f914c`, pre-dating all execution in this study).

**TRAIN (2021-2023):** 8,533 total (LONG 3,984, SHORT 4,549). Maturity: LONG 1585/1372/1027
(300-600s/600-900s/900-1800s), SHORT 1765/1551/1233. Left-censored-above-threshold: 58.
Multiple-crossing regimes: 7,161.

## 4. TRAIN target balance (`TRAIN_TARGET_BALANCE_PASS`, PASS)

Overall: eligible 8,533, resolved 8,442, positive 1,687, censored 91 (1.07%). LONG positive rate
20.61%, SHORT 19.44% (ratio 1.06, well within the 3x collapse guard). No vanishing positive
class, no severe LONG/SHORT or maturity-bucket collapse, no pathological censoring.

## 5. Feature surface (predeclared, git commit `96f914c`, before any Stage-2 TRAIN outcome)

- **Arm A** (1): `stage1_model_c_score` only.
- **Arm B** (14): A + the original Stage-1 13 (`prior_1m/5m_regime_efficiency/mfe_atr/range_atr`,
  `rolling_300s_retention_ratio/current_progress_atr/max_progress_atr/giveback_atr`,
  `arrival_velocity`, `arrival_acceleration`, `ema_slope`).
- **Arm C** (21): B + 7 additions (`current_5m_regime_range_atr_per_min`,
  `distance_to_completed_5m_high_atr/low_atr`, `relative_volume`, `est_delta_ratio`,
  `range_position`, `wick_imbalance`).

A TRAIN-comparability investigation confirmed this 21-input surface is a strict superset of
everything the parent Stage-1 study ever collected/authorized/modeled (13/13/13), and that the
narrowing to 21 (vs. the 129-feature canonical registry) was deliberate and predeclared, with a
named `deferred_not_included` list (22-feature `regime_median_center_slope_alignment` family +
2 named features, source-verified against the registry) and an explicit, pre-committed
prohibition on later broadening (`broaden_arm_c_into_a_feature_mining_pass`).

## 6. TRAIN model selection (governed, bounded grid search, lightgbm, seed 42)

Tuning years [2021, 2022] (one walk-forward fold), final confirmatory validation on [2023]
(accept/reject only, no re-search). `final_validation_status: PASS` both directions.

| Direction | Arm | 2023 final-validation ROC | PR | Brier |
|---|---|---|---|---|
| LONG | A | 0.5027 | 0.2168 | 0.1720 |
| LONG | **B (selected)** | **0.5610** | 0.2612 | 0.1682 |
| LONG | C | 0.5634 | 0.2567 | 0.1693 |
| SHORT | **A (selected)** | **0.5400** | 0.2204 | 0.1519 |
| SHORT | B | 0.5217 | 0.2058 | 0.1674 |
| SHORT | C | 0.5144 | 0.1968 | 0.1689 |

TRAIN freeze: `artifacts/train_experiment_freeze.json`,
`freeze_sha256=19e1c1e58790c3bcc16fc681efa9d06ebc1fdae8b2793b60d0bf8b6b06a06cde`.
Model-selection manifest: `artifacts/model_selection_manifest.json`,
`manifest_sha256=1d05933d8f1f80b48e25679d24e3695c8ed4e0b33d144acaadb7fd5f6ba9e7a3`.

## 7. AUC decomposition (frozen Stage-1 Model C only, no fitting)

| | Full Stage-1 population, Y_FLIP | STAGE2_P90_UPCROSS_V1, Y_FLIP | STAGE2_P90_UPCROSS_V1, Y_T1 |
|---|---|---|---|
| LONG ROC | 0.6754 | 0.5237 | 0.5174 |
| SHORT ROC | 0.6768 | 0.5387 | 0.5107 |

Population conditioning (P90-upcross restriction of range) accounts for the large majority of
the AUC drop (LONG -0.152, SHORT -0.138); the target change to T1 adds a smaller secondary
reduction (LONG -0.006, SHORT -0.028). Score std compresses ~4x under conditioning (LONG
0.110->0.026, SHORT 0.107->0.027). No unexplained residual — Stage-2's actual Arm-A TRAIN
results land within the expected range of this decomposition.

## 8. OOS 2024 (one-shot, frozen models, no refitting/recalibration/reselection)

Population: 2,864 total (LONG 1,362, SHORT 1,502); 2,725 in primary maturity buckets. Resolved
T1: 2,698 (LONG 1,265 pos=238, SHORT 1,433 pos=254). Feature/null-rate parity to TRAIN confirmed
(all causal features 0% null except `rolling_300s_*`).

| Direction | Arm | OOS ROC | PR | Brier | TRAIN final-validation ROC | Verdict |
|---|---|---|---|---|---|---|
| LONG | A | 0.5008 | 0.1889 | 0.1546 | 0.5027 | flat/weak both periods |
| LONG | **B (primary)** | **0.4912** | 0.1822 | 0.1565 | 0.5610 | **COLLAPSES** |
| LONG | C (secondary) | 0.5230 | 0.1986 | 0.1562 | 0.5634 | weakens modestly, best of 3 |
| SHORT | **A (primary)** | **0.5157** | 0.1765 | 0.1477 | 0.5400 | weakens modestly |
| SHORT | B | 0.5150 | 0.1938 | 0.1559 | 0.5217 | roughly stable-weak |
| SHORT | C (secondary) | 0.5362 | 0.1973 | 0.1546 | 0.5144 | improves unexpectedly |

**Calibration.** LONG: score-quintile actual T1 rate is non-monotonic (0.174/0.186/0.245/0.158/0.178)
— ranking does not hold. SHORT: weak/partial (0.156/0.172/0.203/0.185/0.168) — mostly monotonic
through the middle, breaks at the top quintile.

**Negative-subtype diagnostic.** The TRAIN finding that different negative failure modes
(FLIP_FAILED / HIGH_MAE_ONLY / LOW_MFE_AND_HIGH_MAE / LOW_MFE_ONLY) are not strongly separated
from each other **replicates** OOS (LONG 0.204-0.217, SHORT 0.165-0.196). The finding that T1
positives score above all negatives **does not replicate**: LONG T1_POSITIVE mean 0.207 and SHORT
0.193 both fall *inside* their respective negative-subtype ranges.

## 9. OOS provenance

OOS opened exactly once via `research_workflow.experiment.assert_oos_open`, with the current
execution composite, TRAIN freeze hash, and model-selection manifest hash all verified live
against their pinned values before any 2024 access. Three mechanical issues were found and fixed
*during and after* OOS collection, all classified **EXTERNAL_RUNNER_ONLY** (confirmed: the
execution composite is byte-identical, `b010f3c7d4599887279c1e988ecb463e23db9b9077047f288cc36244094d7fe9`,
across all three fixes — none touched `generic_collector.py`, the compiled study, the execution
manifest, the seal, or the OOS authorization):

1. The initial direct 2024 collection window included a 5-day warmup tail (31 checkpoints,
   2023-12-27–29) before strict-2024 filtering was applied to every downstream artifact.
2. A direct-construction collection script omitted `feature_requirements`, leaving
   `relative_volume` 100%-null until corrected and the OOS feature collection re-run.
3. **Found after study closure**, while extracting the population-derivation logic into a
   reusable script (`scripts/build_derived_score_upcross_population.py`): the one-off 2024
   population script incorrectly excluded an *entire* regime once its first checkpoint was
   flagged `LEFT_CENSORED_ABOVE_THRESHOLD`. In the authoritative TRAIN definition,
   left-censoring is diagnostic-only — a regime's ambiguous first state can never itself be
   selected, but a genuine later dip-then-recross in that same regime remains a valid,
   observed crossing. Re-verifying the extracted script against the frozen TRAIN population
   (8,533/8,533, exact identity-set match) confirmed TRAIN was unaffected — only the
   independently-written 2024 script had this bug. It dropped 11 of 2,864 real 2024
   identities (~0.4%). The OOS population, features, forward outcomes, targets, and model
   scoring were fully rebuilt against the corrected population; the numbers in this report
   reflect that correction. Effect on conclusions: **none** — every metric moved by ≤0.003
   ROC, all verdicts (COLLAPSES / weak / etc.) are unchanged.

The metrics in this report come only from the corrected, feature-complete, strictly-2024,
correctly-population-derived dataset.

## 10. What this study establishes

- Stage-1 broad flip prediction remains valid and reproducible (frozen Model C in-sample: LONG
  ROC 0.6754, SHORT ROC 0.6768; deterministic refit parity confirmed, correlation >=0.997 all
  6 arms).
- P90-upcross conditioning compresses Stage-1 score variance ~4x.
- Most of the Stage-1 ~0.67 -> Stage-2 ~0.5 AUC reduction is population restriction of range, not
  a modeling defect.
- The T1 target change adds a smaller secondary reduction.
- **The tested Stage-2 causal feature sets (predeclared Arms A/B/C, 21 inputs) do not robustly
  identify clean/tradable reversals among high-confidence Stage-1 upcrosses.**
- This study does **not** establish that no feature in the full 129-feature canonical registry
  could ever help — it only rejects the predeclared 21-input universe actually tested.

## 11. Historical / non-authoritative items (preserved, not deleted)

- **Old 2,702 first-crossing population**: aggregate counts remain valid; row-level selection
  methodology is unrecoverable (driver script absent from git history). Superseded by
  STAGE2_P90_UPCROSS_V1 for this study.
- **Historical ~0.6495/~0.6499 TRAIN temporal-validation ROC figures**: provenance unrecoverable
  — not found in any surviving repaired Stage-1 artifact. Not used as acceptance evidence
  anywhere in this study; classified `HISTORICAL_SESSION_METRIC` / `PROVENANCE_UNRECOVERABLE` /
  `NON_AUTHORITATIVE`.

## 12. Integrity statement

No TRAIN refit, no OOS hyperparameter search, no OOS feature selection, no OOS arm reselection,
no OOS calibration fitting, no threshold changes, no target changes, no population-rule changes.
2025 and 2026 were never accessed. All frozen-model provenance (hashes, seeds, hyperparameters,
feature order) verified live before scoring.

## 13. Allowed next research directions

A **new**, separately predeclared study — not a continuation of this one — motivated by the
Arm-C secondary OOS observation (LONG 0.5230, SHORT 0.5362) or a different Stage-2 feature
hypothesis (e.g. the deferred `regime_median_center_slope_alignment` family), using genuinely
unseen confirmation data. 2024 cannot be reused as untouched OOS for that follow-on hypothesis.

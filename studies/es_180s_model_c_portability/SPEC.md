# es_180s_model_c_portability

Derived from `research_decision.yaml`. Question: # ES 180s MODEL C PORTABILITY STUDY — SUPERVISED PLATFORM V2 RESEARCH CONTRACT

## 0. DESIGN-WORKER BINDING NOTES (read before writing study.yaml)

This document is the RESEARCH CONTRACT. It is authoritative for every semantic decision it
resolves. Where it points at a governed authority instead of stating a value, resolve the value
from that authority — do not infer it from prose here.

Governed authorities to resolve from:

* Parent NQ study (historical, v1 runtime — a REFERENCE, never a template, never recompiled):
  `studies/clean_maturity_flip_model_180s_horizon`
  Relevant artifacts include `artifacts/frozen_feature_manifest.json`,
  `artifacts/preprocessing_manifest.json`, `artifacts/model_manifest.json`,
  `artifacts/train_experiment_freeze_long.json`, `artifacts/train_experiment_freeze_short.json`,
  `artifacts/180S_HORIZON_TRAIN_CARD.json`, `artifacts/2024_OOS_CARD.json`,
  `artifacts/study_closure.json`, `SPEC.md`, `research_decision.yaml`.
* Dataset: `research/datasets/ES_1S_V2_GLOBEX.yaml` (verify via `research data verify ES_1S_V2_GLOBEX`).
* Capability registry: `research cap search` / `research cap describe` — never guess capability ids.

Known-available capabilities relevant to this study (verified on `main` at intake):
`feature.rolling_retention_ratio`, `feature.rolling_current_progress_atr`,
`feature.rolling_max_progress_atr`, `feature.rolling_giveback_atr` — all take a `window`
parameter (bind `window: 300s`). Direction-specific FIXED hyperparameters are expressible
through modeling **cells** (`research_workflow/grammar/spec.py` — a cell carries its own fixed
`params`). Use cells; do NOT emit a bare arm list, and do NOT introduce a tuning search.

**`research_decision.yaml` MUST declare** (the supervisor reads these; without them it will stop
and raise decision cards this contract has already answered):

```yaml
autonomy_decisions:
  platform_merge: auto_if_green
  closed_study_merge: auto_if_clean
  deterministic_defect: auto_fix
  audit_fixable_defect: auto_fix
  frozen_parent_evidence: authenticate_and_reuse_never_retrain
  protected_data: never_broaden_chronology_authority
  long_jobs: detached_no_polling
terminal_decisions:
  # closure vocabulary — the analysis worker may close ONLY with one of these
  STRONG_PORTABILITY: ...
  PARTIAL_PORTABILITY: ...
  NO_MEANINGFUL_PORTABILITY: ...
```

Also declare, in `research_decision.yaml`, the semantic decisions this contract resolves
(horizon boundary, decision epoch, session censoring, population predicates, direction split,
threshold derivation population) so a `SEMANTIC_DECISION_REQUIRED` gap routes to the design
worker rather than to the user.

---

============================================================
1. RESEARCH QUESTION
============================================================

PRIMARY

Does the validated NQ 180-second Model C architecture transfer to ES?

Specifically:

    Train the same 13-feature Model C architecture natively on ES
    using 2020-2023 TRAIN data.

    Freeze the resulting ES LONG and SHORT models and all TRAIN-derived
    thresholds.

    Then evaluate once on untouched ES 2024 OOS.

Question:

    Does ES show meaningful forward discrimination for an imminent
    prevailing 1m regime flip within 180 seconds?

SECONDARY

Does ES independently learn a similar dominant feature structure to NQ,
especially around:

    ema_slope
    arrival_velocity
    rolling retention
    rolling giveback
    rolling current progress

This is a CROSS-INSTRUMENT PORTABILITY study.

It is NOT:

    a combined NQ+ES model
    a feature-discovery study
    a hyperparameter-tuning study
    a strategy/economics study
    a Stage-2 trade-quality study

============================================================
2. SCIENTIFIC AUTHORITIES TO RESOLVE
============================================================

Before final study compilation, resolve from governed repository authority:

PARENT NQ STUDY

    studies/clean_maturity_flip_model_180s_horizon

Resolve and bind:

    exact repaired Model C 13-feature semantic surface
    accepted 180s target semantics
    accepted established-regime population semantics
    accepted decision timestamp semantics
    accepted session/censor semantics
    accepted horizon boundary semantics
    accepted preprocessing semantics
    frozen direction-specific LightGBM hyperparameters

Do not infer these from this question if authoritative parent artifacts
specify them more precisely.

ES DATASET

Expected:

    ES_1S_V2_GLOBEX

Verify through DatasetSpec/registry.

Do not substitute:
    ES V0
    NQ data
    legacy catalogs

unless a governed authority explicitly requires a historical fixture,
which should not be necessary for this study.

============================================================
3. INSTRUMENT / STREAMS
============================================================

Execution instrument:

    ES

Governed dataset:

    ES_1S_V2_GLOBEX

Expected streams/state:

    native 1s execution stream
    completed 1m regime/context
    governed host-derived 5s / 5m state where required by canonical features

Preserve Platform V2:
    completed-bar semantics
    ts_init availability
    same-timestamp rules
    Globex session authority

No NQ rows may enter ES model fitting.

============================================================
4. TARGET
============================================================

Use the SAME SCIENTIFIC TARGET as the accepted NQ 180s Model C parent:

    prevailing 1m regime flip within (T, T+180s]

Direction:

    both populations
    separate LONG and SHORT models

Resolve exact parent semantics for:

    prevailing regime definition
    decision epoch T
    inclusive/exclusive horizon boundary
    session censoring
    confirmation/event semantics
    horizon_end_rule
    entry/reference semantics if applicable

Do not reinterpret or approximate any of these.

============================================================
5. POPULATION
============================================================

Use the SAME established-regime population semantics as the NQ parent.

Expected constraints include:

    regime age >= 120s
    running MFE >= 1.0 ATR
    >= 2 new-progress windows
    retained MFE ratio >= 0.50
    5-second candidate/scoring cadence
    RTH candidate emission
    both prevailing regime directions

Resolve the exact canonical tracker fields and predicates from parent authority.

These thresholds are FIXED.

Do not optimize them for ES.

============================================================
6. EXACT 13-FEATURE MODEL C SURFACE
============================================================

Use exactly the same semantic feature surface as repaired NQ Model C:

1. arrival_velocity
2. arrival_acceleration
3. ema_slope

4. prior completed 1m regime efficiency
5. prior completed 1m regime MFE ATR
6. prior completed 1m regime range ATR

7. prior completed 5m regime efficiency
8. prior completed 5m regime MFE ATR
9. prior completed 5m regime range ATR

10. rolling retention ratio — 300s
11. rolling current progress ATR — 300s
12. rolling max progress ATR — 300s
13. rolling giveback ATR — 300s

Resolve these through canonical Platform V2 FeatureInstance identities
and parameters.

Do NOT:

    add ES-specific features
    add volume
    add delta
    remove features
    perform feature selection
    substitute approximate aliases
    change timing/reset/null semantics

Physical output aliases may be compiler-generated.

============================================================
7. MODEL ARCHITECTURE
============================================================

Model family:

    LightGBM

Train independent:

    LONG
    SHORT

This is FIXED-ARCHITECTURE PORTABILITY.

NO hyperparameter tuning.

Verify the frozen NQ parent parameter authority before binding.

Expected reference parameters:

LONG

    learning_rate = 0.039440343780424526
    max_depth = 5
    n_estimators = 100
    num_leaves = 4
    random_seed = 42
    verbosity = -1

SHORT

    learning_rate = 0.028861842631876633
    max_depth = 5
    n_estimators = 200
    num_leaves = 4
    random_seed = 42
    verbosity = -1

If authoritative parent representation normalizes parameter names,
use the governed equivalent without changing values/semantics.

Scientific purpose:

    isolate architecture/feature portability

Therefore DO NOT:

    Optuna
    random search
    grid search
    ES-specific architecture selection
    calibration unless parent Model C explicitly requires it

If fixed direction-specific model parameterization is not expressible,
allow the supervisor to route the resulting typed Platform V2 capability gap.

Do not ask the user unless the missing capability requires a genuine
scientific decision.

============================================================
8. CHRONOLOGY
============================================================

TRAIN:

    2020
    2021
    2022
    2023

TRUE OOS:

    2024

PROHIBITED:

    2025
    2026

Hard chronology invariant:

2024 must not influence:

    feature definition
    feature selection
    preprocessing
    fitting
    calibration
    model selection
    architecture
    hyperparameters
    threshold derivation

2024 opens only after:

    LONG model frozen
    SHORT model frozen
    preprocessing frozen
    feature order frozen
    TRAIN thresholds frozen
    lineage/freeze checks passed

2025 and 2026 must remain untouched.

============================================================
9. TRAINING PROTOCOL
============================================================

Fit:

    LONG:
        ES 2020-2023 eligible LONG rows

    SHORT:
        ES 2020-2023 eligible SHORT rows

Use fixed architecture only.

Freeze before OOS:

    estimator/model bytes
    model_id
    canonical artifact hashes
    feature order/hash
    preprocessing identity/hash
    fixed hyperparameters
    random seed
    TRAIN threshold artifacts
    golden score fixture
    stage-scoped execution lineage

No retraining after OOS opens.

============================================================
10. TRAIN-DERIVED SCORE THRESHOLDS
============================================================

Derive separately by direction from ES TRAIN scores only:

    P90
    P95
    P97.5

Transfer the percentile DEFINITIONS from NQ.

Do NOT transfer NQ numerical score thresholds.

Each ES threshold must prove:

    derivation_population = TRAIN

Apply these frozen ES thresholds unchanged to 2024.

============================================================
11. TRAIN DIAGNOSTICS
============================================================

Report separately LONG / SHORT:

Population:

    checkpoint/candidate rows
    unique regimes
    target base rate

Classification:

    ROC-AUC
    PR-AUC
    PR-AUC / base-rate lift
    Brier
    supported calibration diagnostics

At TRAIN-derived:

    P90
    P95
    P97.5

report:

    retained fraction
    flip-within-180s rate
    precision lift versus TRAIN base rate
    median seconds-to-flip

Maturity buckets where populated:

    0-300s
    300-600s
    600-900s
    900-1800s
    >=1800s

Keep checkpoint counts and unique-regime counts distinct.

============================================================
12. FEATURE IMPORTANCE
============================================================

After TRAIN freeze, report native LightGBM importance separately LONG / SHORT.

For all 13 features:

    gain
    gain %
    split count
    split %

Also report:

    top-3 cumulative gain %
    top-5 cumulative gain %
    zero-gain features

NQ DESCRIPTIVE REFERENCE ONLY:

    ema_slope
    arrival_velocity
    rolling retention ratio
    rolling giveback ATR
    rolling current progress ATR

Do not impose this ranking on ES.

Report the ES ranking actually learned.

============================================================
13. OOS 2024
============================================================

Only after the TRAIN freeze:

    authorize/open ES 2024
    collect/score through governed Platform V2

NO:

    refit
    recalibration
    threshold changes
    architecture changes

Report separately LONG / SHORT:

    rows
    unique regimes
    base rate

    ROC-AUC
    PR-AUC
    PR-AUC / base-rate lift
    Brier
    expected calibration error where supported

TRAIN -> OOS:

    ROC change / retention
    PR-AUC change
    PR/base-rate lift retention
    calibration change

At frozen ES TRAIN thresholds:

    P90
    P95
    P97.5

report:

    retained fraction
    flip-within-180s probability
    lift versus 2024 base rate
    median seconds-to-flip

============================================================
14. FIRST-P90 DIAGNOSTIC
============================================================

If current Platform V2 already provides the generic governed first-fire analysis:

Use:

    first eligible checkpoint with score >= frozen ES TRAIN P90
    inclusive threshold
    no below->above crossing requirement
    one first fire per regime

Report separately LONG / SHORT:

    eligible regimes
    regimes with first P90 fire
    % regimes firing
    first-fire signals
    signals per RTH day
    flip-within-180s rate
    median seconds-to-flip

This is descriptive.

Do not optimize the threshold.

If the required generic analysis capability is absent:

    route typed ANALYSIS_HARNESS_GAP / capability gap through supervisor

Do not create study-local analysis Python.

============================================================
15. ES VS NQ PORTABILITY COMPARISON
============================================================

After ES 2024 is complete, compare descriptively against already-frozen NQ 180s evidence.

Do NOT retrain or recollect NQ.

Compare:

    OOS ROC-AUC behavior
    PR/base-rate lift
    calibration
    P90/P95/P97.5 tail behavior
    median seconds-to-flip
    maturity-bucket behavior
    first-fire behavior where available
    feature-importance ranking/concentration

Interpretation categories:

    STRONG_PORTABILITY
    PARTIAL_PORTABILITY
    NO_MEANINGFUL_PORTABILITY

Do NOT define success as identical NQ/ES numerical AUC.

Judge whether the same frozen architecture yields, on ES:

    genuine forward discrimination
    stable tail lift
    reasonable calibration
    useful timing discrimination
    and/or comparable learned feature structure

============================================================
16. NO ECONOMIC WORK
============================================================

Do NOT:

    simulate entries
    submit orders
    optimize SL/PT
    model fills/slippage
    create Stage 2
    train combined NQ+ES models

This study ends at predictive portability.

============================================================
17. INTEGRITY REQUIREMENTS
============================================================

Require:

    exact parent semantic reconciliation
    exact 13-feature contract
    no all-null feature columns
    canonical null-contract compliance
    feature variance checks
    unique-regime counts
    direction/model binding
    golden-score validation
    target-runtime parity/evidence
    chronology proof
    2024 unopened before freeze
    2025/2026 untouched

If ES legitimately exposes a feature-availability difference:

    report it
    fail/route according to canonical null semantics

Do not silently impute or alter feature semantics.

============================================================
18. REQUIRED OUTPUTS
============================================================

Use governed Platform V2 artifacts.

Required logical outputs:

    resolved ES Model C feature contract
    TRAIN population summary
    frozen LONG model
    frozen SHORT model
    frozen ES TRAIN P90/P95/P97.5 thresholds
    TRAIN classification summary
    feature importance table
    2024 OOS classification summary
    2024 score-tail summary
    maturity-bucket summary
    first-P90 summary if supported
    ES-vs-NQ portability comparison
    final study report
    study closure card

No authoritative scratch analysis pipeline.

If a required statistic is unsupported:

    route the typed analysis capability gap.

============================================================
19. AUTONOMY DECISIONS
============================================================

on_capability_gap:

    MISSING_CAPABILITY / UNSUPPORTED_COMPOSITION
        -> supervisor launches fresh capability worker
        -> generic chore branch/worktree
        -> targeted tests
        -> governed promotion/merge
        -> merge current main into study
        -> recompile/reseal/resume

    INVALID_PARAMETERIZATION
        -> fresh study-design worker repairs declarative spec

    semantic ambiguity already resolved by this contract
        -> use this contract
        -> do not ask again

deterministic_defect:

    auto-repair through bounded supervisor repair flow

audit_fixable_defect:

    auto-repair
    regenerate affected packet
    bounded re-audit

platform_merge:

    auto_if_green

    Requirements:
        claimed write surface
        targeted tests green
        required promotion green
        one required pre-merge broad regression gate under current policy
        no new attributable regressions

frozen_parent_evidence:

    authenticate/reuse
    NEVER retrain NQ

protected_data:

    never broaden chronology authority

long_jobs:

    detached
    no AI worker waiting/polling

============================================================
20. USER INTERVENTION CONDITIONS
============================================================

Do NOT ask the user about:

    deterministic implementation defects
    capability implementation details
    test failures
    stale seals
    audit regeneration
    ordinary merge/recompile decisions
    long-job completion
    already-resolved parent semantics

Ask only if there is a genuine unresolved:

    SCIENTIFIC_SEMANTIC_DECISION_REQUIRED
    AUTHORIZATION_AMBIGUITY
    PROTECTED_OOS_AUTHORIZATION_REQUIRED beyond this contract
    DATA_SAFETY_RISK
    CAUSAL_DEFINITION_AMBIGUOUS
    RESEARCH_CONTRACT_CONFLICT
    DESTRUCTIVE_ACTION_REQUIRES_APPROVAL not covered by auto_if_green
    repeated supervisor escalation after bounded repairs

NOTE ON OOS AUTHORIZATION: this contract IS the authorization for ES 2024 to open
after the TRAIN freeze, through the governed `oos` stage. It is NOT authorization for
2025 or 2026, which must remain untouched.

============================================================
21. SUPERVISOR EXECUTION
============================================================

This is a SUPERVISED Platform V2 study.

The owner session should NOT manually carry the study through every phase.

Use the canonical Research Supervisor.

Expected user experience:

    one intake
    -> disposable design worker
    -> disposable capability workers only if required
    -> disposable auditors
    -> detached deterministic collection/fit/OOS jobs
    -> disposable analysis worker
    -> STUDY_CLOSED

No AI worker should remain alive during long deterministic jobs.

Persist all decisions/results in governed artifacts/cards.

============================================================
22. FINAL CARD
============================================================

Write `artifacts/ES_180S_MODEL_C_PORTABILITY_CARD.json` with this shape:

ES_180S_MODEL_C_PORTABILITY_CARD

AUTHORITY:
    dataset:
    dataset_digest:
    parent_nq_authority:
    target:
    population:
    feature_surface_hash:
    model_family:
    fixed_hyperparameters_verified:

TRAIN_2020_2023:

    LONG:
        rows:
        regimes:
        base_rate:
        ROC_AUC:
        PR_AUC:
        PR_base_lift:
        Brier:

    SHORT:
        rows:
        regimes:
        base_rate:
        ROC_AUC:
        PR_AUC:
        PR_base_lift:
        Brier:

ES_TRAIN_THRESHOLDS:

    LONG:
        P90:
        P95:
        P97_5:

    SHORT:
        P90:
        P95:
        P97_5:

FEATURE_IMPORTANCE:

    LONG:
        top_5:
        top_3_gain_pct:
        top_5_gain_pct:
        zero_gain_features:

    SHORT:
        top_5:
        top_3_gain_pct:
        top_5_gain_pct:
        zero_gain_features:

OOS_2024:

    LONG:
        rows:
        regimes:
        base_rate:
        ROC_AUC:
        PR_AUC:
        PR_base_lift:
        Brier:
        calibration:
        P90_flip_rate:
        P90_lift:
        P95_flip_rate:
        P95_lift:
        P97_5_flip_rate:
        P97_5_lift:

    SHORT:
        (same fields)

TRAIN_TO_OOS:

    LONG:
        ROC_retention:
        PR_lift_retention:
        calibration_change:

    SHORT:
        (same fields)

FIRST_P90:

    LONG:
        signals:
        signals_per_day:
        flip_180_rate:
        median_seconds_to_flip:

    SHORT:
        (same fields)

ES_VS_NQ:

    ROC_behavior:
    score_tail_behavior:
    maturity_behavior:
    feature_importance_similarity:
    first_fire_behavior:

PORTABILITY_VERDICT:

    STRONG_PORTABILITY /
    PARTIAL_PORTABILITY /
    NO_MEANINGFUL_PORTABILITY

MODEL_TUNED:
    NO

FEATURES_CHANGED:
    NO

2025_2026_ACCESSED:
    NO

SUPERVISOR:
    capability_gaps_encountered:
    platform_changes_merged:
    unexpected_user_interventions:
    worker_count:
    ai_alive_during_long_jobs:
    wall_time:
    worker_cost:

NEXT_RECOMMENDED_STUDY:
    only if evidence warrants ES-specific tuning or broader cross-instrument testing

---

# RESOLVED SPECIFICATION

The contract above is the authority. This section records what it resolved to, against the
governed artifacts that were actually read. `research_decision.yaml` carries the same
resolutions in machine-readable form; `study.yaml` / `compiled_plan.json` are the executable
composition.

## Authority

| what | resolved from | value |
|---|---|---|
| dataset | `research/datasets/ES_1S_V2_GLOBEX.yaml`, `PLATFORM_STATE.json` `datasets.current.ES` | `ES_1S_V2_GLOBEX`, logical digest `9f38a41edca5b72a71866846ec9aa15d4cf205388d22aabe025250eefbf0068a` |
| parent NQ authority | `studies/clean_maturity_flip_model_180s_horizon` | frozen v1 reference; never recompiled, retrained or recollected |
| feature surface | parent `artifacts/frozen_feature_manifest.json` | `feature_sets.LONG_C == SHORT_C`, `feature_list_sha256 = 38c0201fe2b0fec3070b7a226353d7782778aa82bace3b6070de8844d9d04d32` |
| population / target | parent `study.yaml` `population.qualification` and `target` blocks | reproduced field for field below |
| fixed hyperparameters | parent `artifacts/model_selection_manifest_{long,short}.json` `winner.C.hyperparameters` | verified equal to contract section 7 |
| regime authority | `tracker.regime.dual_ema` defaults | EMA(3)/EMA(9), ATR(14), 1m |

## Population

Established prevailing-1m-regime checkpoints on ES, RTH, both directions. The predicates are
the parent's, FIXED -- none of them may be tuned for ES.

| predicate | parent field | study.yaml expression |
|---|---|---|
| regime age >= 120s | `age_gate_seconds: 120` | `regime_1m.age_s >= 120s` |
| running MFE >= 1.0 ATR | `running_mfe_atr_gte: 1.0` | `excursion.mfe_atr >= 1.0` |
| >= 2 new-progress windows | `new_progress_windows_gte: 2` | `excursion.progress_windows >= 2` (tracker `progress_gap: 120s`) |
| retained MFE ratio >= 0.50 | `retained_mfe_ratio_gte: 0.5` | `excursion.retained_ratio >= 0.5` |
| 5s candidate cadence | `cadence_seconds: 5` | `cadence: {every: 5s, anchor: regime_1m.start_ns}` |
| RTH | `session: RTH` | `population.session: RTH` |
| both directions | `prevailing_regime: both` | `population.direction: regime_1m.dir` |
| frozen ATR available | (implicit) | `excursion.frozen_atr > 0`, `features.structural_snapshot_ready` |

No `max_age` is declared. The parent caps no maturity, and contract section 11 requires a
reachable `>=1800s` maturity bucket -- a 1800s cadence cap would empty it.

`regime_age_seconds`, `running_mfe_atr`, `new_progress_windows`, `retained_mfe_ratio` and
`regime_direction` are emitted as metadata columns: diagnostics and the cell partition key,
never model inputs.

## Target

Prevailing 1m regime flip within `(T, T+180s]`.

* capability: `outcome.flip_within_horizon` via `outcome: {kind: label, event: regime_1m.flipped}`
* horizon `180s`, `horizon_end_rule: strict`, `session_end: censor`
* direction `regime_1m.dir` (the prevailing direction read at T)
* confirmation is the dual-EMA tracker's own completed-1m-bar flip event -- the parent's
  `confirmation: {mode: completed_1m_bar, confirmation_bars: 1}`
* decision epoch T is the 5s grid checkpoint; `triggering_1s_ts_init: epoch.T` records it per row
* label column `target_flip_within_horizon`

## Features

Exactly the 13 semantic features of the repaired NQ Model C, with the parent's own parameters.
`compiled_plan.json` `columns.features` contains these 13 physical aliases and nothing else.

| # | alias | instance |
|---|---|---|
| 1 | `arrival_velocity` | `arrival_velocity` input_timeframe 1s, lookback 20, bar_state completed |
| 2 | `arrival_acceleration` | `arrival_acceleration` input_timeframe 1s, short_lookback 20, bar_state completed |
| 3 | `ema_slope` | `ema_slope` ema_role short, lookback 20 |
| 4 | `prior_1m_regime_efficiency` | `regime_efficiency` timeframe 1m, context prior, bar_state completed |
| 5 | `prior_1m_regime_mfe_atr` | `regime_mfe_atr` timeframe 1m, context prior, bar_state completed |
| 6 | `prior_1m_regime_range_atr` | `regime_range_atr` timeframe 1m, context prior, bar_state completed |
| 7 | `prior_5m_regime_efficiency` | `regime_efficiency` timeframe 5m, context prior, bar_state completed |
| 8 | `prior_5m_regime_mfe_atr` | `regime_mfe_atr` timeframe 5m, context prior, bar_state completed |
| 9 | `prior_5m_regime_range_atr` | `regime_range_atr` timeframe 5m, context prior, bar_state completed |
| 10 | `rolling_300s_retention_ratio` | `rolling_retention_ratio` window 300s, update_every 1s |
| 11 | `rolling_300s_current_progress_atr` | `rolling_current_progress_atr` window 300s, update_every 1s |
| 12 | `rolling_300s_max_progress_atr` | `rolling_max_progress_atr` window 300s, update_every 1s |
| 13 | `rolling_300s_giveback_atr` | `rolling_giveback_atr` window 300s, update_every 1s |

Identity is the canonical `FeatureInstance` plus its `timeframe` / `window` parameter -- the
`prior_5m_*` and `rolling_300s_*` names are compiler-generated output aliases, not separate
features.

## Model

Fixed-architecture portability. One collected ES population; two modeling **cells** fit
independently.

| cell | subset | learning_rate | n_estimators | shared |
|---|---|---|---|---|
| LONG | `regime_direction == 1` | 0.039440343780424526 | 100 | `max_depth: 5`, `num_leaves: 4`, `verbosity: -1`, `random_state: 42` |
| SHORT | `regime_direction == -1` | 0.028861842631876633 | 200 | same |

`random_state` is declared ONLY in `model.params`: `_build_estimator` constructs
`LGBMClassifier(random_state=seed, **cfg)`, so a cell-level `random_state` is a duplicate-kwarg
crash. `n_jobs` / `deterministic` are deliberately not declared -- the parent declared neither,
and this study changes nothing about the architecture it is testing.

No `model.arms`, no `model.search_space`, no `model.validation`. `lifecycle_v2.fit()` therefore
falls back to `tuning = chronology.train` and `final_train_validation_years = []`, and
`research_workflow.tuning.tune` is never invoked. Nothing adaptive runs anywhere in this study.

## Chronology

| role | years |
|---|---|
| TRAIN (fit + all threshold derivation) | 2020, 2021, 2022, 2023 |
| protected OOS (`dev`) | 2024 |
| prohibited | 2025, 2026 |
| smoke (`authorized_dates`) | 2021-01-05 |

Call-by-call year table -- every governed call and the years it touches:

| # | stage / call | years touched | role |
|---|---|---|---|
| 1 | `smoke` | 2021-01-05 only | bounded TRAIN-day execution proof |
| 2 | `collect` (train partitions) | 2020, 2021, 2022, 2023 | TRAIN collection |
| 3 | `reconcile` / `merge` | 2020-2023 | TRAIN population identity |
| 4 | `fit` expanding folds | fit {2020} val 2021, fit {2020,2021} val 2022, fit {2020,2021,2022} val 2023 | TRAIN-internal diagnostics only; selects nothing |
| 5 | `fit` final estimator, per cell | 2020, 2021, 2022, 2023 | the frozen LONG / SHORT models |
| 6 | ES TRAIN P90/P95/P97.5 per cell | 2020-2023 scores only | `derivation_population = train` |
| 7 | `freeze` | 2020-2023 | model bytes, canonical shas, feature order, preprocessing, thresholds |
| 8 | `oos` (opens 2024) | 2024 | collection + scoring, AFTER the freeze |
| 9 | `analyze` | 2024 | OOS classification + score tails at the FROZEN thresholds |
| 10 | ES-vs-NQ comparison | none (reads already-frozen NQ artifacts) | descriptive |

2024 influences nothing in rows 1-7. 2025 and 2026 are never touched by any row. Row 4 selects
nothing: the folds are reported, not compared, and the final estimator's hyperparameters were
fixed by the parent before any ES row existed.

## Deliverables Manifest

1. resolved ES Model C feature contract -- `compiled_plan.json` `columns.features` (13)
2. TRAIN population summary per direction -- `artifacts/experiment_models.json`
3. frozen LONG model, frozen SHORT model -- model store + `artifacts/train_experiment_freeze.json`
4. frozen ES TRAIN P90 / P95 / P97.5 per direction, `derivation_population = train`
5. TRAIN classification summary per direction (ROC-AUC, PR-AUC, PR/base lift, Brier, calibration)
6. feature importance table per direction (gain, gain %, split count, split %, top-3/top-5
   cumulative gain %, zero-gain features)
7. 2024 OOS classification summary per direction -- `artifacts/experiment_analysis_v2.json`
8. 2024 score-tail summary at the frozen ES TRAIN thresholds
9. maturity-bucket summary (0-300 / 300-600 / 600-900 / 900-1800 / >=1800s) from
   `regime_age_seconds`
10. first-P90 summary **if supported**
11. ES-vs-NQ portability comparison (descriptive)
12. `artifacts/ES_180S_MODEL_C_PORTABILITY_CARD.json` (shape: contract section 22)
13. `artifacts/study_closure.json` with one of the declared `terminal_decisions`

## Known platform risks recorded at design time

Not raised by `study compile` -- recorded so phases B/C/D do not rediscover them. Full text in
`research_decision.yaml` `known_platform_risks_for_later_phases`.

* **`multi_cell_freeze`** -- `lifecycle_v2.freeze()` keys `model_canonical_sha256` by `m["name"]`
  over `models["models"]`; the multi-cell fit writes `arm`/`cell`/`model_id` entries with no
  `name`, and sets no top-level `model_id`. Expect a `KeyError` at freeze (deterministic defect,
  `deterministic_defect: auto_fix`).
* **`multi_cell_oos_analyze`** -- `analyze()` emits OOS classification only for `mode == "score"`
  or a single top-level `model_id`; a multi-cell TRAIN study is neither, so deliverable 7 has no
  producer today.
* **`feature_importance`** -- deliverable 6 has no producer: no `importance` symbol exists under
  `research_workflow/` or `research/analysis/`.
* **`train_threshold_artifact`** -- deliverable 4 exists on the v1 path
  (`research_workflow/modeling.py`); `lifecycle_v2.freeze()` writes `thresholds: {}`.
* **`first_p90_diagnostic`** -- `analysis.anchor.first_threshold_crossing` needs literal per-case
  thresholds, which a TRAIN-derived quantile is not at design time; and a declared `analysis:`
  block displaces the OOS classification path. Deliverable 10 is conditional by contract.

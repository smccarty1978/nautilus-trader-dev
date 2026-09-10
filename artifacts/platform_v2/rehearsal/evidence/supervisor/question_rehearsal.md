# Research question — rehearsal_checkpoint_norm (DISPOSABLE full-scale rehearsal)

Does the maximum structural expansion of the current 1m regime, normalized by the ATR at the
decision epoch (`structural_max_expansion_checkpoint_atr`), add out-of-sample tail lift to a
regime-flip classifier that already sees the same quantity normalized by the regime-start
frozen ATR (`structural_max_expansion_atr`)? Instrument NQ, one full TRAIN year (2023), one
full OOS year (2024). Tail lift is measured on the study's OWN fitted-model scores with
thresholds frozen on TRAIN and applied to OOS rows.

This study is a full-scale platform rehearsal. The numbers are not research; the study is
deleted after closure. Every instruction below is a research-contract term.

## Design worker instructions (phase A)

1. `studies/rehearsal_checkpoint_norm/study.yaml`: start from the population, context,
   triggers, outcome, model and analysis of the closed gate study spec reproduced below, and
   change ONLY what these instructions say.

   ```yaml
   study:
     id: rehearsal_checkpoint_norm
     tier: 2
     question: "Does checkpoint-ATR normalization of structural max expansion add OOS tail lift over the frozen-ATR normalization? Full-year TRAIN 2023 / OOS 2024, NQ."
   streams:
     - {dataset: NQ_1S_V2_GLOBEX, timeframes: [1s, 1m]}
   context:
     regime_1m:     {tracker: regime.dual_ema, timeframe: 1m}
     excursion:     {tracker: regime.excursion, bars: 1s, regime: regime_1m}
     regime_bar_5m: {tracker: regime_bar.calendar_bucket, bucket: 5m, bars: 1m, regime: regime_1m}
   population:
     session: RTH
     cadence: {every: 5s, anchor: regime_1m.start_ns, max_age: 1800s}
     qualify: "excursion.frozen_atr > 0 and regime_1m.age_s >= 120s and excursion.mfe_atr >= 1.0 and features.structural_snapshot_ready"
     direction: regime_1m.dir
     anchor_identity: regime_1m.start_ns
   triggers: every_candidate
   features:
     instances:
       - {feature: regime_efficiency, over: {timeframe: [1m, 5m]}, context: prior}
       - {feature: rolling_giveback_atr, window: 300s, update_every: 1s}
       - {feature: structural_max_expansion_atr, context: current}
       - {feature: structural_max_expansion_checkpoint_atr, context: current}
     metadata:
       regime_age_seconds: regime_1m.age_s
       triggering_1s_ts_init: epoch.T
     bindings:
       completed_5m: {tracker: regime_bar_5m, ready_gate: false}
       snapshot: {atr: regime_1m.atr, family_a_atr: excursion.frozen_atr, episode_state: {prevailing_direction: regime_1m.dir}}
   outcome:
     kind: label
     event: regime_1m.flipped
     horizon: 300s
     direction: regime_1m.dir
     session_end: censor
   chronology:
     train: [2023]
     dev: [2024]
     prohibited: [2020, 2021, 2022, 2025, 2026]
     authorized_dates: ['2023-03-01']
   model:
     family: lightgbm
     params: {max_depth: 3, num_leaves: 7, learning_rate: 0.05, min_data_in_leaf: 50, n_estimators: 100, n_jobs: 1, deterministic: true, verbosity: -1, random_state: 42}
     validation: {protocol: model_selection.random, tuning_years: [2023], final_train_validation_years: []}
   analysis:
     source: oos
     model_scores: true
     steps:
       - id: tail
         op: analysis.metric.tail_lift
         rows: frame
         inputs: {reference: train_frame}
         params: {score: score__primary, label: target_flip_within_horizon, quantiles: [0.9, 0.95, 0.975]}
     artifacts:
       - {name: tail_lift.json, source: tail, kind: json}
       - {name: tail_lift.parquet, source: tail, kind: frame}
   ```

   FULL YEARS: there is NO `chronology.windows` entry. TRAIN is all of 2023, OOS is all of 2024.

2. THE FEATURE SET IS A CONTRACT TERM. The four feature instances above are the model's
   inputs. Do NOT drop, rename, substitute, re-parameterize or "approximate" any of them, even
   if `cap search` / `cap describe` cannot find one of them. If `study compile` returns a
   CapabilityGap for a feature, that gap is genuine: commit study.yaml + research_decision.yaml
   + CAPABILITY_GAP_HANDOFF.* and STOP (status BLOCKED, blocker_code CAPABILITY_GAP). Never
   route around it. A spec that compiles because a declared feature was removed is a
   research-contract violation.

3. `research_decision.yaml`: keep status DRAFT, `dataset_id: NQ_1S_V2_GLOBEX`,
   `disposable: true`, `research_question` = the first paragraph of this file, and declare:
   ```yaml
   terminal_decisions:
     REHEARSAL_COMPLETE: the lifecycle ran to closure on full-year TRAIN 2023 / OOS 2024 and tail_lift.json exists for the study's own fitted-model scores with TRAIN-frozen thresholds
     REHEARSAL_INCOMPLETE: a lifecycle stage, gate or deliverable is missing or invalid at the time of the analysis decision
   ```
   `terminal_decisions` is the closure VOCABULARY the analysis decision must come from; it is
   never metadata. Keep the default `autonomy_decisions` written by `study new` and ADD
   `platform_merge: approval_required` under `autonomy_decisions` (a capability merge to main
   needs the owner's approval). Do NOT add `closed_study_merge`.

4. Run `python scripts/research.py study compile --study studies/rehearsal_checkpoint_norm`
   and commit study.yaml, research_decision.yaml and (on success) compiled_plan.json on the
   study branch. Never write research_workflow/, features/ or any study Python.

## Capability implementation instructions (if a CAPABILITY_IMPLEMENTATION worker is launched)

`structural_max_expansion_checkpoint_atr` is the maximum structural expansion of the current
1m regime normalized by the checkpoint-epoch ATR (`checkpoint_atr` passed to the structural
geometry snapshot) instead of the regime-start frozen ATR used by `structural_max_expansion_atr`.
Semantics, availability, warmup, reset (`event_start`), null policy and provider are identical
to `structural_max_expansion_atr`; only the normalizer differs. The registered provider
(`features.trackers.generic_structural_geometry.GenericStructuralGeometryProvider`) already
computes it. Implement it as a feature DEFINITION through the registration boundary
(`features/registry.py` reads catalogues under `features/definitions/` via
`research_workflow/capabilities_index.d/feature_definitions.yaml`); do not add a provider, a
tracker or a host adapter for it. Follow the capability flow (`WORKFLOW.md` section E, section
M.3) including whatever promotion / parity evidence the flow requires for a new definition.

## Analysis worker instructions (phase D)

Read `artifacts/tail_lift.json`, `artifacts/train_experiment_freeze.json` and the OOS metrics.
Report the tail-lift table (quantile, threshold, n_tail, tail_rate, base_rate, lift) and the OOS
roc_auc, the TRAIN and OOS row counts, and whether `score__primary` is present on every OOS row.
The terminal decision MUST be `REHEARSAL_COMPLETE` if every declared deliverable exists and the
freeze authenticates, otherwise `REHEARSAL_INCOMPLETE`. Do not interpret the numbers as science.

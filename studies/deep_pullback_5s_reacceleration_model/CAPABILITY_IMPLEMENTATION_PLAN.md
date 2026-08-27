# Capability Implementation Plan — Deep Pullback / 5s Re-acceleration

Status: pre-scaffold implementation checkpoint. The researcher authorized the generic capability
work in this plan. This does not authorize study scaffolding, collection, fitting, or OOS access.
The frozen authority is `research_decision.yaml`; no semantic clarification remains outstanding.

Implementation checkpoint (2026-08-26):

- C and D are implemented at their generic owning layers with targeted contract tests.
- A is implemented as `CompletedRegimeStateFeed`, delegating calculation to the accepted
  collector_v2 aggregator/engine and rejecting incomplete buckets.
- B is implemented as the typed `EpisodeLifecycleSpec` plus `EpisodePopulationEngine`; its tests
  freeze completed-1s intrabar arming, counter-state-at-arm acceptance, strict post-arm emission,
  one candidate, inversion, rearm, and termination.
- E is implemented as `FrozenExternalModelScorer`; the concrete Model C binding remains refused
  until the parent's repaired-freeze/model-artifact invalidation records are reconciled.
- F duplicate resolution confirms that canonical structural geometry, rolling productivity,
  completed-regime geometry, and parameterized OHLCV/delta windows already own most requested
  concepts. New episode-specific geometry identities are not promoted before the exact 55-65
  feature contract is authored and reviewed; doing so now would guess the feature surface.

## A. Generic completed-5s regime state

- **Owner:** `research_workflow/generic_collector.py`, `research_workflow/execution_plan.py`,
  with the accepted calculation remaining in
  `collectors/collector_v2/{aggregator,regime_engine,registry}.py`.
- **Reusable API:** add `research_workflow/completed_regime_state.py::CompletedRegimeStateFeed`.
  It accepts declared timeframes, consumes completed NT 1s bars using `ts_event` as bucket-open
  time and `ts_init` as availability, calls `TimeframeAggregator.finalize_through(T)`, and
  returns only `CompletedBarRegistry.audit_provenance(timeframe, T)`-legal frozen states.
  `CompiledExecutionPlan` declares required regime-state timeframes once at construction.
- **Expected files:** new `research_workflow/completed_regime_state.py`; modify
  `research_workflow/{generic_collector,execution_plan}.py`; include the new module in execution
  closure/export metadata only if required by the existing resolver.
- **Targeted tests:** completed 5s boundary availability; no forming-bucket read; missing-member
  rejection; ETH-to-RTH retention; parity against direct `TimeframeAggregator` plus
  `RegimeStateEngine`; callback order when 5s and 1m close together.
- **Promotion/audit:** no new regime definition and therefore no feature promotion. Causal review
  must cover timestamp/bucket availability and shared-bar ordering; contract review must prove the
  study requested the state source explicitly.
- **Study consumption:** the episode lifecycle reads the completed 5s state and transition at T.
- **Why reusable:** any governed study may request accepted completed regime state at a supported
  timeframe without adding another collector or regime implementation.

## B. Generic stateful episode/population lifecycle

- **Owner:** typed contract in `research/schemas/study_spec.py`, compilation in
  `research/engines/population_engine.py`, hook contract under `research_workflow/hooks/`, and
  runtime ownership in a new `research_workflow/episode_population.py` used by the generic
  collector.
- **Reusable API:** introduce `EpisodeLifecycleSpec` with ordered declarations for
  `arm_condition`, `required_events`, `emit_condition`, `terminal_conditions`,
  `rearm_conditions`, and `max_candidates_per_episode`. Runtime API:
  `EpisodePopulationEngine.on_event(event, causal_snapshot) -> EpisodeDecision`, where the
  immutable decision reports `NOOP`, `ARMED`, `INTERMEDIATE_SATISFIED`, `EMIT`, `TERMINATE`, or
  `REARM`, plus episode identity and transition provenance. Start with a bounded typed condition
  vocabulary needed for directional thresholds, completed state/transition equality, new
  favorable extremes, and prevailing-state transitions; reject unknown condition kinds.
- **Frozen ordering semantics:** a completed-1s intrabar high/low may arm the episode while the
  counter-state is already active; that state counts as seen. The counter-state may instead begin
  later. Emission requires a flip-back timestamp strictly after the arm timestamp, so no pre-arm
  flip is retroactively emitted. Suggested internal states such as unarmed-counter-seen,
  armed-counter-active, armed-waiting-for-counter, and emitted are implementation details, not
  study-specific public names.
- **Expected files:** modify `research/schemas/study_spec.py` and
  `research/engines/population_engine.py`; add
  `research_workflow/{episode_population.py,hooks/episode.py}`; modify
  `research_workflow/{generic_collector,output_manager,phase0.py}` only where binding and emitted
  episode identity require it.
- **Targeted tests:** one emission per episode; no chatter duplicates; exact directional inverse;
  required-event enforcement; rearm on new favorable extreme; termination on prevailing flip;
  stable episode IDs; RTH emission with retained ETH state; checkpoint/output reconciliation;
  completed-1s low/high arming without close confirmation; counter-state active before arm counts;
  counter-state first appearing after arm counts; pre-arm flip-back never emits.
- **Promotion/audit:** this is population infrastructure, not a feature promotion. It requires
  causal review of every transition timestamp and contract review of candidate reachability,
  duplicate policy, and reset semantics.
- **Study consumption:** parameters freeze threshold `1.0 ATR`, counter-5s required, first
  post-arm flip-back emission, one candidate, completed-1s excursion arming, counter-state-at-arm
  acceptance, and the two rearm/termination events.
- **Why reusable:** the abstraction represents bounded arm → episode → required event → emit →
  reset workflows such as breakout/retest, threshold/recovery, and multi-stage confirmation.

## C. Generic asymmetric ordered-barrier outcome

- **Owner:** `research_workflow/forward_outcomes/{contracts,tracker,guard}.py`,
  `research/schemas/study_spec.py`, and `research/engines/target_engine.py`.
- **Reusable API:** add immutable `OrderedBarrierSpec(id, favorable_atr, adverse_atr,
  horizon_seconds)` to `ForwardOutcomeSpec`; add `BarrierDisposition` with `SUCCESS`, `FAILURE`,
  `TIMEOUT`, `AMBIGUOUS_FIRST_TOUCH`, and `CENSORED`. Generated records contain disposition,
  nullable binary label, first-touch timestamps/seconds, collision flag, and censor reason.
  A bar touching both thresholds before either prior touch is ambiguous by construction.
- **Expected files:** modify the five modules above plus
  `research_workflow/forward_outcomes/analysis.py` for disposition summaries.
- **Targeted tests:** LONG/SHORT symmetry; unequal barriers; success/failure; fully observed
  timeout; same-1s-bar ambiguity; session/data/gap censoring; partition parity; exact output
  namespace caught by the training guard; entry-open and fully-forward inclusion.
- **Promotion/audit:** no feature promotion. Causal audit owns entry/bar inclusion, collision,
  horizon, and censoring; contract audit owns terminal-label reachability and binary-null policy.
- **Study consumption:** `favorable_atr=1.0`, `adverse_atr=0.75`, `horizon_seconds=300`, with
  TIMEOUT=0 and ambiguous/censored rows excluded from binary fitting.
- **Why reusable:** arbitrary direction-normalized X/Y/H barrier races use one tracker and one
  schema rather than study-local labels.

## D. Generic post-TRAIN-merge/pre-fit required gate

- **Owner:** `research/schemas/study_spec.py`, `research_workflow/gates.py`,
  `research_workflow/modeling.py`, and lifecycle documentation/facade.
- **Reusable API:** add stage `pre_fit` after merge and before fit. Extend required-gate evidence
  with declared runtime bindings, initially `train_merge_identity_sha256`. Call
  `assert_gates_satisfied(..., stage="pre_fit", dataset_identity_sha256=...)` at the start of
  `fit_models`, before any estimator construction. Missing, FAIL, StudySpec-stale, or
  merge-identity-stale evidence raises and no fit artifact is written.
- **Expected files:** modify `research/schemas/study_spec.py`,
  `research_workflow/{gates,modeling,lifecycle}.py`, relevant compiler/status documentation, and
  the authoritative lifecycle tables in `docs/{RESEARCH_WORKFLOW,RESEARCH_STUDY_BLUEPRINT}.md`.
- **Targeted tests:** fit refusal for missing/failed/malformed gate; refusal after population,
  target, chronology, or merged-input identity changes; PASS path; existing prepare/readiness/
  preflight/seal/train-freeze gates remain compatible; prove refusal occurs before estimator fit.
- **Promotion/audit:** no feature promotion. Contract review must verify stage ordering and stale
  input binding; causal audit is referred only if a particular gate computes causal quantities.
- **Study consumption:** a declared population/target-balance artifact binds to the reconciled
  2021–2023 TRAIN merge and must PASS before LightGBM fitting begins.
- **Why reusable:** any study can require a deterministic diagnostic over its actual merged TRAIN
  data before fitting, without hard-coding a target-balance gate into modeling.

## E. Generic frozen external-model scoring

- **Owner:** `research/schemas/study_spec.py`, `research_workflow/derived_inputs.py`, a new
  `research_workflow/external_model_scoring.py`, execution-plan binding, and generic collector
  snapshot emission.
- **Reusable API:** extend `DerivedCausalInputSpec` to bind the actual model bundle/manifest bytes,
  ordered parent feature surface, preprocessing identity, directional arm mapping, and score
  output. `FrozenExternalModelScorer.bind(spec, parent_freeze)` verifies all hashes and exact
  order once; `score(causal_snapshot, decision_ts, direction) -> DerivedScoreObservation` refuses
  missing/out-of-order/null-policy-invalid inputs and records latest contributing availability.
  It never retrains and is never registered as a canonical feature.
- **Expected files:** modify `research/schemas/study_spec.py`,
  `research_workflow/{derived_inputs,execution_plan,generic_collector,phase0}.py`; add
  `research_workflow/external_model_scoring.py`. Repair or supersede the parent artifact
  invalidation record before binding Model C bytes.
- **Targeted tests:** artifact/hash/preprocessing/order mismatch refusal; directional arm mapping;
  availability `<= T`; deterministic score parity against the frozen parent model; no P90 gate;
  no retraining path; optional materialized-score fast path with identical provenance.
- **Promotion/audit:** not a feature promotion. Causal audit owns feature availability at T;
  contract audit owns parent freeze/model/preprocessing/ordered-surface identity and non-retrain.
- **Study consumption:** emit raw/probability Model C score at candidate T only. Historical
  pullback snapshots remain optional.
- **Why reusable:** any governed child study can consume a frozen parent score at new causal
  checkpoints through one provenance-bound scorer.

## F. Missing canonical market-state features

- **Owner:** existing generic providers under `features/trackers/`; registry and authority under
  `features/`; generic collector/execution-plan bindings. Prefer extending
  `GenericPullbackProvider`, `GenericStructuralGeometryProvider`, and
  `GenericOHLCVDeltaProvider`; add a parameterized completed-regime-episode geometry provider only
  if no existing formula is equivalent.
- **Reusable API:** canonical identities describe formulas only; episode/timeframe/window/context
  are parameters. Providers consume immutable causal episode/regime snapshots rather than study
  objects. Direction normalization is an explicit parameter/contract, not alias parsing.
- **Expected files:** determined by `feature_ctl` duplicate resolution; likely
  `features/trackers/generic_pullback.py`, `features/trackers/generic_structural_geometry.py`,
  optionally a new `generic_regime_episode_geometry.py`, `features/registry.py`, authority source
  records, collector/execution-plan bindings, and generated canonical reference via its existing
  command.
- **Targeted tests:** every new canonical name is named directly; LONG/SHORT inversion; reset/null
  semantics; max/current/recovery identities; structural-denominator preservation; 5s/60s/300s
  rolling-window availability; completed-5m-only alignment; collector/provider parity.
- **Promotion/audit:** each genuinely new definition requires causal/runtime evidence and the
  standard promotion record. Parameter-only instances need targeted validation but no duplicate
  provider.
- **Study consumption:** freeze one motivated 55–65-feature surface after duplicate removal and
  before TRAIN collection; retain both max depth from completed-1s intrabar extremes and current
  depth from candidate-time price, plus their recovery difference; no automated feature mining or
  arbitrary window expansion.
- **Why reusable:** formulas and state-transition geometry are independent of this candidate
  population and can be instantiated by later continuation, reversal, or episode studies.

## Deliberate non-capabilities

- A universal arbitrary finite-state-machine DSL would materially over-engineer the bounded
  episode need. Implement the typed episode protocol and small fail-closed condition vocabulary;
  add condition kinds only when another concrete study requires them.
- Automatically generating every ratio/window/transformation would violate the frozen feature
  policy. Only economically requested identities/instances proceed after duplicate resolution.
- Historical Model C score snapshots are feasible through the same scorer, but collecting and
  storing arbitrary checkpoint histories is unnecessary for this first study and is deferred.
- Permutation importance and advanced calibration plotting remain out of scope.

## Implementation order after researcher closure

1. Implement D and C first because they close machine-contract gaps independently of population.
2. Implement A, then B, so episode transitions consume one accepted completed-state source.
3. Run feature duplicate resolution; implement/promote only the residual F items.
4. Reconcile the parent Model C artifact and implement E only if no causally complete materialized
   candidate-time score surface exists.
5. Run targeted tests and deterministic schema checks, then return for contract review before any
   `study.yaml` or scaffold is created.

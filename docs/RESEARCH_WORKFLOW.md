# Research Workflow — Authoritative Manual

**This document describes the system that is implemented today.** It is the single
authoritative description of where code belongs, how features are identified, what the
study lifecycle is, and which scripts to run. `CLAUDE.md`, `CODEX.md` and `AGENTS.md` are
short agent operating manuals that link here; they do not restate this content.

If another document in this repository contradicts this one, this one wins and the other
one is stale. See `docs/DOCUMENT_MAP.md` for the classification of every doc in the repo.

---

## 0. Quick answers

| Question | Answer |
|---|---|
| Where does shared research code go? | `research_workflow/` |
| Where do feature definitions go? | `features/` (canonical definitions + providers) |
| Where does a study go? | `studies/<study_id>/` — contracts and artifacts only |
| How do I name a 1m EMA? | You don't. `ema` with `parameters: {period: 20, timeframe: 1m, bar_state: completed}` |
| Do I write a collector? | No. Declare `FeatureInstance`s; the generic collector executes them |
| When may I open OOS? | Only after `artifacts/train_experiment_freeze.json` exists and binds to the current authorization |
| A gate failed. Do I stop? | No. Diagnose, fix, re-run the affected bounded check, resume. See §12 |
| Are forward outcomes model inputs? | Never. They are post-event labels; `forward_outcomes/guard.py` fails closed |

---

## 1. Repository architecture

```
features/                     CANONICAL FEATURE IDENTITY
  authority/active.json         pointer to the active canonical bundle
  authority/candidate/          canonical_registry.json, legacy_alias_mapping.json,
                                promotion_facts.json  (the active bundle after cutover)
  registry.py                   FeatureInstance, validate_feature_instance, resolvers
  candidate_authority.py        bundle load / freeze / atomic activation
  trackers/generic_*.py         parameterized providers (the V2 implementations)
  CANONICAL_FEATURE_REFERENCE.yaml   generated, shareable canonical vocabulary
  archive/legacy_registry_*/    Feature System V1, non-runtime rollback archive

research_workflow/            REUSABLE GOVERNED RESEARCH LIFECYCLE
  study_factory.py  compiler.py            scaffold + compile a declarative study
  prepare.py                               PREPARE + FREEZE (execution closure)
  phase0.py                                generic phase-zero authorization manifest
  readiness.py                             R1-R10 runtime readiness gate
  preflight.py                             deterministic preflight orchestrator
  causal_audit.py  contract_audit.py       executable structured reviews
  seal.py                                  pre-execution cryptographic seal
  smoke.py                                 bounded NT smoke + validation
  generic_collector.py                     THE collector strategy (NT event loop)
  execution_plan.py                        compiled callback groups for one study
  output_manager.py                        persistence, schema + surface enforcement
  experiment.py                            TRAIN/OOS authorization, freeze, OOS gate
  collection.py                            period + partitioned collection adapters
  partitioning.py                          year partitions, merge, parity
  modeling.py                              governed fit + TRAIN artifact freeze
  analysis.py                              provenance-bound classification analysis
  forward_outcomes/                        proposed entry -> future path (see §9)
  hooks/                                   tiny study hook Protocols
  lifecycle.py                             one small facade over all of the above

research/                     ANALYSIS + SCHEMA LAYER (consumed by research_workflow)
  analysis/                     loader, spec, slices, metrics, modeling, reporting, identity
  schemas/                      StudySpec, DatasetSpec
  engines/                      feature binding, target, lineage, population, timestamp
  study_types/                  flip_prediction, bespoke, base

studies/<study_id>/           STUDY-SPECIFIC ONLY
  research_decision.yaml        AUTHORITATIVE decision contract
  SPEC.md                       derived from research_decision.yaml
  study.yaml                    machine-readable contract (declares FeatureInstances)
  compiled_study.json           compiled, sha256-bound
  config/                       feature/population/target/deliverables contracts
  implementation/               small declarative hooks ONLY (often absent)
  audit/                        preflight.json readiness.json pass_NN.md status.json ...
  artifacts/                    seals, authorization, freezes, results JSON
  results/                      STUDY_REPORT.md
  tests/                        study contract tests

strategies/                   EXECUTABLE TRADING STRATEGIES ONLY
                              (STRATEGY_REGISTRY lives in
                               backtests/nt_runtime/strategy_binding.py)

backtests/                    NT RUNTIME
  nt_runtime/                   engine_builder, data_plan, run_plan, strategy_binding,
                                compiled_study_loader, telemetry, modes/
  run_nt_study.py               collect entrypoint
  run_backtest.py               standalone backtest entrypoint
  run_*.py (legacy)             FROZEN references. Not templates.

scripts/                      OPERATIONAL / AUDIT / LIFECYCLE / DIAGNOSTIC CLIs (see §11)

archive/, scratch/, runs/     Historical / generated. Never an active implementation.
features/archive/             Feature System V1. Reference and rollback only.
```

### Core invariant

```
NEW STUDY != NEW INFRASTRUCTURE
```

A new study normally adds only: `research_decision.yaml`, `SPEC.md`, `study.yaml`, its
compiled contracts, study tests, and — rarely — a small declarative hook. If you find
yourself writing a collector, an engine bootstrap, a catalog loader, an analysis loader,
or a `run_*.py`, stop: that capability already exists.

---

## 2. Feature System V2 — canonical, timeframe-agnostic identity

**Status: migrated and active. The runtime is canonical-only.**

A *canonical feature definition* names one thing and one thing only:

- the **formula**
- the **provider** (the implementation that computes it)
- its **causal semantics** (what input it is allowed to see, and when)
- its **reset semantics**
- its **null semantics**

Everything else is a **parameter of an instance**, not a separate feature:

```
timeframe   window   lookback   period   context   bar_state   update_every
source_timeframe   reference_timeframe   input_timeframe   ema_role
```

### The rule that matters most

> **"1m EMA" is NOT a separately named feature.**
> Timeframe belongs in `FeatureInstance.parameters`.

```yaml
# CORRECT — study.yaml
features:
  source: canonical_verified_definition_universe
  instances:
    - feature: regime_efficiency
      parameters: {timeframe: 5m, context: prior, bar_state: completed}
    - feature: rolling_giveback_atr
      parameters: {window: 300s, update_every: 1s}
    - feature: arrival_velocity
      parameters: {input_timeframe: 1s, lookback: 20, bar_state: completed}
```

```yaml
# WRONG — these are physical alias names, not canonical identities
    - feature: prior_5m_regime_efficiency
    - feature: rolling_300s_giveback_atr
    - feature: arrival_vel_20s
```

Physical aliases still exist as **output column names**; they are generated
deterministically by `features.registry.generate_physical_alias()` from the instance.
Verification status lives on the canonical definition, never on the alias.

### Bar-state semantics must be explicit and fail closed

Three genuinely different things must never collapse into one another:

| Meaning | Parameters |
|---|---|
| Completed calendar bar | `timeframe: 1m, bar_state: completed` |
| Forming calendar bar | `timeframe: 1m, bar_state: forming, update_every: 5s` |
| True rolling window | `window: 300s, update_every: 1s` |

`features.registry.validate_feature_instance()` enforces this and raises rather than
guessing. The deterministic error codes:

| Code | Meaning |
|---|---|
| `AMBIGUOUS_TEMPORAL_SEMANTICS` | `timeframe` + `update_every` without `bar_state`; or `timeframe` + `window` together |
| `FORMING_BAR_UPDATE_REQUIRED` | `bar_state: forming` without `update_every` |
| `FORMING_BAR_UPDATE_INVALID` | `update_every` exceeds the `timeframe` |
| `COMPLETED_BAR_UPDATE_FREQUENCY_INVALID` | `update_every` on a completed calendar bar |
| `ROLLING_WINDOW_UPDATE_REQUIRED` | `window` without `update_every` |
| `FORMING_BAR_UNSUPPORTED` | provider supports completed bars only |
| `UNSUPPORTED_TIMEFRAME_PARAMETER` / `UNSUPPORTED_UPDATE_CADENCE` | outside the definition's declared support |
| `UNKNOWN_CANONICAL_FEATURE` / `UNKNOWN_FEATURE_PARAMETER` | not in the active bundle / not in the parameter schema |
| `MISSING_REQUIRED_FEATURE_PARAMETER` | a required parameter was omitted |
| `UNVERIFIED_CANONICAL_FEATURE` | definition exists but is not `verified` in the active bundle |

There is no "sensible default" path through any of these. Ambiguous timeframe semantics
fail closed.

### Feature authority and activation

The active canonical bundle is selected by an atomic pointer,
`features/authority/active.json`, which currently points at the reviewed candidate bundle
(`activation_kind: feature_pipeline_v2`, 129 canonical definitions, 693 legacy aliases with
deterministic parity evidence).

- `features.candidate_authority.load_authority("active"|"candidate")` — the only loader.
  A candidate is never selected by environment variable, ambient state, or fallback.
- `scripts/prepare_feature_candidate.py` / `materialize_feature_candidate.py` — build a
  candidate bundle.
- `scripts/authorize_feature_candidate_activation.py` — bind reviews to the exact bytes.
- `scripts/activate_feature_pipeline_v2.py` — verify parity evidence, then flip the pointer.

### Legacy / alias policy

| | |
|---|---|
| Active runtime | **canonical only** |
| `source: canonical_verified_definition_universe` | the active path |
| `source: verified_registry_numeric_universe` | legacy; raises `LEGACY_FEATURE_ALIAS_NOT_ALLOWED` unless `legacy_mode=True` |
| Active fallback to legacy aliases | **prohibited** — there is no automatic fallback and none may be added |
| New studies using physical alias names | **prohibited** |
| Historical replay | permitted only through an explicit, isolated `legacy_mode=True` call |
| `features/archive/legacy_registry_2026_08_22/` | V1 rollback archive; non-runtime |

Legacy alias behaviour is a compatibility surface for reproducing historical datasets. It
is not a development option and must never be presented as one.

### Adding a feature

1. Check the active bundle first: `features/CANONICAL_FEATURE_REFERENCE.yaml`, or
   `python scripts/feature_ctl.py` to resolve a request.
2. If the formula genuinely does not exist, extend or add a **parameterized provider** in
   `features/trackers/generic_*.py`. Do not add a new provider merely to support another
   timeframe, window, or period — that is a parameter.
3. Add the canonical definition, with `parameter_schema`, `supported_bar_states`,
   `supported_timeframes`, null and reset policies.
4. Tests in `features/tests/` that **name the feature**.
5. Promotion to `verified` is enforced, not asserted:
   `scripts/check_feature_promotion.py` requires the implementation to resolve, a test that
   names the feature, and an explicit promotion record naming the causal-audit artifact and
   the audited execution composite. See `features/FEATURE_REGISTRY_CONTRACT.md`.
6. Declare the instance in `study.yaml`, recompile, re-run preflight.

**Never** bypass `FEATURE_NOT_REGISTERED` / `UNKNOWN_CANONICAL_FEATURE` with a hand-built
script or an inline pandas calculation. Fix it at the canonical layer.

---

## 3. The lifecycle

```
        research_decision.yaml   (AUTHORITATIVE)
                  |
              SPEC.md   ->   study.yaml
                  |
        [1] PREPARE  + FREEZE            research_workflow.prepare
                  |                      -> audit/frozen_execution_manifest.json
        [2] READINESS (R1-R10)           research_workflow.readiness
                  |                      -> audit/readiness.json
        [3] bounded PREFLIGHT            research_workflow.preflight
                  |                      -> audit/preflight.json (+ failure_packet.json)
        [4] CAUSAL / LOOKAHEAD REVIEW    lookahead-auditor | research_workflow.causal_audit
                  |                      -> audit/pass_NN.md + audit/status.json
        [5] CONTRACT REVIEW              contract-checker | research_workflow.contract_audit
                  |                      -> audit/contract_pass_NN.md + contract_status.json
        [6] SEAL                         research_workflow.seal
                  |                      -> artifacts/preexec_audit_seal.json
        [7] NT SMOKE (1 day)             research_workflow.smoke / run_nt_study --stage day
                  |                      -> runs/<ts>_collect_day/ + validation_report.json
        [8] RECONCILIATION               scripts/reconcile_runs.py
                  |                      -> runs/<...>/lifecycle.json
        [9] AUTHORIZE EXPERIMENT         research_workflow.experiment.authorize_experiment
                  |                      -> artifacts/experiment_authorization.json
       [10] GOVERNED TRAIN COLLECTION    collection.collect_period_partitioned
                  |                      -> one run dir per year partition
       [11] PARTITION RECONCILE + MERGE  partitioning.reconcile_partitions / merge_partition_outputs
                  |
       [12] TRAIN MODELING + VALIDATION  research_workflow.modeling.fit_models
                  |                      -> artifacts/experiment_models.json
       [13] TRAIN ARTIFACT FREEZE        modeling.freeze_train_artifacts
                  |                      -> artifacts/train_experiment_freeze.json
       [14] OOS OPENING                  experiment.assert_oos_open   <-- the only door
                  |
       [15] OOS COLLECTION + SCORING     collection.collect_period(..., "oos")
                  |
       [16] ANALYSIS                     research_workflow.analysis.analyze_results
                  |                      -> artifacts/experiment_analysis.json
       [17] DECISION                     results/STUDY_REPORT.md / next research_decision
```

`research_workflow/lifecycle.py` is the small facade: `prepare`, `readiness`,
`bounded_preflight`, `seal`, `run_smoke`, `authorize_experiment_stage`,
`collect_experiment_period`, `open_oos`.

### Stage detail

| # | Stage | Entry point | Output | Fails when |
|---|---|---|---|---|
| 1 | PREPARE + FREEZE | `python -m research_workflow.prepare --study studies/<id>` | `audit/frozen_execution_manifest.json` | compile error, phase0 regeneration error |
| 2 | READINESS | `python -m research_workflow.readiness --study studies/<id>` | `audit/readiness.json` | any of R1–R10 |
| 3 | PREFLIGHT | `python -m research_workflow.preflight --study studies/<id>` | `audit/preflight.json` | any required check missing **or** failing |
| 4 | CAUSAL | `lookahead-auditor` agent, or `research_workflow.causal_audit.run_causal_review` | `audit/pass_NN.md`, `audit/status.json` | CRITICAL findings > 0, or stale freeze |
| 5 | CONTRACT | `contract-checker` agent, or `research_workflow.contract_audit.run_contract_review` | `audit/contract_pass_NN.md`, `audit/contract_status.json` | missing deliverable, unreachable terminal label |
| 6 | SEAL | `research_workflow.seal.generate_preexec_audit_seal` | `artifacts/preexec_audit_seal.json` | `PREEXEC_AUDIT_STALE` |
| 7 | SMOKE | `python backtests/run_nt_study.py --study studies/<id> --mode collect --stage day` | `runs/<ts>_collect_day/` | runtime error, zero events, schema/surface violation |
| 8 | RECONCILE | `python scripts/reconcile_runs.py` | `lifecycle.json` sidecars | — (classification only) |
| 9 | AUTHORIZE | `experiment.authorize_experiment` | `artifacts/experiment_authorization.json` | chronology missing or overlapping |
| 10 | TRAIN COLLECT | `collection.collect_period_partitioned(..., execute=True)` | run dirs | authorization mismatch, prohibited year |
| 11 | MERGE | `partitioning.merge_partition_outputs` | merged frame | overlap, schema/dtype drift |
| 12 | FIT | `modeling.fit_models` | `artifacts/experiment_models.json` | non-TRAIN partition, outcome column in X |
| 13 | FREEZE | `modeling.freeze_train_artifacts` | `artifacts/train_experiment_freeze.json` | non-TRAIN meta, outcome column in a frozen feature set |
| 14 | OOS OPEN | `experiment.assert_oos_open` | freeze payload | `TrainFreezeRequired` |
| 15 | OOS | `collection.collect_period(..., "oos")` | run dirs | freeze absent or stale |
| 16 | ANALYSIS | `analysis.analyze_results` | `artifacts/experiment_analysis.json` | missing columns, OOS not open |

### Three rules about the shape of this lifecycle

1. **Expensive preflight happens late.** READINESS (§4) is deliberately positioned before
   PREFLIGHT, the audits and the seal, because it proves the *real* NT runtime path is safe
   using bounded real samples. Failing at R1 costs seconds; failing after a full audit round
   costs a re-audit.
2. **FREEZE goes stale after any execution-affecting change.** The frozen composite is
   resolved from the study's whole execution closure
   (`scripts/resolve_execution_manifest.py`). Both audit reviews re-resolve it and refuse
   with `STALE_FREEZE` if it moved. After fixing anything inside the closure, re-run PREPARE
   and redo stages 3–6. **`research_workflow/__init__.py` is inside that closure** — even a
   cosmetic edit to `__all__` stales a sealed study.
3. **Targeted tests beat global CI.** `research_workflow/test_selection.py` (via
   `scripts/select_required_tests.py`) selects the tests a change actually requires.
   Repeatedly running the full suite is not diligence, it is latency.

### TRAIN / OOS discipline

`research_workflow/experiment.py` is the whole authority. Concretely:

- `chronology.train` / `chronology.dev` / `chronology.prohibited` in `study.yaml` must be
  non-empty (train, dev) and pairwise disjoint.
- The authorization is content-hashed; `load_authorization` refuses a stale artifact.
- `runtime_authorization(study, "oos")` calls `assert_oos_open` *before* producing dates and
  stamps `train_freeze_sha256` into the plan. `verify_runtime_authorization` re-checks that
  binding at the NT boundary and rejects prohibited years.
- **OOS may not influence** feature selection, preprocessing, model class,
  hyperparameters, calibration, thresholds, or deciles. All of those are fields of
  `train_experiment_freeze.json` and are frozen before OOS opens.
- Thresholds and deciles carry `derivation_population: "train"`.

**Smoke acceptance must use the authoritative population.** A smoke run accepted against a
convenience subset proves nothing about the population the study will actually emit;
`scripts/validate_smoke.py` and `OutputManager` re-derive the feature surface independently
for exactly this reason.

---

## 4. READINESS gate (R1–R10)

`research_workflow/readiness.py`. Every check fails closed with a specific exception. A
failed R1 short-circuits R2–R7 as `R1_PREREQUISITE_FAILED` (they all depend on `DataPlan`);
R8 and R9 are independent and always run.

| Check | Proves |
|---|---|
| R1 | exact physical dataset identity: declared == `DatasetSpec` == resolved == opened, with warmup-through-run coverage |
| R2 | 1s / 1m `ts_init - ts_event` contracts on real bounded samples; derived 5m path via `CompletedMinuteFiveMinuteAggregator` (no external 5m stream) |
| R3 | loaded bars are precision-compatible with the governed instrument |
| R4 | callback causal order, via a minimal probe strategy and the existing verifier |
| R5 | the real collector constructs under real phase0 authorization (construction only, no `engine.run()`) |
| R6 | the `STRATEGY_OUTPUT_INTERFACE_MISSING` contract |
| R7 | a synthetic candidate/observation fixture validates through the real `OutputManager` |
| R8 | the execution identity resolves twice with exact equality and no mutation |
| R9 | zero alternate (ungoverned) catalog openers under `studies/<id>/**/*.py` |
| R10 | bounded real first-nonempty collector output parity against the collection-time feature contract |

`audit/readiness.json` is **additive evidence**. It never rewrites
`frozen_execution_manifest.json`, `status.json`, or any other immutable stage artifact, and
it is not a second execution-identity authority.

---

## 5. Deterministic PREFLIGHT

`research_workflow/preflight.py`. Required checks for a study:

```
EXECUTION_MANIFEST  CAUSAL_LINT  ARTIFACT_SCHEMA
FEATURE_PROMOTION   RESEARCH_DECISION_FIDELITY   CAUSAL_INVARIANTS
```

Readiness is a **two-part claim**: every required check *executed*, **and** every one
passed. `--skip-tests` remains available for diagnostics but cannot report
`READY_FOR_AUDIT` — a check that never ran cannot fail, and that used to make skipping a
check *increase* the reported readiness.

Outputs `audit/preflight.json` and, on failure, `audit/failure_packet.json`. Read the
failure packet; do not re-derive the failure by hand.

---

## 6. Lookahead / causal audit vs. model integrity

These answer different questions and must not be merged or duplicated.

```
LOOKAHEAD / CAUSAL AUDIT
    "Could this information legally be known at T?"

MODEL INTEGRITY
    "Is the feature/model surface scientifically sane and nondegenerate?"
```

### 6.1 The lookahead/causal system (already exists — do not build another)

| Layer | Implementation | Kind |
|---|---|---|
| AST lint | `scripts/causal_lint.py` | deterministic, inside preflight |
| Ruleset | `docs/CAUSAL_CHECKLIST.md` (A1–H4) | single source of truth for all three harnesses |
| Causal reviewer | `lookahead-auditor` agent — owns **A, B, C1–C3, F, G, H** | LLM gate |
| Contract reviewer | `contract-checker` agent — owns **C4, D, E**, deliverables, seals | LLM gate |
| Executable review | `research_workflow/causal_audit.py`, `contract_audit.py` | deterministic composition of the above evidence |
| Provenance | `scripts/run_preexec_audits.py`, `research_workflow/seal.py` | binds report bytes to the audited composite |

The two reviewers have **disjoint scope** and neither may report the other's category. That
boundary is what stopped multi-pass audit loops (one study historically ran 18 passes).
Re-audits: pass 2+ must adjudicate every prior finding before raising new ones, at most 3
new CRITICALs per pass, and always a **new** `audit/pass_NN.md` file — never an append.

Gates read `audit/status.json` / `audit/contract_status.json`. Never prose.

### 6.2 Event-order guarantees

Generic guarantees, verified by R2/R4 and `utils/causal_registration.py`:

- 1s bars are dispatched before the parent 1m bar for the same close instant
  (`add_bars_causal_order`, `verify_callback_causal_order`).
- Catalog bars keep open-stamped `ts_event`; `ts_init = ts_event + bar_duration_ns`, so the
  event loop delivers a bar only at interval close.
- Derived timeframes (e.g. 5m) are aggregated from *completed* lower-timeframe bars, never
  loaded as an independent stream.

For the current regime-flip family of studies, the verified per-event ordering is:
completed 1s state update -> checkpoint snapshot -> candidate registration -> horizon
handling -> coincident completed-timeframe regime update. **That ordering is a property of
that study family**, documented in its own `SPEC.md` and audit passes. Do not hardcode it
into infrastructure documentation or infrastructure code.

### 6.3 Model integrity — implemented vs. available vs. recommended

Governance correctness, causal correctness and scientific integrity are three separate
concerns. Be precise about which controls are actually enforced.

**Implemented hard gates (fail closed, inside the lifecycle):**

| Control | Where |
|---|---|
| Declared feature contract == produced surface; an **all-null column is refused under either null policy** | `scripts/check_feature_surface.py`, enforced in `OutputManager.persist_collection` *and* re-derived independently in `scripts/validate_smoke.py` |
| Forward-outcome columns may not enter a fit feature matrix or a frozen feature set | `research_workflow/forward_outcomes/guard.py` via `modeling.fit_models` and `modeling.freeze_train_artifacts` |
| Outcome columns in `X` rejected at fit time | `research/analysis/modeling.fit_model` (`SchemaSurplus`) |
| TRAIN and DEV may not appear in one fit | `fit_model` (`PartitionMixing`) |
| Refuses to fit without partition provenance | `fit_model` (`PartitionProvenanceMissing`) — absence of a `_partition` column is not evidence of a single partition |
| Threshold freeze requires TRAIN-only scores and records `derivation_population` | `research/analysis/modeling.freeze_threshold` |
| Declared model arms must request features the collection actually provides | `research/analysis/modeling.resolve_arms` (`SchemaMissing`) |
| Model/feature-order binding, binary classes, `predict_proba` | `scripts/check_model_binding.py` (a preflight check) |
| `train_test_split(shuffle=True)` on temporal data | `scripts/causal_lint.py` rule C3, CRITICAL |
| Degenerate slice detection surfaces a caveat rather than a silent single group | `research/analysis/slices.py`, `reporting.py` |

**Available diagnostics (exist, but are not unconditional lifecycle gates):**

- `scripts/verify_collector_parity.py`, `scripts/check_collect_equivalence.py` — full and
  persisted output parity.
- `scripts/run_full_legacy_feature_parity.py` — the 693-alias legacy→canonical parity matrix.
- `scripts/find_first_parity_divergence.py` — first-divergence localization.
- `scripts/run_vertical_slice.py` — 10-stage end-to-end composition gate on a synthetic
  partition.
- `scripts/diagnose_collector_gap.py`, `scripts/run_collector_ablation_matrix.py`,
  `scripts/benchmark_historical_same_harness.py`.

**Recommended integrity checks (the study must perform and report these; they are not
mechanically enforced today — do not claim otherwise):**

- Every declared feature is actually *populated* where its semantics require a value.
- Every required feature has **variance** on the fitted population.
- Each model arm has the feature surface it claims. Two nominally distinct arms producing
  **identical scores** means the added block is dead — compare `prediction_identity()` /
  `fit_identity_sha256` across arms before reporting a delta.
- Score surfaces are nondegenerate (not constant, not accidentally near-binary).
- Frozen thresholds and deciles are nondegenerate (distinct boundaries, non-empty bins).
- A shuffled-label run behaves near chance when performed.
- Temporal validation is chronological.
- Suspiciously strong single-feature predictive power triggers inspection before it is
  reported as a finding.

If a study reports an arm delta, it must state which of these it verified. An unverified
delta between arms is a hypothesis, not a result.

---

## 7. The generic collector

**The authoritative collection path is `research_workflow/generic_collector.py`, executed
through `backtests/run_nt_study.py --mode collect`.**

Studies do **not** copy a historical bespoke collector, subclass one, wrap one, or import
one from a sibling study directory. Ever.

How it works:

1. `study.yaml` declares canonical `FeatureInstance`s.
2. `research_workflow/compiler.py` compiles them; the **provider dependency closure** is
   derived from the declared instances, not discovered at runtime.
3. `research_workflow/phase0.py` materializes the phase-zero authorization manifest from the
   compiled instances. No study module is imported and no historical alias catalog is
   consulted.
4. `research_workflow/execution_plan.py` binds the resolved provider methods and output
   surface **once**, at strategy construction, into fixed callback groups. A declared
   instance whose provider has no output binding is retained as a null column (the
   historical contract) without paying for an unused calculation at every checkpoint.
5. `research_workflow/output_manager.py` persists, and enforces the schema and feature
   surface at persistence time.

Compact snapshot paths and compiled callback grouping are **implementation details**.
Canonical output parity is **mandatory**, and is what the parity scripts verify.

**ETH state may remain causally necessary even when candidate emission is RTH.** Session
filtering governs which candidates are *emitted*; it does not govern which bars the
providers are allowed to *see*. Do not "optimize" by cutting ETH history out of the replay.

### Partitioned TRAIN collection

`research_workflow/partitioning.py` + `collection.collect_period_partitioned`.

A `PartitionSpec` carries three intervals:

```
warmup prefix          [warmup_start, primary_end]      causal context only
primary emission       [primary_start, primary_end]     the ONLY rows retained
forward lookahead      [primary_end, lookahead_end]     target / outcome resolution
```

- `lookahead_seconds` defaults to `target.horizon_seconds` from `study.yaml`.
- At a chronology boundary the lookahead is replayed only if it stays inside an authorized
  year; otherwise the lower-level authorization stays fail-closed and the target contract's
  session/data-end censoring handles the unresolved tail.
- Each year runs in its **own process** (`ProcessPoolExecutor(max_workers=1)`, one worker
  created and torn down per partition). NautilusTrader's Rust logger is process-global and
  cannot be initialized twice in one interpreter, so a reused worker panics on the second
  year — and per-process isolation is what makes partitioning genuinely memory-bounded.
- `retain_primary_rows()` drops warmup/lookahead rows **after** replay, so filtering can
  never change causal state.
- `reconcile_partitions()` rejects duplicate ids, overlapping primary intervals, and
  incompatible authority hashes.
- `merge_partition_outputs()` is deterministic: identical column order, lossless numeric
  dtype promotion only (an all-null `float64` column merging with a populated `int64` one is
  resolved once, at the merge boundary; arbitrary object coercion is rejected), duplicate
  primary keys rejected, stable `mergesort` ordering.

**Partitioned vs. monolithic parity is mandatory.** A partitioned collection that does not
reproduce the monolithic result is a defect, not a variant.

---

## 8. Performance and telemetry

The durable lesson, stated once:

- **Telemetry must not materially alter execution performance.**
- **`tracemalloc` is opt-in.** It instruments every allocation and captures a traceback for
  each one; left always-on it cost this collector ~6–7x replay wall time (measured
  2026-08-24: 5.73s -> 35.24s on a 213,431-event smoke day). Enable it with
  `NT_TELEMETRY_TRACEMALLOC=1` or `CausalTelemetry(trace_allocations=True)`. Process RSS
  telemetry is always collected and is cheap.
- **Benchmark harnesses must separate replay cost from instrumentation cost.** A throughput
  number measured with allocation tracing on is a number about tracing.
- **Compare the generic collector under controlled same-harness conditions.** Use
  `scripts/benchmark_historical_same_harness.py`, which runs historical controls through the
  canonical data-plan/engine builder.

Any claim that the generic collector is intrinsically slow is obsolete. It was an
instrumentation artifact.

---

## 9. Forward outcomes / economic path

`research_workflow/forward_outcomes/` — reusable and study-agnostic. It imports no regime
engine, no flip definition, no instrument, no classifier.

### The architectural separation

```
causal features     what was knowable at decision time      -> model INPUTS
proposed entry      immutable decision/entry anchor         -> the boundary
forward outcome     what happened afterwards                -> LABELS, never inputs
```

### Modules

| Module | Role |
|---|---|
| `contracts.py` | `ProposedEntry` (frozen, `entry_sha256`), `ForwardOutcomeSpec` (frozen, `spec_sha256`), `Direction`, `OutcomeStatus`, `ReferencePrice`, `BarInclusion`, `ConfirmationSpec`; `build_outcome_columns()` **derives** the output schema from the spec |
| `tracker.py` | `ForwardOutcomeTracker` — streaming observation of active entries |
| `selection.py` | Build entries from frozen scores: `first_crossing_entries`, `threshold_crossing_entries`, `score_decile_entries`, `local_score_maximum_entries`, `assign_frozen_deciles`, `validate_frozen_threshold` |
| `partition.py` | `required_lookahead_seconds`, `build_outcome_partitions`, `merge_outcome_partitions`, `assert_partition_parity` |
| `guard.py` | The causal guard (§10) |
| `governance.py` | `write_outcome_artifacts`, `reconcile_outcome_artifacts`, code identity, provenance |
| `analysis.py` | `summarize_outcomes`, `summarize_group`, `confidence_ranking_report` — descriptive only |
| `smoke.py` | Streaming-vs-bruteforce infrastructure smoke on a real bounded day |

### Guarantees

- **Streaming active-entry tracking.** One small `ForwardObservation` per live entry, with
  running extrema and a horizon cursor. Work per bar is O(active observations). **Full
  future paths are never retained.** Not-yet-started entries wait in an `entry_ts`-ordered
  queue; finished ones are reachable only through a lazily validated expiry heap. Nothing
  scans the historical entry set.
- **Partition-safe forward resolution.** `required_lookahead_seconds(spec)` sizes the
  lookahead from the spec; `assert_partition_parity` proves the partitioned result equals
  the monolithic one.
- **Explicit censoring.** `RESOLVED`, `CENSORED_SESSION`, `CENSORED_HORIZON`,
  `CENSORED_DATA_END`, `MISSING_DATA`. A record's overall status is the **worst** status any
  part reached, so a path with one unobservable horizon can never be reported as `RESOLVED`.
- **No silent horizon shortening.** A horizon exceeding `max_tracking_seconds` raises at
  spec construction. A confirmation `max_wait_seconds` the tracking budget cannot cover
  raises too, rather than leaving "confirmed?" permanently unanswerable.
- **Entry-time ATR normalization.** ATR is taken at the entry anchor and is a field of the
  entry; it is never recomputed from the future path.
- **Bar-resolution honesty.** Excursion timestamps resolve to the close of the bar that set
  the extremum. When one bar touches a favourable and an adverse diagnostic level in the
  same interval the ordering is unknowable, and the record says so
  (`first_touch_ambiguous_*`) rather than guessing.
- **Bar inclusion.** `FULLY_FORWARD` (default) admits a bar only when its whole interval is
  at or after `entry_ts`. A bar straddling the entry contains pre-entry price action.
- **Signal-entry vs. confirmation-entry analysis** are separate entry families producing
  separate artifact directories, compared explicitly — never pooled.

### Artifact separation

Four artifact classes stay in separate files:

```
candidate features   ->  collection output          (causal)
model scores         ->  scoring output             (causal, from the frozen model)
proposed entries     ->  proposed_entries.parquet   (causal identity)
forward outcomes     ->  forward_outcomes.parquet   (OUTCOME_LABEL_POST_EVENT)
```

Every outcome artifact carries `forward_outcome_manifest.json` with
`data_class: OUTCOME_LABEL_POST_EVENT`, `causal_relative_to_entry: false`,
`usable_as_model_input: false`, the `spec_sha256`, and the exact outcome column list.

---

## 10. Production causal outcome guard

`research_workflow/forward_outcomes/guard.py`. **Fail-closed.** It raises
`OutcomeLeakError`; there is no warning mode.

Protection exists at two production surfaces:

1. **Fit-time feature surface** — `modeling.fit_models` calls
   `guard_training_frame(X, list(X.columns))`. It checks the declared feature list **and**
   any outcome columns riding along in the frame, because the common accident is a frame
   joined with outcomes and a fitter that later re-derives its own column list from the
   frame.
2. **TRAIN artifact freeze surface** — `modeling.freeze_train_artifacts` calls
   `assert_causal_feature_surface` on **every arm's frozen feature set**. Guarding both is
   deliberate: a set can be assembled and frozen without ever passing through a fitter, and
   a leak frozen into the contract outlives the run.

Detection uses three barriers, none of them naive substring matching:

- **Exact.** `outcome_column_namespace(spec)` regenerates the schema from the spec, so the
  guard knows precisely which columns a given spec produces.
- **Structural.** `OUTCOME_COLUMN_PATTERNS` — anchored regexes matching the *generated
  naming grammar* (`^(mfe|mae|return)_\d+s(_atr|_ticks)?$`, `^max_mfe(_atr)?$`,
  `^(pre|post)_confirmation_.+$`, `^outcome_status$`, and so on).
- **Registry.** `assert_outcome_columns_not_registrable(spec)` asserts that no outcome
  column resolves through `features.registry`. If one did, a study contract could legally
  declare it and every downstream causal check would pass.

### The semantic constraint that must not be broken

These are **legitimate causal features** and must never be rejected:

```
prior_1m_regime_mfe_atr
rolling_300s_giveback_atr
rolling_300s_max_progress_atr
running_mfe_atr
current_progress_atr
```

They describe the past as of the decision. `mfe_300s`, `max_mfe_atr` and `time_to_max_mfe`
describe the future after the entry. The patterns are anchored to the generated grammar
precisely so the first group passes and the second is caught. **Do not "tighten" the guard
with an unanchored substring match** — it would reject the study's own inputs.

Identity columns shared with the entry table (`entry_id`, `decision_ts`, `entry_price`,
`entry_atr`, `score`, `score_decile`, `maturity_bucket`, and the rest of
`CAUSAL_IDENTITY_COLUMNS`) are exempt by name, so joining outcomes back to entries does not
trip the guard.

---

## 11. Scripts

`mutates?` = writes to the repository or to `runs/`. `sealed-safe?` = safe to run while a
study is sealed and in flight, i.e. cannot change the execution composite or a stage
artifact.

### Lifecycle (execution)

| Script | Purpose | When | Mutates | Sealed-safe |
|---|---|---|---|---|
| `create_study.py` | scaffold a study tree from `study.yaml` | study creation | yes | n/a |
| `compile_study.py` | compile + validate contracts | after any contract edit | yes (`compiled_study.json`) | **no** |
| `prepare_and_freeze.py` | PREPARE + FREEZE the execution composite | stage 1 | yes | **no** |
| `build_phase0_manifest.py` | regenerate the phase-zero manifest | inside PREPARE | yes | **no** |
| `resolve_execution_manifest.py` | resolve the execution closure + composite | any time | no | yes |
| `research_preflight.py` | deterministic preflight orchestrator | stage 3 | yes (`audit/*.json`) | yes |
| `run_preexec_audits.py` | ingest an audit report, verify provenance, issue status | stages 4–5 | yes (`audit/status.json`) | yes |
| `preexec_audit_seal.py` | generate / verify the pre-execution seal | stage 6 | yes (`artifacts/`) | yes |
| `run_bounded_study.py` | run a stage under time/memory/stale-progress limits, emit a JSON status card | stages 7, 10, 15 | yes (`runs/`) | yes |
| `reconcile_runs.py` | classify run lifecycle; assign `ABANDONED` by PID liveness | stage 8, and before relaunching | yes (`lifecycle.json` sidecar only; never rewrites `run_manifest.json`) | yes |
| `generate_oos_unlock.py` | legacy per-study OOS dependency-chain verifier | historical studies only | yes | yes |

> The generic OOS authority is `research_workflow.experiment.assert_oos_open`, bound to
> `artifacts/train_experiment_freeze.json`. `generate_oos_unlock.py` predates it and remains
> for studies that were built against it.

### Governance / validation

| Script | Purpose | Mutates | Sealed-safe |
|---|---|---|---|
| `causal_lint.py` | AST lint for recurring causal defects | no | yes |
| `check_artifact_schema.py` | artifact + seal manifest schema and DAG validation | no | yes |
| `check_model_binding.py` | model sha, feature count/order, binary classes, `predict_proba` | no | yes |
| `check_feature_surface.py` | declared contract == produced surface; all-null column refusal | no | yes |
| `check_feature_promotion.py` | feature lifecycle promotion evidence | no | yes |
| `check_candidate_promotion.py` | promotion facts for an inactive canonical authority | no | yes |
| `check_research_decision_fidelity.py` | `research_decision.yaml` -> SPEC/study fidelity | no | yes |
| `check_spec_fidelity.py` | SPEC -> `StudySpec` fidelity | no | yes |
| `check_collect_equivalence.py` | full-collection equivalence against a reference | no | yes |
| `scan_alternate_catalog_openers.py` | static guard: ungoverned catalog opens under a study | no | yes |
| `validate_smoke.py` | canonical smoke acceptance (re-derives the feature surface) | yes (`validation_report.json`) | yes |
| `validate_data.py` | raw file and catalog integrity | no | yes |
| `select_required_tests.py` | choose the tests a change actually requires | no | yes |
| `bootstrap_audit_lineage.py` | record a study's durable audit lineage anchor | yes | **no** |
| `describe_study_diff.py` | describe what changed between study states | no | yes |
| `build_audit_packet.py` | assemble the contextual diff packet for an auditor | yes | yes |
| `safe_cleanup.py` | fail-closed guard for recursive deletion (§13) | yes (deletes) | — |
| `sync_agents.py` | regenerate Codex + Antigravity agent defs from `.claude/agents/` | yes | yes |

### Feature system

| Script | Purpose | Mutates | Sealed-safe |
|---|---|---|---|
| `feature_ctl.py` | V2 canonical feature governance CLI: check and promote | yes (promote) | yes (check) |
| `generate_canonical_feature_reference.py` | regenerate `CANONICAL_FEATURE_REFERENCE.yaml` | yes | yes |
| `prepare_feature_candidate.py` | prepare + freeze an inactive candidate authority | yes | yes |
| `materialize_feature_candidate.py` | materialize the final candidate bundle | yes | yes |
| `authorize_feature_candidate_activation.py` | bind review evidence to candidate bytes | yes | yes |
| `activate_feature_pipeline_v2.py` | verify parity, then atomically flip the active pointer | yes | **no** |
| `run_full_legacy_feature_parity.py` | 693-alias legacy→canonical parity matrix | yes (matrix) | yes |
| `audit_full_feature_system_v2_inventory.py` | normalize V1 physical features for V2 | yes | yes |
| `build_canonical_promotion_inventory.py` | provider-grouped promotion evidence | yes | yes |
| `archive_legacy_feature_registry.py` | create + verify the V1 rollback archive | yes | yes |
| `restore_legacy_feature_file.py` | restore one archived legacy source file exactly | yes | **no** |
| `migrate_cleanflip_feature_instances.py` | one-off historical migration | yes | **no** |

### Diagnostics / benchmarking (never a gate)

| Script | Purpose |
|---|---|
| `find_first_parity_divergence.py` | first-divergence localization — **mandatory first step for any parity failure** |
| `verify_collector_parity.py` | full collector run vs. every persisted field |
| `diagnose_collector_gap.py` | locate the replay-time gap between collectors |
| `run_collector_ablation_matrix.py` | benchmark-only ablation matrix on one replay day |
| `benchmark_historical_same_harness.py` | historical controls through the canonical harness |
| `run_vertical_slice.py` | 10-stage end-to-end composition gate on a synthetic partition |
| `run_isolated_sweeps.py` | isolated parameter sweeps |
| `capture_baseline_fixtures.py` | capture baseline fixtures |
| `check_mbp1_cost.py` | Databento MBP-1 download cost preflight |
| `export_notebook_knowledge_base.py` | export a knowledge-base bundle |

### Data / catalog

| Script | Purpose | Mutates |
|---|---|---|
| `build_v0_catalog.py` | generic raw-parquet -> NT catalog materializer | yes |
| `build_es_v0_2020_2026_catalog.py` | ES.v.0 2020–2026 catalog | yes |
| `build_dense_1s.py` | calendar-aligned dense 1s parquet from immutable raw bars | yes |
| `preflight_dense_1s.py` | preflight for the dense-1s utility | no |

### Compatibility shims — not primary entry points

These redirect to `research_workflow`. Prefer the module.

| Shim | Redirects to |
|---|---|
| `scripts/research_preflight.py` | `research_workflow.preflight` |
| `scripts/compile_study.py` | `research_workflow.compiler` |
| `scripts/create_study.py` | `research_workflow.study_factory` |
| `scripts/prepare_and_freeze.py` | `research_workflow.prepare` |
| `scripts/preexec_audit_seal.py` | `research_workflow.seal` |
| `scripts/build_phase0_manifest.py` | `research_workflow.phase0` |
| `scripts/select_required_tests.py` | `research_workflow.test_selection` |
| `backtests/nt_runtime/output_manager.py` | `research_workflow.output_manager` |
| `backtests/nt_runtime/readiness.py` | `research_workflow.readiness` |

---

## 12. Autonomy policy

**A gate failure means: do not advance past the gate.**
It does **not** mean: stop the task and report `BLOCKED`.

Agents should, autonomously and without asking:

- diagnose deterministic defects (read `audit/failure_packet.json`, the exception, the diff)
- fix them at the owning layer
- add or update **targeted** tests that pin the defect
- re-run the affected **bounded** checks — not the whole suite
- regenerate stale deterministic artifacts (recompile, re-run PREPARE to re-freeze,
  regenerate the phase-zero manifest, regenerate the canonical feature reference)
- resume from the correct lifecycle stage, not from the beginning

A `BLOCKED` preflight is an instruction to *fix*, not an instruction to *stop*.

### Terminal stop conditions

Stop and report only for:

1. **Genuine semantic ambiguity** — two defensible readings of the research question or the
   contract that produce materially different experiments.
2. **Data safety risk** — see §13.
3. **Authorization ambiguity** — unclear whether a period, dataset, or action is authorized.
4. **Inability to preserve causality or TRAIN/OOS correctness** — the only available fix
   would require look-ahead, OOS tuning, or breaking a freeze.
5. **Capability gap** — the harness genuinely cannot express what the study needs. Report
   the specific missing capability (`ANALYSIS_HARNESS_GAP`, `BESPOKE_JUSTIFICATION`), not
   "it didn't work".
6. **Prohibited data access risk** — the next step would touch a prohibited year or an
   unauthorized source.

When you do stop, say which of these six it is.

### Failure routing

| Error code | Owning layer / fix |
|---|---|
| `UNKNOWN_CANONICAL_FEATURE`, `UNVERIFIED_CANONICAL_FEATURE` | canonical bundle / promotion evidence |
| `AMBIGUOUS_TEMPORAL_SEMANTICS` and the other instance codes (§2) | `study.yaml` instance parameters |
| `LEGACY_FEATURE_ALIAS_NOT_ALLOWED` | you used a physical alias — declare a canonical instance |
| `FEATURE_LIST_MISMATCH` | recompile the study |
| `UNREGISTERED_STRATEGY`, `STRATEGY_NOT_BOUND` | `STRATEGY_REGISTRY` in `backtests/nt_runtime/strategy_binding.py` |
| `CONFIG_UNKNOWN_KEYS` | align the YAML key with the config schema |
| `STALE_FREEZE`, `PREEXEC_AUDIT_STALE` | re-run PREPARE, then redo stages 3–6 |
| `MANIFEST_RESOLUTION_FAILED` | `scripts/resolve_execution_manifest.py` |
| `OUTCOME_COLUMN_IN_CAUSAL_SURFACE` / `_IN_TRAINING_FRAME` | drop the outcome columns; never loosen the guard |
| `PartitionProvenanceMissing` | pass `meta` with `_partition`, or an explicit recorded `SplitPolicy` opt-out |
| `PartitionMixing` | you are fitting across TRAIN and DEV |
| `TrainFreezeRequired` | OOS is locked; freeze TRAIN artifacts first |
| any parity failure | **first** run `scripts/find_first_parity_divergence.py`. No broad investigation before first-divergence localization |

### Escalation rule (modifying shared framework code)

You may modify `research_workflow/`, `research/`, `backtests/nt_runtime/`, `utils/runner/`,
`features/` or `scripts/` only if **all** of these hold:

1. A concrete study genuinely cannot be expressed by the existing capability.
2. The failure is **not** caused by a missing feature instance declaration, a missing
   strategy registration, YAML/CLI misuse, a stale audit or seal, or caller misuse.
3. You document the missing capability explicitly (`BESPOKE_JUSTIFICATION`, or the study
   `SPEC.md`).

Otherwise fix it in user space: `study.yaml`, the canonical feature bundle, `strategies/`,
`tests/`.

---

## 13. Data safety

**Before any recursive deletion or cleanup:**

1. Inspect every descendant for **symlinks, junctions, mount points and Windows reparse
   points** that escape the intended root. `os.path.islink()` returns `False` for a Windows
   directory junction — check reparse points, not just symlinks.
2. Resolve before you delete. A path that *looks* inside the root is not necessarily inside
   it; `Path.resolve()` decides, not the string.
3. Confirm the target is inside repository-owned storage. `data/catalog/` in particular may
   be a link to storage that lives outside the repository.
4. **Fail closed.** If any descendant resolves outside the intended disposable root, abort
   the whole operation. Do not delete "the safe part" — a partial delete of a tree you did
   not fully understand is exactly how 179 GB was destroyed here once.

`scripts/safe_cleanup.py::assert_safe_to_delete` implements this. Use it, or replicate it,
before any recursive removal of a directory you did not create in this session.

**Never junction live `data/` into a disposable worktree.**

**Never silently substitute a dataset.** If the authorized source is unavailable, fail
closed and report it. A result computed from a substitute source is not the result that was
asked for, and nothing downstream will notice the difference.

---

## 14. Current research pattern

Prediction of a **structural** event and prediction of a **tradable** event are distinct
research questions. Do not mix them.

```
STUDY 1 — PREDICTION
    Predict a structural event.        e.g. P(regime flip within 300s)
    Validate clean OOS predictive signal.
    Freeze the predictor.              train_experiment_freeze.json

STUDY 2 — ECONOMICS (observational)
    Use the FROZEN scores/thresholds/deciles to create immutable proposed-entry anchors.
    Observe the forward path with research_workflow/forward_outcomes/:
        MFE, MAE, fixed-horizon returns, confirmation timing,
        pre/post-confirmation path, declared diagnostic levels.
    Ask only: does predictor confidence RANK economic quality?
    model_fit: prohibited.  strategy_optimization: prohibited.

STUDY 3 — ECONOMIC-QUALITY MODEL (only if Study 2 warrants it)
    Train against a declared economic target:
        P(clean tradable reversal) | E[MFE] | E[MAE] | E[return] | target-before-stop

STUDY 4 — STRATEGY OPTIMIZATION
    Last, and only after the above.
```

The generic progression:

1. identify a structural hypothesis
2. collect causal features
3. train and freeze a predictor
4. validate clean OOS predictive signal
5. freeze high-confidence proposed-entry anchors
6. use `forward_outcomes` to observe the subsequent path
7. determine whether predictor confidence ranks economic quality
8. only then consider an economic-quality target or an actual strategy

`studies/frozen_flip_score_forward_path_2024/` is the reference implementation of Study 2:
it consumes the frozen artifacts of `clean_maturity_flip_model_rolling_productivity`,
declares `model_fit: prohibited` and `economic_use: observational_only`, and produces
separate `signal_entries/` and `confirmation_entries/` artifact sets.

A study built this way is **not** licensed to tune anything on OOS. Observation is not
optimization.

---

## 15. Analysis discipline

Pandas and Polars are computation libraries, **not** a second governed workflow.

```
validated collection -> research/analysis/ -> AnalysisSpec + validation contracts -> authoritative result
```

Scratch pandas work is legitimate and encouraged for **debugging and forensic inspection**.
Its outputs are **NON-AUTHORITATIVE** and must be labelled so. They may not be quoted as a
study result, entered into a report as a finding, or used to close a research question.

If `research/analysis/` cannot express what a study requires, that is a harness gap, not a
licence to route around it. Stop and report `ANALYSIS_HARNESS_GAP`, naming the missing
capability.

**Do not wrap or duplicate canonical runners.** Use `scripts/run_bounded_study.py` and read
its JSON status card. Do not launch a second identical run while one is `RUNNING` — confirm
with `scripts/reconcile_runs.py`, which classifies a run as `RUNNING` only when its recorded
PID is genuinely alive.

---

## 16. Study directory convention

```
studies/<study_id>/
├── research_decision.yaml    AUTHORITATIVE decision contract      [git]
├── SPEC.md                   derived from research_decision.yaml  [git]
├── study.yaml                machine contract, FeatureInstances   [git]
├── compiled_study.json       compiled, sha256-bound               [git]
├── config/                   feature/population/target/deliverables contracts [git]
├── implementation/           small declarative hooks only, often absent       [git]
├── tests/                    study contract tests                 [git]
├── audit/
│   ├── frozen_execution_manifest.json
│   ├── readiness.json
│   ├── preflight.json  failure_packet.json
│   ├── pass_NN.md            status.json           (causal)       [git]
│   └── contract_pass_NN.md   contract_status.json  (contract)     [git]
├── artifacts/
│   ├── phase0_source_manifest.json
│   ├── preexec_audit_seal.json
│   ├── experiment_authorization.json
│   ├── experiment_models.json
│   ├── train_experiment_freeze.json
│   └── experiment_analysis.json                                   [git]
└── results/STUDY_REPORT.md                                        [git]
```

**Contract authority:** `research_decision.yaml > SPEC.md > study.yaml > compiled_study.json > code`.

Create or verify `research_decision.yaml` **before** drafting or modifying `SPEC.md`.
Nothing compiles or passes preflight unless
`python scripts/check_research_decision_fidelity.py --study studies/<id>` passes.

**Behavioural rule:** never improve, broaden, clean up, or make a study more statistically
pure by changing a fixed baseline or adding feature discovery unless the decision contract
explicitly permits it. Surface a design concern as a caveat; do not silently alter the
experiment.

**Never commit generated data** — `runs/`, `canonical_*/`, `_work/`, `*.parquet`,
`*.joblib`, `*.onnx`. Commit the manifests instead.

---

## 17. Timestamps

- Raw Databento OHLCV bars are **OPEN-stamped** (`ts_event`). Complete OHLCV is usable only
  at interval close.
- Offline research normalizes derived bars to **CLOSE-stamped** indices
  (`label='right', closed='left'`).
- NT catalogs preserve open-stamped `ts_event` and set
  `ts_init = ts_event + bar_duration_ns` (1s +1s, 1m +60s, 3m +180s, 5m +300s), so the event
  loop dispatches completed bars at interval close.
- 1s bars therefore arrive **before** their parent 1m bar. Buffer recent 1s bars and replay
  them retroactively from fill time, or you will miss the first minute of price action.
- Display and analysis in Central Time (`America/Chicago`); NT internals are UTC.
  RTH 08:30–15:15 CT.

---

## 18. What is authoritative, what is deprecated

**Authoritative now**

- Feature System V2, canonical-only active runtime (`features/authority/`, `features/registry.py`)
- `research_workflow/` as the reusable governed lifecycle
- `research_workflow/generic_collector.py` + the compiled execution plan
- Memory-safe year-partitioned TRAIN collection with deterministic merge and parity
- Governed TRAIN/OOS lifecycle via `research_workflow/experiment.py`
- Production outcome-column causal guard at fit time and freeze time
- `research_workflow/forward_outcomes/` for economic-path observation
- `research/analysis/` — present in the main tree and imported by `research_workflow`

**Deprecated / historical**

- Feature System V1 physical names and `features/FEATURES.md` — superseded by
  `features/CANONICAL_FEATURE_REFERENCE.yaml`
- Legacy alias resolution as an active path
- Bespoke per-study collectors (`strategies/*_collector.py`, `collectors/`,
  `studies/*/implementation/collector.py`)
- Legacy `backtests/run_*.py` scripts — frozen references, not templates
- `scripts/generate_oos_unlock.py` as the primary OOS authority
- The root-level `*_HARDENING_*`, `*_HARNESS_*_REPORT`, `*_RFC*`, `*PLAYBOOK*` and
  `PROPOSED_*` documents — see `docs/DOCUMENT_MAP.md`

**Future studies should:** declare canonical `FeatureInstance`s, use the generic collector,
partition TRAIN by year, freeze before OOS, and observe economics through `forward_outcomes`
rather than by building a bespoke outcome collector.

---

## 19. Deeper references

| Topic | Document |
|---|---|
| Causal/contract audit ruleset A1–H4 | `docs/CAUSAL_CHECKLIST.md` |
| Catalog wrangling, building, validation | `docs/DATA_CATALOG.md` |
| Backtest runner, sweeps, YAML configs | `docs/BACKTEST_EXECUTION.md` |
| Feature collection, MFE/MAE replay pattern | `docs/STUDY_METHODOLOGY.md` |
| SPEC templates, Deliverables Manifest | `docs/TEMPLATES.md` |
| Reporting and tearsheets | `docs/ANALYSIS_REPORTING.md` |
| Profiling, ONNX inference | `docs/PERFORMANCE.md` |
| Error code registry | `docs/ERROR_REGISTRY.md` |
| Feature lifecycle + promotion contract | `features/FEATURE_REGISTRY_CONTRACT.md` |
| Canonical feature vocabulary | `features/CANONICAL_FEATURE_REFERENCE.yaml` |
| Analysis harness contract | `ANALYSIS_HARNESS_A0_CONTRACT.md` |
| Backtest harness boundary | `BACKTEST_HARNESS_B0_BOUNDARY.md` |
| READINESS R1–R10 design | `ML_Trend_Analysis_Workflow_V2_Phase1_FINAL.md` §8 |
| Classification of every doc in the repo | `docs/DOCUMENT_MAP.md` |

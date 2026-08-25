<!-- DOC-STATUS-BANNER -->
> **[DESIGN CONTRACT — CITED BY LIVE CODE]**
>
> `research_workflow/readiness.py` and `scripts/tests/test_readiness.py` cite §8 of this document for the R1-R10 readiness contract.
>
> Section numbers here are load-bearing. Do not renumber, delete, or casually edit.
> This is a frozen contract, not a workflow manual — the current workflow is
> **`docs/RESEARCH_WORKFLOW.md`**. Classification: `docs/DOCUMENT_MAP.md`.

# ML Trend Analysis Workflow V2 — Phase 1 Corrected RFC v2

**Status:** FINAL — IMPLEMENTATION AUTHORITY  
**Supersedes:** `ML_Trend_Analysis_Workflow_V2_Phase1_Corrected_RFC.md`  
**Basis:** Independent delta red-team review against the current repository and recent governed run artifacts  
**Primary goal:** Finish one governed CleanFlip vertical slice reliably without replacing hardened infrastructure or changing research semantics.

**Final review status:** CLEAR. All M1–M13 corrections incorporated; final wording corrections T1–T3 applied. Safe to hand to bounded coding agents.

---

## 1. Executive Verdict

The original Workflow V2 proposal is superseded.

Phase 1 is a **surgical hardening pass** around the current NautilusTrader runtime and governance stack.

The current repository already has stronger implementations for:

- `StudySpec`
- compilation
- execution-closure hashing
- freeze / seal
- mandatory preflight gates
- output enforcement
- governed `BacktestEngine` execution

Phase 1 therefore **does not rebuild those systems**.

### Phase 1 must eliminate the actual observed blockers

Recent governed runs failed on:

1. an unexpected canonical dense timeline gap
2. `UNEXPECTED_OUTPUT_COLUMN` from registry feature columns
3. `UNEXPECTED_OUTPUT_COLUMN` from metadata columns

Therefore the Phase 1 failure list must include both anticipated and observed defects.

### Phase 1 objectives

1. exact physical runtime dataset binding
2. fail-closed catalog resolution
3. catalog-aware loader caching
4. per-stream timestamp readiness checks
5. actual runtime callback-order verification
6. study-local test inclusion in mandatory preflight
7. zero-row output contract enforcement
8. non-empty registry-universe output contract support
9. exact candidate/observation reconciliation
10. explicit population-funnel accounting
11. result-to-frozen-composite reconciliation
12. compact error reporting using existing evidence structure

---

## 2. Governing Principle

Workflow refactoring has **no authority to change research semantics**.

Any implementation that would change:

- candidate identity
- candidate timestamp
- population membership
- state-update sequencing
- feature semantics
- target definition
- label clock
- censoring
- session behavior
- TRAIN/DEV/OOS boundaries

must stop with:

`RESEARCH_DECISION_REQUIRED`

---

## 3. Frozen Research-Authority Decisions

### D1 — Population ordering

**PRESERVE CURRENT BEHAVIOR.**

Feature/state updates that currently occur before candidate qualification remain before candidate qualification.

No Phase 1 change may move:

- feature updates
- geometry updates
- running MFE state
- progress-window state
- retained-MFE state
- regime maturity state

across the qualification boundary.

### D2 — Opposite regime flip

**PRESERVE CURRENT BEHAVIOR.**

The opposite flip remains target-label information for this study.

It is not a generic forward-tracker terminal event.

### D3 — Session-close semantics

**PRESERVE CURRENT BEHAVIOR.**

RTH remains an emission/eligibility rule as currently implemented.

No new session-close horizon termination is introduced.

### D4 — Label clock

**PRESERVE CURRENT 1-MINUTE LABEL-RESOLUTION CLOCK.**

Candidates may originate on 1-second callbacks while labels resolve on the 1-minute clock.

### D5 — Feature readiness

**PRESERVE CURRENT HARD-FAIL SEMANTICS.**

Feature unavailability may not silently suppress, admit, default, or relabel a candidate.

### D6 — Chronology / OOS

**PRESERVE CURRENT `StudySpec` AND `data_plan` ENFORCEMENT.**

Retain:

- TRAIN / DEV / prohibited chronology
- exact authorized dates
- OOS unlock
- warmup-domain authorization
- research-decision fidelity

### D7 — Dense vs current runtime catalog

**UNRESOLVED FOR THIS EXISTING STUDY.**

Changing the event stream may change state evolution and censoring.

Phase 1 does not change sparse/dense semantics unless separately authorized.

### D8 — Population denominator

For Phase 1:

```text
total_population_checkpoints
=
5s-aligned checkpoints for which a completed 1s bar was actually dispatched
```

It is **not** the wall-clock 5-second grid.

Changing that denominator requires a D7 research decision.

---

## 4. Existing Infrastructure to Preserve

### KEEP / EXTEND

- `research/schemas/study_spec.py`
- `scripts/compile_study.py`
- `scripts/prepare_and_freeze.py`
- `scripts/resolve_execution_manifest.py`
- `scripts/research_preflight.py`
- existing causal and contract audit machinery
- existing pre-execution seal
- `backtests/nt_runtime/data_plan.py`
- `backtests/nt_runtime/catalog_materializer.py`
- `backtests/nt_runtime/output_manager.py`
- `backtests/nt_runtime/modes/collect.py`
- current `BacktestEngine` path
- current causal registration helpers
- representative study collector
- current feature registry / feature engine
- study-local tests
- current output and run-manifest machinery

### DO NOT BUILD / REPLACE IN PHASE 1

- replacement `StudySpec`
- new execution-identity algorithm
- `GenericResearchActor`
- Actor migration
- new generic `ForwardTracker`
- block semver registry
- new pytest-only preflight
- monolithic `workflow_state.json`
- manual NT `Bar(...)` construction replacing `BarDataWrangler`

---

## 5. Phase 1 Workstreams

Phase 1 contains five required workstreams plus one optional documentation task.

### P1 — Dataset binding and resolver hardening

Required.

### P2 — Runtime-path READINESS

Required.

### P3 — Study-test inclusion

Required.

### P4 — Output contract correction

Required.

This now covers both:

- zero-row contract enforcement
- non-empty registry-universe collection output

### P5 — Population-funnel instrumentation

Required.

### P6 — Error registry documentation

Useful but non-blocking.

Existing failure packet/status infrastructure should be reused rather than rebuilt.

---

# 6. Dataset Binding Design

## 6.1 Dataset declaration location

**No new field may be added anywhere in the `StudySpec` model in Phase 1.**

`StudySpec.compute_sha256()` hashes the full model, including nested models, so adding a field to `FeaturesSpec` or any other nested schema has the same broad invalidation effect as adding a top-level field.

The study dataset reference must be declared under the existing free-form execution data requirements:

```yaml
execution:
  data_requirements:
    dataset_id: NQ_<dataset_id>
```

This follows the existing `authorized_dates` precedent and avoids re-hashing every study by expanding the strict top-level schema.

---

## 6.2 Dataset authority files

Use standalone immutable YAML files:

```text
research/
└── datasets/
    └── NQ_<dataset_id>.yaml
```

Do **not** create `registry.json` in Phase 1 unless a concrete consumer is introduced.

The YAML is the authority.

---

## 6.3 DatasetSpec

Add only a small dataset schema, for example:

```text
research/schemas/dataset_spec.py
```

It is a binding layer over the current runtime resolver, not a parallel data-plan system.

Required conceptual fields:

```yaml
dataset_id:
instrument_id:
catalog_rel_path:

provenance:
  source:
  manifest_path:
  expected_hash:

streams:
  1s:
    source: external
    bar_type:
    source_timestamp_semantics: interval_open
    availability_rule: interval_end
    ts_init_delta_ns: 1000000000

  1m:
    source: external
    bar_type:
    source_timestamp_semantics: interval_open
    availability_rule: interval_end
    ts_init_delta_ns: 60000000000

  5m:
    source: derived
    external_catalog_stream: false
    derived_from: 1m
    aggregator: CompletedMinuteFiveMinuteAggregator

coverage:
  start:
  end:
```

For the representative study, 5m is **not** an external stream.

It is derived from completed 1m bars.

No coding agent may add a 5m catalog stream merely because the YAML has MTF context.

---

## 6.4 Timestamp rule

For externally supplied OPEN-stamped time bars:

```text
ts_event = source interval-open timestamp
ts_init  = ts_event + bar interval
```

Per-stream expected deltas are verification contracts.

Examples:

```text
1s -> +1s
1m -> +60s
```

The current `BarDataWrangler` path remains authoritative.

Phase 1 must not replace it with manual `Bar(...)` construction.

---

## 6.5 Single runtime authority

Required invariant:

```text
study-declared dataset_id
==
DatasetSpec catalog identity
==
resolve_catalog_plan result
==
catalog actually opened by governed runtime
```

### Required resolver hardening

1. remove or fail-close the current CWD fallback in catalog resolution
2. require runtime to use the same declared dataset identity
3. compare physical dataset identity/provenance during READINESS
4. include warmup coverage, not just nominal run dates

---

## 6.6 Alternate runtime entrypoints

The representative study contains an alternate entrypoint:

```text
studies/Codex_clean_maturity_flip_rolling_5m_productivity/
implementation/run_collect.py
```

which opens a hardcoded catalog and bypasses governed resolution.

Phase 1 must **quarantine or remove this as an executable study path**, or otherwise make it fail closed.

READINESS must assert that no alternate catalog opener exists anywhere under:

```text
studies/<study>/**/*.py
```

This scan is intentionally **not** limited to the execution closure, because the current `implementation/run_collect.py` escape path is outside that closure.

The governed entrypoint must be the only authorized path for Phase 1 acceptance.

---

## 6.7 CausalDataLoader cache correctness

`CausalDataLoader` uses a process-global/class-level bar cache.

The cache key must include the resolved physical catalog identity/path.

A cache key of only:

```text
(bar_type, start, end)
```

is insufficient.

Required conceptual key:

```text
(catalog_identity, bar_type, start, end)
```

This prevents READINESS on one catalog from contaminating a later run using another catalog in the same process.

---

## 6.8 Execution closure

The referenced DatasetSpec YAML **must** be added to the existing execution closure.

This is mandatory, not optional.

The closure should include only the dataset authority referenced by the current study, not a blanket glob over every dataset YAML.

Acceptance test:

```text
post-freeze edit to referenced DatasetSpec
→ frozen identity/seal becomes stale
```

Editing an unrelated instrument's DatasetSpec must not invalidate the current NQ study.

---

# 7. PREPARE Contract

Keep the existing preparation architecture.

PREPARE remains the only stage permitted to mutate execution-affecting derived artifacts.

### Preserve

- current `StudySpec`
- research decision hierarchy
- compile step
- phase0/source manifest
- chronology/OOS controls
- transitive execution-manifest resolution

### Add

1. read `execution.data_requirements.dataset_id`
2. resolve referenced DatasetSpec
3. resolve exact physical governed runtime catalog
4. bind dataset provenance into prepared execution state
5. verify required external streams
6. verify requested + warmup coverage
7. reject fallback/alternate catalog substitution
8. ensure referenced DatasetSpec is part of execution closure

---

# 8. READINESS Contract

READINESS uses the same governed runtime mechanics as the study:

- `BacktestEngine`
- same engine builder
- same data loader
- same external bar types
- same `add_data` causal registration
- same collector hosting mode

No `BacktestNode` path is introduced.

## R1 — Exact physical source

Verify:

- dataset id
- DatasetSpec
- resolved catalog
- actual catalog opened
- provenance/hash/materialization identity
- requested run-window coverage
- warmup-window coverage

## R2 — Timestamp contracts

For the actual external streams:

```text
1s
1m
```

load bounded real samples and verify expected `ts_init - ts_event`.

For 5m:

validate the existing `CompletedMinuteFiveMinuteAggregator` path from completed 1m bars.

Do not invent an external 5m stream.

## R3 — Instrument precision

Validate loaded bars against the real NT instrument definition.

## R4 — Callback causal order

Use a **minimal probe strategy** whose only purpose is to record:

```text
(ts_init, timeframe)
```

callbacks.

Feed those tuples to the existing:

```text
verify_callback_causal_order
```

or equivalent existing validator.

The real collector is **not** required to expose an event trace.

## R5 — Real collector instantiation

Separately instantiate the actual representative collector with the prepared contract and phase0 authorization.

## R6 — Output interface

Reuse the existing `STRATEGY_OUTPUT_INTERFACE_MISSING` logic.

READINESS may invoke/reuse it earlier but must not reimplement a second validator.

## R7 — Synthetic schema fixture

Use a deterministic fixture to prove the output layer can validate and persist the declared schema surface.

This does not establish a productive real population.

## R8 — Identity stability

Resolve the prepared execution identity twice with no mutation.

Require exact equality.

## R9 — Alternate catalog opener check

Scan:

```text
studies/<study>/**/*.py
```

and fail if any executable study path constructs or opens a catalog outside `resolve_catalog_plan`.

Do not scope this check to the execution closure; the purpose is to catch out-of-closure escape paths such as the current `implementation/run_collect.py`.

---

# 9. Execution Identity

Keep `scripts/resolve_execution_manifest.py` authoritative.

Do not redesign it.

### Required Phase 1 extension

Add the referenced DatasetSpec YAML as a dataset authority file in the existing closure.

The closure remains:

- transitive runtime execution closure
- contract/compilation authority closure
- governance closure
- study contract files
- referenced dataset authority
- canonical normalized hashing
- deterministic serialization

Required:

```text
coverage_pct == 100.0
unresolved_dependencies == []
```

---

# 10. Study Preflight

Keep `scripts/research_preflight.py`.

All six mandatory gates remain.

## Priority 1 — Study-test discovery

The representative study's local tests must become part of the mandatory selected test surface.

The current selector must discover:

```text
studies/<study>/tests/test_*.py
```

in addition to framework tests.

The study-test surface is currently effectively zero inside the mandatory selector and must be corrected.

## Priority 2 — Selector JSON hygiene

Fix `select_required_tests.py --json` imports / runtime errors.

This is useful hygiene but is **not** the blocking mandatory-path defect.

## Preserve

- mandatory non-pytest governance gates
- fail-safe broad fallback when dependency ownership is unresolved
- current measured/budgeted runtime behavior

No `<30s` target is part of Phase 1.

---

# 11. Output Contract — Zero-Row and Non-Empty Paths

This is a central Phase 1 blocker.

## 11.1 Zero-row contract

Even with zero rows, the output system must validate:

- required metadata columns
- required candidate keys
- required observation keys
- duplicate-column prohibition
- declared output surface
- feature-order/hash contract where applicable

No schema check may become vacuous merely because a DataFrame is empty.

---

## 11.2 Real-smoke population

The real zero-candidate smoke guard already exists in `validate_smoke.py`.

Phase 1 should reference and preserve it.

Do not build a duplicate.

---

## 11.3 Non-empty registry-universe output contract

The representative study collects from a verified registry numeric universe before a later TRAIN-stage Top-N feature freeze.

Therefore:

```text
features.feature_list == null
```

at collection time can be intentional.

A frozen model feature list is **not** the same thing as the allowed collection-time candidate feature universe.

Phase 1 must express the collection-time output surface using the **existing** `FeaturesSpec` fields already present in the repo:

```text
features.source
features.metadata_columns
```

No new `FeaturesSpec` field may be added in Phase 1.

For this study, `features.source` represents the collection-time candidate universe (for example, `verified_registry_numeric_universe`), while the later frozen model feature list remains a separate downstream artifact/selection.

### Required behavior

At collection time, the output layer must know:

1. allowed metadata columns
2. allowed registry-derived feature universe
3. exact candidate key
4. exact observation key
5. columns forbidden from persistence
6. feature lifecycle/nullability rules

### Metadata authority

`metadata_columns` must come from one canonical contract surface.

Remove the duplicate hardcoded `declared_metadata` authority inside the representative collector.

The collector and `OutputManager` must not maintain independent copies of the same schema definition.

### Governance consequence

This change affects `compiled_study.json`.

Therefore:

- apply through the normal research contract/compile path
- re-freeze deliberately
- do not patch the output manager around the contract

---

## 11.4 Candidate key

For the representative study, repo evidence confirms the canonical key:

```text
observation_ts
regime_start_ns
checkpoint_index
```

Reconciliation must require the full key.

It may not derive the key from the intersection of whichever columns happen to survive.

Missing key field => hard failure.

---

# 12. Population Funnel

## 12.1 Denominator

Phase 1 defines:

```text
total_population_checkpoints
=
observed 5s-aligned checkpoints for which a completed 1s bar was dispatched
```

Not the synthetic wall-clock grid.

---

## 12.2 Required invariant

```text
total_population_checkpoints
=
declared_contract_exclusions
+ implementation_only_exclusions
+ candidates_emitted
```

The categories must be exhaustive and mutually exclusive.

---

## 12.3 Qualification-fail branch

The existing branch where the declared qualification gates fail is a:

```text
declared_contract_exclusion
```

and must be counted before returning.

This is telemetry/accounting only.

Eligibility logic and sequencing may not change.

---

## 12.4 Implementation-only exclusions

`implementation_only_exclusions` must either:

- be incremented by real implementation-only branches, or
- be proven structurally unreachable

A counter that is initialized to zero and never updated is not evidence.

For a mature frozen contract:

```text
implementation_only_exclusions == 0
```

is required at acceptance.

---

## 12.5 Persistence path

Population funnel instrumentation is not collector-only.

Packet E may require bounded changes to:

- representative collector telemetry
- `backtests/nt_runtime/telemetry.py`
- `backtests/nt_runtime/modes/collect.py`
- `backtests/nt_runtime/output_manager.py`

The funnel must be persisted into machine-readable run/result artifacts.

---

# 13. Candidate / Observation Reconciliation

Require the full candidate key:

```text
observation_ts
regime_start_ns
checkpoint_index
```

No intersection-derived narrowing.

Required identity:

```text
positive
+ negative
+ censored
+ unresolved
=
candidates
```

For the current study, acceptance expects:

```text
unresolved == 0
```

after normal shutdown/censor handling.

---

# 14. Error Taxonomy

Use the existing failure/status machinery.

Do not build a new runtime error subsystem.

Document and preserve existing codes where possible.

Minimum taxonomy:

| Error | Earliest Stage |
|---|---|
| `WRONG_PHYSICAL_DATASET` | PREPARE / READINESS |
| `SPARSE_DENSE_BINDING_MISMATCH` | PREPARE |
| `TS_INIT_CONTRACT_MISSING` | PREPARE |
| `TS_INIT_DELTA_MISMATCH` | READINESS |
| `DOUBLE_TS_INIT_SHIFT` | READINESS |
| `CALLBACK_CAUSAL_ORDER_VIOLATION` | READINESS |
| `INSTRUMENT_PRECISION_MISMATCH` | READINESS |
| `OUTPUT_SCHEMA_CONTRACT_FAILED` | READINESS |
| `UNEXPECTED_OUTPUT_COLUMN` | output persistence |
| `FEATURE_READINESS_SCOPE_ESCALATION` | existing fail-closed path |
| `IMPLEMENTATION_ONLY_POPULATION_EXCLUSION` | RECONCILIATION |
| `TARGET_RECONCILIATION_FAILED` | RECONCILIATION |
| `POST_FREEZE_MUTATION` | existing freeze boundary |
| `STALE_AUDIT_EVIDENCE` | PREFLIGHT / launch |
| `UNRESOLVED_TEST_DEPENDENCY_FALLBACK` | PREFLIGHT report |
| `REGISTRY_INCOMPLETE` | PREPARE |
| `SESSION_CLASSIFICATION_MISMATCH` | PREFLIGHT |
| `UNAUTHORIZED_EXECUTION_DOMAIN` | existing data-plan gate |

Also record the observed run blockers in the project error map.

---

# 15. Evidence / Results

Preserve separate:

- prepared/frozen identity
- preflight evidence
- audit evidence
- seal
- run manifest
- result manifest
- optional mutable convenience status

No later stage may rewrite earlier immutable evidence.

---

# 16. Revised Implementation Packets

## A1 — DatasetSpec + Dataset Authority + Closure

### Allowed scope

- add `research/schemas/dataset_spec.py`
- add referenced `research/datasets/<dataset>.yaml`
- extend execution closure to include the referenced DatasetSpec

### Requirement

Study reference lives at:

```text
execution.data_requirements.dataset_id
```

No new top-level StudySpec field.

### Acceptance

- referenced DatasetSpec sealed
- unrelated DatasetSpec does not invalidate study
- post-freeze edit to referenced DatasetSpec invalidates seal

---

## A2 — Resolver + Loader Hardening

### Likely scope

- `backtests/nt_runtime/data_plan.py`
- `utils/runner/data.py`
- targeted tests

### Requirements

- remove/fail-close CWD catalog fallback
- same declared/resolved/opened catalog
- catalog identity included in `CausalDataLoader` cache key
- warmup + run coverage checked

---

## A3 — Alternate Entrypoint Quarantine

### Target

```text
studies/Codex_clean_maturity_flip_rolling_5m_productivity/
implementation/run_collect.py
```

### Requirement

It may not remain an accepted alternate governed execution path that opens a hardcoded catalog outside `resolve_catalog_plan`.

READINESS must detect alternate catalog openers on the governed study execution surface.

---

## B — Runtime READINESS

### Reuse

- current engine builder
- current loader
- causal registration
- existing output-interface check

### Add

- source identity
- warmup coverage
- 1s/1m timestamp verification
- derived 5m aggregation verification
- precision
- callback-order probe strategy
- real collector instantiation
- schema fixture
- identity double-resolution
- alternate-opener check

---

## C — Mandatory Study-Test Inclusion

### Scope

- `scripts/select_required_tests.py`
- selector tests

### Requirements

1. discover/select study-local tests
2. retain all six mandatory gates
3. keep fail-safe broad fallback
4. fix `--json` imports as secondary hygiene

---

## D1 — Zero-Row Output Hardening

### Scope

- `output_manager.py`
- output tests

### Requirement

Schema/key enforcement remains active at zero rows.

---

## D2 — Registry-Universe Collection Output Contract

### Scope

- existing research contract/compiler surfaces
- output manager
- representative collector metadata duplication
- tests

### Requirement

Represent:

```text
collection candidate feature universe
```

separately from:

```text
later frozen model feature list
```

Populate metadata columns from one canonical contract.

This is a deliberate contract change and requires normal compile/freeze.

---

## E — Population Funnel

### Scope

- representative collector telemetry
- `nt_runtime/telemetry.py`
- `modes/collect.py`
- `output_manager.py`
- tests

### Requirement

Persist the exact observed-checkpoint funnel.

Qualification-fail branches count as declared contract exclusions.

Implementation-only exclusions must be real or structurally proven impossible.

---

## F — Result/Error Documentation

Non-blocking.

Reuse:

- `finalize_failed`
- `status.json`
- `run_manifest.json`
- `audit/failure_packet.json`

Add only the project error-registry documentation needed for recurring failures.

---

# 17. Acceptance Workflow

```text
RESEARCH DECISION
    ↓
PREPARE
    ↓
READINESS
    ↓
FREEZE
    ↓
STUDY PREFLIGHT
    ↓
CAUSAL REVIEW
    ↓
CONTRACT REVIEW
    ↓
SEAL
    ↓
ONE-DAY AUTHORIZED NT SMOKE
    ↓
POPULATION + TARGET RECONCILIATION
    ↓
RESULT MANIFEST
```

---

# 18. Acceptance Requirements

1. research-decision/spec/study fidelity passes
2. PREPARE mutates only declared execution-affecting outputs
3. dataset reference comes from `execution.data_requirements.dataset_id`
4. declared == resolved == opened catalog identity
5. no alternate hardcoded governed catalog opener
6. requested + warmup coverage valid
7. per-stream timestamp checks pass
8. derived 5m aggregation path passes
9. callback causal order passes via probe
10. real collector instantiates successfully
11. FREEZE identity is stable
12. referenced DatasetSpec is sealed
13. all six mandatory preflight gates pass
14. representative study tests are included
15. causal review passes
16. contract review passes
17. seal verifies
18. one-day smoke uses an explicit authorized known-productive date, e.g.:
   `--expected-smoke-date 2023-10-02`
19. candidate/observation schema passes
20. registry-universe output contract passes on non-empty data
21. full candidate key reconciliation passes
22. population funnel is persisted and balances exactly
23. `implementation_only_exclusions == 0` is meaningful, not a never-updated counter
24. result manifest asserts:
   ```text
   run_manifest.composite_seal_hash
   ==
   frozen_execution_manifest.frozen_execution_composite_sha256
   ```
   and fails on mismatch
25. no manual execution-affecting edits after PREPARE
26. no unnecessary re-freeze

---

# 19. Red-Team Injection Tests

| Defect | Expected detection |
|---|---|
| dataset id missing | PREPARE |
| referenced DatasetSpec missing | PREPARE |
| valid path but wrong physical catalog | READINESS |
| CWD fallback selects different catalog | PREPARE / READINESS |
| loader cache returns bars from prior catalog | loader test / READINESS |
| hardcoded alternate run entrypoint | READINESS / static guard |
| 1s delta missing | READINESS |
| 1s double-shift | READINESS |
| 1m delta wrong | READINESS |
| 5m treated as external | READINESS / contract test |
| callback higher-TF inversion | READINESS |
| zero-row missing metadata | output test |
| non-empty registry feature rejected unexpectedly | output contract test |
| metadata authority disagreement | output contract test |
| candidate key field missing | reconciliation |
| qualification rejection uncounted | funnel test |
| implementation-only branch occurs | reconciliation |
| study-local test omitted | preflight selector test |
| referenced DatasetSpec edited post-freeze | freeze/launch |
| unauthorized 2025/2026 run | existing OOS gate |
| run composite differs from frozen composite | result reconciliation |

---

# 20. Explicit Phase 1 Exclusions

Do not build:

- `GenericResearchActor`
- Actor migration
- generic `ForwardTracker`
- replacement `StudySpec`
- block semver registry
- `research migrate`
- replacement execution-identity algorithm
- monolithic workflow-state authority
- cached MTF
- generalized multi-asset engine
- generalized ML orchestration
- ONNX mandate
- strategy-promotion framework
- UI/dashboard
- automatic causal-audit reasoning
- broad dependency-graph rewrite

---

# 21. Stop Condition

Phase 1 is complete when the representative study passes the governed one-day acceptance flow with:

```text
zero unauthorized catalog substitution
zero timestamp-contract violations
zero callback-order violations
zero omitted mandatory study tests
zero output-contract mismatch
zero unvalidated empty-output schema
zero population-funnel gap
zero implementation-only exclusions
zero composite mismatch
zero manual execution-affecting edits after PREPARE
zero unnecessary re-freezes
```

Then STOP.

Measure:

- total runtime
- readiness runtime
- preflight runtime
- number of agent interventions
- number of reruns
- number of late-stage failures
- study-specific LOC
- common plumbing LOC
- token/context burden

Only after that should the project reconsider a generic collector architecture.

---

# 22. Final Implementation Order

1. **A1 — DatasetSpec + dataset authority + closure**
2. **A2 — Resolver and loader hardening**
3. **A3 — Alternate entrypoint quarantine**
4. **C — Mandatory study-test inclusion**
5. **D1 — Zero-row output hardening**
6. **D2 — Registry-universe non-empty output contract**
7. **E — Population funnel**
8. **B — Runtime READINESS**
9. **F — Error registry documentation**
10. **Run full governed acceptance sequence**

READINESS is implemented after the underlying data/output contracts it is expected to verify.

---

# 23. Final Recommendation

This RFC is now intended to be implementation-ready.

The immediate objective is not architectural purity.

It is:

> **Make the existing governed workflow bind the exact intended data, validate the real runtime path cheaply, persist the intended collection-time feature universe, run the study's actual tests, reconcile every population checkpoint, and finish one authorized CleanFlip smoke without another framework-debugging loop.**

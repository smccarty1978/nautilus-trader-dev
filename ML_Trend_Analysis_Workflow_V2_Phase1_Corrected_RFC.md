<!-- DOC-STATUS-BANNER -->
> **[STALE — SUPERSEDED]**
>
> Superseded by **ML_Trend_Analysis_Workflow_V2_Phase1_FINAL.md**.
>
> Superseded RFC draft.
>
> Kept for its reasoning and for the audit trail. **Not a source of instructions.**
> Classification: `docs/DOCUMENT_MAP.md`.

# ML Trend Analysis Workflow V2 — Phase 1 Corrected Implementation RFC

**Status:** PROPOSED FOR IMPLEMENTATION REVIEW  
**Supersedes:** `ml_trend_analysis_workflow_v2_spec.md` for Phase 1  
**Basis:** Independent red-team findings against the current repository  
**Goal:** Reduce repeated workflow failures and agent/token burden without changing research semantics or replacing hardened infrastructure unnecessarily.

---

## 1. Executive Verdict

The original Workflow V2 RFC is **not** the implementation target.

Phase 1 will be a **surgical hardening pass**, not a framework rewrite.

The repository already contains stronger implementations for several systems the prior RFC proposed to replace:

- strict `StudySpec`
- compilation
- execution-manifest closure
- freeze/pre-execution identity checks
- output-schema enforcement
- preflight governance gates
- existing NautilusTrader `BacktestEngine` runtime path

Phase 1 therefore preserves those systems and fixes only demonstrated gaps.

### Phase 1 objective

Safely execute the representative study through the existing governed workflow while eliminating the specific failure classes that have repeatedly caused wasted runtime and agent effort:

1. wrong physical runtime dataset/catalog
2. timestamp-contract drift
3. study tests omitted from preflight
4. broken targeted-test JSON path
5. zero-candidate schema masking
6. incomplete population-funnel accounting
7. late discovery of callback/data-order defects

### Phase 1 does **not** attempt to eliminate all study-specific Python.

A future modular collector architecture may still be valuable, but it is deferred until its sequencing and target semantics can be proven without changing the experiment.

---

## 2. Governing Principle

Workflow refactoring has **no authority to change research semantics**.

Any implementation that would change:

- candidate identity
- candidate timestamp
- population membership
- regime/reset sequencing
- feature semantics
- target definition
- label clock
- censoring
- session behavior
- OOS boundaries

must stop with:

`RESEARCH_DECISION_REQUIRED`

No coding agent may reinterpret those rules as part of infrastructure cleanup.

---

## 3. Phase 1 Research-Authority Decisions

The representative study's existing semantics are frozen as follows.

### D1 — Population update ordering

**Decision:** PRESERVE CURRENT BEHAVIOR.

State updates that currently occur before candidate qualification remain before candidate qualification.

No refactor may move running MFE, regime maturity, progress-window, retained-MFE, geometry, or related state updates across the qualification boundary without a new research decision.

### D2 — Opposite regime flip

**Decision:** PRESERVE CURRENT BEHAVIOR.

For the representative study, the qualifying opposite flip remains target-label information.

It is **not** converted into a generic forward-tracker terminal event.

### D3 — Session-close behavior

**Decision:** PRESERVE CURRENT BEHAVIOR.

RTH eligibility remains governed by the existing research contract.

Session close is not introduced as a new horizon terminator unless the current study contract already declares it.

### D4 — Label-resolution clock

**Decision:** PRESERVE CURRENT 1-MINUTE LABEL CLOCK.

Candidates may originate on the 1-second clock while flip labels resolve on the 1-minute clock.

Infrastructure must preserve that distinction.

### D5 — Feature readiness

**Decision:** PRESERVE CURRENT HARD-FAIL SEMANTICS.

Feature unavailability may not silently suppress a candidate, admit a candidate, substitute a default, or change the target.

Existing fail-closed behavior remains authoritative.

### D6 — Chronology / OOS policy

**Decision:** PRESERVE EXISTING `StudySpec` AND `data_plan` ENFORCEMENT.

Do not remove or defer:

- TRAIN / DEV / prohibited chronology
- exact authorized dates
- OOS unlock requirements
- warmup-domain restrictions
- research-decision fidelity

### D7 — Dense versus current runtime catalog

**Decision:** UNRESOLVED FOR THE REPRESENTATIVE STUDY.

Canonical dense 1-second data remains the desired long-term data authority.

However, changing this already-defined study from its current runtime stream to dense 1-second data may change population state and censoring behavior.

Therefore a dense/sparse change for this study requires a separate explicit research decision.

Phase 1 must first make the physical runtime dataset **explicit and verifiable**.

---

## 4. Existing Infrastructure to Preserve

The following components are retained unless a concrete Phase 1 defect requires a bounded change.

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
- existing `BacktestEngine` runtime
- existing causal bar-registration helpers
- existing collector for the representative study
- existing feature registry / feature engine
- existing study-specific tests
- existing output persistence and run manifests

### DO NOT REPLACE IN PHASE 1

- current `StudySpec`
- execution identity with single-file/block hashes
- current preflight with a new pytest-only preflight
- current collector with `GenericResearchActor`
- current forward-label logic with `ForwardTracker`
- current split audit/freeze/result evidence with one mutable `workflow_state.json`

---

## 5. Phase 1 Scope

Phase 1 contains six bounded workstreams.

### P1 — Explicit Dataset Binding

Introduce a registered dataset-binding layer that resolves into the **existing runtime data path** rather than creating a parallel authority.

### P2 — Runtime-Path READINESS

Add a cheap readiness gate using the same `BacktestEngine`, loader, bar registration, and runtime configuration as the actual study.

### P3 — Study-Test Selection

Ensure representative-study tests are included in governed preflight selection and fix the existing JSON output defect in the selector.

### P4 — Empty-Output Contract Hardening

Close the zero-candidate path that currently allows schema validation to become vacuous.

### P5 — Population-Funnel Instrumentation

Make every eligible checkpoint resolve deterministically into exactly one accounted category.

### P6 — Structured Failure Reporting

Add compact machine-readable error cards using existing artifact/evidence boundaries; do not create a new monolithic mutable workflow authority.

---

## 6. Dataset Binding Design

### 6.1 Purpose

The dataset layer answers one question:

> Which exact physical data artifact is this study authorized to load at runtime?

It does **not** redefine the research hypothesis and does not replace `StudySpec`.

### 6.2 Proposed location

```text
research/
└── datasets/
    ├── NQ_<dataset_id>.yaml
    ├── ES_<dataset_id>.yaml
    └── registry.json            # generated index, non-authoritative
```

Use one immutable YAML file per dataset.

### 6.3 DatasetSpec role

Add a small dataset schema under the existing schema package, for example:

```text
research/schemas/dataset_spec.py
```

Do not build a second general configuration framework.

The schema must be capable of expressing the actual runtime streams used by the catalog.

### 6.4 Required fields

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
    bar_type:
    source_timestamp_semantics:
    availability_rule:
    ts_init_delta_ns:

  1m:
    bar_type:
    source_timestamp_semantics:
    availability_rule:
    ts_init_delta_ns:

  5m:
    enabled:
    bar_type:
    source_timestamp_semantics:
    availability_rule:
    ts_init_delta_ns:

coverage:
  start:
  end:
```

The exact stream set must reflect the runtime actually consumed by the study.

Do not assume all datasets are single-stream.

### 6.5 Timestamp rule

For an OPEN-stamped external time bar:

```text
ts_event = source interval-open timestamp
ts_init  = ts_event + bar interval
```

The resolved delta is a property of each stream.

Examples:

```text
1s -> 1_000_000_000 ns
1m -> 60_000_000_000 ns
5m -> 300_000_000_000 ns
```

The implementation must preserve the current `BarDataWrangler` path unless a separate review proves replacement is necessary.

Do not manually construct NT `Bar` objects merely to move timestamp logic.

### 6.6 Single resolver rule

The declared DatasetSpec and the runtime resolver must resolve to the **same physical catalog**.

Required invariant:

```text
declared_dataset_id
    ==
resolved_catalog_identity
    ==
catalog_actually_opened_by_runtime
```

Any fallback that allows a different catalog path to be opened must fail closed.

The known CWD fallback in catalog resolution must be reviewed and removed or converted into an explicit failure if it can cause a different physical source to be selected.

---

## 7. PREPARE Contract

Phase 1 keeps the current preparation architecture.

PREPARE remains the only stage allowed to generate execution-affecting derived artifacts.

### PREPARE must preserve

- current `StudySpec` validation
- research-decision hierarchy
- compilation
- phase-0/source-manifest generation where currently required
- chronology / OOS authorization
- execution-manifest resolution
- existing transitive execution closure

### PREPARE additions for Phase 1

1. resolve referenced DatasetSpec
2. resolve the exact physical runtime catalog through the same resolver used later by the runtime
3. bind dataset identity/provenance to the compiled execution state
4. reject undeclared fallback sources
5. confirm requested runtime bar streams exist in the declared dataset contract
6. emit a compact dataset-binding record

### PREPARE must fail on

- dataset id not registered
- physical catalog unresolved
- physical catalog differs from declared dataset
- required stream absent
- missing stream timestamp contract
- requested date outside declared coverage
- dataset provenance mismatch
- unauthorized chronology/OOS domain

---

## 8. READINESS Contract

READINESS is a cheap, non-authoritative validation gate.

It must use the **same runtime path** as the representative study:

- `BacktestEngine`
- same engine builder
- same data loader
- same bar types
- same `add_data` / causal-registration path
- same collector/strategy hosting mode

Do not introduce `BacktestNode` only for READINESS.

### Required checks

#### R1 — Exact physical source identity

Verify dataset id, resolved catalog path, physical catalog opened by runtime, provenance/expected hash or materialization identity, and requested date coverage.

#### R2 — Per-stream timestamp contract

Load a bounded real sample from every stream the study actually uses and assert each stream's declared availability relationship.

If 5m is derived from completed 1m rather than loaded directly, validate the actual aggregation path instead of inventing a 5m external-stream requirement.

#### R3 — Instrument precision

Validate loaded data against the actual NT instrument definition.

#### R4 — Callback causal order

Use the real `BacktestEngine` path and preserve the existing 1s-before-coincident-1m contract.

#### R5 — Import / instantiation

Prove the actual representative collector/strategy can be instantiated with the prepared contract.

#### R6 — Output interface

Verify the actual runtime object exposes required candidate/observation interfaces.

#### R7 — Non-empty output contract fixture

Use a deterministic fixture to test the output schema surface independently of whether the chosen real day happens to emit candidates.

This only validates schema capability. It does **not** replace the real smoke requirement for a known-productive day.

#### R8 — Identity resolution stability

Resolve the prepared execution identity twice without mutation and require identical results.

### READINESS output

Use a stage evidence artifact, not a monolithic mutable workflow file.

```json
{
  "schema_version": 1,
  "study_id": "...",
  "stage": "READINESS",
  "status": "CLEAR",
  "prepared_execution_identity": "...",
  "checks": [],
  "failures": [],
  "artifacts": []
}
```

---

## 9. FREEZE / Execution Identity

Do not redesign the current execution-identity mechanism.

`scripts/resolve_execution_manifest.py` remains authoritative.

Phase 1 may extend the existing closure only if the DatasetSpec or data-binding artifact is not already covered.

### Required properties

- transitive runtime execution closure
- contract/compilation authority closure
- governance closure
- study contract files
- canonical text hashing behavior
- deterministic canonical serialization
- `coverage_pct == 100.0`
- `unresolved_dependencies == []`

### Dataset addition

The frozen identity must include the behavior-affecting dataset-binding evidence required to prove:

```text
declared dataset
==
runtime catalog
```

Do not replace the closure with one block file hash, one actor hash, or one manually concatenated list of hashes.

---

## 10. Study Preflight

Do not replace `scripts/research_preflight.py`.

The six mandatory gates remain.

Phase 1 changes test selection for correctness, not for an arbitrary speed target.

### Required work

1. fix the broken JSON path in `select_required_tests.py`
2. make study-local tests discoverable/selectable
3. preserve mandatory non-pytest governance checks
4. report when dependency ownership is unresolved
5. retain fail-safe broad fallback when dependency ownership is genuinely unknown

### Important principle

The current problem is not simply "too many tests."

The current surface is simultaneously too broad in some framework areas and too narrow because study tests are omitted.

Correctness comes first. Only after selection is correct should runtime be optimized from measured evidence.

No `<30 seconds` target is accepted in Phase 1.

---

## 11. Empty-Output Contract Hardening

The current empty-candidate path must not make schema validation vacuous.

Even with zero candidate rows, the framework must still know and validate declared metadata columns, declared feature columns, duplicate-column prohibition, candidate key contract, observation key contract, and feature-order/hash contract where applicable.

### Two checks remain separate

**Synthetic/schema fixture:** proves the output implementation can emit the required schema.

**Real smoke:** proves a known-productive authorized day actually emits candidates.

A synthetic trigger must not be used to claim the real population is non-empty.

---

## 12. Population Funnel Instrumentation

The representative study must deterministically account for every population checkpoint.

Target invariant:

```text
total_population_checkpoints
=
declared_contract_exclusions
+ implementation_only_exclusions
+ candidates_emitted
```

### Requirements

- every rejection branch maps to an explicit reason
- `not eligible` may not return silently
- implementation-only exclusions are counted
- declared research exclusions and implementation-only exclusions remain distinct
- candidate count reconciles exactly

For a mature frozen research contract:

```text
implementation_only_exclusions == 0
```

unless explicitly authorized.

---

## 13. Candidate / Observation Reconciliation

Do not silently derive reconciliation identity from the intersection of whatever columns happen to exist.

The representative study must declare its canonical candidate key.

If the existing authoritative key is:

```text
observation_ts
regime_start_ns
checkpoint_index
```

then reconciliation must require the full key. Missing key columns fail.

Required identity:

```text
positive + negative + censored + unresolved = candidates
```

with terminal/censor reasons separately accounted.

---

## 14. Error Taxonomy

Phase 1 uses a documented error registry. Do not create a large new runtime subsystem solely for the registry.

Where an equivalent repo error already exists, preserve the existing error string.

Minimum classes:

- `WRONG_PHYSICAL_DATASET`
- `SPARSE_DENSE_BINDING_MISMATCH`
- `TS_INIT_CONTRACT_MISSING`
- `TS_INIT_DELTA_MISMATCH`
- `DOUBLE_TS_INIT_SHIFT`
- `CALLBACK_CAUSAL_ORDER_VIOLATION`
- `INSTRUMENT_PRECISION_MISMATCH`
- `OUTPUT_SCHEMA_CONTRACT_FAILED`
- `EMPTY_REAL_SMOKE_POPULATION`
- `FEATURE_READINESS_SCOPE_ESCALATION`
- `IMPLEMENTATION_ONLY_POPULATION_EXCLUSION`
- `TARGET_RECONCILIATION_FAILED`
- `POST_FREEZE_MUTATION`
- `STALE_AUDIT_EVIDENCE`
- `UNRESOLVED_TEST_DEPENDENCY_FALLBACK`
- `REGISTRY_INCOMPLETE`
- `SESSION_CLASSIFICATION_MISMATCH`
- `UNAUTHORIZED_EXECUTION_DOMAIN`

Each entry should record:

```yaml
error_id:
symptom:
root_cause:
earliest_detection_stage:
deterministic_guard:
regression_test:
status:
```

---

## 15. Evidence / Result Architecture

Do not create one mutable `workflow_state.json` containing immutable evidence.

Preserve separation between mutable workflow/status convenience, immutable/self-binding stage evidence, frozen execution identity, audit evidence, seal, and run/result manifest.

Markdown remains derived from machine-readable truth.

Later stages must never rewrite the evidence that authorized earlier stages.

---

## 16. Phase 1 File-Level Implementation Plan

### Packet A — Dataset Binding

**Likely files:**

- add `research/schemas/dataset_spec.py`
- add `research/datasets/<dataset>.yaml`
- minimally modify `backtests/nt_runtime/data_plan.py`
- minimally modify catalog-resolution configuration if needed

**Goal:** one declared dataset resolves to one runtime physical catalog.

**Do not change:** research semantics, chronology, collector, target, feature logic.

**Tests:** registered dataset resolves; unregistered dataset fails; wrong physical path fails; fallback cannot silently substitute another catalog; requested date coverage checked; existing OOS chronology tests remain green.

### Packet B — Runtime READINESS

**Likely files:** add or extend one readiness script under existing `scripts/`; reuse `engine_builder`, current loader, and causal registration helpers.

**Goal:** catch data/timestamp/runtime defects before full preflight or smoke.

**Tests:** exact physical source, per-stream timestamp delta, callback ordering, precision, actual runtime instantiation, output interface, double identity resolution.

### Packet C — Test Selection Correctness

**Likely files:** `scripts/select_required_tests.py` and related selector tests.

**Goal:** include study tests and fix JSON output while preserving mandatory governance gates.

### Packet D — Empty Output Contract

**Likely files:** `backtests/nt_runtime/output_manager.py` and output-manager tests.

**Goal:** schema remains enforceable with zero rows.

### Packet E — Population Funnel

**Likely files:** representative study collector telemetry only; reconciliation code/tests as needed.

**Goal:** account every checkpoint without changing eligibility semantics.

**Restriction:** no gate logic may change; only instrumentation/accounting may be added.

### Packet F — Result/Error Cards

**Likely files:** existing audit/result artifact helpers plus documentation/error-registry file.

**Goal:** compact deterministic failure output without replacing immutable evidence.

---

## 17. Agent Model Routing

### Cheap / deterministic coding agent

Use for schema addition, registry parser, JSON error formatting, selector import bug, narrow unit tests, documentation/error registry.

### Normal coding model

Use for data resolver integration, readiness implementation, output-manager empty-schema fix, population telemetry instrumentation.

### High-reasoning review

Required for any proposed change touching candidate ordering, target/label resolution, censoring, dense/sparse semantics, OOS/chronology, timestamp availability semantics, or causal registration ordering.

---

## 18. Red-Team Tests After Implementation

Inject at least:

- declared catalog missing
- valid path points to wrong dataset
- runtime resolver points elsewhere
- 1s delta missing
- 1s delta applied twice
- 1m delta incorrect
- coincident 1m callback precedes required 1s state
- undeclared output column
- zero-row frame missing required schema
- known productive smoke returns zero candidates
- population rejection not accounted
- implementation-only exclusion > 0
- post-freeze execution input edit
- unrelated test-file edit
- repeated identity resolution without change
- unauthorized 2025/2026 execution

Each injected failure must be caught at the earliest intended stage.

---

## 19. Phase 1 Acceptance Workflow

The authoritative sequence remains:

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

### Acceptance requirements

1. research-decision/spec/study fidelity passes
2. PREPARE mutates only declared execution-affecting outputs
3. dataset binding resolves to the physical runtime catalog
4. READINESS uses the actual `BacktestEngine` path
5. per-stream timestamp contracts pass
6. callback causal ordering passes
7. FREEZE identity is stable and existing closure remains complete
8. all mandatory preflight gates pass
9. representative study tests are included
10. causal review passes
11. contract review passes
12. seal verifies
13. one authorized known-productive day emits candidates
14. candidate/observation schema passes
15. full candidate-key reconciliation passes
16. population funnel reconciles exactly
17. implementation-only exclusions equal zero
18. no manual execution-affecting edits occur after PREPARE
19. no re-freeze occurs without a deliberate execution change
20. result artifacts bind to the executed identity/seal as required by current governance

---

## 20. Explicit Phase 1 Exclusions

Do **not** build in Phase 1:

- new `GenericResearchActor`
- Actor migration
- new generic `ForwardTracker`
- new StudySpec replacement
- block semantic-version registry
- `research migrate`
- new execution-identity algorithm
- new monolithic workflow-state authority
- cached MTF datasets
- generalized multi-asset engine
- generalized ML orchestration
- ONNX mandate
- full Strategy-promotion architecture
- UI/dashboard
- automatic causal-audit reasoning
- broad dependency-graph rewrite

These remain future candidates only after Phase 1 is measured.

---

## 21. Phase 1 Stop Condition

Phase 1 is complete when the representative study passes the full governed one-day acceptance workflow with:

```text
zero manual execution-affecting edits after PREPARE
zero unauthorized catalog substitution
zero timestamp-contract violations
zero callback-order violations
zero omitted mandatory study tests
zero unvalidated empty-output schemas
zero implementation-only population exclusions
zero population reconciliation gap
zero unnecessary re-freezes
```

At that point: **STOP.**

Do not automatically proceed to generic collector architecture.

Measure runtime, preflight time, number of agent interventions, number of failure loops, study-specific LOC, common plumbing LOC, and token/context burden.

Only then decide whether extracting additional reusable collector blocks produces a net simplification.

---

## 22. Future Architecture Decision Gate

The question of a generic research shell is deferred until Phase 1 evidence exists.

A future proposal must first prove:

1. exact candidate parity against the representative collector
2. exact candidate timestamp parity
3. exact feature parity
4. exact label/censor parity
5. exact reset-state parity
6. no change in OOS policy
7. reduced study-specific code
8. reduced agent context burden

Only after those pass should the project reconsider:

```text
PopulationEngine
FeatureEngine
ForwardTracker
OutputWriter
GenericResearchActor
```

as a production framework abstraction.

---

## 23. Final Recommendation

Implement Phase 1 as a hardening layer around the existing research/runtime architecture.

The immediate goal is not architectural purity.

The immediate goal is:

> **Make the current governed workflow reliably bind the correct data, catch known failures cheaply, run the right tests, reconcile the full population, and finish one real study without repeated framework debugging.**

If Phase 1 achieves that, it has succeeded.

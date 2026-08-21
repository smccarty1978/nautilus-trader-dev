# ML Trend Analysis Workflow V2: Implementation Specification

This specification maps the current repository state to the target modular design, enforcing NautilusTrader's strict causal event model.

---

### 1. Executive Verdict

**PARTIAL REBUILD REQUIRED.** The underlying NautilusTrader runtime, dense 1-second catalogs, and causal review principles are sound. However, the orchestration layer (custom Python compilation, bespoke `collector.py` generation, and fragile preflight test selection) must be replaced by a deterministic, Pydantic-driven CLI control plane and a `GenericResearchActor`.

---

### 2. Repo-Grounded Current Component Map

| Path | Current Responsibility | Reusable? | Target Responsibility | Action |
| --- | --- | --- | --- | --- |
| `study.yaml` | Human configuration | No | `StudySpec` | REPLACE (with Pydantic schema) |
| `scripts/compile_study.py` | Custom Python validation | No | `cli/prepare.py` | REPLACE (with Pydantic validation) |
| `backtests/studies/*/collector.py` | Bespoke collection logic | No | `GenericResearchActor` | DELETE (replace with generic shell) |
| `backtests/nt_runtime/data_plan.py` | Data resolution / catalog binding | Partial | Bind `DatasetSpec` to `BacktestNode` | EXTEND |
| `backtests/nt_runtime/catalog_materializer.py` | Parquet ingestion | Partial | Enforce `ts_init` mapping from `DatasetSpec` | EXTEND |
| `backtests/nt_runtime/output_manager.py` | DF generation | Partial | Enforce strict output schemas | WRAP |
| `backtests/nt_runtime/modes/collect.py` | Collection execution mode | Partial | Run `GenericResearchActor` | KEEP |
| `research_preflight.py` | Test execution | No | `cli/preflight.py` | REPLACE (targeted selection only) |
| `Analysis Harness` | Metric generation | Yes | Unchanged | KEEP |

---

### 3. Minimum Phase 1 Module Tree

```text
research/
├── schemas/
│   ├── dataset.py        # NEW: Pydantic definitions for DatasetSpec. Prevents data misconfiguration.
│   ├── study.py          # NEW: Pydantic definitions for StudySpec. Replaces custom Python validators.
│   └── blocks.py         # NEW: Pydantic definitions for BlockSpec (versioning).
├── datasets/
│   └── NQ_dense_1s_v1.yaml # NEW: Immutable dataset registry. Prevents ts_init mapping errors.
├── blocks/
│   ├── population/       # MOVE: Reusable population gates (e.g., maturity_flip).
│   ├── features/         # MOVE: Reusable feature snapshots.
│   └── trackers/         # NEW: Reusable ForwardTracker implementations.
├── cli/
│   ├── prepare.py        # NEW: Compiles study, derives ts_init_delta, generates compiled_study.json.
│   ├── readiness.py      # NEW: Cheap deterministic gate (schema/path validation).
│   ├── freeze.py         # NEW: Generates minimal execution identity hash.
│   └── preflight.py      # NEW: Runs targeted tests only.
backtests/
└── nt_runtime/
    ├── generic_actor.py  # NEW: Replaces bespoke collectors. Wires Population, Features, Tracker.
    ├── catalog_materializer.py # MODIFY: Applies derived ts_init_delta_ns.
    └── output_manager.py # MODIFY: Enforces strict schema parity.
```

---

### 4. Dataset Spec Design

**Proposed Schema (`schemas/dataset.py`):**

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field

class TimestampSemantics(StrEnum):
    INTERVAL_OPEN = "interval_open"

class AvailabilityRule(StrEnum):
    INTERVAL_END = "interval_end"

class DatasetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset_id: str
    instrument_id: str
    catalog_path: str
    timestamp_semantics: TimestampSemantics
    bar_interval_ns: int = Field(gt=0)
    availability_rule: AvailabilityRule
    dataset_hash: str

    def derive_ts_init_delta_ns(self) -> int:
        if self.availability_rule == AvailabilityRule.INTERVAL_END and \
           self.timestamp_semantics == TimestampSemantics.INTERVAL_OPEN:
            return self.bar_interval_ns
        raise ValueError("Unsupported timestamp contract")
```

**Dataset YAML (`datasets/NQ_dense_1s_v1.yaml`):**

```yaml
dataset_id: NQ_dense_1s_v1
instrument_id: NQ.CME
catalog_path: data/canonical/NQ_dense_1s_2016_2026.parquet
timestamp_semantics: interval_open
bar_interval_ns: 1000000000
availability_rule: interval_end
dataset_hash: "e3b0c442..."
```

**Compiled JSON emitted by PREPARE:**

```json
{
  "dataset_id": "NQ_dense_1s_v1",
  "resolved_nt_mapping": {
    "ts_event_rule": "source_timestamp",
    "ts_init_rule": "ts_event_plus_interval",
    "ts_init_delta_ns": 1000000000
  }
}
```

---

### 5. Study Spec Design (Phase 1)

**Proposed Schema (`schemas/study.py`):**

```python
class BlockRef(BaseModel):
    name: str
    version: str

class DecisionClockSpec(BaseModel):
    instrument_id: str
    timeframe: str

class StudySpec(BaseModel):
    study_id: str                          # REQUIRED NOW
    datasets: list[str]                    # REQUIRED NOW
    decision_clock: DecisionClockSpec      # REQUIRED NOW
    population: BlockRef                   # REQUIRED NOW
    features: list[BlockRef]               # REQUIRED NOW
    tracker: BlockRef                      # REQUIRED NOW
    mtf_context: list[DecisionClockSpec]   # OPTIONAL NOW
    execution: dict | None = None          # DEFER
```

**Proposed `study.yaml`:**

```yaml
study_id: Codex_clean_maturity_flip_rolling_5m
datasets:
  - NQ_dense_1s_v1
decision_clock:
  instrument_id: NQ.CME
  timeframe: 1s
population:
  name: clean_maturity_flip
  version: 1.2.0
features:
  - name: rolling_5m_productivity
    version: 1.0.0
tracker:
  name: forward_horizon_tracker
  version: 2.0.0
```

---

### 6. Block Versioning Design

* **Registry Storage:** A centralized `blocks/registry.json` generated by a script scanning `blocks/**/*.py` docstrings/headers.
* **Hash Computation:** `PREPARE` calculates the SHA-256 of the specific `.py` file implementing the block.
* **Version Bumps:** Code changes *must* bump the semantic version (e.g., `1.0.0` -> `1.0.1`). If code changes without a version bump, the SHA-256 hash changes, and the execution identity fails validation.
* **Old Studies:** A study frozen with `1.0.0` will strictly resolve to the `1.0.0` hash, rejecting the run if that file was mutated.

---

### 7. Generic Runtime Composition

The existing repo suggests a collector-centric architecture. This must change to a **Composition Architecture**.

* **Recommended Core:** `GenericResearchActor` (inherits from NT `Actor`).
* **Why:** Removes the need to write bespoke NT event loops. Order management is avoided in the Actor.
* **State Ownership:** The `GenericResearchActor` owns the `Cache` and subscriptions. It passes immutable events to components.

**Interface Sketch:**

```python
class GenericResearchActor(Actor):
    def on_start(self):
        # Bind PopulationEngine, FeatureEngine, ForwardTracker from StudySpec

    def on_bar(self, bar: Bar):
        # 1. Population logic evaluates candidate (Read-only)
        candidate_id = self.population_engine.evaluate(bar)
        if not candidate_id: return

        # 2. FeatureEngine snapshots current state (Cannot suppress candidate)
        features = self.feature_engine.snapshot(self.cache, bar.ts_init)

        # 3. Register with ForwardTracker
        self.tracker.register_candidate(candidate_id, bar)

        # 4. Emit candidate to OutputWriter
        self.output_writer.emit_candidate(candidate_id, features)
```

---

### 8. Forward Tracker Design

**Action:** GENERALIZE existing MAE/MFE tracking into a single interface.

```python
class ForwardTracker:
    def update_forward_state(self, bar: Bar):
        # CONTINUOUS MEASUREMENT
        # Update running MAE, MFE, time_to_MAE, time_to_MFE
        pass
        
    def resolve_terminal(self, bar: Bar) -> TerminalDisposition | None:
        # TERMINAL DISPOSITION
        # Returns disposition if max horizon reached, session closed, or opposite regime flip occurred.
        pass
```

---

### 9. Data / Timestamp Materialization Design

**Intended Path:**

1. `catalog_materializer.py` reads `DatasetSpec`.
2. Reads canonical Databento parquet.
3. Constructs NT `Bar` objects:
   - `ts_event = row.timestamp`
   - `ts_init = row.timestamp + spec.ts_init_delta_ns`
4. Writes to `ParquetDataCatalog`.
5. MTF Runtime Aggregation (`TimeframeAggregator`) consumes these normalized 1s bars internally.

**Pseudo-diff (`backtests/nt_runtime/catalog_materializer.py`):**

```python
# PROPOSED
delta_ns = dataset_spec.derive_ts_init_delta_ns()

for row in raw_data:
    bar = Bar(
        instrument_id=instrument_id,
        bar_type=bar_type,
        open=row.open, high=row.high, low=row.low, close=row.close,
        volume=row.volume,
        ts_event=row.timestamp,
        ts_init=row.timestamp + delta_ns  # Normalized exactly once
    )
```

---

### 10. Prepare Contract

* **Command:** `python -m cli.prepare --study studies/Codex_clean_maturity/study.yaml`
* **Action:** Reads `study.yaml`, queries `DatasetSpec` registry, queries `BlockSpec` registry.
* **Allowed Mutations:** Generates `compiled_study.json`.
* **Prohibited Mutations:** Cannot modify source code or catalog data.
* **Output JSON:** `compiled_study.json` containing fully resolved block hashes and the explicit `ts_init_delta_ns`.

---

### 11. Readiness Contract

* **Command:** `python -m cli.readiness --compiled-study compiled_study.json`
* **Checks:**
  1. **Physical Source:** Validates `catalog_path` exists.
  2. **Precision:** Ensures loaded Parquet price/qty precision matches NT Instrument definition.
  3. **Timestamp Normalization:** Loads 10 rows. Asserts `ts_init - ts_event == ts_init_delta_ns`.
  4. **Non-Empty Schema:** Injects a synthetic trigger. Verifies `OutputWriter` emits declared columns without debug artifacts.
  5. **Callback Dispatch:** Runs 100 bars through `BacktestNode` to ensure `on_bar` fires.
* **Output:** `readiness.json` (Status: `CLEAR` or `BLOCKED`).

---

### 12. Freeze / Execution Identity Contract

* **Command:** `python -m cli.freeze --compiled-study compiled_study.json`
* **Included:** `compiled_study.json` hash, `DatasetSpec` hash, Block implementations hashes, `GenericResearchActor` hash.
* **Excluded:** Tests, logs, audit reports, human summaries.
* **Composition Rule:** `SHA256(concat(included_hashes))`
* **Output:** `frozen_execution.json`

---

### 13. Framework Certification Design

* **Closure:** Hashes `backtests/nt_runtime/`, `blocks/`, and `schemas/`.
* **Stale Condition:** Any modification to shared NT adapters, generic actor, or feature registry invalidates the certificate.
* **Tests Required:** Data loader parity tests, generic actor integration tests, feature math unit tests.

---

### 14. Study Preflight Design

* **Selection Logic:** Uses `pytest` with specific paths extracted from the `StudySpec` blocks.
* **Avoids Fallback:** Does NOT run `pytest tests/`. Runs `pytest tests/blocks/test_clean_maturity_flip.py` explicitly based on the resolved `PopulationSpec`.
* **Estimated Time:** < 30 seconds (down from 15+ minutes).

---

### 15. Result / Status Schemas

We truly only need **one common envelope**: `workflow_state.json`.

```json
{
  "study_id": "Codex_clean_maturity",
  "execution_identity": "a1b2c3d4...",
  "stages": {
    "PREPARE": {"status": "CLEAR"},
    "READINESS": {"status": "CLEAR"},
    "FREEZE": {"status": "CLEAR"},
    "PREFLIGHT": {"status": "CLEAR"}
  },
  "result_manifest": {
    "population_funnel": {"candidates_emitted": 11500}
  }
}
```

`SUMMARY.md` is generated by a deterministic script reading `workflow_state.json` and formatting it into Markdown.

---

### 16. Error Taxonomy

| Error Code | Detection Stage | Guard | Test | LLM Needed? |
| --- | --- | --- | --- | --- |
| `ERR_CATALOG_MISSING` | READINESS | Check `catalog_path` exists | `test_readiness_path` | No |
| `ERR_DOUBLE_TS_SHIFT` | READINESS | `assert ts_init - ts_event == delta` | `test_ts_normalization` | No |
| `ERR_OUTPUT_SCHEMA` | READINESS | Non-empty fixture schema check | `test_non_empty_output` | No |
| `ERR_POP_SUPPRESSION` | RECONCILIATION | `candidates == eligible - excluded` | `test_population_funnel` | No |
| `ERR_STALE_FREEZE` | PREFLIGHT | Re-hash inputs vs `frozen_execution.json` | `test_identity_stable` | No |
| `ERR_PRECISION_MISMATCH` | READINESS | Match parquet decimals to Instrument | `test_instrument_precision` | No |

---

### 17. Proposed Code Samples

**PROPOSED: `GenericResearchActor` (Partial Skeleton)**

```python
class GenericResearchActor(Actor):
    def __init__(self, config: GenericActorConfig):
        super().__init__()
        self.population = config.population_engine
        self.features = config.feature_engine
        self.tracker = config.forward_tracker
        self.writer = config.output_writer

    def on_bar(self, bar: Bar):
        # PROPOSED: Strict boundary enforcement
        candidate_id = self.population.evaluate(bar)
        if candidate_id:
            feat_data = self.features.snapshot(self.cache, bar.ts_init)
            self.tracker.register(candidate_id, bar)
            self.writer.emit_candidate(candidate_id, feat_data)
            
        self.tracker.update_continuous(bar)
        terminals = self.tracker.resolve_terminals(bar)
        for t in terminals:
            self.writer.emit_observation(t)
```

---

### 18. File-by-File Implementation Plan

| Step | Path | Action | Purpose | Risk | Agent Type |
| --- | --- | --- | --- | --- | --- |
| 1 | `schemas/dataset.py`, `study.py` | ADD | Pydantic contracts | Low | Normal |
| 2 | `datasets/NQ_dense_1s_v1.yaml` | ADD | Immutable data registry | Low | Normal |
| 3 | `cli/prepare.py` | ADD | State mutator, compiles JSON | Med | Normal |
| 4 | `backtests/nt_runtime/catalog_materializer.py` | MODIFY | Enforce `ts_init` mapping | High | Normal |
| 5 | `cli/readiness.py` | ADD | Deterministic checks | Med | Normal |
| 6 | `backtests/nt_runtime/generic_actor.py` | ADD | Generic runtime composition | High | High-Reasoning |

---

### 19. Coding Agent Task Packets

**Packet 1: Schemas & Registry**

* **Objective**: Implement `DatasetSpec` and `StudySpec` Pydantic models.
* **Allowed Files**: `research/schemas/*.py`, `datasets/*.yaml`
* **Requirements**: Enforce UTC, derive `ts_init_delta_ns`.
* **Outputs**: Pydantic validation passing on test YAML.
* **Agent**: Normal coding.

**Packet 2: Data Materialization**

* **Objective**: Modify `catalog_materializer.py` to use `DatasetSpec`.
* **Allowed Files**: `backtests/nt_runtime/catalog_materializer.py`
* **Requirements**: Extract `ts_init_delta_ns`, apply to `Bar` construction exactly once.
* **Outputs**: `pytest` passing for `test_ts_normalization`.
* **Agent**: Normal coding.

**Packet 3: Control Plane (PREPARE/READINESS)**

* **Objective**: Build `cli/prepare.py` and `cli/readiness.py`.
* **Allowed Files**: `cli/*.py`
* **Requirements**: `prepare` emits `compiled_study.json`. `readiness` asserts exact `ts_init` diff.
* **Outputs**: `workflow_state.json`.
* **Agent**: Normal coding.

---

### 20. Red-Team Matrix

| Defect Injected | Expected Failing Stage | Error Code |
| --- | --- | --- |
| Wrong catalog path | READINESS | `ERR_CATALOG_MISSING` |
| Double `+1s` shift applied in NT | READINESS | `ERR_DOUBLE_TS_SHIFT` |
| Undeclared column in output writer | READINESS | `ERR_OUTPUT_SCHEMA` |
| Population gate silently drops candidate | RECONCILIATION | `ERR_POP_SUPPRESSION` |
| Edit to `study.yaml` after FREEZE | PREFLIGHT / AUDIT | `ERR_STALE_FREEZE` |

---

### 21. Current vs. Target Complexity

| Metric | Current (Codex_clean_maturity) | Target (V2) |
| --- | --- | --- |
| Bespoke Python Files | 3+ (`collector.py`, `run_*.py`, validation) | 0 (uses `generic_actor.py`) |
| Boilerplate Burden | High (manual NT event loops) | Zero (YAML config) |
| Validation Steps | Manual log parsing, full test suite | Deterministic CLI gates |
| Agent Context Burden | High (must read entire repo) | Low (reads targeted JSON errors) |

---

### 22. Open Decisions (Require Research Authority)

1. **Model Serialization Format**: (e.g., ONNX vs LightGBM native). Defer until ML pipeline orchestration is built.
2. **OOS Unlock Policy**: Cryptographic seal vs manual approval workflow.
3. **Execution Assumptions**: Specific fill models, slippage, and latencies for the target ExecutionSpec.

---

### 23. Things Not to Build (Phase 1 Exclusions)

* **Cached MTF materializations** (Runtime aggregation is mandatory for Phase 1).
* **Research migrate** functionality.
* **Generalized ML orchestration** (Focus on candidate collection first).
* **UI / Dashboards**.

---

### 24. Final Implementation Blueprint

A. **Minimum Phase 1 Files**: `schemas/*.py`, `datasets/NQ_*.yaml`, `cli/prepare.py`, `cli/readiness.py`, `generic_actor.py`, `catalog_materializer.py`.
B. **Order**: Schemas -> Dataset YAML -> Materializer -> PREPARE -> READINESS -> GenericActor.
C. **Acceptance Test**: Run the CleanFlip study through `PREPARE -> READINESS -> FREEZE -> SMOKE -> RECONCILIATION`.
D. **Expected Risks**: NT internal aggregation (`TimeframeAggregator`) might require strict `time_bars_build_delay` configuration to align perfectly with the derived `ts_init`.
E. **Stop Condition**: When `result_manifest.json` matches the `candidates_emitted` exactly with `eligible - exclusions`, with ZERO manual edits post-PREPARE. STOP. Do not generalize further until red-teamed.

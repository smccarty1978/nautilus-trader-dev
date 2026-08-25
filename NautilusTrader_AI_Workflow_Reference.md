<!-- DOC-STATUS-BANNER -->
> **[STALE — SUPERSEDED]**
>
> Superseded by **docs/RESEARCH_WORKFLOW.md**.
>
> A parallel workflow reference describing the pre-V2 feature system and the layout before `research_workflow/` consolidation.
>
> Kept for its reasoning and for the audit trail. **Not a source of instructions.**
> Classification: `docs/DOCUMENT_MAP.md`.

# NautilusTrader AI Workflow Reference

**Purpose:** A compact, AI-friendly reference for designing research collectors, backtests, data pipelines, validation flows, and live-compatible strategy workflows with NautilusTrader (NT).

**Prepared:** 2026-08-21  
**Primary documentation:** https://nautilustrader.io/docs/latest/  
**Repository:** https://github.com/nautechsystems/nautilus_trader  
**Stable docs note:** The NautilusTrader tutorials page states that `latest` documentation is built from the stable `master` branch, while `nightly` tracks unreleased work.  
**GitHub snapshot inspected:** public repository search results at commit `2114cf6f761429e0adb5ca9596fcd7b895b16011` on the repository's development line.

> This is a synthesized reference, not a verbatim mirror of the NautilusTrader documentation. It summarizes the official docs and turns them into practical workflow rules for AI-assisted research projects. When this document conflicts with the current NautilusTrader API reference or installed version, the current API reference and installed-version behavior are authoritative.

---

# 1. Core operating model

NautilusTrader is designed around one event-driven trading architecture spanning research, deterministic simulation, portfolio/risk modeling, and live execution.

The most important architectural principle for research is:

**Backtest and live environments should share the same strategy/component semantics.**

The substitution primarily occurs at the data and execution boundaries:

- Backtest: historical data + simulated venue/exchange.
- Sandbox: real-time data + simulated venue.
- Live: real-time data + live venue adapter.

The major runtime components include:

- `MessageBus`
- `Cache`
- `DataEngine`
- `ExecutionEngine`
- `RiskEngine`
- `Portfolio`
- `Actor`
- `Strategy`
- Backtest/live nodes
- Venue/data adapters

## AI workflow implication

Avoid building a separate pandas-only research implementation and a different NautilusTrader implementation when the goal is eventual deployment.

Prefer:

```text
canonical data
    ↓
NautilusTrader event stream
    ↓
same collector / feature logic
    ↓
same signal logic
    ↓
backtest
    ↓
live runtime
```

Offline dataframe analysis remains useful for diagnostics and exploratory statistics, but execution-affecting conclusions should be validated in the NT event model.

Sources:
- https://nautilustrader.io/docs/latest/
- https://nautilustrader.io/docs/latest/concepts/architecture/
- https://nautilustrader.io/docs/latest/concepts/backtesting/
- https://nautilustrader.io/docs/latest/concepts/live/

---

# 2. Backtesting API choice

NautilusTrader exposes two broad backtesting approaches.

## High-level: `BacktestNode`

Use when:

- data is in `ParquetDataCatalog`;
- config-driven runs are desired;
- large datasets should be streamed/chunked;
- reproducible batch runs are important;
- the workflow should transition naturally toward live trading.

The official Getting Started docs describe the high-level path as the recommended production workflow.

## Low-level: `BacktestEngine`

Use when:

- direct control over engine construction is required;
- data is not in a Nautilus Parquet catalog;
- data fits in memory or custom streaming is managed manually;
- components need to be added/configured imperatively;
- developing/testing lower-level framework behavior.

## Project recommendation

Default new research workflows to:

```text
ParquetDataCatalog
    +
BacktestNode / config-driven run
```

Use low-level `BacktestEngine` deliberately when the research question specifically requires manual control.

## Important process constraint

NautilusTrader documents that multiple `BacktestNode` or `TradingNode` instances in the same process are not supported because of global singleton state. Sequential runs with proper disposal are supported.

For parallel research sweeps, prefer separate processes rather than multiple nodes in a single Python process.

Sources:
- https://nautilustrader.io/docs/latest/getting_started/
- https://nautilustrader.io/docs/latest/getting_started/backtest_high_level/
- https://nautilustrader.io/docs/latest/concepts/backtesting/apis-and-runs/

---

# 3. Backtest event ordering

The documented backtest loop has a crucial ordering model.

For each incoming data point:

1. The simulated exchange processes the market data.
2. Existing resting orders can match against the newly updated market state.
3. The data is dispatched to actors/strategies.
4. Commands produced by those callbacks are drained/settled.
5. Matching engines run again for newly submitted orders.

Conceptually:

```text
market data arrives
    ↓
exchange / matching state updates
    ↓
existing orders may fill
    ↓
strategy receives event
    ↓
strategy submits/cancels/modifies
    ↓
venue commands settle
    ↓
newly submitted orders may match
```

## AI workflow implication

Do not assume:

```text
strategy sees event
→ order existed before event
```

That is false.

The market state represented by the incoming data point is processed before the strategy callback.

This is especially important with bars.

Source:
- https://nautilustrader.io/docs/latest/concepts/backtesting/execution-flow/

---

# 4. Bar timestamp contract

This is one of the most important NT rules for causal research.

For execution simulation, a complete bar must not become available before the interval has finished.

The documentation specifies:

- `ts_init` should represent when the complete bar becomes available.
- For close-stamped bars, `ts_init` can equal the bar timestamp.
- For open-stamped bars, use:

```text
ts_init = ts_event + bar_interval
```

Example for a one-minute open-stamped bar:

```text
ts_event = 09:30:00
bar interval = 60 seconds
ts_init = 09:31:00
```

The complete 09:30–09:31 OHLCV cannot causally be used at 09:30.

## Required AI checks

For every custom data source:

```text
1. Determine whether source timestamp is OPEN-stamped or CLOSE-stamped.
2. Establish ts_event semantics.
3. Establish ts_init semantics.
4. Validate a small sample before catalog materialization.
5. Ensure decision logic uses only data with:
       ts_init <= decision_time
```

## Internally aggregated time bars

The documentation notes that exact-boundary data and bar-close timers can interact. `time_bars_build_delay` can be used for internally aggregated bars so boundary data is incorporated before closing the bar.

Source:
- https://nautilustrader.io/docs/latest/concepts/backtesting/bar-execution/
- current nightly/stable API behavior should always be verified for the installed version.

---

# 5. Bar-based execution limitations

OHLC bars do not contain the true within-bar sequence of trades.

NT therefore simulates a deterministic plausible path for executable bar processing.

Depending on configuration, the path can be:

```text
Open → High → Low → Close
```

or an adaptive ordering where the extreme closest to the open is visited first.

This matters if both:

- stop-loss
- profit target

are inside the same bar.

The chosen synthetic path determines which level is encountered first.

## Critical research rule

Bar-based results cannot prove exact intrabar execution order.

Use more granular data when results depend on:

- spread;
- tight stops;
- tight targets;
- stop/target ordering;
- gaps;
- queue position;
- precise fill timing;
- order book depth;
- execution latency.

## Next-bar-open warning

NT documentation explicitly explains that the engine does not provide a native "next-bar-open fill mode" in the simplistic sense often used in dataframe backtests.

A completed bar is processed before the strategy receives `on_bar`. The next bar's open is also processed as market state before that next bar is dispatched.

Therefore, code that reads a current bar's open inside `on_bar` as if it were an actionable next-open fill can introduce look-ahead or unrealistic sequencing.

Source:
- https://nautilustrader.io/docs/latest/concepts/backtesting/bar-execution/

---

# 6. Data granularity and venue `book_type`

Backtest realism depends on matching data granularity to the simulated venue book.

From more detailed to less detailed:

1. L3 MBO order book
2. L2 MBP order book
3. L1 quotes
4. trade ticks
5. bars

NT venue book types include:

- `L1_MBP`
- `L2_MBP`
- `L3_MBO`

A key documented constraint:

**NautilusTrader cannot invent higher-granularity data from lower-granularity inputs.**

Examples:

- bars/quotes can update an L1 venue;
- L2/L3 venues require corresponding book data for realistic book state;
- bars sent to L2/L3 may still reach strategies but do not create depth that does not exist.

## Research validation ladder

A useful project standard is:

```text
signal discovery
    → bars if sufficient

causal runtime validation
    → smallest event granularity needed for the signal

execution-sensitive validation
    → quotes / trades / L2 / L3 as required
```

Do not pay for L2/L3 realism when the research question does not depend on it.

Do not claim execution realism from bars when the economics depend on microstructure.

Source:
- https://nautilustrader.io/docs/latest/concepts/backtesting/data-and-venues/

---

# 7. Fill modeling

Historical data cannot reveal how a hypothetical simulated order would have changed the historical market.

NT fill models explicitly encode assumptions.

Important controls include:

- touched-limit fill probability;
- slippage probability for applicable L1 simulation;
- random seed;
- synthetic book models;
- liquidity consumption behavior;
- venue book granularity.

## Determinism

When probabilistic fill behavior is used, set a fixed random seed for reproducible model draws.

## L1 vs L2/L3

With L2/L3, recorded depth participates in price determination.

With L1, more assumptions are required because only top-of-book or derived state is available.

## Liquidity consumption

Historical books remain immutable. If the simulation should prevent repeatedly consuming the same displayed historical size, configure liquidity-consumption behavior where supported.

## Project rule

Every research result involving simulated fills should record:

```yaml
execution_model:
  book_type:
  data_type:
  fill_model:
  fill_model_params:
  random_seed:
  liquidity_consumption:
  latency_model:
  fee_model:
```

Sources:
- https://nautilustrader.io/docs/latest/concepts/backtesting/fill-models/
- https://nautilustrader.io/docs/latest/concepts/backtesting/fill-prices-and-matching/

---

# 8. Market-data precision

Instrument definitions and incoming data precision must agree.

NT validates prices and quantities against instrument precision.

Potential mismatches can cause:

- market data to be skipped;
- orders to be rejected;
- modifications to be rejected;
- fills to be normalized or skipped depending on compatibility.

For custom loaders:

```text
instrument definition
    ↔ price precision
    ↔ quantity precision
    ↔ source data
```

must be validated before expensive runs.

## Cheap-readiness check

For a small sample of every runtime data type:

```text
validate:
    instrument ID
    price precision
    quantity precision
    ts_event
    ts_init
    chronological ordering
    expected schema
```

Source:
- https://nautilustrader.io/docs/latest/concepts/backtesting/fill-prices-and-matching/

---

# 9. Strategies and Actors

`Strategy` extends `Actor`.

Actors provide:

- data requests/subscriptions;
- event handling;
- timers/alerts;
- Cache access;
- Portfolio access;
- logging;
- MessageBus interaction.

Strategies add order-management capabilities.

## Lifecycle warning

The docs warn against using runtime components such as the system clock/logger in the strategy constructor before registration.

Keep constructors focused on:

- configuration;
- local deterministic state initialization;
- tracker creation.

Use lifecycle hooks after registration/start for runtime services.

## AI collector design

A research collector often does not need order management.

Prefer:

```text
Actor
```

when the component only:

- subscribes;
- computes;
- records;
- emits research data.

Prefer:

```text
Strategy
```

when the component needs actual trading/order-management behavior.

This separation can keep research collectors smaller and reduce accidental coupling to execution semantics.

Sources:
- https://nautilustrader.io/docs/latest/concepts/actors/
- https://nautilustrader.io/docs/latest/concepts/strategies/

---

# 10. Message immutability

The NT design principles specify that messages—requests, responses, events, commands—should be immutable after creation.

Benefits include:

- determinism;
- temporal integrity;
- safer concurrency;
- easier replay;
- easier debugging;
- clearer ownership;
- auditability.

## AI workflow implication

Prefer:

```text
input event
→ derive new local state / new record
```

over:

```text
mutate historical event object
```

Research artifacts should preserve what the runtime knew at the time.

Source:
- https://nautilustrader.io/docs/latest/developer_guide/design_principles/

---

# 11. Cache usage

The `Cache` is central in-memory state containing data such as:

- instruments;
- recent market data;
- accounts;
- orders;
- positions;
- custom objects.

Use it for runtime state access, but distinguish between:

```text
event currently being processed
```

and:

```text
state visible in Cache
```

The live environment may involve asynchronous updates, so do not create hidden causal assumptions based on cache update timing without validating the specific runtime path.

Source:
- https://nautilustrader.io/docs/latest/concepts/cache/

---

# 12. Custom data

NT supports user-defined data types and routing.

Custom data can be useful for:

- ML scores;
- external signals;
- feature snapshots;
- alternative data;
- model-state messages;
- research telemetry.

A clean custom-data design should define:

```yaml
type_name:
schema:
event_timestamp_semantics:
initialization_timestamp_semantics:
source:
producer:
consumers:
persistence_encoding:
causal_availability_rule:
```

Do not use custom data as a shortcut around timestamp causality.

Source:
- https://nautilustrader.io/docs/latest/concepts/custom_data/

---

# 13. Parquet data catalog

The high-level backtest workflow is built around the Parquet data catalog.

Advantages:

- standardized historical data storage;
- time-range queries;
- config-driven backtests;
- chunked/streamed loading;
- reusable data across research runs.

## Preferred pipeline

```text
raw provider data
    ↓
normalize/validate
    ↓
canonical NT-compatible records
    ↓
ParquetDataCatalog
    ↓
BacktestNode
```

## Important project rule

"File exists" is not sufficient validation.

Cheap readiness should resolve and report:

```yaml
data_binding:
  configured_source:
  resolved_catalog:
  resolved_dataset:
  instrument_id:
  data_types:
  first_timestamp:
  last_timestamp:
  requested_start:
  requested_end:
  sample_rows_loaded:
  source_manifest_hash:
```

This catches accidental fallback to an old catalog before expensive validation.

Sources:
- https://nautilustrader.io/docs/latest/getting_started/backtest_high_level/
- https://nautilustrader.io/docs/latest/how_to/loading_external_data/
- https://nautilustrader.io/docs/latest/how_to/databento_data_catalog/

---

# 14. Databento integration

NautilusTrader includes a Databento integration/data workflow.

When Databento timestamps or bar schemas are used:

- verify provider timestamp semantics;
- convert to NT `ts_event`/`ts_init` semantics explicitly;
- preserve precision;
- validate representative records after catalog writing;
- do not assume bar timestamps represent availability.

Official integration guide:
- https://nautilustrader.io/docs/latest/integrations/databento/

---

# 15. Event sourcing, replay, and run identity

NT documentation includes event-sourcing concepts for durable state-affecting history, replay, run manifests, and verification.

This aligns naturally with machine-learning research governance.

A research run should be identifiable by immutable inputs rather than by a human-readable folder name alone.

Recommended project result identity:

```yaml
run_identity:
  research_contract_hash:
  runtime_code_hash:
  strategy_or_actor_hash:
  feature_contract_hash:
  data_manifest_hash:
  model_hash:
  NT_version:
  configuration_hash:
  random_seed:
```

Run logs and output paths can be generated after identity is established; they should not themselves redefine the execution identity.

Sources:
- https://nautilustrader.io/docs/latest/concepts/event_sourcing/
- https://nautilustrader.io/docs/latest/developer_guide/design_principles/

---

# 16. Testing philosophy from NautilusTrader

NT's developer guide treats tests as executable specifications.

It recommends using the lowest test layer that proves the required property and escalating only when needed.

Testing ladder includes:

- unit tests;
- parametrized tests;
- property-based tests;
- integration tests;
- fuzz tests;
- acceptance tests;
- deterministic simulation;
- performance tests.

## Important design lesson

**Not every module needs every test technique.**

This is directly applicable to AI-assisted research frameworks.

Do not run the entire repository test universe for every study modification.

Instead map change type to required test scope.

### Suggested research mapping

| Change | Minimum validation |
|---|---|
| Research YAML/config only | contract compile + study contract tests |
| One feature function | unit + causal timestamp tests + feature output test |
| Collector population rule | targeted unit + event-stream integration + population reconciliation |
| Shared FeatureEngine | shared feature certification + affected studies |
| NT runtime adapter | integration/acceptance tests |
| Data loader | sample precision/timestamp/schema tests + catalog readback |
| Execution model | targeted matching/fill tests + smoke |

## Avoid arbitrary sleeps

The NT testing guide recommends waiting for observable conditions with bounded polling rather than arbitrary sleeps in asynchronous testing.

## Mocks

Prefer simple hand-written stubs for fixed behavior. Mock frameworks are most valuable when call arguments/counts or complex transitions must be asserted.

Source:
- https://nautilustrader.io/docs/latest/developer_guide/testing/

---

# 17. Framework certification vs study validation

This section is a **project adaptation** of NT's testing principles rather than an official NautilusTrader workflow.

A scalable research repo should separate:

## Framework certification

Triggered when shared infrastructure changes:

```text
backtest runtime
feature engine
data loader/catalog adapter
execution integration
common collectors
research compiler
shared schemas
```

May run:

- broad unit suite;
- integration suite;
- property tests;
- performance checks;
- data-type lifecycle tests.

Produces:

```yaml
framework_certificate:
  closure_hash:
  test_suite_hash:
  passed_at:
  results:
```

## Study validation

Triggered by study-specific changes.

Runs only:

- study tests;
- tests for shared modules actually changed or newly depended upon;
- causal lint/checks;
- contract fidelity;
- cheap runtime probe.

This avoids repeating hundreds of unchanged framework tests for every collector iteration.

---

# 18. Cheap readiness gate

This is a **recommended project workflow layer** based on recent failure patterns and NT's documented runtime contracts.

It should run before freeze, expensive audits, or large backtests.

Target: seconds to roughly one minute.

## Required checks

### Data

- exact physical catalog/path resolves;
- intended dataset is actually selected;
- instrument exists;
- requested dates exist;
- small sample loads through the same runtime loader;
- timestamp semantics are correct;
- price/quantity precision matches instrument;
- expected bar/data types exist.

### Collector/strategy

- imports cleanly;
- config constructs;
- component instantiates;
- lifecycle registration succeeds in a small fixture;
- required subscriptions resolve.

### Features

- all declared features exist;
- names are unique;
- runtime output shape matches contract;
- causal source timestamps are not in the future.

### Output

Exercise a **non-empty** candidate/observation fixture.

Require:

```text
candidate metadata legal
selected feature columns legal
no undeclared/debug columns
terminal disposition legal
```

Do not validate only the empty dataframe path.

### Runtime

Dispatch a tiny bounded event stream through the same engine surface used for the real run.

Require:

```text
callbacks > 0
expected data type received
candidate interface callable
output extraction succeeds
```

### Identity stability

Resolve prepared execution identity twice without mutation.

Require:

```text
identity_A == identity_B
```

---

# 19. Prepare / Freeze separation

This is a **recommended project governance adaptation**.

## PREPARE

The only stage allowed to generate execution-affecting derived artifacts.

Examples:

- compile research configuration;
- resolve selected features;
- resolve model;
- bind exact data;
- generate required runtime manifest;
- generate strategy config.

## READINESS

Tests prepared state cheaply.

May write evidence, not execution inputs.

## FREEZE

Read-only with respect to execution state.

Freeze writes an evidence record containing hashes of the exact execution inputs.

## AFTER FREEZE

No stage should:

- recompile;
- regenerate source manifests;
- change model;
- refresh selected features;
- change data binding;
- alter strategy/runtime code.

If something changes deliberately:

```text
return to PREPARE
```

Do not automatically loop through preflight.

---

# 20. Minimal execution identity

A useful execution identity should hash things that can change research behavior.

Include:

```text
compiled research contract
collector/strategy runtime code
shared runtime modules actually executed
selected feature definitions/contract
model artifact and feature order
target/population rules
exact data binding and provenance
instrument definitions as needed
execution/fill/latency/fee configuration
OOS authorization
NT version/environment version
```

Do not automatically include:

```text
test source files
audit prose
preflight implementation
logs
run IDs
timestamps
human summaries
result plots
```

Those are validation/evidence, not the study being executed.

---

# 21. Collector architecture

For fast research iteration, collectors should be modular.

A useful separation is:

```text
Population / Trigger
        ↓
Feature snapshot
        ↓
Target / Observation resolution
        ↓
Output writer
```

These concerns should not silently redefine one another.

## Candidate identity

Population logic determines whether a research opportunity exists.

Feature unavailability should generally not silently erase a candidate unless the research contract explicitly says so.

## Output interface

Use one standard interface across collectors:

```python
get_candidates_dataframe()
get_observations_dataframe()
get_runtime_telemetry()
```

The exact API can differ, but the conceptual surface should remain stable.

## Output schema

Separate:

```text
canonical metadata
registered features
declared target/disposition fields
```

from:

```text
internal tracker/debug state
```

Debug state belongs in telemetry/debug artifacts, not silently in the model feature surface.

---

# 22. Population funnel

Every collector smoke should explain why candidate count is what it is.

Example:

```yaml
population_funnel:
  decision_events: 100000
  session_eligible: 85000
  regime_eligible: 44000
  age_eligible: 40000
  mfe_eligible: 21000
  progress_eligible: 16000
  retention_eligible: 12000
  declared_population_eligible: 12000
  declared_exclusions: 500
  candidates_emitted: 11500
  implementation_only_exclusions: 0
```

Hard invariant:

```text
declared_population_eligible
=
candidates_emitted + declared_exclusions
```

and:

```text
implementation_only_exclusions = 0
```

unless the research contract explicitly defines another relation.

This is not an official NT feature; it is a research-governance layer built on NT's deterministic event model.

---

# 23. Result reconciliation

A candidate-driven ML collector should terminate every candidate according to a declared target contract.

Example:

```yaml
target_reconciliation:
  candidates: 11500
  positive: 2100
  negative: 9200
  censored: 200
  unresolved: 0
```

Require:

```text
positive + negative + censored + unresolved
=
candidates
```

Before accepting a completed run:

```text
unresolved = 0
```

unless unresolved observations are explicitly allowed by the contract.

---

# 24. Human-readable and machine-readable outputs

A strong workflow should write machine-readable truth first, then derive human summaries.

## Machine-readable run result

Recommended `result_manifest.json`:

```json
{
  "schema_version": 1,
  "study_id": "example",
  "run_id": "example-20260821",
  "status": "ACCEPTED",
  "nt_version": "...",
  "execution_identity": "...",
  "research_contract_hash": "...",
  "data_manifest_hash": "...",
  "feature_contract_hash": "...",
  "model_hash": null,
  "start": "...",
  "end": "...",
  "population": {
    "eligible": 0,
    "candidates": 0,
    "declared_exclusions": 0,
    "implementation_only_exclusions": 0
  },
  "targets": {
    "positive": 0,
    "negative": 0,
    "censored": 0,
    "unresolved": 0
  },
  "causality": {
    "future_source_violations": 0
  },
  "artifacts": {
    "candidates": "...",
    "observations": "...",
    "telemetry": "..."
  }
}
```

## Human-readable summary

Generate `SUMMARY.md` from the manifest.

Do not independently type numbers into both JSON and Markdown.

That prevents drift.

---

# 25. Error registry

A reusable AI research framework should remember failures so later projects detect them earlier.

Recommended machine-readable entry:

```yaml
error_id: NT_DATA_BINDING_001
title: Wrong physical catalog resolved
first_seen:
study:
symptom:
root_cause:
detection_stage_when_found:
ideal_detection_stage:
permanent_guard:
test:
files:
regression_status:
```

## Core rule

Whenever a later-stage run discovers an error, ask:

```text
What is the cheapest earlier stage that could have detected this?
```

Then add the permanent guard there.

Examples:

| Failure | Found late | Permanent earlier guard |
|---|---|---|
| Wrong sparse catalog | Smoke | Readiness: exact physical data binding |
| Illegal output columns | End of smoke | Readiness: non-empty output schema fixture |
| Open-stamped bar available too early | Audit/run | Data readiness: timestamp contract |
| Population silently suppressed | Research results | Smoke: population funnel |
| Framework tests rerun unnecessarily | Preflight | Change-based framework certificate |
| Post-freeze file changes | Audit/seal | Frozen identity verifier |

---

# 26. Token-efficient AI agent workflow

This section is a project recommendation.

Use deterministic tooling for deterministic questions.

## Cheap/deterministic agent tasks

Use inexpensive models or scripts for:

- repository search;
- file enumeration;
- schema extraction;
- hash comparison;
- test execution;
- log parsing;
- result tabulation;
- source/data-path tracing.

## Higher-reasoning tasks

Reserve expensive reasoning models for:

- defining population/target;
- ambiguous causality questions;
- look-ahead audit;
- contract audit;
- deciding whether a remediation changes research semantics;
- interpretation of OOS results.

## Bounded agent handoff

Each task should end with a compact card:

```yaml
task:
status:
files_read:
files_changed:
tests_run:
execution_identity_changed:
blocking_findings:
next_action:
```

Avoid asking every new agent to rediscover the entire repository.

---

# 27. Auditor authority boundary

An auditor can identify a causal or contract defect and block execution.

An auditor should not silently author a new research policy.

If a proposed remediation changes any of:

```text
candidate identity
candidate timing
population membership
feature definition
target definition
censoring
OOS boundary
```

the workflow should return:

```text
RESEARCH_DECISION_REQUIRED
```

Research authority must explicitly approve the semantic change before implementation.

This rule is a project governance adaptation, not a built-in NT rule.

---

# 28. Recommended end-to-end research workflow

```text
1. RESEARCH DECISION
      ↓
2. PREPARE
      compile + bind exact data/features/model/runtime
      ↓
3. CHEAP READINESS
      data path + timestamp + precision + schema + tiny dispatch
      ↓
4. FREEZE
      minimal execution identity
      ↓
5. STUDY PREFLIGHT
      targeted study + affected shared tests
      ↓
6. INDEPENDENT CAUSAL REVIEW
      +
   INDEPENDENT CONTRACT REVIEW
      ↓
7. ATTESTATION / SEAL
      ↓
8. ONE-DAY OR SMALL NT SMOKE
      ↓
9. POPULATION + TARGET RECONCILIATION
      ↓
10. BOUNDED MULTI-DAY / TRAIN RUN
      ↓
11. OOS UNLOCK
      ↓
12. OOS RUN
      ↓
13. ANALYSIS + RESULT MANIFEST
```

## No-change invariant

If nothing execution-affecting changes after FREEZE:

```text
no re-freeze
no repeated preflight
no repeated audits
```

---

# 29. Backtest realism ladder for ML projects

A practical ladder:

## Level 0 — feature/unit tests

Synthetic inputs.

Use for:

- feature math;
- tracker state;
- schema;
- population gates.

## Level 1 — tiny NT event fixture

Seconds/minutes of data.

Use for:

- callbacks;
- ordering;
- output interface;
- timestamp causality.

## Level 2 — one-day NT smoke

Use for:

- real population;
- actual feature readiness;
- target dispositions;
- data binding;
- output volumes.

## Level 3 — multi-day bounded run

Use for:

- stability;
- runtime;
- distribution sanity;
- rare-state coverage.

## Level 4 — multi-year signal research

Use for:

- ML training;
- feature evaluation;
- regime diversity.

## Level 5 — execution-realistic validation

Use data granularity appropriate to economics:

- 1s bars
- trade ticks
- quotes
- MBP/L2
- MBO/L3

## Level 6 — live/sandbox parity

Use same strategy/actor behavior with real-time adapters.

---

# 30. NT documentation source map

The current stable documentation homepage exposes these primary sections:

1. Getting Started
2. Concepts
3. How-To
4. Tutorials
5. Integrations
6. Developer Guide
7. Rust API
8. Python API

Homepage:
- https://nautilustrader.io/docs/latest/

## Getting Started

Current stable navigation includes:

- Getting Started
- Installation
- Quickstart
- Backtest — Low-Level API
- Backtest — High-Level API

Base:
- https://nautilustrader.io/docs/latest/getting_started/

## Concepts

Current concept index includes or links to:

### Foundations
- Overview
- Architecture

### Domain model
- Instruments
- Continuous Futures
- Synthetics
- Value Types
- Options
- Greeks

### Data
- Data
- Custom Data
- Order Book
- Events
- Event Sourcing

### Execution and portfolio
- Execution
- Orders
- Positions
- Accounting
- Portfolio
- Reports

### Components/runtime
- Actors
- Strategies
- Cache
- Message Bus
- Configuration
- Logging

### Running systems
- Backtesting
- Live Trading
- Execution Reconciliation
- Visualization
- Adapters
- Rust
- Deterministic Simulation Testing (DST)

Base:
- https://nautilustrader.io/docs/latest/concepts/

### Backtesting section reading order

The official backtesting index recommends:

1. APIs and repeated runs
2. Data and venues
3. Execution flow
4. Fill prices and matching
5. Trade execution
6. Bar execution
7. Fill models
8. Accounts and margin

Base:
- https://nautilustrader.io/docs/latest/concepts/backtesting/

## How-To

Current index describes goal-oriented recipes including:

- Loading External Data
- Data Catalog with Databento
- Configure a Live Trading Node
- Get Started with Lighter
- Write an Actor (Rust)
- Write a Strategy (Rust)
- Run a Backtest (Rust)
- Run Live Trading (Rust)
- Deterministic Simulation Testing

Base:
- https://nautilustrader.io/docs/latest/how_to/

## Tutorials

Current stable tutorial index includes:

### Backtesting/data
- Backtest with FX Bar Data
- Backtest with Order Book Depth Data — Binance
- Backtest with Order Book Depth Data — Bybit
- EMA Cross
- Order Book Data
- Order Book Imbalance

### Strategy patterns
- Mean Reversion with Proxy FX Data — AX Exchange
- Gold Perpetual Book Imbalance — AX Exchange
- Grid Market Making with Deadman's Switch — BitMEX
- On-Chain Grid Market Making with Short-Term Orders — dYdX

### Options
- Options Data and Greeks — Bybit
- Delta-Neutral Options Strategy — Bybit
- Delta-Neutral Options Strategy — Derive

### Rust
- Book Imbalance Backtest — Betfair
- Composite Market Making on Lighter RWA with Databento US Equities
- Hurst/VPIN Directional Strategy — Kraken Futures

Base:
- https://nautilustrader.io/docs/latest/tutorials/

## Integrations

Current stable integrations index lists:

- AX Exchange
- Betfair
- Binance
- Coinbase
- BitMEX
- Blockchain
- Bybit
- Databento
- Deribit
- Derive
- dYdX
- Hyperliquid
- Lighter
- Interactive Brokers
- Kraken
- OKX
- Polymarket
- Tardis

Base:
- https://nautilustrader.io/docs/latest/integrations/

## Developer Guide

Current stable navigation includes:

- Environment Setup
- Design Principles
- Coding Standards
- Shell Scripts
- Rust
- Python
- Testing
- Test Datasets
- Docs Style
- Markdown Style
- Releases
- Security Architecture
- Adapters
- Plugins
- Data Testing Spec
- Execution Testing Spec
- Benchmarking
- FFI Memory Contract

Base:
- https://nautilustrader.io/docs/latest/developer_guide/

---

# 31. GitHub documentation tree reference

The public repository contains documentation under `docs/`, including:

```text
docs/
├── api_reference/
├── concepts/
├── developer_guide/
├── getting_started/
├── how_to/
├── integrations/
└── tutorials/
```

Representative files discovered in the repository include:

```text
docs/concepts/architecture.md
docs/concepts/actors.md
docs/concepts/strategies.md
docs/concepts/cache.md
docs/concepts/configuration.md
docs/concepts/custom_data.md
docs/concepts/message_bus.md
docs/concepts/execution.md
docs/concepts/portfolio.md
docs/concepts/reports.md
docs/concepts/event_sourcing.md
docs/concepts/reconciliation.md
docs/concepts/order_book.md
docs/concepts/data/bar.md
docs/concepts/data/quote_tick.md
docs/concepts/data/trade_tick.md
docs/concepts/backtesting/index.md
docs/concepts/orders/index.md
docs/concepts/orders/market.md
docs/concepts/orders/limit.md
docs/concepts/orders/advanced.md
docs/concepts/orders/emulated.md

docs/getting_started/index.md

docs/how_to/index.md
docs/how_to/run_rust_backtest.md
docs/how_to/write_rust_actor.md
docs/how_to/write_rust_strategy.md

docs/developer_guide/index.md
docs/developer_guide/testing.md
docs/developer_guide/adapters.md
docs/developer_guide/rust.md
docs/developer_guide/python.md
docs/developer_guide/security.md
docs/developer_guide/releases.md
docs/developer_guide/docs.md
docs/developer_guide/plugins.md
docs/developer_guide/ffi.md

docs/integrations/index.md
docs/integrations/databento.md
docs/integrations/binance.md
docs/integrations/bybit.md
docs/integrations/coinbase.md
docs/integrations/bitmex.md
docs/integrations/deribit.md
docs/integrations/derive.md
docs/integrations/dydx.md
docs/integrations/hyperliquid.md
docs/integrations/kraken.md
docs/integrations/lighter.md
docs/integrations/okx.md
docs/integrations/polymarket.md
docs/integrations/tardis.md
docs/integrations/betfair.md
docs/integrations/blockchain.md

docs/tutorials/index.md

docs/api_reference/index.md
docs/api_reference/core.md
docs/api_reference/common.md
docs/api_reference/config.md
docs/api_reference/data.md
docs/api_reference/cache.md
docs/api_reference/backtest.md
docs/api_reference/live.md
docs/api_reference/execution.md
docs/api_reference/risk.md
docs/api_reference/portfolio.md
docs/api_reference/accounting.md
docs/api_reference/trading.md
docs/api_reference/persistence.md
docs/api_reference/analysis.md
docs/api_reference/indicators.md
docs/api_reference/model/index.md
docs/api_reference/model/data.md
docs/api_reference/model/book.md
docs/api_reference/model/events.md
docs/api_reference/model/orders.md
```

Repository:
- https://github.com/nautechsystems/nautilus_trader

For automated AI use, prefer the live stable documentation/API for exact signatures because repository `develop` content can be ahead of the stable release.

---

# 32. AI project context block

The following block can be copied into an AI project's instructions.

```text
NAUTILUSTRADER OPERATING RULES

1. Treat NautilusTrader as an event-driven system, not a dataframe backtester.
2. Preserve causal availability:
       a complete bar is usable only at/after ts_init.
3. Verify source timestamp semantics before catalog writing.
4. For open-stamped bars:
       ts_init = ts_event + interval
   unless the specific adapter/version defines otherwise.
5. Match backtest venue book_type to actual data granularity.
6. Never infer L2/L3 realism from L1/trades/bars.
7. Use BacktestNode + ParquetDataCatalog by default for production-style,
   config-driven research; use BacktestEngine when direct low-level control is
   deliberately required.
8. The exchange processes incoming market state before strategy callbacks.
9. Do not assume current-bar or next-bar-open execution that contradicts NT
   event ordering.
10. Record fill/slippage/liquidity/latency/fee assumptions in every result.
11. Use one node per process; parallel sweeps should use process isolation.
12. Validate exact physical data binding before expensive runs.
13. Validate a non-empty output schema before full smoke.
14. Make candidates, features, targets, and debug telemetry separate contracts.
15. Reconcile candidate population and terminal target dispositions.
16. Use targeted testing; escalate to broader tests only when the changed
    component requires it.
17. Treat tests as executable specifications.
18. Prefer deterministic/replayable runs and fixed random seeds where stochastic
    simulation is used.
19. Keep execution identity separate from validation evidence.
20. If current docs/API disagree with this reference, current NT API/docs win.
```

---

# 33. Checklist for a new NT ML collector

## Research contract

```text
[ ] instrument
[ ] session
[ ] candidate definition
[ ] candidate timestamp
[ ] feature timestamp
[ ] target definition
[ ] horizon
[ ] censoring
[ ] train/dev/OOS years
```

## Data

```text
[ ] exact physical catalog
[ ] instrument ID resolves
[ ] date coverage
[ ] data types
[ ] book_type compatibility
[ ] ts_event semantics
[ ] ts_init semantics
[ ] precision compatibility
[ ] provenance hash/manifest
```

## Collector

```text
[ ] Actor vs Strategy choice deliberate
[ ] subscriptions
[ ] deterministic local state
[ ] no future-source reads
[ ] population telemetry
[ ] canonical candidate output
[ ] canonical observation output
[ ] debug state separated
```

## Features

```text
[ ] registered
[ ] unique names
[ ] causal availability
[ ] warmup/readiness behavior
[ ] feature order frozen for models
```

## Runtime

```text
[ ] cheap import/instantiate
[ ] tiny event dispatch
[ ] non-empty schema fixture
[ ] physical source proof
[ ] one-day smoke
[ ] callbacks > 0
```

## Reconciliation

```text
[ ] population funnel
[ ] declared exclusions
[ ] implementation-only exclusions = 0
[ ] every candidate terminally resolved/censored
[ ] future-source violations = 0
```

## Execution economics

```text
[ ] book type
[ ] data granularity
[ ] fill model
[ ] random seed
[ ] slippage
[ ] liquidity consumption
[ ] latency
[ ] commissions/fees
```

## Result package

```text
[ ] result_manifest.json
[ ] SUMMARY.md generated from manifest
[ ] candidates artifact
[ ] observations artifact
[ ] telemetry artifact
[ ] execution identity
[ ] data identity
[ ] code/config identity
```

---

# 34. When to re-check official docs

This reference should be refreshed when:

- NautilusTrader major/minor version changes;
- backtest execution semantics change;
- bar timestamp behavior changes;
- `BacktestNode`/catalog interfaces change;
- fill models or matching semantics change;
- Python v1/v2 API migration changes the runtime path;
- a new adapter/data type becomes material to research;
- production/live deployment begins.

Recommended refresh command for an AI agent:

```text
Review https://nautilustrader.io/docs/latest/ and the current
nautechsystems/nautilus_trader repository.

Compare against NautilusTrader_AI_Workflow_Reference.md.

Report only:
- changed causal/timestamp semantics
- changed backtest execution semantics
- changed data/catalog APIs
- changed testing guidance
- changed live/backtest parity guidance
- new material integrations
- obsolete statements in the reference

Do not rewrite the whole reference unless required.
```

---

# 35. Source priority

For AI-assisted work, use this authority order:

```text
1. Installed NautilusTrader version and its actual API/runtime behavior
2. Matching-version official API reference
3. https://nautilustrader.io/docs/latest/
4. Stable release source code/examples/tests
5. GitHub development branch documentation
6. This synthesized reference
```

The official Concepts page explicitly notes that when concept guides and API reference disagree, the API reference should be treated as correct.

---

# 36. Bottom line for ML research workflow design

The strongest NT-compatible workflow principles are:

```text
event-driven research
causal timestamps
same strategy/component semantics across backtest/live
catalog-backed reproducible data
appropriate execution granularity
explicit simulation assumptions
small targeted tests before broad tests
deterministic identity/replay
machine-readable contracts/results
early runtime readiness checks
population/result reconciliation
```

For AI-assisted research, the biggest efficiency gain comes from ensuring that deterministic failures are detected by cheap deterministic gates before expensive model/audit work.

A healthy collector workflow should be able to answer, before a large run:

```text
What exact data is being loaded?
What time was each input actually available?
What component receives it?
What defines a candidate?
What features are legal at that timestamp?
What target resolves the candidate?
What execution assumptions are used?
What exact code/config/data identity produced the result?
Can every output count be reconciled?
```

If those answers are machine-readable and tested at small scale first, NautilusTrader becomes a strong foundation for repeatable ML research and deployment-oriented backtesting.

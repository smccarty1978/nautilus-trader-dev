# NautilusTrader Research Parquet Platform Blueprint

**Status:** Proposed architecture  
**Primary use case:** Reusable, causal market-state and feature datasets for regime-based research  
**Primary regime:** Confirmed 1-minute regime  
**Base event stream:** Completed 1-second OHLCV bars  
**Canonical research cadences:** 1s, 5s, 30s, 1m, 5m, 15m

---

## 1. Executive objective

Build one reusable NautilusTrader-generated research store that preserves causal event ordering, shared regime identities, feature provenance, and complete trade-path traceability.

The platform should make most future research possible without replaying the entire source dataset or rebuilding every existing feature. New research should normally consist of:

1. selecting an existing observation population;
2. joining only the required feature families;
3. generating model scores or study-specific outcomes;
4. validating the surviving policy in the NautilusTrader event loop.

The canonical store must separate what was known at the observation time from what occurred afterward.

---

## 2. Design principles

### 2.1 Causal generation first

All canonical bars, regime states, and stateful features must be generated from the existing NautilusTrader streaming stack using completed-bar semantics.

No canonical table may depend on retrospective joins that expose partially completed bars or future state.

### 2.2 Stable observations, modular features

Observation rows are immutable. Features are stored as versioned modules keyed to those observations.

Do not repeatedly rewrite a single permanent 700-column parquet whenever a feature is added or corrected.

### 2.3 Shared regime identity

Every timeframe observation must carry the 1-minute regime that was active and causally known at that timestamp.

Every timeframe may also carry its own regime identity.

### 2.4 Inputs and outcomes are physically separated

Causal features, model outputs, selections, trade paths, and forward outcomes must not share an ambiguous namespace.

### 2.5 One expensive replay, many cheap studies

The expensive NT replay should produce the causal market-state spine and approved feature modules. Most subsequent studies should read parquet, not replay raw market data.

### 2.6 Final runtime validation remains mandatory

Research parquet results identify candidates. They do not replace streaming NautilusTrader strategy validation for candidate generation, feature calculation, model scoring, triggers, orders, and fills.

---

## 3. Canonical layer model

```text
Raw 1s OHLCV
    |
    v
NautilusTrader causal event loop
    |
    +--> market_state_1s
    +--> observations_5s
    +--> observations_30s
    +--> observations_1m
    +--> observations_5m
    +--> observations_15m
             |
             +--> feature modules by timeframe/family/version
             +--> model score modules
             +--> signal selection modules
             +--> trade-path modules
             +--> forward-outcome modules
```

---

## 4. Dataset contracts

## 4.1 `market_state_1s`

### Purpose

Provide the minimal causal state and raw path source needed for later trigger, stop, excursion, and execution-harness research.

### Row grain

One row per completed 1-second bar.

### Required key

```text
instrument_id
bar_close_ns
```

### Required columns

#### Raw bar

```text
bar_open_ns
bar_close_ns
open
high
low
close
volume
```

#### Session and provenance

```text
session_date
session_type
source_partition_id
collector_version
bar_schema_version
run_id
```

#### Regime tags

```text
regime_30s_id
regime_30s_direction
regime_1m_id
regime_1m_direction
regime_1m_start_ns
regime_1m_age_seconds
regime_5m_id
regime_5m_direction
regime_15m_id
regime_15m_direction
regime_definition_version
```

#### Minimal reusable state

```text
atr_1m_current
regime_1m_running_high
regime_1m_running_low
regime_1m_directional_extreme
seconds_since_regime_high
seconds_since_regime_low
latest_completed_5s_ns
latest_completed_30s_ns
latest_completed_1m_ns
latest_completed_5m_ns
latest_completed_15m_ns
```

### Exclusions

The 1-second base should not contain the full feature library. Heavy features belong at their natural completed timeframe.

---

## 4.2 Timeframe observation tables

Canonical tables:

```text
observations_5s
observations_30s
observations_1m
observations_5m
observations_15m
```

### Row grain

One row per completed bar for the named timeframe.

### Required immutable key

```text
instrument_id
observation_id
checkpoint_ns
```

`observation_id` should be deterministic from:

```text
instrument_id
timeframe
checkpoint_ns
observation_schema_version
```

### Required columns

```text
timeframe
bar_open_ns
bar_close_ns
open
high
low
close
volume
session_date
session_type
```

### Required regime tags

```text
primary_regime_timeframe       # initially "1m"
primary_regime_id              # alias of regime_1m_id
regime_1m_id
regime_1m_direction
regime_1m_start_ns
regime_1m_age_seconds
regime_30s_id
regime_30s_direction
regime_5m_id
regime_5m_direction
regime_15m_id
regime_15m_direction
regime_definition_version
```

### Required source timestamps

```text
source_5s_close_ns
source_30s_close_ns
source_1m_close_ns
source_5m_close_ns
source_15m_close_ns
```

Each source timestamp must identify the most recent completed bar available at `checkpoint_ns`.

---

## 4.3 Feature modules

### Purpose

Allow feature families to be added, corrected, retired, or recomputed independently.

### Storage convention

```text
features/
  timeframe=<tf>/
    family=<family_name>/
      version=<version>/
```

### Required key

```text
instrument_id
observation_id
checkpoint_ns
```

### Required metadata

```text
feature_family
feature_family_version
feature_manifest_hash
source_observation_schema_version
source_data_manifest_hash
calculation_code_hash
created_at_utc
```

### Example feature families

```text
f0
ohlcv_est_delta
price_level_context
regime_path
rolling_structure
momentum
volatility
session_context
micro_confirmation
```

### Rule

A feature module may only contain values known at or before `checkpoint_ns`.

---

## 4.4 Model score modules

### Storage convention

```text
scores/
  model=<model_id>/
    version=<model_version>/
```

### Required key

```text
instrument_id
observation_id
checkpoint_ns
```

### Required columns

```text
model_id
model_version
model_direction
raw_score
probability
in_domain
percentile
threshold_manifest_hash
feature_manifest_hash
model_artifact_hash
score_source_checkpoint_ns
```

Scores must be written at the model's canonical trained cadence. For the current fade models, that is completed 5-second observations.

---

## 4.5 Signal selection modules

### Purpose

Freeze a research population without modifying the observation or score tables.

### Example

```text
first in-domain Top-2.5% score per confirmed 1m regime
```

### Required columns

```text
selection_id
selection_rule_id
selection_rule_version
trade_id
instrument_id
observation_id
checkpoint_ns
primary_regime_id
model_id
trade_direction
rank_within_regime
selected
threshold_manifest_hash
```

A new entry rule creates a new selection module, not a rewrite of prior datasets.

---

## 4.6 Trade-path modules

### Purpose

Preserve the full one-second price and state path for selected research trades.

### Row grain

One row per `trade_id` per completed 1-second bar from the frozen start to the frozen terminal event.

### Required key

```text
trade_id
bar_close_ns
```

### Required columns

```text
instrument_id
trade_direction
selection_checkpoint_ns
bar_open_ns
bar_close_ns
open
high
low
close
volume
regime_1m_id
regime_1m_direction
atr_at_selection
normalized_close_from_selection_atr
favorable_intrabar_extreme_atr
adverse_intrabar_extreme_atr
running_mfe_atr
running_mae_atr
is_alignment_confirm_flip
is_opposite_confirm_flip
path_complete
censor_reason
```

Directional naming must remain explicit. Avoid ambiguous short-side fields such as `high_from_entry_atr` and `low_from_entry_atr`.

---

## 4.7 Forward-outcome modules

### Purpose

Store labels and future-path summaries separately from causal features.

### Examples

```text
seconds_to_alignment_flip
return_at_alignment_flip_atr
mfe_to_alignment_flip_atr
mae_to_alignment_flip_atr
aligned_regime_duration_seconds
full_trade_mfe_atr
full_trade_mae_atr
return_at_opposite_flip_atr
giveback_atr
mfe_capture_ratio
```

### Required metadata

```text
outcome_definition_id
outcome_definition_version
terminal_event_definition
censor_policy
```

These columns must never be included automatically in a training feature view.

---

## 5. Regime identity contract

## 5.1 Deterministic regime ID

Recommended source fields:

```text
instrument_id
timeframe
confirmed_regime_start_ns
direction
regime_definition_version
```

Recommended ID:

```text
SHA256(instrument_id | timeframe | confirmed_regime_start_ns | direction | regime_definition_version)
```

A readable short ID may be stored alongside the full hash.

## 5.2 Regime membership

A row belongs to the regime state known after processing all events up to that row's completed timestamp.

A lower-timeframe row must never be tagged with a higher-timeframe regime change that was confirmed later.

## 5.3 Regime versions

Changing any of the following requires a new `regime_definition_version`:

- EMA parameters;
- confirmation logic;
- bar labeling semantics;
- session handling that affects regimes;
- sticky-state rules;
- warmup rules.

Old and new regime universes must coexist rather than overwrite one another.

---

## 6. Physical partitioning

Recommended layout:

```text
research_store/
  instrument=NQ/
    market_state_1s/
      schema=v1/year=2024/month=01/

    observations/
      timeframe=5s/schema=v1/year=2024/month=01/
      timeframe=30s/schema=v1/year=2024/month=01/
      timeframe=1m/schema=v1/year=2024/month=01/
      timeframe=5m/schema=v1/year=2024/month=01/
      timeframe=15m/schema=v1/year=2024/month=01/

    features/
      timeframe=5s/family=f0/version=v1/year=2024/month=01/
      timeframe=1m/family=regime_path/version=v1/year=2024/month=01/

    scores/
      model=BEARISH_FADE_TO_BULLISH_FLIP_TOP25_GBT_V2/
        version=v2/year=2024/month=01/

    selections/
      rule=first_top2_5_per_1m_regime/version=v1/year=2024/month=01/

    trade_paths/
      population=fade_top2_5/version=v1/year=2024/month=01/

    outcomes/
      definition=alignment_to_opposite_flip/version=v1/year=2024/month=01/
```

Use monthly partitions to bound memory, make failed runs resumable, and permit targeted rebuilds.

---

## 7. Manifests and provenance

Every generated partition must have a sidecar manifest containing:

```text
run_id
instrument
period_start
period_end
input_files
input_hashes
collector_version
repository_commit
configuration_hash
regime_definition_version
observation_schema_version
feature_manifest_hashes
row_count
min_timestamp
max_timestamp
duplicate_key_count
null_summary
runtime_seconds
peak_memory_mb
output_hash
status
```

A dataset is not canonical without a valid manifest.

---

## 8. Validation gates

## 8.1 Base event validation

- strict timestamp monotonicity;
- no duplicate 1-second keys;
- expected bar count accounting for session gaps;
- no partial higher-timeframe close;
- correct Databento open-label to NT close-processing semantics.

## 8.2 Regime validation

- deterministic sampled parity with the frozen regime engine;
- same 1m regime ID across all timeframe rows covering the same interval;
- no row tagged with a future regime;
- explicit neutral/unconfirmed handling.

## 8.3 Feature validation

- exact ordered feature-name manifest;
- deterministic sample parity;
- null and range checks;
- source timestamps no later than the observation timestamp;
- no forward-outcome column in feature modules.

## 8.4 Score validation

- exact model artifact hash;
- exact feature manifest hash;
- score parity against frozen reference checkpoints;
- canonical 5-second cadence;
- no duplicate score per model and observation.

## 8.5 Trade-path validation

- raw 1-second bar parity;
- every trade summary recomputed from its stored path;
- terminal event and censor reason consistency;
- no missing internal path second unless explicitly documented;
- direction-normalized favorable/adverse calculations tested for long and short.

---

## 9. Build phases

## Phase 0 — contract freeze

Freeze:

- timestamps;
- bar-completion semantics;
- regime definitions;
- observation keys;
- partitioning;
- feature family registry;
- manifests;
- censoring.

## Phase 1 — two-day end-to-end smoke

Produce all base observation tables for two deterministic days.

Acceptance:

- raw-bar parity;
- regime parity;
- cross-timeframe regime-tag parity;
- schema and manifest validity.

## Phase 2 — one-month base build

Produce `market_state_1s` and all timeframe observation tables.

Measure runtime, memory, and output size.

## Phase 3 — feature modules

Generate existing approved feature families at their natural timeframe.

Do not add new research features during infrastructure validation.

## Phase 4 — score and selection modules

Score frozen models and reproduce known checkpoint populations.

Report extra, missing, duplicate, retimed, and rescored observations.

## Phase 5 — trade paths and outcomes

Build complete selected-trade paths through the frozen terminal event.

## Phase 6 — annual expansion

Expand monthly partitions only after the prior gate passes.

---

## 10. Adding a new feature

A new feature request must answer:

1. What decision will it inform?
2. What is the natural timeframe?
3. What source data and warmup does it require?
4. Can it be derived from existing canonical data?
5. Is it causal at `checkpoint_ns`?
6. Does it belong to an existing family or a new family?
7. How will it be validated?
8. Does deployment require a new runtime tracker?

### Decision tree

```text
Can the feature be derived exactly from existing stored inputs?
    |
    +-- Yes --> build a new versioned feature module
    |
    +-- No --> extend the collector/base schema and rebuild only affected partitions
```

Never silently mutate an existing feature version.

---

## 11. Beginning new research inside the existing regime structure

A new study should normally avoid new collection.

The study workflow is:

```text
1. Freeze the event population.
2. Choose the observation timeframe.
3. Select required feature modules.
4. Select or create a score module.
5. Define labels/outcomes separately.
6. Build a disposable study view.
7. Run bounded diagnostics.
8. Promote only surviving logic into NT runtime validation.
```

Examples:

- Study regime maturity: join 5s observations, regime-path features, and flip outcomes.
- Study secondary triggers: join selected signals to `market_state_1s` paths.
- Study model thresholds: read score modules and create a new selection module.
- Study opposite-model exits: join trade paths with carried-forward 5s score modules.

---

## 12. Training-view policy

Training datasets are disposable materializations, not canonical sources.

Example:

```text
training_views/
  study=fade_entry_filter/
    version=v3/
      train_2024.parquet
      validation_2025.parquet
      manifest.json
```

The manifest must list:

- source observation versions;
- included feature modules and columns;
- label definition;
- population filters;
- split policy;
- excluded columns;
- hashes.

Unused feature columns should not be loaded into the training view.

---

## 13. Runtime and resource rules

- Build and write monthly partitions.
- Flush bounded row groups rather than retaining a year in memory.
- Emit progress and usable intermediate manifests.
- Resume only when input and configuration hashes match.
- Fail on duplicate keys, timestamp regression, or schema drift.
- Record runtime and peak memory for every partition.
- Do not automatically proceed from smoke to annual expansion.

Suggested targets:

```text
Two-day smoke: <=10 minutes
One-month base partition: <=30 minutes target
Maximum silent interval: 10 minutes
Maximum phase before usable artifact: 45 minutes
```

Targets are operational goals, not correctness exemptions.

---

## 14. What this platform does and does not guarantee

### It does provide

- causal observation history;
- reusable cross-timeframe context;
- deterministic regime membership;
- modular feature expansion;
- reproducible model scores;
- complete selected-trade paths;
- faster hypothesis iteration.

### It does not replace

- deployment-realistic strategy generation;
- order submission and fill simulation;
- MBP-1 execution validation;
- final OOS policy validation;
- independent look-ahead audit.

---

## 15. Acceptance definition

The platform is ready for general research use when:

1. Two deterministic days pass raw-bar, aggregation, regime, and feature parity.
2. One monthly partition completes within bounded resources.
3. Observation keys are unique and stable across reruns.
4. Shared 1m regime IDs reconcile across all timeframes.
5. Existing model scores reproduce frozen reference checkpoints within the approved causal contract.
6. Every stored trade summary reconciles to its one-second path.
7. Manifests make every dataset version reproducible.
8. A new feature module can be added without rewriting unaffected canonical layers.

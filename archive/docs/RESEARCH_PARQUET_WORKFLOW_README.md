<!-- DOC-STATUS-BANNER -->
> **[STALE — SUPERSEDED]**
>
> Superseded by **docs/RESEARCH_WORKFLOW.md §15**.
>
> Superseded by `research/analysis/`.
>
> Kept for its reasoning and for the audit trail. **Not a source of instructions.**
> Classification: `docs/DOCUMENT_MAP.md`.

# Research Parquet Workflow README

This README explains how to use the NautilusTrader research parquet platform when:

1. starting a new study within the existing regime structure;
2. adding a new feature;
3. changing a model or score threshold;
4. creating a new trade population;
5. validating a candidate strategy in NautilusTrader.

For the full architecture and data contracts, see `RESEARCH_PARQUET_PLATFORM_BLUEPRINT.md`.

---

## 1. Core idea

The platform separates the research process into immutable layers:

```text
Observations -> Features -> Scores -> Selections -> Paths -> Outcomes
```

Each layer has a different responsibility:

| Layer | Meaning |
|---|---|
| Observations | Completed market bars and causal state at a timestamp |
| Features | Transformations known at that timestamp |
| Scores | Output from a specific frozen model |
| Selections | Events chosen by an explicit research rule |
| Paths | One-second evolution after a selected event |
| Outcomes | Future labels and policy results |

Do not mix future outcomes into feature modules.

---

## 2. Available canonical populations

The standard observation cadences are:

```text
1s, 5s, 30s, 1m, 5m, 15m
```

### `market_state_1s`

Use for:

- complete trade paths;
- stop and target simulation;
- secondary entry triggers;
- precise MFE and MAE;
- time-to-event analysis;
- execution-harness preparation.

### Timeframe observations

Use the table matching the natural decision cadence:

| Table | Typical use |
|---|---|
| `observations_5s` | Fade-model scoring, micro confirmation, short-horizon transition research |
| `observations_30s` | Intermediate transition and rolling-context studies |
| `observations_1m` | Primary regime analysis and regime-level models |
| `observations_5m` | Broader trend and volatility context |
| `observations_15m` | Session-scale structure and location |

Every observation carries the active confirmed 1m regime ID and the available regimes from other tracked timeframes.

---

## 3. Starting a new study with existing data

Most new studies should not begin by changing the collector.

### Step 1 — write the decision question

Examples:

```text
Does regime extension at a fade signal identify delayed-flip losers?
```

```text
Does a 5-second counter-direction close reduce MAE without losing too much MFE?
```

```text
Does the opposite model warn of giveback before the next confirmed flip?
```

Use the project `STUDY_PROMPT_TEMPLATE.md` to freeze the study contract.

### Step 2 — freeze the population

Specify exactly:

- instrument;
- period;
- session;
- direction;
- primary regime definition;
- observation cadence;
- entry or event rule;
- overlap policy;
- censoring.

Example:

```text
First in-domain Top-2.5% Bearish Fade score per confirmed bearish 1m regime,
2024-2025, both RTH and ETH, one signal per regime.
```

### Step 3 — choose existing layers

Example entry-filter study:

```text
observations_5s
+ features_5s/regime_path/v1
+ scores/BEARISH_FADE_TO_BULLISH_FLIP_TOP25_GBT_V2/v2
+ outcomes/alignment_flip/v1
```

Example secondary-trigger study:

```text
selections/first_top2_5_per_1m_regime/v1
+ market_state_1s
+ outcomes/alignment_flip/v1
```

### Step 4 — build a disposable study view

Select only required columns.

Do not copy the entire feature library into every study.

The study-view manifest must record:

- source datasets and versions;
- join keys;
- feature columns;
- score version;
- labels;
- filters;
- period and split;
- output hash.

### Step 5 — run bounded analysis

Recommended progression:

```text
2 days -> 1 month -> 3 nonadjacent months -> full research period
```

Do not expand merely because the code runs. Expand when the hypothesis shows useful and repeatable separation.

### Step 6 — promote only surviving logic

A promising parquet result must be implemented in the streaming NT strategy path and tested end to end.

---

## 4. Adding a new feature

### Step 1 — classify the feature

Ask whether it is:

- a causal input;
- a model output;
- selection metadata;
- or a forward outcome.

Only causal inputs belong in feature modules.

### Step 2 — choose its natural timeframe

Examples:

| Feature | Natural storage cadence |
|---|---|
| 5s directional efficiency | 5s |
| 1m regime extension | 1m or projected to lower-timeframe observations |
| 15m structural location | 15m |
| seconds since 1m regime extreme | 1s if needed for path triggers; otherwise 5s |
| full-trade MFE | Outcome module, not a feature |

Do not compute a feature every second if it only changes when a 5-second or 1-minute bar closes.

### Step 3 — determine whether a replay is required

#### No NT replay needed

The feature can be derived exactly from stored causal inputs.

Action:

```text
Create a new versioned feature module keyed by observation_id.
```

#### NT replay required

The feature requires:

- state that was never stored;
- a different warmup history;
- different bar-completion semantics;
- order-book information;
- corrected regime assignment;
- event sequencing lost in aggregation.

Action:

```text
Extend the canonical collector and rebuild only affected monthly partitions.
```

### Step 4 — implement as a versioned module

Recommended path:

```text
features/timeframe=5s/family=regime_extension/version=v1/
```

Required metadata:

```text
feature manifest
source schema version
code hash
source data hash
created timestamp
```

### Step 5 — validate

At minimum:

- deterministic checkpoint comparison;
- causal source timestamps;
- long/short symmetry where applicable;
- null/range tests;
- no duplicate keys;
- exact feature-name registry match.

### Step 6 — do not mutate old versions

A corrected definition becomes `v2`. Existing models continue to point to `v1` until intentionally retrained.

---

## 5. Adding a feature to an existing training dataset

Do not edit the canonical observation parquet.

Instead:

1. create the feature module;
2. register its columns and version;
3. join it into a new disposable training view;
4. create a new training-view manifest;
5. retrain under a new model version.

Example:

```text
training_view fade_long_top100_v3
    = observations_5s/v1
    + f0/v1
    + regime_path/v2
    + price_level_context/v1
```

Unused columns remain in their source modules and are not loaded.

---

## 6. Changing a model or threshold

### New model using existing features

No market replay is required.

1. build a training view;
2. train and freeze the model;
3. save the model and feature-manifest hashes;
4. score the canonical observation population;
5. write a new score module.

### New threshold or percentile

Do not rescore unless the model changed.

1. read the existing score module;
2. use the frozen calibration/reference population;
3. create a new threshold manifest;
4. create a new selection module.

### New selection rule

Examples:

- first Top-2.5% score per regime;
- highest score per regime;
- first score after regime age 900 seconds;
- first score plus secondary trigger.

Each becomes a separately versioned selection module.

---

## 7. Building and using trade paths

Trade paths are generated after a selection population is frozen.

### Freeze path boundaries

Define:

- path start timestamp;
- observation versus executable entry convention;
- terminal event;
- cross-session/year behavior;
- censoring;
- overlapping trade policy.

### Standard current lifecycle

```text
fade signal
-> predicted confirming flip
-> aligned regime
-> next opposing confirmed flip
```

### Path analysis examples

From a complete path, research can simulate:

- 0.5, 1.0, and 1.5 ATR stops;
- delayed entry triggers;
- break-even rules;
- trailing stops;
- time exits;
- score-based exit warnings;
- MFE capture and giveback.

Any strategy using actual orders and fills must still be reimplemented and validated in the NT backtest engine.

---

## 8. Joining across timeframes

Use deterministic observation keys and source timestamps.

A 5-second observation may only use the latest completed higher-timeframe row available at its checkpoint.

Example:

```text
5s checkpoint: 10:01:15
latest completed 1m source: 10:01:00
latest completed 5m source: 10:00:00
latest completed 15m source: 10:00:00
```

Never join a 5-second row to the 1-minute bar closing at 10:02:00 merely because it shares the same wall-clock minute.

For research joins, prefer the persisted `source_<tf>_close_ns` rather than recomputing an as-of join independently.

---

## 9. Deciding whether to extend the collector

Extend the collector only when at least one of these is true:

1. the new field requires state unavailable in canonical storage;
2. the field cannot be reconstructed exactly from stored bars;
3. timestamp-sensitive semantics must be generated inside NT;
4. the feature will be broadly reusable enough to justify canonical storage;
5. a production tracker must eventually calculate the same value.

Do not extend the collector for a one-off arithmetic transformation that can be safely built from existing parquet.

---

## 10. Promotion levels

Use explicit research status labels.

### `EXPLORATORY`

Parquet-only analysis; useful for hypothesis generation.

### `CAUSAL_RESEARCH`

Generated from causal NT observations and validated feature modules, but not yet executed as a strategy.

### `NT_POLICY_VALIDATED`

Candidate generation, features, scoring, triggers, orders, and fills reproduced in the NT streaming backtest.

### `DEPLOYMENT_REALISTIC`

Validated using the required MBP-1 or quote/tick execution stream and realistic order sequencing.

Do not describe parquet-only economics as deployable strategy results.

---

## 11. Common workflows

## Workflow A — investigate a regime hypothesis

```text
1. Select observations_5s or observations_1m.
2. Filter by regime_1m_id/direction/age.
3. Join existing regime and context features.
4. Join a clearly versioned forward outcome.
5. Compare matched groups.
6. Expand only if stable.
```

## Workflow B — test a secondary entry trigger

```text
1. Read an existing selection module.
2. Attach market_state_1s from selection to alignment flip.
3. Define trigger causally.
4. Recalculate entry mark, MFE, MAE, and retention.
5. Promote the best trigger to NT strategy validation.
```

## Workflow C — add a new context feature

```text
1. Confirm source data already exists.
2. Choose timeframe and family.
3. Generate feature module by monthly partition.
4. Validate sampled values and timestamps.
5. Register module.
6. Build a new study/training view.
```

## Workflow D — retrain a model

```text
1. Freeze feature manifest.
2. Freeze population and split.
3. Materialize training view.
4. Train and save artifact hashes.
5. Score canonical observations.
6. Create threshold and selection modules.
7. Validate in NT runtime.
```

## Workflow E — study a new regime timeframe

```text
1. Choose the tracked regime ID, such as regime_5m_id.
2. Define it as primary_regime_id in the study view.
3. Reuse existing observations and feature modules.
4. Create only missing outcome definitions.
5. Do not rebuild base data unless the regime definition itself changes.
```

---

## 12. Research checklist

Before running:

- [ ] Decision question is explicit.
- [ ] Population is frozen.
- [ ] Observation cadence is appropriate.
- [ ] Regime definition and version are named.
- [ ] Feature modules and versions are listed.
- [ ] Outcome definition is separate from features.
- [ ] Source timestamps are causal.
- [ ] Expansion rule and runtime limit are set.

Before accepting results:

- [ ] Counts reconcile to the population contract.
- [ ] No duplicate observation or trade keys exist.
- [ ] Long and short normalization is correct.
- [ ] Results are split by year, direction, and session where relevant.
- [ ] Full-population results accompany filtered results.
- [ ] Findings are labeled exploratory or validated correctly.
- [ ] Surviving policy is queued for NT streaming validation.

---

## 13. Naming rules

Use names that reveal meaning and version.

Good:

```text
regime_1m_distance_from_directional_extreme_atr
features/timeframe=5s/family=regime_path/version=v2
selection_rule=first_top2_5_per_1m_regime_v1
```

Avoid:

```text
feature_new
final_v7
best_model
high_from_entry_atr
```

For direction-normalized path fields, use:

```text
favorable_*
adverse_*
```

rather than high/low names that reverse meaning for shorts.

---

## 14. Minimal study manifest example

```yaml
study_id: bearish_fade_regime_extension_v1
instrument: NQ
observation_table: observations_5s/schema=v1
primary_regime: regime_1m_id
period:
  start: 2024-01-01
  end: 2025-12-31
population:
  selection_rule: first_top2_5_per_1m_regime_v1
features:
  - family: regime_path
    version: v1
    columns:
      - regime_1m_age_seconds
      - regime_1m_extension_atr
      - distance_from_regime_extreme_atr
scores:
  model: BEARISH_FADE_TO_BULLISH_FLIP_TOP25_GBT_V2
  version: v2
outcome:
  definition: alignment_flip_v1
split:
  discovery: 2024
  validation: 2025
status: CAUSAL_RESEARCH
```

---

## 15. Final operating rule

Use the canonical parquet platform to avoid rebuilding known causal history.

Use new feature modules to extend that history without corrupting old versions.

Use disposable study views to answer narrow questions quickly.

Use NautilusTrader streaming backtests as the final gate for any entry, exit, or execution policy intended to become a strategy.

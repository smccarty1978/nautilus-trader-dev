# Full Trade Path and Dual-Model Builder Specification — Implementation-Ready Revision

**Status:** Revised specification  
**Decision:** Architecture approved conditionally; implementation is blocked until the Bullish model is corrected and refrozen causally.  
**Primary purpose:** Build canonical causal artifacts for complete trade-lifecycle analysis, opposite-model exit-warning research, and dynamic exit-policy simulation.

---

# 1. Executive Decision

The builder will not treat the current Bullish model as canonical because its frozen artifact contains a known one-second feature look-ahead.

Before the builder is accepted:

1. Correct the Bullish feature timing.
2. Retrain or refreeze the Bullish model under the corrected causal feature contract.
3. Freeze its ordered feature list, adapter, calibration, scoring cadence, and thresholds.
4. Pass offline/runtime feature-vector and probability parity.

Until that work is complete, any Bullish score may only appear in a separate provisional research artifact and must never satisfy the canonical builder acceptance criteria.

The canonical builder therefore has two phases:

```text
Phase A — correct and refreeze Bullish model
Phase B — build dual-model score and full-path artifacts
```

No canonical dual-model dataset is complete after Phase A alone.

---

# 2. Scope

The builder must support the full lifecycle:

```text
fade entry
→ predicted confirmation flip
→ regime aligns with the trade
→ hold through aligned regime
→ exit at next confirmed opposite regime flip
```

It must allow later testing of fixed stops, break-even rules, trailing stops, retracement exits, time stops, opposite-model exits, hybrid score-plus-price exits, fallback regime-flip exits, and MFE-capture improvement.

The builder records factual paths and scores only. It does not select or optimize an exit policy.

---

# 3. Canonical Frozen Models

## 3.1 Bullish Fade model

Meaning:

```text
prevailing bullish regime
→ forecast bearish confirmed flip within 300 seconds
→ candidate short fade
```

Canonical use requires a newly corrected causal artifact.

Required frozen components:

```text
model binary
manifest
ordered feature list
feature adapter
calibration artifact
threshold manifest
training-domain definition
scoring cadence
model card
hashes
```

The current noncausal artifact must be marked:

```text
PROVISIONAL_NONCAUSAL_RESEARCH_ONLY
```

and excluded from canonical acceptance.

## 3.2 Bearish Fade model

Meaning:

```text
prevailing bearish regime
→ forecast bullish confirmed flip within 300 seconds
→ candidate long fade
```

Its existing strict artifact may be used only after its adapter, ordered vector, calibration, cadence, and thresholds pass the same parity gates defined below.

---

# 4. Model-Specific Feature Architecture

A shared causal market-state layer is allowed. A shared final feature vector is not.

Required architecture:

```text
shared causal market state
├── Bullish adapter
│   └── exact frozen Bullish ordered feature vector
└── Bearish adapter
    └── exact frozen Bearish ordered feature vector
```

Each adapter must independently define exact input names, exact ordering, direction mapping, missing-value handling, reset behavior, warm-up requirements, valid regime domain, valid session domain, and score availability.

Parity must be tested at two levels for each model:

1. exact feature-vector parity;
2. exact model-output parity.

Matching probabilities without vector parity is insufficient.

---

# 5. Canonical Scoring Cadence

The initial canonical cadence is:

```text
every completed five-second checkpoint
```

The one-second path artifact will carry forward the most recent valid five-second score.

Every carried score must include:

```text
score_source_ns
score_age_seconds
is_carried_forward
```

A carried score must never be represented as newly computed.

One-second scoring may be added only as a separately versioned builder after one-second feature parity, score parity, calibration review, new percentile/threshold manifests, and explicit acceptance of the changed observation population.

---

# 6. Global Score Population

`canonical_model_scores` must be collected directly inside the causal NautilusTrader event loop.

It must not be derived from completed-regime artifacts, future-known flip populations, rows requiring a later `confirm_flip_ns`, selected-trade populations, or retrospective checkpoint expansion.

The global population includes every eligible five-second scoring checkpoint in the configured study window, including active bullish regimes, active bearish regimes, neutral or unconfirmed states when model features are computable, and trailing right-censored regimes at the dataset boundary.

Rows must never be excluded because no future flip occurred.

---

# 7. Frozen Trade-Selection Population

## 7.1 Entry candidate

A candidate is created when:

```text
model is in its approved regime domain
AND score is available
AND score meets the frozen Top-2.5% threshold
```

Thresholds must come from the model-specific frozen threshold manifest. No retrospective percentile computed from the study period may be used.

## 7.2 One entry per regime

Use:

```text
first qualifying Top-2.5% checkpoint per regime
```

Later qualifying checkpoints in the same regime do not create additional canonical trades. Store them in the global score artifact only.

## 7.3 Direction

```text
Bullish Fade qualification → candidate short
Bearish Fade qualification → candidate long
```

Out-of-domain model scores may be stored for research but may not create canonical entries.

## 7.4 Overlap policy

Canonical trade construction is signal-population based, not portfolio-constrained.

Therefore:

- long and short canonical trades may overlap;
- multiple trades may overlap across different regimes;
- every qualifying regime creates its own independent canonical trade;
- no global position lockout is applied;
- trade paths may duplicate underlying one-second bars.

Portfolio-constrained economics are a later NautilusTrader execution study and are not part of this factual builder.

## 7.5 Deterministic trade ID

```text
trade_id = hash(
    instrument_id,
    entry_model_id,
    regime_start_ns,
    checkpoint_decision_ns,
    trade_direction
)
```

The hash algorithm and serialization format must be frozen.

---

# 8. Percentiles, Deciles, and Thresholds

Each model must have its own frozen reference distribution and threshold manifest.

Required fields:

```text
model_id
model_version
reference_population_description
reference_start_date
reference_end_date
session_scope
regime_domain
scoring_cadence
score_type
top_10_threshold
top_5_threshold
top_2_5_threshold
decile_boundaries
percentile_mapping_method
manifest_hash
```

Rules:

1. Thresholds may not be derived from the current study period.
2. Thresholds must come from a frozen development or training reference population.
3. Bullish and Bearish models use separate manifests.
4. In-domain percentiles are canonical.
5. Out-of-domain percentiles are exploratory and must be labeled `is_exploratory_out_of_domain_rank = true`.
6. If Top-10% was not frozen upstream, it remains unavailable until a threshold manifest is explicitly created and reviewed.
7. Do not synthesize a Top-10 threshold retrospectively from 2024–2025.

---

# 9. Timestamp and Price Semantics

The canonical artifacts are descriptive market-path artifacts, not execution-fill artifacts. Field names must use `reference` or `mark`, not `fill` or `realized trade PnL`.

## 9.1 Decision timestamp

```text
checkpoint_decision_ns
```

Definition: the right boundary of the completed five-second checkpoint. All features and scores must be causally available at this timestamp.

## 9.2 Entry reference

```text
checkpoint_reference_price
```

Definition: close of the completed five-second checkpoint used for the decision. This is not an executable fill.

The canonical path begins with the first completed one-second bar whose market interval begins at or after `checkpoint_decision_ns`.

## 9.3 First executable bar

```text
first_eligible_bar_open_ns
first_eligible_bar_open_price
```

Definition: first one-second bar open after the decision timestamp under the repository's open-labelled bar contract.

This field is stored for later execution comparison, but the descriptive baseline remains anchored to `checkpoint_reference_price`.

## 9.4 Confirmation milestone

```text
confirm_flip_ns
confirm_flip_close_price
```

`confirm_flip_ns` is the causal right boundary at which the confirmed regime flip becomes known. `confirm_flip_close_price` is the confirming minute close.

Also store:

```text
first_bar_after_confirm_open_ns
first_bar_after_confirm_open_price
```

## 9.5 Fallback exit mark

```text
fallback_exit_flip_ns
fallback_exit_flip_close_price
```

Definition: next confirmed regime flip opposite the trade direction. The timestamp is the causal right boundary at which that confirmed flip becomes known; the price is the confirming minute close.

Also store:

```text
first_bar_after_fallback_exit_open_ns
first_bar_after_fallback_exit_open_price
```

## 9.6 Naming rule

Because these are marks, use:

```text
fallback_exit_mark_return_points
fallback_exit_mark_return_atr
```

Do not call them `realized_return`, `trade_pnl`, or `fill_return`. Actual executable PnL requires a separate NautilusTrader execution artifact.

## 9.7 Endpoint inclusion

The one-second path includes bars whose intervals satisfy:

```text
bar_open_ns >= first_eligible_bar_open_ns
AND bar_close_ns <= fallback_exit_flip_ns
```

The fallback confirmation bar is included through its final completed one-second component. The first one-second bar after the fallback flip is not part of the descriptive path, but its open is stored separately as an executable reference.

---

# 10. Required Artifacts

Produce partitioned Parquet datasets, not monolithic files:

```text
canonical_model_scores/
canonical_trade_population/
canonical_trade_paths/
```

Each dataset must include a versioned manifest.

---

# 11. Artifact A — canonical_model_scores

One row per eligible completed five-second scoring checkpoint.

Partition by:

```text
study_year
study_month
```

Required fields:

```text
timestamp_ns
instrument_id
study_year
study_month
session
prevailing_regime
is_regime_confirmed
regime_start_ns
regime_age_seconds
regime_age_bars
reference_price
atr_at_score
```

Bullish model:

```text
bullish_model_id
bullish_score_available
bullish_unavailable_reason
bullish_in_domain
bullish_raw_score
bullish_probability
bullish_percentile
bullish_decile
bullish_is_top_10
bullish_is_top_5
bullish_is_top_2_5
bullish_feature_vector_hash
```

Bearish model:

```text
bearish_model_id
bearish_score_available
bearish_unavailable_reason
bearish_in_domain
bearish_raw_score
bearish_probability
bearish_percentile
bearish_decile
bearish_is_top_10
bearish_is_top_5
bearish_is_top_2_5
bearish_feature_vector_hash
```

Future research labels, stored separately in the same row but never used in scoring:

```text
seconds_to_next_bullish_confirm_flip
seconds_to_next_bearish_confirm_flip
bullish_confirm_within_300s
bearish_confirm_within_300s
bullish_confirm_within_600s
bearish_confirm_within_600s
label_is_right_censored
```

---

# 12. Artifact B — canonical_trade_population

One row per selected first Top-2.5% signal per regime.

Partition by:

```text
entry_year
entry_month
trade_direction
```

Required fields include identity, entry references, both models at entry, confirmation milestone, fallback exit mark, full-path economics, and opposite-model summary.

Key identity and entry fields:

```text
trade_id
instrument_id
entry_model_id
trade_direction
entry_regime_direction
regime_start_ns
checkpoint_decision_ns
entry_year
entry_month
session
checkpoint_reference_price
first_eligible_bar_open_ns
first_eligible_bar_open_price
atr_at_entry
entry_raw_score
entry_probability
entry_percentile
entry_decile
```

Both models at entry:

```text
bullish_raw_score_at_entry
bullish_probability_at_entry
bullish_percentile_at_entry
bullish_in_domain_at_entry
bearish_raw_score_at_entry
bearish_probability_at_entry
bearish_percentile_at_entry
bearish_in_domain_at_entry
```

Confirmation milestone:

```text
confirm_flip_ns
confirm_flip_direction
confirm_flip_close_price
first_bar_after_confirm_open_ns
first_bar_after_confirm_open_price
seconds_entry_to_confirm
confirmed_within_300s
confirmed_within_600s
```

Fallback exit mark:

```text
fallback_exit_flip_ns
fallback_exit_flip_direction
fallback_exit_flip_close_price
first_bar_after_fallback_exit_open_ns
first_bar_after_fallback_exit_open_price
seconds_entry_to_fallback_exit
seconds_confirm_to_fallback_exit
path_is_complete
is_right_censored
censor_ns
censor_reason
terminal_mark_price
terminal_mark_ns
```

Full-path economics, all relative to `checkpoint_reference_price` and normalized by `atr_at_entry`:

```text
fallback_exit_mark_return_points
fallback_exit_mark_return_atr
full_trade_mfe_points
full_trade_mfe_atr
full_trade_mfe_ns
full_trade_mae_points
full_trade_mae_atr
full_trade_mae_ns
mfe_capture_ratio
giveback_from_mfe_atr
giveback_from_mfe_pct
```

For censored trades, fallback-return and capture fields are null, terminal-mark fields are populated, and `path_is_complete = false`.

Opposite-model summary after confirmation:

```text
opposite_exit_model_id
opposite_score_at_confirm
opposite_probability_at_confirm
opposite_percentile_at_confirm
max_opposite_score_after_confirm
max_opposite_probability_after_confirm
max_opposite_percentile_after_confirm
max_opposite_score_ns
opposite_first_top_10_ns
opposite_first_top_5_ns
opposite_first_top_2_5_ns
seconds_top_10_to_fallback_exit
seconds_top_5_to_fallback_exit
seconds_top_2_5_to_fallback_exit
```

Missing thresholds remain null with a reason field.

---

# 13. Artifact C — canonical_trade_paths

One row per completed one-second bar per selected trade.

Partition by:

```text
entry_year
entry_month
trade_direction
trade_id_prefix
```

Identity and ordering:

```text
trade_id
path_sequence
timestamp_open_ns
timestamp_close_ns
seconds_from_decision
seconds_from_confirm
trade_direction
prevailing_regime
is_regime_confirmed
```

`path_sequence` must be deterministic and strictly increasing within each trade.

Raw OHLC:

```text
open
high
low
close
```

Direction-normalized movement:

```text
open_pnl_atr
close_pnl_atr
favorable_intrabar_extreme_atr
adverse_intrabar_extreme_atr
```

For long:

```text
favorable = (high - checkpoint_reference_price) / atr_at_entry
adverse   = (low  - checkpoint_reference_price) / atr_at_entry
```

For short:

```text
favorable = (checkpoint_reference_price - low)  / atr_at_entry
adverse   = (checkpoint_reference_price - high) / atr_at_entry
```

`adverse_intrabar_extreme_atr` is stored as a signed value, normally non-positive.

Running path state:

```text
running_mfe_atr
running_mae_atr
running_close_pnl_atr
close_drawdown_from_running_mfe_atr
worst_intrabar_drawdown_from_running_mfe_atr
```

The implementation must document the exact update order.

Events:

```text
is_first_path_bar
is_confirm_flip_boundary
is_fallback_exit_boundary
is_final_path_bar
is_new_running_mfe
is_new_running_mae
touches_entry_this_bar
```

Both five-second model scores carried to one-second rows:

```text
bullish_raw_score
bullish_probability
bullish_percentile
bullish_in_domain
bullish_score_source_ns
bullish_score_age_seconds
bullish_is_carried_forward
bearish_raw_score
bearish_probability
bearish_percentile
bearish_in_domain
bearish_score_source_ns
bearish_score_age_seconds
bearish_is_carried_forward
```

---

# 14. Intrabar Ordering Limitation

One-second OHLC bars do not reveal the order of high and low inside the same bar.

Therefore the builder must not claim exact causal ordering when a one-second bar contains both a favorable milestone and an entry revisit or trailing-stop touch.

Classify affected observations as:

```text
ordering_deterministic
ordering_ambiguous_same_bar
```

Any policy sensitive to same-bar order requires MBP-1 or tick replay for final validation.

---

# 15. Censoring and Year Boundaries

Partition membership is based on entry year and entry month. A trade entered in December and exited in January remains in the December entry partition.

2026 remains sealed runtime OOS.

Default builder scope:

```text
entries through 2025-12-31 only
```

For trades entered in 2025 whose fallback exit occurs in 2026:

- do not use 2026 data in the research build;
- mark them right-censored at the 2025 boundary;
- populate terminal mark fields;
- exclude them from completed fallback-exit economics.

A later explicitly authorized runtime-OOS build may complete those paths, but must use a separate dataset version and report.

---

# 16. Partitioning, Scale, and Bounded Execution

Required partitioning:

```text
canonical_model_scores/
  study_year=YYYY/study_month=MM/

canonical_trade_population/
  entry_year=YYYY/entry_month=MM/trade_direction=LONG|SHORT/

canonical_trade_paths/
  entry_year=YYYY/entry_month=MM/trade_direction=LONG|SHORT/trade_id_prefix=XX/
```

Before execution, produce `ESTIMATE.md` containing eligible score rows, estimated selected trades, expected overlapping-trade multiplier, expected path rows, estimated sizes, runtime, and peak-memory target.

Build one calendar month at a time with streaming writes, bounded memory, deterministic ordering, resumable checkpoints, atomic partition completion, and failure-safe temporary paths.

Each completed partition must record input hashes, model hashes, threshold hashes, builder commit, configuration hash, row counts, timestamp bounds, output hashes, and completion timestamp. A resumed run must refuse to mix incompatible hashes.

---

# 17. Validation Gates

## 17.1 Every-trade summary-versus-path parity

Mandatory for every trade, not a sample.

Recompute from path rows and require parity for:

```text
full_trade_mfe_atr
full_trade_mae_atr
full_trade_mfe_ns
full_trade_mae_ns
fallback_exit_mark_return_atr
path first timestamp
path final timestamp
```

Any mismatch fails the partition.

## 17.2 Direct raw-bar parity

For deterministic samples in every monthly partition, compare source one-second OHLC rows directly with path rows. Include boundary bars, month-end entries, exact minute-boundary flips, long and short trades, and overlapping trades.

The sample seed and selected trade IDs must be recorded.

## 17.3 Score parity

For both models, validate:

1. model-specific ordered feature vector;
2. feature-vector hash;
3. raw score;
4. calibrated probability;
5. threshold flags.

Parity must compare offline frozen reference, builder, and NautilusTrader runtime.

Bullish canonical parity cannot pass until the causal artifact is corrected.

## 17.4 Global population integrity

Validate no future-conditioned filtering, monotonic five-second timestamps, expected cadence, explicit missing-score reasons, inclusion of trailing censored regimes, no duplicate score rows, and neutral/unconfirmed coverage.

## 17.5 Trade-selection parity

Recompute first Top-2.5% per regime directly from `canonical_model_scores` and require exact equality with `canonical_trade_population`.

Check no extra trades, no missing trades, no duplicated regimes, exact checkpoint timestamps, exact model IDs, and exact score/threshold values.

---

# 18. Required Reports

`BUILD_REPORT.md` must include:

- model artifact IDs, hashes, causal status, adapters, cadence, and thresholds;
- global-score rows by month, session, and regime;
- both-model availability by regime;
- in-domain versus exploratory rows;
- selected-trade counts and first-signal parity;
- completed versus censored counts;
- overlap and maximum concurrency;
- path rows and size by partition;
- every-trade parity result;
- raw-bar sample parity result;
- ambiguous same-bar ordering counts;
- baseline fallback-exit return, MFE, MAE, MFE capture, and giveback;
- opposite-model threshold lead times and false-warning rates.

No threshold optimization belongs in the builder report.

---

# 19. Acceptance Criteria

The canonical builder is accepted only when all are true:

1. The Bullish model has been corrected and refrozen causally.
2. Both model-specific feature adapters pass exact vector parity.
3. Both model outputs pass runtime parity at the canonical five-second cadence.
4. Frozen model-specific threshold manifests exist.
5. The global score population is collected directly in NautilusTrader.
6. The selected population is exactly first in-domain Top-2.5% signal per regime.
7. Timestamp and descriptive-price conventions are frozen and documented.
8. Every completed trade has a fallback exit mark price.
9. Full-path MFE/MAE cover decision through fallback exit.
10. Every trade passes summary-versus-path parity.
11. Deterministic raw-bar samples pass direct parity in every monthly partition.
12. Censored trades are explicit and excluded from completed-exit economics.
13. Both model scores remain inspectable across all computable regime states.
14. Out-of-domain scores are visibly exploratory.
15. Monthly partitioning, hashing, and resume behavior pass.
16. The baseline fallback-exit MFE-capture ratio can be computed directly.
17. Opposite-model exit-warning studies can be run without rebuilding source paths.

---

# 20. Implementation Sequence

## Phase A — Bullish artifact correction

1. Audit the one-second look-ahead.
2. Correct feature timing.
3. Rebuild the training population if required.
4. Retrain or refreeze.
5. Freeze the Bullish adapter and ordered vector.
6. Freeze calibration and threshold manifest.
7. Pass feature and score parity.

## Phase B — Global score collector

1. Implement shared causal state.
2. Implement separate Bullish and Bearish adapters.
3. Score at completed five-second checkpoints.
4. Write monthly `canonical_model_scores` partitions.
5. Validate global population integrity.

## Phase C — Trade selection

1. Apply frozen in-domain Top-2.5% thresholds.
2. Select first qualifier per regime.
3. Build deterministic trade IDs.
4. Validate exact population parity.

## Phase D — Full path builder

1. Attach one-second raw paths.
2. Continue through fallback exit or censor boundary.
3. Compute full-path extrema and mark returns.
4. Attach carried five-second scores.
5. Write monthly partitioned paths and summaries.

## Phase E — Acceptance audit

1. Every-trade summary/path parity.
2. Deterministic raw-bar parity.
3. Runtime feature/score parity.
4. Build report.
5. Audit sign-off.

---

# 21. First Study After Acceptance

Baseline:

```text
hold until confirmed opposite regime flip
```

Candidate warning thresholds:

```text
opposite model Top-5%
opposite model Top-2.5%
```

Top-10% is included only if a reviewed frozen threshold exists.

The first study should measure warning coverage, lead time, false-warning rate, MFE giveback after warning, mark return at the first executable bar after warning, difference versus fallback exit, and year/direction stability.

Do not optimize thresholds until the descriptive evidence shows that the opposite model contains stable exit information.

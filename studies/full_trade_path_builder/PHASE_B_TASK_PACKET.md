# Phase B Frozen Task Packet — Global Dual-Model Scores

## Objective

Build monthly `canonical_model_scores` partitions directly in a
NautilusTrader event loop for 2021–2025. Emit one factual row at every exact
RTH five-second decision boundary, independent of future flips and independent
of whether either model is in domain or scoreable.

## Frozen models

### Bullish Fade

- Artifact: `artifacts/BULLISH_STRICT_top25_gbt_v2`
- Model SHA-256:
  `ac833f5f4c983b791f3632660d762dfd6fd47ecc20e78822797628c11e7817f8`
- Approved domain: established bullish regime.
- Candidate direction: short (`-1`).
- Its 2025 thresholds are retained as model provenance but are not applied
  inside the overlapping 2021-2025 Phase B window.

### Bearish Fade

- Artifact:
  `studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2`
- Model SHA-256:
  `1d696d85f2e31026db8415fb15913267d447bd7fde9be0fcefed490c7bf4af26`
- Canonical semantic alias: `bearish_fade_top25_gbt_v2`.
- Approved domain: established bearish regime.
- Candidate direction: long (`+1`).
- Its 2025 Top-5/Top-2.5 values are retained as model provenance but are not
  applied inside the overlapping 2021-2025 Phase B window.

The Top-25 Bearish challenger is selected rather than the Top-103 production
model because this final builder revision calls for the existing strict
artifact whose exact 25-feature runtime architecture is reviewable alongside
the corrected Bullish Top-25 artifact. This choice is explicit and must be
accepted by the Phase B pre-execution audit; it is not inferred at runtime.

## Global checkpoint population

- Decision grid: UTC epoch-aligned timestamps `T` with `T % 5s == 0`.
- Dispatch: exact one-second callback with `ts_init == T`, after incorporating
  the completed bar with `ts_event<T`, before an equal-`ts_init` minute callback.
- Session: `[08:30:00,15:00:00)` America/Chicago at decision `T`.
- Emit every grid row in session once ATR is initialized, including confirmed
  bullish, confirmed bearish, neutral/unconfirmed, non-established, null
  feature, and trailing regimes.
- Never require a later flip, completed regime, selected trade, or future label
  to emit a row.
- Missing exact dispatch callbacks are recorded and omitted; no timer or
  catch-up row is allowed.
- Each independent month uses a four-calendar-day causal prefix. The fourth
  day is required to preserve a complete preceding Globex trading day across
  weekends and the fall DST transition.

## Shared causal state and regime domain

- One shared `RegimeEngine` supplies confirmed direction, regime start,
  checkpoint ATR, and confirmed flip facts.
- On every confirmed transition, start a generic prevailing-regime domain
  tracker with immutable `(direction, confirm_flip_ns, reference_price,
  atr_at_regime_start)`.
- Favorable excursion follows prevailing direction:
  `max(0, direction*(extreme_price-anchor))/regime_atr`.
- Current progress is
  `direction*(reference_price-anchor)/regime_atr`.
- Established gate: age `>=120s`, MFE `>=1 ATR`, progress windows `>=2`,
  retained ratio `>=0.5`; progress windows use the frozen 120-second
  new-extreme rule.
- Bullish in-domain iff confirmed direction `+1` and established.
- Bearish in-domain iff confirmed direction `-1` and established.

## Separate feature adapters

Shared raw bars may be fanned out, but adapter state and final vectors are
separate.

### Bullish adapter

- Load the accepted frozen adapter and enforce all bound dependency hashes.
- Direction `-1`.
- Include the completed one-second bar ending at `T`.
- Minute state requires `ts_init<T`.
- Checkpoint ATR normalizes model features.

### Bearish adapter

- Exact ordered 25 features and hash from the strict artifact.
- Direction `+1`; `pct_levels_behind_trade` must use that direction.
- Use a distinct tracker instance.
- Reproduce the strict training attachment's one-second-derived minute buckets
  and source availability; do not drive its level/RTH state from catalog 1m
  bars.
- Snapshot at `T` after incorporating only completed one-second sources with
  `ts_event<T`. For exact parity with the strict training attachment, Bearish
  OHLCV and price-level features use the causal ATR frozen at the prevailing
  regime's confirmed start; `atr_at_checkpoint` remains stored separately.
- The synthetic feature minute is classified by its close label itself
  (08:30 is the first RTH feature minute), matching the strict attachment.
- Any null or non-finite feature suppresses the model score.

Both adapters must pass independent vector and probability parity before the
full build. Matching scores without vector parity is insufficient.

## Score and rank fields

- `raw_score == probability == predict_proba[:,1]` for both HGB models.
- Score unavailable rows persist with explicit reason.
- For both models, percentile, decile, Top-10, Top-5, and Top-2.5 fields are
  null throughout Phase B with unavailable reason
  `NO_PRE_STUDY_FROZEN_RANK_REFERENCE`.
- No 2025-derived threshold may be applied to a 2021-2025 row. No rank or
  threshold may be recomputed from Phase B output.
- The frozen 2025 values remain in model provenance only and may become
  eligible for a separately versioned post-2025 study; they are not policy
  fields in this dataset.
- Feature-vector hash: SHA-256 of the exact ordered little-endian float64
  vector; null vectors have no hash.
- Out-of-domain but feature-complete scores are allowed and explicitly marked
  exploratory.

## Future labels

Flip facts are emitted separately and joined only after collection.

- `seconds_to_next_bullish_confirm_flip`
- `seconds_to_next_bearish_confirm_flip`
- inclusive `(T,T+300s]` and `(T,T+600s]` flags
- `label_300_is_right_censored`
- `label_600_is_right_censored`
- the governing shared `label_is_right_censored` equals the conservative
  600-second censor flag; consumers of 300-second labels must use the
  horizon-specific 300-second flag
- same-time flips excluded
- right-censor if the required horizon is not observable
- month/year partitions carry forward; 2025 ends at the sealed
  `2026-01-01T00:00:00Z` boundary without reading later data
- The final `2025-12` partition is the sole partial CT-calendar partition: its
  exclusive end is exactly the sealed boundary above, not
  `2026-01-01 00:00 America/Chicago` (which would read six sealed UTC hours).

No label may affect checkpoint emission, features, scores, domains, or ranks.

## Required pre-full-run tests

- Exact five-second row keys, gaps, equal-time minute/flip order.
- RTH and DST boundaries.
- Generic bullish/bearish established-domain symmetry.
- Separate adapter state and direction mapping.
- Strict provenance and mutation failures.
- Bearish frozen vector and probability parity.
- Bullish frozen vector and probability parity.
- Null/suppression and out-of-domain exploratory behavior.
- Label boundaries at T, +300, +600, partition and sealed boundaries.
- A sealed-boundary fixture 400 seconds before the boundary must show the
  300-second labels observable and the 600-second labels censored.
- Prefix and month-boundary continuity.
- No 2026 path/content access.

## Outputs and acceptance

- Partition by `study_year/study_month`.
- Atomic Parquet, per-partition hashes, exact config/code/model/adapter/catalog
  identities, restart validation, and month-scoped missing diagnostics.
- Representative March 2025 benchmark before the full run.
- Global integrity: exact unique keys, no future-conditioned exclusions,
  expected grid coverage reconciliation, zero provenance violations.
- Mandatory completion audit with zero CRITICAL and zero WARNING.

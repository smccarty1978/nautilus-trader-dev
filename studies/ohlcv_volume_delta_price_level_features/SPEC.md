# OHLCV Volume/Delta and Price-Level Feature Foundation

## Status

**FROZEN SPEC — NOT IMPLEMENTED.** This is a feature-construction study only:
no model training, no entry/exit optimization, no economic conclusions. See
"Scout pass" below for two open design decisions that must be confirmed
before Part A/B implementation begins.

## Decision to inform

Can a bounded set of causal OHLCV-estimated volume/delta features and causal
price-level context features be added to the shared feature library, and
attached to the existing score-independent short-RTH surface, without
changing strategy mechanics, labels, or populations?

## Scout pass (read before implementing)

A scout pass over `features/` (new since the last CLAUDE.md update) and the
existing short-RTH study lineage found the following, which shapes this
SPEC's Part C/D design:

### 1. A "Central Feature System" already exists — this is not a greenfield build

`features/FEATURE_REGISTRY_CONTRACT.md` defines a two-layer architecture:
`features/registry.py` (`FeatureDefinition` metadata), `features/engine.py`
(`FeatureEngine`, composing trackers, driven by explicit `update_1s`/
`update_1m`/`update_5m` calls, snapshotted via `snapshot()`), and
`features/trackers/{velocity,volume,pullback}.py` (stateful trackers over
`deque` buffers). `features/collector.py`'s `FeatureCollector` wraps the
same `FeatureEngine` for offline/historical use — **the design intent
(confirmed by `features/audit.md`, finding D1) is that the identical
`FeatureEngine` is the single source of truth for both live execution and
offline feature collection**, i.e. historical features are meant to be
produced by replaying bars through the same object, not by a separately
maintained batch reimplementation.

Currently registered families: `arrival_velocity`, `arrival_volume`,
`pullback_1s`, `pullback_1m`, `context` (`is_rth`, `minutes_since_rth_open`,
`regime_age_bars`, EMA slopes). `features/library.py` separately hosts a
70-feature indicator-based library (EMA/RSI/ATR/volume/structure/time) not
wired into `FeatureEngine`/registry.py yet. Neither of these implements
Part A's estimated-delta formulas or any of Part B's price-level features.

### 2. Part A is adjacent to, but not a duplicate of, the existing `arrival_volume` family

`features/trackers/volume.py`'s `ArrivalVolumeTracker` already provides
`up_vol_ratio_10s`/`down_vol_ratio_10s` (split by **candle direction**,
`close >= open`), `rvol_*`, `vol_spike`, `vol_climax`, `vol_accel`,
`vol_price_corr_10s` — all relative-to-recent-history ratios over a single
rolling `deque(maxlen=60)`, not fixed-window sums. This study's Part A
(`bar_est_delta` = `volume * (2*close - high - low) / range`, split by
**close position within the bar's range**, over fixed 5s-1800s windows) is
a **different calculation basis and a different window design** — not a
duplicate. Per `FEATURE_REGISTRY_CONTRACT.md` §7 ("do not add a study-local
duplicate without a documented exemption"), this is the documented
exemption: register Part A under a **new** family (`ohlcv_est_delta`), name
every feature distinctly from the `arrival_volume` family, and note the
relationship explicitly in the registry metadata description so a future
reader does not mistake one for a reimplementation of the other.

### 3. Part B has zero existing implementation anywhere in the repo

Grep across `features/`, `studies/`, and `backtests/` found no prior
`opening_range`, `overnight_high/low`, `prior_day_*`, or level-clustering
implementation (the few incidental hits are unrelated scratch/RL-study
files). Part B is a genuinely new feature family — no exemption needed, no
prior art to reconcile against.

### 4. No canonical trading-day-boundary utility exists yet

Part B's "prior completed trading day" and "overnight session" both require
a trading-day boundary definition (e.g., CME futures day rolls at a fixed
Central-Time hour, not midnight). Nothing in `features/`, `regime_sequence_chop_context/`,
or `CODEX_5_X_weakness_atlas_repair/` defines this. **This must be built
once, in the narrowest appropriate shared location** (proposed:
`features/trackers/price_levels.py` module-level helper, registered as a
stateless context utility — not per-study logic, per the brief's own
"do not create parallel session/timestamp logic" constraint). Concrete
boundary choice (e.g., 17:00 CT) must be confirmed against whatever the
existing `RegimeIndicatorsV2`/regime-engine day-session convention already
assumes, if any — **open item, confirm before implementing overnight/prior-day
logic**, rather than silently picking a boundary.

### 5. Live per-bar tracker replay vs. this repo's established vectorized batch convention — a real performance tension

Every historical atlas-building pipeline in this repo to date
(`CODEX_5_X_build_repaired_atlas.py`, `build_weakness_atlas.py`,
`build_median_centers.py`) uses vectorized numpy/pandas batch computation
over full-year raw 1s files (~3.9-4.0M bars/year), completing in ~250-265s/year
(confirmed empirically in `[[short_rth_entry_surface_backfill]]`). The
Central Feature System's `FeatureEngine`/`FeatureCollector`, by contrast, is
architected as a per-bar Python-object replay (`deque.append` +
list-slicing + `np.mean`/`np.corrcoef` calls **inside** a per-bar loop).
Replaying 6 years × ~4M bars/year through that interface is very likely one
to two orders of magnitude slower than the vectorized convention — this has
not been benchmarked yet and should be, before committing to full-history
attachment (Part D) via live replay.

**Proposed resolution (confirm before implementing):** implement the Part
A/B formulas **once**, canonically, as `features/trackers/ohlcv_delta.py`
and `features/trackers/price_levels.py` tracker classes wired into
`FeatureEngine` (satisfies the registry contract's "single source of truth"
intent and makes the features available to any future live strategy). For
the large-scale historical attachment in Part D specifically, add a
**parity-tested vectorized batch re-derivation** of the identical formulas,
proven byte-identical to the tracker's own output on a bounded smoke sample
(the runtime-validation five-day period) via a dedicated parity test. This
mirrors this repo's own established and already-audited precedent
(`CODEX_5_X_build_repaired_atlas.py`'s `compute_activity_features_batched`
vs. its scalar reference, parity-tested to `rtol=atol=1e-12`) — not a silent
duplicate, but a documented, tested, dual-form implementation of one
registered calculation, chosen for tractable runtime on 6 years of history.
If a fast enough live-replay path is found during implementation (benchmark
first), this vectorized path can be dropped.

## Primary hypothesis

The current short-RTH feature set (152 causal features already used by
`[[short_rth_w4_retrain_entry_strength]]`: 49 center + 100 sequence + 5
local fields) is mostly price/regime-shape based, with only thin volume
representation (no per-bar delta estimate, no price-level context at all).
A bounded set of causal OHLCV-derived volume/delta features and causal
price-level context features may carry useful information for later models
or mechanical rules. This study only builds and validates the feature
foundation to test that hypothesis later — it does not test it.

## Source-of-truth inputs (reuse, do not reimplement)

- Raw completed 1s/1m bars: `data/raw/NQ_v0_1s_{year}.parquet` (existing,
  2016-2026), aggregated to 1m via `regime_sequence_chop_context/reproduce_regimes.py:aggregate_and_run_regimes`.
- ATR: `atr_at_checkpoint`/`atr_at_entry` already in the repaired atlas
  (Wilder ATR from the regime engine) — do not recompute a separate ATR.
- RTH classification: `CODEX_5_X_run_established_fade.is_rth()`, applied on
  **fill-time**, per the remediated convention in
  `[[short_rth_entry_surface_backfill]]` (audit "Remediation" — decision-time
  classification was found to diverge from fill-time at session boundaries).
- Session/established-regime gating, candidate surface: `entry_surface.build_surface`
  (`studies/short_rth_entry_surface_backfill/entry_surface.py`).
- Policy A labels: `label_full_surface.py` (same study) — already computed
  for 2021-2026 (813,972 rows 2021-2024 + 198,255/2025 + 63,021/2026, all in
  `studies/short_rth_w4_retrain_entry_strength/_work/labeled_featured_{year}.parquet`).
- Feature registry conventions: `features/registry.py`, `features/engine.py`,
  `features/FEATURE_REGISTRY_CONTRACT.md` (this SPEC's Part C target).
- Provenance/audit pattern: `lookahead-auditor` findings format already used
  throughout this project (`features/audit.md`,
  `short_rth_entry_surface_backfill/audit/audit.md`).

Do not use V2 collector. Do not use microstructure/order-book/bid-ask data
— this study is strictly OHLCV-derived.

## Required observation contract

Every emitted feature row must satisfy:

```text
latest_source_ts_used <= observation_ts
```

Each snapshot records `observation_ts`, `latest_1s_bar_close_ts_used`,
`latest_1m_bar_close_ts_used`, `latest_source_ts_used`. A violation is a
CRITICAL audit finding. `observation_ts` for this study equals the existing
surface row's `observation_time` (the established-checkpoint decision time
already used by `[[short_rth_entry_surface_backfill]]`), not the fill time —
features describe what is knowable at the decision, consistent with how the
149 existing causal features are already snapped.

## Part A — OHLCV estimated volume/delta features

### A1. Per-bar estimated delta

```text
range = high - low
if range > 0:
    bullish_volume_ratio = clamp((close - low) / range, 0, 1)
    bearish_volume_ratio = 1 - bullish_volume_ratio
    estimated_bullish_volume = volume * bullish_volume_ratio
    estimated_bearish_volume = volume * bearish_volume_ratio
    estimated_delta = volume * (2*close - high - low) / range
    estimated_delta_ratio = estimated_delta / max(volume, epsilon)
else:
    bullish_volume_ratio = bearish_volume_ratio = 0.5
    estimated_delta = estimated_delta_ratio = 0
    zero_range_bar = true
```

Names: `bar_volume`, `bar_est_bull_volume`, `bar_est_bear_volume`,
`bar_est_delta`, `bar_est_delta_ratio`, `bar_zero_range`. Labeled
"estimated" throughout — never presented as true order-flow delta.

### A2. Rolling completed-time windows

Windows: `5s 15s 30s 60s 120s 300s 900s 1800s`, computed from completed 1s
bars only (current forming bar excluded). Per window `W`: `vol_sum_<W>`,
`vol_mean_1s_<W>`, `vol_max_1s_<W>`, `est_bull_vol_sum_<W>`,
`est_bear_vol_sum_<W>`, `est_delta_sum_<W>`, `est_abs_delta_sum_<W>`,
`est_delta_ratio_<W>` (`= est_delta_sum_<W> / max(vol_sum_<W>, epsilon)`),
`est_delta_pos_sum_<W>`, `est_delta_neg_sum_<W>`, `upbar_vol_sum_<W>`
(close>open bars only), `downbar_vol_sum_<W>` (close<open only, flat bars
excluded from both), `up_down_vol_ratio_<W>`, `price_change_points_<W>`,
`price_change_atr_<W>`, `range_points_<W>`, `range_atr_<W>`,
`volume_per_point_moved_<W>`, `volume_per_atr_moved_<W>`,
`abs_delta_per_point_moved_<W>`, `abs_delta_per_atr_moved_<W>`. Windows
without enough completed history are `null` with `<W>_available = false` —
never zero-filled.

### A3. Short-vs-long pressure comparison

`est_delta_sum_15s_minus_60s_scaled`, `est_delta_sum_30s_minus_120s_scaled`,
`est_delta_sum_60s_minus_300s_scaled`, `est_delta_ratio_15s_minus_60s`,
`est_delta_ratio_30s_minus_120s`, `est_delta_ratio_60s_minus_300s`,
`vol_sum_30s_vs_300s_ratio`, `vol_sum_60s_vs_900s_ratio`. Purpose: capture
longer-window pressure persisting positive while short-window pressure
weakens/flips. No level-interaction features in this phase (deferred).

### A4. Regime-relative volume/delta

Causal, reset on regime change (prevailing 1m regime, matching the existing
atlas's `regime_start_ns` key): `regime_vol_sum`, `regime_est_delta_sum`,
`regime_est_delta_ratio`, `regime_est_abs_delta_sum`, `regime_elapsed_seconds`,
`regime_volume_per_second`, `regime_price_change_atr`, `regime_range_atr`,
`regime_volume_per_atr_moved`, `regime_abs_delta_per_atr_moved`, plus a
first-half/second-half split (`regime_first_half_est_delta_ratio`,
`regime_second_half_est_delta_ratio`, `regime_late_minus_early_delta_ratio`,
`regime_first_half_vol`, `regime_second_half_vol`,
`regime_late_vs_early_vol_ratio`) — marked unavailable, not zero, if the
regime is too young to split.

### A5. RTH/session cumulative features

`rth_elapsed_seconds`, `rth_vol_cum`, `rth_est_delta_cum`,
`rth_est_delta_ratio_cum`, `rth_abs_delta_cum`, `rth_volume_per_second`,
reset at each RTH session start, `available=false`/null pre-RTH. No
backfilling later RTH totals into earlier rows. The trailing-20-day
same-elapsed-time comparison features
(`rth_vol_cum_vs_trailing_20day_same_elapsed_median/zscore`,
`rth_delta_cum_vs_trailing_20day_same_elapsed_zscore`) are **Phase Two**:
implement only if a causal historical-profile utility already exists or is
trivial to build without new heavy machinery; otherwise document as
deferred and do not implement in this pass.

## Part B — causal price-level context features

### B1. Approved base levels

Prior completed trading day (`prior_day_open/high/low/close`, frozen for
the current trading day); overnight session (`overnight_high/low_developing`,
`overnight_high/low_final` — final only after the overnight session ends);
`rth_open` (available only once causally established); 30-minute opening
range (`opening_range_30m_high/low_developing`, `_final`, `_is_developing`,
`_is_final`, `_elapsed_seconds` — final only after the range completes);
rolling completed-1m-bar OHLC over `5m 15m 30m 60m`
(`rolling_<W>_open/high/low/close/available` — no partial windows). Do not
expand the level universe beyond this set in this pass.

### B2. Per-level distance features

Per available level: `<level>_price`, `<level>_available`,
`<level>_signed_distance_points/ticks/atr`
(`= (reference_price - level_price) / atr_at_checkpoint`, reference =
completed decision-bar close), `<level>_position` ∈
`{ABOVE, BELOW, TOUCH, UNAVAILABLE}`, touch tolerance =
`max(1 tick, configurable_touch_tolerance_ticks)`.

### B3. Aggregate level-count features

`n_levels_available/above/below/touched`, `pct_levels_above/below/touched`,
`level_balance = (n_levels_below - n_levels_above) / n_levels_available`
(positive = price above more levels), plus by-family counts
(`n_prior_day_levels_above/below`, `n_session_levels_above/below`,
`n_rolling_levels_above/below`).

### B4. Nearest-level geometry

`nearest_level_above/below_{name,price,distance_points,distance_ticks,distance_atr}`,
`nearest_space_balance_atr`, `nearest_space_total_atr`,
`nearest_upside_downside_ratio`. No artificial extreme when one side is
unavailable — null + availability flag instead.

### B5. Level density and envelope

Density bands `0.25A 0.50A 1.00A 2.00A`:
`level_density_{025a,050a,100a,200a}`,
`levels_{above,below}_within_{025a,050a,100a,200a}`,
`inverse_distance_density`. Envelope: `lowest/highest_available_level`,
`full_level_envelope_width_points/atr`, `price_position_in_full_envelope`
(not clamped), `distance_above/below_full_envelope_atr`.

### B6. Simple clustered levels

Cluster tolerance `max(2 ticks, 0.05 * atr_at_checkpoint)`; cluster price =
unweighted median of members; cluster strength = member count.
`n_level_clusters_available/above/below/touched`,
`nearest_cluster_above/below_{price,distance_atr,strength}`,
`max_cluster_strength`, `max_nearby_cluster_strength_{050a,100a}`. Must be
deterministic (stable member-to-cluster assignment given fixed input order)
— no learned weights.

### B7. Direction-normalized level features

Direction is short (`-1`) for every row in this surface (established
bullish-regime short-fade population). `levels_ahead_of_trade` = below-price
levels for short (ahead = the direction the trade is fading toward),
`levels_behind_trade` = above-price levels; `pct_levels_ahead/behind_of_trade`,
`nearest_level_ahead/behind_distance_atr`,
`nearest_cluster_ahead/behind_distance_atr`, `directional_space_balance_atr`.
Direction is a known, fixed property of this surface — never inferred from
outcome.

## Part C — feature library integration

Register every new feature in `features/registry.py` using the existing
`FeatureDefinition` dataclass — no silent additions. New families:
`ohlcv_est_delta` (Part A), `price_level_context` (Part B). Machine-readable
schema in this study's `feature_schema.csv`/`.md`:
`feature_name, family, subfamily, dtype, units, window, source,
availability_rule, normalization, directional_or_absolute, description`.
Implementation classes: `features/trackers/ohlcv_delta.py`
(`OHLCVDeltaTracker`), `features/trackers/price_levels.py`
(`PriceLevelTracker` + the trading-day-boundary helper from Scout-pass
item 4). Wire into `FeatureEngine.update_1s`/`update_1m` and `snapshot()`
following the exact pattern already used for `ArrivalVolumeTracker`/
`PullbackTracker`. Do not duplicate this production code inside the study
directory — the study directory holds only the batch-attachment script,
tests, and validation artifacts, linking to `features/`.

## Part D — attach to existing short-RTH surfaces

Attach to the existing labeled+featured rows for 2021-2026
(`short_rth_w4_retrain_entry_strength/_work/labeled_featured_{year}.parquet`,
already built and reconciled by the two prior studies) — add columns, never
change rows, labels, eligibility, or Policy A outcomes. Required checks per
year: row count unchanged, labels unchanged, candidate identity unchanged
(regime_start_ns/observation_time key), no new duplicate rows, feature join
rate, NaN/availability rates. Preserve known controls exactly: 2025 W4
crossing candidates = 650, 2026 = 222, fixed-807 overlay unchanged (these
are properties of the untouched existing surface, not recomputed here —
this task only ever adds columns via a left-join keyed on
`regime_start_ns`/`observation_time`).

## Part E — labeling/metadata scope

"Labeling" in this task means only: (1) feature schema metadata, (2) joining
new feature columns onto the already-labeled Policy A surfaces, (3)
preserving existing outcome labels unchanged. No new outcome labels unless
strictly required for feature validation (e.g., a unit-test fixture). No
model training. No deployable-PnL reporting.

## Required tests

**Volume/delta**: green full-range candle (delta = +volume), red full-range
candle (delta = −volume), mid-close candle (delta = 0), zero-range candle
(delta = 0, `zero_range_bar=true`), rolling-window completion (15s
unavailable before 15 completed 1s bars, forming bar excluded),
short-vs-long comparison (deterministic synthetic deltas), regime-relative
reset on regime change, RTH-cumulative reset on new session, timestamp
provenance (`latest_source_ts_used <= observation_ts`, always).

**Price-level**: prior-day freeze, overnight developing-vs-final, opening-
range leak prevention, rolling-window completion, above/below/touch counts,
nearest-level selection, envelope behavior, clustering determinism,
direction normalization, timestamp provenance.

## Runtime validation

Five consecutive normal trading days, covering: overnight session, RTH
open, first 30 minutes of RTH, opening-range finalization, rolling
5/15/30/60-minute availability, at least one trading-day transition.
Outputs: `validation/sample_features.parquet`, `validation/feature_validation.md`
with timestamped worked examples for estimated delta, rolling-window
update, regime reset, RTH-cumulative reset, prior-day freeze, overnight
finalization, opening-range finalization, nearest-level above/below, and a
clustered-level example.

## Audit requirements

Independent `lookahead-auditor` pass verifying: no future bars used, no
incomplete bar treated as complete, no final overnight/opening-range values
exposed before finalization, rolling windows complete and causal, ATR
normalization uses only known ATR, RTH uses the remediated fill-time
convention where relevant, unavailable values are null+flag (never
zero-filled), feature schema matches emitted columns exactly, row
counts/labels unchanged post-join, cluster output deterministic. Labels:
`CRITICAL / WARNING / NOT VERIFIED / CLEAR`. Acceptance requires 0
CRITICAL; warnings documented.

## Required artifacts

```text
studies/ohlcv_volume_delta_price_level_features/
  SPEC.md
  feature_schema.csv
  feature_schema.md
  tests/
  validation/sample_features.parquet
  validation/feature_validation.md
  results/feature_join_summary.csv
  results/feature_availability_by_year.csv
  results/feature_nan_rates.csv
  results/manifest.json
  audit/audit.md
  REPRODUCE.md
```

Production feature code lives in `features/trackers/ohlcv_delta.py`,
`features/trackers/price_levels.py`, registered in `features/registry.py`
— linked from, not duplicated in, this study directory. No `implementation/`
subfolder inside the study directory (per the "do not duplicate production
modules" constraint, all implementation is in `features/`).

## Acceptance criteria

Deterministic tests pass; runtime validation passes; audit 0 CRITICAL; row
counts and labels unchanged after join; feature schema covers every new
column; no unavailable numeric feature encoded as zero; source-timestamp
provenance recorded; feature-library integration complete (registry entries
+ `FeatureEngine` wiring); reproduction instructions written.

## Final decision labels

```text
ACCEPT_FEATURE_FOUNDATION
REVISE_AND_RETEST
REJECT_FEATURE_FOUNDATION
```

## Final report must answer

1. How many volume/delta features were added?
2. How many price-level features were added?
3. Were they added to the shared feature library/registry?
4. Did deterministic tests pass?
5. Did runtime validation pass?
6. Did the independent audit find any critical issues?
7. Did feature joining preserve all rows and labels?
8. What are the primary remaining caveats?
9. What is the next bounded study to test information content?

## Guardrails

No model training, feature selection, threshold optimization, entry/exit
changes, or economic conclusions in this study. No delta-near-level,
failed-high, or level-rejection interaction features (deferred to a later
phase). No parallel session/timestamp/RTH logic — reuse the existing
fill-time-remediated `is_rth` and the existing atlas's ATR. No V2 collector,
no microstructure/order-book data. Confirm the two open scout-pass items
(trading-day-boundary hour, live-replay-vs-vectorized-batch performance
decision) before writing `features/trackers/price_levels.py`'s overnight/
prior-day logic or committing to Part D's historical-attachment approach.

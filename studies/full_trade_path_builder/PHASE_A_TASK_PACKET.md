# Phase A Frozen Task Packet

## Objective

Produce `BULLISH_STRICT_top25_gbt_v2`, a causally collected replacement for the
provisional Bullish Fade artifact. The model predicts a bearish confirmed regime
flip within 300 seconds at established bullish RTH five-second checkpoints.

## Allowed new files

- `studies/full_trade_path_builder/**`
- A final frozen artifact directory selected by the Phase-A freeze step.

Existing strategies, models, source studies, raw data, and catalog data are
read-only dependencies.

## Required causal collection

1. Run a dedicated NautilusTrader `BacktestEngine` collector.
2. Register one-second data before one-minute data.
3. Update the central `OHLCVDeltaTracker` and `PriceLevelTracker` only from
   completed bars in event-loop order.
4. Use a Bullish model adapter with trade direction `-1`.
5. Emit exactly the ordered 25-feature vector at every causally eligible
   established bullish RTH five-second checkpoint defined below.
6. Store `max_source_ts_event_1s`, `max_source_ts_init_1s`,
   `max_source_ts_event_1m`, and `max_source_ts_init_1m`. At decision `T`, every
   included one-second bar must satisfy `ts_event < T` and `ts_init <= T`.
   Every included minute bar must satisfy `ts_init < T`; a minute completing
   exactly at `T` is not yet admissible. The one-second bar with `ts_init == T`
   and `ts_event < T` is processed before the snapshot; a one-second bar with
   `ts_event == T` is not available until after `T` and is prohibited.
7. Emit regime-flip facts separately. Do not construct labels inside the feature
   snapshot path.
8. Join NT-emitted checkpoint facts to NT-emitted flip facts after collection.
   The positive predicate is exactly
   `0 < bearish_confirm_flip_ns - checkpoint_decision_ns <= 300_000_000_000`.
   A same-timestamp flip is excluded, `T+300s` is included, and `T+300s+1ns` is
   excluded.
9. Persist `observation_end_ns`, the final timestamp through which the replay is
   known complete. A negative is observable only when `observation_end_ns >=
   T+300s` and no eligible flip occurs in `(T,T+300s]`; otherwise the row is
   right-censored. Month partitions carry unresolved rows forward into the next
   partition. Year boundaries do not censor; only the dataset boundary may.

No pandas signal detection, feature reconstruction, regime construction, or
future-conditioned checkpoint filtering is allowed.

## Frozen checkpoint population

- A regime opens only on an NT-emitted confirmed transition into direction
  `+1`. Its immutable anchor is `(regime_start_ns, flip_close,
  atr_at_regime_start)`. ATR must be finite and positive.
- Checkpoints are the exact grid `T_k = regime_start_ns + 5s*k`, for integer
  `k=1..359`. The `+1800s` endpoint is excluded. `T_k` is both
  `checkpoint_decision_ns` and `checkpoint_availability_ns`. Dispatch occurs
  only on a one-second callback with `ts_init == T_k`, after incorporating that
  completed bar (`ts_event<T_k`) and before any minute callback with
  `ts_init==T_k`. If no such callback exists, that key is omitted and recorded as
  `missing_dispatch_bar`; no timer, delayed catch-up, off-grid decision, or
  later substitution is permitted. A prior completed close must exist.
- Excursions use the prevailing bullish regime geometry and frozen regime ATR:
  `running_mfe_atr=max(0,max_high_before_T-flip_close)/atr_at_regime_start`;
  `running_mae_atr=max(0,flip_close-min_low_before_T)/atr_at_regime_start`;
  `current_pnl_atr=(last_close_before_T-flip_close)/atr_at_regime_start`.
- A new progress window is counted when bullish running MFE makes a strict new
  extreme (`> previous+1e-12`) and either no prior extreme exists or at least
  120 seconds elapsed since the most recent new-extreme timestamp. The most
  recent new-extreme timestamp advances on every strict new extreme, whether or
  not a window was counted.
- The established gate is exactly: age `>=120s`, running MFE `>=1.0 ATR`,
  progress-window count `>=2`, and
  `current_pnl_atr/running_mfe_atr >=0.5`.
- Population RTH is `[08:30:00,15:00:00)` America/Chicago, evaluated at `T`
  (not a later bar/fill), including DST transitions via timezone-aware
  conversion. There is no separate fill-time gate because this is a checkpoint
  population, not an execution population.
- At equal availability timestamp `T`, process the completed one-second bar
  (`ts_event<T`), then snapshot the checkpoint, then process the minute bar
  whose `ts_init==T`. Therefore a flip first confirmed by that minute callback
  occurs after the checkpoint at `T`; its canonical `confirm_flip_ns` is its
  availability timestamp and can label that checkpoint only when strictly
  greater than `T`. The new regime's first possible grid point is
  `confirm_flip_ns+5s`.
- The in-domain model population is the checkpoint population above with all 25
  adapter values finite. Null checkpoints remain in collection diagnostics but
  are score-suppressed and excluded from training/threshold rows.
- Deterministic tests must persist literal expected row keys
  `(regime_start_ns, direction, checkpoint_index, T)` for gap-free, gap,
  timeout, RTH-edge, and flip-tie fixtures. Exact key-set equality is required;
  count parity is insufficient.

## Frozen feature and model contract

- Feature list: exact `F3_top25_gbt_v1` ordered list and hash.
- Feature adapter direction: `-1`.
- Training: 2021–2024.
- Development/threshold reference: 2025.
- 2026: forbidden.
- Estimator and seed: exact values in `config/phase_a.yaml`.
- Positive class: `1`.
- Probability: uncalibrated `predict_proba(...)[positive_class]`.
- Calibration artifact: explicit `NONE_IDENTITY` manifest, not a fabricated
  calibration model.

## Threshold contract

Freeze model-specific 2025 in-domain thresholds at the 90th, 95th, and 97.5th
score quantiles using NumPy's `quantile(..., method="linear")` with the frozen
environment version, after rejecting non-finite scores. Membership is
`score >= threshold`; ties are all included and therefore may exceed the nominal
percentage. Scores are serialized as little-endian float64 before hashing.
Persist the reference population definition, dates, cadence, row count, score
hash, quantile method, numeric thresholds, and manifest hash. Never recompute
them in Phase B.

The fitted 2021-2024 estimator is persisted and SHA-256 hashed before any 2025
score or threshold calculation. The persisted object is reloaded for all 2025
scoring and runtime parity; refitting after hashing is prohibited. The 2025
population is threshold reference and temporal acceptance only, never training.

## Frozen 25-feature adapter

All rows use registry version `1.0`, float64 output, short trade direction `-1`,
the last one-second close strictly before `T` as reference price, and finite
positive `atr_at_checkpoint` from the latest admissible minute state with
`ts_init<T` as every model-feature ATR normalizer. The immutable
`atr_at_regime_start` is used only for established-population excursion
geometry. `allow` below is
the registry's calculation null policy; the study action for every null or
non-finite value is always `emit diagnostic + suppress score`.

| # | Feature | Source/update | Availability/warm-up | Reset | Provenance |
|---:|---|---|---|---|---|
|1|rolling_5m_low_signed_distance_atr|1m, after completed minute|5 rolling minutes|none|max_source_ts_event_1m|
|2|rth_elapsed_seconds|1s accumulated after close|RTH started|session 08:30 CT|max_source_ts_event_1s|
|3|rolling_15m_high_signed_distance_atr|1m, after completed minute|15 rolling minutes|none|max_source_ts_event_1m|
|4|rolling_60m_high_signed_distance_atr|1m, after completed minute|60 rolling minutes|none|max_source_ts_event_1m|
|5|rolling_15m_low_signed_distance_atr|1m, after completed minute|15 rolling minutes|none|max_source_ts_event_1m|
|6|rolling_30m_low_signed_distance_atr|1m, after completed minute|30 rolling minutes|none|max_source_ts_event_1m|
|7|price_change_points_60s|1s, after close|complete 60s window|none|max_source_ts_event_1s|
|8|rolling_30m_high_signed_distance_atr|1m, after completed minute|30 rolling minutes|none|max_source_ts_event_1m|
|9|range_points_1800s|1s, after close|complete 1800s window|none|max_source_ts_event_1s|
|10|opening_range_30m_low_developing_signed_distance_points|1m, after completed minute|RTH open and developing OR30|session|max_source_ts_event_1m|
|11|est_bear_vol_sum_300s|1s, after close|complete 300s window|none|max_source_ts_event_1s|
|12|full_level_envelope_width_atr|1m levels, snapshot at T|at least one available level|mixed level/session|max_source_ts_event_1m|
|13|rth_vol_cum|1s accumulated after close|RTH started|session 08:30 CT|max_source_ts_event_1s|
|14|est_delta_sum_1800s|1s, after close|complete 1800s window|none|max_source_ts_event_1s|
|15|price_change_atr_60s|1s, after close|complete 60s window|none|max_source_ts_event_1s|
|16|prior_day_close_signed_distance_atr|1m levels, snapshot at T|prior RTH close available|session|max_source_ts_event_1m|
|17|up_down_vol_ratio_1800s|1s, after close|complete 1800s window and denominator valid|none|max_source_ts_event_1s|
|18|price_change_atr_30s|1s, after close|complete 30s window|none|max_source_ts_event_1s|
|19|pct_levels_behind_trade|1m levels, direction-normalized snapshot|at least one available level|none|max_source_ts_event_1m|
|20|prior_day_low_signed_distance_points|1m levels, snapshot at T|prior RTH low available|session|max_source_ts_event_1m|
|21|opening_range_30m_low_final_signed_distance_points|1m, after completed minute|OR30 finalized at/after 09:00 CT|session|max_source_ts_event_1m|
|22|vol_max_1s_1800s|1s, after close|complete 1800s window|none|max_source_ts_event_1s|
|23|price_position_in_full_envelope|1m levels, snapshot at T|finite nonzero envelope|mixed level/session|max_source_ts_event_1m|
|24|rth_abs_delta_cum|1s accumulated after close|RTH started|session 08:30 CT|max_source_ts_event_1s|
|25|n_levels_below|1m levels, snapshot at T|level state initialized|none|max_source_ts_event_1m|

The adapter must assert this literal order and registry metadata at startup.
Rolling windows never zero-fill partial history. Regime state resets on the
confirmed flip before subsequent bars. At 08:30 CT, the callback first processes
the bar ending at 08:30 (`ts_event=08:29:59`) only into continuous rolling
state, not the new RTH accumulator; the checkpoint then snapshots, and the new
RTH reset occurs afterward. Thus an exact 08:30 checkpoint is null/suppressed
for the new session's RTH-cumulative fields; 08:30:05 may use
only admissible post-reset events strictly before it. RTH accumulation ends at
15:00 CT. Session-derived price levels follow their registry session resets.
At coincident boundaries, the admissible completed one-second update precedes
the snapshot; the session reset and equal-`ts_init` minute update follow it.

## Required tests before the representative run

- Coincident one-second/one-minute ordering.
- Mutation test injecting a one-second bar with `ts_event==T` before snapshot
  and proving it violates `max_source_ts_event_1s<T`; the admissible bar with
  `ts_init==T` and `ts_event<T` must remain included.
- Minute-boundary mutation test proving `max_source_ts_init_1m == T` fails.
- Prefix invariance.
- Five-second checkpoint cadence and no future-conditioned sampling.
- Strict source-time availability at checkpoint decisions.
- Bullish adapter exact order, direction, null policy, warm-up, and reset rules.
- Regime/RTH transition and boundary tests.
- ATR-routing fixture proving checkpoint ATR may vary while regime ATR remains
  fixed and each reaches only its specified consumer.
- Gap fixtures distinguishing exact event dispatch from missing-event omission
  and delayed-next-bar non-catch-up.
- 08:29:55, 08:30:00, 08:30:05, spring-DST, and fall-DST reset fixtures.
- Pure label arithmetic and trailing censoring.
- Label fixtures at `T`, `T+299s`, `T+300s`, `T+301s`, month/year boundary,
  dataset boundary, and no later flip.
- Model class/positive-class checks.
- Deterministic fixture reproduction.
- No 2026 path access.

## Staged execution

1. Component tests.
2. Mandatory pre-execution look-ahead audit.
3. Bounded March-2025 collector benchmark and memory/runtime estimate.
4. Review benchmark parity and coverage.
5. Bounded monthly collection for 2021–2025 with atomic resumable partitions.
6. Train and immediately persist the model.
7. Freeze adapter, ordered list, model, calibration manifest, threshold manifest,
   fixtures, metrics, hashes, model card, and exact config.
8. Run offline/runtime feature-vector and probability parity.
9. Mandatory completion audit; zero CRITICAL and zero WARNING required.

## Forbidden changes

- No use of the provisional Bullish feature columns as training truth.
- No reuse of `searchsorted(..., side="right") - 1` attachment logic.
- No 2026 reads.
- No model-family or hyperparameter search.
- No random train/test split.
- No policy, stop, target, or PnL labels.
- No overwrite of an existing frozen artifact.

## Phase-A acceptance

- NT-only feature and signal collection.
- Zero feature-source timestamp violations.
- Exact ordered-vector parity between collector, frozen adapter, and runtime.
- Exact probability parity.
- Pure label/censoring parity.
- Frozen 2025 threshold manifest including Top-10, Top-5, and Top-2.5.
- Reproducible monthly hashes and resume protection.
- Final audit passes with zero findings.

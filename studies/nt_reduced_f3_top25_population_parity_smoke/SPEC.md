# NT Event-Driven Reduced-Model Population-Parity Smoke Study

## Status

**SPEC frozen, not yet implemented.** Planning done via direct verification (see
"Planning note" below) rather than a completed `repo-scout` pass — recorded honestly, not
concealed. Pre-execution `lookahead-auditor` pass required before the March run.

## Planning note (process deviation, disclosed)

Per `.claude/AGENT_WORKFLOW.md` Phase 0, `repo-scout` was invoked to trace the established-regime
filter's exact live-computable definition. It hit its `maxTurns` limit (12) without producing a
final report. Rather than blindly re-invoke it, the main session traced the remaining facts
directly (`Grep`/`Read` against `CODEX_5_X_run_established_fade.py`, `build_weakness_atlas.py`,
`entry_surface.py`, `features/trackers/{ohlcv_delta,price_levels}.py`, the prior POC study's
`strategy.py`/`trade_state.py`/`reconcile.py`/`common.py`) and verified every fact below against
source directly. `contract-checker` was not separately invoked given the scope of direct
verification already performed; the completion-gate audit is the independent check.

## Primary decision

Whether `F3_top25_gbt_v1` can be scored causally inside a NautilusTrader `Strategy` and reproduce
its expected offline candidate/score/trigger/trade population for March 2025.

## Verified facts

### Frozen model inputs (blocking gate, already checked and PASSING)

- Model artifact `studies/runtime_constrained_f3_feature_reduction/artifacts/models/F3_top25_gbt_v1/model.joblib`
  SHA-256 `24bf6bece8319cb951bc82f31ea97ac7d3a0a9a200d598d986965143dec7e944` — **matches**, re-hashed
  directly this session.
  Feature-list SHA-256 `8bcfeb74ab3b5453635ad9895fa9d15fd65866044f23fa0415bfc796e5fd6299` — **matches**.
  25 features, exact order confirmed identical to the brief's list.
  `model.classes_ == [0, 1]`, `positive_class_index=1`, `score_method="predict_proba(...)[:, 1]"`,
  sklearn `1.7.2` / numpy `2.3.3` match manifest and current environment exactly.
  All 25 features: `in_registry=True`, `live_tracker_exists=True`, `timing_status="verified"`
  (none of the 17 disclosed `TIMING_UNVERIFIED` features are in this candidate) — 12 from
  `ohlcv_est_delta` family, 13 from `price_level_context` family. No F0 features.

### Feature computation: reuse the two existing verified trackers, no new tracker code

All 25 features are produced by `OHLCVDeltaTracker.calculate(atr)` (12 features) and
`PriceLevelTracker.calculate(observation_ts, reference_price, atr, direction)` (13 features) —
confirmed by direct read of `features/trackers/ohlcv_delta.py` / `price_levels.py`. Both trackers
compute their FULL internal feature set on every `calculate()` call (there is no "compute only
these N keys" mode) — `ReducedFeatureEngine` calls both trackers exactly as
`ohlcv_volume_delta_price_level_features/attach_features.py` already does (verified reuse of an
audited call pattern, not new logic) and slices out only the 25 needed keys from the returned
dicts. "Do not implement the unused 670 features" (brief) is satisfied by instantiating no OTHER
tracker/feature-family infrastructure (no `MedianCenterTracker`, no F0) — not by avoiding the two
trackers' own internal computation, which is not selectively avoidable.

Tracker wiring (verified from `attach_features.py`, reused verbatim):
- `OHLCVDeltaTracker.update(ts_event, open, high, low, close, volume)` — every completed 1s bar,
  unconditional.
- `OHLCVDeltaTracker.accumulate_regime_rth(ts_event, high, low, volume, est_delta)` — buffered per
  forming-minute, replayed once that minute's regime/RTH context resolves at 1m close (matches
  `attach_features.py:210-250`, itself matching the FeatureEngine buffer-and-replay fix CLAUDE.md
  invariant 4 requires).
- `OHLCVDeltaTracker.reset_regime(ts_event, anchor_price)` on 1m-confirmed regime transition;
  `reset_rth`/`end_rth` on RTH boundary.
- `PriceLevelTracker.update_1m(ts_event, open, high, low, close, is_rth)` — every completed 1m bar.
- Both `.calculate()` calls happen at candidate-declaration time (5s grid), using `atr =
  RegimeEngine.atr` (see below) and `direction = entry_direction = -1` (this population is
  short-only, confirmed: `entry_surface.py:69-71` keeps only `direction==1` prevailing regimes,
  `entry_direction = -direction = -1`, matching `prepared_2025.parquet`'s `entry_direction` column
  being 100% `-1`, confirmed directly in the prior `runtime_constrained_f3_feature_reduction`
  study this session).

### Candidate declaration: the established-regime filter, now fully causal and live-computable

Confirmed by direct read of `CODEX_5_X_run_established_fade.py:167-179` (`progress_window_counts`,
already causal/incremental) and `regime_sequence_chop_context/build_weakness_atlas.py:10-124`
(`compute_running_excursions`, checkpoint-grid construction):

```text
On each 1m-confirmed regime flip to direction == +1 (established-bullish, per entry_surface.py's
"prevailing_direction == 1" gate -- entries are SHORT, entry_direction = -1, against this regime):
  flip_ts = bar.ts_init (1m close), flip_close = bar.close, atr_val = RegimeEngine.atr at that instant.
  Reset: highest_high_since_flip = -inf, lowest_low_since_flip = +inf,
         mfe_progress_previous_extreme = -inf, mfe_progress_last_extreme_ts = None, mfe_progress_count = 0.

On every 1s bar while this regime is active:
  highest_high_since_flip = max(highest_high_since_flip, bar.high)
  lowest_low_since_flip = min(lowest_low_since_flip, bar.low)

Candidate grid (per build_weakness_atlas.py:44,71-80): every 5s from flip_ts+5s through
  min(flip_ts + 1800s, next_opposing_flip_ts) -- exclusive of the opposing flip itself.

At each grid timestamp T (a candidate):
  regime_age_s = (T - flip_ts) / 1e9
  current_mfe = max(0, flip_close - lowest_low_since_flip) / atr_val   [direction=-1 branch of
                 compute_running_excursions -- prevailing regime is +1, but excursion is measured
                 for the SHORT entry_direction, matching entry_surface.py's own
                 `favorable = anchor - lows` for its short-fade population]
  current_mae = max(0, highest_high_since_flip - flip_close) / atr_val
  current_pnl = -1 * (price_at_T - flip_close) / atr_val   [entry_direction=-1, instantaneous,
                 NOT running-max; price_at_T = close of the 1s bar at/immediately before T]
  progress_window_counts: increments mfe_progress_count when current_mfe sets a new extreme
                 (> mfe_progress_previous_extreme + 1e-12) AND either no prior extreme was counted
                 or >= 120s have passed since the last counted extreme's timestamp (verbatim port
                 of CODEX_5_X_run_established_fade.py:167-179's loop, applied incrementally).
  retained_mfe_ratio = current_pnl / current_mfe if current_mfe > 0 else NaN

  established = (regime_age_s >= 120.0 and current_mfe >= 1.0
                 and mfe_progress_count >= 2 and retained_mfe_ratio >= 0.5)
                 [exact filter values from CODEX_5_X_established_fade_policy.json:12-16,
                 confirmed "unchanged from prior established-regime study" and reused by
                 entry_surface.py -- same population this study's frozen model was trained on]

  If established: apply entry_surface.py's remaining two gates --
    RTH: is_rth(fill_ts) where fill_ts is the next available 1s bar open at/after T (RTH = 08:30-
         15:00 America/Chicago, entry_surface.py:114-125 -- session classified on FILL time, not
         decision time; a decision/fill RTH divergence is logged, not silently resolved).
    valid_fill: fill_ts < regime_end (the opposing flip has not already occurred by fill time).
  A candidate that clears established+RTH+valid_fill is an ELIGIBLE CANDIDATE — this is the
  population `CandidateTracker` declares, matching `prepared_2025.parquet`'s row population.
  A candidate failing established, RTH, or valid_fill is logged as suppressed with that exact
  reason (entry_surface.py's own attrition-stage vocabulary: bullish_regime/established/rth/
  valid_fill), not silently dropped -- this reproduces entry_surface.py's funnel live, not just
  its final surface.
```

`compute_running_excursions`'s `mfe_points`/`mae_points` branch used above is confirmed against
`entry_surface.py`'s OWN short-fade population convention (`favorable = anchor - lows`,
`entry_surface.py:86`), not blindly copied from `build_weakness_atlas.py`'s generic
direction-parameterized version — both are checked to agree for `entry_direction=-1`.

### Execution policy: reuse the prior NT POC's proven, audited architecture verbatim

Per the brief ("same execution policy as the existing NT POC") and confirmed by direct read of
`nt_pure_flip_trigger_poc_and_mirrored_long_model/phase2/{strategy.py,trade_state.py}`:
- `FlipTradeState` (fixed `entry_px ± 1.25×ATR` stop, placed once, never swapped; no confirmation
  timeout; opposing-flip exit once the thesis regime has been confirmed) reused verbatim — this
  new study's thesis regime is the SAME as the POC's (bearish flip / short thesis), so no
  adaptation needed beyond wiring it to live-declared candidates instead of a frozen schedule.
- Genuine resting `stop_market` order (GTC, `reduce_only`), placed once at entry fill — the POC's
  own pre-execution audit found and fixed a CRITICAL bug (a manually-polled FOK market order that
  filled at bar close instead of trigger price); this study reuses the FIXED pattern directly,
  not the original buggy one.
- `RegimeEngine` (`fable5_pre_flip_d10_reversal_entry/strategy.py:64-101`) reused verbatim for
  live regime state AND live ATR (`self.atr`, Wilder 14-period on 1m H/L/C) — this ALSO supplies
  `atr_val` for the established-gate computation above, so no second ATR indicator is needed.
- `add_data(bars_1s)` then `add_data(bars_1m)` call order reused verbatim (confirmed matches
  `add_bars_causal_order()`'s "1s before 1m" requirement from `nt_live_scoring_infra_prereqs`).
- NT catalog/instrument/venue config reused verbatim: `data/catalog/NQ_v0_2020_2026`,
  `NQ.XCME` via `fable5_pre_flip_d10_reversal_entry.run_nt.create_instrument()`, `Venue("XCME")`
  NETTING/MARGIN, `bar_execution=True, bar_adaptive_high_low_ordering=True`.
- Costs/multiplier: `NQ_MULT=20.0`, `cost_rt=10.0` (identical to POC).
- One-trade-per-regime / position-suppression logic reused verbatim from `strategy.py`'s
  `_try_enter` guard (`self._trade is not None or ...`).

### NEW piece this study builds (does not exist anywhere in the repo yet)

Per the prior POC's own SPEC finding 1 (verified, not re-derived): **no NT strategy in this repo
has ever scored an ML model live in `on_bar`**, and no NT strategy has ever live-computed the
established-regime candidate funnel (every precedent dispatches from a frozen schedule). This
study builds both, made tractable only because the reduced model needs 25 features (not 695) and
only 2 trackers (not a from-scratch `FeatureEngine` integration).

### Threshold policy

Frozen from the ALREADY-COMPLETED full-2025 offline `F3_top25_gbt_v1` scores
(`studies/runtime_constrained_f3_feature_reduction/artifacts/models/F3_top25_gbt_v1/metrics_2025.json`
does not itself store per-row scores -- Phase 1 below computes and freezes `top_5pct`/`top_2_5pct`
quantiles from a fresh, hash-verified full-2025 scoring pass using the exact persisted model, and
`config/frozen_thresholds.json` records the source score-column hash). Per the brief: do not tune
on March; use the exact same two frozen numeric thresholds in both the offline March reference and
the live NT March run.

### Month selection

March 2025 (per the brief, matching the prior POC's precedent). Verified requirements before
freezing:
- `data/raw/NQ_v0_1s_2025.parquet` (12,083,801 rows for the full year, confirmed this session) and
  the NT catalog `data/catalog/NQ_v0_2020_2026` both cover March 2025 with full-year lead-in.
- Lead-in: load the FULL 2025 year (Jan 1 - Dec 31), matching the POC's own convention
  (`LOAD_START = 2025-01-01`), for both `RegimeEngine` warmup (14-bar ATR + EMA3/EMA9) and the two
  feature trackers' warmup (`OHLCVDeltaTracker` needs up to 1800s of 1s history;
  `PriceLevelTracker` needs prior-day OHLC, which requires at least one full prior trading day, and
  up to 60 minutes of rolling 1m history) -- trivially satisfied by a full-year load starting
  January. Score/log/report ONLY March 2025 checkpoints and trades, per the brief.

## Files this study may create or modify

Create only, under `studies/nt_reduced_f3_top25_population_parity_smoke/`: `SPEC.md` (this file),
`REPRODUCE.md`, `STUDY_REPORT.md`, `config/*.json`, `implementation/*.py`, `tests/*.py`,
`audit/audit.md`, `results/*.{csv,json,parquet}`, `_work/**`. No file outside this directory is
modified. `features/trackers/**`, `runtime_constrained_f3_feature_reduction/**`,
`nt_pure_flip_trigger_poc_and_mirrored_long_model/**`, and every other prior study are read-only
inputs, imported (dynamic `importlib` pattern, this repo's established convention for same-named
modules) not copy-pasted where feasible.

## Architecture (per brief's required component split)

- `candidate_tracker.py` — `CandidateTracker`: established-gate + RTH + valid-fill funnel above,
  stable candidate key `(regime_start_ns=flip_ts, regime_direction=+1, checkpoint_index,
  observation_time_ns=T)`. Pure-Python, NT-independent (hand-tested before wiring in, per this
  project's standing pre-execution-test discipline).
- `reduced_feature_engine.py` — wraps `OHLCVDeltaTracker`+`PriceLevelTracker`, emits the exact
  ordered 25-feature vector + a null mask.
- `model_runtime.py` — loads `F3_top25_gbt_v1`, validates hash/feature-order/classes at
  construction, rejects missing/extra/misordered columns, exposes `score(feature_vector) -> float`.
- `threshold_policy.py` — applies frozen R5/R2.5 thresholds only.
- `parity_logger.py` — logs every candidate (not just triggered ones) with full feature/score/
  suppression detail.
- `trade_state.py` — reused from the POC verbatim (see above), not reimplemented.
- `strategy.py` — NT `Strategy` wiring all of the above; must not read stored offline scores,
  trigger flags, a precomputed eligible-candidate schedule, or future information (per brief).
- `offline_reference.py` — Phase 1's fresh offline reference generator.
- `run_nt.py` / `reconcile.py` — runner and parity reconciliation, adapted from the POC's proven
  pattern (`regime_transition_parity`/`trigger_condition_parity`/`atr_and_score_parity` become,
  here, genuine independent re-derivations rather than construction-tautological, since this study
  DOES rescore live).

## Stable candidate key

`(regime_start_ns, regime_direction, checkpoint_index, observation_time_ns)` where
`regime_start_ns = flip_ts` (the established-bullish regime's own start, matching
`prepared_2025.parquet`'s `regime_start_ns` convention directly -- confirmed same field name/
semantics), `regime_direction = +1` always in this population, `checkpoint_index` = position on
the regime's own 5s grid (0-indexed from `flip_ts+5s`), `observation_time_ns` = the grid
timestamp T. This exact tuple is emitted by both the offline reference and the live NT strategy,
enabling exact-match reconciliation without relying on row order.

## Phases 1-8

Implemented per the brief's exact phase structure (offline reference generation; live 25-feature
scoring strategy; causal/synthetic tests; bounded smoke ladder — synthetic, 1 day, 1 week, full
March; candidate-population parity; feature/score parity; trigger/trade parity) — no deviation
from the brief's required artifacts, gates, or stop conditions. Full artifact list, acceptance
gates, and final decision vocabulary are adopted verbatim from the brief and are the binding
contract for this study; not restated in full here to avoid drift between two copies of the same
rules. `STUDY_REPORT.md` will restate the 17-point required report structure with actual findings.

## Guardrails carried forward

Do not use 2026. Do not run MBP-1. Do not test the long model. Do not change label, checkpoint
construction, trigger policy, stop geometry, exit policy, costs, or fill assumptions. Do not
expand beyond March 2025 without a separate user decision after this report is reviewed. Mandatory
`lookahead-auditor` pass before the full March run (pre-execution) and after (completion-gate), 0
CRITICAL required for both.

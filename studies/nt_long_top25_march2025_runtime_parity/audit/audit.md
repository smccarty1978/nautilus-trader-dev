# Look-Ahead & Timestamp Audit

**Date:** 2026-07-21
**Scope:** `studies/nt_long_top25_march2025_runtime_parity/implementation/{common.py, long_feature_engine.py, strategy.py, candidate_tracker_long.py, run_nt.py, reconcile.py, build_offline_reference.py, model_runtime_long.py}`; `SPEC.md`; `STUDY_REPORT.md`; `tests/test_harness_invariants.py`; upstream reference `studies/long_rth_mirrored_surface_top100_training/implementation/attach_features_long.py`; `features/trackers/median_center.py`; results artifacts (`run_manifest_layerA_v2.json`, `reconciliation_layerA_v2.json`, `population_waterfall_live_layerA_v2.csv`, `population_waterfall_offline.csv`).
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 0
- Warning: 2
- Note: 3

## The central claim (minute-bucket `S >= m` chain): VERIFIED, not refuted

I re-derived this independently against the actual code, not the SPEC's prose, across every branch requested:

- **No-gap case:** `_finalize_minute()` for the bucket closing at `m` only ever executes inside `update_1s(ts_trigger, ...)` where `ts_trigger` is the first bar carrying a *different* `minute_bucket_key`, and by construction of that monotonic key function `ts_trigger > m` always (minimum `ts_trigger = m + 1s`). The snap timestamp read by a checkpoint (`self._last_1s_ts`) becomes `ts_trigger` only starting at the *next* tick, i.e. one full bar after `_finalize_minute` returned. So `S = ts_trigger >= m + 1s`, strictly stronger than the claimed `S >= m`. Confirmed in `long_feature_engine.py:100-116`.
- **Gaps in the 1s stream:** finalize is triggered lazily by "next bar with a different key," regardless of how large the gap is, so `ts_trigger` only ever moves *later*, never earlier. `S >= m` still holds; the only effect of a gap is added staleness (see Note 3), never a leak.
- **First bucket after warmup start:** `self._minute_key is None` bypasses `_finalize_minute()` entirely on the very first bar (`long_feature_engine.py:101-104`), exactly mirroring the offline `if current_minute is None:` branch (`attach_features_long.py:140-143`). The partial first bucket is folded in only when the *second* bucket begins — same in both pipelines, and it happens in early February, weeks before any March candidate exists.
- **Missing first second of a minute:** `m_close_ts` is derived purely from the bucket key (`long_feature_engine.py:122`), never from a bar's own timestamp, so a missing leading second delays the rollover without corrupting `S >= m`. Identical in offline (`attach_features_long.py:145`).
- **Session boundaries:** RTH/regime resets are applied inside the same lazily-triggered `_finalize_minute()` call, so they inherit the same `S >= m` guarantee; no separate code path exists for session edges.
- **The one scenario that looked like a counter-example and wasn't:** I initially suspected a checkpoint whose observation `T` coincides exactly with the bucket-rollover trigger bar could see stale (pre-finalize) state. Working through the actual call order: a checkpoint's *snap* is always `ts_prev` (the tick **before** the current one), and by the time the current tick runs, `ts_prev`'s own `_on_1s` call — including any `_finalize_minute()` it triggered — has already returned (NT's event loop is single-threaded/synchronous). This exactly mirrors the offline loop's own ordering (`ohlcv_tracker.update` → maybe-finalize → `hits = obs_lookup.get(bar_ts)`, all in the same iteration, `attach_features_long.py:137-168`). No divergence found.

**Verdict: the offline replay's minute-bucket quirk, and the live code's reproduction of it, is not a look-ahead in any branch I could construct.** The claim survives adversarial review.

## Checkpoint-ordering, center-ATR, and convention-separation checks (items 1-5 from the task)

1. **Checkpoint emission before fold-in (`strategy.py:131-172`, `candidate_tracker_long.py:175-208`).** Confirmed by direct trace and by `test_checkpoint_uses_previous_bar_close_not_its_own` (`tests/test_harness_invariants.py:65-84`), which is a real behavioral test, not a tautology (it feeds a bar that "plunges" and asserts the checkpoint born on that same bar sees `running_mfe_atr == 0.0`). `_check_stop` (management) runs before the tracker call but mutates only `self._open`/`self.trades`, never a feature tracker — no interaction with causality. **PASS.**
2. **`_center_atr_at_snap` (`strategy.py:100-102, 172`).** Set at the *end* of processing bar `ts_prev`, read by checkpoints fired at the *start* of the next tick, before it is overwritten for the current bar. Given the pre-existing invariant `ts_prev < T <= ts`, the recorded ATR can only ever reflect a 1m bar with `close_ts <= ts_prev < T` — never one closing at or after the observation. **PASS.**
3. **Two conventions kept separate.** `self._regime_dir` (immediate, `close_ts <= T`, updated in `_on_1m`) feeds `MedianCenterTracker.update_1s`/`calculate` **directly**, matching the median-center offline reproduction proven exact in SPEC.md §2-3 and confirmed by reading `features/trackers/median_center.py:189-193`, which detects a regime transition purely by comparing the passed `current_regime` int against its own last value — no bucket logic at all. The deferred `_pending_regime_starts` queue (`strategy.py:198`, `long_feature_engine.py:73-78, 124-127`) touches **only** `OHLCVDeltaTracker.reset_regime`, matching `attach_features_long.py`'s `reg_idx`/`regime_starts` bucket-rollover logic — a *different, separate* upstream file from the one that builds median centers. No conflation found in either direction.
4. **NT delivery-order dependency (`run_nt.py:58-64`).** Documented, not silent (`strategy.py:8-15`, `SPEC.md:205-210`), but see Note 1 below — the guarantee itself is asserted, not directly regression-tested inside a running `BacktestEngine`.
5. **Deferred regime reset via `declare_regime_start` (`long_feature_engine.py:73-78, 124-127`).** Reproduces the offline `reg_idx` advancement (`attach_features_long.py:146-148`) bar-for-bar, including the anchor price (`self._m_open`, captured before being overwritten by the new bucket). No leakage of future regime state found — the deferral is applied at the identical shifted boundary in both pipelines by construction.

## Warnings

### [Population reporting] `strategy.py:210-226` — waterfall counters not gated to the emit window

`self.waterfall[...]` is incremented unconditionally for every candidate the tracker emits (line 212 onward), and only the per-row export (`self.candidates.append(row)`, the last line of `_on_candidate`) is gated by `in_window`. Because bars are loaded from `WARMUP_START_UTC` (2025-02-01) but the emit window is March only, `population_waterfall_live_layerA_v2.csv` reports `eligible=28,894` — nearly double the correctly-gated `n_eligible_in_window=15,576` recorded in the same run's manifest, and far from offline's `15,234`. This file sits directly beside `population_waterfall_offline.csv` in `results/` and is exactly the artifact SPEC.md names for Phase 1 evidence; a naive side-by-side read would wrongly conclude population parity is catastrophically broken (~90% over), when the actual (correctly windowed) gap is 2.25%. **Not a look-ahead** — a Feb-warmup/March-window reporting-scope defect. The real Phase 1 reconciliation in `reconcile.py` is unaffected (it reads the window-gated parquet ledger, not the waterfall dict). Fix: gate the waterfall increments by `in_window` too, or clearly relabel the CSV as "cumulative since warmup start."

### [H4/E4, dormant] `strategy.py:307-328` — fill/exit price is the frozen snap price / exact stop level, not an NT-realized fill

`_enter()` sets `fill_px = float(self._last_1s_close)` (the snap-bar close used for the feature vector, matching the frozen model's own convention — correct for *scoring*, but not necessarily what NT's market order actually fills at). `_check_stop()` closes trades at the exact `stop_px` level rather than the triggering bar's low or any NT-reported fill price. Both paths are currently **inert**: every run inspected uses `trigger_threshold=-1.0` (Layer A, threshold-free; `n_triggers=0`, `n_trades=0` in every manifest read). No reconciliation between the strategy's internal `self.trades` ledger and NT's own position/fill events exists yet. Flagging now, per the explicit instruction to audit `strategy.py` fully, so it is caught before Layer B (Phases 4-5, order/fill/trade parity) is exercised — this is exactly the H4 checklist item ("fill price is next-bar open / actual fill, not trigger price").

## Notes

### [Note 1] `run_nt.py:58-64` — 1s-before-1m tie-break is a documented but externally-fragile dependency

Per prior project memory (`nt_live_scoring_infra_prereqs_ready_reduced_scope.md`), `add_data()`'s finer-timeframe-first ordering at equal `ts_init` is "a calling convention, not an NT guarantee." The regime-mapping convention (`close_ts <= T`) depends on this holding for the *last* 1s bar of a minute versus the coincident 1m bar (both `ts_init == T`). `test_regime_engine_matches_offline_reproduction` (`test_harness_invariants.py:212-231`) verifies the resulting *regime series* matches offline over two real days, which is a strong indirect check, but no test directly asserts bar-receipt order inside a live `BacktestEngine`. Given how much of this study's causal argument rests on it, a direct order-of-receipt assertion (log `on_bar` call order for a few known coincident timestamps) would close the residual risk cheaply.

### [Note 2] `candidate_tracker_long.py:162-173, 183` — checkpoints exactly at a regime-flip instant are silently dropped, not mis-evaluated

`on_regime_flip` closes any `_active` candidate and clears `self._active` to `None` *before* the coincident 1s bar's `on_1s_bar` runs. If that candidate had a checkpoint due at the same instant, `on_1s_bar` returns immediately (`active is None`) without emitting it — the checkpoint is dropped, never evaluated against the wrong (post-flip) regime. This is a completeness/undercount edge case, not a causality violation (no future data ever reaches an emitted row). It is a plausible small contributor to the still-"not yet attributed" 99.32% (not 100%) population match noted in `STUDY_REPORT.md`.

### [Note 3] Gap-induced staleness is symmetric between live and offline, not a live-only defect

Both pipelines finalize a minute bucket lazily, on the next bar carrying a different bucket key, regardless of gap size. A multi-second gap in the 1s stream causes every 5s-grid checkpoint queued inside that gap to be evaluated against identically stale snap price/ATR/MFE state in *both* live and offline. Not a look-ahead, and not new this session, but worth recording as a candidate explanation for some of the `>30s` / `no counterpart` symmetric-difference rows STUDY_REPORT.md flags as unattributed.

## Clean checks

- A1-A5 — `ts_init`/`ts_event` usage, `ts_init_delta` semantics (1s bars need none; 1m regime read is via NT's own `ts_init`, not a manual shift), and the `close_ts <= t` vs strict-snap conventions are correctly separated (see items 1-5 above).
- B1-B7, B9, B10 — no `center=True`, no `.shift(-N)`, no `bfill` in the feature path; `MedianCenterTracker`'s rolling medians/slopes are causal deques; window units and warmup are explicit (`MARCH-warmup from 2025-02-01`).
- C1-C4 — out of scope (no label construction in this study; frozen model only).
- D1-D4 — `model_runtime_long.py` cross-validates the joblib pipeline against the explicit coefficient/intercept path on every score, with documented and bounded CSV round-trip tolerances (`model_runtime_long.py:56-87`); `test_explicit_formula_reproduces_joblib_on_real_rows` exercises this on 200 real rows.
- E1, E2, E5 — bar-type strings match subscriptions (`strategy.py:119-122`); warmup (Feb-01) precedes candidate emission (March-gated).
- F1-F4 — session rules are explicit America/Chicago conversions (`minute_of_day_chicago`), with two deliberately-separate RTH definitions (08:30-15:00 features vs 08:30-15:15 decisions) both covered by `test_feature_path_rth_window_is_the_offline_one_and_differs_from_decisions`.
- G3, G4 — minute resampling uses the (deliberately non-obvious but measured and tested) offline-matching `label`/`closed` semantics; documented and behaviorally tested (`test_engine_finalizes_the_minute_one_bar_late_and_with_shifted_membership`).
- H1, H3 — established-regime/MFE/MAE gate uses bar high/low (`candidate_tracker_long.py:77-78`), not close; re-entry/one-trade-per-regime logic (`strategy.py:291, 301`) mirrors the tracker's own regime-close semantics.

---

*Audit complete. Findings reflect read-only static analysis. 0 CRITICAL findings against the core causal claim under attack; 2 WARNING items are reporting/dormant-code issues, not look-ahead.*

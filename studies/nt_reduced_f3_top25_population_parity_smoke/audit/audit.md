# Look-Ahead & Timestamp Audit

**Date:** 2026-07-20
**Scope:** `studies/nt_reduced_f3_top25_population_parity_smoke/` — `SPEC.md`; `implementation/{common,candidate_tracker,reduced_feature_engine,model_runtime,threshold_policy,parity_logger,strategy,run_nt,offline_reference,build_thresholds,reconcile}.py`; `tests/{test_candidate_tracker,test_candidate_tracker_real_data,test_reduced_feature_engine_real_data,test_model_runtime,test_parity_logger_and_guardrails}.py`. Cross-checked against `studies/ohlcv_volume_delta_price_level_features/attach_features.py`, `studies/short_rth_entry_surface_backfill/entry_surface.py`, `studies/nt_live_scoring_infra_prereqs/tests/test_coincident_bar_ordering.py`, `studies/nt_pure_flip_trigger_poc_and_mirrored_long_model/phase2/{strategy.py,trade_state.py}`, `features/trackers/price_levels.py`.
**Auditor:** lookahead-auditor v1
**Trigger:** Mandatory pre-execution gate per `SPEC.md`'s "Mandatory `lookahead-auditor` pass before the full March run (pre-execution)."

## PROCESS DEVIATION — READ FIRST

`SPEC.md` (this study's own frozen contract) states: *"Mandatory `lookahead-auditor` pass before the full March run (pre-execution) and after (completion-gate), 0 CRITICAL required for both."* The main session started the full March 2025 `BacktestEngine` run **before** invoking this audit. That is a direct violation of the study's own gate. The run cannot be un-started, but per the findings below (3 independent CRITICAL code defects), **its output must not be treated as a valid population-parity result** regardless of what it shows. Do not report its numbers as the study's answer; fix the CRITICAL items, rerun, and pass a completion-gate audit before drawing any conclusion.

## Summary

- Critical: 4
- Warning: 3
- Note: 2

## Critical findings

### [PROCESS] Pre-execution audit gate bypassed before an irreversible ~100-minute run

`SPEC.md` line 241 mandates this audit runs before the full March run; it did not. Combined with the 3 code-level CRITICAL findings below, the in-flight/completed run's results are not trustworthy as evidence for the study's primary decision, no matter how they turn out. This is a compliance failure independent of whether the code bugs happen to be benign in this particular data window.

### [D1 — train/serve skew] `strategy.py:284-285` (via `:195`) — candidate feature snapshot uses a stale, one-bar-old `reference_price`

`_on_candidate` computes:
```python
atr = self._engine.atr
price_now = self._prev_close
vec, null_mask, any_null = self._feature_engine.ordered_vector(obs_ts, price_now, atr)
```
`_on_candidate` is invoked **synchronously** from `CandidateTracker.on_1s_bar` → `_emit` → `self._on_candidate(...)`, which is itself called from inside `strategy.py`'s `_on_1s` (line 193) **before** line 195 (`self._prev_close = c`) executes. At the moment `_on_candidate` runs, `self._prev_close` still holds the close of the *previous* 1-second bar, not the close of the bar that just triggered this candidate (`c`, the current bar's own close).

This directly contradicts the audited reference implementation this study is supposed to replicate. `attach_features.py:259-260`:
```python
f_price = price_tracker.calculate(bar_ts, closes[i], atr, direction=-1)
```
uses `closes[i]` — the **current** bar's own close (`bar_ts == i == T`, the observation instant) — not the prior bar's close. `features/trackers/price_levels.py`'s `calculate(observation_ts, reference_price, atr, direction)` feeds `reference_price` into 13 distance/position-to-level features (`nearest_level_*_distance_*`, `n_*_levels_above/below`, cluster/density features, etc.) — all 13 of these model inputs are therefore computed against the *wrong* bar's price in every live candidate, systematically, for the entire study population (this is not an edge case — it fires on every single `_on_candidate` call).

**Not caught by any existing test**: `test_feature_engine_exact_match_on_real_march_regime` (the test claimed to show "0.0 abs diff on all 25 features") calls `engine.ordered_vector(bar_ts, closes[i], atr)` directly — i.e., it passes the **correct** current-bar close itself, bypassing `strategy.py`'s `_on_candidate` code path entirely. The "exact match" claim is real for `ReducedFeatureEngine` in isolation, but it does not validate `strategy.py`'s own price-selection logic, which is where the bug lives.

Impact: this is exactly the class of defect `reconcile.py`'s `feature_and_score_parity` (tolerance `1e-6`) is designed to catch — and very likely will, once the already-launched run completes, at the cost of the ~100 minutes already spent. Fix and rerun before trusting any parity number from this pass.

### [G2/A4 — silent gap corruption] `strategy.py:198-241` — the "no preceding 1s bars" guard in `_on_1m` cannot fire after the very first minute, so a genuine mid-run 1s/1m coverage gap silently corrupts `PriceLevelTracker`

```python
def _on_1m(self, bar: Bar):
    ts = int(bar.ts_init)
    if self._minute_o is None:
        self.log.warning(f"1m bar at {ts} with no preceding 1s bars this session -- skipped")
        return
    ...
```
`self._minute_o` is set to `None` exactly once, in `__init__` (line 105), and is **never reset to `None` anywhere else** in the file — it is only ever reassigned real float values (lines 163, 176). Consequently this guard is a true one-shot: it can only possibly fire on the very first `_on_1m` call of the loaded range. The comment claims this "should not happen" except "at/near the very start of the loaded catalog range" — but the code gives it no way to detect a *later* recurrence at all, contradicting its own stated safety rationale.

If any minute in the Jan 1 – Dec 31 2025 load range has a 1m bar with no matching 1s bars (plausible: this repo's own memory records `NQ catalog bars ≠ raw tick file on roll days` and a previously-fixed `closed='right'` 1m-resample look-ahead bug, both evidence that 1s/1m catalog coverage has had real discrepancies before), `_on_1m` will proceed past the guard using **stale** `self._minute_o/_minute_h/_minute_l` (left over from whatever minute last had 1s data) and feed them into `self._feature_engine.update_1m(...)` for a minute they do not belong to — with **no log line at all** (the only `log.warning` call is on the now-effectively-dead `None` branch). This corrupts `PriceLevelTracker`'s rolling 60-minute OHLC / prior-day-close state for an unknown duration after the gap, silently, for however long that stale state keeps influencing later features. `RegimeEngine.update()` and flip detection are unaffected (they read `bar.high/low/close` directly, not the buffered minute state), so this does not cause a missed flip — it corrupts a subset of the 13 `PriceLevelTracker` features instead.

### [H4 — offline sim credits trigger price instead of realistic fill] `offline_reference.py:149-152, 166` — stop-exit branch of `build_trades()` uses the exact stop level, not a next-bar-open fill

```python
if st.stop_would_touch(h, l):
    exit_reason = st.on_stop_touch()
    exit_px = st.stop_px          # <-- exact trigger level
    exit_ts = bar_ts
    break
...
gross = (exit_px - entry_px) * (-1) * C.NQ_MULT
```
`stop_would_touch` correctly uses bar `high`/`low` (H1 satisfied) and the loop iterates raw 1s bars (H2 satisfied), but the fill price on a stop touch is credited at `st.stop_px` — the exact trigger price — rather than the next bar's realistic fill. This is precisely the documented anti-pattern this repo's own memory (`feedback_offline_sim_use_ohlc_for_triggers.md`, `be_simulation_path_checkpoint_inflation.md`) has previously found to inflate offline stop-exit PnL by double-digit dollars/trade relative to NT's real 1s-bar-low-triggered fills. `offline_trades_march_2025.parquet` is described in `SPEC.md` as a "secondary offline trade reference" used for trade-level comparison against the live NT run's actual (realistic) fills — any PnL gap this produces will look like an NT execution discrepancy when it is actually this offline script overstating its own reference. (The opposing-flip-exit branch, by contrast, correctly uses the next bar's own open — only the stop branch has this defect.)

## Warnings

### [A2/B9] `strategy.py:210-245` — no `reset_regime`/`on_regime_flip` call for the very first (0→±1) regime establishment

`flip = prev_regime != 0 and new_regime != 0 and new_regime != prev_regime` is `False` on the very first transition out of the initial `self._regime_dir = 0` state, so `OHLCVDeltaTracker.reset_regime` and `CandidateTracker.on_regime_flip` are never called for that first regime. `attach_features.py` (lines ~180-201) explicitly handles this via a pre-loop seeding block that resets the tracker once for whichever regime is already active at the start of the window; `strategy.py` has no equivalent. Given the full Jan-1 lead-in, this transient un-reset state is very likely overwritten by the second real flip (probably within days), well before March — but this is an assumption, not a verified fact in this session's evidence. Recommend either adding the seeding call or an explicit test proving the first flip occurs early enough in January to be immaterial by March.

### [D3 — methodology disclosure] `offline_reference.py:51` — "offline reference" features are read from a pre-existing `prepared_2025.parquet`, not freshly recomputed this session

`build_candidates()` does `df = pd.read_parquet(C.PREPARED_2025_PATH, columns=feat_list + EXTRA_COLS)` — it reuses feature columns already computed by an earlier, separate pipeline run, and only the model **score** is freshly (re-)computed this session (as `SPEC.md` itself discloses: "Phase 1... computes and freezes... quantiles from a fresh... scoring pass," i.e., fresh scoring, not fresh features). This is not necessarily wrong — it does mean `reconcile.py`'s feature-parity check is comparing live NT against an independently-and-previously-computed ground truth (good, and this is exactly the mechanism that will surface the D1 CRITICAL finding above) — but it should be stated plainly in `STUDY_REPORT.md` that "feature parity" tests whether live NT reproduces an *earlier pipeline's* feature values, not a feature computation freshly derived in lock-step with this study.

### [G3] 1s→1m catalog resample `closed`/`label` convention not independently re-verified this session

CLAUDE.md memory records a previously-fixed catalog bug (`closed='right'` injecting look-ahead into 1m resampling, since fixed to `closed='left'`). This study reuses `data/catalog/NQ_v0_2020_2026` as-is without re-checking that fix is still in effect for the specific bar types (`NQ.XCME-1-SECOND-LAST-EXTERNAL`, `NQ.XCME-1-MINUTE-LAST-EXTERNAL`) used here. Trusted-but-unverified this session; recommend a one-time spot check before the completion-gate audit.

## Notes

### Root-cause contributor to the D1 CRITICAL finding: `self._prev_close` is overloaded with two different semantics

`self._prev_close` is correctly used as "close of the last 1s bar of the just-finished minute" for `update_1m` (line 236-238, which is correct and matches `attach_features.py`'s own `prev_close` variable), but the *same* attribute is reused in `_on_candidate` where the required semantics are "close of the bar at the candidate's own observation instant." The naming collision is what let the D1 bug go unnoticed. Recommend a dedicated, distinctly-named variable (e.g., `self._last_1s_close`, updated and read in a way that's unambiguous about which instant it reflects) when this is fixed, rather than reusing `_prev_close`.

### [E5] No explicit indicator/tracker warmup-stabilization gate before scoring begins

Beyond `RegimeEngine.atr is None` guards (which block candidate-stream opening and entry on a missing ATR) and the two trackers' own internal warmup handling (not independently re-audited this session — reused as "verified" per `SPEC.md`), there is no explicit assertion in `strategy.py` that `OHLCVDeltaTracker`/`PriceLevelTracker` have fully stabilized (e.g., prior-day OHLC populated, 1800s rolling window full) before March scoring begins. The full-year Jan lead-in almost certainly covers this in practice, but it is not asserted in code or tests.

## Clean checks

- A1 (bar indexing consistently uses `bar.ts_init`, not `ts_event`, throughout `strategy.py`)
- A3 (current-price references inside `_on_1s`/`_on_1m` use the `bar` argument's own OHLC directly, not future-indexed lookups — except the D1 finding above, which is a *stale*, not *future*, price)
- A4 (RTH classification via `_in_rth`/`is_rth_minute_of_day` consistently uses the bar's own `ts_init`, i.e., close time)
- A5 (all UTC↔America/Chicago conversions are explicit and consistent; DST handled natively by `pd.Timestamp.tz_convert`)
- B4/B5/B6 (no `.shift(-N)`, no `ffill`/`bfill`, no frequency-mismatched merges anywhere in this study's own code — no pandas feature path exists in `strategy.py` at all)
- B7 (R5/R2.5 thresholds are frozen constants from the full 2025 population, never recomputed on March — `build_thresholds.py`/`threshold_policy.py`)
- B10 (both feature families reuse the single central `OHLCVDeltaTracker`/`PriceLevelTracker` verbatim; no copy-pasted variant trackers)
- C3 (thresholds explicitly derived from the full-year population, not tuned on March — `build_thresholds.py` asserts source is "full-year 2025... never tuned on March")
- D4 (`ModelRuntime.score`/`score_dict` explicitly reject missing/extra/misordered feature columns rather than silently imputing or reordering — `test_model_runtime.py` covers all four failure modes)
- E1/E2 (bar-type strings used in `subscribe_bars` exactly match the catalog query bar types in `run_nt.py`)
- E3/E8 (stop-order mechanics: genuine resting `stop_market` GTC `reduce_only`, placed once at entry fill via `on_order_filled`, verified byte-for-byte pattern match against the POC's own already-audited `strategy.py`/`trade_state.py` — no regression to the manually-polled-market-order bug that POC's pre-execution audit found and fixed)
- Coincident 1s/1m bar ordering: `run_nt.py` calls `engine.add_data(bars_1s)` then `engine.add_data(bars_1m)`, matching `nt_live_scoring_infra_prereqs/tests/test_coincident_bar_ordering.py`'s `add_bars_causal_order()` finding exactly (confirmed by direct read of that test, which proves the ordering is a calling-convention artifact of `add_data`'s stable sort, not an NT-native guarantee) — and is itself regression-tested by this study's own `test_add_data_call_order_is_1s_before_1m`.
- One-trade-per-regime / re-entry suppression: `self._attempted_regimes.add(regime_start_ns)` executes synchronously *before* `_try_enter`/`submit_order` (`strategy.py:320-322`), so a same-bar double-candidate-emission for one regime cannot double-submit.
- 2026 data access: no `read_parquet`/`read_csv`/`open` call anywhere under `implementation/*.py` references a 2026 file (verified directly and matches this study's own `test_2026_path_access_prohibition`/`test_run_nt_load_end_hardcoded_to_2025` regression tests); `run_nt.py`'s `LOAD_END` is hardcoded `"2025-12-31 23:59:59"`.
- `_on_1m`'s reset-then-accumulate ordering fix itself (regime reset → RTH reset/end → `accumulate_regime_rth` → `update_1m`) does correctly match `attach_features.py:222-246`'s exact sequence, line-for-line — the *ordering* fix described as "fourth bug, unvalidated" in the task brief is verified CORRECT; the guard-scope bug found above (G2/A4) is a separate, adjacent defect in the same method.
- `evaluate_checkpoint`'s use of `active.last_close` (bar strictly before T) for `current_pnl`/`retained_mfe_ratio` is a *different*, correctly-implemented "current price" concept from the model-feature `reference_price` bug above — this one is real-data-validated (`test_established_flag_matches_ground_truth_exactly`, 0 mismatches across ~2,177 checkpoints) and matches `build_weakness_atlas.py:96-112`'s convention exactly.

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., whether a mid-run 1s/1m gap actually occurs in the March 2025 catalog window) are out of scope for static review but are flagged per the auditor's "when in doubt, flag it" mandate given the code provides no defense or observability if one does occur.*

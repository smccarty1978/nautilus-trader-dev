# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-12
**Scope:** `SPEC.md` (§3-5), `implementation/regime_5s.py`, `implementation/policy.py`,
`implementation/lineage.py`, `implementation/analysis.py`, `implementation/validate.py`,
`run_study.py`, `tests/test_regime_5s_parity.py`; read-only reference to shared
`studies/model_driven_entry_exit_discovery/implementation/engine.py` (pre-existing,
previously audited, unmodified — not re-litigated here).
**Scope hash:** `df23824655645abe54fcbe21e70369a424c05906053b1b18e1596500de0a3bc4`
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 10 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Verification of the seven load-bearing claims

1. **5s bucket = `(C-5s, C]`, no future fold-in.** `regime_5s.py:61-75`:
   `bucket_id = path_event_ns // 5e9`, `close_ts = (bucket_id+1)*5e9`, bucketing
   strictly on `path_event_ns` (open clock), never on `path_init_ns`. Confirmed by
   `test_bucket_contains_only_past_bars` against a real 400K-row slice. **Holds.**
2. **Entry fills at open of first bar with `path_init_ns > t0`.** `policy.py:113,123-124`
   uses `market.index_strictly_after(arm_ns)` → `engine.py:66-67`,
   `np.searchsorted(ts, ts_ns, side="right")` — strictly greater, ties excluded.
   Gate `V5` (`validate.py:55-58`) checks `entry_ns > arm_ns` on every entered
   trade. **Holds.**
3. **5s exit fills at open of first bar after flip's `close_ts`.** `policy.py:128-138`:
   `flip_ns = r5.first_non_aligned_after(arm_ns, direction)` (itself
   strictly-after via `side="right"` in `regime_5s.py:166`), then
   `f = market.index_strictly_after(exit_signal_ns)`. Gate `V6` checks
   `exit_ns > five_s_flip_ns` for every `FIVE_S_EXIT`. **Holds.**
4. **Stop detected on completed bar, fills next bar's open, trigger price never
   credited.** `policy.py:150-173`: `run_mae` scanned over `[start, f)`
   (completed bars only), `trigger` is the first crossing index, `fill = start +
   trigger + 1`; `exit_price = market.open_[fill]`. If `fill` isn't reachable
   in-session it degrades to `SESSION_CLOSE` at the session's own close — never
   backfills a trigger price. **Holds** (H4 clean).
5. **1m confirmation is diagnostic only.** `OUTCOMES = {STOP, FIVE_S_EXIT,
   SESSION_CLOSE}` (`policy.py:40`); `confirm_ns`/`confirmed_before_exit` are
   computed *after* `outcome` is already decided (`policy.py:189-198`) and never
   feed back into the exit branch. Gate `V7` asserts the outcome set. **Holds.**
6. **MFE/MAE start at the fill bar; reported excursion at trigger index, not
   fill index.** `hi/lo = market.high/low[start:f]` — index 0 is the entry/fill
   bar itself. For `STOP`, `held = trigger` (the completed bar that crossed the
   stop, one bar *before* the fill index `trigger+1`). For `FIVE_S_EXIT`/
   `SESSION_CLOSE`, `held = hi.size-1` (last actively-held bar, one bar before
   the fill index `f`). **Holds.**
7. **Vectorised `ewm_mean`/forward-fill ≡ literal per-bar engine replay.**
   `tests/test_regime_5s_parity.py` drives the real `TimeframeAggregator` +
   `RegimeStateEngine` bar-by-bar over a real 400,000-row slice and asserts exact
   equality of `close_ts`, OHLC, and `regime` against the vectorised build.
   **Holds for the tested equivalence** — see Note below for a caveat on what
   the *production* pipeline actually writes.

## Critical findings
None.

## Warnings
None.

## Notes

### [G] `regime_5s.py` — final partial bucket is not actually discarded, contrary to its own disclosed contract, but the defect is provably inert
`regime_5s.py`'s `main()` (lines 192–243) never truncates the last row of
`build_buckets()`/`flip_timeline()`. The real aggregator (`aggregator.py:83`,
cited in the module docstring at `regime_5s.py:1-27` and in SPEC §3.1/§7)
never closes a bucket that has no bar in the *next* slot to trigger it — i.e.
it never emits a genuinely in-progress final bucket. The test suite knows
this and manually compensates: `test_regime_5s_parity.py:79-81` does
`vectorised = apply_regime(buckets).head(buckets.height - 1)` before comparing
to the real replay. Production `main()` has no equivalent truncation, so
`_work/regime_5s_flips.parquet` (18,774,839 buckets, confirmed via
`regime_5s_build.json`) includes one bucket the real system would never have
closed. The build metadata's `"final_partial_bucket_discarded": true`
(`regime_5s.py:232`) is a hardcoded literal, not a computed check — it is
false on its face given the code.

**Why this doesn't change any reported number:** the store's last row is
`2025-12-30 23:59:52` UTC ≈ 17:59:52 CT — outside RTH (08:30–15:00 CT) by
~3 hours, so no P90 arm (RTH-only) can ever have `close_ts <= arm_ns` land on
this bucket. Even a forward search (`first_non_aligned_after`/
`first_aligned_after`) that happened to reach this tail entry would be moot:
`simulate_impulse`'s `f = min(f, session_end)` caps every exit at the entry
session's own 15:00 CT close before any fill index derived from this bucket
could be used. No arm, entry, or exit in the delivered results can reach it.

**Smallest fix (if desired):** drop the last row of `flip_timeline()`'s output
in `main()` to match the aggregator contract literally, and compute
`final_partial_bucket_discarded` rather than hardcoding it.

## Referred to contract-checker
- SPEC §2.1 documents arm loading as `implementation/arming.py::arm_population`; no
  `arming.py` exists — arms are read directly by `lineage.load_arms()`. Documentation/manifest accuracy, not a causal defect.

## Clean checks
A1-A5, B1-B7/B9/B10, C1-C3, F1-F4, G1-G3, H1-H4 verified clean on the files in
scope. Same-instant STOP/FIVE_S_EXIT tie resolves adversely as specified
(`policy.py:158-173`, always resolves `STOP` when triggered inside the held
window, matching SPEC §4.4's rule since the stop scan is bounded to indices
`< f`). Entry/exit denominators and alignment partitioning cross-checked by
gates `V8`, `V9`, `V13`, `V14` in `validate.py` (self-consistency only, not
independent re-derivation — noted for completeness, not blocking).

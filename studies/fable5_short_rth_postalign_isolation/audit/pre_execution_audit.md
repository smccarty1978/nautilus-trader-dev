# Pre-Execution Look-Ahead & Causality Audit — fable5_short_rth_postalign_isolation

**Date:** 2026-07-17 (re-audited 2026-07-17 after remediation)
**Scope:**
- `studies/fable5_short_rth_postalign_isolation/run_isolation.py`
- `studies/fable5_short_rth_postalign_isolation/tests/test_h1_variant.py`
- Direct imports inspected for cross-reference: `studies/fable5_specialized_w4/fable5_common.py` (`simulate_trade_arrays`, `touched_stop`, `stop_fill`), `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py` (`canonical_regime_timeline`, `simulate`), frozen schedule files `studies/fable5_nt_short_rth_policy_a/_work/short_rth_schedule_{2025,2026}.parquet`, frozen benchmark `studies/codex_5_w4_fade_confirmation_clock_isolation/results/isolation_trade_diffs.parquet`.

**Auditor:** lookahead-auditor v1 (pre-execution gate, per CLAUDE.md "Pre-execution trigger for complex causal/matching logic" — stop-timing mechanics reused from another study)

This is a **static, pre-execution** review; `run_isolation.py` has not been run as part of this audit (initial pass or re-audit). Frozen artifacts (schedule parquets, benchmark parquet) were read read-only to verify schema/column-name assumptions used by the reconciliation gate. The remediation described below was verified by direct source review and by independently executing the test suite (`pytest studies/fable5_short_rth_postalign_isolation/tests/test_h1_variant.py -v` — 4 passed), not by taking the remediation report at face value.

---

## Summary

- Critical: 0
- Warning: 0 (1 found in initial pass, fixed and independently re-verified — see Remediation below)
- Note: 0 open (2 found in initial pass, both addressed and independently re-verified)

---

## Checklist walk-through

### 1. `simulate()` vs `fable5_common.simulate_trade_arrays` — direct comparison

Line-by-line diff of `run_isolation.py:48-104` against `fable5_common.py:189-242` confirms the two are logically identical when `post_stop_enabled=True`:

- Same `timeout_ts`, `start`/`scheduled_i` boundary computation and the same `RuntimeError` guard (`run_isolation.py:53-58` ≡ `fable5_common.py:199-204`).
- Same `pre_stop`/`post_stop` formulas (`1.25`/`1.50` ATR, sign convention `entry - direction * mult * atr`).
- Same loop body ordering: early alignment check gated by `align_ts <= timeout_ts`, `timeout_pending` escalation, `now >= scheduled_fill_ts` opposing-flip exit, the (redundant, but faithfully-reproduced) second unconditional alignment check, `timeout_pending` arming, then the stop check.
- The only structural additions are (a) `stop_active = (not aligned) or post_stop_enabled` gating the `touched_stop` call (`run_isolation.py:88,91`), which is `True` unconditionally when `post_stop_enabled=True`, making the stop check behave identically to the original engine's unconditional `if touched_stop(...)` (`fable5_common.py:229`); and (b) the `mae_after_align` diagnostic accumulator (write-only, see Remediation).
- Both call the same `F.touched_stop` / `F.stop_fill` from `fable5_common` — no re-implementation of the fill/gap logic, so the "gap-through stop fills at trigger repriced to open" behavior is inherited unchanged (accepted per task framing).
- **Now additionally enforced by a direct cross-engine unit test**, not just manual diff (see Remediation, item R2).

**Verdict: clean.** `post_stop_enabled=True` reproduces the audited engine's decision path exactly; `post_stop_enabled=False` (H1) differs *only* in that `stop_active` becomes `False` once `aligned=True`, which is the intended, and only, behavioral change.

### 2. H1 stop removal — no new look-ahead

Removing the post-align stop check does not change how far forward the replay loop is allowed to see. The loop still walks `ts[start..scheduled_i]` bar-by-bar and only fires the opposing-flip exit when `now >= scheduled_fill_ts` (`run_isolation.py:80-82`), i.e., strictly causal — the trade is never closed "early" using knowledge of a future timestamp before the replay clock reaches it. `scheduled_fill_ts` itself is precomputed via `next_ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()` (`run_isolation.py:120-121`), using `canonical_regime_timeline`, which is the **same function object** imported from `CODEX_5_X_run_established_fade.py` and used identically (`ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()`, `CODEX_5_X_run_established_fade.py:354`) by the offline benchmark's own `simulate()`. Confirmed this is not a re-derivation with different semantics — it is literally the same builder call. H1 therefore only ever lets a trade run *later in already-causal replay time* than H0 would have; it cannot pull information from beyond `scheduled_fill_ts` because H0 already treats that same timestamp as its own hard upper replay bound.

**Verdict: clean.**

### 3. Input causality / freezing

All per-trade decision inputs in `run_year()` (`run_isolation.py:124-137`) come from the frozen schedule columns: `entry_ts=target_fill_ts`, `direction=entry_direction`, `atr=atr_at_checkpoint`, `align_ts=recon_confirm_flip_ns`. `entry` price is independently recomputed as `opens[searchsorted(ts, entry_ts)]` rather than trusted from the schedule's `offline_entry_open` field — this is a stricter, not weaker, causal posture (it re-derives from raw 1s bars rather than reusing a possibly stale cached value), and any divergence would be caught by `reconcile_h0`'s exact-match gate on `h0_net_pnl`. No field derived from H0 or H1 *outcomes* feeds any decision variable — `mae_after_align` is accumulated during the replay but never read back into the same replay's control flow (confirmed: it is only written to, never branched on, within `simulate()`).

**Verdict: clean.**

### 4. `attribution()` / `summarize()` / `monthly()` — descriptive only

All three functions in `run_isolation.py:177-263` operate on the already-materialized `all_df` (post-simulation) and compute pure aggregates (profit factor, drawdown, win rate, cohort counts, medians). None of these values are fed back into `simulate()` or into schedule construction — there is no second pass. `decide()` (`run_isolation.py:266-277`) uses only `net_pnl` and `max_closed_dd` from the "combined" split summary, not `mae_after_align`.

**Verdict: clean** on causality grounds. The correctness (not look-ahead) defect previously found in `mae_after_align`'s formula has been fixed and independently re-verified — see Remediation, item R1.

### 5. `reconcile_h0()` — exact-reproduction gate

Verified against the actual benchmark file: `isolation_trade_diffs.parquet` contains exactly the columns `reconcile_h0` reads (`policy_id`, `year`, `trade_direction`, `session`, `entry_fill_ts`, `new_exit_fill_ts`, `new_exit_fill_px`, `new_exit_reason`, `new_net_pnl_usd`). Filtering to `POLICY_A_COMBINED_1P25_300S` / `short_fade` / `RTH` yields exactly **807** rows across 2025 (604) + 2026 (203), matching `run_isolation.py`'s hard population assertion (`len(all_df) != 807`) and the frozen schedule row counts (604 + 203 = 807, verified directly from the schedule parquets). The benchmark's `new_exit_reason` value counts (`original_opposing_flip_exit`=372, `preflip_policy_stop`=255, `confirmation_timeout_exit`=144, `original_stop_after_aligned_flip`=36) use the identical four string literals hard-coded in `run_isolation.py`'s `simulate()`, and the 36-trade `stop_after_flip` count matches the task's disclosed +$27,013/36 reference figure. `reconcile_h0` compares entry ts, exit ts, exit px (`atol=1e-9`), exit reason, and net PnL (`atol=1e-6`) row-for-row after sorting both frames by `entry_fill_ts`, and raises `RuntimeError` on any nonzero mismatch count or population-count mismatch — this is a real, enforced gate, not a no-op comparison (contrast with the "tautology" class of bug flagged in prior audits, e.g. `w4_exit_study_dropped_b4`). The row-alignment safety gap (Note N2 in the initial pass) has been closed — see Remediation, item R3.

**Verdict: clean.**

---

## Remediation (verified 2026-07-17, same day as initial pass)

All three findings from the initial pass were addressed. Each fix was independently confirmed by direct source review (not by trusting the remediation report) plus, where applicable, an executed test run.

### R1 — [WARNING, closed] `mae_after_align` sign fix

`run_isolation.py:66-71` now reads:

```python
if aligned:
    # ADVERSE move after alignment: for a short (dir=-1) price UP
    # (highs) is against us; for a long, price DOWN (lows) is.
    adv = ((highs[i] - entry) / atr if direction == -1
           else (entry - lows[i]) / atr)
    mae_after_align = max(mae_after_align, adv)
```

Confirmed by direct read: branches now match the engine's own sign convention (`fable5_common.touched_stop`: short stop triggers on `high >= stop`, long stop triggers on `low <= stop`) — for a short, `highs[i] - entry` is the adverse (against-position) excursion; for a long, `entry - lows[i]` is. This is the correct swap of the originally-inverted ternary. Confirmed still write-only within `simulate()` (never branched on, never feeds `aligned`/`stop_active`/exit routing/`net_pnl`) — the fix is scoped exactly to the diagnostic-correctness defect identified, with no side effect on the causal/PnL path. `median_mae_after_h0_stop_atr` / `max_mae_after_h0_stop_atr` in `attribution()`/manifest/`attribution.json` will now correctly report adverse (not favorable) excursion for the `original_stop_after_aligned_flip` cohort.

Residual minor point (not blocking, informational only): the accumulator still only starts updating from the bar *after* alignment first becomes `True` within a given loop iteration (the `if aligned:` check runs before that iteration's alignment-assignment), so the alignment bar's own H/L range is excluded from the diagnostic. This is a one-bar completeness detail on a non-decision diagnostic field, immaterial to the study's causality or PnL conclusions — not re-raised as a Warning.

**Status: CLOSED.**

### R2 — [Note N1, closed] Direct engine-parity test added

`tests/test_h1_variant.py:75-91` adds `test_h0_matches_audited_engine`, which imports `fable5_common` directly, runs `F.simulate_trade_arrays(...)` and `run_isolation.simulate(..., post_stop_enabled=True)` on the identical tape used by `test_aligned_h0_stops_h1_holds` (the post-alignment-stop-breach case, i.e., the one scenario where `post_stop_enabled` actually changes control flow relative to a naive `stop_active=True`), and asserts `exit_reason`, `exit_ts`/`exit_fill_ts`, `aligned`/`reached_aligning_flip`, `net_pnl`/`net_pnl_usd`, and `exit_px`/`exit_fill_px` are all equal. Verified the key-mapping dict in the test is correct (`exit_fill_ts`↔`exit_ts`, `reached_aligning_flip`↔`aligned`) by cross-checking both functions' actual return-dict keys. Independently executed:

```
pytest studies/fable5_short_rth_postalign_isolation/tests/test_h1_variant.py -v
```
→ `4 passed` (all four tests, including the new one).

This makes the "byte-identical when `post_stop_enabled=True`" claim self-verifying rather than resting solely on the population-level `reconcile_h0` gate.

**Status: CLOSED.**

### R3 — [Note N2, closed] `reconcile_h0` duplicate-`entry_fill_ts` guard

`run_isolation.py:164-165` now inserts, immediately after the length check and before the positional-compare block:

```python
if mine.entry_fill_ts.duplicated().any() or off.entry_fill_ts.duplicated().any():
    raise RuntimeError(f"{year} duplicate entry_fill_ts; positional reconcile unsafe")
```

Confirmed correctly placed (before any positional array comparison) and correctly scoped (checks both frames). This closes the previously-unverified assumption that the sort-then-zip alignment in `reconcile_h0` is safe.

**Status: CLOSED.**

---

## Clean checks

- Loop-by-loop diff of `simulate()` against `fable5_common.simulate_trade_arrays` — identical decision path when `post_stop_enabled=True`; `stop_active` gate is the only intended H1 behavioral change. Now also covered by an executed direct-comparison unit test (R2).
- H1's opposing-flip exit boundary (`scheduled_fill_ts`) is checked causally (`now >= scheduled_fill_ts` inside the forward replay loop) and is sourced from the same `canonical_regime_timeline` builder call used by the offline benchmark — confirmed by direct source comparison, not by name alone.
- All per-trade `simulate()` inputs (`entry_ts`, `direction`, `atr`, `align_ts`) are frozen-schedule fields; `scheduled_decision` is derived from a timeline built over full-year raw bars but used only as a forward replay boundary, never to alter entry/stop pricing or to look behind `now`.
- Stop-touch detection uses `highs`/`lows` via `F.touched_stop`, not `close` (H1 in the general checklist) — inherited from the audited engine.
- Stop/timeout/opposing-flip fills all use the triggering bar's `open` (or gap-adjusted price via `F.stop_fill`), not the trigger level itself when gapped — consistent with H4 in the general checklist; inherited from the audited engine and disclosed as an accepted caveat.
- `reconcile_h0` reads the correct, verified column names from the actual `isolation_trade_diffs.parquet` schema and filters to the correct `(policy_id, trade_direction, session)` slice; population count (807 = 604 + 203) and exit-reason distribution (36 `stop_after_flip`) match the task's disclosed reference figures; now also guarded against unsafe positional alignment on duplicate `entry_fill_ts` (R3).
- `attribution()`, `summarize()`, `monthly()`, `decide()` are single-pass descriptive aggregates over already-simulated output; no field feeds back into `simulate()` or schedule construction.
- `mae_after_align` is confirmed write-only inside `simulate()` (does not influence `aligned`, `stop_active`, exit routing, or `net_pnl`) and now correctly signed (R1).
- Test fixtures in `test_h1_variant.py` were hand-traced against the engine and are internally consistent (correct stop levels, correct alignment-gate boundary, correct H0==H1 equivalence off the post-align-stop path); all 4 tests independently executed and passing.

---

*Audit complete. Initial-pass findings reflect read-only static analysis; remediation was verified by direct source review plus an independently-executed test run (`pytest ... -v` → 4 passed). `run_isolation.py`'s `main()` (the full 807-trade simulation + `reconcile_h0` gate) was not executed as part of this audit — that remains the coordinator's own execution to run and observe pass/fail on. Per CLAUDE.md's audit-gate methodology, zero CRITICAL and zero open WARNING/Note clears this component for its first execution.*

**Status:** **PASS**
**Findings:** **0 CRITICAL, 0 WARNING**

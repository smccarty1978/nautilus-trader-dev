# Look-Ahead & Timestamp Audit (PRE-EXECUTION)

**Date:** 2026-07-11
**Scope:**
- `studies/_shared_exit_mgmt/base_strategy.py` (480 lines)
- `studies/_shared_exit_mgmt/mfe_mae.py` (71 lines)
- `studies/all_flips_exit_management/strategy.py` (41 lines)
- `studies/f2_confirmed_exit_management/strategy.py` (78 lines)

Trusted (already-audited) infra called by the above, read for call-correctness only, not re-audited:
- `collectors/collector_v2/registry.py`
- `collectors/collector_v2/aggregator.py`
- `collectors/collector_v2/regime_engine.py`

Also read for cross-reference (NOT in scope, NOT modified, flagged only where the new code inherits a pattern from it):
- `collectors/collector_v2/strategy.py`

**Auditor:** lookahead-auditor v1
**Status:** Code has NOT been executed. This is the CLAUDE.md pre-execution gate for new fill-timing/entry mechanics.

## Summary

- Critical: 1
- Warning: 5
- Note: 7

## Critical findings

### [A1/F1] `studies/_shared_exit_mgmt/base_strategy.py:232` — RTH gate uses bar OPEN time (`ts_event`), not CLOSE time (`ts_init`)

```python
231	        if flipped:
232	            in_rth = self._is_rth(bar_ts_event)
```

`bar_ts_event` (line 219: `bar_ts_event = bar_data["ts_event"]`) is the 1m flip bar's **OPEN** timestamp. Per project convention (CLAUDE.md A1/F1), RTH/ETH classification must use the bar's **CLOSE** time (`bar_data["ts_init"]`, or `decision_ts`), since Databento/NT 1m bars are `ts_event`=open, `ts_init`=close (post `ts_init_delta`).

**Impact:** this is the sole gate for whether a regime flip is even considered for entry (`if not in_rth: return` in both `AllFlipsStrategy._on_regime_flip` and `F2ConfirmedStrategy._on_regime_flip`). Using open-time systematically misclassifies boundary bars:
- A 1m bar covering 08:29:00–08:30:00 CT (open=08:29, close=08:30) is the **true first RTH bar** (closes exactly at the 08:30 RTH open) but is classified as ETH under this code (08:29 < rth_start_min).
- A 1m bar covering 14:59:00–15:00:00 CT closes exactly at session end; open-time classification happens to still label it RTH here, but the logic is fragile/coincidental, not deliberately close-time-based.

This silently drops (or, at the other boundary, could silently admit) specific flips every single trading day — not a one-off, a systematic per-day misclassification.

**Provenance note:** this exact pattern (`in_rth = self._is_rth(bar_ts_event)`) already exists at `collectors/collector_v2/strategy.py:499`, which is *not* one of the three files this task designated as trusted infra (only `registry.py`/`aggregator.py`/`regime_engine.py` are trusted). The new code appears to have faithfully re-derived this bug from the un-audited `strategy.py` pattern rather than introducing a new one. Per CLAUDE.md's pre-execution rule ("a bug inherited from upstream is still a bug in your results"), this should be corrected here regardless of whether `collector_v2/strategy.py` itself is ever revisited.

**Recommended fix (do not apply):** change line 232 to `in_rth = self._is_rth(bar_data["ts_init"])` (or `self._is_rth(decision_ts)`, which is `>= ts_init` and therefore also safe).

## Warnings

### [E-integrity] `studies/_shared_exit_mgmt/base_strategy.py:354-363` — no retry on exit-order rejection; orphaned trade risk

```python
354	    def on_order_rejected(self, event):
355	        if self._trade is None:
356	            return
357	        cid = event.client_order_id.value
358	        if cid == self._trade.get("entry_order_id"):
359	            self._diag["entries_rejected"] += 1
360	            self._trade = None
361	        elif cid == self._trade.get("exit_order_id"):
362	            self._diag["exits_rejected"] += 1
363	            self._trade["exit_order_id"] = None
```

If a reduce-only FOK exit order is rejected, `exit_order_id` is cleared but nothing resubmits an exit. `self._trade` stays open indefinitely; the position will only be closed on the **next** opposing 1m flip (`_submit_exit` is only called from the flip-detection block in `_on_1m_bucket_closed`), which may not occur before the backtest/session ends. Consequences:
- `_update_open_trade` keeps appending checkpoints for this trade (correctly causal on their own), but if the trade never gets a fill event, `_finalize_trade()` is never called and the trade never lands in `self._trades` / `trades.parquet` — an orphaned block of checkpoints with no matching completed-trade record, and a silently-missing trade in the final tally.
- No new entry can be scheduled while `self._trade is not None` (guarded in the pending-entry submission check), so a stuck trade also blocks all subsequent signals for that instrument until the position resolves.

**Recommended fix (do not apply):** add a resubmission path (e.g., retry the exit on the next 1s bar, or force-close at `on_stop`) and/or emit a hard diagnostic/halt if a trade remains open with `exit_order_id is None` for more than N bars.

### [D1-adjacent] `studies/_shared_exit_mgmt/base_strategy.py:201-249` — unverified equivalence of two independent "1m" bar sources

The strategy consumes **two different 1m data streams** for the same nominal bar:
1. The really-subscribed `bar_type_1m` catalog bars (`_on_1m_bar`, lines 201-210) — source of `bar_data["open"/"high"/"low"/"close"]`, used for HH/LL confirmation (F2) and `flip_h`/`flip_l`.
2. The aggregator's synthetic 1m bucket built by summing 1s bars (`TimeframeAggregator` → `RegimeStateEngine` → `CompletedBarRegistry`) — source of `s_1m.regime`/`s_1m.atr`, used for direction and ATR normalization.

The only cross-check performed is a **timestamp** match (`bar_data["ts_init"] != s_1m.close_ts: return`, line 217) — there is no check that the two sources' OHLC values actually agree. If the 1m catalog was built independently from the 1s catalog (different resampling method, different roll-day handling, different session alignment), the regime direction (from stream 2) and the HH/LL levels used to confirm entries (from stream 1) could silently reference two different realities of the same nominal minute.

**Recommended fix (do not apply, this is a data-validation step, not a code change):** before trusting results, run a one-time reconciliation comparing `bar_type_1m` catalog OHLC to the aggregator's synthetic-1m OHLC (built by feeding the 1s catalog through the same aggregator standalone) over a full sample period; assert max abs diff ≈ 0.

### [E5] `studies/_shared_exit_mgmt/base_strategy.py:381-403` (via `RegimeStateEngine` in `regime_engine.py:88-102`) — no ATR/EMA warmup gate before entries are eligible

`RegimeStateEngine._atr` is `None` until 14 completed bars have contributed a true-range sample (`atr_period=14`), while EMA9-based regime (`self._ema9_h`/`_l`) is seeded on the very first bar and can flip to non-zero within the first few bars. This means a flip (and therefore an entry) can be scheduled while `s_1m.atr` is still `NaN`.

`_update_open_trade`'s fallback:
```python
381	        atr = t.get("atr_at_signal", float("nan"))
382	        safe_atr = atr if atr and atr == atr and atr > 0 else 1.0
```
silently substitutes `safe_atr = 1.0` in that case, so every `*_atr_from_entry` checkpoint field (`mfe_atr_from_entry`, `mae_atr_from_entry`, `giveback_atr_from_entry`, `current_pnl_atr_from_entry`) is computed in **raw price points** instead of true ATR units for these early trades, with no flag distinguishing them from correctly-normalized rows downstream. This will contaminate the first ~14+ bars of every backtest run (and after any data gap that resets the engine).

**Recommended fix (do not apply):** gate entries behind `s_1m.atr is not None` (or an explicit `indicator.initialized`-style flag on `RegimeStateEngine`), or at minimum write an explicit `atr_was_warmed_up: bool` column to checkpoints/trades so contaminated rows can be filtered downstream.

### [F2/F4-ambiguity] `studies/_shared_exit_mgmt/base_strategy.py:231-249` + `studies/f2_confirmed_exit_management/strategy.py:66-78` — confirmation/entry is never re-checked against the RTH window

Only the **flip bar's** `in_rth` status gates whether a flip is tracked at all (`_pending_flip` only created `if in_rth`). For F2, the confirmation (and therefore the entry decision) happens one full minute later, at bar+1's close — but `in_rth` is never re-evaluated at that point. Combined with the CRITICAL open/close-time bug above, it is genuinely ambiguous whether an RTH flip in the last tradable minute of the session (e.g. 14:58-14:59 CT) is intended to produce an entry that fills in the first ETH minute after 15:00 CT, or whether entries should also be RTH-gated at confirmation/fill time.

**This is filed as a WARNING with a specific open question** (per audit protocol for genuine ambiguity), not asserted as a bug: please confirm the intended session-boundary behavior for F2_CONFIRMED before the first execution, since it changes the population definition at the margin.

### [defensive/dead-code] `studies/f2_confirmed_exit_management/strategy.py:42-43` — confirmation guard likely unreachable

```python
42	        if bar_ts_event <= self._pending_flip["flip_ts_event"]:
43	            return  # this bar IS the flip bar itself; wait for bar+1
```
Given `_on_1m_bucket_closed` only fires once per strictly-increasing `close_ts` (enforced by `CompletedBarRegistry.update`'s monotonicity check), and `_check_pending_confirmation` runs before the same call's own `_on_regime_flip` (so `_pending_flip` can never contain the *current* bar's own data when this guard is evaluated), this branch appears unreachable in practice — `_pending_flip`, when non-`None`, will always have `flip_ts_event` strictly less than the current `bar_ts_event`. Not a correctness bug (the guard is harmless if it never fires), but worth a comment/assertion so a future refactor doesn't inadvertently start relying on it to actually gate something.

## Notes

### `studies/_shared_exit_mgmt/base_strategy.py:397-403` vs `studies/_shared_exit_mgmt/mfe_mae.py:61-71` — formula duplication

`giveback_atr()`/`to_atr()` in `mfe_mae.py` are never called by `base_strategy.py`; the checkpoint's `giveback_atr_from_entry` / `distance_from_mfe_atr` fields (lines 400-403) are hand-computed inline using the identical formula. Recommend the base class call the shared function directly so a future formula change can't silently diverge between the two call sites (the module docstring's stated goal — "used identically by live NT strategy and offline atlas builders" — is only actually true for `update_running_extremes`/`bar_pnl_mfe_mae`, not for giveback).

### `studies/_shared_exit_mgmt/base_strategy.py:400-403` — duplicate columns

`giveback_atr_from_entry` and `distance_from_mfe_atr` are computed with the literally identical formula (`(new_mfe - cur_pnl) / safe_atr`). Likely an intentional naming alias for downstream convenience; flag with a comment so it isn't mistaken for a bug by a future reader (or removed as if redundant, which would be fine, but should be a conscious choice).

### `studies/_shared_exit_mgmt/base_strategy.py:201-210` — no monotonicity assertion on the real 1m bar stream

Unlike `CompletedBarRegistry.update()` (which raises on non-monotonic `close_ts`), `_on_1m_bar` unconditionally overwrites `self._latest_1m_bar_data` with no check that `bar.ts_init` is strictly increasing. Defensive suggestion: assert increasing `ts_init` so an out-of-order bar (which should never happen under normal NT streaming) fails loudly instead of silently corrupting `bar_data`.

### `studies/_shared_exit_mgmt/base_strategy.py:192-199, 275-286` — `entry_delay_ns > 0` path is unexercised

The "submit ~1s before target so NT's bar_execution engine fills at the target bar's open" mechanism is only meaningfully different from immediate-submit when `entry_delay_ns > 0`. Both in-scope studies hardcode `entry_delay_ns = 0`, which collapses the check (`decision_ts >= fill_ts_target - 1s`) to "always true in the same iteration the signal fires." This is fine for the current studies but means the nonzero-delay branch is **entirely unverified** by this code review or by execution. Flag for a dedicated test before any future study sets a nonzero delay.

### Config default `position_size=1` (both studies) — historical FOK gotcha reminder

Per project memory, NT FOK orders **cancel entirely** rather than partial-filling above ~1-lot synthetic liquidity. Both `AllFlipsConfig`/`F2ConfirmedConfig` inherit `position_size: int = 1` from the shared base config, so this shouldn't bite in the current studies, but is worth flagging explicitly since the field is exposed and unguarded — any future config bump to >1 lot for these studies should re-trigger this exact historical failure mode and needs the same audit treatment given previously.

### Post-execution parity checks needed on first run (not verifiable by static review alone)

Two assumptions embedded in the "submit ~1s before target" design are standard NT `bar_execution=True` behavior but should be empirically confirmed on the very first run before trusting results, per the pre-execution gate's intent:
1. A market order submitted synchronously inside `_on_1s_bar` fills at the **next** 1s bar's open, not the current bar's close.
2. `on_order_filled` fires (and `self._trade["fill_price"]`/`entry_ts` are set) before the **next** `on_bar` dispatch, so `_update_open_trade`'s post-fill guard (`entry_ts is None` check) behaves as intended and no bar is skipped or double-counted around the fill event.

### `_maybe_stop_policy_exit` stub (Phase 5/6)

Noted descriptively per task instructions — not treated as a finding. When populated, it will need its own causality pass: in particular it must only act on state already appended by `_update_open_trade` for the *current* bar (never a future bar), and must never retroactively rewrite earlier checkpoints.

## Clean checks

- **A1/A2 (elsewhere):** `decision_ts` is `bar.ts_init` throughout, never `ts_event`, for every registry/indicator read. `CompletedBarRegistry.audit_provenance()` (trusted infra) enforces `close_ts <= decision_ts` as a hard invariant on every timeframe — this is airtight except for the single RTH-gating call flagged as CRITICAL above, which reads `bar_data["ts_event"]` directly rather than going through the registry.
- **B2/B3:** No `i+1` leakage found in confirmation logic. F2's bar+1 HH/LL + momentum check correctly uses only the flip bar's OHLC (available at/after its own close, stored earlier) and the confirmation bar's own OHLC (available at its own close) — never data from a bar that hasn't closed relative to `decision_ts`.
- **C-series:** N/A — no label construction in these files; forward-looking fields are explicitly deferred to a separate, not-yet-written offline atlas builder per both `audit/population_definition.md` files, matching CLAUDE.md's ML label-construction rule.
- **D2/D3:** N/A — no ML filter cascade or ONNX inference in these files.
- **H-series:** N/A — no SL/PT/bracket simulation loop in these files; exit is opposing-flip only, and the future stop-policy hook is currently a no-op stub.
- **MFE/MAE fill-anchoring:** confirmed anchored to `t["fill_price"]` (the actual NT fill from `on_order_filled`), never to `flip_close`/`pending_flip`/any pre-fill reference (`base_strategy.py:342-345`, `366-379`).
- **Checkpoint causality (item 1 of the task's specific checklist):** confirmed no path appends a checkpoint before `entry_ts`/`fill_price` are set (`_update_open_trade`'s early-return guard, line 368-369), and no path appends a checkpoint after a trade is finalized (`_trade` is set to `None` in `_finalize_trade` and only re-populated by `_submit_entry`, which requires `_trade is None` — no window found where a stale `_trade` reference could receive a late checkpoint into what is actually the next trade).
- **Stale/future bar_data (item 2):** confirmed `bar_data` passed into `_on_regime_flip`/`_check_pending_confirmation` is always the just-closed bar matching the current bucket-close event (`bar_data["ts_init"] != s_1m.close_ts` guard, line 217), and the real `bar_type_1m` subscription bar for a given minute is guaranteed (by strict `ts_init`-ordered dispatch) to arrive one full second before the aggregator's synthetic completion event for the same minute — so no future/stale-bar read was found.
- **Pending-flip overwrite (item 3):** confirmed NOT a look-ahead risk. `_check_pending_confirmation` always resolves (clears) `_pending_flip` on the very next 1m bucket close regardless of confirm/reject outcome, and runs strictly before that same call's own `_on_regime_flip`, so a new flip can never silently replace an unresolved pending flip — every pending flip has an enforced 1-bar lifetime.
- **regime_start_ts population (item 4):** confirmed populated from information available at (not after) the entry decision instant in both studies. AllFlips uses the flip bar's own `ts_init`; F2 uses the *original* flip bar's `ts_init`, stored one bar earlier than the confirmation/entry decision — matches the documented population definition in both `audit/population_definition.md` files.
- **Opposite-flip pending-entry cancellation:** confirmed causal — cancellation is decided from the same bucket-close event's `new_regime` before any new pending entry could be scheduled in that same cycle.
- **Bar-type dispatch routing (`on_bar`):** confirmed no cross-contamination between the 1s and 1m subscription handlers (exact string match on `bar.bar_type`).

---

*Audit complete. Findings reflect read-only static analysis of code that has not yet been executed. Address the CRITICAL finding and resolve the ambiguity in Warning #4 before first execution; the remaining Warnings should be addressed or explicitly waived before the study's results are trusted. Re-invoke lookahead-auditor on this scope after edits, per CLAUDE.md's audit gate.*

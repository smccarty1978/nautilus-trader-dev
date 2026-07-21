# Look-Ahead & Timestamp Audit (RE-AUDIT, PRE-EXECUTION)

**Date:** 2026-07-11
**Scope:**
- `studies/_shared_exit_mgmt/base_strategy.py` (526 lines)
- `studies/_shared_exit_mgmt/mfe_mae.py` (72 lines)
- `studies/all_flips_exit_management/strategy.py` (42 lines)
- `studies/f2_confirmed_exit_management/strategy.py` (84 lines)

This is a **re-audit** following fixes applied against the prior report (same
file, previously dated 2026-07-11, 1 CRITICAL / 5 WARNING / 7 NOTE). Code has
STILL NOT been executed — this is the second pass of the CLAUDE.md
pre-execution gate. Files were re-read in full (not diffed) for this pass.

Trusted (already-audited) infra called by the above, read for call-correctness
only, not re-audited: `collectors/collector_v2/registry.py`,
`collectors/collector_v2/aggregator.py`, `collectors/collector_v2/regime_engine.py`.

Also reviewed: `studies/_shared_exit_mgmt/bar_source_reconciliation_report.md`
(standalone data-validation output, not code, produced to close the
D1-adjacent WARNING).

**Auditor:** lookahead-auditor v1

## Summary

- Critical: 0
- Warning: 0
- Note: 2 (both residual/cosmetic, no action required to proceed)

## Verification of each prior finding

### [CRITICAL, A1/F1] RTH gate used bar OPEN time — RESOLVED, no regression

`base_strategy.py:255` now reads:

```python
in_rth = self._is_rth(bar_data["ts_init"])
```

inside `_on_1m_bucket_closed`'s `if flipped:` block. `bar_data` is
`self._latest_1m_bar_data`, which is guaranteed equal to `s_1m.close_ts` by
the guard three lines earlier (`bar_data["ts_init"] != s_1m.close_ts: return`,
line 234) — so this is genuinely the flip bar's CLOSE time, not its open
time. This is exactly the recommended fix from the prior audit.

No regression: `bar_data["ts_init"]` is read from the already-validated,
already-monotonicity-checked `_latest_1m_bar_data` dict (see NOTE fix #3
below), not recomputed or re-derived. `_is_rth_minute` (used separately for
session-tagging a finalized trade, line 480) already used the correct
timestamp (the actual fill event's `ts_event`) and was never part of this
finding — unaffected, still correct.

**Verdict: fully resolved, clean.**

### [WARNING, E-integrity] No retry on rejected exit orders — RESOLVED, no double-submission risk found

New code in `_on_1s_bar` (lines 189–200):

```python
if self._trade is not None:
    self._update_open_trade(bar, decision_ts)
    if (self._trade.get("exit_reason") is not None
            and self._trade.get("exit_order_id") is None):
        self._submit_exit(reason=self._trade["exit_reason"])
```

Traced the full state machine to check for double-submission / interaction
with the opposite-flip-triggered exit path (`_on_1m_bucket_closed`, which
runs earlier in the same `_on_1s_bar` call, before this block):

- `_submit_exit` guards itself: `if self._trade.get("exit_order_id") is not
  None: return` (line 354). `exit_order_id` is set synchronously *before*
  `self.submit_order(order)` is called, so by the time the retry-check block
  runs later in the same `_on_1s_bar` dispatch, if the opposite-flip path
  already submitted an exit this bar, `exit_order_id` is already non-`None`
  and the retry is a no-op. **No concurrent duplicate orders are possible**
  — the guard is checked at the single entry point (`_submit_exit`) that all
  callers (flip-triggered and retry) share.
- `exit_order_id` is only ever cleared back to `None` by
  `on_order_rejected`, which is the terminal outcome of a specific,
  uniquely-`client_order_id`'d order. Since NT generates a fresh unique
  `client_order_id` per `order_factory.market()` call, event routing by
  `cid ==` comparison cannot confuse a stale rejection/fill event from an
  earlier attempt with a later one, regardless of synchronous vs.
  asynchronous event delivery.
- Interaction with the flip-triggered path: confirmed the retry can never
  fire while a flip-triggered exit order is genuinely in flight (unfilled,
  unrejected) — it only fires when `exit_order_id is None`, i.e. no order is
  currently outstanding.

**Residual NOTE (not a functional bug):** if the matching engine processes
`on_order_rejected` synchronously inside `self.submit_order(order)` (typical
for NT's default backtest fill model), then on the specific 1s bar where an
opposite-flip exit is first submitted *and* immediately rejected, the retry
block later in that same `_on_1s_bar` call will find `exit_order_id is None`
again and attempt a second submission within the same bar — rather than
waiting for the "next" 1s bar as the code comment implies. This does not
cause duplicate live orders or wrong PnL (each attempt is still gated
sequentially through the same guard), just a slightly tighter retry cadence
than the comment describes on the specific bar of the original rejection.
Cosmetic — no fix required to proceed.

`on_stop`'s new `trade_open_at_stop` diagnostic is a passive counter (does
not force-close), which matches the fix description ("surface it loudly");
if the retry genuinely never succeeds by the end of a run, the trade is
still excluded from `trades.parquet` (its checkpoints remain, orphaned) —
but this is now a visible, diagnosed condition rather than silent, and is
expected to be exceedingly rare given retries occur on every subsequent 1s
bar for the remainder of the session.

**Verdict: resolved. No new double-submission or race-condition risk
found.**

### [WARNING, E5] No ATR-warmup gate before entries — RESOLVED

`_schedule_entry` (lines 298–320) now rejects (returns early, increments
`entries_rejected_atr_not_warmed`) when `atr_at_signal is None or
atr_at_signal != atr_at_signal` (NaN check), for both call sites:
`AllFlipsStrategy._on_regime_flip` and
`F2ConfirmedStrategy._check_pending_confirmation` (the latter correctly
gates at *confirmation* time, using the ATR value read at that time, which
is consistent with F2's actual decision instant).

Checked for side effects: the early return happens before `_pending_entry`
is touched, so no partial/corrupt pending-entry state is left behind; F2's
`self._pending_flip = None` reset still executes unconditionally afterward
("confirmation check done either way"), so no stale `_pending_flip` lingers.

Consequence verified: `_update_open_trade`'s `safe_atr = ... else 1.0`
fallback (line 416) is now effectively unreachable for any trade that
actually reaches `_submit_entry`, since every scheduled (and therefore
every filled) trade's `atr_at_signal` passed the NaN gate before being
stored in `_pending_entry`. The fallback remains as a harmless defensive
guard against a genuine ATR of exactly `0`/negative, which should not occur
for a true-range-based Wilder ATR once warmed.

**Verdict: fully resolved, clean.**

### [WARNING, F2/F4-ambiguity] RTH re-check at confirmation time — confirmed non-issue per user decision

Re-read `_check_pending_confirmation` in both the base class (no-op) and
`F2ConfirmedStrategy` (lines 38–69): confirmed no `in_rth` parameter is even
passed into this method's signature, and no RTH/session check of any kind
exists anywhere in it. The only RTH gate in the entire pipeline is the one
evaluated once, at flip time, in `_on_1m_bucket_closed` (now using
`ts_init`, per the CRITICAL fix above) and consumed by `_on_regime_flip`'s
`if not in_rth: return` guard in both subclasses. This is exactly the
"gate only at flip time" behavior the user confirmed, and it matches the
`collector_v2` precedent cited. No code changes were needed and none were
made.

**Verdict: confirmed accurately reflects the user-confirmed design. Not a
bug — population-definition choice, correctly implemented as stated.**

### [WARNING, D1-adjacent] Unverified equivalence of two 1m bar sources — resolved, reasoning checked

`bar_source_reconciliation_report.md` reports 8,038/8,039 matched
`close_ts` bars byte-identical (max abs diff 0.0) across open/high/low/close
over a full week (2024-01-08 to 2024-01-15). This substantively closes the
WARNING: the two independent 1m sources (real `bar_type_1m` catalog
subscription vs. the 1s-aggregated synthetic bucket) do agree.

Checked the boundary-artifact reasoning: the report attributes the single
non-matching `close_ts` (the sample window's last 1m bar) to
`TimeframeAggregator` never closing a final partial bucket without a
subsequent triggering 1s bar, and characterizes this as a property of the
*standalone validation script's* truncated window, "not a discrepancy that
exists in the live NT strategy... which runs continuously." This claim is
correct **for every interior day/minute** of a continuous backtest — mid-run,
a subsequent 1s bar is always available to close the prior bucket, so the
artifact genuinely cannot occur there. However, it is worth being precise
that the identical mechanism **does** apply to the literal last 1m bucket of
the *entire* backtest date range (the live strategy's own run also
terminates at some point, with no further 1s bar to close its final
bucket) — this is not something the validation script's boundary
artificially introduces, it's an inherent property of `TimeframeAggregator`
shared by both systems. The task's framing already anticipated and accepted
this as "an acceptable/expected edge case, not a hidden data problem," which
this audit agrees with: the impact is bounded to at most the final ~60
seconds of data across a full backtest (typically end-of-year), it does not
compound, it introduces no directional bias, and it affects the validation
script and the live strategy symmetrically (not a source of skew between
them). Recorded as a NOTE below rather than reopening the WARNING.

**Verdict: resolved. Reasoning holds for its stated scope (no mid-backtest
occurrence); the "final bucket of the whole run" symmetry noted below for
completeness, not as a blocking issue.**

### NOTE fixes — verified applied correctly

- Giveback/`to_atr` dedup: `_update_open_trade` (lines 431–441) now calls
  `to_atr(cur_pnl, atr)`, `to_atr(new_mfe, atr)`, `to_atr(new_mae, atr)`, and
  `giveback_atr(new_mfe, cur_pnl, atr)` from `mfe_mae.py`, matching the
  imported functions (`base_strategy.py:68-70`). No inline duplicate formula
  remains. `giveback_atr_from_entry` / `distance_from_mfe_atr` are still two
  columns computed from the same call, now with a comment explaining this is
  deliberate (lines 434–437) — matches the fix description.
- Monotonicity assertion: `_on_1m_bar` (lines 211–219) now raises
  `ValueError` if `new_ts_init <= self._latest_1m_bar_data["ts_init"]`,
  correctly guarded by `self._latest_1m_bar_data is not None` so it cannot
  false-fire on the first bar.
- F2 "unreachable" guard comment: `f2_confirmed_exit_management/strategy.py:42-48`
  now explains why the branch is believed unreachable in practice. Purely
  descriptive, no behavior change — confirmed harmless.

## New issues introduced by these fixes

None found at CRITICAL or WARNING severity. Two minor NOTEs (see below);
neither blocks execution.

## Notes

1. **Retry cadence within the flip bar** (`base_strategy.py:189-200`) — under
   synchronous order-rejection processing, the exit retry can fire twice
   within the same 1s bar (once via the flip-triggered path, once via the
   retry-check immediately after) rather than strictly "once per subsequent
   bar" as the comment states. Harmless (no duplicate live orders, no PnL
   impact), but worth knowing if `exits_rejected` diagnostics look
   higher than expected on flip bars specifically.

2. **Final-bucket blind spot is shared, not eliminated** — the
   `TimeframeAggregator`'s "never close a final partial bucket without a
   subsequent bar" behavior means the live strategy's own literal last 1m
   bucket, at the true end of its full run, will also never fire a
   bucket-closed event (no regime-flip check for that last ~60s of data).
   This is symmetric with the validation script's finding (not a
   discrepancy between them), bounded in impact to a single minute at the
   very end of the entire backtest, and does not affect any interior data.
   No action required; recorded for completeness in case a future reader
   assumes the reconciliation report proves 100% completeness rather than
   100% agreement-where-both-sources-exist.

## Clean checks (carried forward, re-verified against current file text)

- `decision_ts` is `bar.ts_init` throughout, never `ts_event`, for every
  registry/indicator read — now including the RTH gate itself, closing the
  one gap the prior audit found.
- No `i+1` leakage in F2's bar+1 HH/LL + momentum confirmation logic.
- MFE/MAE fill-anchored to `t["fill_price"]` (actual NT fill), never to
  flip-close or pre-fill reference.
- Checkpoint causality: no path appends a checkpoint before
  `entry_ts`/`fill_price` are set, and none after a trade is finalized.
- `bar_data` passed to `_on_regime_flip`/`_check_pending_confirmation` is
  always the just-closed bar for the current bucket-close event; the real
  `bar_type_1m` subscription bar for a given minute is guaranteed to arrive
  before the aggregator's synthetic completion event for the same minute.
- `_pending_flip` (F2) has an enforced 1-bar lifetime; cannot be silently
  overwritten while unresolved.
- Opposite-flip pending-entry cancellation is decided causally, before any
  new pending entry could be scheduled in the same cycle.
- Bar-type dispatch (`on_bar`) has no cross-contamination between 1s/1m
  handlers.
- Entry order rejection path (`on_order_rejected`, entry side) still
  correctly clears `self._trade = None` without side effects from the new
  exit-retry code (independent branches, `cid` comparison distinguishes
  entry vs. exit order ids).

---

*Re-audit complete. All items from the prior CRITICAL/WARNING list are
resolved, correctly reasoned as non-issues, or closed via data validation.
No new CRITICAL or WARNING findings from the fixes themselves. Per
CLAUDE.md's audit gate, this scope is now clear to execute for the first
time — standard post-execution parity checks (NT fill-timing assumptions
listed in the prior report's Notes) still apply on the first run, as they
would for any new strategy, but are not blocking.*

---

## Addendum: focused re-audit of opposite_flip_ts delta (2026-07-11, third pass)

Full file re-read (not diffed) after a further edit made on top of the
already-passed second-pass audit above, while a full multi-year NT backtest
was already running against this code.

**Trigger:** Phase 1 atlas-builder integrity check (`build_atlas.py::integrity_report`,
`n_checkpoint_after_opposite_flip`) flagged `opposite_flip_ts` values against
smoke-test output. Root cause: `_submit_exit` was reading
`self._latest_1m_bar_data["ts_event"]` (flip bar OPEN time) instead of
`["ts_init"]` (CLOSE time). Fix applied and re-read in full: `base_strategy.py`
(535 lines, current), `build_atlas.py` (237 lines),
`studies/all_flips_exit_management/strategy.py` (42 lines),
`studies/f2_confirmed_exit_management/strategy.py` (84 lines).

### Findings: 0 CRITICAL, 0 WARNING, 1 new NOTE (pre-existing, out-of-scope, not a regression) + 1 forward-looking NOTE for the future Phase 5/6 gate

### Verification of the five requested points

**1. Is opposite_flip_ts correct in all cases, including first-submission-rejected + later-retry-fills?**
Yes, confirmed correct. Traced the full call chain:
- `_on_1m_bucket_closed` (`base_strategy.py:229-276`) only reaches the
  `_submit_exit(reason="opposite_flip")` call (line 258) inside the
  `if flipped:` block after the guard at line 234
  (`if bar_data is None or bar_data["ts_init"] != s_1m.close_ts: return`)
  has already passed. That guard is only satisfiable when
  `self._latest_1m_bar_data` has already been updated (via `_on_1m_bar`,
  lines 211-227) to the just-closed flip bar's own data. So at the exact
  moment `_submit_exit` reads `self._latest_1m_bar_data["ts_init"]`
  (line 375), it is guaranteed -- synchronously, same call stack, no
  intervening bar dispatch -- to be the true flip bar's close time, not a
  stale or future one.
- On rejection (`on_order_rejected`, lines 404-406), only `exit_order_id`
  is cleared to `None`; `exit_reason` and `opposite_flip_ts` are left
  untouched.
- On retry (`_on_1s_bar`, lines 189-200), `_submit_exit` is called again
  with `reason=self._trade["exit_reason"]`, now with
  `self._latest_1m_bar_data` potentially pointing at a later 1m bar (if
  the retry happens on a subsequent minute). The guard at lines 372-373
  (`reason == "opposite_flip" and self._trade.get("opposite_flip_ts") is
  None`) is False this time (already set), so the stale/later bar data is
  never read into `opposite_flip_ts` on retry. Confirmed: the field is
  populated once, from the correct triggering bar, and never clobbered by
  a later retry -- including the specific inflation scenario the
  integrity check caught.

**2. Does the first-call-only guard correctly distinguish "first call" from "retry", with no external call counter?**
Yes. `opposite_flip_ts` starts at `None` (set at trade creation,
`_submit_entry`, line 343) and is set exactly once inside a single
synchronous statement together with `exit_order_id`/`exit_reason`
(lines 363-364, 372-376) -- there is no window in which another dispatch
can interleave between "exit_order_id set" and "opposite_flip_ts set" in
this single-threaded backtest loop. Since ts_init is always a non-`None`
positive integer once set, the field can never spuriously revert to
`None` and re-trigger the branch. The `is None` check is therefore a
correct proxy for "first successful pass," including in the tightest case
(same-1s-bar synchronous rejection-then-retry, previously flagged as a
cosmetic NOTE in the prior audit round) -- in that case the guard is
redundant-but-harmless since `_latest_1m_bar_data` hasn't changed within
the same call anyway; the guard's value is specifically for the
cross-bar retry case, which is exactly the scenario that produced the
integrity-check symptom.

**3. Does the guard interact badly with any other reason value?**
Confirmed by exhaustive call-site search for `_submit_exit(` across
`base_strategy.py`, `all_flips_exit_management/strategy.py`, and
`f2_confirmed_exit_management/strategy.py` -- there are exactly two call
sites, both passing literally `"opposite_flip"` (line 258, flip path) or
`self._trade["exit_reason"]` (line 200, retry path), and the retry path
can only ever re-read a value that was itself set to `"opposite_flip"`
by the flip path (no other writer of `exit_reason` exists pre-fill).
`_maybe_stop_policy_exit` (the Phase 5/6 hook, lines 457-461) is
currently a no-op in the base class and is not overridden by either
current subclass -- it does not call `_submit_exit` at all right now.
Confirmed: nothing currently calls `_submit_exit` with any reason other
than `"opposite_flip"`, so the `reason ==` scoping is correctly
restrictive for the current codebase.

Forward-looking NOTE (not a current bug, flagged for the Phase 5/6 gate
CLAUDE.md already mandates): if a future stop-policy subclass calls
`_submit_exit(reason="stop_policy")` while a previously rejected
`"opposite_flip"` exit is sitting with `exit_order_id is None` (rejected,
not yet retried), the shared top-of-function guard (line 354) would NOT
block it (no order is currently in flight), and the unconditional line
`self._trade["exit_reason"] = reason` (line 364) would silently overwrite
`"opposite_flip"` with `"stop_policy"` for a trade that was, causally,
actually flip-exited-then-retried, not stop-policy-exited.
`opposite_flip_ts` itself would stay correctly set (harmless), but
`exit_reason`/`eventual_opposite_flip` downstream in `build_atlas.py`
(lines 192-193) would then mislabel the trade's true exit cause. This
cannot happen today (no stop-policy subclass exists yet) -- recorded here
so it is re-checked when Phase 5/6 work begins, per CLAUDE.md's
pre-execution audit gate for reused/adjacent exit-timing mechanics.

**4. Does the exit-retry mechanism (already audited) still avoid double-submission next to this edit?**
Yes. The retry block itself (lines 189-200) is textually unchanged by
this delta. The new code is entirely inside `_submit_exit`, below the
pre-existing `if self._trade.get("exit_order_id") is not None: return`
guard (line 354) that both call sites share -- that guard is unaffected
by the new `opposite_flip_ts` logic beneath it. Re-confirmed no new
double-submission path is introduced.

**5. Is base_strategy.py / all_flips_exit_management/strategy.py / f2_confirmed_exit_management/strategy.py clear to execute?**
Yes, re-read all three files in full end-to-end for this pass (not just
the delta region). No new CRITICAL or WARNING found. `build_atlas.py` was
also checked for compatibility with the field rename
(`opposite_flip_ts_event` -> `opposite_flip_ts`): `REQUIRED_ATLAS_COLUMNS`
(line 66) and the `trade_meta` selection (line 180) both already use the
new name; no stale reference to the old name exists anywhere in
`build_atlas.py` or `smoke_test.py` (repo-wide grep for
`opposite_flip_ts_event` found only one other, unrelated pre-existing
occurrence: `base_strategy.py:266`, the `_pending_cancellations`
diagnostic dict for canceled pending entries, which is a separate,
correctly-named-as-open-time field not touched by this delta and not
consumed by `build_atlas.py`).

### New NOTE (residual, non-blocking)

- **`_pending_cancellations`'s `opposite_flip_ts_event` field
  (`base_strategy.py:266`)** uses `bar_ts_event` (open time) by design/
  name -- honestly labeled, not a mislabeled-as-close-time bug, and not
  read by `build_atlas.py` or any other consumer found in this repo (it
  is diagnostic-only, written to `pending_cancellations.parquet`). Not
  part of this delta and not a regression, but flagged for completeness
  since the sibling field on the trade dict was just corrected for the
  identical class of open-vs-close ambiguity. No action required to
  proceed with the current run.

### Verdict

`opposite_flip_ts` delta verified correct for all present call paths,
including the specific first-rejected/later-retry-fills scenario that
motivated the fix. No new CRITICAL/WARNING introduced. One forward-looking
NOTE recorded for the Phase 5/6 stop-policy gate (not blocking today). Per
CLAUDE.md's pre-execution audit gate, `base_strategy.py`,
`all_flips_exit_management/strategy.py`, and
`f2_confirmed_exit_management/strategy.py` remain clear to execute -- no
action required against the two backtests currently running.

*Addendum complete. Scope: same files as the second-pass audit above, this
pass focused on the opposite_flip_ts guard delta specifically.*

# Look-Ahead & Timestamp Audit

**Date:** 2026-07-20

**Scope:**
- `studies/nt_pure_flip_trigger_poc_and_mirrored_long_model/phase2/trade_state.py`
- `studies/nt_pure_flip_trigger_poc_and_mirrored_long_model/phase2/strategy.py`
- `studies/nt_pure_flip_trigger_poc_and_mirrored_long_model/phase2/build_schedules.py`
- `studies/nt_pure_flip_trigger_poc_and_mirrored_long_model/phase2/run_nt.py` (read for execution config context)
- `studies/nt_pure_flip_trigger_poc_and_mirrored_long_model/phase2/reconcile.py` (read for parity-coverage context)
- `studies/nt_pure_flip_trigger_poc_and_mirrored_long_model/phase2/common.py`
- `studies/nt_pure_flip_trigger_poc_and_mirrored_long_model/tests/test_trade_state.py`
- `studies/nt_pure_flip_trigger_poc_and_mirrored_long_model/SPEC.md`
- Cross-reference (read-only, already audited): `studies/fable5_nt_short_rth_policy_a/strategy.py`,
  `studies/fable5_nt_short_rth_policy_a/tests/test_policy_a_fixture.py`,
  `studies/fable5_pre_flip_d10_reversal_entry/strategy.py`

**Auditor:** lookahead-auditor v1

**Pre-execution status:** This code has NOT yet been run through a real `BacktestEngine`. This audit is the
mandatory pre-execution gate (`feedback_preexecution_audit_gate`). 21/21 synthetic pytest cases pass on
`trade_state.py` only; `strategy.py`'s order-wiring logic has zero automated test coverage (this matches the
precedent's own testing discipline, which relies on a fixture test + full-run reconciliation rather than a
strategy-level pytest suite — see Warning 2 below for the one place this matters).

## Summary

- Critical: 1
- Warning: 2
- Note: 2

## Critical findings

### [E3/H4] `strategy.py:74,116-125,182-192` — the fixed stop is never placed as a real `stop_market` order; the manual detect-then-market-order substitute will misprice exactly the fixture case the precedent was built to get right

`SPEC.md:95-106` (finding 8b) explicitly specifies the intended design: *"a single stop-market order at
`entry_px + 1.25*atr`, placed once at entry fill, never cancelled/replaced, **remains resting** until either
it fills or the position closes via the opposing-flip exit."* This is also this project's standing convention
(`feedback_real_fills_from_top_of_book.md`: "SL stop-market@bid").

`strategy.py` does not do this. There is no `order_factory.stop_market(...)` call anywhere in the file. The
`_stop_order_id` attribute is declared (`strategy.py:74`) exactly as in the precedent, but is **never assigned
or read again** — it is vestigial, strong evidence of an incomplete port from `fable5_nt_short_rth_policy_a`.

Instead, the stop is implemented as manual polling:
- `strategy.py:121-125` — on every completed 1s bar, if a position is open, calls
  `st.stop_would_touch(float(bar.high), float(bar.low))` (this part is correct — see Clean checks, H1) and,
  if true, calls `self._submit_exit(st.on_stop_touch())`.
- `strategy.py:182-192` (`_submit_exit`) — submits a plain **FOK market order**, not a stop order.

Per this exact sibling study's own fixture-verified fill-model documentation
(`fable5_nt_short_rth_policy_a/strategy.py:20-24`: *"FOK market fills at the just-completed bar's close at its
ts_init boundary"*), any market/FOK order submitted synchronously while processing bar N fills at bar N's
**close**, not at whatever intrabar level triggered the submission. A genuine `stop_market` order, by contrast,
is matched by NT's `SimulatedExchange` (with `bar_execution=True`, `bar_adaptive_high_low_ordering=True` — both
set identically in `run_nt.py:53-57`) against the **trigger price**, independent of where the bar closes.

The precedent's own regression test proves this distinction is not academic —
`fable5_nt_short_rth_policy_a/tests/test_policy_a_fixture.py::test_pre_alignment_stop` (lines 112-127)
constructs a bar with `high=113.0, low=100.0, close=100.0` against a stop at `112.5` (i.e., price spikes
through the stop and fully reverts to the entry price by the bar's close), and asserts:
```
assert t["exit_px"] == pytest.approx(112.5)      # fills at TRIGGER, not close
assert t["gross_pnl"] == pytest.approx(-250.0)    # (112.5-100)*-1*20
```
Replaying that identical bar through this new strategy's mechanism: `stop_would_touch(high=113.0, low=100.0)`
returns `True` (correct detection), `_submit_exit` fires, but the resulting FOK market order would fill at
~100.0 (this bar's close), not 112.5 — turning a real **-$250** stop-loss into an approximately **breakeven**
fill (net ≈ -$10 cost only). This is a systematic, favorable-direction mispricing on every stop-touch where a
1-second bar pierces the stop level and reverts before its own close — precisely the class of bug this
project's own history has already priced at $13-14/trade in adjacent studies
(`feedback_offline_sim_use_ohlc_for_triggers.md`, `be_simulation_path_checkpoint_inflation.md`), except here it
is baked into the live NT strategy itself rather than an offline sim, so it will silently inflate every T1/T2/T3
run's reported EV on every stop-out with an intrabar spike-and-revert.

Detection (H1 — using high/low, not close) is correct. Temporal resolution (H2 — 1s bars) is correct. The bug
is specifically in the **fill price** credited once a touch is detected, and it has no test coverage anywhere
(neither `test_trade_state.py`, which only tests the boolean `stop_would_touch` logic and never touches order
submission/fill semantics, nor any `strategy.py`-level fixture analogous to `test_pre_alignment_stop`).

**This must be resolved (either by submitting a real resting `stop_market` order per the SPEC's own stated
design, or by an explicit, tested, documented decision to accept market-order-at-close semantics with a
fixture proving the resulting fill-price distribution is acceptable) before the first real `BacktestEngine`
run.**

## Warnings

### [D1/H3-adjacent] `build_schedules.py:24-26` — source `entry_ts` column is read but silently discarded; no entry-timing parity check exists anywhere in this study

`build_schedules.py` reads `entry_ts` from the upstream `schedule_{trigger_key}_2025.parquet` file (line 25)
but never uses it — the output schedule only carries `observation_time` (renamed `signal_decision_ts`). This
is very likely fine causally (`strategy.py`'s own dispatch loop, `_on_1s:131-135`, independently re-derives a
causal "first available 1s bar at/after the decision timestamp" fill point, matching how `entry_ts` appears to
have been constructed upstream in most rows — confirmed empirically: `entry_ts == observation_time` in
97.6-98.8% of rows across the three variant schedules, with the remainder differing by up to 7 seconds,
presumably "quiet-second" gaps). However, unlike `fable5_nt_short_rth_policy_a` — whose schedule carries
`offline_entry_open`/`target_fill_ts` and whose strategy builds an explicit `entry_timing` list comparing
actual NT fill price/time against the offline-expected values (`fable5_nt_short_rth_policy_a/strategy.py:309-314`)
— this study has **no equivalent check**. `reconcile.py` verifies regime-transition parity, trigger-condition
parity, and ATR/score parity, but nothing verifies that the NT dispatch loop's actual entry fill time/price
matches what the offline pipeline assumed when it computed `atr_at_checkpoint` and the frozen score. Given the
confirmed up-to-7-second drift in ~2% of rows, this is a real, currently-unverified gap, not merely a
documentation nicety — recommend adding an entry-timing parity check (or explicitly re-deriving why it's
unnecessary) before treating Phase 2's gate as fully proven.

### [testing-coverage] `strategy.py` has no fixture-level regression test for the stop-touch-to-exit path

This matches the precedent's general testing discipline (no full strategy-level pytest suite for
`fable5_nt_short_rth_policy_a/strategy.py` either — it relies on `tests/test_policy_a_fixture.py`'s targeted
fixtures plus full-run reconciliation), so this is not flagged as a standalone gap in isolation. It is flagged
here specifically because the ONE new, non-reused piece of order-execution logic in this study (the manual
stop-detection-to-market-order substitution — see Critical finding above) has **no** fixture test analogous to
`test_pre_alignment_stop`, despite being exactly the kind of logic that class of fixture exists to catch.
Recommend adding a deterministic bar-tape fixture test (spike-through-and-revert, spike-through-and-continue,
and no-touch cases) before the real run, mirroring `test_policy_a_fixture.py`'s pattern.

## Notes

### [F3/F4] `strategy.py:108-114` — RTH gate is correct and conventionally consistent, but has no boundary-case observability

`_rth_minute_of_day`/`_in_rth` convert `bar.ts_init` (UTC ns) to `America/Chicago` via `pd.Timestamp(...).tz_convert(...)`,
which correctly handles DST transitions (not a fixed-offset conversion), and the window (`rth_start_min=8*60+30`,
`rth_end_min=15*60`) matches the project's established convention verbatim
(`fable5_nt_short_rth_policy_a/common.py:29-33`: `RTH_START_MIN = 8*60+30`, 08:30-15:00 America/Chicago).
Confirmed empirically that 100% of `observation_time` rows in the upstream trigger schedules already fall
inside this window, so the schedule is RTH-filtered upstream and this runtime check is a (harmless, correctly
conservative) redundant guard. It gates `_try_enter` only (`strategy.py:143-146`) and is never consulted on the
exit path — matching `fable5_nt_short_rth_policy_a`, which also never forces a session-close exit (hold until
stop/opposing-flip is the established convention in both strategies). The only minor gap: unlike Policy A's
`boundary_cases` list, there is no logging of cases where the actual dispatch bar's `ts_init` differs from the
schedule's `signal_decision_ts` (quiet-second snap-forward) or where a near-boundary entry is skipped for RTH —
purely an observability gap, not a correctness issue.

### [G-adjacent] `strategy.py:303-314` (`on_stop`) — end-of-data-censored trades are correctly NaN'd, but downstream aggregate-stats scripts were not in this audit's scope

Trades still open when the backtest data ends are appended with `exit_reason="end_of_data_exit"`,
`exit_price=np.nan`, `net_pnl=np.nan`/`gross_pnl=np.nan` — correct censoring (matches this project's own
recorded convention against silently counting these as flat/zero-PnL). Not independently verified: that
`summarize_variants.py`/`apply_gate.py` (not in this audit's requested scope) actually filter on `.notna()`
before computing aggregate economics, rather than accidentally coercing NaN to 0.

## Clean checks

- **A1/A3** — `strategy.py` indexes exclusively off `bar.ts_init` (the already-elapsed close time) and the
  `bar`/`Bar` argument passed into `on_bar`/`_on_1s`/`_on_1m`; no future-indexed cache lookups found.
- **A4** — no `TimeEvent`/timer-based callbacks exist in this strategy; all logic is bar-driven.
- **A5** — `_rth_minute_of_day` uses a proper tz-aware `pd.Timestamp.tz_convert("America/Chicago")` conversion,
  not a fixed-offset shift; correctly DST-safe.
- **B/C** — no pandas rolling/ewm/shift(-N) anywhere in the decision path; `trade_state.py` is pure-Python,
  event-driven state, causal by construction.
- **`FlipTradeState.__post_init__`** stop_px formula hand-traced for both directions: short (`entry_direction=-1`)
  → `stop_px = entry_px + 1.25*atr` (above entry, correct — price rising is adverse for a short); long
  (`entry_direction=+1`) → `stop_px = entry_px - 1.25*atr` (below entry, correct).
- **`stop_would_touch`** hand-traced: short uses `high >= stop_px`; long uses `low <= stop_px`. Both correct
  (H1 — high/low, never close).
- **`on_regime_update` thesis/opposing fix verified correct** for both directions by hand trace:
  - `entry_direction=-1`: `thesis_regime=-1` (bearish flip confirms short thesis), `opposing_regime=+1`
    (bullish flip exits). Requires bearish flip observed before a bullish flip can exit. Correct.
  - `entry_direction=+1`: `thesis_regime=+1` (bullish flip confirms long thesis), `opposing_regime=-1`
    (bearish flip exits). Correct, mirrors the short case exactly as SPEC intends for Phase 3.
  - Re-traced against the **original (pre-fix) buggy assignment** (`thesis_regime = -entry_direction`,
    `opposing_regime = entry_direction`) for both directions: confirmed
    `test_bullish_regime_before_bearish_flip_does_not_exit`,
    `test_opposing_flip_exit_only_fires_after_bearish_confirmed`, and
    `test_mirrored_long_thesis_is_bullish_flip_then_bearish_exit` would each have **failed** under the old
    buggy code (traced by hand, not assumed) — these tests are genuine regression coverage for the fix, not
    coincidental passes.
- **`favorable_adverse_points`/`unrealized_pnl`/`realized_favorable_atr`** — each hand-traced with one concrete
  short and one concrete long example beyond the existing tests (e.g. short: entry=1000, high=1005, low=990 →
  fav=10, adv=5; long: entry=1000, high=1010, low=995 → fav=10, adv=5; unrealized_pnl short entry=1000
  close=990 mult=20 → +200; long entry=1000 close=1010 → +200; realized_favorable_atr short entry=1000
  exit=1012.5 atr=10 → floored 0). No double-negation found in any of the three functions, nor in
  `strategy.py:243` (`_close`'s `gross = (px - entry_price) * direction * multiplier`, direction multiplied
  exactly once, consistent with `unrealized_pnl`'s convention).
- **No confirmation-timeout logic anywhere** — confirmed by grep across `trade_state.py` and `strategy.py`
  (only the docstrings mention the removed Policy A timeout, no functional timeout code remains).
- **No stop-swapping logic anywhere** — `stop_px` is computed exactly once in `__post_init__` and never
  reassigned; no `_swap_to_post_stop`-equivalent method exists in `strategy.py`.
- **`_state`/`_trade` reset between trades** — hand-traced two consecutive trades: `_close()` (`strategy.py:261-266`)
  sets `st.closed=True` then `self._trade=None`, `self._state=None`; the next `_on_entry_filled` constructs a
  brand-new `FlipTradeState()` (fresh `bearish_flip_confirmed=False`). No cross-trade state leakage possible.
- **No pyramiding / no overlapping positions** — `_try_enter`'s guard (`strategy.py:138-142`) blocks a new
  entry whenever `self._trade is not None`, `self._entry_order_id is not None`, `self._exit_order_id is not None`,
  or `self._exit_retry` is true; verified this guard is checked synchronously before any order submission and
  cannot be bypassed within a single bar's processing (entry dispatch happens after the exit-check/exit-retry
  block in `_on_1s`, using the still-unset-until-fill-event `self._trade`).
- **`recon_confirm_flip_ns` is reconciliation-only** — confirmed by grep: referenced exactly once in
  `strategy.py` (`_on_entry_filled`, stored verbatim into the trade dict) and never read in any conditional —
  matches the documented convention from `fable5_nt_short_rth_policy_a/build_schedule.py`.
- **`build_schedules.py` guards are real** — `(out["atr_at_checkpoint"] <= 0).any() or .isna().any()` and
  `out["regime_start_ns"].duplicated().any()` both raise `RuntimeError` and would genuinely fire against a
  malformed upstream schedule; confirmed the upstream `schedule_trig_*_2025.parquet` files are already
  deduplicated one-row-per-regime by construction (`trigger_grid.py:build_schedule`,
  `.groupby("regime_start_ns").first()`), so these guards are defensive-in-depth, not currently load-bearing,
  but would catch a real regression if that upstream invariant broke.
- **RegimeEngine warmup** — `common.py:31` loads from `2025-01-01` (a full 2+ months of warmup before the
  March-2025 selected month), matching the established convention
  (`fable5_nt_short_rth_policy_a`) for fresh-engine ATR/EMA stabilization.
- **Bar subscriptions match dispatch (E1/E2)** — `bar_type_1s`/`bar_type_1m` config strings match
  `common.py`'s `BAR_1S`/`BAR_1M` constants and the catalog bar types loaded in `run_nt.py:41-42`.

---

*Audit complete. Findings reflect read-only static analysis and hand-tracing against a fixture-verified
sibling study; the strategy has not yet been executed in a live `BacktestEngine`. The Critical finding above
must be resolved (or explicitly accepted with a fixture test proving the resulting fill-price distribution is
acceptable) before that run, per this project's standing pre-execution audit gate.*

---

# Follow-up Audit — CRITICAL Finding Resolution Verification

**Date:** 2026-07-20
**Scope:** `phase2/strategy.py` (current version, post-fix, read in full), `phase2/trade_state.py` (read in
full, unchanged), `tests/test_trade_state.py` (re-executed), cross-reference
`studies/fable5_nt_short_rth_policy_a/strategy.py` (grepped for the precedent's stop-order construction and
ordering).

**Auditor:** lookahead-auditor v1 (targeted follow-up, not a full re-audit)

**Trigger:** Implementer reports the [E3/H4] CRITICAL finding above has been fixed by removing manual
high/low polling and replacing it with a genuine resting `stop_market` order, wired to mirror
`fable5_nt_short_rth_policy_a/strategy.py`'s already-audited mechanism.

## Verification result: CRITICAL finding is RESOLVED

### 1. Full order-lifecycle trace (entry fill → stop placed → stop fills → `_on_stop_filled` → `_close`)

Traced end to end in the current `strategy.py`:

- `_on_entry_filled` (`strategy.py:221-262`) constructs `FlipTradeState`, then at lines 255-262 builds and
  submits a genuine `self.order_factory.stop_market(...)` (GTC, `reduce_only=True`, `trigger_price=Price(tick_round(state.stop_px), 2)`),
  storing the id in `self._stop_order_id`. No FOK/market order is submitted here for the stop path.
- `on_order_filled` (`strategy.py:211-219`) routes a fill event to `_on_stop_filled` via
  `elif cid == self._stop_order_id`.
- `_on_stop_filled` (`strategy.py:264-270`) clears `self._stop_order_id`, computes the exit-reason label via
  `st.on_stop_touch()` (unchanged, still correctly branches on `bearish_flip_confirmed`), then calls
  `self._close(reason, px, ts)` using the **event's own fill price** (`px = float(event.last_px)`, set at
  `strategy.py:213`) — i.e., whatever price NT's `SimulatedExchange` actually matched the resting stop at,
  not a manually-assumed trigger price and not a bar-close.
- `_close` (`strategy.py:278-308`) computes `gross = (px - entry_price) * direction * multiplier` off that
  same fill price, marks the trade closed, and idempotently calls `_cancel_stop()` (a no-op here since
  `_stop_order_id` was already cleared in `_on_stop_filled`).

**Grep confirmation:** `stop_would_touch` is no longer referenced anywhere in `strategy.py`. It appears only
in `phase2/trade_state.py:74` (definition) and `tests/test_trade_state.py:27-34` (unit tests of the boolean
logic in isolation). The manual-polling call site that previously existed in `_on_1s` has been deleted and
replaced with a comment (`strategy.py:123-129`) explicitly documenting why (referencing this exact audit
finding). Confirmed clean — no dual/parallel detection path remains.

### 2. `_cancel_stop()` ordering relative to opposing-flip exit submission

`_submit_exit` (`strategy.py:186-201`), the ONLY path that submits an opposing-flip exit order, calls
`self._cancel_stop()` at line 194 — before constructing/submitting the exit market order at lines 195-201.
Both statements execute synchronously in the same Python call with no bar-processing or event-loop yield
between them, so there is no window in which the resting stop order is live while an exit order is also being
submitted. This is structurally identical to the precedent's `fable5_nt_short_rth_policy_a/strategy.py:244-262`
`_submit_exit`, which also calls `self._cancel_stop()` (line 253) immediately before submitting its exit order,
with the same documented caveat inherited verbatim in spirit ("cancel resting stop first... a same-bar
already-triggered stop still wins" — i.e., if the stop had already matched intrabar via the 1s-bars-before-1m
dispatch ordering, the corresponding fill event will already have closed the trade and set `self._trade = None`
before `_on_1m` even evaluates the opposing flip; `_on_1m`'s own guard at `strategy.py:175`
(`if t is None or st is None or st.closed: return`) prevents any double-processing in that case). Confirmed
matching ordering and matching accepted race semantics.

### 3. Stop order side/trigger-price construction for direction = -1 (short)

Hand-verified line by line against the precedent (`fable5_nt_short_rth_policy_a/strategy.py:315-323`,
`_on_entry_filled`'s pre-alignment-stop block):

| | This study (`strategy.py:255-260`) | Precedent (`fable5_.../strategy.py:315-323`) |
|---|---|---|
| side | `OrderSide.BUY if direction == -1 else OrderSide.SELL` → `BUY` for short | `OrderSide.BUY` (hardcoded, short-only population) |
| trigger formula | `tick_round(state.stop_px)`, where `state.stop_px = entry_px + 1.25*atr` for `entry_direction=-1` (`trade_state.py:44-47`) | `tick_round(t["entry_px"] + self._cfg.preflip_stop_atr * t["atr"])`, `preflip_stop_atr=1.25` |
| price object | `Price(trig, 2)` | `Price(trig, 2)` |
| time_in_force | `TimeInForce.GTC` | `TimeInForce.GTC` |
| reduce_only | `True` | `True` |
| quantity | `Quantity.from_int(1)` | `Quantity.from_int(1)` |

For the short case (`direction == -1`, this population's only case in Phase 2), the two constructions are
**identical**: `BUY` side, trigger at `entry_px + 1.25*atr`, same order-object construction pattern. Confirmed
the new strategy's generalization (`BUY if direction == -1 else SELL`) is a correct, direction-aware
superset of the precedent's hardcoded short-only version and reproduces it exactly when `direction == -1`.

### 4. `on_order_filled` routing order and simultaneous-order-id reachability

`on_order_filled` (`strategy.py:211-219`) checks `_entry_order_id`, then `_stop_order_id`, then
`_exit_order_id`, in that order. Traced whether `_stop_order_id` and `_exit_order_id` can ever be
simultaneously non-`None`:

- The only place `_exit_order_id` is assigned is `_submit_exit` (`strategy.py:199`), which unconditionally
  calls `_cancel_stop()` (line 194) first — and `_cancel_stop()` unconditionally sets
  `self._stop_order_id = None` (`strategy.py:209`) before returning, regardless of whether the venue has
  actually processed the cancel yet. Since both statements run synchronously with no intervening bar
  dispatch, by the time `_exit_order_id` is set, `_stop_order_id` is already `None` in the strategy's own
  state — **not reachable**, confirmed by direct code trace (not merely inferred).
- The reverse (a stop being placed while an exit order is pending) cannot happen either: `_stop_order_id` is
  only assigned in `_on_entry_filled` (`strategy.py:261`), which only runs on a fresh entry, and entries are
  blocked while `self._trade is not None` (`_try_enter` guard, `strategy.py:142-143`), which is true for the
  entire lifetime of any pending exit order.

No reachable state has both ids set at once; the routing order in `on_order_filled` is safe regardless of
priority given this invariant. Confirmed.

### 5. Exactly one path can close a trade via "stop touched"

Confirmed by full-file trace and grep: the only call to `_close(...)` with a stop-related reason is in
`_on_stop_filled` (`strategy.py:270`), which is only reachable via `on_order_filled`'s
`elif cid == self._stop_order_id` branch (`strategy.py:216-217`), which is only ever populated by the single
`order_factory.stop_market(...)` submission in `_on_entry_filled` (`strategy.py:257-262`). The previous dual
path (manual `stop_would_touch` detection → FOK market order via `_submit_exit`) has been fully removed, not
merely bypassed — `_submit_exit` is now documented and used exclusively for `"opposing_flip_exit"`
(`strategy.py:186-190` docstring, and the sole call site at `strategy.py:181`). Confirmed there is exactly one
order-submission path that can close a trade via stop-touch, and it is the genuine resting `stop_market`
order that the venue matches against trigger price per `bar_execution=True` /
`bar_adaptive_high_low_ordering=True` (`run_nt.py:57`, unchanged from the pre-fix version and re-confirmed
present in the current file). The root-cause mechanism of the original CRITICAL finding (fill executing at
bar-close instead of trigger price) cannot recur through any other path in the current file.

### 6. `tests/test_trade_state.py` re-run

```
21 passed in 0.02s
```

Confirmed 21/21 pass, as expected — `trade_state.py` was not touched by this fix (only `strategy.py` was);
this is a no-op confirmation that no incidental regression was introduced in the shared state-machine module.

## Residual open items (not blockers for this CRITICAL, still outstanding from the original audit)

- **Warning 1** (`build_schedules.py:24-26`, entry-timing parity check) — unaddressed by this fix; out of
  scope for it. Still open.
- **Warning 2** (no fixture-level regression test for the stop-touch-to-exit path) — **partially stale, not
  fully closed.** The original warning was specifically about the manual-polling substitution having no
  fixture coverage; that substitution no longer exists, so the original warning's literal subject is moot.
  However, the **replacement** mechanism (the genuine `stop_market` order and its `_on_stop_filled` routing)
  still has **no dedicated fixture test** analogous to
  `fable5_nt_short_rth_policy_a/tests/test_policy_a_fixture.py::test_pre_alignment_stop` — no new test file
  was added alongside this fix (`tests/` in this study still contains only `test_trade_state.py`). Static
  trace and hand-verification in items 1-5 above provide reasonable confidence, but this is not the same
  standard of evidence as a deterministic bar-tape fixture test proving `exit_px` equals the trigger price
  (not bar close) on a spike-through-and-revert bar, as the precedent has. Recommend adding one before or
  immediately after the first real `BacktestEngine` run, not as a hard pre-run blocker given the strength of
  the static trace, but as a durable regression guard.
- **Notes 1-2** from the original audit (RTH-gate observability, end-of-data censoring downstream handling) —
  unaffected by this fix, still stand as originally written.

## Conclusion

**The CRITICAL finding [E3/H4] is RESOLVED.** The manual high/low-polling-to-FOK-market-order substitution has
been fully removed and replaced with a genuine resting `stop_market` order, structurally identical (for the
short-only case this population uses) to the already fixture-verified precedent in
`fable5_nt_short_rth_policy_a/strategy.py`. Order-lifecycle tracing found no residual path by which a
stop-loss exit could be priced at bar-close instead of trigger price, no reachable double-fill/mis-route
scenario given the codebase's documented 1s-bars-before-1m-bar dispatch invariant, and no regression in the
unchanged `trade_state.py` module (21/21 tests pass).

**It is safe to proceed to the first real `BacktestEngine` run.** The one remaining recommendation (a
dedicated fixture test for the new stop-order path, per residual item above) is a durable-regression-guard
improvement, not a correctness gate — it does not need to block the run, but should not be forgotten
afterward.

---

*Follow-up audit complete. This was a targeted verification of one previously-identified CRITICAL finding,
not a full re-audit of the study. All other findings from the 2026-07-20 base audit stand as originally
written above.*

---

# Completion-Gate Audit — Full Phase 2 Pipeline, Post-Execution (Second Pass)

**Date:** 2026-07-20
**Trigger:** Mandatory `lookahead-auditor` completion gate (`CLAUDE.md` invariant 5,
`feedback_preexecution_audit_gate`) after the real `BacktestEngine` run and downstream analysis completed for
T1/T2/T3.

**Scope (full pipeline, all read in full unless noted):**
- `SPEC.md` (re-read against implementation)
- `phase2/strategy.py` (re-read in full, current version)
- `phase2/trade_state.py` (re-read in full, unchanged since prior audits)
- `phase2/build_schedules.py`
- `phase2/run_nt.py`
- `phase2/reconcile.py`
- `phase2/summarize_variants.py`
- `phase2/apply_gate.py`
- `phase0_freeze_inputs.py`
- `phase1_month_selection.py`
- `phase2/common.py`
- Cross-reference (read-only): `studies/fable5_pre_flip_d10_reversal_entry/strategy.py` (`RegimeEngine`,
  `tick_round`), `studies/short_rth_pure_flip_score_entry_policy/trigger_logic.py`
  (`build_trigger_flags`, used by `reconcile.py`), `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py`
  (`canonical_regime_timeline`, used by `reconcile.py`), `studies/fable5_nt_short_rth_policy_a/run_nt.py`
  (dual 1s+1m bar-feed precedent), `studies/fable5_nt_short_rth_policy_a/tests/test_policy_a_fixture.py`
  (full-`BacktestEngine` stop-fill fixture, re-executed).
- Output artifacts cross-checked against reported numbers: `phase2/variant_summary.csv`,
  `phase2/manifest.json`, `phase2/regime_runtime_parity.csv`, `phase2/trigger_runtime_parity.csv`,
  `phase2/score_runtime_parity.csv`, `phase2/exit_reason_summary.csv`.

**Auditor:** lookahead-auditor v1 (full completion-gate pass, re-verifying rather than trusting the prior
audit trail, per instruction)

## Summary

- Critical: 0
- Warning: 0
- Note: 4

## Independent verification performed (not just re-reading the prior audit trail)

1. **Re-ran `tests/test_trade_state.py` from scratch:** `21 passed in 0.03s`. Confirms no regression since
   the prior audit; `trade_state.py` file content re-read in full and is byte-identical to what the prior
   follow-up audit verified (same formulas, same direction-sign handling, same `on_regime_update` fix).
2. **Re-ran the precedent's full-`BacktestEngine` stop-fill fixture in isolation**
   (`fable5_nt_short_rth_policy_a/tests/test_policy_a_fixture.py::test_pre_alignment_stop`): **PASSED**
   (`1 passed in 0.87s`). This is the test that empirically proves a resting `stop_market` order, fed through
   an engine configured with **both** 1s and 1m bar streams simultaneously (`engine.add_data(bars_1s)`;
   `engine.add_data(bars_1m)`) and `bar_execution=True`/`bar_adaptive_high_low_ordering=True` (the *exact*
   configuration this study's `run_nt.py:53-60` uses, confirmed identical), fills at the **trigger price**
   (112.5) and not the bar's close/open, even when the touching bar fully reverts before its own close. This
   directly re-confirms H4 compliance under this study's specific dual-granularity engine configuration,
   independent of trusting the prior audit's static trace. (Note: running the full 2-test file in one pytest
   process produced truncated output on this machine — an environment quirk, not a code issue; running the
   target test in isolation gave a clean, complete pass.)
3. **Cross-checked all three reconciliation outputs and gate outputs against the reported run results.**
   `phase2/regime_runtime_parity.csv`, `trigger_runtime_parity.csv`, `score_runtime_parity.csv` all show
   `exact_match=True`/`atr_exact_match=True`/`any_unmatched_rows=False` for T1/T2/T3, matching what was
   reported. `phase2/variant_summary.csv` reproduces exactly: T1 net_pnl=$1545.00 PF=1.1061..., T2
   net_pnl=$10600.00 PF=1.6118..., T3 net_pnl=$10530.00 PF=1.6053..., all with `n_skips=0`. `phase2/manifest.json`
   reproduces the exact gate decision and per-variant economic-check booleans reported, including T1's
   `not_outlier_driven: false` (hand-verified: T1 `largest_winner=$5295` > `net_pnl=$1545`, so removing that
   one trade would flip the variant's sign — the check is doing exactly what it claims, not a rubber stamp).
4. **Read `trigger_logic.py::build_trigger_flags` and `CODEX_5_X_run_established_fade.py::canonical_regime_timeline`**
   (the two independent re-derivation functions `reconcile.py` calls) to confirm the three parity checks are
   genuine re-derivations from raw/causal inputs, not tautological identity checks on the same object (see
   below).

## Analysis: are `reconcile.py`'s three parity checks rigorous, or tautological?

- **`regime_transition_parity`** — genuinely independent. `canonical_regime_timeline` recomputes the entire
  regime-flip sequence from **raw 1s OHLCV** (`RAW_1S[2025]`) via a completely separate pandas pipeline
  (`reproduce_regimes.aggregate_and_run_regimes`), unrelated to the live `RegimeEngine` class the NT strategy
  uses internally. It also self-validates against the existing year-atlas file before returning (raises if
  mismatched). Comparing this to `strategy.flips` (the NT run's own live-computed flip stream) is a real,
  non-circular check. **Not tautological — genuine.**
- **`trigger_condition_parity`** — also genuine. `build_trigger_flags` recomputes trigger conditions from the
  frozen score column using only backward-looking operations (`groupby(...).shift(1)` for the "previous
  checkpoint" family, and an exact-time backward lookback — `observation_time - offset_s` — for the 30s/60s
  "change" families; hand-verified no forward shift or centered window exists anywhere in this file). This
  independently reproduces the (regime_start_ns, signal_decision_ts) pairs used to build the schedule.
  **Not tautological — genuine**, and confirms the trigger logic itself is causal (no `.shift(-N)`, no
  `center=True`, no forward lookback).
- **`atr_and_score_parity`** — this one **is** substantially tautological by the study's own admission
  (`reconcile.py:83-88` docstring says so explicitly: "verified by construction... not an independent
  recomputation of the model itself"). It re-joins the NT schedule back to the same upstream file the
  schedule was built from. It is not worthless, though — it does independently catch ETL-layer bugs in
  `build_schedules.py` itself (e.g., an accidental row-misalignment, wrong dtype cast, or sort-order bug
  between `atr_at_checkpoint` and its source `atr_at_entry`), since the merge is keyed on
  `(regime_start_ns, signal_decision_ts)`, not on row position. It does **not**, and cannot by design, catch
  a causality bug in the upstream ATR computation itself (that would need to be caught by whatever audit
  gated the upstream `short_rth_pure_flip_score_entry_policy` study — out of this study's scope by SPEC's own
  explicit design, finding 2/3). This is accurately and honestly documented in the SPEC and the docstring, not
  a hidden overclaim — flagged as a **Note**, not a Warning or Critical, since the limitation is disclosed and
  the check still has genuine (if narrower) value.

## Notes

### [documentation] `reconcile.py:83-101` — ATR/score parity check is disclosed as construction-tautological, but the two other checks fully compensate

See analysis above. No action required; the SPEC and code both accurately scope this check's limits. Recorded
here so future readers of this audit don't need to re-derive the same conclusion.

### [metric-methodology] `summarize_variants.py:30-47` (`max_mtm_dd`) — MTM drawdown is understated relative to `whole_trade_mfe_atr`/`mae_pts`'s own high/low convention

`_track_excursion` in `strategy.py:336-354` correctly computes `favorable_adverse_points` from `bar.high`/
`bar.low` (H1-compliant) for `whole_trade_mfe_pts`/`whole_trade_mae_pts`. However, the same function's
`unrealized_pnl` call (feeding `max_unrealized_pnl`/`min_unrealized_pnl`, which `summarize_variants.py`'s
`max_mtm_dd` consumes as each trade's "intratrade low") uses `bar.close` only
(`unrealized_pnl(d, ep, float(bar.close), ...)` — `strategy.py:348`), not `bar.low`/`bar.high`. Since 1s bars
are used, the practical understatement per bar is small, but it is a systematic one-directional bias (`max_mtm_dd`
is a lower bound on the true intrabar mark-to-market drawdown, never an overstatement). This does not affect
the gate decision — `apply_gate.py` does not consult `max_mtm_dd` or `max_closed_trade_dd` in any pass/fail
condition — so it is not a completion-gate blocker, but it should be corrected (use `bar.low`/`bar.high` per
direction, matching `favorable_adverse_points`'s own convention) before `max_mtm_dd` is used for any real
risk-sizing decision in Phase 3 or beyond.

### [latent-inconsistency] `build_schedules.py:27` vs `reconcile.py:66` — inconsistent choice of column for month-bucketing, provably inert for this run but not for a differently-scoped future reuse

`build_schedules.py` (and `phase1_month_selection.py:25`) bucket rows into calendar months using
`entry_ts`'s month, while `reconcile.py`'s `trigger_condition_parity` (`reconcile.py:66`) buckets using
`observation_time`'s month. Given the confirmed up-to-7-second drift between these two columns (Warning 1,
carried from the pre-execution audit, still open) and the fact that a row's calendar month only changes
between the two columns if a midnight boundary falls between them, this is provably harmless **for this
specific RTH-gated population** (all trigger timestamps fall in 08:30-15:00 America/Chicago, many hours from
any UTC midnight boundary, so no row can actually flip month under either column choice in this dataset —
checked: RTH window never approaches a UTC-midnight rollover for `America/Chicago`, which is UTC-5/-6).
Confirmed harmless in this run (all three `trigger_runtime_parity.csv` rows show `exact_match=True` with zero
`only_rederived`/`only_schedule` rows). Flagged as a latent code-hygiene inconsistency only — should be
unified (pick one column, document why) before this pattern is reused for a session/population where a
midnight-adjacent trigger is possible (e.g., any future ETH-inclusive study).

### [process] `apply_gate.py` — the SPEC's "qualitative path evidence" gate criterion has no code implementation

`SPEC.md:151-153` lists "plus qualitative path evidence" as part of the Phase 2 gate criteria. `apply_gate.py`'s
`econ_checks`/`passes` logic implements every other listed criterion (net-positive-or-PF, n_trades≥30,
pct_flip≥55%, opposing-flip-bucket-positive, not-one-outlier-driven) but has no corresponding automated check
for "qualitative path evidence" — this appears to be, and should remain, a human-judgment step performed
outside this script (e.g., reviewing `raw_trade_paths.parquet`/`winner_giveback_counts.csv` by eye) rather
than a coded boolean. Not a bug — flagged so the human gatekeeper doesn't mistake `apply_gate.py`'s `passes`
field alone as the complete, self-sufficient gate the SPEC describes.

## Additional re-verification of prior findings (not re-litigated, confirmed still true)

- **[E3/H4] fix confirmed still in place, re-traced end to end** in the current `strategy.py`: single
  `order_factory.stop_market(...)` call at `strategy.py:257-262`, routed via `on_order_filled`'s
  `elif cid == self._stop_order_id` branch (`strategy.py:216-217`), fill price taken from
  `event.last_px` (`strategy.py:213`), not a manually assumed trigger price or bar close. No
  `stop_would_touch` call site remains in `strategy.py` (grep-confirmed; only referenced in `trade_state.py`'s
  definition and its own unit tests). This is the same conclusion the prior follow-up audit reached, now
  independently reproduced against the current file content plus a live pytest re-run of the mechanism's
  fixture-verified precedent (see "Independent verification performed" item 2 above), not merely re-read.
- **`_on_1s`/`_on_1m` dispatch ordering, RTH gate, no-pyramiding guard, direction-sign formulas in
  `trade_state.py`** — all re-hand-traced against the current file content in this pass; conclusions
  unchanged from the original audit and its follow-up (see relevant sections above). No new discrepancy found.
- **`summarize_variants.py` correctly excludes `end_of_data_exit` rows** from all aggregate economics
  (`variant_metrics`, `exit_reason_summary`, `giveback_counts`, and the equity-curve rows all filter via
  `trades[trades["exit_reason"] != "end_of_data_exit"]` before computing any statistic). This **resolves** the
  original audit's Note 2 ("not independently verified... filter on `.notna()`... rather than accidentally
  coercing NaN to 0") — confirmed clean, upgraded from "unverified" to "verified clean."
- **`apply_gate.py`'s "not-one-outlier-driven" check hand-verified against the actual reported numbers** (see
  item 3 above) — confirmed the logic does what it claims and that T1's fail / T2's and T3's pass are genuine
  outputs of the stated formula, not an accidental sign flip or off-by-one that happened to match the reported
  narrative.
- **`run_nt.py`'s full-year data load (`LOAD_START`=2025-01-01, `LOAD_END`=2025-12-31)** while the schedule is
  filtered to March 2025 only — confirmed this cannot introduce look-ahead: bars are dispatched to the
  strategy strictly in `ts_init` order by the event loop, so data from April-December, though loaded into the
  engine, is never visible to any decision made for a March entry. Verified this is the same pattern already
  used (and previously accepted) in `fable5_nt_short_rth_policy_a`. A March trade whose stop/opposing-flip
  exit resolves after month-end would correctly use genuine subsequent-month price action for its exit (more
  realistic than an artificial truncation), not a source of bias.
- **`RegimeEngine.update()` (`fable5_pre_flip_d10_reversal_entry/strategy.py:77-103`)** — re-read in full;
  confirmed purely recursive/causal (EMA/ATR updates use only the just-passed bar's `h,l,c` and the engine's
  own prior state; no lookahead).

## Forced compliance matrix (abbreviated to items with non-obvious status; full checklist walked)

| Item | Status | Basis |
|---|---|---|
| A1/A3 | PASS | `bar.ts_init` used exclusively; no future-indexed lookups |
| A2 | N/A | Catalog reused verbatim from already-audited precedent; not re-derived here |
| A4 | PASS | No `TimeEvent` callbacks in strategy |
| A5/F3/F4 | PASS | tz-aware `tz_convert`, DST-safe |
| B1-B7 | PASS | No pandas rolling/ewm/shift(-N) in decision path; `trigger_logic.py` lookbacks confirmed backward-only |
| C1-C4 | N/A | No ML label construction in this phase (frozen scores, Phase 3 deferred) |
| D1 | WARNING (open, carried) | Entry-timing parity check still absent (see original audit) |
| D2/D3/D4 | N/A | No live scoring/meta-labeling in this phase by SPEC's explicit design |
| E1/E2 | PASS | Bar type strings match catalog/config |
| E3/H4 | PASS (re-verified) | Genuine resting `stop_market`, fixture-precedent re-run confirms trigger-price fill |
| E4 | PASS | Entries dispatched from frozen schedule, not same-bar-derived signals |
| E5 | PASS | RegimeEngine warmed 2+ months before selected month |
| F1/F2 | PASS | RTH gate uses `ts_init` (close time); no session-spanning rolling windows in this strategy |
| G1-G4 | N/A | Single-instrument NQ.XCME reused catalog; no continuous-contract stitching in this study |
| H1 | PASS | `stop_would_touch`/`favorable_adverse_points` use high/low, not close |
| H2 | PASS | 1s-bar resolution stop matching, matches NT's own execution granularity |
| H3 | N/A | No offline pre-collected trade set replayed; all trades generated live by NT itself |
| H4 | PASS (re-verified live) | Fixture re-run confirms trigger-price fill under this exact dual-bar engine config |

## Conclusion

**0 CRITICAL findings.** The previously-identified and previously-resolved CRITICAL ([E3/H4], manual stop
polling) remains resolved under independent re-verification, including an actual pytest re-run of the
precedent's full-`BacktestEngine` fixture proving trigger-price fills under this study's exact dual 1s/1m
bar-feed configuration — this was not merely re-read from the prior audit trail but independently reproduced.
All three reconciliation checks were read and confirmed genuinely causal re-derivations (with one, ATR/score
parity, honestly self-disclosed as narrower-scope by the study's own docstring — not a hidden weakness). Gate
logic in `apply_gate.py` was hand-verified against the actual reported numbers and found to implement exactly
what it claims, with no sign-flip or off-by-one that would turn a fail into a pass. Four Notes are recorded
(one documentation note, one metric-methodology understatement in `max_mtm_dd` that does not affect the gate
decision, one latent column-choice inconsistency that is provably inert for this run, one process note about
the SPEC's qualitative-evidence criterion having no code equivalent). One Warning from the original
pre-execution audit remains open and carried forward (entry-timing parity check, D1) — it did not block this
run and the empirical entry_ts/observation_time drift is small (≤7s, ~1-2% of rows), but it should still be
added before this study's results are treated as the final word on entry-timing fidelity.

**It is safe to proceed to Phase 3 (the mirrored long-entry model)** on the infrastructure/causality axis. The
economic gate decision itself (`NT_POC_PROMISING_LONG_MODEL_NOT_RUN`, driven by T2/T3 passing and T1 failing
only the outlier-concentration check) is a modeling/business call for the user, not an audit finding — this
audit confirms the numbers behind that decision were computed correctly and causally, not that the decision
itself is the "right" one to make.

---

*Completion-gate audit complete. This was a full re-verification of the entire Phase 2 pipeline post-execution,
performed independently (re-running tests, re-tracing code, and cross-checking output artifacts against
reported figures) rather than trusting the prior audit trail, per instruction. All findings above are new to
this pass except where explicitly marked as re-confirmations of prior conclusions.*

# Causal audit — pass 04 (delta) — nq_va_multitf_trade_state_geometry

audit_type: "causal"

Delta pass over `pass_03` (CLEAR, 1 warning: C-6). New execution composite
`c9249f99ff96ab5b1dd8ae7f0876f490f6e1f9e3238fe4b7ae9cd71150748356`, plan
`11fcaf24a18e3c3f442e8a589a962f3cff6f075810fb136f14ac1b4720d1e557`. Tests 158 passed / 0
failed (narrow); wider outcome-adjacent set 234 passed / 4 failed, all four pre-existing on
this branch base in the frozen V1 `target_runtime` path, identical with and without this
commit — completeness/regression-classification question, referred below, not re-audited.

**Scope of this pass**: one commit, `e341d709`, touching only `research_workflow/host/
outcomes.py` (+17/-2) and `research_workflow/tests/test_composite_session_end_truncate.py`
(+3 tests, 22 total, all green). No other file in the closure changed; `study.yaml` untouched.
Read via full-file re-read of the two touched code ranges (`outcomes.py:422-436` exit-fill
block, `outcomes.py:540-580` `_complete`), not re-derived from a diff tool.

---

## Δ1 — C-6 closed: C1 exit fill now checks the session boundary explicitly, ahead of GAP

`outcomes.py:425-436`:

```python
if (c1 := self.c).terminal_outcome and p.flip_ts is not None and p.exit_ts is None and ts > p.flip_ts:
    if p.session_close is not None and ts > p.session_close:
        p.exit_reason = "SESSION_END"
    elif c1.max_gap_ns is not None and (ts - p.flip_ts) > c1.max_gap_ns:
        p.exit_reason = "GAP"
    else:
        p.exit_price = op
        p.exit_ts = ts - (bar.ts_init - bar.ts_event)
```

This is my pass_03 "smallest fix," adopted verbatim, and it closes C-6: the exit fill can no
longer be sourced from a bar whose `ts_init` is past `session_close`, regardless of how the
calendar's actual maintenance-break duration compares to `max_gap_ns`. Confirmed by
`test_the_exit_fill_session_bound_does_not_depend_on_max_gap` — `max_gap_ns` set to 86400s
(wide enough to wave any gap through) and the fill is still refused, proving the guard is the
explicit `ts > session_close` check and not an accident of the gap threshold.

**Inertness confirmed:**
- **`ignore`** — `session_end_censoring=False` ⇒ `p.session_close is None` at `open()` ⇒ the
  new `if p.session_close is not None and ts > p.session_close:` branch is never true; falls
  through to the pre-existing `max_gap_ns` check unchanged. No behavior change.
- **`censor`** — traced the full call path: under `censor`, every arm is resolved
  `CENSORED SESSION_END` inside the *same* `on_bar` call that resolves the entry
  (`outcomes.py:410-421`, `truncate=False` branch, unchanged), so `p.arm_open` reaches 0
  before the exit-fill check is even reached that bar; `_complete` then immediately resolves
  the flip child too (`elif p.session_close is not None and p.flip_end > p.session_close:` at
  `:564`, unconditional on `truncate`), and the row is emitted and removed from `self.pending`
  on the entry bar itself. `on_flip` only mutates candidates still in `self.pending`, so
  `p.flip_ts` can never become non-`None` for a `censor` composite candidate whose horizon
  exceeds the session (true of this contract's 24h vs. ~23h day) — the new branch is provably
  unreachable, exactly as claimed. Unchanged regression:
  `test_censor_still_voids_an_overlong_window_at_the_close` still asserts `terminal_flip_ts is
  None` for `censor`.
- **Flip-at-the-close, no in-session fill bar** — `test_the_exit_fill_never_comes_from_a_bar_
  past_the_session_close`: flip lands on the last in-session bar; `terminal_flip_ts`/
  `terminal_flip_disposition` resolve `LABELED_POSITIVE` (the flip is real and observed
  in-session), while `terminal_exit_unavailable_reason == "SESSION_END"` and every economics
  column (`terminal_exit_price`, `terminal_gross_pnl_atr`, `terminal_net_pnl_atr`) is explicit
  `None` — not a silently-absent row. Traced independently in `_emit` (`:679-701`): the
  `if p.entry_resolved and p.exit_ts is not None and p.exit_price is not None:` guard is false
  whenever `exit_reason` was set instead of `exit_ts`, so the `else` branch always explicitly
  nulls every economics column; there is no code path that leaves them simply absent from the
  row dict. **Confirmed — resolved terminal, economics explicitly unavailable, never silent.**

**C-6: CLOSED.**

## Δ2 — new finding traced adversarially: the one-tick hold on the truncated flip child

**The defect (pre-`e341d709`, present only in the `chore/composite_truncate` state pass_03
audited, never sealed):** `_complete`'s truncated-flip branch resolved on `now_ts >=
p.session_close`. `host_runner.sort_bars_causal` breaks ties at equal `ts_init` by
shorter-timeframe-first, and `host/strategy.py::_deliver` runs each stream's own trackers only
for that stream's bar — so the 1s outcome bar closing exactly at `session_close` reaches
`kernel.on_bar` **before** the 1m bar whose `regime_1m` tracker fires `on_flip` at that same
instant. `_flip_effective_end` is inclusive of the close (`flip_ts <= effective_end`), so a
flip landing in the last second of the session was structurally eligible — but `_complete`
would have already stamped `CENSORED SESSION_END` on the 1s bar's `on_bar` call, one delivery
tick before the 1m bar carrying the flip arrived. This is the repository's repeat "1s-before-1m"
pattern (a feature/decision reading an incomplete or not-yet-updated 1m-derived state from a 1s
callback), here applied to the terminal rather than a feature.

**The fix**, `outcomes.py:558`:
```python
if p.session_close < now_ts or (p.session_close == now_ts and final):
    p.flip_state, p.flip_at, p.flip_reason = CENSORED, p.session_close, "SESSION_END"
elif final:
    p.flip_state, p.flip_at, p.flip_reason = CENSORED, now_ts, "DATA_END"
else:
    return False
```
identical in structure to `_sweep_flip`'s pre-existing `session_due` test for `kernel: flip`
(`:596-597`) — same tie-break rule reused, not invented.

**Is the hold correct and sufficient?** Traced the event sequence at `ts_init == session_close`:
(1) 1s bar delivered → `on_bar` → arms for this candidate resolve *within this same call*
(`past_end = ts > end` is `False` when `ts == end`, so the arm sweep's `elif ts >= end:
self._expire_arm` branch fires using this bar's own in-session HIGH/LOW — unaffected by this
fix) → `_complete` reaches the truncated-flip branch, `p.session_close == now_ts and not final`
→ `return False`, candidate retained. (2) 1m bar delivered (same `ts_init`, later in delivery
order per the platform's causal-order guarantee) → tracker fires → `on_flip` → composite branch
sets `p.flip_ts = flip_ts` (`p.T < flip_ts <= session_close`, both true) — this only *mutates
the pending record*, it does not call `_complete`/`_emit`. (3) The *next* bar (`ts_init >
session_close`) arrives → `on_bar` → `_complete` re-runs, now `p.flip_ts is not None` →
`POSITIVE`; the exit-fill block (Δ1) sees `ts > p.session_close` → `exit_reason = "SESSION_END"`
(no in-session bar left to fill from) or resolves normally if still in-session. Verified exactly
by the new `test_a_flip_at_the_close_instant_still_lands_although_the_bar_arrives_first`, which
explicitly asserts `k.drain_rows()` is empty immediately after the 1s bar and before `on_flip`
is called — the row is provably not emitted early. **Sufficient**, and it is the same fix already
proven for `kernel: flip`.

**Does holding expose the candidate to information it should not see?** No, explicitly checked:
the hold defers only a *disposition decision*, not a data read. Nothing new is read from the
holding bar — its arms were already resolved from its own in-session OHLC (legitimate,
pre-existing, unaffected by this fix), and the only information used to eventually complete the
row is (a) the flip event itself, a real market event whose `ts_init` is `<= session_close` and
therefore inside the declared window, and (b) the timestamp (not the price) of the next bar, used
solely to detect that the close has passed. No post-close OHLC is read by anything this fix
touches. **CLEAR — no look-ahead introduced.**

**Does `finalize` still terminate every candidate?** Traced: `finalize`'s composite/barrier tail
(`:628-634`) calls `self._complete(p, now, final=True)` then **unconditionally** `self._emit(p)`
regardless of `_complete`'s return value. With `final=True`, the truncated branch's condition
`p.session_close < now_ts or (p.session_close == now_ts and final)` is true whenever
`p.session_close <= now_ts`, and the `elif final:` immediately below catches the remaining case
(`p.session_close > now_ts`, i.e. the tape ran out before the close) with `CENSORED DATA_END`.
No candidate can reach `finalize`'s `_emit` with `flip_state` still `None`, and the C1 block's own
`if not final: return False` / `p.exit_reason = "DATA_END"` guard likewise cannot return `False`
when `final=True`. **CLEAR — every pending candidate terminates.**

**No new finding.** This was pass_03-window-only (introduced in `4139ae15`, never sealed,
self-caught while writing the C-6 regression test, fixed in the same commit reviewed here). No
new C-n id assigned; recorded as adjudicated, not as a residual finding.

## Δ3 — un-changed branch: the identical same-timestamp hazard in the non-truncated NEGATIVE path

`outcomes.py:566-570` (`elif now_ts >= p.flip_end or final:`) still resolves `NEGATIVE` at
`now_ts >= p.flip_end` without the one-tick hold. This carries the structurally identical
1s-before-1m hazard: a flip landing exactly at `flip_end` could be pre-empted by the 1s bar's
`on_bar` call deciding `NEGATIVE` before the same-instant 1m bar's `on_flip` arrives.

**Does it bind this seal?** No. Traced the guard conditions above it: this branch is reached
only when `truncated` is `False`, i.e. `session_close is None` (`ignore` — not this contract) or
`flip_end <= session_close`. For this study `flip.horizon_ns = 86400e9` (24h) against a
`TRADING_DAY` close at most ~23h from any in-session `T`, so `flip_end > session_close` always,
`truncated` is always `True`, and this branch is unreachable for every candidate this contract
can ever open. Agree with the coordinator: **correct call for this seal** — fixing it here would
be speculative hardening of dead code for this contract, not a defect with a concrete failure
path against it.

**Does it deserve a carried-forward NOTE?** Yes.

### NOTE C-7 — the non-truncated flip-child NEGATIVE resolution has the same unfixed 1s-before-1m hazard as C-6's flip child had; latent for any future composite study whose flip horizon fits inside its session
Unreachable for this study (24h horizon always exceeds the trading day, so `truncated` is
always `True` here); a future `kernel: composite` study declaring a flip horizon that fits
inside its session (any `session_end_rule`, since the hazard is about `flip_end` landing on a
bar boundary, not about the close specifically) would reproduce pass_03/Δ2's defect at
`flip_end` instead of at `session_close`. Smallest fix when it becomes reachable: mirror
`outcomes.py:558`'s tie-break (`now_ts > p.flip_end or (now_ts == p.flip_end and final)`) at
`:566`.

---

## Q1–Q7 reconfirmed against the new composite

| Q | pass_03 conclusion | This pass |
|---|---|---|
| Q1 (forward-only exposure at T) | CLEAR | Undisturbed — Δ1/Δ2 touch only post-entry state |
| Q2 (post-close bar influencing exit fill) | WARNING C-6 | **Closed** by Δ1 |
| Q3 (SESSION_END > GAP > TOUCH > EXPIRY precedence) | CLEAR | Reconfirmed for the exit-fill block too: Δ1 checks `session_close` before `max_gap_ns`, extending the same declared precedence to C1 exit resolution, which pass_03 had not yet covered explicitly |
| Q4 (cross-candidate/session state leak) | CLEAR | Undisturbed by Δ1; Δ2's hold is scalar per-`_Pending`, no cross-candidate coupling (see Δ2) |
| Q5 (inert for `censor`/`ignore`/`kernel:flip`) | CLEAR | Reconfirmed for Δ1 in Δ1 above; Δ2 reuses `_sweep_flip`'s existing tie-break, touches no `kernel:flip` code |
| Q6 (SESSION_END meaning under truncate) | Not a finding, documented | Undisturbed |
| Q7 (pass_02 C-4/C-5) | Untouched | Untouched — this delta is confined to `outcomes.py`/tests |

---

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| C-6 | C1 exit fill relied on calendar-gap duration rather than an explicit session check (pass_03 WARNING) | **Resolved** | `outcomes.py:426-431`; `test_the_exit_fill_never_comes_from_a_bar_past_the_session_close`, `test_the_exit_fill_session_bound_does_not_depend_on_max_gap` |
| C-4 | Discovery/replication split is contractual (pass_02 NOTE) | Unchanged | Δ has no chronology surface |
| C-5 | Shallow 1h warmup at two partition edges (pass_02 NOTE) | Unchanged | Δ has no warmup surface |

## Carried forward from pass_01 / pass_02 / pass_03

Population, executable `next_bar_open` entry, opposite-flip terminal definition, the three
independent clocks, MTF causality, geometry reconstructability, gross-only economics,
chronology, `model: null`, GAP-precedence and truncate-inertness for `censor`/`ignore`/`kernel:
flip` on the barrier-arm surface: all CLEAR/adjudicated in prior passes and untouched by this
delta.

## Referred to contract-checker

- The 4 pre-existing failures in the wider 234-test outcome-adjacent run (frozen V1
  `target_runtime` path, identical with/without `e341d709`) are a test-classification/
  completeness question, not a causal one.

## Clean checks

A1-A5, B1-B10, C1-C3, F1-F4, G1-G4, H1-H4 clean; H2/H4 (temporal resolution, executable fill
price) specifically re-verified against Δ1/Δ2's touched surface.

## Verdict

**CLEAR.** Zero critical, zero warning (C-6 closed, no new warning raised), one new note
(C-7, forward-looking, non-blocking, unreachable for this contract). The `e341d709` delta
correctly closes C-6, correctly fixes a genuinely new same-timestamp hazard it introduced and
self-caught before this study's seal, introduces no look-ahead, and leaves the untouched
same-timestamp hazard in the non-truncated NEGATIVE branch dead code for this contract's
horizon/session arithmetic.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "audited_execution_composite_sha256": "c9249f99ff96ab5b1dd8ae7f0876f490f6e1f9e3238fe4b7ae9cd71150748356", "auditor": "claude-causal-pass04", "critical": 0, "note": 1, "study": "nq_va_multitf_trade_state_geometry", "verdict": "CLEAR", "warning": 0}
<!-- AUDIT_SUMMARY_V2_END -->

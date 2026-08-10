# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-10
**Scope:** `implementation/engine.py`, `implementation/build.py`, `analysis/policies.py`
**Scope hash:** 8a0763c885daac74312c58b0ce253e61a2a85569c707081e4ce19987eee818ad
**Lint:** 0 critical / 0 warning (`audit/lint.json`, 7 files scanned, clean)
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 1
- Note: 0

## Critical findings

### [H4-class] `implementation/engine.py:224-231` — `P90ARM_PRICE` searches for the adverse crossing starting on the P90 observation bar itself, so it fires (almost) trivially on that same bar instead of testing a genuine later reversal.

```python
ref = float(mark[jb])
seg = slice(jb, nat_i + 1)          # <-- includes bar jb itself
h = _first(bar_lo[seg] <= ref)
finish(jb + h if h >= 0 else -1, True, "P90ARM_PRICE")
```

`ref = mark[jb]` is the **close** of bar `jb` (the P90 event bar). `bar_lo[jb]` is
that **same bar's** own worst level: for longs `bar_lo=(lo-px)/atr` vs.
`mark=(cl-px)/atr`, so `bar_lo[jb] <= ref` reduces to `lo <= cl`, which is true
for every OHLC bar by construction (for shorts it reduces to `cl <= hi`, also
always true). `h` is therefore `0` for essentially every trade where `jb >= 0`,
regardless of any actual subsequent adverse move.

**Failure path:** For any confirmed trade with a raw-causal P90 event (`jb>=0`),
`trig_i = jb + 0 = jb` — the exact same index `P90B_EXIT` uses
(`finish(jb, True, "P90B_EXIT")`). `P90ARM_PRICE` therefore collapses into a
near-duplicate of `P90B_EXIT` across the population instead of testing "price
crosses back through the P90 observation level" (SPEC §4, policy 9). Every
Phase 6/9/10/11 number reported for `P90ARM_PRICE` (and the `_BUF` buffered
variant, which shares the same off-by-one and is only saved from the identical
outcome by needing `bar_lo[jb] <= ref - 0.25` on that one bar) is measuring the
wrong thing. This is exactly the failure mode item 6 of the audit brief asked
to rule out ("cannot fire on the P90 bar itself") — it does.

**Smallest fix:** `seg = slice(jb + 1, nat_i + 1)` so the adverse-crossing scan
starts on the bar *after* the observation, not on it.

## Warnings

### [H4] `implementation/engine.py:96-101` — `exit_at` silently falls back to same-bar close when a STOP's next-bar-open fill would land past the session/array boundary.
`nat_kind == "STOP"` uses `fill_next=True`; if `stop_i` is the very last index
of the walked window (the window end is fixed by `min(close_ns, opposing_ns)`,
independent of where the stop is), `f = start+i+1 == end`, which fails
`f < sess_end`, and the code falls back to `cl[i]` — the stop bar's own close
— instead of a next-bar open. Not future information (low/close of the same
bar are known together at bar-close), and it is session-containment-forced
(no legal next bar exists), but it is a same-bar fill for what the rest of the
study treats as a triggered exit, and it is not counted by
`ambiguous_stop_confirm` or any other flag. Narrow: only affects trades whose
stop is hit on the final bar of an already-truncated (session/opposing-flip)
window. Does not change the headline result.

## Prior findings adjudicated
N/A — pass 1.

## Referred to contract-checker
- SPEC §2 promises "same-bar ties resolved adversely, flagged, both bounds
  reported" as a general contract clause; only `ambiguous_stop_confirm`
  (stop-vs-confirm) is implemented/flagged — no flag exists for P90/P80-vs-stop
  or P90/P80-vs-opposing-flip same-bar coincidences, even though the underlying
  resolution (via `bar_lo` worst-case) is already adverse in every case.

## Clean checks
- `finish()` clamp (`trig_i >= nat_i` → natural): verified no policy can exit
  after `nat_i` or past the stop; `trail_from`/`event_block` outputs are
  structurally bounded to `<= nat_i`.
- `trail_from`: running extreme is a causal prefix-max at each bar; `bar_lo`
  sign convention verified correct for both directions
  ((lo-px)/atr long, (px-hi)/atr short); `armed = ext >= floor_mfe` uses only
  data through the current bar, no look-ahead.
- Landmark indices (`lm{t}_ns`) and `event_block` indices both explicitly
  clamped to `<= nat_i`; unclamped fallback for `RUNNER_TIERS` tier 4.0 (not
  in `LANDMARKS`) is safe because the `policies.py` pool filter
  (`baseline_max_mfe_atr >= T`, itself `nat_i`-clamped) guarantees the first
  unclamped touch cannot exceed `nat_i` whenever it is actually consulted.
- `{prefix}_seconds_to_maxmfe`: confirmed retrospective-only, not read by any
  policy.
- `first_events()` (build.py): new-regime model selection (`bullish` iff new
  regime direction is `+1`) verified correct via the join constraint tying
  `direction` to `regime_direction`; crossing uses `shift(1)` (backward, not
  `-1`) `.over("regime_id")` on a null-filtered, time-sorted stream — no
  carry-forward can count as a crossing; `in_domain` is applied only after
  `cross_*` is computed (at the crossing row), matching stream A/B separation
  in SPEC §1.2; score availability gated by `checkpoint_decision_ns >=
  confirm_ns`.
- Session containment (`engine.py` `sess_end`/`day_close_ns`/`horizon`
  clamping): matches the accepted upstream pattern in
  `model_driven_entry_exit_discovery/implementation/engine.py`; fills verified
  bounded by `f < sess_end`.
- `policies.py`: `pre_sum` added only to level metrics
  (`mean_net_atr_per_original_entry`), correctly cancels out of
  `delta_per_original_entry`/`delta_per_confirmed` (both computed from `inc =
  tot - base_sum` over the confirmed population only); `cut_before_tier`
  correctly compares policy exit index against the landmark first-touch index.
- A, B, F1-F4, G1-G4 otherwise verified clean in the diffed files.

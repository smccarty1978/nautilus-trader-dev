# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-11
**Scope:** `SPEC.md` §5, `implementation/rungs.py`, `implementation/build.py`;
call-convention only for reused-unchanged `top10_fast_confirm_runner_path/implementation/{engine.py,build.py}`
**Scope hash:** `c931e987f5f46238e90c910c4197c14f2986e03c0ad2c9184ea7e8d6db8c7d50`
**Lint:** 0 critical / 0 warning from `causal_lint.py` (5 files scanned, clean)
**Verdict:** BLOCKED

## Summary
- Critical: 0
- Warning: 1
- Note: 0

## Warnings

### [D5] `implementation/rungs.py:198-199` — optimistic-bound column silently degrades to the adverse value on single-bar-to-target transitions
```python
adv = self._adverse(r, t, X)
opt = self._adverse(r, t - 1, X) if (ok and t - 1 > r) else adv
```
**Failure path:** SPEC D5 defines the optimistic bound as the adverse measures computed
over the *open* interval `(r, t)` — i.e. strictly between the rung bar and the target
bar, excluding the target bar's own low. When the target is first reached at bar
`t = r+1` (the very next bar after arming — a real and unremarkable case for
`ARM_AT_CONFIRM` rows whose banked MFE is already close to the next target, or for
fast-moving `FAST_CONFIRM` trades), the true optimistic window `(r, r+1)` contains no
bars at all, so both `retrace_below_rung_optimistic_atr` and `mae_from_hwm_optimistic_atr`
should be `0.0` — `_adverse(r, r, X)` already returns exactly that via its own
`t <= r` guard (line 218-219). Instead, the `ok and t - 1 > r` condition routes this
case to `opt = adv`, i.e. the optimistic column is set equal to the *adverse* value,
which includes bar `t`'s own low — precisely the ambiguous bar D5 exists to treat
optimistically. For every such row the "optimistic bound... never a substitute for
the adverse number" (SPEC D5) becomes a literal substitute, and `collision_at_target`
(`adv != opt`) is trivially `False` regardless of whether bar `r+1` actually collided.

**Scope of impact:** confined to the disclosure-only optimistic columns in
`rung_transitions` (Deliverable #4) and any Phase 5 "optimistic bound" derivative.
It does **not** reach `exit_index`/`build_exit_tables`/`policy()` — the actual stop
simulation and `ratchet_economics` pricing read `bar_lo`/`hwm_prev` directly, never
`_adverse`'s output — so `master_tradeoff`, the decision gate, and gate 7's strict
adverse-only CDF equality (§9) are unaffected. Severity is WARNING, not CRITICAL,
because no headline economic number or gate condition changes; it is a genuine defect
in a mandated per-row column, not adjudicated anywhere in the SPEC.

**Smallest fix:** drop the `t - 1 > r` guard and always call
`self._adverse(r, t - 1, X)` when `ok`; the existing `t <= r` early return inside
`_adverse` already produces the correct `(0.0, 0.0)` for the degenerate one-bar case.

## Notes
(none)

## Referred to contract-checker
- `rungs.py`'s module docstring and `_fill_returns` docstring both promise a
  bar-for-bar equality assertion against `Window.realise(i, True)` "in validate.py",
  but no `validate.py` exists yet under `implementation/`; deliverable/manifest
  completeness, not a causal defect in the code that does exist.

## Clean checks
- **D3 (arming boundary):** `rung_index` reads `bar_hi[:r+1]` only (rungs.py:124);
  every transition/excursion helper (`transition`, `_adverse`, `_failure_geometry`,
  `build_exit_tables`) slices strictly from `r+1`. No expression spans the boundary.
- **D4 (hwm reference):** `hwm_prev = concat([-inf], run_mfe[:-1])` (rungs.py:90) is
  used consistently as `run_mfe[k-1]` in `_fill_returns` is N/A (fill uses price, not
  hwm), `build_exit_tables`, `_adverse`, `_failure_geometry` — verified no path reads
  `run_mfe[k]` as a same-bar stop reference.
- **H4 (fill pricing):** `exit_index` returns the trigger bar; `policy()` and
  `returns_for_armings` price exclusively via `w.realise(e, True)` / `fill_ret[e]`,
  both bar `e+1`'s open. `_fill_returns` is a faithful vectorisation of
  `Window.realise(i, True)` (rungs.py:93-110 vs engine.py:101-112, term-for-term
  match). No trigger-price credit found.
- **D5 (adverse window, adv side):** `_adverse(r, t, X)` correctly includes bar `t`
  (rungs.py:220-222); the SUCCESS/FAIL classification correctly treats a same-bar
  collision as adverse by construction (no exclusion of bar `t` in `adv`).
- **D2 (already-met trap):** rows with `run_mfe[r] >= Y` are classified
  `ALREADY_MET` with all adverse fields set `None` (rungs.py:189-194) and excluded
  from transition/MAE distributions by construction (never emitted with numeric
  adverse values).
- **Retrospective labels:** `eventual_max_mfe_atr`, `runner_bucket`,
  `nat_terminal_return_atr`/`unc_terminal_return_atr` (trade_meta, rungs.py:379-407)
  are stored only as output columns; confirmed no path feeds them into
  `rung_index`, `exit_index`, `build_exit_tables`, or `policy`. `tier_idx` (used only
  by `runner_survived`, a descriptive column) is similarly isolated from arming/exit.
- **D8 (placebos):** `P_BLIND` draws from the fixed grid `DENSE_OFFSETS_S`
  (build.py:68), converted via `index_at_offset` (session-clamped, causal); rejection
  on `j > w.nat_i` does not enlarge its support with future information. `P_UNIFORM`
  correctly draws `[ci, nat_i)` and is labelled `FUTURE_INFORMATION` throughout
  `partition_manifest.json` (build.py:236).
- **2026 seal:** `armed_regime_score_paths.parquet` (`valid=True`) contains no 2026
  rows at the source; the `assert 2026 not in years` (build.py:150) runs before the
  per-trade walk loop.
- **Session containment:** windows are built exclusively via the reused `prepare()`
  (session-clamped to `sess_end`); this study introduces no additional indexing that
  could cross a session boundary.
- **D7 (architecture dominance):** verified algebraically that every frozen `D` in
  `STOP_DISTANCES` keeps the armed level `>= -0.25` ATR, so `max(-1.00, level)`
  always equals `level` post-arming — the `unc_ret` fallback used in `policy()` when
  an armed stop never triggers is therefore the correct terminal (opposing
  flip/session close), not a silent loosening of the original 1.00 ATR stop.

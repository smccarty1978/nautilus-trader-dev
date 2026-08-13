# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-10
**Scope:** `studies/confirmation_economics_excursion_map/implementation/panel.py` (pre-execution; no results exist yet)
**Scope hash:** `b56ef37b6a0bd927cec8717231a1176edcbfd079e3fdd8d91579e1c1c038594f`
**Lint:** 0 critical / 0 warning (`causal_lint`, 6 files scanned)
**Verdict:** BLOCKED

## Summary
- Critical: 2
- Warning: 2
- Note: 2

## Critical findings

### [C1/H] `panel.py:277-278` — Phase 7 transition clock resets to a spurious *later* bar when a landmark was already held at confirmation
```python
ha = np.flatnonzero(p_fav >= a)
ia = int(ha[0]) if ha.size else (-1 if float(run_mfe[confirm_idx]) < a else 0)
```
The "already held" check (`run_mfe[confirm_idx] >= a`) is only consulted when `ha.size == 0`, i.e. only when no post-confirm bar's own high ever independently re-touches level `a` again. Whenever landmark `a` was already achieved at/before confirmation (`run_mfe[confirm_idx] >= a`, the common case — median return at confirm ≈0.85 ATR) **and** price pulls back after confirmation before re-touching `a`, `ia` is set to that later re-touch index instead of `0`. `seg_gb = cummax(max(seg_ext - seg_low, 0))` then starts at that later index, silently omitting the entire pullback between confirmation and the re-touch from `trans_*_giveback_atr`. `trans_*_seconds` is also measured from the wrong start.

**Failure path:** landmark `a=1.00`, `run_mfe[confirm_idx]=1.10` (already held). Bar 0 post-confirm high-mark drops to 0.70 and stays below 1.00 for 50 bars (a genuine 0.4+ ATR giveback), then bar 51 re-touches 1.05. Correct behavior is `ia=0`, capturing the pullback in `seg_gb`. Actual behavior: `ia=51`, and every bar of the pullback is excluded — `trans_100_to_150_giveback_atr` reports near-zero giveback for a trade that actually gave back 0.4+ ATR. This directly inverts the finding Phase 7 exists to surface (giveback distributions split by successful/failed transition) for the exact population — already-profitable runners that pull back — the phase targets.

**Smallest fix:** check `already = run_mfe[confirm_idx] >= a` first; if true, `ia = 0` unconditionally (matching the Phase 3 `already_at_confirm` precedence), and only fall back to `ha[0]`/`-1` when not already held.

### [H] `panel.py:253-271, 301-316` — same-bar collisions handled for stop-vs-confirm only; stop-vs-landmark and floor-vs-landmark collisions are silently resolved by inferred intrabar ordering, contra SPEC §1.1
SPEC §1.1 is explicit: "This applies to stop-vs-confirm, stop-vs-landmark, and floor-vs-landmark collisions alike" — each must be resolved adversely and flagged `ambiguous`. Only `ambiguous_stop_confirm` (line 143) is implemented. Landmark first-touch (`hits = np.flatnonzero(p_fav >= L)`, line 259) and floor-touch (`hits = np.flatnonzero(bar_low_mark <= F)`, line 313) are computed purely from the bar's own high/low with no cross-check against the same bar also breaching the stop (constrained mode, last window bar = `stop_idx`) or a floor. A wide 1s bar whose high clears a landmark and whose low also breaches the stop/floor is silently credited with the (optimistic) landmark reach — the opposite of §1.1's mandated adverse resolution — with no `ambiguous` flag for downstream reporting.

**Failure path:** constrained-mode trade, last included post-confirm bar is `stop_idx` (bar's low breaches the 1.0 ATR stop). The same bar's high also crosses landmark `+0.50`. Intrabar order is unknowable; §1.1 requires resolving adversely (stop-first, landmark not credited or flagged) — the code instead unconditionally credits `lm0_50_reached_after_confirm=True` with no flag, silently assuming the favorable touch happened first. This directly violates validation gate 10 (`same_bar_accounting`, SPEC §9), and biases Phase 3/6 landmark-reach counts and adverse-excursion figures optimistically for exactly the ambiguous, high-volatility bars most likely to matter.

**Smallest fix:** for each landmark/floor hit index, check whether it coincides with `stop_idx` (constrained mode) or another trigger's index in the same bar; if so, resolve per §1.1 (adverse bound + `ambiguous_*` flag), reporting the optimistic bound alongside as SPEC requires.

## Warnings

### [C2] `panel.py:186-198, 318-323` — Phase 1 and Phase 8 fields are computed unconditionally on `confirm_idx >= 0`, without regard to whether the trade actually reached that state under the row's own `path_mode`
Phase 1 fields (`return_at_confirm_atr`, `mfe_to_confirm_atr`, etc., lines 191-198) are populated whenever `confirm_idx >= 0`, including constrained-mode rows where `stop_idx <= confirm_idx` (`STOPPED_BEFORE_CONFIRM` — SPEC §3.4: "not confirmed; excluded from this study"). Phase 8 fields (lines 318-323, commented "constrained semantics") use `mark[-1]`/`run_mfe[-1]` from the raw full-window arrays, which do not respect `stop_idx` at all — `reached_opposing_flip` can be `True` even when a constrained stop would have exited the trade long before the opposing flip. Both are reliably gated by existing boolean fields (`confirmed`, `terminal_label_constrained`), so this is not a lookahead bug, but nothing in-code documents that Phase 1/8 fields require filtering on those gates rather than on their own presence — a plausible mistake in not-yet-written analysis code that would silently blend unconfirmed/pre-stop price action into confirmation-economics and flip-exit-efficiency tables. Not shown to fail today since no consuming code exists yet; flagged per severity discipline as WARNING rather than CRITICAL.

**Smallest fix:** add a one-line comment at each block naming the required gate (`confirmed==True` for Phase 1; `terminal_label_constrained in (FLIP_WINNER, FLIP_LOSER)` for Phase 8), or compute `None` when the gate is false.

## Notes
- `panel.py:240` — seeding `running_extreme` with the floored `run_mfe[confirm_idx]` (never negative) is consistent with the existing MFE convention in `engine.py` (`max(fav, 0.0)` accumulated); defensible, not a defect.
- `panel.py:298-299` — once the CRITICAL `ia` fix above is applied, `trans_*_seconds` for already-held landmarks will still measure from the post-confirm bar-0 proxy rather than the true (pre-confirm) achievement time, since Phase 3-7 only track bar arrays from confirmation onward by design. Inherent to the phase framing, not a lookahead defect — worth disclosing in `README.md`/`REPORT.md`.

## Referred to contract-checker
- `results/validation_report.json` gate 10 (`same_bar_accounting`) cannot pass as currently scoped in panel.py output — completeness of the required output fields, not this agent's call to make.

## Clean checks
- A1-A5: inherited from already-accepted `engine.py`/`MarketData`/`RegimeIndex`, not modified by panel.py.
- B1-B10: no rolling/ewm/shift/merge_asof/normalization logic introduced in panel.py.
- C3: not applicable (no train/test split in this diagnostic study).
- F1, F2: session containment verified — `end` clamped to `session_end`/`market.n`, matching the accepted `engine.py::simulate` pattern exactly; only RTH bars loaded so no overnight-gap crossing is possible.
- G1: substrate is `data/canonical/regime_complete_v1` (accepted canonical store), no new data loading path.
- H1, H2, H4: stop/landmark/floor triggers all use intrabar HIGH/LOW at 1s resolution; fills use next-bar open (`exit_px`), never trigger price. Landmark first-touch indexing (Check 1) and Method A/B sign conventions (Check 2, `bar_high_mark`/`bar_low_mark` unfloored and correctly signed for both LONG/SHORT) verified clean. Window-floor arithmetic (Check 5) verified clean.

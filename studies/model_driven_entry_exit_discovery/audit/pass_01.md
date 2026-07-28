# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-07-27
**Scope:** implementation/engine.py, implementation/candidates.py, implementation/screen.py, implementation/composite.py (diff-first not applicable — new study, full files reviewed against SPEC.md)
**Scope hash:** 79df7d0ff4757cedb8111573dc82d98bb404117d6dd878e3b35474701b7d25b8
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 9 files scanned)
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 0
- Note: 1

## Critical findings

### [H4-adjacent] `engine.py:262-265` — breakeven "return to entry" check is a tautology; forces exit exactly 1 bar after arming regardless of price
**Evidence:**
```
262:    after = np.arange(run_mae.size) > be_hit
263:    be_stop = _first_true(after & (run_mae >= 0.0))
```
`run_mae = np.maximum.accumulate(np.maximum(adverse, 0.0)) / atr` (line 248) is a running
**maximum** of a floor-0 array, so `run_mae[i] >= 0.0` for every index `i` by construction —
it can never go negative and never resets. `after & (run_mae >= 0.0)` therefore reduces
exactly to `after`, and `_first_true` returns `be_hit + 1` unconditionally, i.e. the very
next bar after the MFE-arm bar, for **every** trade that arms breakeven and has not already
hit the real ATR stop. Since `be_stop` then overrides `stop_hit` at line 264 whenever it is
earlier, every armed trade is forcibly closed one bar after arming — the intended "close
only if price actually returns to entry" logic never executes.

**Confirmed with synthetic data** (rally past arm level, pull back, then rally further —
`run_mae` never drops back to reflect the pullback because it is a running high-water mark,
so the trivial condition still fires on the bar immediately after arming, before the real
pullback bar).

**Failure path:** Any `ExitPolicy` with `breakeven_at_atr` set (`breakeven1.0`, `breakeven0.5`
in `screen.py:154-155`; `direction_flip_be0.5` in `composite.py:42-44`) truncates every
armed trade's duration to 1 bar, independent of subsequent price action. `results/stage1_exits.json`
shows `breakeven1.0`/`breakeven0.5` labeling 96-99.5% of trades `STOP` (3411/3541 and
3523/3540) — consistent with nearly every armed trade being force-closed by this bug rather
than by a real stop or a real return to breakeven. This is exactly the "truncates too early"
failure class called out for a negative-result study: it silently collapses the very exit
family designed to let winners run, and the study's negative conclusion about breakeven exits
is not evidence against breakeven exits — it is untested.

**Smallest fix:** compare the **per-bar, non-accumulated** adverse value against 0 (or
against entry) after arming — e.g. `adverse[after_mask] <= 0.0` — not the running maximum,
which can never satisfy a "returned to X" test once it has already exceeded X.

## Warnings
None within scope (A, B, C1-C3, F, G, H) beyond the item above.

## Notes
- `stop_hit`/`target_hit`/`give_hit` themselves compare running MFE/MAE against real
  positive thresholds (not 0), so they are not tautological — the defect is isolated to the
  breakeven branch.

## Referred to contract-checker
- Entry fill uses `checkpoint_reference_price` (last close at the decision second) directly with no next-bar-open shift, while exits enforce a next-bar-open rule — an order-submission-timing question (E4), not a look-ahead defect (the price is causally available at decision time).
- Event-driven exits (`OPPOSING_FLIP`/`SCORE_EXIT`/time-stop, `engine.py:296-312`) fill at the confirming bar's own close rather than the next bar's open — also an E4-territory execution-timing question, not a bracket-trigger issue (H4 correctly enforced for SL/PT/giveback at lines 292-302).
- `composite.py` Stage-2/3 selects a top-6 by discovery-year net_atr and then evaluates on 2024/2025 — walk-forward/selection-seal correctness is C4 (contract-checker), not re-audited here.

## Clean checks
- `engine.simulate` window construction (`index_strictly_after`, entry bar excluded from monitoring window; `index_at_or_after` + session clamp) — A1, A3, F1, F2, H2 verified clean.
- `session_end`/`day_close_ns` clamp correctly prevents the RTH-only path array from running through the overnight gap into the next session (engine.py:228-236) — G2 verified clean.
- SL/TARGET/GIVEBACK detection uses bar HIGH/LOW via running maxima that only include bars up to and including the current index (no future bars in the window); fill index is `idx + 1`, strictly after the trigger bar, and falls back to same-session-only close when no next bar exists — H1, H3, H4 verified clean (excluding the breakeven branch above).
- `RegimeIndex.next_start_after` uses `searchsorted(..., side="right")`, which excludes a regime start at or before the query timestamp from being returned as "next" — verified no lifecycle leak (item 3).
- `candidates.load_scored`: global sort by `checkpoint_decision_ns` precedes all `.over("regime_id")` window ops; `shift(1)` confirmed (synthetic test) to return the temporally previous row within the group, not an arbitrary row; `cum_max` confirmed expanding (inclusive running max), not whole-group — B2, B4 verified clean.
- `reexpansion` family: `probability >= running_max_probability` is not vacuous look-ahead — Polars `cum_max` is inclusive of the current row, so the condition is satisfied exactly when the current row ties/sets a new within-regime high using only rows at or before it; combined with the pullback legs (`prev`, `prev2`), it causally matches its docstring ("re-expanded to a new within-regime high").
- `atr_at_checkpoint` / `checkpoint_reference_price`: traced to `phase_a_strategy.py:162-170` — both are read from strategy state (`self._regime.atr`, `self._last_close`) at the moment `_on_checkpoint` fires for that decision, i.e. available at the decision timestamp, not derived from later bars.
- Timezone handling (`_chicago_minute`, `RTH_CLOSE_MINUTE` boundary) uses named zone `America/Chicago` with explicit UTC conversion for the session-close boundary — F3, F4 verified clean.
- `persistence`, `acceleration`, `age_conditioned`, `spread`, `true_crossing` families: all comparisons use same-row or `shift(k>=1)`/expanding aggregates only — B2, B4 verified clean.

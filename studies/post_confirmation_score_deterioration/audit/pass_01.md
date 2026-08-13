# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-10
**Scope:** implementation/build_panel.py, implementation/phase0_gate1.py, analysis/events.py, analysis/landmark_tradeoff.py, analysis/gate2_ledger.py, analysis/placebo.py
**Scope hash:** 3508292b7112c905b15192be0f4ebc747040f42ff68b29a77c21abe5f2781c56
**Lint:** 0 critical / 0 warning from causal_lint.py (12 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 2

## Highest-priority checks — findings

**1. Terminal leakage.** No flag/event condition reads `terminal_label`, `is_failure`,
`full_mfe_atr`, `terminal_ns`, or `final_pnl_atr`. `full_mfe_atr` and
`full_gross_atr` are joined into panels/snapshots and used only in two legitimate
ways: (a) population stratification of *winners* into MFE buckets for Gate-2
reporting (`events.py:184-209`, `landmark_tradeoff.py:80-115`), and (b)
reconstruction of the counterfactual terminal PnL used solely as the economic
*target* in `gate2_ledger.py`/`placebo.py` deltas — never as a selection
condition. `hold_s > horizon` (`build_panel.py`→`phase0_gate1.py:125`,
`landmark_tradeoff.py:41`, `gate2_ledger.py:67`) is used only as an alive-filter.
This is causally legitimate: "still open at elapsed time `horizon`" is knowable
in real time at that instant (you only need to know the position hasn't yet
closed), unlike `terminal_label` or `full_mfe_atr`, which require observing the
close. Verified clean — this is exactly the SPEC's own landmark methodology
(§2), correctly implemented in all three modules with the same alive-filter
pattern.

**2. Expanding vs whole-window aggregates.** `build_panel.py:148-157`:
`run_mfe_atr`/`run_mae_atr`/`score_b_running_max`/`score_b_running_min` are all
`.cum_max()`/`.cum_min()` `.over("regime_id")`, evaluated on a frame sorted
`["regime_id","checkpoint_decision_ns"]` immediately upstream (line 134); Polars
preserves row order through subsequent `.with_columns()` calls, so these are
correctly expanding-to-date, not whole-window. `events.py:73` (`c_running_max`)
uses the identical pattern. Confirmed clean.

**3. `remaining_mfe_atr`/`max_pnl_after`.** In `events.py:104-123` and
`landmark_tradeoff.py:65-72`, these are computed strictly `> fire_ns` /
`> horizon` and only feed `econ_*` / `median_remaining_mfe_*` reporting fields —
never a `event_specs()` condition or an operating-point selection rule.
Confirmed forward-looking-from-event-only, never forward-looking-from-terminal,
and never a predictor.

**4. `gate2_ledger.py` exit-price algebra.** Predecessor defines
`full_gross_atr = ((exit_price - arm_price) * direction) / arm_atr`
(`armed_fade_score_path_progression/implementation/walks.py:282-283`). Solving:
`exit_price = arm_price + full_gross_atr * arm_atr * direction` (since
`1/direction == direction` for ±1) — matches `gate2_ledger.py:92-93` exactly.
Re-anchoring `final_pnl_atr = (exit_price - confirm_price) * direction /
atr_at_confirmation` (line 95-96) is the correct confirmation-anchored
re-normalization, using the two ATRs (`arm_atr` for the points reconstruction,
`atr_at_confirmation` for the re-anchored ratio) consistently with SPEC §4's
dual-anchor convention. `final_pnl_atr` is used only inside `delta_atr =
open_pnl_atr - final_pnl_atr` in `ledger()` (line 109) and `placebo.py:50,75` —
the counterfactual target, never a predictor or flag input. Confirmed correct
and confirmed target-only.

**5. `placebo.py` control fairness.** RANDOM and WORST_PNL are computed from the
identical `snap` DataFrame used for the score-rule operating point at the same
horizon (`placebo.py:71-99`), with `k = int(sel.sum())` taken directly from the
score selection and both controls drawing exactly `k` from the same `n`-row
alive population. Confirmed matched population and matched flag count — a fair
comparison as SPEC intends.

**6. Panel window / session containment.** `build_panel.py:112-115` filters
`checkpoint_decision_ns` to `[confirm_ns, terminal_ns]` inclusive; no observation
can precede confirmation or follow the terminal event by construction. Scores
table is pre-filtered to `session == "RTH"` (line 92) before the join, so no
non-RTH dispatch can enter the panel. `terminal_ns`/`session_close_ns` are
inherited from the accepted upstream continuation walk (forced-flat 15:00 CT),
not re-derived here — out of this pass's scope to re-audit.

## Polarity (SPEC §1.1) — verified correct
`score_b` = `bullish_probability` if `direction==1` else `bearish_probability`
(`build_panel.py:120-122`) correctly implements "domain-model raw, ungated,
rising = danger". `escalation_from_confirm`/`escalation_from_min` are both
`score_b - <earlier score_b>`, so positive = rising = danger, matching
`ESCALATION_*` event semantics in `events.py:50-52`. Stream C
(`STREAMC_RETREAT_*`) correctly keeps the brief's original (opposite) polarity.
This inverted-polarity design is easy to get backwards silently; it is
implemented correctly in every file that touches it.

## Critical findings
None.

## Warnings
None.

## Notes
- **[N1]** `landmark_tradeoff.py:84-86` / `gate2_ledger.py:106-107` compute the
  score-quantile cutoff from the *full* alive cross-section at each horizon
  (all years 2021-2025 pooled), not a temporally held-out subset. This is not a
  look-ahead within a trade (cross-sectional, not forward-in-time), and the SPEC
  explicitly frames this as characterization ("no cutoff is selected or carried
  forward"), not a deployable trained threshold, so C3 does not bind. Flagging
  for visibility only in case a later phase promotes one of these cutoffs into a
  policy.
- **[N2]** Tie-break policy for duplicate `checkpoint_decision_ns` within a
  `regime_id` is not explicit in the six audited files (relevant to
  `.first()`/`.last()` aggregations in `landmark()`/`snapshot()`). Does not
  change `cum_max`/`cum_min` results (commutative) and SPEC §9 item 7 assigns
  this to `validate.py` (out of scope here). Not a look-ahead defect.

## Referred to contract-checker
None identified in this pass.

## Clean checks
A1-A5 (n/a, no NT strategy/bar code in scope), B1-B7 (expanding aggregates,
no shift(-N)/bfill/center), C1-C3 (labels are terminal-only, landmark design
enforces feature/label separation, no random split used as train/test),
F1-F2 (RTH pre-filter, window bounded to [confirm_ns, terminal_ns]), G1-G4
(upstream canonical store, not re-derived here), H1-H4 (no new bracket/trigger
simulation in these six files — `gate2_ledger.py` reconstructs an
already-computed predecessor result algebraically, not a fresh SL/PT touch
simulation).

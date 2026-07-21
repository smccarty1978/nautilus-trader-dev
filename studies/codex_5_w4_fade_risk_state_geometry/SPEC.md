# codex_5 W4 Fade Risk-State Geometry

## Scope

Stage 1 is retrospective descriptive geometry on the already-frozen repaired
W4 fade entries. It does not simulate a new policy. Stage 2 is permitted only
after a separate audit and may contain at most two frozen paired simulations.

## Stage 1 geometry

- Price units use each trade's `atr_at_checkpoint`, matching its original stop.
- Pre-flip MAE is measured through the first aligning-flip next-open mark for
  trades that reach the flip, or through the stored stop fill for pre-flip stops.
- Pre-stop MFE uses the conservative value that excludes the unknown favorable
  range of the 1-second stop bar.
- Post-flip peaks use causal peak availability (`bar ts_event + 1s`) from the
  audited countertrade-path diagnostic.
- Revisit flags after the peak use raw 1-second OHLC ranges after peak
  availability plus the known stored exit fill. They are retrospective path
  labels and are not live signals.

## Predeclared Stage 2 gate and selection (2025 only)

The 2026 descriptive rows are never read by gate/selection functions.

1. Initial-stop geometry is supportive if 2025 reached-flip p95 pre-flip MAE is
   at most 1.25 ATR.
2. Post-flip geometry is supportive if, in 2025, planned losers have median
   giveback at least 1.0 ATR and at least 50% reach 1.0 ATR post-flip MFE, while
   at least 90% of planned winners reach 1.0 ATR.

If initial-stop geometry passes, select the smallest of 0.75, 1.00, and 1.25 ATR
that would preserve at least 95% of 2025 reached-flip trades. This is one
selection rule, not three policy tests.

If post-flip geometry passes, freeze exactly one candidate: after the aligning
flip, arm when entry-anchored post-flip MFE first reaches 1.0 ATR; protection
becomes active on the next 1-second bar; exit if retained profit touches +0.25
ATR. This rule is predeclared and is not selected from a grid.

No W4 retraining, entry change, or 2026-driven selection is allowed.

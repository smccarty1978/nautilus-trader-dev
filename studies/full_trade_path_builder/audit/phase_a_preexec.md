# Phase A Final Pre-Execution Causal Audit

**Date:** 2026-07-23  
**Scope hash:** `a838824c32f60c61b2a83defa2845ee5b5b8bdd97859b39bf8e2e1d44b3f99fa`  
**Verdict:** **ACCEPTED — 0 CRITICAL, 0 WARNING**

## Findings

- Critical: 0
- Warning: 0
- Note: 0

## Clean checks

- One-second features include only bars satisfying `ts_event < T` and
  `ts_init <= T`.
- Minute features require `ts_init < T`; the minute completing at `T` is
  excluded.
- Decision and availability both equal `T`, dispatched from the completed
  one-second callback with `ts_init == T`.
- Equal-time processing is completed 1s update, checkpoint snapshot, session
  reset, then minute update/flip.
- A minute-confirmed flip at `T` follows the checkpoint and cannot label it as
  a same-time future flip.
- Missing exact dispatch callbacks are omitted without timers, catch-up, or
  off-grid substitution.
- Regime-start ATR is restricted to established-population excursion geometry;
  checkpoint ATR normalizes model features.
- The 08:30 order and RTH accumulator availability are explicit.
- The mutation test rejects premature injection of `ts_event == T`, while
  requiring inclusion of the admissible `ts_init == T`, `ts_event < T` bar.
- Population construction, progress geometry, RTH boundaries, deterministic
  key parity, label/censor arithmetic, thresholds, estimator persistence,
  parity, and sealed-2026 access are frozen.

## Acceptance

The Phase A task packet and configuration satisfy the pre-execution causal gate.
Implementation may proceed through component tests and the staged workflow.
The representative run remains gated behind successful component tests, and
final acceptance requires the mandatory completion audit.

# CODEX 5.X Original W4 Two-Contract PT + Runner Diagnostic

## Frozen population and baselines

The study uses the exact 4,383 original repaired pooled-W4 fills used by the
audited symmetric bracket study (3,246 in 2025; 1,137 in 2026). Entry timestamp,
open, direction, `atr_at_checkpoint`, and frozen opposing-regime-flip horizon
are unchanged. Policy A and the conservative 1.25A bracket are imported and
reconciled exactly.

## Two-contract lifecycle

- Contract 1: +1.25A PT versus -1.25A SL, conservative first touch.
- Contract 2: shares the -1.25A initial SL until it exits; otherwise exits at a
  protective floor (when applicable) or the frozen opposing-flip horizon.
- The runner is a real open contract from entry. Therefore, if the frozen
  horizon occurs before Contract 1 resolves, the runner exits at the horizon
  while Contract 1 continues its independent bracket. This causally covers the
  bracket paths which resolve after the original horizon.
- After PT1, the initial SL is removed from the runner. V0 is then unprotected.

Variants:

- `V0`: no positive runner floor.
- `V75_25`: +0.75A favorable reach arms a +0.25A runner stop.
- `V100_50`: +1.00A favorable reach arms a +0.50A runner stop.

## 1-second ordering

This is an OHLC research simulation, not NT-native or tick-level validation.

1. Frozen horizon exits execute at that timestamp's open before its bar range.
2. Before PT1, a bar touching initial SL and any favorable event is SL-first.
   If that bar opens adversely through the initial stop, both contracts fill at
   the adverse open. The imported pure-bracket baseline remains unchanged and
   is reported separately; the new two-contract simulation uses the executable
   shared-stop gap rule.
3. A floor arms only after the arming bar completes and is active on later bars.
4. If a later bar touches PT1 and an already-active runner floor without touching
   initial SL, PT1 fills first and the runner floor is deferred to later bars.
5. Touched floors fill at the stop unless the bar opens adversely beyond it, in
   which case the adverse open is used.
6. The frozen-horizon bar range is never consumed. For an initial-stop or floor
   exit, the entire exit bar's excursion is excluded because OHLC cannot order
   the stop touch versus that bar's favorable extreme. Giveback is based only on
   excursion causally available before that ambiguous exit bar.
7. A floor exit and +2A/+3A/+4A touch in the same bar are marked unordered and
   excluded from ordered "floor before level" / "future runner clipped" labels.

## Economics

Each contract pays $20/point and incurs $10 round-trip cost. Total trade PnL is
Contract 1 gross plus runner gross minus $20. Decomposition also reports each
leg net of its own $10 cost.

## Isolation

No W4 retraining, entry change, re-entry, delayed confirmation, W4 lifecycle
exit, or new threshold is permitted. 2025 seals before 2026. Results are fixed
diagnostics, not a broad policy search.

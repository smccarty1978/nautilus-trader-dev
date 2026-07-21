# CODEX 5.X Original W4 Symmetric Bracket Race

## Question

For the exact 4,383 frozen original repaired pooled-W4 entries, how often does a
symmetric profit target touch before the same-distance stop?

## Frozen population

- 2025: 3,246 original repaired W4 first-threshold-crossing fills.
- 2026: 1,137 original repaired W4 first-threshold-crossing fills.
- Entry timestamp, entry open, fade direction, and `atr_at_checkpoint` are used
  without regeneration or modification.
- Specialized, side-specific, session-specific, delayed, re-entry, and streaming
  models/policies are excluded.

## Primary race

- PT: `entry + direction * 1.25 * atr_at_checkpoint`.
- SL: `entry - direction * 1.25 * atr_at_checkpoint`.
- Raw 1-second OHLC is scanned from the entry bar forward until either level is
  touched or the available raw year ends.
- Regime flips, timeouts, W4 signals, and portfolio state do not terminate or
  alter the race. Each frozen entry is an independent diagnostic path.

## Same-bar policies

- `conservative`: both levels touched in one 1-second bar is classified SL-first.
- `decisive`: compare favorable versus adverse normalized overshoot beyond the
  symmetric brackets; PT wins only when favorable overshoot is strictly larger.

The conservative 1.25/1.25 result is primary. OHLC cannot establish true
intrabar order; this is a 1-second OHLC research label, not tick-level or
NT-native executable validation.

## Fixed sensitivities

Symmetric 1.00, 1.25, and 1.50 ATR races are reported without selection or
optimization. 2025 is development/validation and must seal before the untouched
2026 run.

## Economics

Each resolved win earns `bracket * ATR * $20 - $10`; each resolved loss earns
`-bracket * ATR * $20 - $10`. Unresolved paths have no invented exit and are
excluded from resolved-trade economics while remaining in all-trade PT rates.
The estimated cost-adjusted breakeven rate respects the observed ATR difference
between winning and losing cohorts. With conditional average gross magnitudes
`W` and `L`, it is `(L + $10) / (W + L)`. This rate is therefore consistent
with the exported realized expectancy even when winners and losers have
different average ATR.

## Tail diagnostic

The primary conservative race outcome is followed diagnostically only until the
frozen original opposing-regime-flip decision horizon. For PT-first trades the
study measures total/additional MFE, 2A/3A/4A reach, original-horizon PnL, and
giveback. It also labels a return to entry before 2A and whether an SL-first path
later reaches the original PT after the resolution bar. These are retrospective
diagnostics, not exit policies.

Post-resolution tail labels are unavailable when the primary bracket resolves
at or after the frozen horizon. If a subsequent 1-second bar touches both entry
and +2A, the ordering label is explicitly intrabar-ambiguous rather than being
forced to reversal-first or runner-first.

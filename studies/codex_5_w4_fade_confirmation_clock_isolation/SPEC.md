# CODEX 5.X W4 Fade Confirmation-Clock Isolation

## Purpose

Attribute the prior Policy A result to its 1.25 ATR pre-flip stop, its five-minute confirmation timeout, or their interaction. The exact repaired 4,383-entry set is fixed. W4 and entry logic are unchanged.

## Frozen policies

- Baseline: 1.50 ATR pre-flip stop, no timeout.
- Policy S: 1.25 ATR pre-flip stop, no timeout.
- Policy T: 1.50 ATR pre-flip stop, 300-second timeout.
- Policy A: 1.25 ATR pre-flip stop, 300-second timeout.

All policies revert to the original 1.50 ATR stop after the first aligning flip and retain the original next-opposing-flip exit. No other policy or parameter is evaluated.

## Execution semantics

The semantics are identical to the audited prior confirmation-clock study:

1. Entry is the stored explicit next raw one-second open.
2. A flip at exactly entry +300 seconds counts as confirmed.
3. If no flip occurs within the enabled timeout, the decision occurs at 300 seconds and fills at the first raw one-second open strictly afterward.
4. The active stop remains live through the timeout-labelled bar and until the market fill.
5. A flip decision changes state before the same-timestamp bar range.
6. Stops are loss-first within ambiguous one-second OHLC bars.
7. Opposing-flip market exits fill at the first available raw open at or after the stored decision, including raw gaps.
8. Stop levels use stored checkpoint ATR; cost is $10 round trip and multiplier is $20 per NQ point.

This is a one-second OHLC research simulation, not NT-native executable validation.

## Attribution

For each sample:

```text
interaction = change(A) - change(S) - change(T)
```

The interaction is labeled "approximately zero; additive" when its absolute combined value is less than or equal to 5% of the smaller absolute combined main-component change. Outside that frozen tolerance it is labeled by sign.

Maximum drawdown is the peak-to-trough decline of cumulative per-trade net PnL in original entry-time order. It is not an intraday marked-to-market portfolio drawdown.

## Time isolation

Policies are frozen before replay. The 2026 path is blocked until exact 2025 artifacts and dependencies reconcile and hash-seal.

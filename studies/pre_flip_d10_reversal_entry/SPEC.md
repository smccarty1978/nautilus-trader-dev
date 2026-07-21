# Pre-Flip D10 Reversal Entry Study

## Hypothesis

The first causal crossing of a validation-frozen top-decile W4 terminal-weakness
score can front-run the next one-minute regime flip profitably, and the same
score in the confirmed new regime can improve the natural opposite-flip exit.

## Population and frozen score

- W4 is refit exactly from the upstream `regime_sequence_chop_context` feature
  manifest on 2021-2024 checkpoints only, with the documented fixed seed 42.
- D10 is an **absolute validation-frozen score threshold**: the 90th percentile
  of W4 probabilities on Jan-Feb 2025 validation checkpoints.
- The threshold is persisted before any 2025/2026 policy economics are run.
- A D10 event is the first causal transition `previous_score < threshold` and
  `current_score >= threshold` within a regime. The first valid score already
  above threshold counts as a crossing from the implicit below-threshold state.

## Execution contracts

The primary result is `EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT`. It is a
chronological one-second OHLC research simulation, not NT-native executable
validation. A causal decision fills at the first adjusted Databento one-second
bar open at or after the decision boundary. The fill-anchored fixed ATR stop is
active from that entry bar open. Each bar is evaluated chronologically. If the
bar opens through the stop it fills at the worse open; otherwise an OHLC stop
touch is labeled at the trigger. Exact intrabar touch time/order is unknown.
When a stop and D10/flip exit occur on the same one-second bar, the stop wins.
The position is not released for a new trade until that touch bar's `ts_init`.
If the exact boundary has no bar, the fill uses the first later available 1s
open. Exact, <=60-second, and >60-second market-data gaps are classified and
reported separately; extended weekend/holiday gaps are not silently discarded.

The appendix contract is `CLOSE_DETECTED_NEXT_NT_FILL_SENSITIVITY`. Consistent
with the isolated fixture, an order submitted at a boundary is modeled with the
prior completed bar close as price and the next bar event as fill timestamp.
Stops are detected only after a completed bar and use that fixture-observed next
NT fill convention. It is sensitivity only and cannot select the main result.

Both use one NQ contract, ETH+RTH, $5 round-trip commission plus one NQ tick of
cost. No tick/quote path exists, so neither OHLC stop label claims exact
fill-anchored executable accuracy.

## Policies

- P0: regime flip entry; opposite regime flip exit.
- P1: old-regime D10 reversal entry; fixed stop; opposite flip after confirmation.
- P2: regime flip entry; confirmed-regime D10 or opposite flip exit.
- P3: old-regime D10 reversal entry; fixed stop; confirmed-regime D10 or flip exit.
- P4A/P4B: matched placebo versions of P1/P3.

P1/P3/P4 allow one attempt per originating regime. Before anticipated-flip
confirmation, the fixed stop is the only exit. The original stop remains active
after confirmation. Open positions at data end are censored.

## Data caveat

Primary 2025 economics begin March 1; Jan-Feb 2025 is threshold calibration and
is excluded from policy economics. The separately referenced
`pre_flip_d10_reversal_investigation(1).md` was not
present in the repository or attachment bundle. The attached Codex implementation
prompt is the authoritative specification for this implementation.

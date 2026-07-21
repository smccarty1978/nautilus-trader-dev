# CODEX 5.X W4 Price-Response Delayed Entry Replay

## Purpose

Run a fixed, causal replay of two delayed-entry gates on the repaired W4 fade
candidate stream. This study tests PR10 and PR30 only. It does not retrain W4,
change the W4 trigger, add an entry filter, or search a threshold.

## Frozen opportunity set

- 4,383 repaired W4 candidate entries: 3,246 in 2025 and 1,137 in 2026.
- Baseline: the exact audited Policy A rows from the confirmation-clock
  isolation study.
- Development/validation: 2025.
- Selection-isolated final description: 2026.

## Causal confirmation clock

For a delay `D` of 10 or 30 seconds:

1. Let `t0` be the original explicit next-open fill timestamp and `p0` its
   stored fill open.
2. The gate decision instant is `tg = t0 + D`.
3. The virtual mark is the close of the latest raw one-second bar whose full
   interval is complete by `tg`: `bar.ts_event + 1 second <= tg`.
4. Virtual directional PnL is `direction * (completed_close - p0)`. No cost is
   included because this is an unexecuted causal state check.
5. Approve only when virtual directional PnL is at least zero.
6. An approved trade fills at the first available raw one-second open with
   `ts_event > tg`. Equality is prohibited so the completed confirmation state
   cannot fill on its own decision instant.
7. Reject if the aligning flip occurs at or before the gate decision, or at or
   before the delayed fill. This also handles a flip hidden inside a raw-data
   gap. The W4 setup is considered unavailable after its prevailing regime
   ends.

The latest completed mark and its staleness are exported. Raw gaps are not
filled or imputed.

## Delayed-entry management

- Entry fill: explicit delayed raw one-second open.
- ATR denominator: frozen `atr_at_checkpoint`, matching Policy A.
- Pre-alignment stop: 1.25 ATR from the delayed fill.
- Post-alignment stop: 1.50 ATR from the delayed fill.
- The stop is submitted at the delayed fill and is active on its entry bar.
- The five-minute timeout is anchored to the delayed fill.
- If no aligning flip occurs by the timeout, exit at the first available raw
  one-second open strictly after the timeout decision.
- If the aligning flip occurs exactly at the timeout, it is confirmed.
- The scheduled opposing regime flip remains the natural planned exit, filled
  at its next available one-second open.
- Stops use the prior conservative OHLC rule: the stop is adverse-first within
  a bar; a gap through a stop fills at the bar open, otherwise at the stop.
- There is no profit target and therefore no stop/target intrabar tie.

## Outputs

- `price_response_trade_diffs.parquet`: one row per candidate and policy.
- `price_response_policy_results.parquet`: baseline/PR10/PR30 required splits.
- `price_response_trade_accounting.parquet`: overlapping requested trade-diff
  classes with paired Policy A and delayed-policy totals.
- `final_report.md`: concise evidence and final decision label.

## Interpretation limits

This is a one-second OHLC research simulation. It is not tick-level path
reconstruction, NT-native executable validation, or an NT-validated strategy.
PR10 and PR30 were predeclared; no 2026 result may select a new rule.

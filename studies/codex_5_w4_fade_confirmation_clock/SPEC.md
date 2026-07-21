# CODEX 5.X W4 Fade Confirmation-Clock Study

## Scope

Paired 1-second OHLC research simulation on the exact repaired CODEX 5.X established-regime fade entries. W4, thresholds, entry timestamps, entry prices, and the entry set are unchanged.

This is not NT-native executable validation and does not claim tick-level intrabar ordering.

## Baseline

The stored repaired W4 policy: 1.50 ATR fill-anchored stop, hold through the first aligning flip, then exit at the next opposing flip.

## Frozen policies

- `POLICY_A_TIMEOUT_300S_STOP_1P25`: 1.25 ATR pre-flip stop. If no aligning flip occurs by entry + 300 seconds, decide to exit and fill at the first available 1-second open strictly after the timeout.
- `POLICY_B_TIMEOUT_300S_MFE_0P75_STOP_1P25`: same as A, except a trade whose completed pre-timeout path reached +0.75 ATR MFE activates an entry +0.75 ATR protective stop at the timeout and continues. The stop persists after a later aligning flip.
- `POLICY_C_TIMEOUT_300S_STOP_1P00`: the single optional controlled variant, identical to A except for a 1.00 ATR pre-flip stop.

No other timeout, stop, target, or protection value is evaluated.

## Event ordering

1. An aligning flip at exactly `entry + 300s` is within the confirmation window.
2. A scheduled opposing-flip exit or previously scheduled timeout market fill occurs at the bar open before that bar's OHLC range.
3. A flip decision at a bar timestamp changes the state before that bar's range.
4. Policy A/C timeout decision occurs at entry + 300s and the market order fills at the first raw bar open strictly later. The current stop remains active until that fill.
5. Policy B qualification uses favorable excursion only from bars with `ts_event < timeout`. Its protective stop becomes active for the OHLC range at the timeout timestamp, or the first available bar afterward. A gap through the floor fills at that bar's open; otherwise a touch fills at the floor.
6. Stops are loss-first versus favorable excursion within the same one-second OHLC bar.
7. Before alignment, the policy stop is 1.25 ATR (A/B) or 1.00 ATR (C). After alignment, A/C use the original 1.50 ATR stop. B retains its +0.75 ATR protected stop if it qualified; otherwise it uses 1.50 ATR.

ATR means the stored `atr_at_checkpoint`, matching the original repaired execution policy and stop price. Round-trip cost is $10 and the NQ multiplier is $20/point.

## Time isolation

Policies and definitions are frozen before simulation. Run 2025 first and hash-seal its paired results. The 2026 runner refuses to execute without that exact predecessor seal. No 2026 value can alter a policy.

## Outputs

- `confirmation_clock_path_diagnostics.parquet`
- `confirmation_clock_diagnostic_summary.parquet`
- `confirmation_clock_policy_trade_diffs.parquet`
- `confirmation_clock_policy_results.parquet`
- `final_report.md`


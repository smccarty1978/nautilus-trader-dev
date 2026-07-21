# Minimal execution-contract report

## Scope

This report isolates execution mechanics only. The D10 reversal policy study was
not run. All contracts use the same four adjusted Databento one-second bars from
`NQ_v0_2025_fixed` (`ts_init = ts_event + 1 second`). The intended long entry is
the next bar open with a one-tick fixed stop, deliberately crossed by the entry
bar low. The path was selected ex post solely to force this diagnostic edge
case; it is not a trade-selection rule or a performance sample.

## Comparison

| contract | decision_timestamp | expected_fill_bar_ts_event | expected_fill_bar_ts_init | expected_fill_open | entry_bar_low | entry_bar_high | stop_trigger_price | entry_bar_crosses_stop | actual_entry_fill_timestamp | actual_entry_fill_price | assumed_entry_fill_timestamp | assumed_entry_fill_price | stop_submission_timestamp | stop_active_on_entry_bar | stop_fill_timestamp | stop_fill_price | gross_pnl_usd | pnl_difference_vs_intended_usd | pnl_basis | evidence_type | assumed_stop_touch_window_start | assumed_stop_touch_window_end | assumed_stop_fill_price | exit_only_normalized_pnl_from_expected_open_usd |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NT native bar matcher | 2025-03-03 23:00:01+00:00 | 2025-03-03 23:00:01+00:00 | 2025-03-03 23:00:02+00:00 | 20511.25 | 20505.25 | 20511.75 | 20511.0 | True | 2025-03-03 23:00:01+00:00 | 20514.25 |  |  | 2025-03-03 23:00:01+00:00 | False | 2025-03-03 23:00:02+00:00 | 20511.0 | -65.0 | -60.0 | engine-observed entry and exit fills | NT BacktestEngine observed |  |  |  |  |
| Explicit next-1s-open + immediate stop | 2025-03-03 23:00:01+00:00 | 2025-03-03 23:00:01+00:00 | 2025-03-03 23:00:02+00:00 | 20511.25 | 20505.25 | 20511.75 | 20511.0 | True |  |  | 2025-03-03 23:00:01+00:00 | 20511.25 | 2025-03-03 23:00:01+00:00 | True |  |  | -5.0 | 0.0 | 1s OHLC label: assumed open entry and adverse-touch stop price; time unknown within bar | 1s OHLC research label; adverse touch assumed, not NT fill | 2025-03-03 23:00:01+00:00 | 2025-03-03 23:00:02+00:00 | 20511.0 |  |
| Close-detected stop + next market fill | 2025-03-03 23:00:01+00:00 | 2025-03-03 23:00:01+00:00 | 2025-03-03 23:00:02+00:00 | 20511.25 | 20505.25 | 20511.75 | 20511.0 | True | 2025-03-03 23:00:01+00:00 | 20514.25 |  |  | 2025-03-03 23:00:02+00:00 | False | 2025-03-03 23:00:02+00:00 | 20508.25 | -120.0 | -115.0 | engine-observed entry and exit fills; normalized exit diagnostic separate | OHLC close detection + NT market-exit fill; delayed-information contract |  |  |  | -60.0 |

## Interpretation

1. **NT native bar matcher:** engine-observed evidence. The entry and stop fills
   are whatever NT actually produced. The stop submitted inside the entry-fill
   callback was not active against the entry bar's already-processing OHLC.
2. **Explicit next-1s-open:** an OHLC research label. It assumes the entry at the
   recorded open and an adverse-touch stop price when the bar crosses it. The
   touch/fill time is unknown inside `[ts_event, ts_init]`; no exact timestamp or
   actual fill is claimed, and intrabar ordering is unresolved.
3. **Close-detected:** stop touch becomes known only at entry-bar close. A market
   exit is then submitted and NT supplies the next fill. Primary PnL uses both
   engine-observed fills, consistently with Contract 1. A separately named
   normalized diagnostic isolates the exit from the entry-price mismatch.

## Limitation

No tick/quote path was used. Therefore this report does not claim fill-anchored
stop accuracy. Contract 2 is a labeled 1s-OHLC assumption; Contract 3 is a
delayed-information convention and is not guaranteed economically conservative
under gaps. The full D10 study remains blocked until
one contract is explicitly selected.

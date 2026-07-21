# Execution Audit — Phase 3 baseline sanity (2024)

Strategy: bar-4 all-flips, GTC market orders, state-gated opposite-regime exit. No ML, no hC mgmt.

## Execution integrity (HARD INVARIANT)
- market_order_confirmed = **True** (47128/47128 orders are MARKET)
- FOK_order_count = **0** PASS
- IOC_order_count = **0** PASS
- opposite_regime_seen_count = 23564
- exit_submitted_count = 23564
- exit_filled_count = 23564
- max_bars_after_opposite_regime = **0**
- count_delay_gt_1 = **0** PASS

## Run validity: **VALID**

## Universe / mapping coverage (join rate)
- bar-4 flips entered (total) = 23,564
- of which found in pQF mapping = 20,141 (**85.5%** join rate on regime_start_ts)
  - <80% would indicate the capsule is a filtered subset of the live NT flip universe.

## Activity
- n_trades = 23,564 | entries_filled = -
- add_count = 0 | reduce_count = 0 | sizing_count = 0
- net PnL = $-443,565 | $/trade = $-18.82
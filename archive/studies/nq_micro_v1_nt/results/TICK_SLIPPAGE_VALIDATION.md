# Tick-Data Slippage Validation — NQ Feb-Sep 2025

Validates the cost model used in the NT runtime filtered backtest by replaying actual NQ trade ticks against the trade record from the filtered run (`flip2conf_dir_efficiency >= 0.30`, NQ RTH).

Window extended from the user-requested 1-month (Feb 2025 had only 23 filtered trades) to the full 8 months Feb-Sep 2025 covered by the available tick file. February alone is reported separately for transparency.

## Setup

- Source trades: `collectors\collector_v2\results\filtered_f2c30\NQ_2025\trades.parquet` filtered to Feb-Sep 2025 RTH
- Tick data: `data\raw\NQ_trades_20250201_20250930.parquet` (Feb-Sep 2025 slice, 59,307,727 trade ticks)
- Reconstruction: for each trade's entry_ts and exit_ts, find the first market-trade tick at or after that timestamp. Use that tick's price as the realized fill.
- Cost model under test: $5 commission/round-trip + $5 tick = $10/trade.

## Sample size

- 238 candidate filtered NQ RTH trades in Feb-Sep 2025
- 7 excluded for tick-data gap (no tick within 5.0s of order ts — indicates a market-data hole, not real slippage)
- **231 valid trades** for slippage measurement

Per-month breakdown:

| Month | n | NT mean $ | Tick mean $ | Round-trip slip $ |
|---|--:|--:|--:|--:|
| 2025-02 | 23 | $-160.43 | $-153.04 | $-2.39 |
| 2025-03 | 30 | $-74.83 | $-65.83 | $-4.00 |
| 2025-04 | 25 | $1,450 | $1,459 | $-4.20 |
| 2025-05 | 25 | $210.40 | $210.60 | $4.80 |
| 2025-06 | 33 | $-170.15 | $-166.52 | $1.36 |
| 2025-07 | 30 | $119.17 | $123.50 | $0.67 |
| 2025-08 | 22 | $-48.41 | $-44.77 | $1.36 |
| 2025-09 | 43 | $-25.00 | $-21.63 | $1.63 |

## Order-to-fill latency (gap from order ts to next tick)

| Quantile | Entry latency (s) | Exit latency (s) |
|---|--:|--:|
| p50 | 0.0848 | 0.0888 |
| p90 | 0.6872 | 0.5369 |
| p99 | 4.3033 | 2.4601 |
| max | 4.8971 | 3.2119 |

## Per-side slippage (ticks)

Positive = adverse (paid worse than the NT bar).

| Quantile | Entry slip (ticks) | Exit slip (ticks) | Entry $ | Exit $ |
|---|--:|--:|--:|--:|
| p5 | -4.00 | -5.00 | $-20.00 | $-25.00 |
| p25 | -1.00 | -2.00 | $-5.00 | $-10.00 |
| p50 | +0.00 | +0.00 | $0.00 | $0.00 |
| p75 | +1.00 | +1.00 | $5.00 | $5.00 |
| p95 | +5.00 | +4.00 | $25.00 | $20.00 |
| mean | +15.372 | -15.368 | $76.86 | $-76.84 |
| stddev | 190.190 | 190.181 | $950.95 | $950.90 |

- **Mean round-trip slippage** (entry + exit): $0.02
- **Cost model assumption**: $5.0 (1 NQ tick) per trade round-trip
- **Cost model is CONSERVATIVE** by $4.98

## PnL comparison

| Series | n | Mean $ | Total $ | WR |
|---|--:|--:|--:|--:|
| NT bar net (cost model: $5 commission + $5 tick) | 231 | $135.93 | $31,400 | 34.63% |
| NT bar net (cost: $5 commission only, no tick cost) | 231 | $140.93 | $32,555 | 35.06% |
| Tick-reconstructed net ($5 commission only) | 231 | $140.91 | $32,550 | 35.50% |

- **Δ per-trade (tick - NT model)**: $4.98
- **Δ total Feb-Sep 2025 (tick - NT model)**: $1,150

- Trades better under tick reconstruction: 131/231
- Trades worse under tick reconstruction: 69/231

## Verdict

✅ **Cost model is realistic.** Tick-reconstructed PnL deviates by $4.98 per trade from NT model (within $5 = 1 tick).

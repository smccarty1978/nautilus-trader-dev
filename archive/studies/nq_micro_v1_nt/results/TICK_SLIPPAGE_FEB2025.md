# Tick-Data Slippage Validation — NQ Feb 2025

Validates the cost model used in the NT runtime filtered backtest by replaying actual NQ trade ticks for February 2025 against the trade record from the filtered run (`flip2conf_dir_efficiency >= 0.30`, NQ RTH).

## Setup

- Source trades: `collectors\collector_v2\results\filtered_f2c30\NQ_2025\trades.parquet` filtered to Feb 2025 RTH
- Tick data: `data\raw\NQ_trades_20250201_20250930.parquet` (Feb 2025 slice, 7,687,450 trade ticks)
- Reconstruction: for each trade's entry_ts and exit_ts, find the first market-trade tick at or after that timestamp. Use that tick's price as the realized fill.
- Cost model under test: $5 commission/round-trip + $5 tick = $10/trade.

## Sample size

- 23 filtered NQ RTH trades in Feb 2025

## Order-to-fill latency (gap from order ts to next tick)

| Quantile | Entry latency (s) | Exit latency (s) |
|---|--:|--:|
| p50 | 0.0347 | 0.0524 |
| p90 | 0.2631 | 0.2269 |
| p99 | 0.3796 | 0.6842 |
| max | 0.4007 | 0.7028 |

## Per-side slippage (ticks)

Positive = adverse (paid worse than the NT bar).

| Quantile | Entry slip (ticks) | Exit slip (ticks) | Entry $ | Exit $ |
|---|--:|--:|--:|--:|
| p5 | -2.90 | -3.00 | $-14.50 | $-15.00 |
| p25 | -2.00 | -2.00 | $-10.00 | $-10.00 |
| p50 | +0.00 | -1.00 | $0.00 | $-5.00 |
| p75 | +1.00 | +0.50 | $5.00 | $2.50 |
| p95 | +2.00 | +4.90 | $10.00 | $24.50 |
| mean | -0.217 | -0.217 | $-1.09 | $-1.09 |
| stddev | 1.882 | 2.938 | $9.41 | $14.69 |

- **Mean round-trip slippage** (entry + exit): $-2.17
- **Cost model assumption**: $5.0 (1 NQ tick) per trade round-trip
- **Cost model is CONSERVATIVE** by $7.17

## PnL comparison

| Series | n | Mean $ | Total $ | WR |
|---|--:|--:|--:|--:|
| NT bar net (cost model: $5 commission + $5 tick) | 23 | $-160.43 | $-3,690 | 30.43% |
| NT bar net (cost: $5 commission only, no tick cost) | 23 | $-155.43 | $-3,575 | 30.43% |
| Tick-reconstructed net ($5 commission only) | 23 | $-153.26 | $-3,525 | 30.43% |

- **Δ per-trade (tick - NT model)**: $7.17
- **Δ total Feb 2025 (tick - NT model)**: $165.00

- Trades better under tick reconstruction: 15/23
- Trades worse under tick reconstruction: 5/23

## Verdict

✅ **Cost model is CONSERVATIVE** — real slippage is smaller than assumed. Existing backtest economics are pessimistic; real-world results would be slightly better.

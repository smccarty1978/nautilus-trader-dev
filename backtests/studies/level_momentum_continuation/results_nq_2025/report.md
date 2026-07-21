# Level Momentum Continuation — NQ 2025

Run: 2026-05-01T20:56:42.845632+00:00

## Source
- File: `data\raw\NQ_v0_1s_2025.parquet`
- Symbol: NQ.v.0 (volume-roll continuous)
- Schema: ohlcv-1s, resampled to 1m
- 1s bars: 12,083,801
- 1m bars: 351,189 (RTH=98,096, ETH=253,093)

## Method
- Levels: 00, 11, 25, 50, 75, 90 within each 100-pt handle; sequence wraps across handles
- Long trigger: 1m close strictly above a level where prior close was below
- Short trigger: 1m close strictly below a level where prior close was above
- Goldilocks filter: close must lie strictly in the LOWER half of the move toward (next level - 10 ticks)
- Multi-level breach in single bar: take the LATEST qualifying level (highest for long, lowest for short)
- Re-entry: every Goldilocks-qualifying close is an independent trigger
- Entry: open of the bar AFTER the trigger (causal)
- Stop: level ONE PRIOR in sequence (e.g. long 50→75 stops at 25)
- Exit priority within a bar: stop-out beats target (conservative)
- Time limit: 120 bars (120 min); marked to bar-120 close at expiry

## Roll discontinuity finding
Empirical check on NQ.v.0 1s data resampled to 1m: quarterly rolls produce single-bar gaps of ~200-242 pts (similar magnitude and dates as .c.0). The 4 rolls in 2025: 
- 2025-03-19 19:01 CT: 200.75 pt gap
- 2025-06-22 17:00 CT: 275.00 pt gap (also captured as roll-window contamination)
- 2025-09-17 19:00 CT: 242.75 pt gap
- 2025-12-16 18:00 CT: 237.50 pt gap

The Goldilocks filter naturally rejects entries ON these gap bars (close is far past the midpoint), but trades that were already OPEN when a roll occurs can be falsely closed at target/stop by the gap. Two passes are reported below to quantify the contamination.

## UNFILTERED (per user spec)
- Triggers detected: 58,831
- Trades simulated: 58,831
- **Win rate: 59.93%**
- Loss rate: 38.74%
- Timed-out: 1.34%  (positive: 325, negative: 448)
- Avg time to target (winners): 10.5 min
- Mean PnL: -0.24 pts/trade  (median 6.50)
- Mean MAE (all): 13.71 pts; wins-only 6.60; losses-only 24.62

### By session

| Session | n | WinR | LossR | TimedOut | MeanPnL | AvgTimeToTgt(min) | MeanMAE(all) |
|---|--:|--:|--:|--:|--:|--:|--:|
| ETH | 35,446 | 59.47% | 38.40% | 2.13% | -0.12 | 14.1 | 12.88 |
| RTH | 23,385 | 60.62% | 39.25% | 0.13% | -0.42 | 5.1 | 14.96 |

### By level pair (overall, sorted by n)

| Pair | n | WinR | LossR | TimedOut | MeanPnL | AvgTime(min) | MeanMAE |
|---|--:|--:|--:|--:|--:|--:|--:|
| 75->50_short | 6,089 | 47.61% | 50.99% | 1.40% | -0.41 | 14.5 | 15.88 |
| 25->50_long | 6,067 | 47.49% | 51.11% | 1.40% | 0.09 | 14.2 | 15.19 |
| 50->75_long | 6,028 | 56.98% | 39.10% | 3.92% | -0.49 | 16.8 | 19.60 |
| 50->25_short | 5,891 | 59.41% | 36.56% | 4.02% | 0.67 | 16.5 | 18.81 |
| 75->90_long | 4,968 | 71.70% | 26.85% | 1.45% | -0.22 | 11.7 | 15.16 |
| 90->75_short | 4,962 | 52.38% | 47.62% | 0.00% | -0.60 | 7.1 | 10.56 |
| 11->25_long | 4,854 | 56.76% | 43.20% | 0.04% | -0.42 | 7.4 | 10.59 |
| 25->11_short | 4,522 | 73.82% | 24.88% | 1.30% | -0.07 | 9.6 | 14.19 |
| 00->11_long | 3,999 | 61.67% | 38.21% | 0.13% | -0.36 | 5.4 | 9.01 |
| 11->00_short | 3,980 | 67.94% | 31.98% | 0.08% | -0.33 | 6.2 | 10.18 |
| 90->00_long | 3,860 | 71.32% | 28.68% | 0.00% | -0.52 | 6.3 | 9.73 |
| 00->90_short | 3,611 | 65.47% | 34.48% | 0.06% | -0.49 | 4.7 | 8.65 |

### By level pair × session

| Pair | Session | n | WinR | LossR | TimedOut | MeanPnL | AvgTime(min) |
|---|---|--:|--:|--:|--:|--:|--:|
| 00->11_long | ETH | 2,494 | 62.19% | 37.61% | 0.20% | -0.15 | 7.0 |
| 00->11_long | RTH | 1,505 | 60.80% | 39.20% | 0.00% | -0.70 | 2.6 |
| 00->90_short | ETH | 2,314 | 67.20% | 32.71% | 0.09% | -0.11 | 6.1 |
| 00->90_short | RTH | 1,297 | 62.37% | 37.63% | 0.00% | -1.15 | 2.1 |
| 11->00_short | ETH | 2,509 | 68.87% | 31.01% | 0.12% | 0.00 | 8.1 |
| 11->00_short | RTH | 1,471 | 66.35% | 33.65% | 0.00% | -0.91 | 2.7 |
| 11->25_long | ETH | 3,000 | 56.50% | 43.43% | 0.07% | -0.27 | 10.1 |
| 11->25_long | RTH | 1,854 | 57.17% | 42.83% | 0.00% | -0.67 | 3.2 |
| 25->11_short | ETH | 2,751 | 73.14% | 24.72% | 2.14% | 0.00 | 13.0 |
| 25->11_short | RTH | 1,771 | 74.87% | 25.13% | 0.00% | -0.18 | 4.4 |
| 25->50_long | ETH | 3,367 | 45.53% | 51.98% | 2.49% | 0.11 | 20.6 |
| 25->50_long | RTH | 2,700 | 49.93% | 50.04% | 0.04% | 0.06 | 6.9 |
| 50->25_short | ETH | 3,294 | 56.13% | 37.07% | 6.80% | 0.36 | 24.0 |
| 50->25_short | RTH | 2,597 | 63.57% | 35.93% | 0.50% | 1.06 | 8.0 |
| 50->75_long | ETH | 3,372 | 55.49% | 37.96% | 6.55% | -0.04 | 24.0 |
| 50->75_long | RTH | 2,656 | 58.89% | 40.55% | 0.56% | -1.06 | 8.0 |
| 75->50_short | ETH | 3,532 | 45.50% | 52.10% | 2.41% | -0.50 | 20.8 |
| 75->50_short | RTH | 2,557 | 50.53% | 49.47% | 0.00% | -0.29 | 6.6 |
| 75->90_long | ETH | 3,058 | 70.96% | 26.75% | 2.29% | -0.10 | 15.6 |
| 75->90_long | RTH | 1,910 | 72.88% | 27.02% | 0.10% | -0.42 | 5.5 |
| 90->00_long | ETH | 2,593 | 71.58% | 28.42% | 0.00% | -0.38 | 8.1 |
| 90->00_long | RTH | 1,267 | 70.80% | 29.20% | 0.00% | -0.82 | 2.5 |
| 90->75_short | ETH | 3,162 | 52.31% | 47.69% | 0.00% | -0.38 | 9.6 |
| 90->75_short | RTH | 1,800 | 52.50% | 47.50% | 0.00% | -1.00 | 2.6 |

## ROLL-FILTERED (±3 days around quarterly rolls)
- Triggers detected: 54,227
- Trades simulated: 54,227
- **Win rate: 59.88%**
- Loss rate: 38.73%
- Timed-out: 1.39%  (positive: 315, negative: 428)
- Avg time to target (winners): 10.4 min
- Mean PnL: -0.24 pts/trade  (median 6.25)
- Mean MAE (all): 13.81 pts; wins-only 6.61; losses-only 24.85

### By session

| Session | n | WinR | LossR | TimedOut | MeanPnL | AvgTimeToTgt(min) | MeanMAE(all) |
|---|--:|--:|--:|--:|--:|--:|--:|
| ETH | 32,697 | 59.44% | 38.35% | 2.21% | -0.12 | 14.0 | 13.02 |
| RTH | 21,530 | 60.56% | 39.30% | 0.14% | -0.43 | 5.0 | 14.99 |

### By level pair (overall, sorted by n)

| Pair | n | WinR | LossR | TimedOut | MeanPnL | AvgTime(min) | MeanMAE |
|---|--:|--:|--:|--:|--:|--:|--:|
| 25->50_long | 5,624 | 47.14% | 51.44% | 1.42% | -0.04 | 14.1 | 15.28 |
| 75->50_short | 5,608 | 47.54% | 51.03% | 1.43% | -0.43 | 14.3 | 16.21 |
| 50->75_long | 5,548 | 56.56% | 39.38% | 4.06% | -0.66 | 16.7 | 19.76 |
| 50->25_short | 5,424 | 59.57% | 36.15% | 4.28% | 0.78 | 16.4 | 18.77 |
| 75->90_long | 4,549 | 71.99% | 26.47% | 1.54% | -0.05 | 11.4 | 15.03 |
| 90->75_short | 4,534 | 52.43% | 47.57% | 0.00% | -0.60 | 6.9 | 10.58 |
| 11->25_long | 4,502 | 56.15% | 43.80% | 0.04% | -0.57 | 7.5 | 10.69 |
| 25->11_short | 4,172 | 74.14% | 24.54% | 1.32% | 0.05 | 9.8 | 14.75 |
| 00->11_long | 3,705 | 61.94% | 37.92% | 0.13% | -0.32 | 5.4 | 9.04 |
| 11->00_short | 3,688 | 67.81% | 32.10% | 0.08% | -0.36 | 6.2 | 10.20 |
| 90->00_long | 3,532 | 71.83% | 28.17% | 0.00% | -0.42 | 6.1 | 9.65 |
| 00->90_short | 3,341 | 65.28% | 34.66% | 0.06% | -0.52 | 4.6 | 8.74 |

### By level pair × session

| Pair | Session | n | WinR | LossR | TimedOut | MeanPnL | AvgTime(min) |
|---|---|--:|--:|--:|--:|--:|--:|
| 00->11_long | ETH | 2,299 | 62.51% | 37.28% | 0.22% | -0.10 | 7.1 |
| 00->11_long | RTH | 1,406 | 61.02% | 38.98% | 0.00% | -0.66 | 2.7 |
| 00->90_short | ETH | 2,130 | 67.14% | 32.77% | 0.09% | -0.12 | 6.0 |
| 00->90_short | RTH | 1,211 | 62.01% | 37.99% | 0.00% | -1.21 | 2.1 |
| 11->00_short | ETH | 2,323 | 68.79% | 31.08% | 0.13% | -0.02 | 8.2 |
| 11->00_short | RTH | 1,365 | 66.15% | 33.85% | 0.00% | -0.93 | 2.8 |
| 11->25_long | ETH | 2,772 | 55.99% | 43.94% | 0.07% | -0.40 | 10.1 |
| 11->25_long | RTH | 1,730 | 56.42% | 43.58% | 0.00% | -0.83 | 3.3 |
| 25->11_short | ETH | 2,543 | 73.61% | 24.22% | 2.16% | 0.18 | 13.3 |
| 25->11_short | RTH | 1,629 | 74.95% | 25.05% | 0.00% | -0.14 | 4.5 |
| 25->50_long | ETH | 3,123 | 44.89% | 52.58% | 2.53% | -0.13 | 20.3 |
| 25->50_long | RTH | 2,501 | 49.94% | 50.02% | 0.04% | 0.07 | 7.1 |
| 50->25_short | ETH | 3,040 | 56.35% | 36.45% | 7.20% | 0.54 | 23.8 |
| 50->25_short | RTH | 2,384 | 63.67% | 35.78% | 0.55% | 1.08 | 8.0 |
| 50->75_long | ETH | 3,112 | 54.82% | 38.43% | 6.75% | -0.31 | 24.1 |
| 50->75_long | RTH | 2,436 | 58.78% | 40.60% | 0.62% | -1.10 | 7.9 |
| 75->50_short | ETH | 3,274 | 45.69% | 51.86% | 2.44% | -0.43 | 20.7 |
| 75->50_short | RTH | 2,334 | 50.13% | 49.87% | 0.00% | -0.43 | 6.1 |
| 75->90_long | ETH | 2,821 | 71.25% | 26.34% | 2.41% | 0.11 | 15.3 |
| 75->90_long | RTH | 1,728 | 73.21% | 26.68% | 0.12% | -0.30 | 5.3 |
| 90->00_long | ETH | 2,363 | 71.82% | 28.18% | 0.00% | -0.33 | 7.8 |
| 90->00_long | RTH | 1,169 | 71.86% | 28.14% | 0.00% | -0.60 | 2.5 |
| 90->75_short | ETH | 2,897 | 52.54% | 47.46% | 0.00% | -0.35 | 9.3 |
| 90->75_short | RTH | 1,637 | 52.23% | 47.77% | 0.00% | -1.04 | 2.6 |

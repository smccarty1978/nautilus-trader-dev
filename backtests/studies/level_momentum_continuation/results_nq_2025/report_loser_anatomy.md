# Loser & Timeout Anatomy — Level Momentum Study

Source: `studies\level_momentum_continuation\results_nq_2025\trades_with_first_bar.csv` | Losers n=22,789, Timeouts n=786

## Method

For each LOSER (outcome='loss', stopped at original 'one prior in sequence' stop) and each TIMEOUT (outcome='timed_out'), re-walk all bars from entry to exit and compute:
- **MFE** (max favorable excursion): the best the trade ever was, in trade direction.
- **MAE** (max adverse excursion): the worst it ever was. For losers this should ≈ original stop distance.
- **mfe/mae ratio**: did the trade ever look like a winner before reversing?
- **% with MFE ≥ X**: how often did losers reach X pts favorable at any point during the trade?

## Losers — overall

- n = 22,789
- MFE: mean=5.95, p50=4.25, p75=8.00, p90=13.50, p95=16.75, max=231.75
- MAE: mean=24.62, p50=21.50, p90=36.50, p95=42.50
- MFE/MAE ratio: median=0.192, mean=0.265
- % of losers with MFE >= threshold:
  - >= 2.5 pt: 68.1%
  - >= 5.0 pt: 45.2%
  - >= 7.5 pt: 28.3%
  - >= 10.0 pt: 18.3%
  - >= 15.0 pt: 7.6%
  - >= 20.0 pt: 2.1%

## Timeouts — overall

- n = 786
- MFE: mean=11.90, p50=12.00, p90=18.88, p95=20.00, max=22.75
- MAE: mean=16.03, p50=16.25, p90=24.88, p95=26.25
- MFE/MAE ratio: median=0.740, mean=1.287
- % of timeouts with MFE >= threshold:
  - >= 2.5 pt: 96.3%
  - >= 5.0 pt: 88.7%
  - >= 7.5 pt: 76.1%
  - >= 10.0 pt: 62.2%
  - >= 15.0 pt: 34.1%
  - >= 20.0 pt: 5.6%

## Losers — by pair × session

| Pair | Session | n | MFE p50 | p75 | p90 | p95 | MFE mean | MAE mean | MFE/MAE | %MFE≥5 | %MFE≥10 | %MFE≥15 |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 00->11_long | ETH | 938 | 2.50 | 4.50 | 6.50 | 7.75 | 3.29 | 15.29 | 0.224 | 21.4% | 3.3% | 1.9% |
| 00->11_long | RTH | 590 | 3.25 | 5.50 | 10.00 | 14.96 | 5.13 | 19.51 | 0.290 | 30.7% | 10.3% | 5.1% |
| 00->90_short | ETH | 757 | 2.50 | 4.25 | 5.75 | 6.25 | 2.93 | 15.70 | 0.196 | 18.0% | 1.6% | 0.7% |
| 00->90_short | RTH | 488 | 3.25 | 6.25 | 12.50 | 17.24 | 5.49 | 19.63 | 0.297 | 32.6% | 13.9% | 7.2% |
| 11->00_short | ETH | 778 | 2.75 | 4.50 | 6.25 | 7.00 | 3.09 | 19.74 | 0.170 | 22.0% | 0.5% | 0.3% |
| 11->00_short | RTH | 495 | 3.25 | 6.00 | 11.80 | 17.15 | 5.43 | 23.38 | 0.240 | 31.9% | 12.7% | 7.1% |
| 11->25_long | ETH | 1,303 | 3.50 | 6.00 | 8.25 | 9.25 | 4.03 | 16.99 | 0.256 | 34.3% | 3.1% | 0.5% |
| 11->25_long | RTH | 794 | 4.00 | 6.75 | 10.25 | 16.34 | 5.87 | 20.67 | 0.302 | 44.0% | 11.5% | 6.0% |
| 25->11_short | ETH | 680 | 3.88 | 6.75 | 8.75 | 9.75 | 4.90 | 32.88 | 0.153 | 40.0% | 4.9% | 2.4% |
| 25->11_short | RTH | 445 | 3.75 | 6.75 | 9.00 | 10.25 | 4.76 | 33.48 | 0.143 | 40.7% | 6.3% | 2.9% |
| 25->50_long | ETH | 1,750 | 5.75 | 10.50 | 15.75 | 18.00 | 7.18 | 21.68 | 0.354 | 56.4% | 28.2% | 12.5% |
| 25->50_long | RTH | 1,351 | 6.25 | 11.50 | 16.25 | 18.12 | 7.62 | 25.21 | 0.340 | 57.6% | 32.1% | 13.7% |
| 50->25_short | ETH | 1,221 | 6.50 | 11.75 | 16.50 | 18.50 | 7.64 | 32.61 | 0.244 | 58.6% | 31.9% | 14.9% |
| 50->25_short | RTH | 933 | 7.25 | 12.00 | 16.00 | 18.10 | 7.92 | 35.78 | 0.234 | 64.0% | 34.7% | 12.9% |
| 50->75_long | ETH | 1,280 | 6.50 | 11.75 | 16.00 | 18.25 | 7.83 | 33.62 | 0.242 | 59.6% | 31.9% | 13.0% |
| 50->75_long | RTH | 1,077 | 6.75 | 12.00 | 16.00 | 18.25 | 7.85 | 35.71 | 0.233 | 60.1% | 34.5% | 14.4% |
| 75->50_short | ETH | 1,840 | 5.75 | 11.06 | 15.75 | 18.25 | 7.28 | 22.91 | 0.347 | 56.7% | 30.1% | 12.0% |
| 75->50_short | RTH | 1,265 | 6.50 | 11.25 | 15.75 | 18.25 | 7.82 | 26.04 | 0.333 | 60.8% | 31.7% | 11.9% |
| 75->90_long | ETH | 818 | 4.50 | 7.25 | 9.83 | 11.25 | 6.16 | 33.15 | 0.196 | 46.1% | 10.0% | 2.6% |
| 75->90_long | RTH | 516 | 4.25 | 6.81 | 9.38 | 10.75 | 5.25 | 35.18 | 0.150 | 45.0% | 7.8% | 1.4% |
| 90->00_long | ETH | 737 | 2.50 | 4.00 | 5.50 | 6.25 | 2.81 | 20.09 | 0.149 | 14.8% | 1.4% | 0.5% |
| 90->00_long | RTH | 370 | 2.75 | 4.69 | 6.50 | 14.89 | 4.09 | 23.63 | 0.182 | 21.4% | 7.6% | 5.1% |
| 90->75_short | ETH | 1,508 | 3.50 | 6.25 | 8.75 | 10.00 | 4.39 | 15.97 | 0.302 | 38.3% | 5.8% | 1.3% |
| 90->75_short | RTH | 855 | 3.75 | 7.25 | 10.50 | 16.82 | 5.62 | 19.16 | 0.326 | 42.1% | 12.5% | 5.8% |

## Timeouts — by pair × session (non-empty cells)

| Pair | Session | n | MFE p50 | p75 | p90 | MFE mean | MAE mean | MFE/MAE | %MFE≥5 | %MFE≥10 | %MFE≥15 |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 25->11_short | ETH | 59 | 6.75 | 7.88 | 9.50 | 6.59 | 17.34 | 0.504 | 81.4% | 6.8% | 0.0% |
| 25->50_long | ETH | 84 | 15.25 | 17.56 | 19.53 | 14.17 | 9.81 | 2.837 | 92.9% | 84.5% | 52.4% |
| 50->25_short | ETH | 224 | 13.88 | 17.00 | 19.00 | 12.94 | 16.45 | 1.476 | 92.9% | 71.9% | 40.6% |
| 50->75_long | ETH | 221 | 13.00 | 16.75 | 19.00 | 11.94 | 18.15 | 0.940 | 82.8% | 64.3% | 36.2% |
| 75->50_short | ETH | 85 | 14.00 | 16.50 | 18.25 | 13.56 | 11.80 | 1.596 | 98.8% | 80.0% | 38.8% |
| 75->90_long | ETH | 70 | 8.12 | 9.25 | 11.28 | 7.34 | 18.12 | 0.502 | 78.6% | 20.0% | 0.0% |

## Interpretation guide

- **High MFE losers** = trades that DID move in our favor before reversing. A move-to-BE or trailing stop could have saved many. Pairs with high `%MFE≥5pt` for losers are candidates for breakeven-stop rules.
- **Low MFE losers** = trades that immediately went against us. The entry signal was wrong. No exit rule saves these.
- **MFE/MAE ratio < 0.5** = losers were never close to their target. Tightening stop helps; can't 'save' these with a partial exit.
- **MFE/MAE ratio > 0.7** = losers got fairly close to winning. A trailing stop or move-to-BE after MFE = X is worth testing.

# First-Bar MFE/MAE Analysis — Level Momentum Study

Source trades: `studies\level_momentum_continuation\results_nq_2025\trades_unfiltered.csv` | n=58,831

## Method

- 'First bar' = the bar AFTER the trigger bar (entry happens at this bar's open).
- **first_bar_MFE** = within this bar, how far did price move favorably for the trade direction (high-open for long, open-low for short)?
- **first_bar_MAE** = within this bar, how far adverse (open-low for long, high-open for short)?
- **first_bar_winner** = did the bar's CLOSE move favorably vs OPEN? Equivalent to a 1-bar holding-period outcome.
- **P(trade_win | first_bar_win)** = of trades whose first bar closed favorably, what fraction eventually hit the level target?
- **P(trade_win | first_bar_loss)** = of trades whose first bar closed unfavorably, what fraction still hit target.
- **lift** = the difference. Positive lift means first-bar outcome predicts the trade outcome (could be a useful early filter).

## Overall (all trades)

- n = 58,831
- **First-bar winner% (close > open in dir): 48.1%**
- Full-trade winner% (target hit before stop): 59.9%
- First-bar mean MFE: 6.12 pts (median 3.50, p90 14.50)
- First-bar mean MAE: 5.96 pts (median 3.50, p90 14.00)
- Mean close-move (signed by direction): -0.026 pts
- **P(trade_win | first_bar_win) = 77.9%**
- **P(trade_win | first_bar_loss) = 44.8%**
- **First-bar filter lift: 33.0%**

## By session

| Session | n | 1st-bar Win% | Full Win% | 1st MFE | 1st MAE | Mean Close-Move | P(W\|1st W) | P(W\|1st L) | Lift |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| ETH | 35,446 | 47.7% | 59.5% | 4.34 | 4.11 | +0.036 | 74.7% | 48.0% | 26.7% |
| RTH | 23,385 | 48.7% | 60.6% | 8.82 | 8.76 | -0.121 | 82.4% | 40.1% | 42.4% |

## By pair (overall)

| Pair | n | 1st-bar Win% | Full Win% | 1st MFE | 1st MAE | Mean Move | P(W\|1st W) | P(W\|1st L) | Lift |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 90->75_short | 4,962 | 47.2% | 52.4% | 5.98 | 5.78 | -0.112 | 74.4% | 32.8% | 41.6% |
| 00->90_short | 3,611 | 49.0% | 65.5% | 5.80 | 5.30 | +0.215 | 86.7% | 45.2% | 41.5% |
| 00->11_long | 3,999 | 48.3% | 61.7% | 5.28 | 5.43 | -0.178 | 82.8% | 42.1% | 40.7% |
| 11->25_long | 4,854 | 49.0% | 56.8% | 5.73 | 5.50 | +0.184 | 76.0% | 38.3% | 37.7% |
| 11->00_short | 3,980 | 47.0% | 67.9% | 5.71 | 5.56 | -0.134 | 87.0% | 51.1% | 35.9% |
| 90->00_long | 3,860 | 47.0% | 71.3% | 4.95 | 5.04 | -0.210 | 89.0% | 55.6% | 33.4% |
| 25->50_long | 6,067 | 48.7% | 47.5% | 6.58 | 6.57 | -0.074 | 65.2% | 32.0% | 33.2% |
| 75->50_short | 6,089 | 47.7% | 47.6% | 6.84 | 6.74 | -0.220 | 65.1% | 32.9% | 32.2% |
| 50->75_long | 6,028 | 49.0% | 57.0% | 6.55 | 6.44 | +0.124 | 73.8% | 45.2% | 28.7% |
| 25->11_short | 4,522 | 47.5% | 73.8% | 6.22 | 5.73 | +0.109 | 88.8% | 62.1% | 26.7% |
| 50->25_short | 5,891 | 48.2% | 59.4% | 7.06 | 6.72 | +0.037 | 75.7% | 49.0% | 26.7% |
| 75->90_long | 4,968 | 48.2% | 71.7% | 5.60 | 5.57 | -0.055 | 85.4% | 61.0% | 24.4% |

## By pair × session

| Pair | Session | n | 1st-bar Win% | Full Win% | 1st MFE | 1st MAE | P(W\|1st W) | P(W\|1st L) | Lift |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 00->11_long | ETH | 2,494 | 47.6% | 62.2% | 3.74 | 3.86 | 80.3% | 46.0% | 34.2% |
| 00->11_long | RTH | 1,505 | 49.4% | 60.8% | 7.85 | 8.03 | 86.8% | 35.3% | 51.5% |
| 00->90_short | ETH | 2,314 | 48.8% | 67.2% | 4.12 | 3.70 | 85.0% | 50.3% | 34.7% |
| 00->90_short | RTH | 1,297 | 49.3% | 62.4% | 8.79 | 8.16 | 89.5% | 36.0% | 53.5% |
| 11->00_short | ETH | 2,509 | 47.1% | 68.9% | 3.90 | 3.75 | 85.2% | 54.5% | 30.8% |
| 11->00_short | RTH | 1,471 | 46.9% | 66.3% | 8.81 | 8.66 | 90.0% | 45.5% | 44.5% |
| 11->25_long | ETH | 3,000 | 47.8% | 56.5% | 4.14 | 3.94 | 73.6% | 40.9% | 32.7% |
| 11->25_long | RTH | 1,854 | 51.0% | 57.2% | 8.29 | 8.02 | 79.6% | 33.8% | 45.8% |
| 25->11_short | ETH | 2,751 | 46.6% | 73.1% | 4.48 | 4.09 | 85.6% | 65.2% | 20.5% |
| 25->11_short | RTH | 1,771 | 49.0% | 74.9% | 8.91 | 8.28 | 93.3% | 57.1% | 36.2% |
| 25->50_long | ETH | 3,367 | 47.7% | 45.5% | 4.68 | 4.45 | 59.7% | 34.7% | 25.0% |
| 25->50_long | RTH | 2,700 | 49.9% | 49.9% | 8.96 | 9.21 | 71.5% | 28.5% | 43.0% |
| 50->25_short | ETH | 3,294 | 48.2% | 56.1% | 4.89 | 4.50 | 70.0% | 51.0% | 19.0% |
| 50->25_short | RTH | 2,597 | 48.2% | 63.6% | 9.82 | 9.54 | 82.4% | 46.6% | 35.8% |
| 50->75_long | ETH | 3,372 | 49.4% | 55.5% | 4.77 | 4.42 | 70.2% | 48.6% | 21.5% |
| 50->75_long | RTH | 2,656 | 48.5% | 58.9% | 8.82 | 9.00 | 78.3% | 41.2% | 37.2% |
| 75->50_short | ETH | 3,532 | 47.5% | 45.5% | 4.83 | 4.66 | 59.7% | 34.8% | 24.9% |
| 75->50_short | RTH | 2,557 | 48.1% | 50.5% | 9.62 | 9.62 | 72.3% | 30.3% | 42.0% |
| 75->90_long | ETH | 3,058 | 48.4% | 71.0% | 3.94 | 3.80 | 82.6% | 63.2% | 19.3% |
| 75->90_long | RTH | 1,910 | 47.9% | 72.9% | 8.24 | 8.41 | 89.8% | 57.4% | 32.4% |
| 90->00_long | ETH | 2,593 | 45.5% | 71.6% | 3.60 | 3.64 | 86.6% | 59.0% | 27.6% |
| 90->00_long | RTH | 1,267 | 50.0% | 70.8% | 7.71 | 7.91 | 93.5% | 48.0% | 45.5% |
| 90->75_short | ETH | 3,162 | 47.5% | 52.3% | 4.40 | 4.08 | 70.7% | 35.7% | 35.0% |
| 90->75_short | RTH | 1,800 | 46.5% | 52.5% | 8.74 | 8.75 | 81.0% | 27.7% | 53.3% |

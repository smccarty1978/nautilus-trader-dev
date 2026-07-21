# Re-Breach Rescue Analysis — Level Momentum

## Part 1 — Deep-win second-leg MAE

Subset: winners with deep MAE (>15 pt for wide gaps, >12 pt for narrow) AND first bar closed ADVERSELY (no first-bar follow-through).

- n = 3,495
- Second-leg MAE (from first-bar close):
  - p50 = 11.50 pts
  - p75 = 15.50 pts
  - p90 = 20.00 pts
  - p95 = 22.50 pts
  - mean = 11.07 pts
- For comparison, distance from entry to first-bar close (where the failure happened):
  - mean = -5.94 pts (negative = adverse)

**Interpretation**: these wins didn't just draw down a little — they drew down 11 pts on average AFTER the first bar already showed adverse movement. The second leg is a real adverse phase before the eventual recovery.

## Part 2 — Stop early + re-enter on next breach

Rule: if MAE >= X, stop out at -X pts. Then look for next same-direction same-level Goldilocks trigger within 60 bars. Recursively apply same rule (max 3 chains).

Commission: 0.25 pts per trade in chain.

### Overall comparison (all trades)

| Strategy | Mean PnL net | Total | Annual $ |
|---|--:|--:|--:|
| Original (no early stop) | -0.488 | -28736 | $-574,725 |
| Early-stop @5.0 pt + re-enter | -0.707 | -41584 | $-831,685 |
| Early-stop @7.5 pt + re-enter | -0.721 | -42446 | $-848,925 |
| Early-stop @10.0 pt + re-enter | -0.637 | -37456 | $-749,110 |
| Early-stop @15.0 pt + re-enter | -0.770 | -45317 | $-906,345 |

### Per (pair × session) — best early-stop X for chain strategy

| Pair | Session | n | Orig Net | Best X | Chain Net | Δ vs Orig | Annual $ |
|---|---|--:|--:|--:|--:|--:|--:|
| 50->25_short | ETH | 3,294 | +0.107 | 10.0 | +0.622 | +0.515 | $40,955 |
| 50->75_long | ETH | 3,372 | -0.290 | 5.0 | +0.098 | +0.388 | $6,630 |
| 90->00_long | ETH | 2,593 | -0.626 | 10.0 | -0.305 | +0.321 | $-15,825 |
| 25->11_short | ETH | 2,751 | -0.247 | 15.0 | +0.050 | +0.297 | $2,745 |
| 75->50_short | ETH | 3,532 | -0.751 | 5.0 | -0.501 | +0.251 | $-35,365 |
| 50->75_long | RTH | 2,656 | -1.314 | 10.0 | -1.117 | +0.197 | $-59,355 |
| 90->75_short | ETH | 3,162 | -0.626 | 10.0 | -0.561 | +0.065 | $-35,480 |
| 75->90_long | ETH | 3,058 | -0.348 | 15.0 | -0.284 | +0.064 | $-17,345 |
| 25->50_long | RTH | 2,700 | -0.193 | 15.0 | -0.150 | +0.043 | $-8,115 |
| 11->00_short | ETH | 2,509 | -0.248 | 10.0 | -0.249 | -0.001 | $-12,485 |
| 00->11_long | ETH | 2,494 | -0.405 | 5.0 | -0.424 | -0.020 | $-21,170 |
| 11->25_long | RTH | 1,854 | -0.922 | 7.5 | -0.961 | -0.039 | $-35,620 |
| 25->50_long | ETH | 3,367 | -0.142 | 5.0 | -0.199 | -0.057 | $-13,415 |
| 00->90_short | ETH | 2,314 | -0.360 | 10.0 | -0.452 | -0.092 | $-20,910 |
| 90->00_long | RTH | 1,267 | -1.073 | 15.0 | -1.186 | -0.114 | $-30,065 |
| 11->25_long | ETH | 3,000 | -0.517 | 5.0 | -0.654 | -0.138 | $-39,260 |
| 75->90_long | RTH | 1,910 | -0.672 | 15.0 | -0.833 | -0.161 | $-31,835 |
| 90->75_short | RTH | 1,800 | -1.250 | 7.5 | -1.453 | -0.203 | $-52,310 |
| 11->00_short | RTH | 1,471 | -1.159 | 10.0 | -1.369 | -0.210 | $-40,280 |
| 75->50_short | RTH | 2,557 | -0.540 | 15.0 | -0.752 | -0.212 | $-38,475 |
| 00->90_short | RTH | 1,297 | -1.405 | 10.0 | -1.649 | -0.244 | $-42,765 |
| 25->11_short | RTH | 1,771 | -0.427 | 15.0 | -0.709 | -0.282 | $-25,130 |
| 00->11_long | RTH | 1,505 | -0.954 | 10.0 | -1.313 | -0.358 | $-39,515 |
| 50->25_short | RTH | 2,597 | +0.806 | 10.0 | +0.245 | -0.561 | $12,750 |

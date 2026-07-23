# Top 2.5% First-Signal MAE and Stop Survival

All cohorts use pure `confirm_flip_ns` timing. The primary table excludes every
signal whose confirmed flip occurs after 300 seconds. The 600-second and
eventual tables are cumulative secondary cohorts, not disjoint buckets.

`NQ dollars per contract = MAE points × $20`. Stop survival is descriptive and
uses exactly `countertrend_mae_atr <= stop_atr`; it does not simulate an order,
fill, slippage, or commission.

This is an event-corrected artifact comparison. Bullish selection comes from
the provisional artifact with inherited one-second feature look-ahead; Bearish
selection is strict-causal. Directional differences cannot establish structural
market asymmetry.

## Primary — confirmed flip within 300 seconds

| direction    | unit                    |   qualifying_flips |       p50 |        p75 |        p90 |       p95 |       p99 |    maximum |
|:-------------|:------------------------|-------------------:|----------:|-----------:|-----------:|----------:|----------:|-----------:|
| bullish_fade | ATR                     |                734 |  0.241014 |   0.539406 |   0.856512 |   1.2122  |   2.31871 |    6.42303 |
| bullish_fade | points                  |                734 |  2.5      |   6.25     |  12        |  17       |  31.2525  |   58       |
| bullish_fade | NQ_dollars_per_contract |                734 | 50        | 125        | 240        | 340       | 625.05    | 1160       |
| bearish_fade | ATR                     |                476 |  0.281905 |   0.645689 |   1.155    |   1.58266 |   2.44861 |    6.32557 |
| bearish_fade | points                  |                476 |  3.25     |   7.3125   |  16.25     |  23.3125  |  42.1875  |   80.75    |
| bearish_fade | NQ_dollars_per_contract |                476 | 65        | 146.25     | 325        | 466.25    | 843.75    | 1615       |

### Fixed-stop survival

|   stop_atr | bearish_fade   | bullish_fade   |
|-----------:|:---------------|:---------------|
|       0.5  | 66.8%          | 72.8%          |
|       0.75 | 78.2%          | 85.1%          |
|       1    | 86.1%          | 92.8%          |
|       1.25 | 92.0%          | 95.5%          |
|       1.5  | 94.3%          | 97.4%          |
|       2    | 98.3%          | 98.2%          |

## Secondary — confirmed flip within 600 seconds

| direction    | unit                    |   qualifying_flips |       p50 |       p75 |       p90 |       p95 |        p99 |    maximum |
|:-------------|:------------------------|-------------------:|----------:|----------:|----------:|----------:|-----------:|-----------:|
| bullish_fade | ATR                     |                918 |  0.362056 |   0.83223 |   1.48077 |   1.89675 |    3.3664  |    8.31007 |
| bullish_fade | points                  |                918 |  3.5      |  10       |  18.325   |  26.75    |   42.33    |  113       |
| bullish_fade | NQ_dollars_per_contract |                918 | 70        | 200       | 366.5     | 535       |  846.6     | 2260       |
| bearish_fade | ATR                     |                591 |  0.417847 |   1.06409 |   1.83984 |   2.37268 |    4.17291 |   12.1484  |
| bearish_fade | points                  |                591 |  4.75     |  12       |  23.25    |  35.375   |   65.2     |  107.25    |
| bearish_fade | NQ_dollars_per_contract |                591 | 95        | 240       | 465       | 707.5     | 1304       | 2145       |

### Fixed-stop survival

|   stop_atr | bearish_fade   | bullish_fade   |
|-----------:|:---------------|:---------------|
|       0.5  | 54.8%          | 59.6%          |
|       0.75 | 65.7%          | 71.2%          |
|       1    | 73.4%          | 80.4%          |
|       1.25 | 80.4%          | 85.9%          |
|       1.5  | 84.6%          | 90.5%          |
|       2    | 92.6%          | 95.5%          |

## Secondary — eventual confirmed flips

| direction    | unit                    |   qualifying_flips |        p50 |      p75 |        p90 |        p95 |        p99 |   maximum |
|:-------------|:------------------------|-------------------:|-----------:|---------:|-----------:|-----------:|-----------:|----------:|
| bullish_fade | ATR                     |               1226 |   0.648758 |   1.8192 |    3.80881 |    5.48878 |    8.34925 |   17.8632 |
| bullish_fade | points                  |               1226 |   7.125    |  20.9375 |   44.625   |   67.5     |  134.875   |  291.5    |
| bullish_fade | NQ_dollars_per_contract |               1226 | 142.5      | 418.75   |  892.5     | 1350       | 2697.5     | 5830      |
| bearish_fade | ATR                     |                785 |   0.777589 |   2.3056 |    4.81705 |    6.89118 |   17.1196  |   59.0192 |
| bearish_fade | points                  |                785 |   8.5      |  28      |   58.95    |   83.1     |  189.16    |  348.75   |
| bearish_fade | NQ_dollars_per_contract |                785 | 170        | 560      | 1179       | 1662       | 3783.2     | 6975      |

### Fixed-stop survival

|   stop_atr | bearish_fade   | bullish_fade   |
|-----------:|:---------------|:---------------|
|       0.5  | 41.3%          | 44.7%          |
|       0.75 | 49.4%          | 53.8%          |
|       1    | 55.4%          | 60.8%          |
|       1.25 | 60.8%          | 65.8%          |
|       1.5  | 64.6%          | 70.4%          |
|       2    | 73.0%          | 77.4%          |

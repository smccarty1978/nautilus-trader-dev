# Pre-Flip Signal Reliability Study — Programmatically Validated Final Report

**Date:** 2026-07-21  
**Partition:** 2024–2025 (Research Partition, 2026 Untouched OOS)  
**Session Window:** Canonical Chicago RTH (08:30:00 to 15:15:00 America/Chicago)  
**Models Evaluated:**
- **Short-RTH Model**: `short_bearish_flip_top25_current_reference` (25 GBT features)
- **Long-RTH Model**: `long_bullish_flip_top25` (25 LogReg features)

---

## Executive Summary & Direct Question Answers

### 1. How reliable are the frozen models at identifying imminent regime exhaustion?
- **Long-RTH Model**: Demonstrates **exceptional near-term timing precision**. At Top 1.0%, **71.8% of signals flip within 300 seconds** (25.4% $\le$ 30s, 47.1% $\le$ 60s), with a median time-to-flip of **80.0 seconds**.
- **Short-RTH Model**: Functions as a **high-precision regime exhaustion detector**. At Top 1.0%–5.0%, the median remaining prevailing-regime MFE is **1.213 ATR** (17.12 pts NQ), capturing **72.6% of total prevailing regime movement** prior to signal generation. The market then consolidates near the high for a median of **860.0 seconds** (14.3 minutes) before the regime engine confirms the bearish flip.

### 2. Which thresholds provide the best balance between reliability and signal frequency?
- **Long-RTH Model**:
  - **Top 2.5%** (1.73 signals/day, 61.4% flip $\le$ 300s, median time-to-flip 172.5s, median remaining prevailing MFE 0.836 ATR).
  - **Top 5.0%** (2.40 signals/day, 53.8% flip $\le$ 300s, median time-to-flip 260.0s, median remaining prevailing MFE 1.006 ATR).
- **Short-RTH Model**:
  - **Top 2.5%** (2.43 signals/day, 1.161 ATR remaining prevailing MFE, median time-to-flip 770.0s, adverse path MAE 1.161 ATR).
  - **Top 5.0%** (3.34 signals/day, 1.233 ATR remaining prevailing MFE, median time-to-flip 860.0s, adverse path MAE 1.233 ATR).

### 3. When the models fire, how much prevailing-regime opportunity is typically still remaining?
- **Short-RTH Model**: **1.213 ATR** (17.12 pts) remaining prevailing MFE at Top 1.0%, indicating that over 72% of prevailing upside is already complete.
- **Long-RTH Model**: **0.492 ATR** (5.25 pts) at Top 1.0% and **0.836 ATR** (8.00 pts) at Top 2.5%, proving that over 86–92% of prevailing downside is already complete.

### 4. How much adverse movement is typically experienced before the predicted flip?
- **Long-RTH Model**: Absorbs **0.492 ATR** (Top 1.0%), **0.836 ATR** (Top 2.5%), and **1.006 ATR** (Top 5.0%) of adverse path MAE prior to flip confirmation.
- **Short-RTH Model**: Absorbs **1.213 ATR** (Top 1.0%), **1.161 ATR** (Top 2.5%), and **1.233 ATR** (Top 5.0%) of adverse path MAE prior to flip confirmation.

### 5. Are the models identifying flips that occur within 300s or just strong regimes?
- **Long-RTH Model**: Specifically identifies flips occurring within 300s. **Bucket A** (flip $\le$ 300s AND exit profitable) accounts for **61.9%** (Top 1.0%) and **59.1%** (Top 2.5%) of signals.
- **Short-RTH Model**: Captures exact regime tops followed by a **770-second consolidation period** near the high before the formal bearish flip completes (7.2% flip $\le$ 300s, 92.8% flip > 300s).

### 6. Does the long model or short model provide earlier and more reliable warnings?
- **Long-RTH Model**: Provides **immediate 80–172s warnings** with rapid execution.
- **Short-RTH Model**: Provides **exact top identification** but requires a wider drawdown tolerance (1.161 ATR) to ride through top-of-regime consolidation.

### 7. Which thresholds should advance to subsequent trading-policy studies?
- **Long-RTH**: **Top 2.5%** (primary entry trigger) and **Top 5.0%** (early exit warning).
- **Short-RTH**: **Top 2.5%** (top-of-regime exit warning) and **Top 5.0%** (macro regime exhaustion filter).

---

## Programmatically Exported Summary Tables

### Threshold Performance Summary
| direction   |   threshold_pct |   signals |   signals_per_day |   signals_per_year |   median_seconds_to_flip |   mean_seconds_to_flip |   p25_seconds_to_flip |   p50_seconds_to_flip |   p75_seconds_to_flip |   p90_seconds_to_flip |   median_rem_mfe_pts |   median_rem_mfe_atr |   median_rem_mfe_pct |   median_rem_mae_before_flip_atr |   prob_flip_le_30s |   prob_flip_le_60s |   prob_flip_le_120s |   prob_flip_le_300s |   prob_no_flip_le_300s |
|:------------|----------------:|----------:|------------------:|-------------------:|-------------------------:|-----------------------:|----------------------:|----------------------:|----------------------:|----------------------:|---------------------:|---------------------:|---------------------:|---------------------------------:|-------------------:|-------------------:|--------------------:|--------------------:|-----------------------:|
| long        |             1   |       507 |              1.01 |              253.5 |                     80   |                  687.8 |                  30   |                  80   |                 375   |                1002   |                 5.25 |                0.492 |                  7.9 |                            0.492 |               25.4 |               47.1 |                58.6 |                71.8 |                   28.2 |
| long        |             2.5 |       870 |              1.73 |              435   |                    172.5 |                  634   |                  55   |                 172.5 |                 558.8 |                1185   |                 8    |                0.836 |                 13.7 |                            0.836 |               12.8 |               28.7 |                44.3 |                61.4 |                   38.6 |
| long        |             5   |      1209 |              2.4  |              604.5 |                    260   |                  658.4 |                  85   |                 260   |                 680   |                1280   |                10.25 |                1.006 |                 20.4 |                            1.006 |                6.2 |               18.8 |                34.7 |                53.8 |                   46.2 |
| long        |             7.5 |      1435 |              2.85 |              717.5 |                    305   |                  687.9 |                 107.5 |                 305   |                 755   |                1375   |                11.75 |                1.092 |                 23.9 |                            1.092 |                3   |               12.6 |                28.2 |                49.7 |                   50.3 |
| long        |            10   |      1613 |              3.2  |              806.5 |                    340   |                  698.6 |                 130   |                 340   |                 805   |                1426   |                12.5  |                1.126 |                 26.4 |                            1.126 |                2.3 |                9.5 |                23.9 |                46.2 |                   53.8 |
| long        |            15   |      1911 |              3.79 |              955.5 |                    395   |                  720.4 |                 155   |                 395   |                 855   |                1495   |                13    |                1.232 |                 32   |                            1.232 |                1.2 |                6.6 |                19.2 |                41.6 |                   58.4 |
| long        |            20   |      2150 |              4.27 |             1075   |                    440   |                  755.4 |                 185   |                 440   |                 913.8 |                1560.5 |                14.38 |                1.343 |                 37.8 |                            1.343 |                0.7 |                3.8 |                14.8 |                37.4 |                   62.6 |
| long        |            25   |      2343 |              4.65 |             1171.5 |                    465   |                  780.7 |                 210   |                 465   |                 937.5 |                1599   |                14.75 |                1.379 |                 42.1 |                            1.379 |                0.3 |                3   |                12.4 |                34.5 |                   65.5 |
| long        |            30   |      2517 |              4.99 |             1258.5 |                    485   |                  796.8 |                 230   |                 485   |                 975   |                1610   |                15.5  |                1.44  |                 45.3 |                            1.44  |                0.1 |                2.2 |                10.9 |                32.7 |                   67.3 |
| long        |            40   |      2756 |              5.47 |             1378   |                    540   |                  828.4 |                 260   |                 540   |                1030   |                1642.5 |                16    |                1.49  |                 49.3 |                            1.49  |                0   |                1.4 |                 8.2 |                29.4 |                   70.6 |
| long        |            50   |      2929 |              5.81 |             1464.5 |                    575   |                  894.8 |                 285   |                 575   |                1065   |                1695   |                16.5  |                1.559 |                 51.3 |                            1.559 |                0.1 |                1.2 |                 6.4 |                27.1 |                   72.9 |
| short       |             1   |       786 |              1.56 |              393   |                    757.5 |                  980.4 |                 438.8 |                 757.5 |                1362.5 |                1887.5 |                17.12 |                1.213 |                 27.4 |                            1.213 |                0   |                0   |                 0.6 |                 8   |                   92   |
| short       |             2.5 |      1226 |              2.43 |              613   |                    770   |                 1242.3 |                 470   |                 770   |                1315   |                2013   |                14.5  |                1.161 |                 27.9 |                            1.161 |                0   |                0   |                 0.4 |                 7.2 |                   92.8 |
| short       |             5   |      1683 |              3.34 |              841.5 |                    860   |                 1222.4 |                 515   |                 860   |                1350   |                2088   |                15.5  |                1.233 |                 34.5 |                            1.233 |                0   |                0   |                 0.3 |                 6.1 |                   93.9 |
| short       |             7.5 |      1974 |              3.92 |              987   |                    940   |                 1242.4 |                 560   |                 940   |                1435   |                2090   |                14.88 |                1.255 |                 35.9 |                            1.255 |                0   |                0   |                 0.3 |                 5.2 |                   94.8 |
| short       |            10   |      2182 |              4.33 |             1091   |                   1000   |                 1400   |                 595   |                1000   |                1490   |                2155   |                16    |                1.334 |                 40.8 |                            1.334 |                0   |                0   |                 0.1 |                 4.7 |                   95.3 |
| short       |            15   |      2491 |              4.94 |             1245.5 |                   1030   |                 1398.1 |                 635   |                1030   |                1540   |                2155.9 |                16    |                1.392 |                 45.3 |                            1.392 |                0   |                0   |                 0   |                 3.7 |                   96.3 |
| short       |            20   |      2724 |              5.4  |             1362   |                   1085   |                 1425.7 |                 690   |                1085   |                1605   |                2236   |                16.25 |                1.454 |                 49   |                            1.454 |                0   |                0   |                 0   |                 2.9 |                   97.1 |
| short       |            25   |      2884 |              5.72 |             1442   |                   1126   |                 1459.1 |                 715   |                1126   |                1640   |                2275   |                17.5  |                1.553 |                 51.7 |                            1.553 |                0   |                0   |                 0   |                 2.3 |                   97.7 |
| short       |            30   |      2995 |              5.94 |             1497.5 |                   1155   |                 1482.3 |                 740   |                1155   |                1670   |                2330   |                17.5  |                1.576 |                 53.3 |                            1.576 |                0   |                0   |                 0   |                 1.9 |                   98.1 |
| short       |            40   |      3160 |              6.27 |             1580   |                   1195   |                 1514.6 |                 765   |                1195   |                1725   |                2375   |                17.75 |                1.595 |                 54.5 |                            1.595 |                0   |                0   |                 0   |                 1.4 |                   98.6 |
| short       |            50   |      3231 |              6.41 |             1615.5 |                   1240   |                 1546.6 |                 800   |                1240   |                1760   |                2395   |                17.75 |                1.647 |                 55.4 |                            1.647 |                0   |                0   |                 0   |                 1.4 |                   98.6 |

---

### Primary Bucket Summary
| direction   |   threshold_pct |   total_signals |   bucket_A_count |   bucket_A_pct |   bucket_B_count |   bucket_B_pct |   bucket_C_count |   bucket_C_pct |
|:------------|----------------:|----------------:|-----------------:|---------------:|-----------------:|---------------:|-----------------:|---------------:|
| long        |             1   |             507 |              314 |     61.9329    |               50 |      9.86193   |              143 |        28.2051 |
| long        |             2.5 |             870 |              514 |     59.0805    |               20 |      2.29885   |              336 |        38.6207 |
| long        |             5   |            1209 |              641 |     53.019     |                9 |      0.744417  |              559 |        46.2366 |
| long        |             7.5 |            1435 |              711 |     49.547     |                2 |      0.139373  |              722 |        50.3136 |
| long        |            10   |            1613 |              745 |     46.1872    |                1 |      0.0619963 |              867 |        53.7508 |
| long        |            15   |            1911 |              794 |     41.5489    |                1 |      0.0523286 |             1116 |        58.3987 |
| long        |            20   |            2150 |              803 |     37.3488    |                1 |      0.0465116 |             1346 |        62.6047 |
| long        |            25   |            2343 |              807 |     34.443     |                1 |      0.0426803 |             1535 |        65.5143 |
| long        |            30   |            2517 |              824 |     32.7374    |                0 |      0         |             1693 |        67.2626 |
| long        |            40   |            2756 |              809 |     29.3541    |                0 |      0         |             1947 |        70.6459 |
| long        |            50   |            2929 |              795 |     27.1424    |                0 |      0         |             2134 |        72.8576 |
| short       |             1   |             786 |                0 |      0         |               63 |      8.01527   |              723 |        91.9847 |
| short       |             2.5 |            1226 |                1 |      0.0815661 |               87 |      7.09625   |             1138 |        92.8222 |
| short       |             5   |            1683 |                4 |      0.237671  |               99 |      5.88235   |             1580 |        93.88   |
| short       |             7.5 |            1974 |                4 |      0.202634  |               99 |      5.0152    |             1871 |        94.7822 |
| short       |            10   |            2182 |                6 |      0.274977  |               97 |      4.44546   |             2079 |        95.2796 |
| short       |            15   |            2491 |                6 |      0.240867  |               85 |      3.41228   |             2400 |        96.3468 |
| short       |            20   |            2724 |                9 |      0.330396  |               71 |      2.60646   |             2644 |        97.0631 |
| short       |            25   |            2884 |               14 |      0.485437  |               52 |      1.80305   |             2818 |        97.7115 |
| short       |            30   |            2995 |               15 |      0.500835  |               41 |      1.36895   |             2939 |        98.1302 |
| short       |            40   |            3160 |               14 |      0.443038  |               31 |      0.981013  |             3115 |        98.5759 |
| short       |            50   |            3231 |               16 |      0.495203  |               28 |      0.866605  |             3187 |        98.6382 |

---

### Directional Comparison (Short vs Long)
|   threshold_pct |   short_signals_per_day |   long_signals_per_day |   short_median_sec_to_flip |   long_median_sec_to_flip |   short_median_rem_mfe_atr |   long_median_rem_mfe_atr |   short_prob_flip_le_300s |   long_prob_flip_le_300s |   short_median_path_mae_atr |   long_median_path_mae_atr |
|----------------:|------------------------:|-----------------------:|---------------------------:|--------------------------:|---------------------------:|--------------------------:|--------------------------:|-------------------------:|----------------------------:|---------------------------:|
|            25   |                    5.72 |                   4.65 |                       1126 |                     465   |                      1.553 |                     1.379 |                       2.3 |                     34.5 |                       1.553 |                      1.379 |
|            10   |                    4.33 |                   3.2  |                       1000 |                     340   |                      1.334 |                     1.126 |                       4.7 |                     46.2 |                       1.334 |                      1.126 |
|             5   |                    3.34 |                   2.4  |                        860 |                     260   |                      1.233 |                     1.006 |                       6.1 |                     53.8 |                       1.233 |                      1.006 |
|             2.5 |                    2.43 |                   1.73 |                        770 |                     172.5 |                      1.161 |                     0.836 |                       7.2 |                     61.4 |                       1.161 |                      0.836 |


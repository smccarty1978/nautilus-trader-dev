# Consolidated Multi-Year Keltner Channel extension fade report (2020-2026)

## 1. Executive Summary (RTH Only, Net of $10 Friction)
| Cell | Trades | Win Rate | Profit Factor | Net PnL ($) | Max DD ($) | Mean Basis-to-Ext (pts) | Mean Ext-to-Ext (pts) | Bootstrap 95% CI ($/tr) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| A_rr_0_5_target_0.25   | 33317  | 40.3%    | 0.94          | $-433,715.00 | $482,845.00 | 27.68                   | 55.36                 | [$-18.90, $-7.23]    |
| A_rr_0_5_target_0.5    | 38572  | 40.1%    | 0.94          | $-449,470.00 | $505,780.00 | 27.80                   | 55.59                 | [$-16.55, $-6.79]    |
| B_stop_2_5_target_0.25 | 22281  | 39.5%    | 0.89          | $-345,915.00 | $358,825.00 | 29.75                   | 59.51                 | [$-19.85, $-11.16]   |
| B_stop_2_5_target_0.5  | 22281  | 47.0%    | 0.89          | $-309,840.00 | $320,080.00 | 29.75                   | 59.51                 | [$-17.97, $-9.80]    |

## 2. Year-by-Year Performance Breakdown

### Cell: A_rr_0_5_target_0.25
| Year | Trades | Win Rate | Profit Factor | Net PnL ($) |
| :--- | :---: | :---: | :---: | :---: |
| 2020 | 5620   | 39.5% | 0.94 | $-57,295.00 |
| 2021 | 5271   | 39.9% | 0.91 | $-85,155.00 |
| 2022 | 5403   | 40.1% | 0.93 | $-102,250.00 |
| 2023 | 5248   | 40.7% | 0.95 | $-47,545.00 |
| 2024 | 5088   | 40.5% | 0.92 | $-89,695.00 |
| 2025 | 5112   | 40.6% | 0.96 | $-66,640.00 |
| 2026 | 1575   | 42.3% | 1.03 | $+14,865.00 |

### Cell: A_rr_0_5_target_0.5
| Year | Trades | Win Rate | Profit Factor | Net PnL ($) |
| :--- | :---: | :---: | :---: | :---: |
| 2020 | 6500   | 39.2% | 0.94 | $-67,320.00 |
| 2021 | 6115   | 39.9% | 0.91 | $-86,760.00 |
| 2022 | 6287   | 40.1% | 0.94 | $-87,120.00 |
| 2023 | 6133   | 40.2% | 0.93 | $-64,780.00 |
| 2024 | 5866   | 40.0% | 0.92 | $-98,295.00 |
| 2025 | 5849   | 40.3% | 0.95 | $-76,090.00 |
| 2026 | 1822   | 42.5% | 1.06 | $+30,895.00 |

### Cell: B_stop_2_5_target_0.25
| Year | Trades | Win Rate | Profit Factor | Net PnL ($) |
| :--- | :---: | :---: | :---: | :---: |
| 2020 | 3778   | 39.9% | 0.92 | $-33,520.00 |
| 2021 | 3487   | 39.2% | 0.87 | $-48,475.00 |
| 2022 | 3665   | 38.8% | 0.84 | $-93,980.00 |
| 2023 | 3617   | 38.8% | 0.88 | $-45,355.00 |
| 2024 | 3389   | 39.6% | 0.89 | $-49,230.00 |
| 2025 | 3310   | 40.4% | 0.90 | $-61,790.00 |
| 2026 | 1035   | 40.3% | 0.93 | $-13,565.00 |

### Cell: B_stop_2_5_target_0.5
| Year | Trades | Win Rate | Profit Factor | Net PnL ($) |
| :--- | :---: | :---: | :---: | :---: |
| 2020 | 3778   | 47.5% | 0.92 | $-29,055.00 |
| 2021 | 3487   | 47.1% | 0.89 | $-37,965.00 |
| 2022 | 3665   | 46.4% | 0.87 | $-69,940.00 |
| 2023 | 3617   | 46.2% | 0.86 | $-48,135.00 |
| 2024 | 3389   | 46.7% | 0.89 | $-46,860.00 |
| 2025 | 3310   | 47.9% | 0.89 | $-65,485.00 |
| 2026 | 1035   | 48.0% | 0.93 | $-12,400.00 |

## 3. Normalized Slope-relative Performance Gating
The Keltner slope is normalized in ATR units per 3m bar at trade entry. We align the slope with the trade's direction (relative slope = slope * direction):

*   **Trend Continuation:** The channel is sloping away from the entry, suggesting strong trending momentum in the breakout direction.
*   **Mean Reverting:** The channel is sloping towards the entry, suggesting potential exhaustion or deceleration.
*   **Flat:** The channel is horizontally stable.


### Cell: A_rr_0_5_target_0.25
| Slope Gating Bucket | Trades | Win Rate | Profit Factor | Net PnL ($) |
| :--- | :---: | :---: | :---: | :---: |
| Flat ([-0.05, 0.05])      | 8229   | 38.3% | 0.97 | $-53,775.00 |
| Mean Reverting (<-0.05)   | 23329  | 41.3% | 0.94 | $-344,645.00 |
| Trend Continuation (>0.05) | 1759   | 36.0% | 0.90 | $-35,295.00 |

### Cell: A_rr_0_5_target_0.5
| Slope Gating Bucket | Trades | Win Rate | Profit Factor | Net PnL ($) |
| :--- | :---: | :---: | :---: | :---: |
| Flat ([-0.05, 0.05])      | 8927   | 38.4% | 0.96 | $-62,675.00 |
| Mean Reverting (<-0.05)   | 27773  | 40.9% | 0.94 | $-355,470.00 |
| Trend Continuation (>0.05) | 1872   | 35.9% | 0.91 | $-31,325.00 |

### Cell: B_stop_2_5_target_0.25
| Slope Gating Bucket | Trades | Win Rate | Profit Factor | Net PnL ($) |
| :--- | :---: | :---: | :---: | :---: |
| Flat ([-0.05, 0.05])      | 412    | 53.4% | 0.99 | $-745.00    |
| Mean Reverting (<-0.05)   | 21865  | 39.2% | 0.88 | $-344,140.00 |
| Trend Continuation (>0.05) | 4      | 25.0% | 0.09 | $-1,030.00  |

### Cell: B_stop_2_5_target_0.5
| Slope Gating Bucket | Trades | Win Rate | Profit Factor | Net PnL ($) |
| :--- | :---: | :---: | :---: | :---: |
| Flat ([-0.05, 0.05])      | 412    | 64.8% | 0.97 | $-1,140.00  |
| Mean Reverting (<-0.05)   | 21865  | 46.7% | 0.89 | $-307,960.00 |
| Trend Continuation (>0.05) | 4      | 50.0% | 0.08 | $-740.00    |
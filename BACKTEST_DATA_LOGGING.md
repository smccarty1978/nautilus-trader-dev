# Nautilus Trader - Backtest Data Logging Best Practices

This document outlines the best practices for structuring and logging backtest and study data. Adhering to these standards ensures that your coding agents design strategies whose outputs can be visualized instantly, without requiring custom backend modifications.

---

## 1. How the Visualizer Constructs the Chart (Data Flow)

The chart is built by combining two distinct data sources:
1. **Trade Metadata (`trades.parquet`):** Loaded from the specific backtest run folder. This dictates the trade window, entry/exit levels, markers, and metrics.
2. **Market Candles (Raw Price Catalog):** Loaded on the fly from the Nautilus `ParquetDataCatalog` (`data/catalog/`) using the entry and exit timestamps (+ padding) from the trade file.
3. **Indicators:** EMA bands, ATR line, and background Regime states are **computed dynamically on the fly** by the FastAPI backend using the raw catalog price candles.

---

## 2. Standardized `trades.parquet` Schema

To ensure a backtest can be loaded immediately by the visualizer, the strategy must output a `trades.parquet` file with the following standardized columns. 

### Required Columns
| Standard Column | Fallback Names | Type | Description / Value |
| :--- | :--- | :--- | :--- |
| **`direction`** | `signal_direction` | `int` or `str` | Trade direction: `1` / `"Long"` / `"BUY"` or `-1` / `"Short"` / `"SELL"`. |
| **`entry_ts`** | `entry_ts_ns` | `int` | Trade entry event timestamp in **nanoseconds epoch**. |
| **`fill_price`** | `entry_px`, `entry_fill_price` | `float` | Exact execution price at entry. |
| **`atr_at_entry`** | `entry_atr`, `atr_at_signal` | `float` | Average True Range at the time of entry (used for relative risk/PnL scaling). |

### Recommended Columns (Highly Encouraged)
Logging exit values prevents the visualizer from having to reconstruct exits using historical candle price scans, improving load times significantly.

| Standard Column | Fallback Names | Type | Description / Value |
| :--- | :--- | :--- | :--- |
| **`exit_ts`** | `exit_ts_ns` | `int` | Trade exit event timestamp in **nanoseconds epoch**. |
| **`exit_price`** | `exit_px`, `exit_fill_price` | `float` | Exact execution price at exit. |
| **`exit_reason`** | - | `str` | Reason for exit (e.g., `"SL"`, `"TP"`, `"Trailing"`, `"EOD"`, `"MaxHold"`). |
| **`net_pnl`** | `pnl_pts`, `pnl` | `float` | Profit/Loss in points. |
| **`pnl_atr`** | `exit_pnl_atr` | `float` | PnL scaled by the entry ATR (`net_pnl / atr_at_entry`). |

---

## 3. Best Practices for Backtests & Studies Code

When prompting agents to write backtest scripts (e.g., inside `run_backtest.py`), instruct them to follow these guidelines:

### Rule 1: Always Output a Complete Exits Table
Do not rely on the visualizer's backend exit reconstruction. Reconstructing exits requires loading high-resolution candles (1s data) and running iterative price checks, which is slow for large trade lists. Save the exact fill price and timestamp of the exit order.

### Rule 2: Clean and Normalize Column Names Before Exporting
Before saving the DataFrame to Parquet, map the column names to the visualizer's preferred names:
```python
# Standardize columns in your strategy logger/backtester
df_normalized = df_raw.rename(columns={
    "entry_fill_price": "fill_price",
    "exit_fill_price": "exit_price",
    "signal_direction": "direction",
    "atr_at_signal": "atr_at_entry",
    "pnl_pts": "net_pnl"
})
df_normalized.to_parquet(run_dir / "trades.parquet")
```

### Rule 3: Maintain Parquet Catalog Compatibility
The visualizer automatically detects whether the trade is on **NQ** or **ES** based on the entry price level. It then attempts to query the corresponding catalog folders:
* **NQ Catalog Path**: `data/catalog/NQ_v0_2020_2026`
* **ES Catalog Path**: `data/catalog/ES_v0_2020_2026`

Ensure that any backtests run on these instruments have their raw tick/bar catalog data correctly written to these folders.

### Rule 4: Log Custom Time-Series Indicators (Advanced)
If a study computes indicators that cannot be easily calculated on raw candles alone (e.g., HMM hidden states, ML forecast probabilities, custom volatility matrices):
1. **At Entry Point:** Log the indicator state as a column directly in `trades.parquet` (e.g., `hmm_state_at_entry`).
2. **Time-Series Overlays:** Save a companion file named `indicators.parquet` in the same directory containing `['timestamp', 'indicator_name', 'value']` to log the values over time. The visualizer can then load this file to render overlays of the exact states used during the backtest execution.

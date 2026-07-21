import os
import glob
import re
import math
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Nautilus Trader - Backtest Visualizer")

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

class BrowserLog(BaseModel):
    message: str

@app.post("/api/logs")
def log_browser_message(log: BrowserLog):
    print(f"[BROWSER] {log.message}")
    log_dir = PROJECT_ROOT / "scratch"
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / "browser_logs.txt", "a", encoding="utf-8") as f:
        f.write(log.message + "\n")
    return {"status": "ok"}

# Configure project paths
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DATA_CATALOG_DIR = PROJECT_ROOT / "data" / "catalog"
FRONTEND_DIR = Path(__file__).parent / "visualizer_hc_frontend"

# Cache for loaded backtest trade data to speed up lookups
_backtest_cache = {}

# Cache for per-run KNN health indicators.parquet (hC time-series)
_indicator_cache = {}


def load_trade_knn(backtest_id: str, start_ns: int, end_ns: int):
    """Load the run's precomputed KNN-health time-series (indicators.parquet) and
    slice to the trade window. hC is NOT candle-derivable, so it is served from the
    precomputed companion file rather than computed in compute_indicators().
    Returns {} gracefully for runs without the file (e.g. V_A / unmapped flips)."""
    if backtest_id not in _indicator_cache:
        rel = backtest_id.replace("__", "/")
        p = PROJECT_ROOT / rel / "indicators.parquet"
        try:
            _indicator_cache[backtest_id] = pd.read_parquet(p) if p.exists() else None
        except Exception:
            _indicator_cache[backtest_id] = None
    ind = _indicator_cache[backtest_id]
    if ind is None or ind.empty:
        return {}
    w = ind[(ind["timestamp"] >= start_ns) & (ind["timestamp"] <= end_ns)]
    out = {}
    for name in ("hc", "hc_slope", "hc_state", "hc_dd"):
        s = w[w["indicator"] == name].sort_values("timestamp")
        out[name] = [{"time": int(t // 1_000_000_000), "value": float(v)}
                     for t, v in zip(s["timestamp"], s["value"])]
    return out

# Map product names to their catalog names and instrument details
PRODUCT_CFG = {
    "NQ": {
        "catalog_path": "data/catalog/NQ_v0_2020_2026",
        "bar_type_1s": "NQ.XCME-1-SECOND-LAST-EXTERNAL",
        "bar_type_1m": "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
    },
    "ES": {
        "catalog_path": "data/catalog/ES_v0_2020_2026",
        "bar_type_1s": "ES.XCME-1-SECOND-LAST-EXTERNAL",
        "bar_type_1m": "ES.XCME-1-MINUTE-LAST-EXTERNAL",
    }
}


def load_bars_from_catalog(catalog_path: str, bar_type: str, start_ns: int, end_ns: int):
    """Load bar data from Nautilus ParquetDataCatalog for a specific window."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    
    full_catalog_path = str(PROJECT_ROOT / catalog_path)
    if not os.path.exists(full_catalog_path):
        raise FileNotFoundError(f"Catalog not found at {full_catalog_path}")

    catalog = ParquetDataCatalog(full_catalog_path)
    start_ts = pd.Timestamp(start_ns, unit='ns', tz='UTC')
    end_ts = pd.Timestamp(end_ns, unit='ns', tz='UTC')
    
    bars = catalog.bars(
        bar_types=[bar_type],
        start=start_ts,
        end=end_ts
    )
    return bars


def bars_to_df(bars):
    """Convert list of Cython Bar objects to a pandas DataFrame."""
    data = []
    for b in bars:
        data.append({
            "timestamp": int(b.ts_event), # ts_event is in nanoseconds
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": int(b.volume)
        })
    df = pd.DataFrame(data)
    if not df.empty:
        df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def aggregate_bars(df_1s, resolution_str: str):
    """Aggregate 1-second bars into candles of arbitrary duration (e.g. 5s, 15s, 1m)."""
    if df_1s.empty:
        return df_1s

    # Parse resolution (e.g. '5s', '1m')
    match = re.match(r"(\d+)([sm])", resolution_str)
    if not match:
        return df_1s
    
    val, unit = int(match.group(1)), match.group(2)
    seconds = val if unit == 's' else val * 60
    ns_bucket = seconds * 1_000_000_000
    
    df = df_1s.copy()
    df['bucket'] = (df['timestamp'] // ns_bucket) * ns_bucket
    
    agg_funcs = {
        'timestamp': 'first', # Floor time of the candle
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }
    
    df_agg = df.groupby('bucket').agg(agg_funcs).reset_index(drop=True)
    return df_agg


def reconstruct_exit_if_missing(row, catalog_path: str, bar_type: str):
    """Reconstruct exit details if exit_ts/exit_px are missing in the trades parquet."""
    exit_ts = row.get('exit_ts')
    exit_px = row.get('exit_px') or row.get('exit_fill_price')
    exit_reason = row.get('exit_reason', 'UNKNOWN')

    # If already fully populated, return immediately
    if pd.notna(exit_ts) and pd.notna(exit_px) and exit_ts != 0:
        return int(exit_ts), float(exit_px), str(exit_reason)

    entry_ts = int(row['entry_ts'])
    entry_px = float(row['entry_px'])
    entry_atr = float(row.get('entry_atr', 1.0))
    direction = int(row.get('signal_direction', 1))

    # Standard fallback
    fallback_ts = entry_ts + 300 * 1_000_000_000 # 5 minutes later
    fallback_px = entry_px

    try:
        # Load up to 4 hours of 1s data to find the exit
        end_query_ts = entry_ts + 4 * 3600 * 1_000_000_000
        bars = load_bars_from_catalog(catalog_path, bar_type, entry_ts, end_query_ts)
        if not bars:
            return fallback_ts, fallback_px, exit_reason

        df_1s = bars_to_df(bars)
        if df_1s.empty:
            return fallback_ts, fallback_px, exit_reason

        # ATR-based TP and SL levels
        tp_dist = 1.0 * entry_atr
        sl_dist = 1.0 * entry_atr
        
        if direction == 1:
            tp_px = entry_px + tp_dist
            sl_px = entry_px - sl_dist
        else:
            tp_px = entry_px - tp_dist
            sl_px = entry_px + sl_dist

        for _, bar in df_1s.iterrows():
            ts = int(bar['timestamp'])
            high = float(bar['high'])
            low = float(bar['low'])
            
            # Check maximum hold time
            if ts - entry_ts >= 4 * 3600 * 1_000_000_000:
                return ts, float(bar['close']), 'max_hold'
                
            # Stop loss hit
            if exit_reason == 'SL':
                if direction == 1 and low <= sl_px:
                    return ts, sl_px, 'SL'
                elif direction == -1 and high >= sl_px:
                    return ts, sl_px, 'SL'
            # Take profit hit
            elif exit_reason in ('T', 'TP'):
                if direction == 1 and high >= tp_px:
                    return ts, tp_px, 'TP'
                elif direction == -1 and low <= tp_px:
                    return ts, tp_px, 'TP'

        # If scanned and didn't touch, fall back to last bar close
        last_bar = df_1s.iloc[-1]
        return int(last_bar['timestamp']), float(last_bar['close']), exit_reason
    except Exception as e:
        print(f"Reconstruction failed: {e}")
        return fallback_ts, fallback_px, exit_reason


def compute_indicators(df_candles):
    """Compute EMA3 (H/L/C), EMA9 (H/L), and Regime State on DataFrame."""
    if df_candles.empty:
        return {}

    # Short EMAs (span-3)
    ema3_h = df_candles['high'].ewm(span=3, adjust=False).mean()
    ema3_l = df_candles['low'].ewm(span=3, adjust=False).mean()
    ema3_c = df_candles['close'].ewm(span=3, adjust=False).mean()

    # Long EMAs (span-9)
    ema9_h = df_candles['high'].ewm(span=9, adjust=False).mean()
    ema9_l = df_candles['low'].ewm(span=9, adjust=False).mean()

    # Regime calculation (dual band confirmation)
    regime = [0] * len(df_candles)
    curr_regime = 0
    
    close_vals = df_candles['close'].values
    ema3_h_vals = ema3_h.values
    ema3_l_vals = ema3_l.values
    ema9_h_vals = ema9_h.values
    ema9_l_vals = ema9_l.values

    for i in range(len(df_candles)):
        c = close_vals[i]
        if c > ema3_h_vals[i] and c > ema9_h_vals[i]:
            curr_regime = 1
        elif c < ema3_l_vals[i] and c < ema9_l_vals[i]:
            curr_regime = -1
        regime[i] = curr_regime

    # Calculate Wilder's ATR-14
    high_vals = df_candles['high']
    low_vals = df_candles['low']
    close_prev = df_candles['close'].shift(1)
    tr = pd.concat([high_vals - low_vals, (high_vals - close_prev).abs(), (low_vals - close_prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False).mean()
    if not atr.empty:
        atr.iloc[0] = tr.iloc[0]

    timestamps = (df_candles['timestamp'] // 1_000_000_000).tolist() # Convert to seconds for TV

    return {
        "short_ema_high": [{"time": t, "value": v} for t, v in zip(timestamps, ema3_h.tolist()) if not math.isnan(v)],
        "short_ema_low": [{"time": t, "value": v} for t, v in zip(timestamps, ema3_l.tolist()) if not math.isnan(v)],
        "short_ema_close": [{"time": t, "value": v} for t, v in zip(timestamps, ema3_c.tolist()) if not math.isnan(v)],
        "long_ema_high": [{"time": t, "value": v} for t, v in zip(timestamps, ema9_h.tolist()) if not math.isnan(v)],
        "long_ema_low": [{"time": t, "value": v} for t, v in zip(timestamps, ema9_l.tolist()) if not math.isnan(v)],
        "regime": [{"time": t, "value": v} for t, v in zip(timestamps, regime)],
        "atr": [{"time": t, "value": v} for t, v in zip(timestamps, atr.tolist()) if not math.isnan(v)]
    }


def determine_product(entry_price: float, timestamp_ns: int) -> str:
    """Determine whether the traded instrument is NQ or ES based on the entry price and year."""
    try:
        year = pd.Timestamp(timestamp_ns, unit='ns', tz='UTC').year
    except Exception:
        year = 2026  # Fallback

    if year <= 2020:
        threshold = 5000.0
    elif year == 2021:
        threshold = 8000.0
    elif year in (2022, 2023):
        threshold = 7500.0
    elif year == 2024:
        threshold = 10000.0
    elif year == 2025:
        threshold = 12000.0
    else:  # 2026 and later
        threshold = 15000.0

    return "NQ" if entry_price > threshold else "ES"


@app.get("/api/backtests")
def get_backtests():
    """List all directories containing a backtest trades.parquet file."""
    # Find all trades.parquet files in both backtests and studies directories recursively
    backtests_paths = glob.glob(str(PROJECT_ROOT / "backtests" / "**" / "trades.parquet"), recursive=True)
    studies_paths = glob.glob(str(PROJECT_ROOT / "studies" / "**" / "trades.parquet"), recursive=True)
    parquet_paths = sorted(list(set(backtests_paths + studies_paths)))
    
    backtests_list = []
    for path_str in parquet_paths:
        path = Path(path_str)
        relative = path.parent.relative_to(PROJECT_ROOT)
        parts = relative.parts
        
        # ID is url safe (replaces slashes with double underscores)
        bt_id = str(relative).replace("\\", "__").replace("/", "__")
        
        # Friendly name parsing to accommodate varying subdirectory depths
        prefix = f"[{parts[0]}] " if parts[0] == "studies" else ""
        if len(parts) >= 3:
            strategy_name = parts[1]
            if strategy_name in ("results", "results_all_years", "results_regime_only") and len(parts) >= 3:
                strategy_name = parts[0]
            run_name = parts[-1]
            name = f"{prefix}{strategy_name} - {run_name}"
        elif len(parts) == 2:
            name = f"{prefix}{parts[1]}"
        else:
            name = f"{prefix}{str(relative)}"
        
        backtests_list.append({
            "id": bt_id,
            "name": name,
            "path": str(relative)
        })
        
    return {"backtests": sorted(backtests_list, key=lambda x: x["name"])}


@app.get("/api/backtests/{backtest_id}/trades")
def get_backtest_trades(backtest_id: str):
    """Load trades parquet file, normalize the columns, and return the trades list."""
    relative_path = backtest_id.replace("__", "/")
    trades_parquet = PROJECT_ROOT / relative_path / "trades.parquet"
    
    if not trades_parquet.exists():
        raise HTTPException(status_code=404, detail="Trades parquet file not found")

    try:
        df = pd.read_parquet(trades_parquet)
        
        # Standardize columns
        trades = []
        has_exit = 'exit_ts' in df.columns or 'exit_ts_ns' in df.columns
        
        for index, row in df.iterrows():
            # Check direction column names
            direction_val = row.get('signal_direction') or row.get('direction')
            direction_str = "Long" if direction_val in (1, 'BUY', 'Long') else "Short"
            
            # Entry Timestamp
            entry_ts_val = row.get('entry_ts') or row.get('entry_ts_ns')
            entry_ts = int(entry_ts_val) if entry_ts_val is not None else 0
            
            # Entry Price
            entry_px_val = row.get('entry_px') or row.get('entry_fill_price') or row.get('fill_price')
            entry_px = float(entry_px_val) if (entry_px_val is not None and pd.notna(entry_px_val)) else 0.0
            
            # ATR (optional, default 1.0)
            entry_atr_val = row.get('entry_atr') or row.get('atr_at_signal') or row.get('atr_at_entry')
            entry_atr = float(entry_atr_val) if (entry_atr_val is not None and pd.notna(entry_atr_val)) else 1.0
            
            # Exits and PnL
            exit_reason = str(row.get('exit_reason')) if row.get('exit_reason') is not None else 'UNKNOWN'
            
            if has_exit and row.get('exit_ts') is not None and pd.notna(row.get('exit_ts')):
                exit_ts = int(row.get('exit_ts') or row.get('exit_ts_ns'))
                exit_px_val = row.get('exit_px') or row.get('exit_fill_price') or row.get('exit_price')
                exit_px = float(exit_px_val) if (exit_px_val is not None and pd.notna(exit_px_val)) else entry_px
                # Calculate points PnL if not already present
                pnl_val = row.get('pnl_pts') or row.get('net_pnl') or row.get('pnl')
                if pnl_val is None or pd.isna(pnl_val):
                    pnl_val = (exit_px - entry_px) * (1 if direction_str == "Long" else -1)
                pnl_val = float(pnl_val)
                pnl_atr_val = row.get('exit_pnl_atr') or row.get('pnl_atr')
                pnl_atr = float(pnl_atr_val) if (pnl_atr_val is not None and pd.notna(pnl_atr_val)) else float(pnl_val / entry_atr if entry_atr > 0 else 0)
                needs_recon = False
            else:
                # Placeholders for trades list (avoid slow catalog search during load)
                exit_ts = entry_ts + 60 * 1_000_000_000  # 1 min default placeholder
                exit_px = entry_px
                pnl_val = 0.0
                pnl_atr = 0.0
                needs_recon = True

            # Entry Time readable
            entry_dt = pd.Timestamp(entry_ts, unit='ns', tz='UTC')
            exit_dt = pd.Timestamp(exit_ts, unit='ns', tz='UTC')

            trades.append({
                "id": index,
                "direction": direction_str,
                "entry_time": entry_dt.isoformat(),
                "entry_timestamp_ns": entry_ts,
                "entry_price": entry_px,
                "entry_atr": entry_atr,
                "exit_time": exit_dt.isoformat(),
                "exit_timestamp_ns": exit_ts,
                "exit_price": exit_px,
                "exit_reason": exit_reason,
                "pnl": pnl_val,
                "pnl_atr": pnl_atr,
                "needs_reconstruction": needs_recon
            })
            
        # Cache this backtest's normalized trades
        _backtest_cache[backtest_id] = trades
        return {"trades": trades}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load trades: {e}")


@app.get("/api/backtests/{backtest_id}/trades/{trade_id}/candles")
def get_trade_candles(backtest_id: str, trade_id: int, resolution: str = "5s", padding: int = 15):
    """Get candlestick and indicator data for a specific trade window, aggregated to requested resolution."""
    # Retrieve trades from cache
    trades = _backtest_cache.get(backtest_id)
    if not trades:
        # Load trades if cache is clean
        res = get_backtest_trades(backtest_id)
        trades = res["trades"]

    if trade_id < 0 or trade_id >= len(trades):
        raise HTTPException(status_code=404, detail="Trade index not found")

    trade = trades[trade_id]

    # Dynamically reconstruct exit details on demand if missing
    if trade.get("needs_reconstruction", False):
        product = determine_product(trade["entry_price"], trade["entry_timestamp_ns"])
        cfg = PRODUCT_CFG[product]
        
        row_mock = {
            "entry_ts": trade["entry_timestamp_ns"],
            "entry_px": trade["entry_price"],
            "entry_atr": trade["entry_atr"],
            "signal_direction": 1 if trade["direction"] == "Long" else -1,
            "exit_reason": trade["exit_reason"]
        }
        
        exit_ts, exit_px, exit_reason = reconstruct_exit_if_missing(
            row_mock, cfg["catalog_path"], cfg["bar_type_1s"]
        )
        
        pnl_val = (exit_px - trade["entry_price"]) * (1 if trade["direction"] == "Long" else -1)
        pnl_atr = pnl_val / trade["entry_atr"] if trade["entry_atr"] > 0 else 0
        
        # Update cached trade details
        trade["exit_timestamp_ns"] = exit_ts
        trade["exit_price"] = exit_px
        trade["exit_reason"] = exit_reason
        trade["exit_time"] = pd.Timestamp(exit_ts, unit='ns', tz='UTC').isoformat()
        trade["pnl"] = pnl_val
        trade["pnl_atr"] = pnl_atr
        trade["needs_reconstruction"] = False

    entry_ns = trade["entry_timestamp_ns"]
    exit_ns = trade["exit_timestamp_ns"]

    # Calculate padding bounds (padding in minutes)
    padding_ns = padding * 60 * 1_000_000_000
    start_ns = entry_ns - padding_ns
    end_ns = exit_ns + padding_ns

    # Determine product configurations
    product = determine_product(trade["entry_price"], trade["entry_timestamp_ns"])
    cfg = PRODUCT_CFG[product]

    # KNN health series for this window (precomputed; not candle-derivable)
    knn = load_trade_knn(backtest_id, start_ns, end_ns)

    try:
        # Fetch 1-second candles first (allows arbitrary aggregation)
        bars_1s = load_bars_from_catalog(
            cfg["catalog_path"], cfg["bar_type_1s"], start_ns, end_ns
        )
        if not bars_1s:
            # Fall back to 1-minute bars if 1s bars are missing
            bars_1m = load_bars_from_catalog(
                cfg["catalog_path"], cfg["bar_type_1m"], start_ns, end_ns
            )
            df_raw = bars_to_df(bars_1m)
        else:
            df_raw = bars_to_df(bars_1s)

        if df_raw.empty:
            return {"candles": [], "indicators": {}, "knn": knn, "trade": trade}

        # Aggregate to target resolution
        df_candles = aggregate_bars(df_raw, resolution)

        # Convert candles to Lightweight Charts format
        candles_list = []
        for _, r in df_candles.iterrows():
            candles_list.append({
                "time": int(r["timestamp"] // 1_000_000_000), # TV uses seconds epoch
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"])
            })

        # Calculate EMAs & Regime
        indicators = compute_indicators(df_candles)

        return {
            "candles": candles_list,
            "indicators": indicators,
            "knn": knn,
            "trade": trade
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch bar data: {e}")


@app.post("/api/shutdown")
def shutdown():
    import os
    import signal
    import threading
    import time

    def kill_server():
        time.sleep(0.5)  # Allow the client to receive the response first
        print("[SERVER] Shutting down process...")
        os.kill(os.getpid(), signal.SIGTERM)

    print("[SERVER] Shutdown requested from UI. Stopping FastAPI server...")
    threading.Thread(target=kill_server).start()
    return {"status": "shutdown scheduled"}


# Serve visualizer static assets
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
else:
    @app.get("/")
    def fallback_index():
        return HTMLResponse("Frontend assets directory not found. Place index.html and style.css in visualizer_frontend/ folder.")

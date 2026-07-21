import pandas as pd
import numpy as np
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from nautilus_trader.persistence.catalog import ParquetDataCatalog

def main():
    print("Loading low excursion trades...")
    base_dir = Path("backtests/excursion_validation/results")
    dfs = []
    for yr in range(2020, 2027):
        p = base_dir / f"live_{yr}" / "trades.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df = df[df["excursion_bkt"] == "low"].copy()
            dfs.append(df)
            
    trades = pd.concat(dfs, ignore_index=True)
    trades["entry_dt"] = pd.to_datetime(trades["entry_ts"], unit='ns', utc=True).dt.tz_convert('America/New_York')
    trades["date_str"] = trades["entry_dt"].dt.strftime("%Y-%m-%d")
    trades["time_str"] = trades["entry_dt"].dt.strftime("%H:%M")
    trades["year"] = trades["entry_dt"].dt.year
    trades["month"] = trades["entry_dt"].dt.month
    
    print("Loading 1m bars...")
    catalog = ParquetDataCatalog("data/catalog/NQ_v0_2020_2026")
    bars = catalog.bars(["NQ.XCME-1-MINUTE-LAST-EXTERNAL"])
    
    b_ts = [b.ts_event for b in bars]
    b_h = [float(b.high) for b in bars]
    b_l = [float(b.low) for b in bars]
    b_c = [float(b.close) for b in bars]
    b_v = [float(b.volume) for b in bars]
    
    df_bars = pd.DataFrame({
        "ts": b_ts,
        "high": b_h,
        "low": b_l,
        "close": b_c,
        "volume": b_v
    })
    
    df_bars["dt"] = pd.to_datetime(df_bars["ts"], unit='ns', utc=True).dt.tz_convert('America/New_York')
    df_bars["trading_day"] = df_bars["dt"].dt.date
    df_bars["time_str"] = df_bars["dt"].dt.strftime("%H:%M")
    
    print("Calculating RTH VWAP (Anchored 09:30 NY)...")
    df_bars["is_rth"] = (df_bars["time_str"] >= "09:30") & (df_bars["time_str"] < "16:00")
    rth_bars = df_bars[df_bars["is_rth"]].copy()
    rth_bars["pv"] = rth_bars["close"] * rth_bars["volume"]
    
    rth_bars["cum_vol"] = rth_bars.groupby("trading_day")["volume"].cumsum()
    rth_bars["cum_pv"] = rth_bars.groupby("trading_day")["pv"].cumsum()
    rth_bars["vwap"] = rth_bars["cum_pv"] / rth_bars["cum_vol"]
    
    rth_bars["dev_sq"] = rth_bars["volume"] * ((rth_bars["close"] - rth_bars["vwap"]) ** 2)
    rth_bars["cum_dev_sq"] = rth_bars.groupby("trading_day")["dev_sq"].cumsum()
    rth_bars["vwap_std"] = np.sqrt(rth_bars["cum_dev_sq"] / rth_bars["cum_vol"].replace(0, np.nan))
    rth_bars["vwap_std"] = rth_bars["vwap_std"].fillna(0)
    
    rth_subset = rth_bars[["ts", "vwap", "vwap_std"]].sort_values("ts")
    trades = trades.sort_values("entry_ts")
    
    trades = pd.merge_asof(
        trades, 
        rth_subset, 
        left_on="entry_ts", 
        right_on="ts", 
        direction="backward",
        tolerance=60 * 1_000_000_000
    )
    
    trades["dist_to_vwap"] = trades["entry_fill_price"] - trades["vwap"]
    trades["abs_dist_vwap"] = trades["dist_to_vwap"].abs()
    
    def classify_vwap(row):
        if pd.isna(row["vwap"]): return "Outside_RTH"
        dist = row["dist_to_vwap"]
        abs_dist = row["abs_dist_vwap"]
        std = row["vwap_std"] if row["vwap_std"] > 0 else 1
        atr = row["atr_at_signal"]
        d = row["direction"]
        
        if abs_dist <= 0.5 * atr:
            cell = "1_Near_VWAP_0.5ATR"
        elif abs_dist <= 1.0 * std:
            cell = "2_Inside_Band_1_SD"
        elif abs_dist >= 2.0 * std:
            cell = "3_Stretched_Outside_Band_2"
        else:
            cell = "4_Between_B1_and_B2"
            
        if (d == 1 and dist > 0) or (d == -1 and dist < 0):
            intent = "Away_From_VWAP"
        else:
            intent = "Toward_VWAP"
            
        return f"{cell} | {intent}"
        
    trades["vwap_context"] = trades.apply(classify_vwap, axis=1)
    
    # Filter to Primary Hypothesis
    hypo_mask = (trades["vwap_context"].str.contains("1_Near") | trades["vwap_context"].str.contains("2_Inside")) & trades["vwap_context"].str.contains("Away_From")
    hypo_trades = trades[hypo_mask].copy()
    
    print(f"\nAnalyzing Primary Hypothesis Cohort ({len(hypo_trades)} trades)")
    
    print("\n--- Year-by-Year Results ---")
    win = hypo_trades["exit_reason"] == "target"
    years = hypo_trades["year"].value_counts().sort_index()
    for y in years.index:
        m = hypo_trades["year"] == y
        wr = win[m].mean()
        gross = hypo_trades[m]["gross_pnl"].sum()
        net = hypo_trades[m]["net_pnl"].sum()
        print(f"  {y}: {wr:.2%} (n={m.sum():>3}) | Net PnL: ${net:,.2f}")
        
    print("\n--- Long / Short Split ---")
    longs = hypo_trades["direction"] == 1
    shorts = hypo_trades["direction"] == -1
    print(f"  Longs : {win[longs].mean():.2%} (n={longs.sum()})")
    print(f"  Shorts: {win[shorts].mean():.2%} (n={shorts.sum()})")
    
    print("\n--- Monthly Distribution ---")
    months = hypo_trades["month"].value_counts().sort_index()
    for m in months.index:
        month_name = pd.to_datetime(f"2020-{m}-01").strftime('%B')
        print(f"  {month_name[:3]}: {months[m]} trades")
        
    print("\n--- Max Drawdown ---")
    # Cumulative Net PnL
    hypo_trades = hypo_trades.sort_values("entry_ts")
    hypo_trades["cum_net"] = hypo_trades["net_pnl"].cumsum()
    hypo_trades["high_water_mark"] = hypo_trades["cum_net"].cummax()
    hypo_trades["drawdown"] = hypo_trades["cum_net"] - hypo_trades["high_water_mark"]
    max_dd = hypo_trades["drawdown"].min()
    print(f"  Max Drawdown: ${max_dd:,.2f}")
    
    print("\n--- Forward Scanning (2 ATR & Max MFE) ---")
    # Convert bars to numpy arrays for fast forward scanning
    bars_ts = df_bars["ts"].values
    bars_h = df_bars["high"].values
    bars_l = df_bars["low"].values
    
    hit_2atr = []
    max_mfe_pts = []
    
    for i, row in hypo_trades.iterrows():
        entry_ts = row["entry_ts"]
        d = row["direction"]
        px = row["entry_fill_price"]
        atr = row["atr_at_signal"]
        
        # Target/stop thresholds
        target_1atr = px + atr if d == 1 else px - atr
        stop_1atr = px - atr if d == 1 else px + atr
        target_2atr = px + (2*atr) if d == 1 else px - (2*atr)
        
        # Start scanning from entry_ts
        start_idx = np.searchsorted(bars_ts, entry_ts)
        
        hit_2 = False
        mfe = 0
        
        # Scan forward max 120 minutes
        for j in range(start_idx, min(start_idx + 120, len(bars_ts))):
            h = bars_h[j]
            l = bars_l[j]
            
            # Update MFE
            curr_mfe = (h - px) if d == 1 else (px - l)
            if curr_mfe > mfe:
                mfe = curr_mfe
            
            # Check 1 ATR adverse
            if d == 1 and l <= stop_1atr:
                break
            elif d == -1 and h >= stop_1atr:
                break
                
            # Check 2 ATR favorable
            if d == 1 and h >= target_2atr:
                hit_2 = True
                break
            elif d == -1 and l <= target_2atr:
                hit_2 = True
                break
                
        hit_2atr.append(hit_2)
        max_mfe_pts.append(mfe)
        
    hypo_trades["hit_2atr"] = hit_2atr
    hypo_trades["max_mfe_pts"] = max_mfe_pts
    
    print(f"  Win Rate (2 ATR Target before 1 ATR Stop): {np.mean(hit_2atr):.2%}")
    print(f"  Median MFE before 1 ATR Stop: {np.median(max_mfe_pts):.2f} pts")
    print(f"  75th Percentile MFE: {np.percentile(max_mfe_pts, 75):.2f} pts")

if __name__ == "__main__":
    main()

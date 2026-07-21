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
    # Convert trade timestamps to NY time
    trades["entry_dt"] = pd.to_datetime(trades["entry_ts"], unit='ns', utc=True).dt.tz_convert('America/New_York')
    trades["date_str"] = trades["entry_dt"].dt.strftime("%Y-%m-%d")
    trades["time_str"] = trades["entry_dt"].dt.strftime("%H:%M")
    
    def get_bucket(t):
        if "09:30" <= t < "11:00": return "AM_Open"
        if "11:00" <= t < "14:00": return "Midday"
        if "14:00" <= t < "16:00": return "PM_Trend"
        return "Overnight"
        
    trades["time_bkt"] = trades["time_str"].apply(get_bucket)
    
    print("Loading 1m bars...")
    catalog = ParquetDataCatalog("data/catalog/NQ_v0_2020_2026")
    bars = catalog.bars(["NQ.XCME-1-MINUTE-LAST-EXTERNAL"])
    
    print(f"Converting {len(bars)} bars to DataFrame...")
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
    
    # Convert bars to NY time
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
    
    print("Merging context onto trades...")
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
        
        # Distance cells
        if abs_dist <= 0.5 * atr:
            cell = "1_Near_VWAP_0.5ATR"
        elif abs_dist <= 1.0 * std:
            cell = "2_Inside_Band_1_SD"
        elif abs_dist >= 2.0 * std:
            cell = "3_Stretched_Outside_Band_2"
        else:
            cell = "4_Between_B1_and_B2"
            
        # Direction
        if (d == 1 and dist > 0) or (d == -1 and dist < 0):
            intent = "Away_From_VWAP"
        else:
            intent = "Toward_VWAP"
            
        return f"{cell} | {intent}"
        
    trades["vwap_context"] = trades.apply(classify_vwap, axis=1)
    
    print("\n=== LOW EXCURSION: TIME & VWAP CONTEXT ===")
    win = trades["exit_reason"] == "target"
    
    print("\n--- By Time Bucket (NY Time) ---")
    for bkt in ["AM_Open", "Midday", "PM_Trend", "Overnight"]:
        mask = trades["time_bkt"] == bkt
        if mask.sum() > 0:
            print(f"  {bkt:10s}: {win[mask].mean():.2%} (n={mask.sum()})")
            
    print("\n--- By VWAP Context ---")
    counts = trades["vwap_context"].value_counts().sort_index()
    for state in counts.index:
        if state == "Outside_RTH": continue
        mask = trades["vwap_context"] == state
        if mask.sum() > 0:
            print(f"  {state:50s}: {win[mask].mean():.2%} (n={mask.sum()})")
            
    # Test the primary hypothesis:
    print("\n--- PRIMARY HYPOTHESIS ---")
    print("low 30m excursion + near/inside VWAP + flip away from VWAP")
    hypo_mask = (trades["vwap_context"].str.contains("1_Near") | trades["vwap_context"].str.contains("2_Inside")) & trades["vwap_context"].str.contains("Away_From")
    if hypo_mask.sum() > 0:
        print(f"  Hypothesis Win Rate: {win[hypo_mask].mean():.2%} (n={hypo_mask.sum()})")
        
    # Gross and Net PnL for hypothesis
    hypo_trades = trades[hypo_mask]
    gross = hypo_trades["gross_pnl"].sum()
    net = hypo_trades["net_pnl"].sum()
    print(f"  Hypothesis Gross PnL: ${gross:,.2f}")
    print(f"  Hypothesis Net PnL: ${net:,.2f}")
    print(f"  Hypothesis EV/Trade: ${net / len(hypo_trades):,.2f}")
    
    # Test the INVERSE hypothesis (Fading the exhaustion trap)
    print("\n--- INVERSE TRADES (Fading Exhaustion) ---")
    exhausted_mask = trades["vwap_context"].str.contains("3_Stretched") & trades["vwap_context"].str.contains("Away_From")
    exhausted_trades = trades[exhausted_mask]
    
    if len(exhausted_trades) > 0:
        # If the original trade exited via "stop" (loss), the inverse trade would exit via "target" (win).
        # We also need to flip the PnL signs.
        inverse_wins = exhausted_trades["exit_reason"] == "stop" # Fading the loss
        print(f"  Inverse Win Rate (Fading Outside Band 2): {inverse_wins.mean():.2%} (n={len(exhausted_trades)})")
        
        # Original trades lost money. The inverse trade gains the gross loss, minus commissions.
        # Original gross PnL
        orig_gross = exhausted_trades["gross_pnl"].sum()
        # The inverse trade takes the opposite side, so its gross is -orig_gross
        inv_gross = -orig_gross
        # We still pay commissions on the inverse trade ($5 per round trip)
        inv_net = inv_gross - (len(exhausted_trades) * 5.0)
        
        print(f"  Inverse Gross PnL: ${inv_gross:,.2f}")
        print(f"  Inverse Net PnL: ${inv_net:,.2f}")
        print(f"  Inverse EV/Trade: ${inv_net / len(exhausted_trades):,.2f}")

if __name__ == "__main__":
    main()

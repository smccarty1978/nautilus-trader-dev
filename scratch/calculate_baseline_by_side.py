import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"

def load_1s(year):
    parts = []
    for y in (year - 1, year, year + 1):
        p = ONE_S.get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(p, columns=["high", "low", "close", "open"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    return bars

def main():
    ds_path = "scratch/bar1_conditioning_dataset.parquet"
    if not os.path.exists(ds_path):
        print("Error: Dataset not found.")
        return
        
    df_trades = pd.read_parquet(ds_path)
    years = sorted(df_trades["year"].unique())
    bars_1m_cache = {}
    
    for y in years:
        try:
            bars_1s = load_1s(y)
        except Exception as e:
            continue
        df_1m = pd.DataFrame()
        df_1m["open"] = bars_1s["open"].resample("1Min").first()
        df_1m["high"] = bars_1s["high"].resample("1Min").max()
        df_1m["low"] = bars_1s["low"].resample("1Min").min()
        df_1m["close"] = bars_1s["close"].resample("1Min").last()
        df_1m = df_1m.dropna()
        bars_1m_cache[y] = df_1m

    # Run baseline (Cat Stop Only)
    for side in ["both", "long", "short"]:
        exit_pnls = []
        total_trades = 0
        
        for y in years:
            if y not in bars_1m_cache:
                continue
            df_1m = bars_1m_cache[y]
            ts_1m = df_1m.index.values.astype("int64")
            high_arr = df_1m["high"].to_numpy()
            low_arr = df_1m["low"].to_numpy()
            close_arr = df_1m["close"].to_numpy()
            open_arr = df_1m["open"].to_numpy()
            
            y_trades = df_trades[df_trades["year"] == y].copy()
            for _, row in y_trades.iterrows():
                entry_ts = int(row["entry_ts_bar1"])
                exit_ts = int(row["exit_ts"])
                entry_px = float(row["entry_px_bar1"])
                atr = float(row["entry_atr"])
                d = int(row["signal_direction"])
                
                if side == "long" and d != 1:
                    continue
                if side == "short" and d != -1:
                    continue
                    
                idx_entry = np.searchsorted(ts_1m, entry_ts, side="left")
                idx_exit = np.searchsorted(ts_1m, exit_ts, side="right") - 1
                
                if idx_entry >= len(ts_1m) or idx_exit >= len(ts_1m) or idx_entry > idx_exit:
                    continue
                    
                total_trades += 1
                cat_idx = max(0, idx_entry - 1)
                catastrophic_stop = open_arr[cat_idx]
                
                active_stop = catastrophic_stop
                is_stopped = False
                exit_px = close_arr[idx_exit]
                
                # Check stop-out in first bar (loop_offset = 0)
                for j in range(idx_entry, idx_exit + 1):
                    h = high_arr[j]
                    l = low_arr[j]
                    
                    if d == 1 and l <= active_stop:
                        is_stopped = True
                        exit_px = active_stop
                        break
                    elif d == -1 and h >= active_stop:
                        is_stopped = True
                        exit_px = active_stop
                        break
                        
                trade_exit_pnl = ((exit_px - entry_px) * d / atr)
                exit_pnls.append(trade_exit_pnl)
                
        df_res = pd.DataFrame({"exit_pnl_atr": exit_pnls})
        mean_pnl = df_res["exit_pnl_atr"].mean()
        df_res["gross_usd"] = df_res["exit_pnl_atr"] * 400.0
        df_res["net_usd"] = df_res["gross_usd"] - 10.0
        g_wins = df_res[df_res["gross_usd"] > 0]["gross_usd"].sum()
        g_losses = abs(df_res[df_res["gross_usd"] < 0]["gross_usd"].sum())
        gross_pf = g_wins / g_losses if g_losses > 0 else float("inf")
        n_wins = df_res[df_res["net_usd"] > 0]["net_usd"].sum()
        n_losses = abs(df_res[df_res["net_usd"] < 0]["net_usd"].sum())
        net_pf = n_wins / n_losses if n_losses > 0 else float("inf")
        
        print(f"Baseline {side}: trades={total_trades}, mean={mean_pnl:.4f}, GrossPF={gross_pf:.2f}, NetPF={net_pf:.2f}")

if __name__ == "__main__":
    main()

import pandas as pd
import numpy as np
from pathlib import Path

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2020, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"

def load_1s(year):
    p = ONE_S.get(year)
    if p and Path(p).exists():
        bars = pd.read_parquet(p, columns=["high", "low", "close", "open"])
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        return bars
    raise FileNotFoundError(f"1s NQ file not found for year {year}")

def main():
    df_flips = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    df_bar1 = df_flips[df_flips["bar1_confirm"] == 1].copy()
    
    df_dedup = df_bar1.groupby("entry_ts").agg({
        "entry_px_bar1": "first",
        "entry_px_flip": "first",
        "exit_ts": "first",
        "exit_px": "first",
        "signal_direction": "first",
        "entry_atr": "first",
        "year": "first",
        "regime_win_bar1": "first"
    }).reset_index()
    
    df_dedup["bar1_close_confirmed"] = ((df_dedup["entry_px_bar1"] - df_dedup["entry_px_flip"]) * df_dedup["signal_direction"] > 0).astype(int)
    df_cohort = df_dedup[df_dedup["bar1_close_confirmed"] == 1].copy()
    
    print(f"Total cohort size: {len(df_cohort)}")
    
    # We will trace the 2025 cohort as a representative sample
    y = 2025
    df_y = df_cohort[df_cohort["year"] == y].copy()
    print(f"\nAnalyzing year {y}: count = {len(df_y)}")
    
    bars = load_1s(y)
    ts_1s = bars.index.values.astype("int64")
    
    # Let's inspect the first 10 episodes
    st_indices = np.searchsorted(ts_1s, df_y["entry_ts"].to_numpy(np.int64), side="left")
    et_indices = np.searchsorted(ts_1s, df_y["exit_ts"].to_numpy(np.int64), side="left")
    
    n_kept = 0
    n_wins_raw = 0
    n_wins_kept = 0
    
    for i in range(len(df_y)):
        idx_start = st_indices[i]
        idx_end = et_indices[i]
        
        if idx_start >= len(ts_1s) or idx_end >= len(ts_1s):
            continue
            
        t_start = df_y["entry_ts"].iloc[i]
        t_end = df_y["exit_ts"].iloc[i]
        
        t_first_1m = ((t_start + 59_999_999_999) // 60_000_000_000) * 60_000_000_000
        t_last_1m = (t_end // 60_000_000_000) * 60_000_000_000
        boundaries = np.arange(t_first_1m, t_last_1m + 60_000_000_000, 60_000_000_000)
        
        has_ctrls = False
        if len(boundaries) >= 2:
            # Let's check how many qualifying control bars exist
            bound_indices = np.searchsorted(ts_1s, boundaries, side="left")
            ctrl_count = 0
            for b_idx in range(1, len(boundaries) - 1):
                idx_open = bound_indices[b_idx]
                idx_close = bound_indices[b_idx + 1]
                if idx_open < len(ts_1s) and idx_close < len(ts_1s):
                    px_open = bars["open"].values[idx_open]
                    px_close = bars["close"].values[idx_close]
                    d = df_y["signal_direction"].iloc[i]
                    if (px_close - px_open) * d > 0:
                        ctrl_count += 1
            if ctrl_count > 0:
                has_ctrls = True
                
        is_win = df_y["regime_win_bar1"].iloc[i] == 1
        if is_win:
            n_wins_raw += 1
            
        if has_ctrls:
            n_kept += 1
            if is_win:
                n_wins_kept += 1
                
    print(f"Raw Win% (year {y}): {n_wins_raw / len(df_y):.2%}")
    print(f"Kept Episodes: {n_kept} / {len(df_y)}")
    print(f"Kept Win% (year {y}): {n_wins_kept / n_kept:.2%}")

if __name__ == "__main__":
    main()

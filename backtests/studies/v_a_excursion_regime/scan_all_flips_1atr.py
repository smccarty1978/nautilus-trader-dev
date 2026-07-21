import pandas as pd
import numpy as np
import time
from pathlib import Path
import os, sys

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

OUT = Path("studies/v_a_excursion_regime/results")
OUT.mkdir(parents=True, exist_ok=True)

WINDOWS = {
    "fast": 5 * 60,
    "medium": 15 * 60,
    "slow": 30 * 60,
}

from numba import njit

@njit
def compute_features_fast(
    signal_times, directions, atrs,
    ts_index_ns, opens, highs, lows, closes
):
    N = len(signal_times)
    out_mfe_fast = np.full(N, np.nan)
    out_mae_fast = np.full(N, np.nan)
    out_ratio_fast = np.full(N, np.nan)
    out_eff_fast = np.full(N, np.nan)
    out_tot_fast = np.full(N, np.nan)

    out_mfe_med = np.full(N, np.nan)
    out_mae_med = np.full(N, np.nan)
    out_ratio_med = np.full(N, np.nan)
    out_eff_med = np.full(N, np.nan)
    out_tot_med = np.full(N, np.nan)

    out_mfe_slow = np.full(N, np.nan)
    out_mae_slow = np.full(N, np.nan)
    out_ratio_slow = np.full(N, np.nan)
    out_eff_slow = np.full(N, np.nan)
    out_tot_slow = np.full(N, np.nan)
    
    out_hit_target = np.full(N, -1)
    out_bars_to_hit = np.full(N, -1)

    for i in range(N):
        decision_ts = signal_times[i]
        direction = directions[i]
        atr = atrs[i]

        i_hi = np.searchsorted(ts_index_ns, decision_ts, side="left")
        if i_hi == 0 or i_hi >= len(ts_index_ns):
            continue
            
        anchor_open = closes[i_hi - 1]

        # Backward scan
        for w_idx, (w_name, w_secs) in enumerate([("fast", 5*60), ("medium", 15*60), ("slow", 30*60)]):
            win_start_ns = decision_ts - w_secs * 1_000_000_000
            i_lo = np.searchsorted(ts_index_ns, win_start_ns, side="left")
            if i_hi - i_lo < 10:
                continue
            
            w_anchor_open = opens[i_lo]
            h_max = np.max(highs[i_lo:i_hi])
            l_min = np.min(lows[i_lo:i_hi])
            c_now = closes[i_hi - 1]

            if direction == 1:
                mfe = h_max - w_anchor_open
                mae = w_anchor_open - l_min
            else:
                mfe = w_anchor_open - l_min
                mae = h_max - w_anchor_open
                
            tot = mfe + mae
            ratio = mfe / max(mae, 0.25)
            eff = abs(c_now - w_anchor_open) / max(tot, 0.25)
            
            if w_idx == 0:
                out_mfe_fast[i] = mfe; out_mae_fast[i] = mae; out_ratio_fast[i] = ratio; out_eff_fast[i] = eff; out_tot_fast[i] = tot
            elif w_idx == 1:
                out_mfe_med[i] = mfe; out_mae_med[i] = mae; out_ratio_med[i] = ratio; out_eff_med[i] = eff; out_tot_med[i] = tot
            else:
                out_mfe_slow[i] = mfe; out_mae_slow[i] = mae; out_ratio_slow[i] = ratio; out_eff_slow[i] = eff; out_tot_slow[i] = tot

        # Forward scan for 1 ATR target vs 1 ATR stop
        if atr <= 0:
            continue
            
        if direction == 1:
            target_px = anchor_open + atr
            stop_px = anchor_open - atr
        else:
            target_px = anchor_open - atr
            stop_px = anchor_open + atr
            
        # Scan forward
        j = i_hi
        while j < len(ts_index_ns):
            h = highs[j]
            l = lows[j]
            
            if direction == 1:
                hit_target = h >= target_px
                hit_stop = l <= stop_px
            else:
                hit_target = l <= target_px
                hit_stop = h >= stop_px
                
            if hit_target and hit_stop:
                # hit both in same 1s bar, mark as 0 (tie goes to runner/fail)
                out_hit_target[i] = 0
                out_bars_to_hit[i] = j - i_hi + 1
                break
            elif hit_target:
                out_hit_target[i] = 1
                out_bars_to_hit[i] = j - i_hi + 1
                break
            elif hit_stop:
                out_hit_target[i] = 0
                out_bars_to_hit[i] = j - i_hi + 1
                break
            
            j += 1

    return (
        out_ratio_fast, out_eff_fast, out_tot_fast,
        out_ratio_med, out_eff_med, out_tot_med,
        out_ratio_slow, out_eff_slow, out_tot_slow,
        out_hit_target, out_bars_to_hit
    )


def load_v0_1s_for_year(year: int):
    parts = []
    if year == 2024:
        for f in ("data/raw/NQ_v0_1s_2023.parquet", "data/raw/NQ_v0_1s_2024.parquet"):
            if Path(f).exists():
                parts.append(pd.read_parquet(f, columns=["open", "high", "low", "close"]))
    elif year == 2025:
        for f in ("data/raw/NQ_v0_1s_2024.parquet", "data/raw/NQ_v0_1s_2025.parquet"):
            if Path(f).exists():
                parts.append(pd.read_parquet(f, columns=["open", "high", "low", "close"]))
    elif year == 2026:
        for f in ("data/raw/NQ_v0_1s_2025.parquet", "data/raw/NQ_v0_1s_2026_ytd.parquet"):
            if Path(f).exists():
                parts.append(pd.read_parquet(f, columns=["open", "high", "low", "close"]))
    
    if not parts:
        return None
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    return bars

def process_year(year: int):
    print(f"\n=== Processing year {year} ===")
    
    # Load all flips for this year
    f_path = Path(f"studies/1m_regime_collector_v2/results/v2_feature_snapshots_{year}.parquet")
    if not f_path.exists():
        print(f"Skipping {year}, file missing")
        return None
        
    df = pd.read_parquet(f_path)
    
    # Just take 1 snapshot per flip (event_id is unique)
    df = df.drop_duplicates(subset=["signal_time", "signal_direction"]).copy()
    print(f"  Flips: {len(df):,}")
    
    bars = load_v0_1s_for_year(year)
    if bars is None:
        return None
        
    ts_index_ns = bars.index.astype("int64").to_numpy()
    opens = bars["open"].values.astype(np.float64)
    highs = bars["high"].values.astype(np.float64)
    lows = bars["low"].values.astype(np.float64)
    closes = bars["close"].values.astype(np.float64)

    # Convert flip times
    if pd.api.types.is_numeric_dtype(df["signal_time"]):
        signal_times = df["signal_time"].values.astype(np.int64)
    else:
        signal_times = df["signal_time"].astype("int64").values

    directions = df["signal_direction"].values.astype(np.int64)
    atrs = df["atr_at_signal"].values.astype(np.float64)

    t0 = time.time()
    res = compute_features_fast(
        signal_times, directions, atrs,
        ts_index_ns, opens, highs, lows, closes
    )
    
    df["ratio_fast"], df["efficiency_fast"], df["total_excursion_fast"] = res[0], res[1], res[2]
    df["ratio_medium"], df["efficiency_medium"], df["total_excursion_medium"] = res[3], res[4], res[5]
    df["ratio_slow"], df["efficiency_slow"], df["total_excursion_slow"] = res[6], res[7], res[8]
    df["hit_1atr_target"] = res[9]
    df["bars_to_hit"] = res[10]
    
    print(f"  done in {time.time()-t0:.1f}s")
    
    # Filter valid
    valid = df[df["hit_1atr_target"] != -1].copy()
    print(f"  Valid targets: {len(valid):,} / {len(df):,}")
    
    out_path = OUT / f"all_flips_1atr_target_{year}.parquet"
    valid.to_parquet(out_path)
    return valid

def main():
    dfs = []
    for yr in [2024, 2025, 2026]:
        df = process_year(yr)
        if df is not None:
            dfs.append(df)
            
    if not dfs:
        return
        
    all_df = pd.concat(dfs)
    print("\n--- Summary of 1ATR Target Hits ---")
    print(f"Total flips analyzed: {len(all_df):,}")
    print(f"Overall win rate: {all_df['hit_1atr_target'].mean():.2%}")
    
    # Bucket into tertiles on the IS data (2024-2025)
    is_df = pd.concat([d for d, yr in zip(dfs, [2024, 2025, 2026]) if yr in (2024, 2025)])
    
    print("\nWin Rates by Tertile (Out of Sample 2026):")
    oos_df = dfs[-1]
    
    for feat in ["ratio_fast", "efficiency_fast", "total_excursion_slow"]:
        if feat not in is_df.columns: continue
        valid_is = is_df[is_df[feat].notna()]
        if len(valid_is) == 0: continue
        
        cuts = valid_is[feat].quantile([1/3, 2/3]).values
        def bucket(x):
            if pd.isna(x): return "nan"
            if x < cuts[0]: return "low"
            if x < cuts[1]: return "mid"
            return "high"
            
        oos_df[f"{feat}_bkt"] = oos_df[feat].apply(bucket)
        
        agg = oos_df.groupby(f"{feat}_bkt")["hit_1atr_target"].agg(["count", "mean"])
        print(f"\nFeature: {feat}")
        print(f"Cuts: {cuts[0]:.2f}, {cuts[1]:.2f}")
        for bkt, row in agg.iterrows():
            if bkt == "nan": continue
            print(f"  {bkt:>4} : {row['count']:>5.0f} trades -> {row['mean']:.2%} hit +1ATR first")

if __name__ == "__main__":
    main()

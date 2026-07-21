import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"

CT_TZ = "America/Chicago"

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

def compute_1m_indicators(df_1m):
    # Compute indicators on 1-minute bars
    close = df_1m["close"]
    high = df_1m["high"]
    low = df_1m["low"]
    
    # 1. Wilder ATR (14)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    df_1m["atr_14"] = tr.ewm(alpha=1/14, adjust=False).mean()
    
    # 2. EMAs
    df_1m["ema3"] = close.ewm(span=3, adjust=False).mean()
    df_1m["ema13"] = close.ewm(span=13, adjust=False).mean()
    
    # 3. Bollinger Band Width (20, 2)
    std_20 = close.rolling(20).std()
    df_1m["bb_width"] = 4 * std_20
    
    # 4. Keltner Channel Width (20, 1.5)
    tr_20 = tr.ewm(alpha=1/20, adjust=False).mean()
    df_1m["keltner_width"] = 3.0 * tr_20
    
    # 5. Realized Volatility (30-bar std of log returns)
    log_ret = np.log(close / close.shift(1))
    df_1m["rv_30m"] = log_ret.rolling(30).std()
    
    # 6. High-to-Low Range (60-bar)
    df_1m["range_60m"] = high.rolling(60).max() - low.rolling(60).min()
    
    # 7. Volatility Contraction Ratio (ATR_14 / ATR_200)
    atr_200 = tr.ewm(alpha=1/200, adjust=False).mean()
    df_1m["vol_contraction_ratio"] = df_1m["atr_14"] / atr_200.replace(0, np.nan)
    
    # 8. Percentiles (Rolling Rank over 1440 minutes = 1 day)
    # Using rolling rank to avoid look-ahead
    for col in ["atr_14", "rv_30m", "range_60m", "bb_width", "keltner_width"]:
        # rank pct
        df_1m[f"{col}_pct"] = df_1m[col].rolling(1440).rank(pct=True)
        
    return df_1m

def compute_session_metrics(df_1m):
    # Convert index to Chicago time
    df_1m["ct"] = df_1m.index.tz_convert(CT_TZ)
    df_1m["time_min"] = df_1m["ct"].dt.hour * 60 + df_1m["ct"].dt.minute
    
    # Define trading day (starts at 5:00 PM CT of previous day)
    # If CT is >= 5:00 PM, trading day is next calendar day
    is_after_5pm = df_1m["ct"].dt.hour >= 17
    df_1m["trading_day"] = df_1m["ct"].dt.date
    df_1m.loc[is_after_5pm, "trading_day"] = df_1m["ct"].dt.date + pd.Timedelta(days=1)
    
    # RTH session mask: 8:30 AM to 3:00 PM
    df_1m["is_rth"] = (df_1m["time_min"] >= 510) & (df_1m["time_min"] < 900)
    
    # Session high/low cumulative within RTH of each trading day
    rth_df = df_1m[df_1m["is_rth"]].copy()
    rth_df["session_high"] = rth_df.groupby("trading_day")["high"].cummax()
    rth_df["session_low"] = rth_df.groupby("trading_day")["low"].cummin()
    
    # Map back to main df
    df_1m = df_1m.join(rth_df[["session_high", "session_low"]], how="left")
    
    # Overnight session mask: 5:00 PM (prev day) to 8:30 AM (today)
    # This corresponds to CT time_min >= 1020 (17:00) OR time_min < 510 (8:30)
    df_1m["is_overnight"] = (df_1m["time_min"] >= 1020) | (df_1m["time_min"] < 510)
    
    # Overnight high/low (max/min over the overnight session of each trading day)
    eth_df = df_1m[df_1m["is_overnight"]].copy()
    eth_stats = eth_df.groupby("trading_day").agg(
        overnight_high=("high", "max"),
        overnight_low=("low", "min")
    )
    df_1m = df_1m.join(eth_stats, on="trading_day", how="left")
    
    # Opening range (first 30 minutes of RTH: 8:30 AM to 9:00 AM CT, i.e. 510 to 540 minutes)
    or_df = df_1m[(df_1m["time_min"] >= 510) & (df_1m["time_min"] <= 540)].copy()
    or_stats = or_df.groupby("trading_day").agg(
        or_high=("high", "max"),
        or_low=("low", "min")
    )
    df_1m = df_1m.join(or_stats, on="trading_day", how="left")
    
    # Gap size: Open RTH today (at 8:30 AM) minus Close RTH yesterday (at 3:00 PM)
    # Yesterday's close is close at 2:59 PM (minute 899)
    daily_close = df_1m[df_1m["time_min"] == 899][["trading_day", "close"]].rename(columns={"close": "prev_close"})
    daily_open = df_1m[df_1m["time_min"] == 510][["trading_day", "open"]].rename(columns={"open": "today_open"})
    
    # Shift daily close by 1 trading day to align with today
    daily_close["trading_day"] = daily_close["trading_day"] + pd.Timedelta(days=1)
    
    daily_gap = pd.merge(daily_open, daily_close, on="trading_day", how="inner")
    daily_gap["gap_size"] = daily_gap["today_open"] - daily_gap["prev_close"]
    
    # Gap percentile (rolling 20 trading days rank)
    daily_gap["gap_pct"] = daily_gap["gap_size"].rolling(20).rank(pct=True)
    
    df_1m = df_1m.join(daily_gap.set_index("trading_day")[["gap_size", "gap_pct"]], on="trading_day", how="left")
    
    return df_1m

def main():
    t0 = time.time()
    
    # Load bar1 excursions dataset
    trades_path = "scratch/predict_bar1_excursions.parquet"
    if not os.path.exists(trades_path):
        print(f"Error: {trades_path} not found.")
        return
        
    df_trades = pd.read_parquet(trades_path)
    print(f"Loaded {len(df_trades):,} trades for feature enrichment.")
    
    enriched_dfs = []
    
    for y in sorted(df_trades["year"].unique()):
        year_trades = df_trades[df_trades["year"] == y].copy()
        if len(year_trades) == 0:
            continue
            
        print(f"Enriching features for year {y}...")
        
        # Load 1s price bars
        try:
            bars_1s = load_1s(y)
        except Exception as e:
            print(f"  Failed to load 1s bars for {y}: {e}")
            continue
            
        # Resample to 1-minute bars
        df_1m = pd.DataFrame()
        df_1m["open"] = bars_1s["open"].resample("1Min").first()
        df_1m["high"] = bars_1s["high"].resample("1Min").max()
        df_1m["low"] = bars_1s["low"].resample("1Min").min()
        df_1m["close"] = bars_1s["close"].resample("1Min").last()
        df_1m = df_1m.dropna()
        
        # Compute indicators
        df_1m = compute_1m_indicators(df_1m)
        df_1m = compute_session_metrics(df_1m)
        
        # Load snapshots database for the year
        snap_p = f"studies/1m_regime_collector_v2/results/v2_feature_snapshots_{y}.parquet"
        if os.path.exists(snap_p):
            df_snap = pd.read_parquet(snap_p)
            df_snap["signal_time"] = df_snap["signal_time"].astype("int64")
            # Filter for checkpoint_s == 0 first, then deduplicate
            df_snap = df_snap[df_snap["checkpoint_s"] == 0]
            df_snap = df_snap.drop_duplicates(subset=["signal_time", "signal_direction"])
        else:
            df_snap = None
            print(f"  WARN: Snapshot file not found for {y}")
            
        # For each trade, lookup entry-time indicators from 1m df and snapshots
        ts_1m = df_1m.index.values.astype("int64")
        
        # Merge snapshots features first
        if df_snap is not None:
            year_trades = year_trades.merge(
                df_snap,
                left_on=["entry_ts_bar1", "signal_direction"],
                right_on=["signal_time", "signal_direction"],
                how="inner"
            )
            print(f"  Matched with snapshots database: {len(year_trades)} / {len(df_trades[df_trades['year']==y])}")
        else:
            continue
            
        # Now lookup dynamic 1m features causally
        # The completed bar ending at entry_ts_bar1 starts at (entry_ts_bar1 - 60s)
        target_lookup_ts = year_trades["entry_ts_bar1"].to_numpy("int64") - 60_000_000_000
        idx_1m = np.searchsorted(ts_1m, target_lookup_ts, side="left")
        
        # Safe boundary check and alignment verification
        exact_matches = (ts_1m[idx_1m] == target_lookup_ts)
        valid_idx = (idx_1m >= 0) & (idx_1m < len(ts_1m)) & exact_matches
        year_trades = year_trades[valid_idx].copy()
        idx_1m = idx_1m[valid_idx]
        
        # Extract features
        px_close = df_1m["close"].to_numpy()[idx_1m]
        px_high = df_1m["high"].to_numpy()[idx_1m]
        px_low = df_1m["low"].to_numpy()[idx_1m]
        ema3 = df_1m["ema3"].to_numpy()[idx_1m]
        ema13 = df_1m["ema13"].to_numpy()[idx_1m]
        
        atr_pct_30m = df_1m["atr_14_pct"].to_numpy()[idx_1m]
        rv_pct = df_1m["rv_30m_pct"].to_numpy()[idx_1m]
        range_pct = df_1m["range_60m_pct"].to_numpy()[idx_1m]
        bb_width_pct = df_1m["bb_width_pct"].to_numpy()[idx_1m]
        keltner_width_pct = df_1m["keltner_width_pct"].to_numpy()[idx_1m]
        vol_contraction = df_1m["vol_contraction_ratio"].to_numpy()[idx_1m]
        
        s_high = df_1m["session_high"].to_numpy()[idx_1m]
        s_low = df_1m["session_low"].to_numpy()[idx_1m]
        o_high = df_1m["overnight_high"].to_numpy()[idx_1m]
        o_low = df_1m["overnight_low"].to_numpy()[idx_1m]
        or_high = df_1m["or_high"].to_numpy()[idx_1m]
        or_low = df_1m["or_low"].to_numpy()[idx_1m]
        gap_size = df_1m["gap_size"].to_numpy()[idx_1m]
        gap_pct = df_1m["gap_pct"].to_numpy()[idx_1m]
        
        # Compute normalized distance features
        atr = year_trades["entry_atr"].to_numpy()
        close_px = year_trades["entry_px_bar1"].to_numpy()
        d = year_trades["signal_direction"].to_numpy()
        
        year_trades["dist_ema3"] = (close_px - ema3) * d
        year_trades["dist_ema3_atr"] = year_trades["dist_ema3"] / atr
        
        year_trades["dist_ema13"] = (close_px - ema13) * d
        year_trades["dist_ema13_atr"] = year_trades["dist_ema13"] / atr
        
        # Distance from VWAP is already in snapshots as vwap_z_signed/vwap_z_abs
        
        # Session High/Low
        year_trades["dist_session_high"] = s_high - close_px
        year_trades["dist_session_high_atr"] = year_trades["dist_session_high"] / atr
        
        year_trades["dist_session_low"] = close_px - s_low
        year_trades["dist_session_low_atr"] = year_trades["dist_session_low"] / atr
        
        # Overnight High/Low
        year_trades["dist_overnight_high"] = o_high - close_px
        year_trades["dist_overnight_high_atr"] = year_trades["dist_overnight_high"] / atr
        
        year_trades["dist_overnight_low"] = close_px - o_low
        year_trades["dist_overnight_low_atr"] = year_trades["dist_overnight_low"] / atr
        
        # Opening Range position
        year_trades["or_position"] = (close_px - or_low) / np.maximum(or_high - or_low, 0.25)
        
        # Session Progress
        time_min = df_1m["time_min"].to_numpy()[idx_1m]
        year_trades["session_progress"] = (time_min - 510) / 390.0 # 8:30 AM is 510, 3:00 PM is 900
        
        # Percentiles
        year_trades["atr_percentile_30m"] = atr_pct_30m
        year_trades["rv_percentile"] = rv_pct
        year_trades["range_percentile"] = range_pct
        year_trades["bb_width_percentile"] = bb_width_pct
        year_trades["keltner_width_percentile"] = keltner_width_pct
        year_trades["volatility_contraction_ratio"] = vol_contraction
        year_trades["gap_size_raw"] = gap_size
        year_trades["gap_percentile"] = gap_pct
        
        # Prior Regime Features
        # 1. Prior regime duration in minutes is prior_regime_duration_bars
        year_trades["prior_regime_duration_minutes"] = year_trades["prior_regime_duration_bars"]
        
        # Compute dynamic prior regime stats using 1s data to get exact highs/lows
        # Prior regime interval is [entry_ts_bar1 - (duration_bars + 1)*60s, entry_ts_bar1 - 60s)
        # Note: entry_ts_bar1 is raw flip + 60s. The raw flip is at entry_ts_bar1 - 60s.
        # So prior regime ends at raw flip time.
        # Let's perform a fast scan to get prior regime highs/lows
        ts_1s = bars_1s.index.astype("int64").to_numpy()
        h_1s = bars_1s["high"].to_numpy(np.float64)
        l_1s = bars_1s["low"].to_numpy(np.float64)
        c_1s = bars_1s["close"].to_numpy(np.float64)
        o_1s = bars_1s["open"].to_numpy(np.float64)
        
        prior_ts_start = year_trades["entry_ts_bar1"].to_numpy("int64") - (year_trades["prior_regime_duration_bars"].to_numpy("int64") + 1) * 60_000_000_000
        prior_ts_end = year_trades["entry_ts_bar1"].to_numpy("int64") - 60_000_000_000
        
        # Scan prior regimes using numba
        res_prior = scan_prior_regimes(
            prior_ts_start, prior_ts_end, ts_1s, o_1s, h_1s, l_1s, c_1s, d
        )
        
        year_trades["prior_regime_total_return_points"] = res_prior[0]
        year_trades["prior_regime_total_return_atr"] = year_trades["prior_regime_total_return_points"] / atr
        year_trades["prior_regime_max_favorable_excursion"] = res_prior[1] / atr
        year_trades["prior_regime_max_adverse_excursion"] = res_prior[2] / atr
        year_trades["prior_regime_range_points"] = res_prior[3]
        year_trades["prior_regime_range_atr"] = year_trades["prior_regime_range_points"] / atr
        year_trades["prior_regime_efficiency_ratio"] = res_prior[4]
        year_trades["prior_regime_chop_ratio"] = res_prior[5]
        year_trades["prior_regime_realized_vol"] = res_prior[6] / atr
        year_trades["prior_regime_mean_bar_range"] = res_prior[7] / atr
        year_trades["prior_regime_std_bar_range"] = res_prior[8] / atr
        
        enriched_dfs.append(year_trades)
        
    df_enriched = pd.concat(enriched_dfs, ignore_index=True)
    
    # Save enriched dataset
    out_p = Path("scratch/bar1_conditioning_dataset.parquet")
    df_enriched.to_parquet(out_p, index=False)
    print(f"\nSuccessfully generated {out_p} with {len(df_enriched):,} rows.")
    print(f"Total time: {(time.time()-t0)/60:.2f} min")

@njit
def scan_prior_regimes(start_ts_arr, end_ts_arr, ts_1s, open_1s, high_1s, low_1s, close_1s, d_arr):
    N = len(start_ts_arr)
    ret_pts = np.full(N, np.nan)
    mfe = np.full(N, np.nan)
    mae = np.full(N, np.nan)
    rng = np.full(N, np.nan)
    eff = np.full(N, np.nan)
    chop = np.full(N, np.nan)
    rv = np.full(N, np.nan)
    mean_br = np.full(N, np.nan)
    std_br = np.full(N, np.nan)
    
    idx_start_arr = np.searchsorted(ts_1s, start_ts_arr, side="left")
    idx_end_arr = np.searchsorted(ts_1s, end_ts_arr, side="right") - 1
    
    for i in range(N):
        idx_lo = idx_start_arr[i]
        idx_hi = idx_end_arr[i]
        
        if idx_lo >= len(ts_1s) or idx_hi >= len(ts_1s) or idx_lo > idx_hi:
            continue
            
        d_prior = -d_arr[i]
        px_open = open_1s[idx_lo]
        px_close = close_1s[idx_hi]
        
        h_max = np.max(high_1s[idx_lo:idx_hi+1])
        l_min = np.min(low_1s[idx_lo:idx_hi+1])
        
        # Excursions
        if d_prior == 1:
            ret = px_close - px_open
            mfe_val = h_max - px_open
            mae_val = px_open - l_min
        else:
            ret = px_open - px_close
            mfe_val = px_open - l_min
            mae_val = h_max - px_open
            
        ret_pts[i] = ret
        mfe[i] = mfe_val
        mae[i] = mae_val
        rng[i] = h_max - l_min
        eff[i] = abs(px_close - px_open) / max(h_max - l_min, 0.25)
        
        # Chop and volatility on 1m resampled bars inside the prior regime window
        # We can approximate this by sampling every 60s bars in [idx_lo, idx_hi]
        step = 60
        sub_closes = []
        sub_ranges = []
        for k in range(idx_lo, idx_hi + 1, step):
            sub_closes.append(close_1s[k])
            # bar range high-low over the 60s interval
            k_end = min(k + step, idx_hi + 1)
            sub_ranges.append(np.max(high_1s[k:k_end]) - np.min(low_1s[k:k_end]))
            
        n_bars = len(sub_closes)
        if n_bars >= 2:
            closes_arr = np.array(sub_closes)
            diffs = np.abs(closes_arr[1:] - closes_arr[:-1])
            chop[i] = np.sum(diffs) / max(h_max - l_min, 0.25)
            
            # Realized vol
            pct_diffs = (closes_arr[1:] - closes_arr[:-1]) / closes_arr[:-1]
            rv[i] = np.std(pct_diffs) * px_open # scale by open price
            
            # Mean and std bar range
            ranges_arr = np.array(sub_ranges)
            mean_br[i] = np.mean(ranges_arr)
            std_br[i] = np.std(ranges_arr)
        else:
            chop[i] = 0.0
            rv[i] = 0.0
            mean_br[i] = h_max - l_min
            std_br[i] = 0.0
            
    return ret_pts, mfe, mae, rng, eff, chop, rv, mean_br, std_br

if __name__ == "__main__":
    main()

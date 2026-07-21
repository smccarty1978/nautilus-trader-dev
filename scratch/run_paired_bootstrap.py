"""Run Paired HMM Flip vs Random-in-Regime Entry Bootstrap Study."""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
os.chdir(PROJECT_ROOT)

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2020, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"
B_ITER = 1000
SEED = 42
NQ_MULT = 20.0
FRICTION = 10.0  # $10 RT per trade

def load_1s(year):
    p = ONE_S.get(year)
    if p and Path(p).exists():
        bars = pd.read_parquet(p, columns=["high", "low", "close", "open"])
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        return bars
    raise FileNotFoundError(f"1s NQ file not found for year {year}")

@njit
def scan_single_excursion(px_entry, d, ts_1s, high_1s, low_1s, idx_start, idx_end):
    running_mfe = 0.0
    running_mae = 0.0
    
    for j in range(idx_start, idx_end + 1):
        h, l = high_1s[j], low_1s[j]
        if d == 1:
            mfe_t = h - px_entry
            mae_t = px_entry - l
        else:
            mfe_t = px_entry - l
            mae_t = h - px_entry
            
        running_mfe = max(running_mfe, mfe_t)
        running_mae = max(running_mae, mae_t)
        
    return running_mfe, running_mae

def precalculate_episode_bars(entry_ts, exit_ts, entry_px_bar1, exit_px, signal_direction, entry_atr,
                              ts_1s, open_1s, high_1s, low_1s, close_1s, idx_entry_1s, idx_exit_1s):
    # Find all 1m boundaries within the episode:
    # A 1m bar opens on a timestamp divisible by 60,000,000,000
    t_start = entry_ts
    t_end = exit_ts
    
    # Generate list of 1m boundaries
    # Align to 1m boundary
    t_first_1m = ((t_start + 59_999_999_999) // 60_000_000_000) * 60_000_000_000
    t_last_1m = (t_end // 60_000_000_000) * 60_000_000_000
    
    boundaries = np.arange(t_first_1m, t_last_1m + 60_000_000_000, 60_000_000_000)
    
    ctrl_candidates = []
    
    # Pre-lookup index mappings for speed
    # We map timestamps in boundaries to indices in ts_1s
    if len(boundaries) < 2:
        return None, []
        
    bound_indices = np.searchsorted(ts_1s, boundaries, side="left")
    
    # 1. Treatment Bar
    # The treatment enters at entry_ts + 60s (which is the first boundary after entry_ts)
    # The treatment entry timestamp is t_first_1m.
    # Check if treatment has a valid mapped index
    if bound_indices[0] >= len(ts_1s) or ts_1s[bound_indices[0]] != t_first_1m:
        # If we cannot find exact timestamp match, search sorted is fine
        pass
        
    idx_treat_entry = bound_indices[0]
    mfe_t_pts, mae_t_pts = scan_single_excursion(
        entry_px_bar1, signal_direction, ts_1s, high_1s, low_1s, idx_treat_entry, idx_exit_1s
    )
    holding_bars_t = (exit_ts - t_first_1m) / 60_000_000_000
    
    treatment_data = {
        "px_entry": entry_px_bar1,
        "holding_bars": holding_bars_t,
        "pnl_pts": (exit_px - entry_px_bar1) * signal_direction,
        "mfe_pts": mfe_t_pts,
        "mae_pts": mae_t_pts,
        "mfe_atr": mfe_t_pts / entry_atr,
        "mae_atr": mae_t_pts / entry_atr
    }
    
    # 2. Control Bars
    # Control entries are random bars AFTER the treatment entry bar (so from boundary index 1 onwards)
    for b_idx in range(1, len(boundaries) - 1):
        t_open = boundaries[b_idx]
        t_close = t_open + 60_000_000_000
        
        # We need the 1m bar's open and close price
        idx_open = bound_indices[b_idx]
        idx_close = bound_indices[b_idx + 1]
        
        if idx_open >= len(ts_1s) or idx_close >= len(ts_1s):
            continue
            
        # 1m Open = price at t_open
        # 1m Close = price at t_close
        px_open = open_1s[idx_open]
        px_close = close_1s[idx_close]
        
        # Shape condition: Bar must close in the direction of the regime
        if (px_close - px_open) * signal_direction > 0:
            # Reconstruct excursion from this bar's close to the terminal exit
            mfe_pts, mae_pts = scan_single_excursion(
                px_close, signal_direction, ts_1s, high_1s, low_1s, idx_close, idx_exit_1s
            )
            holding_bars = (exit_ts - t_close) / 60_000_000_000
            
            if holding_bars <= 0:
                continue
                
            ctrl_candidates.append({
                "px_entry": px_close,
                "holding_bars": holding_bars,
                "pnl_pts": (exit_px - px_close) * signal_direction,
                "mfe_pts": mfe_pts,
                "mae_pts": mae_pts,
                "mfe_atr": mfe_pts / entry_atr,
                "mae_atr": mae_pts / entry_atr
            })
            
    return treatment_data, ctrl_candidates

def run_paired_study():
    t0 = time.time()
    
    # Load Bar-1 Confirmed flips
    df_flips = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    df_bar1 = df_flips[df_flips["bar1_confirm"] == 1].copy()
    
    # Deduplicate: Collapse entry_ts to one row per trade-event
    df_dedup = df_bar1.groupby("entry_ts").agg({
        "entry_px_bar1": "first",
        "entry_px_flip": "first",
        "exit_ts": "first",
        "exit_px": "first",
        "signal_direction": "first",
        "entry_atr": "first",
        "year": "first"
    }).reset_index()
    
    # Tighter confirmation filter as requested: bar1 close must exceed flip close
    df_dedup["bar1_close_confirmed"] = ((df_dedup["entry_px_bar1"] - df_dedup["entry_px_flip"]) * df_dedup["signal_direction"] > 0).astype(int)
    
    # Run the paired analysis on this Close-Confirmed cohort
    df_cohort = df_dedup[df_dedup["bar1_close_confirmed"] == 1].copy()
    
    print(f"Total Close-Confirmed episodes: {len(df_cohort)}")
    
    episodes_data = []
    
    years = sorted(df_cohort["year"].unique())
    for y in years:
        df_y = df_cohort[df_cohort["year"] == y].copy()
        if len(df_y) == 0:
            continue
            
        print(f"Loading and pre-calculating excursions for year {y}...")
        try:
            bars = load_1s(y)
        except Exception as e:
            print(f"  Error loading 1s data for {y}: {e}")
            continue
            
        ts_1s = bars.index.values.astype("int64")
        o_1s = bars["open"].to_numpy(np.float64)
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        
        # Pre-lookup indices for entries and exits
        st_indices = np.searchsorted(ts_1s, df_y["entry_ts"].to_numpy(np.int64), side="left")
        et_indices = np.searchsorted(ts_1s, df_y["exit_ts"].to_numpy(np.int64), side="left")
        
        for i in range(len(df_y)):
            idx_start = st_indices[i]
            idx_end = et_indices[i]
            
            if idx_start >= len(ts_1s) or idx_end >= len(ts_1s):
                continue
                
            treat, ctrls = precalculate_episode_bars(
                df_y["entry_ts"].iloc[i],
                df_y["exit_ts"].iloc[i],
                df_y["entry_px_bar1"].iloc[i],
                df_y["exit_px"].iloc[i],
                df_y["signal_direction"].iloc[i],
                df_y["entry_atr"].iloc[i],
                ts_1s, o_1s, h_1s, l_1s, c_1s, idx_start, idx_end
            )
            
            # We ONLY keep episodes where at least one qualifying control bar exists
            if treat is not None and len(ctrls) > 0:
                episodes_data.append({
                    "episode_id": df_y["entry_ts"].iloc[i],
                    "year": int(df_y["year"].iloc[i]),
                    "treatment": treat,
                    "controls": ctrls
                })
                
    print(f"\nTotal paired episodes kept (with at least 1 valid control): {len(episodes_data)}")
    
    # Perform bootstrap: draw random control entries B = 1,000 times
    np.random.seed(SEED)
    
    # Store bootstrap outcomes
    # We want to compare Treatment vs Control pooled and year-by-year
    # Let's extract treatment arrays for easier vectorized comparison
    treat_years = np.array([ep["year"] for ep in episodes_data])
    treat_pnl_pts = np.array([ep["treatment"]["pnl_pts"] for ep in episodes_data])
    treat_holding = np.array([ep["treatment"]["holding_bars"] for ep in episodes_data])
    treat_mfe_atr = np.array([ep["treatment"]["mfe_atr"] for ep in episodes_data])
    treat_mae_atr = np.array([ep["treatment"]["mae_atr"] for ep in episodes_data])
    
    # Time-normalized treatment metrics
    treat_pnl_per_bar = treat_pnl_pts / treat_holding
    treat_mfe_norm = treat_mfe_atr / np.sqrt(treat_holding)
    treat_mae_norm = treat_mae_atr / np.sqrt(treat_holding)
    treat_asym_norm = treat_mfe_norm - treat_mae_norm
    
    # We run B bootstrap draws
    boot_control_pnl_pts = np.zeros((B_ITER, len(episodes_data)))
    boot_control_holding = np.zeros((B_ITER, len(episodes_data)))
    boot_control_mfe_atr = np.zeros((B_ITER, len(episodes_data)))
    boot_control_mae_atr = np.zeros((B_ITER, len(episodes_data)))
    
    for b in range(B_ITER):
        for i, ep in enumerate(episodes_data):
            ctrl = np.random.choice(ep["controls"])
            boot_control_pnl_pts[b, i] = ctrl["pnl_pts"]
            boot_control_holding[b, i] = ctrl["holding_bars"]
            boot_control_mfe_atr[b, i] = ctrl["mfe_atr"]
            boot_control_mae_atr[b, i] = ctrl["mae_atr"]
            
    # Vectorized computation of bootstrap control metrics
    boot_control_pnl_per_bar = boot_control_pnl_pts / boot_control_holding
    boot_control_mfe_norm = boot_control_mfe_atr / np.sqrt(boot_control_holding)
    boot_control_mae_norm = boot_control_mae_atr / np.sqrt(boot_control_holding)
    boot_control_asym_norm = boot_control_mfe_norm - boot_control_mae_norm
    
    # Helper function to print tables
    def analyze_subset(mask, label):
        sub_n = mask.sum()
        
        # Treatment pooled metrics
        t_wr = (treat_pnl_pts[mask] > 0).mean()
        t_term_pts = treat_pnl_pts[mask].mean()
        t_term_usd = (treat_pnl_pts[mask] * NQ_MULT - FRICTION).mean()
        t_pnl_bar = treat_pnl_per_bar[mask].mean()
        t_mfe_raw = treat_mfe_atr[mask].mean()
        t_mae_raw = treat_mae_atr[mask].mean()
        t_mfe_n = treat_mfe_norm[mask].mean()
        t_mae_n = treat_mae_norm[mask].mean()
        t_asym_n = treat_asym_norm[mask].mean()
        
        # Control bootstrap distributions
        c_wrs = (boot_control_pnl_pts[:, mask] > 0).mean(axis=1)
        c_term_ptss = boot_control_pnl_pts[:, mask].mean(axis=1)
        c_term_usds = (boot_control_pnl_pts[:, mask] * NQ_MULT - FRICTION).mean(axis=1)
        c_pnl_bars = boot_control_pnl_per_bar[:, mask].mean(axis=1)
        c_mfe_raws = boot_control_mfe_atr[:, mask].mean(axis=1)
        c_mae_raws = boot_control_mae_atr[:, mask].mean(axis=1)
        c_mfe_ns = boot_control_mfe_norm[:, mask].mean(axis=1)
        c_mae_ns = boot_control_mae_norm[:, mask].mean(axis=1)
        c_asym_ns = boot_control_asym_norm[:, mask].mean(axis=1)
        
        # Calculate percentiles of treatment in control distributions
        pct_wr = (c_wrs < t_wr).mean() * 100
        pct_term_pts = (c_term_ptss < t_term_pts).mean() * 100
        pct_term_usd = (c_term_usds < t_term_usd).mean() * 100
        pct_pnl_bar = (c_pnl_bars < t_pnl_bar).mean() * 100
        pct_asym_n = (c_asym_ns < t_asym_n).mean() * 100
        
        print(f"\n--- {label} (Episodes: {sub_n}) ---")
        print(f"Metric                       | Treatment | Control Mean | Boot 5th / 95th    | Treat Percentile")
        print("-" * 92)
        print(f"Win Rate                     | {t_wr:>9.1%} | {c_wrs.mean():>12.1%} | {np.percentile(c_wrs, 5):>5.1%} / {np.percentile(c_wrs, 95):>5.1%} | {pct_wr:>15.1f}%")
        print(f"Terminal PnL (pts)           | {t_term_pts:>+9.2f} | {c_term_ptss.mean():>+12.2f} | {np.percentile(c_term_ptss, 5):>+5.2f} / {np.percentile(c_term_ptss, 95):>+5.2f} | {pct_term_pts:>15.1f}%")
        print(f"Terminal PnL (USD/tr)        | ${t_term_usd:>+8.2f} | ${c_term_usds.mean():>+11.2f} | ${np.percentile(c_term_usds, 5):>+4.2f} / ${np.percentile(c_term_usds, 95):>+4.2f} | {pct_term_usd:>15.1f}%")
        print(f"Per-Bar PnL (pts/bar)        | {t_pnl_bar:>+9.4f} | {c_pnl_bars.mean():>+12.4f} | {np.percentile(c_pnl_bars, 5):>+5.4f} / {np.percentile(c_pnl_bars, 95):>+5.4f} | {pct_pnl_bar:>15.1f}%")
        print(f"Raw MFE / MAE (ATR)          | {t_mfe_raw:>4.2f}/{t_mae_raw:>4.2f} | {c_mfe_raws.mean():>5.2f}/{c_mae_raws.mean():>5.2f} |                  |")
        print(f"Per-sqrt(t) MFE / MAE        | {t_mfe_n:>4.2f}/{t_mae_n:>4.2f} | {c_mfe_ns.mean():>5.2f}/{c_mae_ns.mean():>5.2f} |                  |")
        print(f"Per-sqrt(t) MFE-MAE Asymmetry | {t_asym_n:>+9.4f} | {c_asym_ns.mean():>+12.4f} | {np.percentile(c_asym_ns, 5):>+5.4f} / {np.percentile(c_asym_ns, 95):>+5.4f} | {pct_asym_n:>15.1f}%")
        
        return {
            "p_val_pnl_bar": 1.0 - (pct_pnl_bar / 100.0),
            "p_val_asym": 1.0 - (pct_asym_n / 100.0),
            "pct_pnl_bar": pct_pnl_bar,
            "pct_asym": pct_asym_n,
            "treat_pnl_bar": t_pnl_bar,
            "control_pnl_bar_mean": c_pnl_bars.mean(),
            "treat_asym": t_asym_n,
            "control_asym_mean": c_asym_ns.mean()
        }

    # Pooled Analysis
    pooled_res = analyze_subset(np.ones(len(episodes_data), dtype=bool), "POOLED ALL YEARS (2020-2026)")
    
    # Year-by-year Analysis
    yearly_results = {}
    for y in years:
        mask_y = treat_years == y
        if mask_y.sum() > 0:
            yearly_results[y] = analyze_subset(mask_y, f"YEAR {y}")
            
    print(f"\nCompleted in {(time.time() - t0)/60:.2f} minutes.")

if __name__ == "__main__":
    run_paired_study()

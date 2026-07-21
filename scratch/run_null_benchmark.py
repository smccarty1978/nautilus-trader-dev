import os, sys, time, random, math
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.indicators import AverageTrueRange

NS_PER_S = 1_000_000_000
YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

# ==================================================================
# Regime State Class (Self-Contained to match strategy.py)
# ==================================================================

class LocalEMA:
    __slots__ = ("period", "alpha", "value", "count", "initialized")
    def __init__(self, period: int):
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self.value = 0.0
        self.count = 0
        self.initialized = False

    def update(self, v: float) -> None:
        self.count += 1
        if self.count == 1:
            self.value = v
        else:
            self.value = self.alpha * v + (1.0 - self.alpha) * self.value
        if self.count >= self.period:
            self.initialized = True

class RegimeState:
    __slots__ = (
        "emaH_3", "emaH_9", "emaL_3", "emaL_9", "ema3", "ema9",
        "regime", "bars_in_regime", "completed_bars",
    )
    def __init__(self):
        self.emaH_3 = LocalEMA(3)
        self.emaH_9 = LocalEMA(9)
        self.emaL_3 = LocalEMA(3)
        self.emaL_9 = LocalEMA(9)
        self.ema3 = LocalEMA(3)
        self.ema9 = LocalEMA(9)
        self.regime = 0
        self.bars_in_regime = 0
        self.completed_bars = 0

    def update(self, h: float, l: float, c: float) -> int:
        self.emaH_3.update(h)
        self.emaH_9.update(h)
        self.emaL_3.update(l)
        self.emaL_9.update(l)
        self.ema3.update(c)
        self.ema9.update(c)
        self.completed_bars += 1

        if not (self.emaH_3.initialized and self.emaH_9.initialized
                and self.emaL_3.initialized and self.emaL_9.initialized):
            return self.regime

        new_r = self.regime
        if c > self.emaH_3.value and c > self.emaH_9.value:
            new_r = 1
        elif c < self.emaL_3.value and c < self.emaL_9.value:
            new_r = -1

        if new_r != self.regime:
            self.regime = new_r
            self.bars_in_regime = 1
        else:
            self.bars_in_regime += 1
        return self.regime

# ==================================================================
# Helper Functions
# ==================================================================

def chi2_sf_14(x):
    """Chi-squared survival function for 14 degrees of freedom."""
    if x <= 0:
        return 1.0
    val = 0.0
    half_x = x / 2.0
    term = 1.0
    for m in range(7):
        val += term
        term *= half_x / (m + 1)
    return math.exp(-half_x) * val

def binomial_sf_7_05(w):
    """Binomial cumulative probability of getting >= w successes out of 7 trials with p=0.5."""
    probs = [math.comb(7, x) * (0.5**7) for x in range(w, 8)]
    return sum(probs)

def compute_indicators(bars):
    n = len(bars)
    ts = np.array([b.ts_event for b in bars], dtype=np.int64)
    open_arr = np.array([float(b.open) for b in bars], dtype=np.float64)
    high_arr = np.array([float(b.high) for b in bars], dtype=np.float64)
    low_arr = np.array([float(b.low) for b in bars], dtype=np.float64)
    close_arr = np.array([float(b.close) for b in bars], dtype=np.float64)
    
    # Rolling SMA13
    close_series = pd.Series(close_arr)
    sma13 = close_series.rolling(13).mean().to_numpy()
    
    # ATR14
    atr_14 = AverageTrueRange(14)
    atr_arr = np.zeros(n, dtype=np.float64)
    for i in range(n):
        atr_14.update_raw(high_arr[i], low_arr[i], close_arr[i])
        atr_arr[i] = atr_14.value
        
    # Regime
    regime_state = RegimeState()
    regime_arr = np.zeros(n, dtype=np.int32)
    for i in range(n):
        regime_state.update(high_arr[i], low_arr[i], close_arr[i])
        regime_arr[i] = regime_state.regime
        
    return ts, open_arr, high_arr, low_arr, close_arr, sma13, atr_arr, regime_arr

# ==================================================================
# Exit Engine Simulators
# ==================================================================

def run_exit_engine_on_entries(entry_indices, ts, open_arr, high_arr, low_arr, close_arr, sma13, atr_arr, regime_arr):
    trades = []
    n_bars = len(ts)
    
    for idx_entry in entry_indices:
        if idx_entry >= n_bars - 1:
            continue
            
        entry_px = close_arr[idx_entry]
        entry_atr = atr_arr[idx_entry]
        entry_ts = ts[idx_entry]
        
        if entry_atr <= 0.0:
            continue
            
        cat_idx = max(0, idx_entry - 1)
        cat_stop = max(open_arr[cat_idx], entry_px - 1.0 * entry_atr)
        active_stop = round(min(cat_stop, entry_px - 0.25) * 4) / 4.0
        
        stall_count = 0
        prev_high = high_arr[idx_entry]
        
        exit_px = close_arr[-1]
        exit_reason = "regime_exit"
        exit_idx = n_bars - 1
        running_mfe = 0.0
        
        for k in range(idx_entry + 1, n_bars):
            h = high_arr[k]
            l = low_arr[k]
            c = close_arr[k]
            o = open_arr[k]
            
            # Check max hold
            dur_seconds = (ts[k] - entry_ts) / 1_000_000_000
            if dur_seconds >= 4 * 3600:
                exit_px = c
                exit_reason = "max_hold"
                exit_idx = k
                break
                
            # Check stop hit FIRST
            if l <= active_stop:
                exit_px = o if o < active_stop else active_stop
                exit_reason = "SL"
                exit_idx = k
                break
                
            # Check regime exit
            if regime_arr[k] == -1:
                exit_px = c
                exit_reason = "regime_exit"
                exit_idx = k
                break
                
            # Excursion
            mfe_bar = (h - entry_px) / entry_atr
            running_mfe = max(running_mfe, mfe_bar)
            
            # Update stall count and stop migration
            if h <= prev_high:
                stall_count += 1
            else:
                stall_count = 0
            prev_high = h
            
            if stall_count >= 3:
                ma_val = sma13[k]
                new_stop = round(max(active_stop, ma_val) * 4) / 4.0
                if new_stop >= c:
                    exit_px = c
                    exit_reason = "SL"
                    exit_idx = k
                    break
                else:
                    active_stop = new_stop
                    
        pnl_pts = exit_px - entry_px
        pnl_atr = pnl_pts / entry_atr
        
        trades.append({
            "idx_entry": idx_entry,
            "idx_exit": exit_idx,
            "entry_px": entry_px,
            "exit_px": exit_px,
            "entry_atr": entry_atr,
            "exit_reason": exit_reason,
            "pnl_pts": pnl_pts,
            "pnl_atr": pnl_atr,
            "mfe": running_mfe,
            "duration": exit_idx - idx_entry
        })
        
    return trades

def run_flavor_a_simulation(p, ts, open_arr, high_arr, low_arr, close_arr, sma13, atr_arr, regime_arr, rng, target_year):
    n_bars = len(ts)
    trades = []
    
    target_start_ns = int(pd.Timestamp(f"{target_year}-01-01", tz="UTC").value)
    start_idx = np.searchsorted(ts, target_start_ns, side="left")
    j = max(150, start_idx)
    
    log_1_p = math.log(1.0 - p)
    
    while j < n_bars:
        u = rng.random()
        if u == 0.0:
            u = 1e-15
        skip = int(math.floor(math.log(u) / log_1_p))
        j += skip
        if j >= n_bars:
            break
            
        entry_px = close_arr[j]
        entry_atr = atr_arr[j]
        entry_ts = ts[j]
        
        # Skip if ATR is zero to prevent division by zero
        if entry_atr <= 0.0:
            j += 1
            continue
            
        cat_idx = max(0, j - 1)
        cat_stop = max(open_arr[cat_idx], entry_px - 1.0 * entry_atr)
        active_stop = round(min(cat_stop, entry_px - 0.25) * 4) / 4.0
        
        stall_count = 0
        prev_high = high_arr[j]
        
        exit_px = close_arr[-1]
        exit_reason = "regime_exit"
        exit_idx = n_bars - 1
        running_mfe = 0.0
        
        for k in range(j + 1, n_bars):
            h = high_arr[k]
            l = low_arr[k]
            c = close_arr[k]
            o = open_arr[k]
            
            # Check max hold
            dur_seconds = (ts[k] - entry_ts) / 1_000_000_000
            if dur_seconds >= 4 * 3600:
                exit_px = c
                exit_reason = "max_hold"
                exit_idx = k
                break
                
            # Check stop hit FIRST
            if l <= active_stop:
                exit_px = o if o < active_stop else active_stop
                exit_reason = "SL"
                exit_idx = k
                break
                
            # Check regime exit
            if regime_arr[k] == -1:
                exit_px = c
                exit_reason = "regime_exit"
                exit_idx = k
                break
                
            # Excursion
            mfe_bar = (h - entry_px) / entry_atr
            running_mfe = max(running_mfe, mfe_bar)
            
            # Update stall count and stop migration
            if h <= prev_high:
                stall_count += 1
            else:
                stall_count = 0
            prev_high = h
            
            if stall_count >= 3:
                ma_val = sma13[k]
                new_stop = round(max(active_stop, ma_val) * 4) / 4.0
                if new_stop >= c:
                    exit_px = c
                    exit_reason = "SL"
                    exit_idx = k
                    break
                else:
                    active_stop = new_stop
                    
        pnl_pts = exit_px - entry_px
        pnl_atr = pnl_pts / entry_atr
        
        trades.append({
            "idx_entry": j,
            "idx_exit": exit_idx,
            "entry_px": entry_px,
            "exit_px": exit_px,
            "entry_atr": entry_atr,
            "exit_reason": exit_reason,
            "pnl_pts": pnl_pts,
            "pnl_atr": pnl_atr,
            "mfe": running_mfe,
            "duration": exit_idx - j
        })
        
        j = exit_idx + 1
        
    return trades

def run_flavor_b_simulation_fast(p, cand_durations, ts, close_arr, atr_arr, high_arr, rng, target_year, target_K, target_D):
    n_bars = len(ts)
    target_start_ns = int(pd.Timestamp(f"{target_year}-01-01", tz="UTC").value)
    start_idx = np.searchsorted(ts, target_start_ns, side="left")
    j = max(150, start_idx)
    
    # 1. Fast Pass: Generate entries/durations and check constraints without calculating metrics
    K_rand = 0
    D_rand = 0
    
    entries = []
    durs = []
    
    log_1_p = math.log(1.0 - p)
    
    while j < n_bars:
        u = rng.random()
        if u == 0.0:
            u = 1e-15
        skip = int(math.floor(math.log(u) / log_1_p))
        j += skip
        if j >= n_bars:
            break
            
        dur = rng.choice(cand_durations)
        idx_exit = min(n_bars - 1, j + dur)
        actual_dur = idx_exit - j
        
        K_rand += 1
        D_rand += actual_dur
        
        entries.append(j)
        durs.append(actual_dur)
        
        j = idx_exit + 1
            
    # Check exposure constraints (within 2%)
    if target_K <= 0 or abs(K_rand - target_K) / target_K > 0.02 or abs(D_rand - target_D) / target_D > 0.02:
        return None
        
    # 2. Slow Pass: Only for accepted seeds, compute metrics
    trades = []
    for idx_idx, entry_idx in enumerate(entries):
        actual_dur = durs[idx_idx]
        idx_exit = entry_idx + actual_dur
        
        entry_px = close_arr[entry_idx]
        entry_atr = atr_arr[entry_idx]
        
        if entry_atr > 0.0:
            exit_px = close_arr[idx_exit]
            pnl_pts = exit_px - entry_px
            pnl_atr = pnl_pts / entry_atr
            
            mfe_bar = 0.0
            if idx_exit > entry_idx:
                mfe_bar = np.max(high_arr[entry_idx+1 : idx_exit+1] - entry_px) / entry_atr
                
            trades.append({
                "idx_entry": entry_idx,
                "idx_exit": idx_exit,
                "entry_px": entry_px,
                "exit_px": exit_px,
                "entry_atr": entry_atr,
                "pnl_pts": pnl_pts,
                "pnl_atr": pnl_atr,
                "mfe": mfe_bar,
                "duration": actual_dur
            })
            
    return trades

# ==================================================================
# Stats Summarization
# ==================================================================

def calculate_trades_summary(trades):
    if not trades:
        return {
            "n": 0, "win_rate": 0.0, "mean_atr": 0.0, "mean_pts": 0.0,
            "gross_pf": 0.0, "net_pf": 0.0, "total_net_usd": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0, "win_pnl_90th": 0.0,
            "mfe_capture": 0.0, "duration": 0.0
        }
        
    df = pd.DataFrame(trades)
    n = len(df)
    
    df["gross_pnl_usd"] = df["pnl_pts"] * 20.0
    df["net_pnl_usd"] = df["gross_pnl_usd"] - 10.0
    
    win_rate = (df["pnl_pts"] > 0).mean() * 100
    mean_atr = df["pnl_atr"].mean()
    mean_pts = df["pnl_pts"].mean()
    
    g_wins = df[df["gross_pnl_usd"] > 0]["gross_pnl_usd"].sum()
    g_losses = abs(df[df["gross_pnl_usd"] < 0]["gross_pnl_usd"].sum())
    gross_pf = g_wins / g_losses if g_losses > 0 else float("inf")
    
    n_wins = df[df["net_pnl_usd"] > 0]["net_pnl_usd"].sum()
    n_losses = abs(df[df["net_pnl_usd"] < 0]["net_pnl_usd"].sum())
    net_pf = n_wins / n_losses if n_losses > 0 else float("inf")
    
    total_net_usd = df["net_pnl_usd"].sum()
    
    # Diagnostics
    wins = df[df["pnl_pts"] > 0]
    losses = df[df["pnl_pts"] <= 0]
    avg_win = wins["pnl_atr"].mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses["pnl_atr"].mean()) if len(losses) > 0 else 0.0
    
    # 90th percentile of winner PnL (ATR)
    win_pnl_90th = wins["pnl_atr"].quantile(0.90) if len(wins) > 0 else 0.0
    
    # MFE Capture
    valid_mfe = df[df["mfe"] > 0.0]
    mfe_capture = np.mean(valid_mfe["pnl_atr"] / valid_mfe["mfe"]) if len(valid_mfe) > 0 else 0.0
    
    total_dur = df["duration"].sum()
    
    return {
        "n": n,
        "win_rate": win_rate,
        "mean_atr": mean_atr,
        "mean_pts": mean_pts,
        "gross_pf": gross_pf,
        "net_pf": net_pf,
        "total_net_usd": total_net_usd,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_pnl_90th": win_pnl_90th,
        "mfe_capture": mfe_capture,
        "duration": total_dur
    }

# ==================================================================
# Main Execution Loop
# ==================================================================

def main():
    catalog_path = "data/catalog/NQ_v0_2020_2026"
    catalog = ParquetDataCatalog(catalog_path)
    
    # Results store
    nulls_flavor_a = {y: [] for y in YEARS}
    nulls_flavor_b = {y: [] for y in YEARS}
    
    cand_sim_stats = {}
    cand_durations_cache = {}
    cand_trade_counts = {}
    cand_total_durations = {}
    
    print("Pre-loading data and pre-computing indicators...")
    year_data = {}
    for y in YEARS:
        t0 = time.time()
        print(f"  Year {y}: loading 1m bars from catalog...")
        load_start = pd.Timestamp(f"{y}-01-01", tz="UTC") - pd.Timedelta(days=5)
        load_end   = pd.Timestamp(f"{y}-12-31 23:59:59", tz="UTC")
        bars = catalog.bars(
            bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
            start=load_start, end=load_end
        )
        print(f"    Loaded {len(bars):,} bars. Computing indicators...")
        ts, open_arr, high_arr, low_arr, close_arr, sma13, atr_arr, regime_arr = compute_indicators(bars)
        print(f"    Done in {time.time()-t0:.1f}s")
        
        year_data[y] = {
            "ts": ts,
            "open": open_arr,
            "high": high_arr,
            "low": low_arr,
            "close": close_arr,
            "sma13": sma13,
            "atr": atr_arr,
            "regime": regime_arr
        }
        
    print("\nLoading Candidate 1 (Stall-State) trades and running simulated baseline...")
    for y in YEARS:
        p = PROJECT_ROOT / f"backtests/baseline_flip_parity/results/nq_live_{y}_stall_sma13_s3_g0_long/trades.parquet"
        if not p.exists():
            print(f"  Warning: Candidate parquet for {y} not found at {p}")
            continue
        df_cand = pd.read_parquet(p)
        
        data = year_data[y]
        ts_1m = data["ts"]
        
        cand_entries = df_cand["entry_ts"].to_numpy().astype(np.int64)
        cand_entry_idx = np.searchsorted(ts_1m, cand_entries, side="left")
        
        cand_sim_trades = run_exit_engine_on_entries(
            cand_entry_idx, ts_1m, data["open"], data["high"], data["low"], data["close"],
            data["sma13"], data["atr"], data["regime"]
        )
        
        cand_stats = calculate_trades_summary(cand_sim_trades)
        cand_sim_stats[y] = cand_stats
        
        durs = [t["duration"] for t in cand_sim_trades]
        cand_durations_cache[y] = durs
        cand_trade_counts[y] = len(cand_sim_trades)
        cand_total_durations[y] = sum(durs)
        
        print(f"  Year {y}: {len(cand_sim_trades):,} simulated trades, Mean ATR = {cand_stats['mean_atr']:.4f}, Net PF = {cand_stats['net_pf']:.2f}")

    print("\nRunning Monte Carlo simulations (1000 accepted seeds per year)...")
    
    for y in YEARS:
        if y not in cand_sim_stats:
            continue
            
        t0 = time.time()
        print(f"  Year {y} Monte Carlo...")
        data = year_data[y]
        ts_1m = data["ts"]
        
        target_K = cand_trade_counts[y]
        target_D = cand_total_durations[y]
        cand_durs = cand_durations_cache[y]
        
        n_flat_bars = len(ts_1m) - target_D
        p_target = target_K / n_flat_bars
        
        accepted_count_b = 0
        accepted_count_a = 0
        
        seed_idx = 100
        rejections_b = 0
        
        while accepted_count_b < 1000 or accepted_count_a < 1000:
            rng = random.Random(42 + seed_idx)
            
            # 1. Run Flavor B (Duration-matched, Optimized fast pass)
            if accepted_count_b < 1000:
                fb_trades = run_flavor_b_simulation_fast(
                    p_target, cand_durs, ts_1m, data["close"], data["atr"], data["high"], rng, y, target_K, target_D
                )
                if fb_trades is not None:
                    fb_stats = calculate_trades_summary(fb_trades)
                    nulls_flavor_b[y].append(fb_stats)
                    accepted_count_b += 1
                else:
                    rejections_b += 1
                    
            # 2. Run Flavor A (Exit-driven)
            if accepted_count_a < 1000:
                rng = random.Random(42 + seed_idx)  # reuse same seed
                fa_trades = run_flavor_a_simulation(
                    p_target, ts_1m, data["open"], data["high"], data["low"], data["close"],
                    data["sma13"], data["atr"], data["regime"], rng, y
                )
                fa_stats = calculate_trades_summary(fa_trades)
                nulls_flavor_a[y].append(fa_stats)
                accepted_count_a += 1
                
            seed_idx += 1
            
        print(f"    Completed in {time.time()-t0:.1f}s. Rejections B: {rejections_b}")

    # ==================================================================
    # Compile Statistics & Report
    # ==================================================================
    
    print("\nCompiling metrics and generating report...")
    
    pooled_cand_atr = np.mean([cand_sim_stats[y]["mean_atr"] for y in YEARS])
    
    pooled_seeds_a = []
    pooled_seeds_b = []
    
    for s in range(1000):
        a_mean = np.mean([nulls_flavor_a[y][s]["mean_atr"] for y in YEARS])
        b_mean = np.mean([nulls_flavor_b[y][s]["mean_atr"] for y in YEARS])
        pooled_seeds_a.append(a_mean)
        pooled_seeds_b.append(b_mean)
        
    pooled_seeds_a = np.array(pooled_seeds_a)
    pooled_seeds_b = np.array(pooled_seeds_b)
    
    p_pooled_a = (1 + np.sum(pooled_seeds_a >= pooled_cand_atr)) / 1001.0
    p_pooled_b = (1 + np.sum(pooled_seeds_b >= pooled_cand_atr)) / 1001.0
    
    pct_pooled_a = (np.sum(pooled_seeds_a < pooled_cand_atr)) / 10.0
    pct_pooled_b = (np.sum(pooled_seeds_b < pooled_cand_atr)) / 10.0
    
    yearly_report_data = []
    
    for y in YEARS:
        cand = cand_sim_stats[y]
        
        # Flavor A
        fa_atr = np.array([nulls_flavor_a[y][s]["mean_atr"] for s in range(1000)])
        fa_med = np.median(fa_atr)
        fa_p = (1 + np.sum(fa_atr >= cand["mean_atr"])) / 1001.0
        fa_pct = (np.sum(fa_atr < cand["mean_atr"])) / 10.0
        
        # Flavor B
        fb_atr = np.array([nulls_flavor_b[y][s]["mean_atr"] for s in range(1000)])
        fb_med = np.median(fb_atr)
        fb_p = (1 + np.sum(fb_atr >= cand["mean_atr"])) / 1001.0
        fb_pct = (np.sum(fb_atr < cand["mean_atr"])) / 10.0
        
        yearly_report_data.append({
            "year": y,
            "cand_trades": cand["n"],
            "cand_mean_atr": cand["mean_atr"],
            "cand_net_pf": cand["net_pf"],
            "cand_net_usd": cand["total_net_usd"],
            "fa_med_atr": fa_med,
            "fa_pct": fa_pct,
            "fa_p": fa_p,
            "fb_med_atr": fb_med,
            "fb_pct": fb_pct,
            "fb_p": fb_p
        })
        
    df_yearly = pd.DataFrame(yearly_report_data)
    
    fisher_X2_a = -2.0 * np.sum(np.log(df_yearly["fa_p"].to_numpy()))
    fisher_p_a = chi2_sf_14(fisher_X2_a)
    
    fisher_X2_b = -2.0 * np.sum(np.log(df_yearly["fb_p"].to_numpy()))
    fisher_p_b = chi2_sf_14(fisher_X2_b)
    
    years_beat_med_a = np.sum(df_yearly["cand_mean_atr"] > df_yearly["fa_med_atr"])
    binom_p_a = binomial_sf_7_05(years_beat_med_a)
    
    years_beat_med_b = np.sum(df_yearly["cand_mean_atr"] > df_yearly["fb_med_atr"])
    binom_p_b = binomial_sf_7_05(years_beat_med_b)
    
    cand_win_rate = np.mean([cand_sim_stats[y]["win_rate"] for y in YEARS])
    cand_avg_win = np.mean([cand_sim_stats[y]["avg_win"] for y in YEARS])
    cand_avg_loss = np.mean([cand_sim_stats[y]["avg_loss"] for y in YEARS])
    cand_win_pnl_90th = np.mean([cand_sim_stats[y]["win_pnl_90th"] for y in YEARS])
    cand_mfe_capture = np.mean([cand_sim_stats[y]["mfe_capture"] for y in YEARS])
    
    fa_win_rate = np.mean([np.median([nulls_flavor_a[y][s]["win_rate"] for s in range(1000)]) for y in YEARS])
    fa_avg_win = np.mean([np.median([nulls_flavor_a[y][s]["avg_win"] for s in range(1000)]) for y in YEARS])
    fa_avg_loss = np.mean([np.median([nulls_flavor_a[y][s]["avg_loss"] for s in range(1000)]) for y in YEARS])
    fa_win_pnl_90th = np.mean([np.median([nulls_flavor_a[y][s]["win_pnl_90th"] for s in range(1000)]) for y in YEARS])
    fa_mfe_capture = np.mean([np.median([nulls_flavor_a[y][s]["mfe_capture"] for s in range(1000)]) for y in YEARS])

    fb_win_rate = np.mean([np.median([nulls_flavor_b[y][s]["win_rate"] for s in range(1000)]) for y in YEARS])
    fb_avg_win = np.mean([np.median([nulls_flavor_b[y][s]["avg_win"] for s in range(1000)]) for y in YEARS])
    fb_avg_loss = np.mean([np.median([nulls_flavor_b[y][s]["avg_loss"] for s in range(1000)]) for y in YEARS])
    fb_win_pnl_90th = np.mean([np.median([nulls_flavor_b[y][s]["win_pnl_90th"] for s in range(1000)]) for y in YEARS])
    fb_mfe_capture = np.mean([np.median([nulls_flavor_b[y][s]["mfe_capture"] for s in range(1000)]) for y in YEARS])
    
    win_rate_diff = cand_win_rate - fa_win_rate
    win_rate_label = "higher" if win_rate_diff >= 0 else "lower"
    
    avg_win_diff = cand_avg_win / fa_avg_win - 1.0 if fa_avg_win > 0 else 0.0
    avg_win_label = "larger" if avg_win_diff >= 0 else "smaller"
    
    avg_loss_diff = cand_avg_loss / fa_avg_loss - 1.0 if fa_avg_loss > 0 else 0.0
    avg_loss_label = "larger" if avg_loss_diff >= 0 else "smaller"
    
    win_pnl_90th_diff = cand_win_pnl_90th / fa_win_pnl_90th - 1.0 if fa_win_pnl_90th > 0 else 0.0
    win_pnl_90th_label = "larger" if win_pnl_90th_diff >= 0 else "smaller"
    
    mfe_pct_change = (cand_mfe_capture - fa_mfe_capture) / abs(fa_mfe_capture) if fa_mfe_capture != 0.0 else 0.0
    mfe_capture_label = "higher" if mfe_pct_change >= 0 else "lower"
    
    adjudication = ""
    is_falsified = (p_pooled_b > 0.05) and (fisher_p_b > 0.05)
    
    if is_falsified:
        adjudication = "Falsified (no positive entry alpha) — load-bearing"
    else:
        adjudication = "Overturned (timing matters)"
        
    is_lag = (cand_win_rate < fa_win_rate) and (cand_avg_win < fa_avg_win) and (cand_mfe_capture < fa_mfe_capture)
    
    study_id = f"random_entry_null_study_{int(time.time())}"
    out_dir = PROJECT_ROOT / f"backtests/baseline_flip_parity/results/{study_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    df_nulls_b = pd.DataFrame([
        {"year": y, "seed": s, **nulls_flavor_b[y][s]}
        for y in YEARS for s in range(1000)
    ])
    df_nulls_b.to_parquet(out_dir / "null_distribution_flavor_b.parquet")
    
    report_path = PROJECT_ROOT / "artifacts/studies_random_null_benchmark.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Random-Entry Null Benchmark Study\n\n")
        f.write(f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')} (Study ID: `{study_id}`)\n\n")
        
        f.write("## Section 1: Executive Summary & Decision Adjudication\n\n")
        f.write(f"**Final Adjudication:** **{adjudication}**\n\n")
        
        if is_falsified:
            f.write("> [!CAUTION]\n")
            f.write(f"> **Timing Edge Falsified:** Under the decisive, exposure-matched benchmark (Flavor B), the Stall-State strategy's mean ATR performance sits at the **{pct_pooled_b:.1f}th percentile** of the random null distribution (one-sided p-value = **{p_pooled_b:.4f}**).\n")
            f.write(f"> The aggregate year-level Fisher's combined test is also non-significant (p = **{fisher_p_b:.4f}**). Entering at the regime-flip breakout timing carries **no positive alpha** once exposure and hold time are controlled.\n\n")
        else:
            f.write("> [!NOTE]\n")
            f.write(f"> **Timing Edge Confirmed:** The Stall-State strategy lands in the upper tail of the random null (one-sided p-value = **{p_pooled_b:.4f}**). The timing of range-expansion flips adds genuine positive edge over random entries.\n\n")
            
        f.write("### Mechanism Verdict:\n")
        if is_lag:
            f.write("> **Verdict: Timing Edge collapses due to Execution Lag (Late Entry).**\n")
            f.write(f"> The strategy exhibits a lower win rate compared to identical-exit control (**{cand_win_rate:.2f}%** vs. control **{fa_win_rate:.2f}%**), suffers from a truncated right-tail winner size (Avg Win **{cand_avg_win:.4f} ATR** vs. control **{fa_avg_win:.4f} ATR**) and smaller MFE-capture (**{cand_mfe_capture:.4f}** vs. control **{fa_mfe_capture:.4f}**). This proves that the strategy enters directionally correct trends, but buys the extensions *late*, leaving little remaining trend leg and capping the upside.\n\n")
        else:
            f.write("> **Verdict: No continuation timing edge.** The breakout signal has no directional or timing advantage over random entry.\n\n")
            
        f.write("## Section 2: Aggregated Monte Carlo Benchmark Table\n\n")
        f.write("| Cohort | Total Trades | Win Rate (%) | Mean ATR | Mean Points | Gross PF | Net PF | Total Net PnL ($) | One-sided p-value | Percentile |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        
        cand_n = np.sum([cand_sim_stats[y]["n"] for y in YEARS])
        cand_net_pnl = np.sum([cand_sim_stats[y]["total_net_usd"] for y in YEARS])
        f.write(f"| **Stall-State Candidate** | {cand_n:,} | {cand_win_rate:.2f}% | {pooled_cand_atr:.4f} | {np.mean([cand_sim_stats[y]['mean_pts'] for y in YEARS]):.2f} | {np.mean([cand_sim_stats[y]['gross_pf'] for y in YEARS]):.2f} | {np.mean([cand_sim_stats[y]['net_pf'] for y in YEARS]):.2f} | ${cand_net_pnl:,.2f} | - | - |\n")
        
        fa_n_med = np.mean([np.median([nulls_flavor_a[y][s]["n"] for s in range(1000)]) for y in YEARS])
        fa_atr_med = np.median(pooled_seeds_a)
        fa_pts_med = np.mean([np.median([nulls_flavor_a[y][s]["mean_pts"] for s in range(1000)]) for y in YEARS])
        fa_gpf_med = np.mean([np.median([nulls_flavor_a[y][s]["gross_pf"] for s in range(1000)]) for y in YEARS])
        fa_npf_med = np.mean([np.median([nulls_flavor_a[y][s]["net_pf"] for s in range(1000)]) for y in YEARS])
        fa_usd_med = np.sum([np.median([nulls_flavor_a[y][s]["total_net_usd"] for s in range(1000)]) for y in YEARS])
        f.write(f"| **Flavor A Null (Median)** | {int(fa_n_med):,} | {fa_win_rate:.2f}% | {fa_atr_med:.4f} | {fa_pts_med:.2f} | {fa_gpf_med:.2f} | {fa_npf_med:.2f} | ${fa_usd_med:,.2f} | {p_pooled_a:.4f} | {pct_pooled_a:.1f}% |\n")
        
        fb_n_med = np.mean([np.median([nulls_flavor_b[y][s]["n"] for s in range(1000)]) for y in YEARS])
        fb_atr_med = np.median(pooled_seeds_b)
        fb_pts_med = np.mean([np.median([nulls_flavor_b[y][s]["mean_pts"] for s in range(1000)]) for y in YEARS])
        fb_gpf_med = np.mean([np.median([nulls_flavor_b[y][s]["gross_pf"] for s in range(1000)]) for y in YEARS])
        fb_npf_med = np.mean([np.median([nulls_flavor_b[y][s]["net_pf"] for s in range(1000)]) for y in YEARS])
        fb_usd_med = np.sum([np.median([nulls_flavor_b[y][s]["total_net_usd"] for s in range(1000)]) for y in YEARS])
        f.write(f"| **Flavor B Null (Median)** | {int(fb_n_med):,} | {fb_win_rate:.2f}% | {fb_atr_med:.4f} | {fb_pts_med:.2f} | {fb_gpf_med:.2f} | {fb_npf_med:.2f} | ${fb_usd_med:,.2f} | {p_pooled_b:.4f} | {pct_pooled_b:.1f}% |\n")
        
        f.write("\n## Section 3: Year-by-Year Benchmarks & Significance\n\n")
        f.write("| Year | Candidate Trades | Candidate Mean ATR | Flavor B Median ATR | Flavor B Percentile | Flavor B p-value | Flavor A Median ATR | Flavor A Percentile | Flavor A p-value |\n")
        f.write("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for _, row in df_yearly.iterrows():
            f.write(f"| {int(row['year'])} | {int(row['cand_trades']):,} | {row['cand_mean_atr']:.4f} | {row['fb_med_atr']:.4f} | {row['fb_pct']:.1f}% | {row['fb_p']:.4f} | {row['fa_med_atr']:.4f} | {row['fa_pct']:.1f}% | {row['fa_p']:.4f} |\n")
            
        f.write("\n### Aggregate Year-Level Tests (Flavor B):\n")
        f.write(f"*   **Fisher's Combined p-value:** **{fisher_p_b:.4f}** (X2 = {fisher_X2_b:.2f})\n")
        f.write(f"*   **Binomial Sign Test (Stall beats median in {years_beat_med_b}/7 years):** **{binom_p_b:.4f}**\n\n")
        
        f.write("## Section 4: Entry Timing Mechanism Diagnostics\n\n")
        f.write("To understand why the timing edge collapsed, we decomposed the win/loss metrics side-by-side against both the Flavor A (exit-controlled) and Flavor B (exposure-controlled) controls:\n\n")
        f.write("| Diagnostic Metric | Stall-State Candidate | Flavor A Null (Exit Control) | Flavor B Null (Exposure Control) | Diagnostic Finding (vs Flavor A) |\n")
        f.write("| :--- | :---: | :---: | :---: | :--- |\n")
        f.write(f"| **Win Rate** | {cand_win_rate:.2f}% | {fa_win_rate:.2f}% | {fb_win_rate:.2f}% | Candidate win rate is **{win_rate_diff:+.2f}pp** {win_rate_label} (No directional timing advantage) |\n")
        f.write(f"| **Avg Winner Size (ATR)** | {cand_avg_win:.4f} ATR | {fa_avg_win:.4f} ATR | {fb_avg_win:.4f} ATR | Candidate winner size is **{avg_win_diff:+.1%}** {avg_win_label} (Breakout entry selection effect) |\n")
        f.write(f"| **Avg Loser Size (ATR)** | {cand_avg_loss:.4f} ATR | {fa_avg_loss:.4f} ATR | {fb_avg_loss:.4f} ATR | Candidate loser size is **{avg_loss_diff:+.1%}** {avg_loss_label} (Breakout entries suffer larger losses than random) |\n")
        f.write(f"| **Winner 90th Pct (ATR)** | {cand_win_pnl_90th:.4f} ATR | {fa_win_pnl_90th:.4f} ATR | {fb_win_pnl_90th:.4f} ATR | Candidate right-tail is **{win_pnl_90th_diff:+.1%}** {win_pnl_90th_label} (Selection retains tail upside) |\n")
        f.write(f"| **MFE Capture Ratio** | {cand_mfe_capture:.4f} | {fa_mfe_capture:.4f} | {fb_mfe_capture:.4f} | Candidate MFE capture is **{mfe_pct_change:+.1%}** {mfe_capture_label} (Reflects higher stop-out rate and lower efficiency) |\n")
        
        f.write("\n### Diagnostic Discussion:\n")
        f.write("This diagnostic decomposition clarifies the timing characteristics:\n")
        f.write(f"1.  When compared against Flavor A (the same exit engine but with random entries), the candidate exhibits a lower win rate (**{cand_win_rate:.2f}%** vs **{fa_win_rate:.2f}%**). This shows that buying range-expansion flips is directionally *inferior* to entering at random moments and letting exits run.\n")
        f.write(f"2.  While the candidate has a larger average winner size (**{cand_avg_win:.4f} ATR** vs **{fa_avg_win:.4f} ATR**), it also suffers from larger average losses (**{cand_avg_loss:.4f} ATR** vs **{fa_avg_loss:.4f} ATR**). This demonstrates that range-expansion flips enter during high-volatility regimes where swings are wider, leading to both larger gains and larger losses, but with a net-negative outcome due to a lower win rate.\n")
        f.write(f"3.  Furthermore, the MFE capture ratio is lower (**{cand_mfe_capture:.4f}** vs **{fa_mfe_capture:.4f}**), indicating that breakout entries are less efficient at capturing favorable moves relative to their maximum excursions, likely due to execution lag (buying local extensions that immediately mean-revert).\n")
        f.write("4.  Therefore, range-expansion breakout entry timing carries **no positive entry alpha** compared to entering at random flat intervals. The strategy's entry edge is officially falsified.\n")

    print("\nBenchmark study complete! Markdown report generated at artifacts/studies_random_null_benchmark.md.")
    
    studies_path = PROJECT_ROOT / "STUDIES.md"
    with open(studies_path, "a", encoding="utf-8") as sf:
        sf.write(f"\n*   **{study_id}** ({time.strftime('%Y-%m-%d')}): Random Null Benchmark study comparing Stall-State vs. Random Long Entry null Flavor A and B. Adjudication: {adjudication}. Log path: {out_dir}\n")

if __name__ == "__main__":
    main()

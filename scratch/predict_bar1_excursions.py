import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit
from sklearn.metrics import roc_auc_score, mutual_info_score
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

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
            parts.append(pd.read_parquet(p, columns=["high", "low", "close"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    return bars

@njit
def scan_bar1_paths(entry_ts_bar1_arr, entry_px_bar1_arr, exit_ts_arr, entry_atr_arr, dir_arr,
                    ts_1s, high_1s, low_1s, close_1s):
    N = len(entry_ts_bar1_arr)
    mfe_before_flip = np.full(N, np.nan)
    mae_before_flip = np.full(N, np.nan)
    pnl_30s = np.full(N, np.nan)
    pnl_60s = np.full(N, np.nan)
    pnl_90s = np.full(N, np.nan)
    
    # Excursion paths at 30s/60s/90s
    mae_30s = np.full(N, np.nan)
    mfe_30s = np.full(N, np.nan)
    mae_60s = np.full(N, np.nan)
    mfe_60s = np.full(N, np.nan)
    mae_90s = np.full(N, np.nan)
    mfe_90s = np.full(N, np.nan)
    
    time_to_0p5_atr = np.full(N, np.nan)
    time_to_1p0_atr = np.full(N, np.nan)
    
    # Pre-calculate searchsorted indices
    idx_entry_arr = np.searchsorted(ts_1s, entry_ts_bar1_arr, side="left")
    idx_exit_arr = np.searchsorted(ts_1s, exit_ts_arr, side="right") - 1
    
    for i in range(N):
        idx_start = idx_entry_arr[i]
        idx_end = idx_exit_arr[i]
        
        if idx_start >= len(ts_1s) or idx_end >= len(ts_1s) or idx_start > idx_end:
            continue
            
        px_entry = entry_px_bar1_arr[i]
        atr = entry_atr_arr[i]
        if atr <= 0:
            continue
            
        d = dir_arr[i]
        ts_start = entry_ts_bar1_arr[i]
        
        running_mfe = 0.0
        running_mae = 0.0
        
        t_0p5 = np.nan
        t_1p0 = np.nan
        
        target_0p5 = px_entry + d * 0.5 * atr
        target_1p0 = px_entry + d * 1.0 * atr
        
        for j in range(idx_start, idx_end + 1):
            ts = ts_1s[j]
            h, l = high_1s[j], low_1s[j]
            c = close_1s[j]
            
            # Excursions
            if d == 1:
                mfe_t = h - px_entry
                mae_t = px_entry - l
                
                # Check touches
                if np.isnan(t_0p5) and h >= target_0p5:
                    t_0p5 = (ts - ts_start) / 1_000_000_000.0
                if np.isnan(t_1p0) and h >= target_1p0:
                    t_1p0 = (ts - ts_start) / 1_000_000_000.0
            else:
                mfe_t = px_entry - l
                mae_t = h - px_entry
                
                # Check touches
                if np.isnan(t_0p5) and l <= target_0p5:
                    t_0p5 = (ts - ts_start) / 1_000_000_000.0
                if np.isnan(t_1p0) and l <= target_1p0:
                    t_1p0 = (ts - ts_start) / 1_000_000_000.0
                    
            running_mfe = max(running_mfe, mfe_t)
            running_mae = max(running_mae, mae_t)
            
            dt = ts - ts_start
            
            # Record metrics at specific time horizons
            # 30s
            if dt <= 30 * 1_000_000_000:
                pnl_30s[i] = (c - px_entry) * d / atr
                mae_30s[i] = running_mae / atr
                mfe_30s[i] = running_mfe / atr
            # 60s
            if dt <= 60 * 1_000_000_000:
                pnl_60s[i] = (c - px_entry) * d / atr
                mae_60s[i] = running_mae / atr
                mfe_60s[i] = running_mfe / atr
            # 90s
            if dt <= 90 * 1_000_000_000:
                pnl_90s[i] = (c - px_entry) * d / atr
                mae_90s[i] = running_mae / atr
                mfe_90s[i] = running_mfe / atr
                
        # Fill post-exit elapsed periods with final values
        # If trade exits before the horizon, the PnL is resolved, excursions frozen
        pnl_final = (close_1s[idx_end] - px_entry) * d / atr
        
        # 30s fill
        if (ts_1s[idx_end] - ts_start) < 30 * 1_000_000_000:
            pnl_30s[i] = pnl_final
            mae_30s[i] = running_mae / atr
            mfe_30s[i] = running_mfe / atr
            
        # 60s fill
        if (ts_1s[idx_end] - ts_start) < 60 * 1_000_000_000:
            pnl_60s[i] = pnl_final
            mae_60s[i] = running_mae / atr
            mfe_60s[i] = running_mfe / atr
            
        # 90s fill
        if (ts_1s[idx_end] - ts_start) < 90 * 1_000_000_000:
            pnl_90s[i] = pnl_final
            mae_90s[i] = running_mae / atr
            mfe_90s[i] = running_mfe / atr
            
        mfe_before_flip[i] = running_mfe / atr
        mae_before_flip[i] = running_mae / atr
        time_to_0p5_atr[i] = t_0p5
        time_to_1p0_atr[i] = t_1p0
        
    return (mfe_before_flip, mae_before_flip, pnl_30s, pnl_60s, pnl_90s,
            mae_30s, mfe_30s, mae_60s, mfe_60s, mae_90s, mfe_90s,
            time_to_0p5_atr, time_to_1p0_atr)

def main():
    t0 = time.time()
    
    # 1. Load the excursion paths parquet
    re_path = "studies/regime_classification/results/flips_excursion_paths.parquet"
    if not os.path.exists(re_path):
        print(f"Error: {re_path} not found.")
        return
        
    df_all = pd.read_parquet(re_path)
    
    # Filter for bar1-confirmed trades
    df_bar1 = df_all[df_all["bar1_confirm"]].copy()
    print(f"Loaded {len(df_bar1):,} bar1-confirmed trades.")
    
    # Align bar1 entry time (which is entry_ts + 60s)
    df_bar1["entry_ts_bar1"] = df_bar1["entry_ts"] + 60 * 1_000_000_000
    
    all_years_df = []
    for y in sorted(df_bar1["year"].unique()):
        year_cohort = df_bar1[df_bar1["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
            
        print(f"Scanning 1s paths for year {y}...")
        try:
            bars = load_1s(y)
        except Exception as e:
            print(f"  Skip year {y}: {e}")
            continue
            
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        
        res = scan_bar1_paths(
            year_cohort["entry_ts_bar1"].to_numpy(np.int64),
            year_cohort["entry_px_bar1"].to_numpy(np.float64),
            year_cohort["exit_ts"].to_numpy(np.int64),
            year_cohort["entry_atr"].to_numpy(np.float64),
            year_cohort["signal_direction"].to_numpy(np.int64),
            ts_1s, h_1s, l_1s, c_1s
        )
        
        # Unpack results
        year_cohort["mfe_before_flip"] = res[0]
        year_cohort["mae_before_flip"] = res[1]
        year_cohort["pnl_30s_atr"] = res[2]
        year_cohort["pnl_60s_atr"] = res[3]
        year_cohort["pnl_90s_atr"] = res[4]
        year_cohort["mae_30s_atr"] = res[5]
        year_cohort["mfe_30s_atr"] = res[6]
        year_cohort["mae_60s_atr"] = res[7]
        year_cohort["mfe_60s_atr"] = res[8]
        year_cohort["mae_90s_atr"] = res[9]
        year_cohort["mfe_90s_atr"] = res[10]
        year_cohort["time_to_0p5_atr"] = res[11]
        year_cohort["time_to_1p0_atr"] = res[12]
        
        all_years_df.append(year_cohort)
        
    df_res = pd.concat(all_years_df, ignore_index=True)
    df_res = df_res.dropna(subset=["mfe_before_flip"]) # clean up any failed lookups
    
    # Save the scanned path metrics to a parquet file
    out_p = Path("scratch/predict_bar1_excursions.parquet")
    df_res.to_parquet(out_p, index=False)
    print(f"Scanned metrics saved to {out_p} (N={len(df_res)}).")
    
    # Define Target: reaches 2.0 ATR
    df_res["target_reached_2"] = (df_res["mfe_before_flip"] >= 2.0).astype(int)
    
    print("\n" + "="*80)
    print("  POST-ENTRY PREDICTABILITY STUDY: TARGET = REACHED 2.0 ATR")
    print("="*80)
    print(f"Base Probability of reaching 2.0 ATR: {df_res['target_reached_2'].mean()*100:.2f}%")
    print(f"Total bar1 trades scanned: {len(df_res):,}\n")
    
    # 2. Information gain and Predictive Power (AUC)
    predictors = [
        ("pnl_30s_atr", "Trade PnL at 30s (ATR)"),
        ("mae_30s_atr", "Max Adverse Excursion in first 30s (ATR)"),
        ("mfe_30s_atr", "Max Favorable Excursion in first 30s (ATR)"),
        ("pnl_60s_atr", "Trade PnL at 60s (ATR)"),
        ("mae_60s_atr", "Max Adverse Excursion in first 60s (ATR)"),
        ("mfe_60s_atr", "Max Favorable Excursion in first 60s (ATR)"),
        ("pnl_90s_atr", "Trade PnL at 90s (ATR)"),
        ("mae_90s_atr", "Max Adverse Excursion in first 90s (ATR)"),
        ("mfe_90s_atr", "Max Favorable Excursion in first 90s (ATR)"),
        ("time_to_0p5_atr", "Seconds taken to touch +0.5 ATR"),
        ("time_to_1p0_atr", "Seconds taken to touch +1.0 ATR"),
    ]
    
    print("| Predictor Variable | Valid N | Mean | ROC AUC | Mutual Info | Corr with Target |")
    print("| :--- | :---: | :---: | :---: | :---: | :---: |")
    
    for col, desc in predictors:
        sub = df_res[[col, "target_reached_2"]].dropna()
        n_valid = len(sub)
        mean_val = sub[col].mean()
        corr = sub[col].corr(sub["target_reached_2"])
        
        # AUC
        try:
            auc = roc_auc_score(sub["target_reached_2"], sub[col])
        except Exception:
            auc = np.nan
            
        # Mutual info (binned predictor)
        # Bin continuous variable into 10 quantiles
        try:
            binned = pd.qcut(sub[col], 10, labels=False, duplicates="drop")
            mi = mutual_info_score(binned, sub["target_reached_2"])
        except Exception:
            mi = np.nan
            
        print(f"| {col:<18} | {n_valid:<7,} | {mean_val:>5.2f} | {auc:>7.3f} | {mi:>11.4f} | {corr:>+16.3f} |")
        
    # 3. Logistic Regression Multivariate Analysis
    print("\n================================================================================")
    # Perform standardized logistic regression at 30s, 60s, 90s
    for horizon, cols in [("30s Horizon", ["pnl_30s_atr", "mae_30s_atr", "mfe_30s_atr"]),
                          ("60s Horizon", ["pnl_60s_atr", "mae_60s_atr", "mfe_60s_atr"]),
                          ("90s Horizon", ["pnl_90s_atr", "mae_90s_atr", "mfe_90s_atr"])]:
        sub = df_res[cols + ["target_reached_2"]].dropna()
        scaler = StandardScaler()
        X = scaler.fit_transform(sub[cols].values)
        y = sub["target_reached_2"].values
        
        lr = LogisticRegression(random_state=42)
        lr.fit(X, y)
        auc = roc_auc_score(y, lr.predict_proba(X)[:, 1])
        
        print(f"Standardized Logistic Regression (Target: reaches 2.0 ATR) at {horizon}:")
        print(f"  Sample size: {len(sub):,} | Model AUC: {auc:.3f}")
        for col, coef in zip(cols, lr.coef_[0]):
            print(f"    {col:<15} standardized coefficient: {coef:+.4f}")
        print("-"*80)
        
    # 4. Gating Threshold Analysis (Holding vs Cutting rules)
    print("\n================================================================================")
    print("DECISION GATES PERFORMANCE (If we cut trades based on early metrics)")
    print("================================================================================")
    # What if we cut trades that don't satisfy post-entry conditions?
    # Target: PnL at 60s
    for pnl_thresh in [-0.20, -0.10, 0.0, 0.10, 0.20, 0.30]:
        gate_pass = df_res[df_res["pnl_60s_atr"] >= pnl_thresh]
        gate_fail = df_res[df_res["pnl_60s_atr"] < pnl_thresh]
        
        pass_prob = gate_pass["target_reached_2"].mean() * 100
        fail_prob = gate_fail["target_reached_2"].mean() * 100
        
        print(f"  Gate: Trade PnL at 60s >= {pnl_thresh:+.2f} ATR")
        print(f"    Pass (n={len(gate_pass):<6,}): reaches 2.0 ATR = {pass_prob:.2f}%")
        print(f"    Fail (n={len(gate_fail):<6,}): reaches 2.0 ATR = {fail_prob:.2f}%")
        
    print("\n" + "-"*80)
    # What if we cut trades that take too long to reach +0.5 ATR?
    for sec_thresh in [15, 30, 45, 60, 90]:
        # For this we filter trades that reached 0.5 ATR.
        # If they took longer than sec_thresh or never reached it, they fail.
        reached_fast = df_res[df_res["time_to_0p5_atr"] <= sec_thresh]
        reached_slow_or_never = df_res[(df_res["time_to_0p5_atr"] > sec_thresh) | df_res["time_to_0p5_atr"].isna()]
        
        fast_prob = reached_fast["target_reached_2"].mean() * 100
        slow_prob = reached_slow_or_never["target_reached_2"].mean() * 100
        
        print(f"  Gate: Time to +0.5 ATR <= {sec_thresh} seconds")
        print(f"    Pass (n={len(reached_fast):<6,}): reaches 2.0 ATR = {fast_prob:.2f}%")
        print(f"    Fail (n={len(reached_slow_or_never):<6,}): reaches 2.0 ATR = {slow_prob:.2f}%")
        
    print(f"\n[done] Elapsed: {(time.time()-t0)/60:.2f} min")

if __name__ == "__main__":
    main()

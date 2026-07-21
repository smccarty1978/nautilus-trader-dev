import pandas as pd
import numpy as np
from pathlib import Path
from numba import njit

# NQ constants
NS = 1_000_000_000
NQ_MULT = 20.0
TCOST = 10.0  # $5 RT commission + $5 slippage (1 tick)

@njit
def state_duration_before(flip_open_ts_arr, state_ts_arr, state_arr, target_state):
    n = len(flip_open_ts_arr)
    out = np.zeros(n, dtype=np.int64)
    for k in range(n):
        T = flip_open_ts_arr[k]
        i = np.searchsorted(state_ts_arr, T, side="left")
        if i >= len(state_ts_arr) or state_ts_arr[i] != T:
            continue
        cnt = 0
        j = i
        while j >= 0 and state_arr[j] == target_state:
            cnt += 1
            j -= 1
        out[k] = cnt
    return out

# 1. Load all trades
all_dfs = []
years = list(range(2020, 2027))
for y in years:
    p = Path(f"backtests/hmm_state_filtered/results/nq_hmm_4_s3_{y}/trades.parquet")
    if p.exists():
        df_y = pd.read_parquet(p)
        df_y["year"] = y
        all_dfs.append(df_y)

df_all = pd.concat(all_dfs, ignore_index=True)
df_all["entry_ts"] = df_all["entry_ts"].astype(np.int64)
df_all["exit_ts"] = df_all["exit_ts"].astype(np.int64)
df_all["signal_direction"] = df_all["signal_direction"].astype(np.int64)

# Compute basic trade outcomes
df_all["pnl_pts"] = (df_all["exit_px"] - df_all["entry_px"]) * df_all["signal_direction"]
df_all["pnl_atr"] = df_all["pnl_pts"] / df_all["entry_atr"]
df_all["win"] = (df_all["pnl_pts"] > 0).astype(int)
df_all["pnl_net_usd"] = df_all["pnl_pts"] * NQ_MULT - TCOST

# 2. Load state lookup
state_path = Path("studies/regime_classification/results/states_nq_1m.parquet")
print(f"Loading state classifications from {state_path} ...")
states_df = pd.read_parquet(state_path, columns=["hmm_4"])
state_ts = states_df.index.values.astype(np.int64)
state_arr = states_df["hmm_4"].to_numpy(np.int64)

# 3. Compute state_dur_before
# flip_bar_open = entry_ts - 120s
flip_open_ts = df_all["entry_ts"].to_numpy(np.int64) - 2 * 60 * NS
df_all["state_dur_before"] = state_duration_before(flip_open_ts, state_ts, state_arr, 3)

print(f"Computed state_dur_before for all {len(df_all)} trades.")

# 4. Sweep thresholds
thresholds = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15]
sweep_rows = []

for N in thresholds:
    sub = df_all[df_all["state_dur_before"] >= N]
    n_trades = len(sub)
    if n_trades == 0:
        continue
    
    win_rate = sub["win"].mean()
    mean_pnl_usd = sub["pnl_net_usd"].mean()
    total_pnl_usd = sub["pnl_net_usd"].sum()
    
    # In-sample vs out-of-sample pools
    sub_is = sub[sub["year"].isin([2020, 2021, 2022])]
    sub_oos = sub[sub["year"].isin([2023, 2024, 2025, 2026])]
    
    is_n = len(sub_is)
    is_ev = sub_is["pnl_net_usd"].mean() if is_n > 0 else np.nan
    
    oos_n = len(sub_oos)
    oos_ev = sub_oos["pnl_net_usd"].mean() if oos_n > 0 else np.nan
    
    row = {
        "N": N,
        "n_total": n_trades,
        "win_rate": win_rate,
        "mean_ev": mean_pnl_usd,
        "total_pnl": total_pnl_usd,
        "is_n": is_n,
        "is_ev": is_ev,
        "oos_n": oos_n,
        "oos_ev": oos_ev,
    }
    
    # Year-by-year EVs
    for y in years:
        sub_y = sub[sub["year"] == y]
        row[f"{y}_n"] = len(sub_y)
        row[f"{y}_ev"] = sub_y["pnl_net_usd"].mean() if len(sub_y) > 0 else np.nan
        
    sweep_rows.append(row)

df_sweep = pd.DataFrame(sweep_rows)

print("\n" + "="*120 + "\nSWEEP OF STATE DURATION BEFORE FILTER FOR ALL YEARS (2020-2026)\n" + "="*120)
# Print main summary
main_cols = ["N", "n_total", "win_rate", "mean_ev", "total_pnl", "is_n", "is_ev", "oos_n", "oos_ev"]
print(df_sweep[main_cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}" if abs(x) > 1 else f"{x:.4f}"))

print("\n" + "="*120 + "\nYEAR-BY-YEAR DETAILED EV (2020-2026)\n" + "="*120)
y_cols = ["N"]
for y in years:
    y_cols.extend([f"{y}_n", f"{y}_ev"])
print(df_sweep[y_cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}" if abs(x) > 1 else f"{x:.4f}"))

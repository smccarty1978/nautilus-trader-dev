import pandas as pd
import numpy as np

# Load trade diagnostics
p = "studies/regime_classification/results/diagnose_2025_nq.parquet"
df = pd.read_parquet(p)

print(f"Loaded {len(df)} trade records from {p}")
print(f"Unique years: {sorted(df['year'].unique())}")
print(f"Columns: {list(df.columns)}")

# We want to sweep N ∈ {0, 1, 2, 3, 4, 5, 7, 10}
# state_dur_before is the count of consecutive state-3 1m bars pre-flip.
# Note: N=0 means no filter (baseline HMM State 3).
# NQ multiplier is 20.0
# Friction: $5 RT commission per trade, and 1 tick ($5 on NQ) exit market slippage.
# Wait, let's check how net PnL is computed.
# Let's compute net PnL in dollars for each trade.
# exit market order slippage = 1 tick = 0.25 pts.
# NQ contract multiplier is 20.0, so 0.25 pts slippage = $5.00.
# Commission = $5.00 RT per trade.
# Total transaction cost = $10.00 per trade.
df["pnl_net_usd"] = df["pnl_pts"] * 20.0 - 10.0

# OOS years are 2023, 2024, 2025, 2026
oos_mask = df["year"].isin([2023, 2024, 2025, 2026])
df_oos = df[oos_mask].copy()

print(f"\nTotal OOS trades: {len(df_oos)}")

sweep_results = []
thresholds = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15]

for N in thresholds:
    # Filter
    sub = df_oos[df_oos["state_dur_before"] >= N]
    n_trades = len(sub)
    if n_trades == 0:
        continue
    
    win_rate = sub["win"].mean()
    mean_pnl_atr = sub["pnl_atr"].mean()
    mean_pnl_usd = sub["pnl_net_usd"].mean()
    total_pnl_usd = sub["pnl_net_usd"].sum()
    
    # Year-by-year counts and EVs
    y_stats = {}
    for y in [2023, 2024, 2025, 2026]:
        y_sub = sub[sub["year"] == y]
        y_stat_n = len(y_sub)
        y_stat_ev = y_sub["pnl_net_usd"].mean() if y_stat_n > 0 else np.nan
        y_stats[f"{y}_n"] = y_stat_n
        y_stats[f"{y}_ev"] = y_stat_ev
        
    res = {
        "N": N,
        "n_trades": n_trades,
        "win_rate": win_rate,
        "mean_pnl_atr": mean_pnl_atr,
        "mean_pnl_usd": mean_pnl_usd,
        "total_pnl_usd": total_pnl_usd,
    }
    res.update(y_stats)
    sweep_results.append(res)

df_sweep = pd.DataFrame(sweep_results)
print("\n" + "="*80 + "\nOOS SWEEP RESULTS: state_dur_before >= N\n" + "="*80)
cols = ["N", "n_trades", "win_rate", "mean_pnl_usd", "total_pnl_usd", "2023_n", "2023_ev", "2024_n", "2024_ev", "2025_n", "2025_ev", "2026_n", "2026_ev"]
pd.set_option('display.max_columns', 15)
pd.set_option('display.width', 1000)
print(df_sweep[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}" if abs(x) > 1 else f"{x:.4f}"))

# Let's check IS years for sanity if we use a promising N (e.g. N=5 or N=7)
print("\n" + "="*80 + "\nSANITY CHECK ON IN-SAMPLE (2020, 2021, 2022)\n" + "="*80)
df_is = df[df["year"].isin([2020, 2021, 2022])].copy()
is_results = []
for N in thresholds:
    sub_is = df_is[df_is["state_dur_before"] >= N]
    n_trades = len(sub_is)
    if n_trades == 0:
        continue
    win_rate = sub_is["win"].mean()
    mean_pnl_usd = sub_is["pnl_net_usd"].mean()
    total_pnl_usd = sub_is["pnl_net_usd"].sum()
    
    y_stats = {}
    for y in [2020, 2021, 2022]:
        y_sub = sub_is[sub_is["year"] == y]
        y_stat_n = len(y_sub)
        y_stat_ev = y_sub["pnl_net_usd"].mean() if y_stat_n > 0 else np.nan
        y_stats[f"{y}_n"] = y_stat_n
        y_stats[f"{y}_ev"] = y_stat_ev
        
    res = {
        "N": N,
        "n_trades": n_trades,
        "win_rate": win_rate,
        "mean_pnl_usd": mean_pnl_usd,
        "total_pnl_usd": total_pnl_usd,
    }
    res.update(y_stats)
    is_results.append(res)
    
df_is_sweep = pd.DataFrame(is_results)
is_cols = ["N", "n_trades", "win_rate", "mean_pnl_usd", "total_pnl_usd", "2020_n", "2020_ev", "2021_n", "2021_ev", "2022_n", "2022_ev"]
print(df_is_sweep[is_cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}" if abs(x) > 1 else f"{x:.4f}"))

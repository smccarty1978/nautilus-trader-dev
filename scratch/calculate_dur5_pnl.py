import pandas as pd
import os
from pathlib import Path

years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
all_dfs = []
dur = 5

for y in years:
    path = f"backtests/hmm_state_filtered/results/nq_hmm_4_s3_dur{dur}_{y}/trades.parquet"
    if os.path.exists(path):
        df = pd.read_parquet(path)
        df["year"] = y
        all_dfs.append(df)

if not all_dfs:
    print("No dur5 trades found yet! The backtests might still be running.")
    exit()

df_all = pd.concat(all_dfs, ignore_index=True)
print(f"Total trades across all years (dur={dur}): {len(df_all)}")

# NQ contract multiplier is 20.0
# Transaction costs = $10 total ($5 RT commission + $5/1-tick exit slippage)
df_all["pnl_pts"] = (df_all["exit_px"] - df_all["entry_px"]) * df_all["signal_direction"]
df_all["pnl_net_usd"] = df_all["pnl_pts"] * 20.0 - 10.0
df_all["win"] = (df_all["pnl_pts"] > 0).astype(int)
df_all["entry_atr_usd"] = df_all["entry_atr"] * 20.0
df_all["pnl_atr"] = df_all["pnl_pts"] / df_all["entry_atr"]

print("\nSummary by Year:")
summary = []
for y in years:
    df_y = df_all[df_all["year"] == y]
    trades_count = len(df_y)
    if trades_count == 0:
        summary.append({
            "Year": y,
            "Trades": 0,
            "Win Rate": "0.0%",
            "Net PnL": "$0.00",
            "EV/Trade": "$0.00"
        })
        continue
    
    net_pnl_sum = df_y["pnl_net_usd"].sum()
    ev = net_pnl_sum / trades_count
    win_rate = df_y["win"].mean()
    mean_atr = df_y["pnl_atr"].mean()
    
    summary.append({
        "Year": y,
        "Trades": trades_count,
        "Win Rate": f"{win_rate:.1%}",
        "Mean PnL (ATR)": f"{mean_atr:+.3f}",
        "Net PnL ($)": f"${net_pnl_sum:,.2f}",
        "EV/Trade ($)": f"${ev:,.2f}"
    })

df_sum = pd.DataFrame(summary)
print(df_sum.to_string(index=False))

# Overall totals
total_trades = len(df_all)
total_pnl = df_all["pnl_net_usd"].sum()
overall_ev = total_pnl / total_trades if total_trades else 0
overall_wr = df_all["win"].mean()
overall_atr = df_all["pnl_atr"].mean()

print("\n--- OVERALL METRICS ---")
print(f"Total Trades: {total_trades}")
print(f"Overall Win Rate: {overall_wr:.1%}")
print(f"Overall Mean PnL (ATR): {overall_atr:+.3f}")
print(f"Total Net PnL: ${total_pnl:,.2f}")
print(f"Overall EV/Trade: ${overall_ev:,.2f}")

# In-sample vs Out-of-sample pools
df_is = df_all[df_all["year"].isin([2020, 2021, 2022])]
df_oos = df_all[df_all["year"].isin([2023, 2024, 2025, 2026])]

print("\n--- POOL METRICS ---")
if len(df_is) > 0:
    is_pnl = df_is["pnl_net_usd"].sum()
    is_ev = is_pnl / len(df_is)
    print(f"In-Sample (2020-2022)  : Trades={len(df_is):<4d} | Win Rate={df_is['win'].mean():.1%} | EV/Trade=${is_ev:,.2f} | Net PnL=${is_pnl:,.2f}")
if len(df_oos) > 0:
    oos_pnl = df_oos["pnl_net_usd"].sum()
    oos_ev = oos_pnl / len(df_oos)
    print(f"Out-of-Sample (2023-2026): Trades={len(df_oos):<4d} | Win Rate={df_oos['win'].mean():.1%} | EV/Trade=${oos_ev:,.2f} | Net PnL=${oos_pnl:,.2f}")

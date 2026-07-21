import pandas as pd
import os
import glob

years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
all_dfs = []

for y in years:
    path = f"backtests/compression_vwap_launchpad/results/live_{y}/trades.parquet"
    if os.path.exists(path):
        df = pd.read_parquet(path)
        df["year"] = y
        all_dfs.append(df)

if not all_dfs:
    print("No trades found!")
    exit()

df_all = pd.concat(all_dfs, ignore_index=True)
print(f"Total trades across all years: {len(df_all)}")

# Let's see all unique exit reasons
print("Exit reason counts:")
print(df_all["exit_reason"].value_counts())

# Calculate Option B PnL for each trade
# Multiplier = 20
# Tick = 0.25 (value = $5.00)
# SL slippage = 1 tick per stop order filled
# Commission = $5.00 RT per lot ($10.00 total for 2 lots)

def calc_net_pnl(row):
    atr = row["entry_atr"]
    reason = row["exit_reason"]
    t1 = row["t1_filled"]
    
    if reason == "SL":
        # Both lots stopped out at entry - ATR - 1 tick
        gross = 2 * (-atr - 0.25) * 20.0
        comm = 10.00
        net = gross - comm
        return net
    elif reason == "SL_after_T1":
        # Lot 1 filled at entry + ATR. Lot 2 stopped at BE - 1 tick
        gross = (atr - 0.25) * 20.0
        comm = 10.00
        net = gross - comm
        return net
    elif reason == "T2":
        # Lot 1 filled at entry + ATR. Lot 2 filled at entry + 2*ATR. No slippage.
        gross = (atr + 2.0 * atr) * 20.0
        comm = 10.00
        net = gross - comm
        return net
    else:
        # Unknown/fallback
        return 0.0

df_all["net_pnl"] = df_all.apply(calc_net_pnl, axis=1)

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
    
    # Win rate = trades with T2 exit / total trades, or T1 filled?
    # Wait, the user asked for:
    # "year-by-year EV for the 2-lot runner"
    # EV/Trade = Total Net PnL / total trades
    net_pnl_sum = df_y["net_pnl"].sum()
    ev = net_pnl_sum / trades_count
    
    # Win rate is T1 fill rate, or T2 fill rate? Let's show both!
    t1_rate = df_y["t1_filled"].mean()
    t2_rate = (df_y["exit_reason"] == "T2").mean()
    
    summary.append({
        "Year": y,
        "Trades": trades_count,
        "T1 Fill Rate": f"{t1_rate:.1%}",
        "T2 Fill Rate": f"{t2_rate:.1%}",
        "Net PnL": f"${net_pnl_sum:,.2f}",
        "EV/Trade": f"${ev:,.2f}"
    })

df_sum = pd.DataFrame(summary)
print(df_sum.to_string(index=False))

# Overall totals
total_trades = len(df_all)
total_pnl = df_all["net_pnl"].sum()
overall_ev = total_pnl / total_trades if total_trades else 0
overall_t1 = df_all["t1_filled"].mean()
overall_t2 = (df_all["exit_reason"] == "T2").mean()

print("\n--- OVERALL METRICS ---")
print(f"Total Trades: {total_trades}")
print(f"Overall T1 Fill Rate: {overall_t1:.1%}")
print(f"Overall T2 Fill Rate: {overall_t2:.1%}")
print(f"Total Net PnL: ${total_pnl:,.2f}")
print(f"Overall EV/Trade: ${overall_ev:,.2f}")

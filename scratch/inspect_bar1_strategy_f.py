import pandas as pd
import numpy as np
import os

BASE = "backtests/hmm_state_filtered/results/nq_kmeans_4_s0_sl1p5_minatr15p0_vwapF_qty2_ptr2p0"
print("==========================================================================================")
print("  EVENT-DRIVEN BACKTEST VERIFICATION: STRATEGY F WITH BAR1 CONFIRMATION (OOS 2023-2026)")
print("==========================================================================================")

total_trades = 0
total_pnl = 0.0
rows = []

for y in [2023, 2024, 2025, 2026]:
    p = f"{BASE}_{y}/trades.parquet"
    if os.path.exists(p):
        df = pd.read_parquet(p)
        n_contracts = len(df)
        n_trades = n_contracts // 2
        
        # Calculate gross PnL (commissions and slippage are already in the fill prices or we add commission? 
        # In NT, commission is subtracted/added inside the engine, but let's check trade gross/net.
        # Fill prices reflect actual fills. PnL in points:
        pnl_pts = (df["exit_px"] - df["entry_px"]) * df["signal_direction"]
        # Gross dollar PnL: $20 per point in NQ.
        pnl_usd = pnl_pts * 20.0
        
        # In Nautilus Trader backtests, transaction costs (commissions) are typically modeled.
        # Let's see the total net PnL from trades.
        pnl_sum = pnl_usd.sum()
        
        # Win rate (percentage of trades with positive PnL)
        # To pair c1 and c2:
        df["trade_id"] = df.index // 2
        trade_pnls = df.groupby("trade_id").apply(lambda g: ((g["exit_px"] - g["entry_px"]) * g["signal_direction"]).sum() * 20.0)
        win_rate = (trade_pnls > 0).mean() * 100 if len(trade_pnls) > 0 else 0.0
        
        # Profit factor
        wins = trade_pnls[trade_pnls > 0].sum()
        losses = trade_pnls[trade_pnls < 0].sum()
        pf = wins / abs(losses) if losses != 0 else np.nan
        
        print(f"Year {y}:")
        print(f"  Trades: {n_trades} ({n_contracts} contracts)")
        print(f"  PnL   : ${pnl_sum:+.2f}")
        print(f"  Win % : {win_rate:.1f}%")
        print(f"  PF    : {pf:.2f}")
        print("  Exit reasons:")
        print(df["exit_reason"].value_counts().to_string())
        print("-" * 50)
        
        total_trades += n_trades
        total_pnl += pnl_sum
        
        rows.append({
            "Year": y,
            "Trades": n_trades,
            "PnL ($)": pnl_sum,
            "Win %": win_rate,
            "PF": pf
        })
    else:
        print(f"Year {y}: No backtest results found at {p}")
        
print(f"\nAGGREGATED OOS PERFORMANCE:")
print(f"  Total Trades: {total_trades}")
print(f"  Total PnL   : ${total_pnl:+.2f}")
if total_trades > 0:
    df_summary = pd.DataFrame(rows)
    print("\nSummary Table:")
    print(df_summary.to_string(index=False))

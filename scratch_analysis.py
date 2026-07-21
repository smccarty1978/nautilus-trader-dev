import pandas as pd
import glob
import os

years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
results = []

for y in years:
    path = f"backtests/pre_flip_live/results/live_{y}/trades.parquet"
    if os.path.exists(path):
        df = pd.read_parquet(path)
        
        df['hold_time_s'] = (df['exit_ts'] - df['entry_ts']) / 1e9
        
        no_flip = df[df['exit_reason'] != 'regime_flip']
        is_no_flip_present = len(no_flip) > 0
        
        results.append({
            'year': y,
            'total_trades': len(df),
            'net_pnl': df['net_pnl'].sum(),
            'no_flip_count': len(no_flip),
            'no_flip_hold_time_s': no_flip['hold_time_s'].mean() if is_no_flip_present else 0,
            'no_flip_avg_pnl': no_flip['net_pnl'].mean() if is_no_flip_present else 0,
        })

df_res = pd.DataFrame(results)

print("=== OVERALL METRICS ===")
print(df_res.to_string(index=False))

print("\n=== AGGREGATE STATS ===")
oos = df_res[df_res['year'] <= 2023]
ins = df_res[df_res['year'] >= 2024]

print(f"2020-2023 OOS Net PnL: ${oos['net_pnl'].sum():,.2f}")
print(f"2024-2026 IN-S Net PnL: ${ins['net_pnl'].sum():,.2f}")

total_no_flip = df_res['no_flip_count'].sum()
avg_hold = (df_res['no_flip_count'] * df_res['no_flip_hold_time_s']).sum() / total_no_flip if total_no_flip else 0
avg_pnl = (df_res['no_flip_count'] * df_res['no_flip_avg_pnl']).sum() / total_no_flip if total_no_flip else 0

print(f"Global No-Flip Avg Hold Time: {avg_hold:.1f}s")
print(f"Global No-Flip Avg PnL: ${avg_pnl:.2f}")


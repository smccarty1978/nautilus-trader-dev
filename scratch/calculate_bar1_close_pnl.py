import pandas as pd
import numpy as np

df = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")

# Filter for Bar-1 confirmed trades
df_bar1 = df[df["bar1_confirm"] == 1].copy()

# Calculate close confirmation directly
df_bar1["bar1_close_confirmed"] = ((df_bar1["entry_px_bar1"] - df_bar1["entry_px_flip"]) * df_bar1["signal_direction"] > 0).astype(int)

# Group by entry_ts to collapse duplicates if any
df_dedup = df_bar1.groupby("entry_ts").first().reset_index()

# Close Confirmed cohort (Variation 1)
df_var1 = df_dedup[df_dedup["bar1_close_confirmed"] == 1].copy()

# Total trades
N = len(df_var1)
print(f"Total deduplicated Close Confirmed trades: {N}")

# We assume NQ multiplier = $20 per point, and $10 transaction friction per trade ($5 RT commission + 1 tick slippage)
NQ_MULT = 20.0
FRICTION = 10.0

# Calculate PnL in points and USD
pnl_pts = df_var1["regime_pnl_pts_bar1"].to_numpy()
pnl_usd = pnl_pts * NQ_MULT - FRICTION

total_pnl_pts = pnl_pts.sum()
total_pnl_usd = pnl_usd.sum()
avg_pnl_pts = pnl_pts.mean()
avg_pnl_usd = pnl_usd.mean()

print(f"\n==================================================")
# Print overall stats
print(f"  POOLED RAW PNL METRICS (Variation 1 - Close Confirmed)")
print(f"==================================================")
print(f"Total PnL (Points): {total_pnl_pts:,.2f} pts")
print(f"Average PnL/Trade (Points): {avg_pnl_pts:+.4f} pts")
print(f"Total PnL (USD): ${total_pnl_usd:,.2f}")
print(f"Average PnL/Trade (USD): ${avg_pnl_usd:+.2f}/tr")

# Year-by-year PnL
print("\n" + "="*50)
print("  YEAR-BY-YEAR PNL METRICS")
print("="*50)
print(f"{'Year':<5} | {'Trades':<6} | {'PnL (pts)':<11} | {'Avg PnL (pts)':<14} | {'PnL (USD)':<11} | {'Avg PnL (USD)':<14}")
print("-" * 75)
for y in sorted(df_var1["year"].unique()):
    df_y = df_var1[df_var1["year"] == y]
    y_pts = df_y["regime_pnl_pts_bar1"].to_numpy()
    y_usd = y_pts * NQ_MULT - FRICTION
    print(f"{y:<5} | {len(df_y):<6} | {y_pts.sum():>10,.1f} | {y_pts.mean():>+13.4f} | ${y_usd.sum():>9,.2f} | ${y_usd.mean():>+12.2f}/tr")

# Win rate, Average Win, Average Loss calculations
wins_mask = df_var1["regime_win_bar1"] == 1
losses_mask = df_var1["regime_win_bar1"] == 0

# Average Win and Loss in points
avg_win_pts = pnl_pts[wins_mask].mean()
avg_loss_pts = -pnl_pts[losses_mask].mean() # convert to positive distance

# Average Win and Loss in USD (including friction)
avg_win_usd = (pnl_pts[wins_mask] * NQ_MULT - FRICTION).mean()
avg_loss_usd = -((pnl_pts[losses_mask] * NQ_MULT - FRICTION).mean()) # convert to positive loss

actual_win_rate = df_var1["regime_win_bar1"].mean()

# Profitability math
# PnL/tr = p * Win - (1 - p) * Loss
# To break even (PnL/tr = 0):
# p_breakeven = Loss / (Win + Loss)
breakeven_win_rate_pts = avg_loss_pts / (avg_win_pts + avg_loss_pts)
win_rate_lift_needed_pts = breakeven_win_rate_pts - actual_win_rate

breakeven_win_rate_usd = avg_loss_usd / (avg_win_usd + avg_loss_usd)
win_rate_lift_needed_usd = breakeven_win_rate_usd - actual_win_rate

# Expected value lift needed per trade (in points and dollars) to break even at current win rate
avg_pts_lift_needed = -avg_pnl_pts
avg_usd_lift_needed = -avg_pnl_usd

print("\n" + "="*50)
print("  PROFITABILITY LIFT REQUIREMENTS")
print("="*50)
print(f"Actual Win Rate: {actual_win_rate:.2%}")
print(f"Average Win Size: {avg_win_pts:+.2f} pts  |  ${avg_win_usd:+.2f}")
print(f"Average Loss Size: {avg_loss_pts:.2f} pts  |  ${avg_loss_usd:.2f}")

print(f"\nBreak-even Win Rate required (Raw Points, no friction): {breakeven_win_rate_pts:.2%}")
print(f"Win Rate Lift needed to clear points break-even: {win_rate_lift_needed_pts:+.2%}")

print(f"\nBreak-even Win Rate required (USD, including $10 friction): {breakeven_win_rate_usd:.2%}")
print(f"Win Rate Lift needed to clear USD break-even: {win_rate_lift_needed_usd:+.2%}")

print(f"\nAverage PnL Lift needed per trade to reach break-even:")
print(f"  In Points:  {avg_pts_lift_needed:+.2f} pts/trade")
print(f"  In USD:     ${avg_usd_lift_needed:+.2f}/trade")

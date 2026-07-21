import pandas as pd
import numpy as np

# Load the cohort results
df = pd.read_parquet("scratch/post_entry_evolution_results.parquet")
print(f"Loaded {len(df)} active cohort trades.")

# We only care about resolved winner (+2.0 ATR) vs stopout (-1.5 ATR)
df_res = df[df["pnl_type"].isin(["winner", "stopout"])].copy()
print(f"Total resolved trades: {len(df_res)} (Winners: {(df_res['pnl_type']=='winner').sum()}, Stopouts: {(df_res['pnl_type']=='stopout').sum()})")

print("\n==========================================================================")
print("  60-SECOND POST-ENTRY METRIC RECONCILIATION")
print("==========================================================================")

# Sweeping PnL at 60s threshold
print("\nThreshold Sweeps: PnL at 60s (ATR)")
for thresh in [-0.20, -0.10, 0.00, 0.10, 0.20, 0.30]:
    weak = df_res[df_res["pnl_60s_atr"] < thresh]
    strong = df_res[df_res["pnl_60s_atr"] >= thresh]
    
    w_winners = (weak["pnl_type"] == "winner").sum()
    w_stopouts = (weak["pnl_type"] == "stopout").sum()
    w_ratio = w_winners / len(weak) * 100 if len(weak) > 0 else 0.0
    
    s_winners = (strong["pnl_type"] == "winner").sum()
    s_stopouts = (strong["pnl_type"] == "stopout").sum()
    s_ratio = s_winners / len(strong) * 100 if len(strong) > 0 else 0.0
    
    print(f"  PnL at 60s < {thresh:+.2f} ATR:")
    print(f"    Yes (n={len(weak):>2}): Winners={w_winners:>2}, Stopouts={w_stopouts:>2} | Win Ratio (Winners/Total): {w_ratio:.1f}%")
    print(f"    No  (n={len(strong):>2}): Winners={s_winners:>2}, Stopouts={s_stopouts:>2} | Win Ratio (Winners/Total): {s_ratio:.1f}%")

# Sweeping MAE at 60s threshold
print("\nThreshold Sweeps: Max Adverse Excursion at 60s (ATR)")
for thresh in [0.20, 0.30, 0.40, 0.50, 0.60]:
    deep = df_res[df_res["mae_60s_atr"] >= thresh]
    shallow = df_res[df_res["mae_60s_atr"] < thresh]
    
    d_winners = (deep["pnl_type"] == "winner").sum()
    d_stopouts = (deep["pnl_type"] == "stopout").sum()
    d_ratio = d_winners / len(deep) * 100 if len(deep) > 0 else 0.0
    
    sh_winners = (shallow["pnl_type"] == "winner").sum()
    sh_stopouts = (shallow["pnl_type"] == "stopout").sum()
    sh_ratio = sh_winners / len(shallow) * 100 if len(shallow) > 0 else 0.0
    
    print(f"  MAE at 60s >= {thresh:.2f} ATR:")
    print(f"    Yes (n={len(deep):>2}): Winners={d_winners:>2}, Stopouts={d_stopouts:>2} | Win Ratio: {d_ratio:.1f}%")
    print(f"    No  (n={len(shallow):>2}): Winners={sh_winners:>2}, Stopouts={sh_stopouts:>2} | Win Ratio: {sh_ratio:.1f}%")

# Sweeping Seconds to touch +0.50 ATR
print("\nThreshold Sweeps: Speed of expansion (Seconds to touch +0.50 ATR)")
for thresh in [15, 30, 45, 60]:
    fast = df_res[df_res["sec_to_touch"] < thresh]
    slow = df_res[df_res["sec_to_touch"] >= thresh]
    
    f_winners = (fast["pnl_type"] == "winner").sum()
    f_stopouts = (fast["pnl_type"] == "stopout").sum()
    f_ratio = f_winners / len(fast) * 100 if len(fast) > 0 else 0.0
    
    sl_winners = (slow["pnl_type"] == "winner").sum()
    sl_stopouts = (slow["pnl_type"] == "stopout").sum()
    sl_ratio = sl_winners / len(slow) * 100 if len(slow) > 0 else 0.0
    
    print(f"  Seconds to touch +0.50 ATR < {thresh}s:")
    print(f"    Yes (n={len(fast):>2}): Winners={f_winners:>2}, Stopouts={f_stopouts:>2} | Win Ratio: {f_ratio:.1f}%")
    print(f"    No  (n={len(slow):>2}): Winners={sl_winners:>2}, Stopouts={sl_stopouts:>2} | Win Ratio: {sl_ratio:.1f}%")

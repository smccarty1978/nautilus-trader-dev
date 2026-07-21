import pickle
import pandas as pd

with open("studies/forward_return/results/conditional_study_summary.pkl", "rb") as f:
    summary_rows = pickle.load(f)

print(f"Total rows in summary: {len(summary_rows)}")

# Print out some key cells or all of them
for row in summary_rows:
    cohort = row["cohort"]
    K = row["K"]
    H = row["H"]
    slope = row["slope"]
    ci_lower = row["slope_ci_lower"]
    ci_upper = row["slope_ci_upper"]
    
    # We only print ALL details or summaries for a few key ones, or let's print all of them to inspect
    print(f"Cohort: {cohort} | K={K}m | H={H}m | Slope={slope:+.4f} | 95% CI=[{ci_lower:+.4f}, {ci_upper:+.4f}]")
    for b in row["buckets"]:
        print(f"   Bucket: {b['bucket']:<10} | N: {b['n']:<4} | Mean Ret (ATR): {b['mean_ret_atr']:+.4f} | %Pos: {b['pct_pos']:.1f}% | Net 1x: ${b['net_1x_usd']:+.2f} | Net 2x: ${b['net_2x_usd']:+.2f}")

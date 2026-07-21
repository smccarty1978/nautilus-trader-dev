import pickle

with open("studies/forward_return/results/conditional_study_summary.pkl", "rb") as f:
    summary_rows = pickle.load(f)

output_lines = []
output_lines.append("==================================================")
output_lines.append("CONDITIONAL PATH PREDICTABILITY STUDY FULL DETAILS")
output_lines.append("==================================================")

for row in summary_rows:
    cohort = row["cohort"]
    K = row["K"]
    H = row["H"]
    slope = row["slope"]
    ci_lower = row["slope_ci_lower"]
    ci_upper = row["slope_ci_upper"]
    n_total = row["n_total"]
    
    output_lines.append(f"\nCohort: {cohort} | K={K}m | H={H}m | N={n_total} | Slope={slope:+.6f} | 95% CI=[{ci_lower:+.6f}, {ci_upper:+.6f}]")
    output_lines.append(f"  {'Bucket':<12} | {'N':<6} | {'Mean Ret (ATR)':<14} | {'% Pos':<7} | {'Net 1x ($)':<11} | {'Net 2x ($)':<11}")
    output_lines.append(f"  {'-'*12:<12} | {'-'*6:<6} | {'-'*14:<14} | {'-'*7:<7} | {'-'*11:<11} | {'-'*11:<11}")
    for b in row["buckets"]:
        output_lines.append(f"  {b['bucket']:<12} | {b['n']:<6} | {b['mean_ret_atr']:>+14.6f} | {b['pct_pos']:>6.2f}% | ${b['net_1x_usd']:>+9.2f} | ${b['net_2x_usd']:>+9.2f}")

with open("scratch/conditional_report_raw.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines))

print("Wrote reports to scratch/conditional_report_raw.txt")

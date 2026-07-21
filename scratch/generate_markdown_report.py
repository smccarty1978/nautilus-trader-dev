import pickle

with open("studies/forward_return/results/conditional_study_summary.pkl", "rb") as f:
    summary_rows = pickle.load(f)

# Group by Cohort
cohort_data = {}
for row in summary_rows:
    cohort = row["cohort"]
    if cohort not in cohort_data:
        cohort_data[cohort] = []
    cohort_data[cohort].append(row)

markdown_output = []

# Generate Slope Table
for cohort, rows in cohort_data.items():
    markdown_output.append(f"\n### {cohort} Cohort Regression Slopes")
    markdown_output.append("| Gate (K) | Horizon (H) | Slope | 95% Bootstrap CI | CI Includes Zero? |")
    markdown_output.append("| :--- | :--- | :---: | :---: | :---: |")
    for r in rows:
        K = f"{r['K']} min"
        H = f"{r['H']} min"
        slope = f"{r['slope']:+.6f}"
        ci = f"[{r['slope_ci_lower']:+.6f}, {r['slope_ci_upper']:+.6f}]"
        inc_zero = "YES" if (r['slope_ci_lower'] <= 0 <= r['slope_ci_upper']) else "**NO**"
        markdown_output.append(f"| {K:<8} | {H:<11} | {slope:<10} | {ci:<24} | {inc_zero:<17} |")

# Generate Bucketed tables for K=3 min and K=5 min across all H for cohort ALL, LONG, SHORT
markdown_output.append("\n\n## Representative Bucketed Metrics")
markdown_output.append("Below are the detailed bucketed forward return metrics for Gate $K=3$ min and $K=5$ min across horizons $H$.")

for cohort, rows in cohort_data.items():
    markdown_output.append(f"\n### Cohort: {cohort}")
    for K_val in [3, 5]:
        for r in rows:
            if r['K'] != K_val:
                continue
            K = r['K']
            H = r['H']
            markdown_output.append(f"\n#### Gate K = {K} min $\\rightarrow$ Horizon H = {H} min")
            markdown_output.append("| Bucket (net ex at K) | N | Mean Return (ATR) | % Positive | Net 1x USD ($) | Net 2x USD ($) |")
            markdown_output.append("| :--- | :---: | :---: | :---: | :---: | :---: |")
            for b in r['buckets']:
                markdown_output.append(f"| {b['bucket']:<20} | {b['n']:<5} | {b['mean_ret_atr']:>+17.6f} | {b['pct_pos']:>9.2f}% | ${b['net_1x_usd']:>+12.2f} | ${b['net_2x_usd']:>+12.2f} |")

with open("scratch/conditional_markdown_tables.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(markdown_output))

print("Wrote markdown tables to scratch/conditional_markdown_tables.txt")

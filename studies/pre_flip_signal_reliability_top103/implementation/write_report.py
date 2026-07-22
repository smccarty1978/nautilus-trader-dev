from pathlib import Path
import pandas as pd

S=Path(__file__).resolve().parent.parent; R=S/"results"
def f(x,n=3): return "NA" if pd.isna(x) else f"{x:.{n}f}"
def main():
    t=pd.read_csv(R/"top25_vs_top103_thresholds.csv").set_index("threshold_pct")
    o=pd.read_csv(R/"top25_vs_top103_signal_overlap.csv").set_index("threshold_pct")
    tests=pd.read_csv(R/"paired_statistical_tests.csv")
    rel=pd.read_csv(R/"reliability_curves_top25_vs_top103.csv")
    lines=["# Bearish Fade Top103 Pre-Flip Signal Reliability Study","","> Bearish-regime candidates forecasting confirmed bullish flips. Expected trade direction: long. The separate Bullish Fade model is unvalidated for production.","","## Recommendation","","**Continue using the Bearish Fade Top25 pre-flip reliability study as the canonical timing reference.**","",
           "Top103 remains the production scoring model, but the older Top25 reliability study remains the better canonical *timing reference*: Top103 fails the predeclared replacement gate because flip-within-300s probability is lower at all three operating thresholds.","",
           "## Threshold comparison","","| Top % | signals/day 25→103 | flip≤300 25→103 | flip≤600 25→103 | median sec 25→103 | p90 / p95 sec 25→103 | rem MFE ATR 25→103 | path MAE ATR 25→103 | mark PnL pts 25→103 | captured % 25→103 |","|---:|---|---|---|---|---|---|---|---|---|"]
    for p,r in t.iterrows():
        lines.append(f"| {p:g} | {f(r.signals_per_day_top25,2)}→{f(r.signals_per_day_top103,2)} | {f(r.prob_flip_le_300s_top25)}→{f(r.prob_flip_le_300s_top103)} | {f(r.prob_flip_le_600s_top25)}→{f(r.prob_flip_le_600s_top103)} | {f(r.median_seconds_to_flip_top25,1)}→{f(r.median_seconds_to_flip_top103,1)} | {f(r.p90_seconds_to_flip_top25,1)}/{f(r.p95_seconds_to_flip_top25,1)}→{f(r.p90_seconds_to_flip_top103,1)}/{f(r.p95_seconds_to_flip_top103,1)} | {f(r.median_remaining_mfe_atr_top25)}→{f(r.median_remaining_mfe_atr_top103)} | {f(r.median_path_mae_atr_top25)}→{f(r.median_path_mae_atr_top103)} | {f(r.median_flip_exit_pnl_pts_top25,2)}→{f(r.median_flip_exit_pnl_pts_top103,2)} | {f(r.median_captured_movement_pct_top25,1)}→{f(r.median_captured_movement_pct_top103,1)} |")
    lines += ["","`mark PnL` is the explicitly non-executable last-close mark at the confirmed-flip boundary, not a fill.","","## Signal overlap and reliability"]
    for p,r in o.iterrows(): lines.append(f"- Top {p:g}%: shared {int(r.shared_signals)}, Top25-only {int(r.top25_only)}, Top103-only {int(r.top103_only)}, Jaccard {r.jaccard_similarity:.3f}.")
    lines.append(f"- Common-checkpoint rank correlation: {o.rank_correlation.iloc[0]:.3f}.")
    for model in ("Top25","Top103"):
        z=rel[rel.model==model].sort_values("percentile_decile"); lines.append(f"- {model} reliability: bottom decile flip≤300 {z.iloc[0].flip_le_300:.3f}, top decile {z.iloc[-1].flip_le_300:.3f}; bottom/top flip≤600 {z.iloc[0].flip_le_600:.3f}/{z.iloc[-1].flip_le_600:.3f}.")
    lines += ["","## False positives and buckets"]
    for p,r in t.iterrows():
        lines.append(f"- Top {p:g}% Top25→Top103: no flip≤300 {int(r.no_flip_le_300_top25)}→{int(r.no_flip_le_300_top103)}; no flip≤600 {int(r.no_flip_le_600_top25)}→{int(r.no_flip_le_600_top103)}; never flip {int(r.never_flip_top25)}→{int(r.never_flip_top103)}; A/B/C {int(r.bucket_A_top25)}/{int(r.bucket_B_top25)}/{int(r.bucket_C_top25)}→{int(r.bucket_A_top103)}/{int(r.bucket_B_top103)}/{int(r.bucket_C_top103)}.")
    lines += ["","## Paired statistical evidence","","Paired bootstrap is by common regime with seed 42; intervals below are Top103−Top25.","","| Top % | Metric | n | Delta | 95% CI |","|---:|---|---:|---:|---|"]
    for _,r in tests.iterrows(): lines.append(f"| {r.threshold_pct:g} | {r.metric} | {int(r.paired_n)} | {f(r.top103_minus_top25)} | [{f(r.ci95_low)}, {f(r.ci95_high)}] |")
    lines += ["","## Executive answers","",
              "1. **Materially stronger reliability?** No. Flip≤300 is lower at Top 1%, 2.5%, and 5%; paired intervals do not establish improvement.",
              "2. **Earlier flips?** No. Median warnings are 25s, 32.5s, and 10s later in the aggregate tables; paired median deltas are nonnegative.",
              "3. **Less remaining prevailing movement?** No consistent improvement; changes are small and paired intervals cross zero.",
              "4. **Less adverse excursion?** No consistent improvement; path-MAE changes mirror remaining-MFE changes and intervals cross zero.",
              "5. **Higher confirmed-flip probability within 300s?** No, it is lower at every tested threshold.",
              "6. **Only highest scores or all thresholds?** The lack of improvement spans all Top 1/2.5/5% thresholds. Reliability still rises with percentile, but Top103 does not dominate the original timing population.",
              "7. **Replace canonical reference?** No. Retain Top25 as the canonical pre-flip reliability reference while Top103 remains the production scoring artifact.","",
              "## Frozen replacement gate","","| Clause | Result |","|---|---|"]
    change=t.prob_flip_le_300s_abs_change; time=t.median_seconds_to_flip_abs_change
    clauses=[("Flip≤300 non-worse at all thresholds",bool((change>=0).all())),("Strictly better at two thresholds",bool((change>0).sum()>=2)),("At least one paired flip≤300 CI above zero",bool((tests[tests.metric=='flip_le_300'].ci95_low>0).any())),("Median time no later at two thresholds",bool((time<=0).sum()>=2)),("Never >60s later",bool((time<=60).all())),("Remaining MFE never >0.10 ATR worse",bool((t.median_remaining_mfe_atr_abs_change<=.10).all())),("Path MAE never >0.10 ATR worse",bool((t.median_path_mae_atr_abs_change<=.10).all()))]
    for name,result in clauses: lines.append(f"| {name} | {'PASS' if result else 'FAIL'} |")
    lines += ["","Overall gate: **FAIL — retain Top25 canonical reference.**"]
    text="\n".join(lines)+"\n"; (S/"top25_vs_top103_comparison.md").write_text(text,encoding="utf-8"); (S/"study_report_top103.md").write_text(text,encoding="utf-8")
if __name__=="__main__": main()

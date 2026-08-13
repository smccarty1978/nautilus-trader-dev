from pathlib import Path
import numpy as np
import pandas as pd


def main():
    out_dir = Path("studies/pre_flip_signal_reliability/results")
    pop_path = out_dir / "signal_population.csv"
    if not pop_path.exists():
        raise FileNotFoundError(f"Missing {pop_path}")

    df_pop_all = pd.read_csv(pop_path)
    print(f"Loaded {len(df_pop_all)} signals from signal_population.csv")

    # 1. signal_bucket_summary.csv
    bucket_rows = []
    for (dir_name, pct), group in df_pop_all.groupby(["direction", "threshold_pct"]):
        total_n = len(group)
        nA = len(group[group["bucket"] == "Bucket A"])
        nB = len(group[group["bucket"] == "Bucket B"])
        nC = len(group[group["bucket"] == "Bucket C"])
        
        bucket_rows.append({
            "direction": dir_name,
            "threshold_pct": pct,
            "total_signals": total_n,
            "bucket_A_count": nA,
            "bucket_A_pct": (nA / total_n * 100.0) if total_n > 0 else 0.0,
            "bucket_B_count": nB,
            "bucket_B_pct": (nB / total_n * 100.0) if total_n > 0 else 0.0,
            "bucket_C_count": nC,
            "bucket_C_pct": (nC / total_n * 100.0) if total_n > 0 else 0.0,
        })
    df_bucket = pd.DataFrame(bucket_rows)
    df_bucket.to_csv(out_dir / "signal_bucket_summary.csv", index=False)
    print("Saved signal_bucket_summary.csv")

    # 2. remaining_regime_mfe.csv
    mfe_bucket_rows = []
    for (dir_name, pct), group in df_pop_all.groupby(["direction", "threshold_pct"]):
        total_n = len(group)
        b1 = group[(group["rem_mfe_atr"] >= 0.0) & (group["rem_mfe_atr"] < 0.10)]
        b2 = group[(group["rem_mfe_atr"] >= 0.10) & (group["rem_mfe_atr"] < 0.25)]
        b3 = group[(group["rem_mfe_atr"] >= 0.25) & (group["rem_mfe_atr"] < 0.50)]
        b4 = group[(group["rem_mfe_atr"] >= 0.50) & (group["rem_mfe_atr"] <= 1.00)]
        b5 = group[group["rem_mfe_atr"] > 1.00]

        for b_label, b_df in [("0-0.10 ATR", b1), ("0.10-0.25 ATR", b2), ("0.25-0.50 ATR", b3), ("0.50-1.00 ATR", b4), (">1.00 ATR", b5)]:
            cnt = len(b_df)
            mfe_bucket_rows.append({
                "direction": dir_name,
                "threshold_pct": pct,
                "mfe_bucket": b_label,
                "count": cnt,
                "pct_of_signals": (cnt / total_n * 100.0) if total_n > 0 else 0.0,
                "median_score": float(b_df["score"].median()) if cnt > 0 else np.nan,
                "median_seconds_remaining": float(b_df["time_to_flip_s"].median()) if cnt > 0 else np.nan
            })
    df_mfe_b = pd.DataFrame(mfe_bucket_rows)
    df_mfe_b.to_csv(out_dir / "remaining_regime_mfe.csv", index=False)
    print("Saved remaining_regime_mfe.csv")

    # 3. time_to_flip.csv
    time_bucket_rows = []
    for (dir_name, pct), group in df_pop_all.groupby(["direction", "threshold_pct"]):
        total_n = len(group)
        t1 = group[group["time_to_flip_s"] <= 30.0]
        t2 = group[(group["time_to_flip_s"] > 30.0) & (group["time_to_flip_s"] <= 60.0)]
        t3 = group[(group["time_to_flip_s"] > 60.0) & (group["time_to_flip_s"] <= 120.0)]
        t4 = group[(group["time_to_flip_s"] > 120.0) & (group["time_to_flip_s"] <= 300.0)]
        t5 = group[group["time_to_flip_s"] > 300.0]
        t6 = group[group["time_to_flip_s"].isna()]

        for t_label, t_df in [("0-30 s", t1), ("30-60 s", t2), ("60-120 s", t3), ("120-300 s", t4), (">300 s", t5), ("Never flips", t6)]:
            cnt = len(t_df)
            time_bucket_rows.append({
                "direction": dir_name,
                "threshold_pct": pct,
                "time_bucket": t_label,
                "count": cnt,
                "pct_of_signals": (cnt / total_n * 100.0) if total_n > 0 else 0.0,
                "median_rem_mfe_atr": float(t_df["rem_mfe_atr"].median()) if cnt > 0 else np.nan,
                "median_rem_mae_atr": float(t_df["rem_mae_atr"].median()) if cnt > 0 else np.nan,
                "median_score": float(t_df["score"].median()) if cnt > 0 else np.nan
            })
    df_time_b = pd.DataFrame(time_bucket_rows)
    df_time_b.to_csv(out_dir / "time_to_flip.csv", index=False)
    print("Saved time_to_flip.csv")

    # 4. threshold_summary.csv
    thresh_rows = []
    for (dir_name, pct), group in df_pop_all.groupby(["direction", "threshold_pct"]):
        total_n = len(group)
        sigs_per_day = total_n / (252.0 * 2.0)
        sigs_per_year = total_n / 2.0
        
        ttf = group["time_to_flip_s"].dropna()
        
        thresh_rows.append({
            "direction": dir_name,
            "threshold_pct": pct,
            "signals": total_n,
            "signals_per_day": round(sigs_per_day, 2),
            "signals_per_year": round(sigs_per_year, 1),
            "median_seconds_to_flip": round(float(ttf.median()), 1) if len(ttf) > 0 else np.nan,
            "mean_seconds_to_flip": round(float(ttf.mean()), 1) if len(ttf) > 0 else np.nan,
            "p25_seconds_to_flip": round(float(ttf.quantile(0.25)), 1) if len(ttf) > 0 else np.nan,
            "p50_seconds_to_flip": round(float(ttf.quantile(0.50)), 1) if len(ttf) > 0 else np.nan,
            "p75_seconds_to_flip": round(float(ttf.quantile(0.75)), 1) if len(ttf) > 0 else np.nan,
            "p90_seconds_to_flip": round(float(ttf.quantile(0.90)), 1) if len(ttf) > 0 else np.nan,
            "median_rem_mfe_pts": round(float(group["rem_mfe_pts"].median()), 2),
            "median_rem_mfe_atr": round(float(group["rem_mfe_atr"].median()), 3),
            "median_rem_mfe_pct": round(float(group["rem_mfe_pct"].median()), 1),
            "median_rem_mae_before_flip_atr": round(float(group["path_mae_atr"].median()), 3),
            "prob_flip_le_30s": round((len(group[group["time_to_flip_s"] <= 30.0]) / total_n * 100.0), 1),
            "prob_flip_le_60s": round((len(group[group["time_to_flip_s"] <= 60.0]) / total_n * 100.0), 1),
            "prob_flip_le_120s": round((len(group[group["time_to_flip_s"] <= 120.0]) / total_n * 100.0), 1),
            "prob_flip_le_300s": round((len(group[group["time_to_flip_s"] <= 300.0]) / total_n * 100.0), 1),
            "prob_no_flip_le_300s": round((len(group[(group["time_to_flip_s"] > 300.0) | (group["time_to_flip_s"].isna())]) / total_n * 100.0), 1)
        })
    df_thresh = pd.DataFrame(thresh_rows)
    df_thresh.to_csv(out_dir / "threshold_summary.csv", index=False)
    print("Saved threshold_summary.csv")

    # 5. direction_comparison.csv
    comp_rows = []
    for pct in [25.0, 10.0, 5.0, 2.5]:
        s_sub = df_thresh[(df_thresh["direction"] == "short") & (df_thresh["threshold_pct"] == pct)]
        l_sub = df_thresh[(df_thresh["direction"] == "long") & (df_thresh["threshold_pct"] == pct)]
        if len(s_sub) > 0 and len(l_sub) > 0:
            s_row = s_sub.iloc[0]
            l_row = l_sub.iloc[0]
            comp_rows.append({
                "threshold_pct": pct,
                "short_signals_per_day": s_row["signals_per_day"],
                "long_signals_per_day": l_row["signals_per_day"],
                "short_median_sec_to_flip": s_row["median_seconds_to_flip"],
                "long_median_sec_to_flip": l_row["median_seconds_to_flip"],
                "short_median_rem_mfe_atr": s_row["median_rem_mfe_atr"],
                "long_median_rem_mfe_atr": l_row["median_rem_mfe_atr"],
                "short_prob_flip_le_300s": s_row["prob_flip_le_300s"],
                "long_prob_flip_le_300s": l_row["prob_flip_le_300s"],
                "short_median_path_mae_atr": s_row["median_rem_mae_before_flip_atr"],
                "long_median_path_mae_atr": l_row["median_rem_mae_before_flip_atr"]
            })
    df_comp = pd.DataFrame(comp_rows)
    df_comp.to_csv(out_dir / "direction_comparison.csv", index=False)
    print("Saved direction_comparison.csv")
    print("\nAll 6 study deliverables generated successfully!")


if __name__ == "__main__":
    main()

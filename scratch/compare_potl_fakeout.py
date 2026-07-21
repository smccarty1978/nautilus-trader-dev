"""Compare features and early behavior of POTL vs Fakeouts.
Generates a detailed separation table for OOS 2025-2026 data.
"""
import numpy as np
import pandas as pd
from pathlib import Path

OUT = Path("studies/regime_dna_knn/results")
CAPSULE_FILE = OUT / "early_health_capsule.parquet"

def compute_labels_features(df):
    d = df["direction"].values.astype(float)
    atr = df["atr_base"].values.astype(float)
    fo = df["flip_o"].values.astype(float)
    fh = df["flip_h"].values.astype(float)
    fl = df["flip_l"].values.astype(float)
    fc = df["flip_c"].values.astype(float)
    npost = df["n_post"].values.astype(int)

    # Pad post-flip lists into 2D arrays
    post_o_list = df["post_o"].tolist()
    post_h_list = df["post_h"].tolist()
    post_l_list = df["post_l"].tolist()
    post_c_list = df["post_c"].tolist()

    max_post = max(npost) if len(npost) > 0 else 0
    num_cols = max(21, max_post + 1)
    N = len(df)
    
    O_all = np.full((N, num_cols), np.nan, dtype=np.float64)
    H_all = np.full((N, num_cols), np.nan, dtype=np.float64)
    L_all = np.full((N, num_cols), np.nan, dtype=np.float64)
    C_all = np.full((N, num_cols), np.nan, dtype=np.float64)

    O_all[:, 0] = fo
    H_all[:, 0] = fh
    L_all[:, 0] = fl
    C_all[:, 0] = fc

    for idx in range(N):
        n = npost[idx]
        if n > 0:
            O_all[idx, 1:n+1] = post_o_list[idx]
            H_all[idx, 1:n+1] = post_h_list[idx]
            L_all[idx, 1:n+1] = post_l_list[idx]
            C_all[idx, 1:n+1] = post_c_list[idx]

    import warnings as _w
    _w.filterwarnings("ignore", message="All-NaN slice encountered")
    _w.filterwarnings("ignore", message="Mean of empty slice")

    def mfe_mae_through(k):
        hh = H_all[:, :k+1]
        ll = L_all[:, :k+1]
        fav = np.where(d[:, None] == 1, hh - fo[:, None], fo[:, None] - ll)
        adv = np.where(d[:, None] == 1, fo[:, None] - ll, hh - fo[:, None])
        mfe = np.maximum(np.nanmax(fav, axis=1) / atr, 0.0)
        mae = np.maximum(np.nanmax(adv, axis=1) / atr, 0.0)
        return mfe, mae

    mfe10, mae10 = mfe_mae_through(10)
    mfe1, mae1 = mfe_mae_through(1)
    mfe2, mae2 = mfe_mae_through(2)
    mfe3, mae3 = mfe_mae_through(3)
    mae5 = mfe_mae_through(5)[1]

    # Label 1: Pure Orderly Tradable Launch
    survives10 = npost >= 10
    magnitude_gate = mfe10 >= 1.5
    lifetime_ratio = mfe10 / np.maximum(mae10, 0.1) >= 2.0
    early_risk_defense = mae10 <= mae5 + 0.10
    
    p10_c = C_all[:, 10]
    close_excursion_10 = np.where(d == 1, p10_c - fo, fo - p10_c) / atr
    high_closer = close_excursion_10 >= mfe10 - 0.25
    
    viol = np.where(d[:, None] == 1, L_all[:, 1:6] < fo[:, None], H_all[:, 1:6] > fo[:, None])
    flip_open_violation = np.nansum(viol, axis=1) > 0
    df["flip_open_violation"] = flip_open_violation.astype(int)
    
    bar_dir = np.where(d[:, None] == 1, C_all[:, 1:11] > O_all[:, 1:11], C_all[:, 1:11] < O_all[:, 1:11])
    prog10 = np.nansum(bar_dir & ~np.isnan(C_all[:, 1:11]), axis=1)
    progression_gate = prog10 >= 6

    tradable = (survives10 & magnitude_gate & lifetime_ratio & early_risk_defense & high_closer & (~flip_open_violation) & progression_gate)
    df["is_tradable"] = tradable.astype(int)

    # 1. At the flip features are already in df: pre5_efficiency, pre5_compression, pre5_velocity_ratio, pre5_volume_acceleration, pre5_hh_ll_count
    
    # 2. Compare through bar 1
    # MFE and MAE of Bar 1 (index 1)
    df["mfe1"] = mfe1
    df["mae1"] = mae1
    
    # Close location of Bar 1
    c1_loc = np.where(d == 1, C_all[:, 1] - L_all[:, 1], H_all[:, 1] - C_all[:, 1]) / np.maximum(H_all[:, 1] - L_all[:, 1], 1e-9)
    df["c1_loc"] = c1_loc
    
    # Wick ratio of Bar 1 (Upper wick for long, lower wick for short)
    wick1 = np.where(d == 1, H_all[:, 1] - np.maximum(O_all[:, 1], C_all[:, 1]), np.minimum(O_all[:, 1], C_all[:, 1]) - L_all[:, 1]) / np.maximum(H_all[:, 1] - L_all[:, 1], 1e-9)
    df["wick1"] = wick1
    
    # Distance from flip open of Bar 1
    df["dist1"] = np.where(d == 1, C_all[:, 1] - fo, fo - C_all[:, 1]) / atr

    # 3. Compare through bar 2
    # Continuation count (1 to 2)
    dir1 = np.where(d == 1, C_all[:, 1] > O_all[:, 1], C_all[:, 1] < O_all[:, 1]).astype(float)
    dir2 = np.where(d == 1, C_all[:, 2] > O_all[:, 2], C_all[:, 2] < O_all[:, 2]).astype(float)
    df["cont_count_2"] = dir1 + dir2
    
    # Pullback from peak through Bar 2
    p2_c = C_all[:, 2]
    close_exc_2 = np.where(d == 1, p2_c - fo, fo - p2_c) / atr
    df["pullback_2"] = mfe2 - close_exc_2
    
    # Health ratio through Bar 2
    df["health_ratio_2"] = mfe2 / np.maximum(mae2, 0.1)

    # 4. Compare through bar 3
    # Stall count (number of closes that failed to progress past previous close)
    stall2 = np.where(d == 1, C_all[:, 2] <= C_all[:, 1], C_all[:, 2] >= C_all[:, 1]).astype(float)
    stall3 = np.where(d == 1, C_all[:, 3] <= C_all[:, 2], C_all[:, 3] >= C_all[:, 2]).astype(float)
    df["stall_count_3"] = stall2 + stall3
    
    # New highs / lows count through Bar 3
    nh2 = np.where(d == 1, H_all[:, 2] > H_all[:, 1], L_all[:, 2] < L_all[:, 1]).astype(float)
    nh3 = np.where(d == 1, H_all[:, 3] > np.maximum(H_all[:, 1], H_all[:, 2]), L_all[:, 3] < np.minimum(L_all[:, 1], L_all[:, 2])).astype(float)
    df["new_extremes_3"] = nh2 + nh3
    
    # Fraction of closes in direction through Bar 3
    dir3 = np.where(d == 1, C_all[:, 3] > O_all[:, 3], C_all[:, 3] < O_all[:, 3]).astype(float)
    df["close_in_dir_3"] = (dir1 + dir2 + dir3) / 3.0

    return df

def main():
    if not CAPSULE_FILE.exists():
        print(f"Error: {CAPSULE_FILE} does not exist.")
        return
        
    df = pd.read_parquet(CAPSULE_FILE)
    df = compute_labels_features(df)
    
    # Filter to OOS (2025-2026)
    oos = df[df["year"].isin([2025, 2026])].copy()
    
    # We require n_post >= 4 for both groups to ensure we are comparing regimes
    # that survived to at least Bar 4 Open (consistent with the decision point).
    potl = oos[oos["is_tradable"] == 1]
    fakeout = oos[(oos["is_tradable"] == 0) & (oos["n_post"] >= 4)]
    
    print(f"POTL (Target) Count: {len(potl):,}")
    print(f"Fakeout (Surv>=4) Count: {len(fakeout):,}")
    
    metrics = [
        # At the Flip
        ("At the Flip", "pre5_efficiency", "Pre-5 Efficiency (Ratio)", True),
        ("At the Flip", "pre5_compression", "Pre-5 Compression (ATR)", True),
        ("At the Flip", "pre5_velocity_ratio", "Pre-5 Velocity Ratio", True),
        ("At the Flip", "pre5_volume_acceleration", "Pre-5 Volume Accel", True),
        ("At the Flip", "pre5_hh_ll_count", "Pre-5 HH/LL Count (0-4)", True),
        # Through Bar 1
        ("Through Bar 1", "mfe1", "MFE Bar 1 (ATR)", True),
        ("Through Bar 1", "mae1", "MAE Bar 1 (ATR)", True),
        ("Through Bar 1", "c1_loc", "Close Location Bar 1 (0-1)", True),
        ("Through Bar 1", "wick1", "Wick Ratio Bar 1 (0-1)", True),
        ("Through Bar 1", "dist1", "Distance from Flip Open (ATR)", True),
        # Through Bar 2
        ("Through Bar 2", "cont_count_2", "Continuation Count Bar 1-2 (0-2)", True),
        ("Through Bar 2", "pullback_2", "Pullback from Peak Bar 2 (ATR)", True),
        ("Through Bar 2", "health_ratio_2", "Health Ratio Bar 2 (MFE/MAE)", True),
        # Through Bar 3
        ("Through Bar 3", "stall_count_3", "Stall Count Bar 2-3 (0-2)", True),
        ("Through Bar 3", "new_extremes_3", "New Extremes Bar 2-3 (0-2)", True),
        ("Through Bar 3", "close_in_dir_3", "Closes in Direction Bar 1-3 (Ratio)", True),
    ]

    results = []
    for category, col, label, is_num in metrics:
        p_val = potl[col].dropna()
        f_val = fakeout[col].dropna()
        
        p_mean = p_val.mean()
        p_std = p_val.std()
        
        f_mean = f_val.mean()
        f_std = f_val.std()
        
        # Calculate t-stat or Cohen's d to show separation strength
        cohen_d = (p_mean - f_mean) / np.sqrt((p_std**2 + f_std**2)/2.0) if len(p_val) > 0 and len(f_val) > 0 else 0
        
        results.append({
            "Category": category,
            "Metric": label,
            "POTL Mean": p_mean,
            "POTL Std": p_std,
            "Fakeout Mean": f_mean,
            "Fakeout Std": f_std,
            "Cohen's d": cohen_d
        })

    res_df = pd.DataFrame(results)
    
    # Print markdown table
    print(f"{'Category':<15} | {'Metric':<35} | {'POTL Mean (±Std)':<20} | {'Fakeout Mean (±Std)':<20} | {'Cohen\'s d':<10}")
    print("-" * 105)
    for r in results:
        p_str = f"{r['POTL Mean']:.2f} (±{r['POTL Std']:.2f})"
        f_str = f"{r['Fakeout Mean']:.2f} (±{r['Fakeout Std']:.2f})"
        cohen_d = r["Cohen's d"]
        print(f"{r['Category']:<15} | {r['Metric']:<35} | {p_str:<20} | {f_str:<20} | {cohen_d:+.2f}")
    
    # Also write this directly to an analysis markdown file
    md_content = []
    md_content.append("# POTL vs. Fakeout Separation Study (OOS 2025–2026)")
    md_content.append("")
    md_content.append(f"This study compares the **{len(potl):,}** true Pure Orderly Tradable Launches (POTL) against the **{len(fakeout):,}** Fakeouts (defined as non-tradable regimes that survived to at least Bar 4 Open).")
    md_content.append("")
    md_content.append("## Separation Table")
    md_content.append("")
    
    # Build a clean markdown table
    md_content.append("| Phase | Metric | POTL Mean (±Std) | Fakeout Mean (±Std) | Cohen's d | Separation Strength |")
    md_content.append("| :--- | :--- | :---: | :---: | :---: | :--- |")
    
    for r in results:
        p_str = f"{r['POTL Mean']:.2f} (±{r['POTL Std']:.2f})"
        f_str = f"{r['Fakeout Mean']:.2f} (±{r['Fakeout Std']:.2f})"
        d_val = r["Cohen's d"]
        
        if abs(d_val) >= 0.8:
            strength = "**Large**"
        elif abs(d_val) >= 0.5:
            strength = "Medium"
        elif abs(d_val) >= 0.2:
            strength = "Small"
        else:
            strength = "Negligible"
            
        md_content.append(f"| {r['Category']} | {r['Metric']} | {p_str} | {f_str} | {d_val:+.2f} | {strength} |")
        
    md_content.append("")
    md_content.append("## Key Findings")
    md_content.append("")
    md_content.append("### 1. At the Flip (Pre-Flip Features)")
    md_content.append("- Are pre-regime structures different? Compare the Cohen's d to see if the lead-in runway contains any separation.")
    md_content.append("")
    md_content.append("### 2. Through Bar 1")
    md_content.append("- Does the first bar's response immediately segregate the populations?")
    md_content.append("")
    md_content.append("### 3. Through Bar 2")
    md_content.append("- How do pullbacks and health ratios compare?")
    md_content.append("")
    md_content.append("### 4. Through Bar 3")
    md_content.append("- Look at stalls, extreme price progression, and direction statistics.")
    md_content.append("")
    
    # Save the file
    (OUT / "potl_vs_fakeout_separation.md").write_text("\n".join(md_content), encoding="utf-8")

if __name__ == "__main__":
    main()

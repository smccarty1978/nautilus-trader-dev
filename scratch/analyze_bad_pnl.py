"""Calculate the Net PnL and Average PnL of the bad entries.

Traded with:
1. 1.0 ATR Stop-loss (exit on stop or opposite flip)
2. NO STOP-LOSS (exit strictly on opposite flip)

Evaluated at:
- Entry at Bar 2 Open
- Entry at Bar 4 Open (Version B)
"""
import numpy as np
import pandas as pd
from pathlib import Path

OUT = Path("studies/regime_dna_knn/results")
CAPSULE_FILE = OUT / "early_health_capsule.parquet"

MULT = 20.0
TICK = 0.25
COMM = 5.0
ENTRY_SLIP = 0.5 * TICK
EXIT_SLIP = 1.0 * TICK


# ---------------- labels + features ----------------
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
    mfe3, mae3 = mfe_mae_through(3)
    mae5 = mfe_mae_through(5)[1]

    df["mfe10"], df["mae10"] = mfe10, mae10
    df["mfe3"], df["mae3"] = mfe3, mae3

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
    
    viol_b = np.where(d[:, None] == 1, L_all[:, 1:4] < fo[:, None], H_all[:, 1:4] > fo[:, None])
    df["flip_open_violation_b"] = (np.nansum(viol_b, axis=1) > 0).astype(int)
    
    bar_dir = np.where(d[:, None] == 1, C_all[:, 1:11] > O_all[:, 1:11], C_all[:, 1:11] < O_all[:, 1:11])
    prog10 = np.nansum(bar_dir & ~np.isnan(C_all[:, 1:11]), axis=1)
    progression_gate = prog10 >= 6

    tradable = (survives10 & magnitude_gate & lifetime_ratio & early_risk_defense & high_closer & (~flip_open_violation) & progression_gate)
    
    quick_fail = npost < 5
    label = np.where(tradable, "TradableLaunch",
                     np.where(quick_fail, "QuickFailure", "ChaoticChop"))
    df["label"] = label
    df["is_tradable"] = tradable.astype(int)
    df["is_quickfail"] = quick_fail.astype(int)
    df["survives10"] = survives10.astype(int)
    df["survives4"] = (npost >= 4).astype(int)
    
    bar1_confirmed = np.where(d == 1, C_all[:, 1] > O_all[:, 1], C_all[:, 1] < O_all[:, 1])
    df["bar1_confirmed"] = (bar1_confirmed & (npost >= 1)).astype(int)

    # Feature Block B
    df["early_mfe_expansion"] = mfe3
    df["early_mae_peak"] = mae3
    df["early_health_ratio"] = mfe3 / np.maximum(mae3, 0.1)
    
    ext_all = np.where(d[:, None] == 1, H_all, -L_all)
    running_max = np.maximum.accumulate(np.nan_to_num(ext_all[:, :3], nan=-1e18), axis=1)
    is_new_ext1 = (ext_all[:, 1] > ext_all[:, 0]) & ~np.isnan(ext_all[:, 1]) & ~np.isnan(ext_all[:, 0])
    is_new_ext2 = (ext_all[:, 2] > running_max[:, 1]) & ~np.isnan(ext_all[:, 2])
    is_new_ext3 = (ext_all[:, 3] > running_max[:, 2]) & ~np.isnan(ext_all[:, 3])
    df["progress_count_3"] = (is_new_ext1.astype(int) + is_new_ext2.astype(int) + is_new_ext3.astype(int))
    
    bar_dir_3 = np.where(d[:, None] == 1, C_all[:, 1:4] > O_all[:, 1:4], C_all[:, 1:4] < O_all[:, 1:4])
    df["close_progression_ratio"] = np.nansum(bar_dir_3 & ~np.isnan(C_all[:, 1:4]), axis=1) / 3.0
    
    p3_c = C_all[:, 3]
    close_excursion_3 = np.where(d == 1, p3_c - fo, fo - p3_c) / atr
    df["current_pullback_from_peak"] = mfe3 - close_excursion_3
    
    return df


def get_trade_pnl_stop(row, entry_bar):
    d_val = row["direction"]
    atr_val = row["atr_base"]
    n_post_val = int(row["n_post"])
    
    post_o = list(row["post_o"])
    post_h = list(row["post_h"])
    post_l = list(row["post_l"])
    post_c = list(row["post_c"])
    
    entry = post_o[entry_bar - 1]
    entry_fill = entry + d_val * ENTRY_SLIP
    stop = entry_fill - d_val * 1.0 * atr_val
    
    exit_px = None
    for i in range(entry_bar, n_post_val + 1):
        bh, bl, bc = post_h[i - 1], post_l[i - 1], post_c[i - 1]
        if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
            exit_px = stop - d_val * EXIT_SLIP
            break
    if exit_px is None:
        exit_px = post_c[-1] - d_val * EXIT_SLIP
        
    return (exit_px - entry_fill) * d_val * MULT - COMM


def get_trade_pnl_no_stop(row, entry_bar):
    d_val = row["direction"]
    n_post_val = int(row["n_post"])
    
    post_o = list(row["post_o"])
    post_c = list(row["post_c"])
    
    entry = post_o[entry_bar - 1]
    entry_fill = entry + d_val * ENTRY_SLIP
    
    exit_px = post_c[-1] - d_val * EXIT_SLIP
    return (exit_px - entry_fill) * d_val * MULT - COMM


def main():
    if not CAPSULE_FILE.exists():
        print(f"Error: {CAPSULE_FILE} does not exist.")
        return
        
    df = pd.read_parquet(CAPSULE_FILE)
    df = compute_labels_features(df)
    
    # Replicate variables
    d = df["direction"].values.astype(float)
    atr = df["atr_base"].values.astype(float)
    npost = df["n_post"].values.astype(int)
    mfe1_cum = df["mfe10"] # Wait, let's recalculate mfe1_cum
    
    # Pad post-flip lists to get mfe1_cum
    post_h_list = df["post_h"].tolist()
    post_l_list = df["post_l"].tolist()
    fo = df["flip_o"].values.astype(float)
    fh = df["flip_h"].values.astype(float)
    fl = df["flip_l"].values.astype(float)
    fc = df["flip_c"].values.astype(float)
    max_post = max(npost) if len(npost) > 0 else 0
    num_cols = max(21, max_post + 1)
    N = len(df)
    H_all = np.full((N, num_cols), np.nan, dtype=np.float64)
    L_all = np.full((N, num_cols), np.nan, dtype=np.float64)
    H_all[:, 0] = fh
    L_all[:, 0] = fl
    for idx in range(N):
        n = npost[idx]
        if n > 0:
            H_all[idx, 1:n+1] = post_h_list[idx]
            L_all[idx, 1:n+1] = post_l_list[idx]
            
    fav = np.where(d[:, None] == 1, H_all - fo[:, None], fo[:, None] - L_all)
    adv = np.where(d[:, None] == 1, fo[:, None] - L_all, H_all - fo[:, None])
    mfe1_cum = np.maximum(np.nanmax(fav[:, :2], axis=1) / atr, 0.0)
    mae1_cum = np.maximum(np.nanmax(adv[:, :2], axis=1) / atr, 0.0)
    viol_1 = np.where(d[:, None] == 1, L_all[:, 1:2] < fo[:, None], H_all[:, 1:2] > fo[:, None])
    flip_open_violation_1 = np.nansum(viol_1, axis=1) > 0

    # Filter to OOS (2025-2026)
    oos_mask = df["year"].isin([2025, 2026])
    idx_oos = np.where(oos_mask)[0]
    npost_oos = npost[idx_oos]
    is_tradable_oos = df["is_tradable"].values[idx_oos]
    mfe1_cum_oos = mfe1_cum[idx_oos]
    mae1_cum_oos = mae1_cum[idx_oos]
    flip_open_violation_1_oos = flip_open_violation_1[idx_oos]
    bar1_confirmed_oos = df["bar1_confirmed"].values[idx_oos]

    # Post-flip Bar 3 excursions for Version B
    mfe3_cum = np.maximum(np.nanmax(fav[:, :4], axis=1) / atr, 0.0)
    mae3_cum = np.maximum(np.nanmax(adv[:, :4], axis=1) / atr, 0.0)
    viol_b = np.where(d[:, None] == 1, L_all[:, 1:4] < fo[:, None], H_all[:, 1:4] > fo[:, None])
    flip_open_violation_b = np.nansum(viol_b, axis=1) > 0
    progress_count_3 = df["progress_count_3"].values
    close_progression_ratio = df["close_progression_ratio"].values
    early_health_ratio = df["early_health_ratio"].values

    # Causal Version B mask (enters at open of Bar 4)
    verB_mask = (oos_mask & (npost >= 3) & (mfe3_cum >= 0.75) & (mae3_cum <= 0.50) &
                 (early_health_ratio >= 2.0) & (~flip_open_violation_b) &
                 (progress_count_3 >= 2) & (close_progression_ratio >= 0.67))

    # --- PART 1: BAR 2 ENTRIES ---
    print("=== BAR 2 ENTRY FILTERS (OOS 2025-2026) ===")
    
    bar2_filters = [
        ("Filter 1: Simple Survival (n_post >= 2)", 
         npost_oos >= 2),
        ("Filter 2: Bar 1 Confirmation", 
         (npost_oos >= 2) & (bar1_confirmed_oos == 1)),
        ("Filter 5: Strict Bar 2 Health", 
         (npost_oos >= 2) & (mfe1_cum_oos >= 0.75) & (mae1_cum_oos <= 0.25) & (~flip_open_violation_1_oos))
    ]
    
    for fname, mask in bar2_filters:
        bad_mask = mask & (is_tradable_oos == 0)
        sub_df = df.iloc[idx_oos[bad_mask]]
        total_bad = len(sub_df)
        if total_bad == 0:
            continue
            
        # 1.0 ATR stop
        pnls_stop = [get_trade_pnl_stop(row, 2) for _, row in sub_df.iterrows()]
        p_arr_stop = np.array(pnls_stop)
        
        # No stop
        pnls_nostop = [get_trade_pnl_no_stop(row, 2) for _, row in sub_df.iterrows()]
        p_arr_nostop = np.array(pnls_nostop)
        
        print(f"\n{fname} ({total_bad:,} bad entries):")
        print(f"  With 1.0 ATR Stop: Net PnL: ${p_arr_stop.sum():+,.0f} | Avg: ${p_arr_stop.mean():+.2f} per trade")
        print(f"  With NO Stop-Loss: Net PnL: ${p_arr_nostop.sum():+,.0f} | Avg: ${p_arr_nostop.mean():+.2f} per trade")

    # --- PART 2: BAR 4 ENTRY (VERSION B) ---
    print("\n=== BAR 4 ENTRY FILTER (VERSION B) (OOS 2025-2026) ===")
    sub_df_b = df[verB_mask & (df["is_tradable"] == 0)]
    total_bad_b = len(sub_df_b)
    
    if total_bad_b > 0:
        pnls_stop_b = [get_trade_pnl_stop(row, 4) for _, row in sub_df_b.iterrows()]
        p_arr_stop_b = np.array(pnls_stop_b)
        
        pnls_nostop_b = [get_trade_pnl_no_stop(row, 4) for _, row in sub_df_b.iterrows()]
        p_arr_nostop_b = np.array(pnls_nostop_b)
        
        print(f"Version B Filter ({total_bad_b:,} bad entries):")
        print(f"  With 1.0 ATR Stop: Net PnL: ${p_arr_stop_b.sum():+,.0f} | Avg: ${p_arr_stop_b.mean():+.2f} per trade")
        print(f"  With NO Stop-Loss: Net PnL: ${p_arr_nostop_b.sum():+,.0f} | Avg: ${p_arr_nostop_b.mean():+.2f} per trade")


if __name__ == "__main__":
    main()

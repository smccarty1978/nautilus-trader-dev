"""Evaluate moving trade entry up to the open of Bar 5 or Bar 6.

We test:
1. Entry at Bar 5 Open (requires n_post >= 5)
   - Filter A: Simple Survival (n_post >= 5)
   - Filter B: Causal Bar 5 Health Check (MFE4 >= 1.0, MAE4 <= 0.5, No Flip-Open Violation in bars 1-4)
2. Entry at Bar 6 Open (requires n_post >= 6)
   - Filter A: Simple Survival (n_post >= 6)
   - Filter B: Causal Bar 6 Health Check (MFE5 >= 1.25, MAE5 <= 0.5, No Flip-Open Violation in bars 1-5)
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
    
    bar_dir = np.where(d[:, None] == 1, C_all[:, 1:11] > O_all[:, 1:11], C_all[:, 1:11] < O_all[:, 1:11])
    prog10 = np.nansum(bar_dir & ~np.isnan(C_all[:, 1:11]), axis=1)
    progression_gate = prog10 >= 6

    tradable = (survives10 & magnitude_gate & lifetime_ratio & early_risk_defense & high_closer & (~flip_open_violation) & progression_gate)
    df["is_tradable"] = tradable.astype(int)
    
    return df


def main():
    if not CAPSULE_FILE.exists():
        print(f"Error: {CAPSULE_FILE} does not exist.")
        return
        
    df = pd.read_parquet(CAPSULE_FILE)
    df = compute_labels_features(df)
    
    # Replicate variables
    d = df["direction"].values.astype(float)
    atr = df["atr_base"].values.astype(float)
    fo = df["flip_o"].values.astype(float)
    fh = df["flip_h"].values.astype(float)
    fl = df["flip_l"].values.astype(float)
    fc = df["flip_c"].values.astype(float)
    npost = df["n_post"].values.astype(int)

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

    # Excursions
    fav = np.where(d[:, None] == 1, H_all - fo[:, None], fo[:, None] - L_all)
    adv = np.where(d[:, None] == 1, fo[:, None] - L_all, H_all - fo[:, None])

    # Bar 4 Excursions
    mfe4_cum = np.maximum(np.nanmax(fav[:, :5], axis=1) / atr, 0.0)
    mae4_cum = np.maximum(np.nanmax(adv[:, :5], axis=1) / atr, 0.0)
    viol_4 = np.where(d[:, None] == 1, L_all[:, 1:5] < fo[:, None], H_all[:, 1:5] > fo[:, None])
    flip_open_violation_4 = np.nansum(viol_4, axis=1) > 0

    # Bar 5 Excursions
    mfe5_cum = np.maximum(np.nanmax(fav[:, :6], axis=1) / atr, 0.0)
    mae5_cum = np.maximum(np.nanmax(adv[:, :6], axis=1) / atr, 0.0)
    viol_5 = np.where(d[:, None] == 1, L_all[:, 1:6] < fo[:, None], H_all[:, 1:6] > fo[:, None])
    flip_open_violation_5 = np.nansum(viol_5, axis=1) > 0

    # Filter to OOS (2025-2026)
    oos_mask = df["year"].isin([2025, 2026])
    
    total_potl = int(df["is_tradable"].values[oos_mask].sum())
    
    # Reference baseline bad entries (from earlier entry points)
    # Bar 2 entry (n_post >= 2) has:
    bad_bar2 = int((oos_mask & (npost >= 2) & (df["is_tradable"] == 0)).sum())
    # Bar 4 entry (n_post >= 4) has:
    bad_bar4 = int((oos_mask & (npost >= 4) & (df["is_tradable"] == 0)).sum())

    print(f"OOS 2025-2026 Reference:")
    print(f"  POTL Target:                     {total_potl:,}")
    print(f"  Bar 2 Entry Bad Trades Baseline: {bad_bar2:,}")
    print(f"  Bar 4 Entry Bad Trades Baseline: {bad_bar4:,}")

    # Helper function to trade
    def get_trade_pnl(row, entry_bar, exit_m):
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
        last_bar = min(n_post_val, 10) if exit_m == 1 else n_post_val
        
        for i in range(entry_bar, last_bar + 1):
            bh, bl, bc = post_h[i - 1], post_l[i - 1], post_c[i - 1]
            if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                exit_px = stop - d_val * EXIT_SLIP
                break
            if exit_m == 1 and i == 10:
                exit_px = bc - d_val * EXIT_SLIP
                break
        if exit_px is None:
            exit_px = post_c[last_bar - 1] - d_val * EXIT_SLIP
            
        return (exit_px - entry_fill) * d_val * MULT - COMM

    # --- PART 1: BAR 5 ENTRY ---
    print("\n=== BAR 5 ENTRY (OOS 2025-2026) ===")
    
    # Filter 5A: Simple Survival
    mask_5a = oos_mask & (npost >= 5)
    bad_5a = int((mask_5a & (df["is_tradable"] == 0)).sum())
    potl_5a = int((mask_5a & (df["is_tradable"] == 1)).sum())
    avoid_2_5a = bad_bar2 - bad_5a
    avoid_4_5a = bad_bar4 - bad_5a
    
    # Filter 5B: Causal Health Check
    mask_5b = oos_mask & (npost >= 5) & (mfe4_cum >= 1.0) & (mae4_cum <= 0.5) & (~flip_open_violation_4)
    bad_5b = int((mask_5b & (df["is_tradable"] == 0)).sum())
    potl_5b = int((mask_5b & (df["is_tradable"] == 1)).sum())
    avoid_2_5b = bad_bar2 - bad_5b
    avoid_4_5b = bad_bar4 - bad_5b

    for name, mask, bad, potl, av2, av4 in [
        ("Survival-Only (n_post >= 5)", mask_5a, bad_5a, potl_5a, avoid_2_5a, avoid_4_5a),
        ("Causal Health Filter", mask_5b, bad_5b, potl_5b, avoid_2_5b, avoid_4_5b)
    ]:
        print(f"\n  Policy: {name}")
        print(f"    POTL Captured:         {potl:,} / {total_potl:,} ({potl/total_potl*100:.1f}%)")
        print(f"    Bad Trades entered:    {bad:,} (FPR: {bad/(bad+potl)*100:.1f}%)")
        print(f"    Bad Trades AVOIDED vs:")
        print(f"      Bar 2 Open entry:    {av2:,} ({av2/bad_bar2*100:.1f}% reduction)")
        print(f"      Bar 4 Open entry:    {av4:,} ({av4/bad_bar4*100:.1f}% reduction)")
        
        # Sim trading
        for exit_m in (1, 2):
            exit_name = "Tactical-Bar10" if exit_m == 1 else "Macro-OppFlip"
            sub_df = df[mask]
            pnls = [get_trade_pnl(row, 5, exit_m) for _, row in sub_df.iterrows()]
            p_arr = np.array(pnls)
            net_profit = p_arr.sum()
            avg_profit = p_arr.mean() if len(p_arr) > 0 else 0
            win_rate = (p_arr > 0).mean() * 100 if len(p_arr) > 0 else 0
            pf = p_arr[p_arr > 0].sum() / (-p_arr[p_arr < 0].sum()) if (p_arr < 0).any() else np.inf
            print(f"      Exit {exit_name:15}: Win%: {win_rate:.1f}% | PF: {pf:.2f} | Net: ${net_profit:+,.0f} | Avg: ${avg_profit:+.2f}")

    # --- PART 2: BAR 6 ENTRY ---
    print("\n=== BAR 6 ENTRY (OOS 2025-2026) ===")
    
    # Filter 6A: Simple Survival
    mask_6a = oos_mask & (npost >= 6)
    bad_6a = int((mask_6a & (df["is_tradable"] == 0)).sum())
    potl_6a = int((mask_6a & (df["is_tradable"] == 1)).sum())
    avoid_2_6a = bad_bar2 - bad_6a
    avoid_4_6a = bad_bar4 - bad_6a
    
    # Filter 6B: Causal Health Check
    mask_6b = oos_mask & (npost >= 6) & (mfe5_cum >= 1.25) & (mae5_cum <= 0.5) & (~flip_open_violation_5)
    bad_6b = int((mask_6b & (df["is_tradable"] == 0)).sum())
    potl_6b = int((mask_6b & (df["is_tradable"] == 1)).sum())
    avoid_2_6b = bad_bar2 - bad_6b
    avoid_4_6b = bad_bar4 - bad_6b

    for name, mask, bad, potl, av2, av4 in [
        ("Survival-Only (n_post >= 6)", mask_6a, bad_6a, potl_6a, avoid_2_6a, avoid_4_6a),
        ("Causal Health Filter", mask_6b, bad_6b, potl_6b, avoid_2_6b, avoid_4_6b)
    ]:
        print(f"\n  Policy: {name}")
        print(f"    POTL Captured:         {potl:,} / {total_potl:,} ({potl/total_potl*100:.1f}%)")
        print(f"    Bad Trades entered:    {bad:,} (FPR: {bad/(bad+potl)*100:.1f}%)")
        print(f"    Bad Trades AVOIDED vs:")
        print(f"      Bar 2 Open entry:    {av2:,} ({av2/bad_bar2*100:.1f}% reduction)")
        print(f"      Bar 4 Open entry:    {av4:,} ({av4/bad_bar4*100:.1f}% reduction)")
        
        # Sim trading
        for exit_m in (1, 2):
            exit_name = "Tactical-Bar10" if exit_m == 1 else "Macro-OppFlip"
            sub_df = df[mask]
            pnls = [get_trade_pnl(row, 6, exit_m) for _, row in sub_df.iterrows()]
            p_arr = np.array(pnls)
            net_profit = p_arr.sum()
            avg_profit = p_arr.mean() if len(p_arr) > 0 else 0
            win_rate = (p_arr > 0).mean() * 100 if len(p_arr) > 0 else 0
            pf = p_arr[p_arr > 0].sum() / (-p_arr[p_arr < 0].sum()) if (p_arr < 0).any() else np.inf
            print(f"      Exit {exit_name:15}: Win%: {win_rate:.1f}% | PF: {pf:.2f} | Net: ${net_profit:+,.0f} | Avg: ${avg_profit:+.2f}")


if __name__ == "__main__":
    main()

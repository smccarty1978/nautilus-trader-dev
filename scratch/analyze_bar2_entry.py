"""Evaluate moving trade entry up to the open of Bar 2.

We test three filters at the open of Bar 2 (after Bar 1 closes):
1. Simple Survival: regime simply survives to Bar 2 Open (n_post >= 2).
2. Bar 1 Confirmation: n_post >= 2 and Bar 1 closes in the trend direction.
3. Strict Bar 2 Health Filter:
   - n_post >= 2
   - Cumulative MFE through Bar 1 >= 0.50 ATR
   - Cumulative MAE through Bar 1 <= 0.25 ATR
   - Flip Open violation is 0.
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


def main():
    if not CAPSULE_FILE.exists():
        print(f"Error: {CAPSULE_FILE} does not exist.")
        return
        
    df = pd.read_parquet(CAPSULE_FILE)
    
    # Replicate labels/features
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

    mfe10, mae10 = np.maximum(np.nanmax(fav[:, :11], axis=1) / atr, 0.0), np.maximum(np.nanmax(adv[:, :11], axis=1) / atr, 0.0)
    mae5 = np.maximum(np.nanmax(adv[:, :6], axis=1) / atr, 0.0)

    survives10 = npost >= 10
    magnitude_gate = mfe10 >= 1.5
    lifetime_ratio = mfe10 / np.maximum(mae10, 0.1) >= 2.0
    early_risk_defense = mae10 <= mae5 + 0.10
    
    p10_c = C_all[:, 10]
    close_excursion_10 = np.where(d == 1, p10_c - fo, fo - p10_c) / atr
    high_closer = close_excursion_10 >= mfe10 - 0.25
    
    viol = np.where(d[:, None] == 1, L_all[:, 1:6] < fo[:, None], H_all[:, 1:6] > fo[:, None])
    flip_open_violation = np.nansum(viol, axis=1) > 0
    
    bar_dir = np.where(d[:, None] == 1, C_all[:, 1:11] > O_all[:, 1:11], C_all[:, 1:11] < O_all[:, 1:11])
    prog10 = np.nansum(bar_dir & ~np.isnan(C_all[:, 1:11]), axis=1)
    progression_gate = prog10 >= 6

    tradable = (survives10 & magnitude_gate & lifetime_ratio & early_risk_defense & high_closer & (~flip_open_violation) & progression_gate)
    df["is_tradable"] = tradable.astype(int)

    # Excursions through Bar 1 (indices 0 and 1, representing Flip Bar and post-flip Bar 1)
    mfe1_cum = np.maximum(np.nanmax(fav[:, :2], axis=1) / atr, 0.0)
    mae1_cum = np.maximum(np.nanmax(adv[:, :2], axis=1) / atr, 0.0)
    
    # Violation of flip open at Bar 1
    viol_1 = np.where(d[:, None] == 1, L_all[:, 1:2] < fo[:, None], H_all[:, 1:2] > fo[:, None])
    flip_open_violation_1 = np.nansum(viol_1, axis=1) > 0

    # Bar 1 closed in direction of trend
    bar1_confirmed = np.where(d == 1, C_all[:, 1] > O_all[:, 1], C_all[:, 1] < O_all[:, 1])
    df["bar1_confirmed"] = (bar1_confirmed & (npost >= 1)).astype(int)

    # Filter to OOS (2025-2026)
    oos_mask = df["year"].isin([2025, 2026])
    sub_oos = df[oos_mask].copy()
    
    total_oos_flips = len(sub_oos)
    total_potl = int(sub_oos["is_tradable"].sum())
    
    print(f"OOS Year 2025-2026 General Stats:")
    print(f"  Total Regime Flips:              {total_oos_flips:,}")
    print(f"  Total Pure Orderly Launches:     {total_potl:,}")
    
    # Define OOS slices
    idx_oos = np.where(oos_mask)[0]
    npost_oos = npost[idx_oos]
    is_tradable_oos = df["is_tradable"].values[idx_oos]
    mfe1_cum_oos = mfe1_cum[idx_oos]
    mae1_cum_oos = mae1_cum[idx_oos]
    flip_open_violation_1_oos = flip_open_violation_1[idx_oos]
    bar1_confirmed_oos = df["bar1_confirmed"].values[idx_oos]

    # Filters to test (all requiring survival to open of Bar 2: n_post >= 2)
    filters = [
        ("Filter 1: Simple Survival to Bar 2 (n_post >= 2)", 
         npost_oos >= 2),
         
        ("Filter 2: Bar 1 Trend Confirmation (n_post >= 2 & Bar 1 Confirmed)", 
         (npost_oos >= 2) & (bar1_confirmed_oos == 1)),
         
        ("Filter 3: Mild Bar 2 Health (MFE1 >= 0.25, MAE1 <= 0.25, No Violation)", 
         (npost_oos >= 2) & (mfe1_cum_oos >= 0.25) & (mae1_cum_oos <= 0.25) & (~flip_open_violation_1_oos)),
         
        ("Filter 4: Medium Bar 2 Health (MFE1 >= 0.50, MAE1 <= 0.25, No Violation)", 
         (npost_oos >= 2) & (mfe1_cum_oos >= 0.50) & (mae1_cum_oos <= 0.25) & (~flip_open_violation_1_oos)),
         
        ("Filter 5: Strict Bar 2 Health (MFE1 >= 0.75, MAE1 <= 0.25, No Violation)", 
         (npost_oos >= 2) & (mfe1_cum_oos >= 0.75) & (mae1_cum_oos <= 0.25) & (~flip_open_violation_1_oos))
    ]

    print("\n--- Bar 2 Entry Filter Results ---")
    for fname, mask in filters:
        selected_count = int(mask.sum())
        potl_captured = int((mask & (is_tradable_oos == 1)).sum())
        bad_trades = selected_count - potl_captured
        capture_pct = (potl_captured / total_potl) * 100
        false_positive_pct = (bad_trades / selected_count * 100) if selected_count > 0 else 0
        
        print(f"\n{fname}:")
        print(f"  Trades Entered:        {selected_count:,}")
        print(f"  POTL Captured:         {potl_captured:,} / {total_potl:,} ({capture_pct:.1f}%)")
        print(f"  Bad Trades (Non-POTL): {bad_trades:,} ({false_positive_pct:.1f}% False Positive Rate)")
        
        # Sim trading for these selected trades
        # (Entry at open of Bar 2, 1.0 ATR stop, Tactical-Bar10 vs Macro-OppFlip exit)
        for exit_m in (1, 2):
            exit_name = "Tactical-Bar10" if exit_m == 1 else "Macro-OppFlip"
            pnls = []
            
            # Select sub DataFrame
            sub_mask_indices = idx_oos[mask]
            sub_df = df.iloc[sub_mask_indices]
            
            for _, r in sub_df.iterrows():
                # Entry at Bar 2 Open
                d_val = r["direction"]
                atr_val = r["atr_base"]
                n_post_val = int(r["n_post"])
                
                post_o = list(r["post_o"])
                post_h = list(r["post_h"])
                post_l = list(r["post_l"])
                post_c = list(r["post_c"])
                
                entry = post_o[1]  # open of Bar 2
                entry_fill = entry + d_val * ENTRY_SLIP
                stop = entry_fill - d_val * 1.0 * atr_val
                
                exit_px = None
                last_bar = min(n_post_val, 10) if exit_m == 1 else n_post_val
                
                for i in range(2, last_bar + 1):
                    bh, bl, bc = post_h[i - 1], post_l[i - 1], post_c[i - 1]
                    
                    if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                        exit_px = stop - d_val * EXIT_SLIP
                        break
                    
                    if exit_m == 1 and i == 10:
                        exit_px = bc - d_val * EXIT_SLIP
                        break
                        
                if exit_px is None:
                    bc = post_c[last_bar - 1]
                    exit_px = bc - d_val * EXIT_SLIP
                    
                pnl = (exit_px - entry_fill) * d_val * MULT - COMM
                pnls.append(pnl)
                
            p_arr = np.array(pnls)
            net_profit = p_arr.sum()
            avg_profit = p_arr.mean() if len(p_arr) > 0 else 0
            win_rate = (p_arr > 0).mean() * 100 if len(p_arr) > 0 else 0
            pf = p_arr[p_arr > 0].sum() / (-p_arr[p_arr < 0].sum()) if (p_arr < 0).any() else np.inf
            
            print(f"    Exit {exit_name:15}: Win%: {win_rate:.1f}% | PF: {pf:.2f} | Net: ${net_profit:+,.0f} | Avg: ${avg_profit:+.2f}")


if __name__ == "__main__":
    main()

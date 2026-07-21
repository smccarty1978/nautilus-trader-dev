"""Analyze the 1,228 OOS Pure Orderly Launches.

Calculates:
1. MFE/MAE distributions at Bar 4
2. MFE/MAE distributions at Bar 10
3. MFE/MAE distributions post-Bar 10
4. Survival rates under 4 stop-loss variants (Flip-bar, 0.5 ATR, 0.75 ATR, 1.0 ATR)
5. Average profit/loss when entered at:
   - Flip bar close (open of Bar 1)
   - Bar +1 open (open of Bar 1)
   - Bar +4 open (open of Bar 4)
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
    
    # We must replicate the label calculations to get is_tradable
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

    # Label 1 metrics
    mfe10 = np.maximum(np.nanmax(fav[:, :11], axis=1) / atr, 0.0)
    mae10 = np.maximum(np.nanmax(adv[:, :11], axis=1) / atr, 0.0)
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

    # Filter to OOS Pure Orderly Launches
    oos_mask = (df["year"].isin([2025, 2026])) & (df["is_tradable"] == 1)
    sub = df[oos_mask].copy()
    print(f"Isolated OOS Pure Orderly Launches: {len(sub):,}")
    
    # Extract arrays for the subset
    idx_sub = np.where(oos_mask)[0]
    d_sub = d[idx_sub]
    atr_sub = atr[idx_sub]
    fo_sub = fo[idx_sub]
    fh_sub = fh[idx_sub]
    fl_sub = fl[idx_sub]
    npost_sub = npost[idx_sub]
    
    fav_sub = fav[idx_sub]
    adv_sub = adv[idx_sub]
    
    H_sub = H_all[idx_sub]
    L_sub = L_all[idx_sub]
    C_sub = C_all[idx_sub]
    O_sub = O_all[idx_sub]
    
    # 1. MFE/MAE through Bar 4 (indices 0 to 4)
    # 2. MFE/MAE of Bar 4 itself (index 4)
    mfe4_cum = np.maximum(np.nanmax(fav_sub[:, :5], axis=1) / atr_sub, 0.0)
    mae4_cum = np.maximum(np.nanmax(adv_sub[:, :5], axis=1) / atr_sub, 0.0)
    
    mfe4_ind = np.maximum(fav_sub[:, 4] / atr_sub, 0.0)
    mae4_ind = np.maximum(adv_sub[:, 4] / atr_sub, 0.0)

    # 3. MFE/MAE through Bar 10 (indices 0 to 10)
    # 4. MFE/MAE of Bar 10 itself (index 10)
    mfe10_cum = np.maximum(np.nanmax(fav_sub[:, :11], axis=1) / atr_sub, 0.0)
    mae10_cum = np.maximum(np.nanmax(adv_sub[:, :11], axis=1) / atr_sub, 0.0)
    
    mfe10_ind = np.maximum(fav_sub[:, 10] / atr_sub, 0.0)
    mae10_ind = np.maximum(adv_sub[:, 10] / atr_sub, 0.0)

    # 5. MFE after Bar 10 (indices 11 to the end)
    # 6. MAE after Bar 10 (indices 11 to the end)
    surv10_mask_sub = npost_sub > 10
    post_10_mfe = np.full(len(sub), np.nan)
    post_10_mae = np.full(len(sub), np.nan)
    
    if surv10_mask_sub.any():
        post_10_mfe[surv10_mask_sub] = np.nanmax(fav_sub[surv10_mask_sub, 11:], axis=1) / atr_sub[surv10_mask_sub]
        post_10_mae[surv10_mask_sub] = np.nanmax(adv_sub[surv10_mask_sub, 11:], axis=1) / atr_sub[surv10_mask_sub]

    # Function to print distribution percentiles
    def get_dist(arr):
        arr_clean = arr[~np.isnan(arr)]
        if len(arr_clean) == 0:
            return "No data"
        p = np.percentile(arr_clean, [10, 25, 50, 75, 90])
        return f"Mean: {arr_clean.mean():.2f} | 10%: {p[0]:.2f} | 25%: {p[1]:.2f} | 50% (Med): {p[2]:.2f} | 75%: {p[3]:.2f} | 90%: {p[4]:.2f}"

    print("\n--- Excursion Distributions ---")
    print("1. Cumulative MFE at Bar 4:", get_dist(mfe4_cum))
    print("   Individual Bar 4 MFE:     ", get_dist(mfe4_ind))
    print("2. Cumulative MAE at Bar 4:", get_dist(mae4_cum))
    print("   Individual Bar 4 MAE:     ", get_dist(mae4_ind))
    print("3. Cumulative MFE at Bar 10:", get_dist(mfe10_cum))
    print("   Individual Bar 10 MFE:    ", get_dist(mfe10_ind))
    print("4. Cumulative MAE at Bar 10:", get_dist(mae10_cum))
    print("   Individual Bar 10 MAE:    ", get_dist(mae10_ind))
    print("5. MFE after Bar 10 (survivors only):", get_dist(post_10_mfe))
    print("6. MAE after Bar 10 (survivors only):", get_dist(post_10_mae))

    # 7. Survival rates under 4 stop-loss variants
    # Entered at Bar 1 Open, evaluated over:
    # (a) Tactical Exit (up to Bar 10)
    # (b) Macro Exit (entire regime)
    print("\n--- Stop Survival Rates (Entered at Bar 1 Open) ---")
    stops = ["Flip-bar stop", "0.5 ATR stop", "0.75 ATR stop", "1.0 ATR stop"]
    
    for stop_variant in (1, 2, 3, 4):
        # 4 corresponds to 0.75 ATR
        stop_name = stops[stop_variant - 1]
        
        # Simulate tactical exit
        tact_surv = 0
        macro_surv = 0
        
        for idx in range(len(sub)):
            d_val = d_sub[idx]
            atr_val = atr_sub[idx]
            n_post_val = npost_sub[idx]
            
            post_o = post_o_list[idx_sub[idx]]
            post_h = post_h_list[idx_sub[idx]]
            post_l = post_l_list[idx_sub[idx]]
            
            entry = post_o[0]
            entry_fill = entry + d_val * ENTRY_SLIP
            
            if stop_variant == 1:
                stop = (fl_sub[idx] - TICK) if d_val == 1 else (fh_sub[idx] + TICK)
            elif stop_variant == 2:
                stop = entry_fill - d_val * 0.5 * atr_val
            elif stop_variant == 3:
                stop = entry_fill - d_val * 0.75 * atr_val
            else:
                stop = entry_fill - d_val * 1.0 * atr_val
                
            # Check tactical (first 10 bars)
            tact_hit = False
            for i in range(1, min(n_post_val, 10) + 1):
                bh, bl = post_h[i - 1], post_l[i - 1]
                if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                    tact_hit = True
                    break
            if not tact_hit:
                tact_surv += 1
                
            # Check macro (entire regime)
            macro_hit = False
            for i in range(1, n_post_val + 1):
                bh, bl = post_h[i - 1], post_l[i - 1]
                if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                    macro_hit = True
                    break
            if not macro_hit:
                macro_surv += 1
                
        print(f"{stop_name}:")
        print(f"  Tactical Survival: {tact_surv:,} / {len(sub):,} ({tact_surv/len(sub)*100:.1f}%)")
        print(f"  Macro Survival:    {macro_surv:,} / {len(sub):,} ({macro_surv/len(sub)*100:.1f}%)")

    # 8. Profit if entered at:
    # (a) Flip bar close (open of Bar 1)
    # (b) Bar +1 open (open of Bar 1)
    # (c) Bar +4 open (open of Bar 4)
    # Let's test exit variants: Tactical (Bar 10 close) and Macro (opposite flip)
    # We will assume a wide 1.0 ATR stop to allow most trades to play out
    print("\n--- Average Profit per Trade (Assuming 1.0 ATR Stop) ---")
    
    entries = [
        ("Flip Bar Close (Bar 1 Open)", 1),
        ("Bar +1 Open", 1),
        ("Bar +4 Open", 4)
    ]
    
    for entry_name, entry_bar in entries:
        print(f"\nEntry: {entry_name}")
        for exit_m in (1, 2):
            exit_name = "Tactical-Bar10" if exit_m == 1 else "Macro-OppFlip"
            pnls = []
            
            for idx in range(len(sub)):
                r = sub.iloc[idx]
                d_val = r["direction"]
                atr_val = r["atr_base"]
                n_post_val = int(r["n_post"])
                
                # Check if we survive to entry_bar open
                if n_post_val < entry_bar:
                    continue
                    
                post_o = list(r["post_o"])
                post_h = list(r["post_h"])
                post_l = list(r["post_l"])
                post_c = list(r["post_c"])
                
                entry = post_o[entry_bar - 1]
                entry_fill = entry + d_val * ENTRY_SLIP
                
                # Stop is 1.0 ATR
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
                    bc = post_c[last_bar - 1]
                    exit_px = bc - d_val * EXIT_SLIP
                    
                pnl = (exit_px - entry_fill) * d_val * MULT - COMM
                pnls.append(pnl)
                
            p_arr = np.array(pnls)
            net_profit = p_arr.sum()
            avg_profit = p_arr.mean() if len(p_arr) > 0 else 0
            win_rate = (p_arr > 0).mean() * 100 if len(p_arr) > 0 else 0
            pf = p_arr[p_arr > 0].sum() / (-p_arr[p_arr < 0].sum()) if (p_arr < 0).any() else np.inf
            
            print(f"  Exit {exit_name:15}: Trades: {len(p_arr):,} | Win%: {win_rate:.1f}% | PF: {pf:.2f} | Net: ${net_profit:+,.0f} | Avg: ${avg_profit:+.2f}")


if __name__ == "__main__":
    main()

"""Identify and analyze OOS 'fakeout' regimes that look similar through Bar 4.

Criteria for a 'similar path' through Bar 4:
- n_post >= 4 (survives to Bar 4)
- Cumulative MFE through Bar 4 >= 1.5 ATR (strong breakout velocity)
- Cumulative MAE through Bar 4 <= 0.5 ATR (low initial adverse heat)
- is_tradable == 0 (fails the final Label 1 Pure Orderly Launch definition)
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

    # Excursions at Bar 4
    mfe4_cum = np.maximum(np.nanmax(fav[:, :5], axis=1) / atr, 0.0)
    mae4_cum = np.maximum(np.nanmax(adv[:, :5], axis=1) / atr, 0.0)

    # Filter for OOS (2025-2026)
    oos_mask = df["year"].isin([2025, 2026])
    
    # 1. Total launches in OOS surviving to Bar 4
    surv4_oos = oos_mask & (npost >= 4)
    print(f"Total OOS regimes surviving to Bar 4: {surv4_oos.sum():,}")

    # 2. Pure Orderly Launches in OOS (this is the true positive subset)
    potl_oos = oos_mask & (df["is_tradable"] == 1)
    print(f"  True Pure Orderly Launches (POTL): {potl_oos.sum():,}")
    
    # 3. Fakeout criteria: survives to Bar 4, MFE4 >= 1.5, MAE4 <= 0.5, but is NOT POTL
    fakeout_mask = oos_mask & (npost >= 4) & (mfe4_cum >= 1.5) & (mae4_cum <= 0.5) & (df["is_tradable"] == 0)
    sub_fake = df[fakeout_mask].copy()
    print(f"  OOS Fakeout Regimes (POTL-like at Bar 4, but fails later): {len(sub_fake):,}")
    
    if len(sub_fake) == 0:
        print("No fakeout regimes found.")
        return

    # Let's see why they failed (failure modes analysis)
    idx_fake = np.where(fakeout_mask)[0]
    
    # Failure category counts
    fail_flip_early = (npost[idx_fake] < 10).sum()              # Flipped before Bar 10
    
    # For those surviving to Bar 10 (npost >= 10):
    surv10_fake = npost[idx_fake] >= 10
    idx_fake_surv10 = idx_fake[surv10_fake]
    
    fail_magnitude = (mfe10[idx_fake_surv10] < 1.5).sum()       # Magnitude < 1.5 ATR (impossible if MFE4 >= 1.5, but let's check)
    fail_lifetime = (mfe10[idx_fake_surv10] / np.maximum(mae10[idx_fake_surv10], 0.1) < 2.0).sum()  # Lifetime ratio < 2.0
    fail_risk_defense = (mae10[idx_fake_surv10] > mae5[idx_fake_surv10] + 0.10).sum()               # MAE expanded after Bar 5
    fail_high_closer = (close_excursion_10[idx_fake_surv10] < mfe10[idx_fake_surv10] - 0.25).sum() # Spiked and ground down
    
    # Structural flip open violation in bars 1-5
    viol_fake = np.where(d[idx_fake_surv10, None] == 1, L_all[idx_fake_surv10, 1:6] < fo[idx_fake_surv10, None], H_all[idx_fake_surv10, 1:6] > fo[idx_fake_surv10, None])
    fail_structural = (np.nansum(viol_fake, axis=1) > 0).sum()
    
    # Progression count < 6
    bar_dir_fake = np.where(d[idx_fake_surv10, None] == 1, C_all[idx_fake_surv10, 1:11] > O_all[idx_fake_surv10, 1:11], C_all[idx_fake_surv10, 1:11] < O_all[idx_fake_surv10, 1:11])
    prog_fake = np.nansum(bar_dir_fake & ~np.isnan(C_all[idx_fake_surv10, 1:11]), axis=1)
    fail_progression = (prog_fake < 6).sum()

    print("\n--- Failure Modes of Fakeouts ---")
    print(f"1. Flipped before Bar 10 (early flip):          {fail_flip_early:,} ({fail_flip_early/len(sub_fake)*100:.1f}%)")
    print(f"For those that survived to Bar 10 ({surv10_fake.sum():,} regimes):")
    print(f"2. Fails Structural Defense (flip open violated): {fail_structural:,} ({fail_structural/len(sub_fake)*100:.1f}%)")
    print(f"3. Fails Progression Gate (fewer than 6 trend closes): {fail_progression:,} ({fail_progression/len(sub_fake)*100:.1f}%)")
    print(f"4. Fails Lifetime Ratio (MFE/MAE < 2.0):          {fail_lifetime:,} ({fail_lifetime/len(sub_fake)*100:.1f}%)")
    print(f"5. Fails Early Risk Defense (late MAE expansion): {fail_risk_defense:,} ({fail_risk_defense/len(sub_fake)*100:.1f}%)")
    print(f"6. Fails High-Closer Constraint (stalled spike):  {fail_high_closer:,} ({fail_high_closer/len(sub_fake)*100:.1f}%)")
    print(f"7. Fails Magnitude Gate (< 1.5 ATR):              {fail_magnitude:,} ({fail_magnitude/len(sub_fake)*100:.1f}%)")
    
    # Let's check what trading looks like for these fakeout regimes if entered at open of Bar 4
    # (Assuming 1.0 ATR stop, under both Tactical and Macro exits)
    print("\n--- Trading Performance of Fakeouts (Entered at Bar 4 Open, 1.0 ATR Stop) ---")
    
    for exit_m in (1, 2):
        exit_name = "Tactical-Bar10" if exit_m == 1 else "Macro-OppFlip"
        pnls = []
        
        for idx in range(len(sub_fake)):
            r = sub_fake.iloc[idx]
            d_val = r["direction"]
            atr_val = r["atr_base"]
            n_post_val = int(r["n_post"])
            
            post_o = list(r["post_o"])
            post_h = list(r["post_h"])
            post_l = list(r["post_l"])
            post_c = list(r["post_c"])
            
            # Entry at Bar 4 Open (index 3)
            entry = post_o[3]
            entry_fill = entry + d_val * ENTRY_SLIP
            
            # Stop is 1.0 ATR
            stop = entry_fill - d_val * 1.0 * atr_val
            
            exit_px = None
            last_bar = min(n_post_val, 10) if exit_m == 1 else n_post_val
            
            for i in range(4, last_bar + 1):
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

"""Analyze all entry options side-by-side for the NQ 1m Launch study.
Evaluates Bar 2, Bar 4, Bar 5, and Bar 6 entries on OOS 2025-2026 data.
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
    
    # Causal structural violation for Version B at entry (bars 1 to 3)
    viol_b = np.where(d[:, None] == 1, L_all[:, 1:4] < fo[:, None], H_all[:, 1:4] > fo[:, None])
    df["flip_open_violation_b"] = (np.nansum(viol_b, axis=1) > 0).astype(int)
    
    bar_dir = np.where(d[:, None] == 1, C_all[:, 1:11] > O_all[:, 1:11], C_all[:, 1:11] < O_all[:, 1:11])
    prog10 = np.nansum(bar_dir & ~np.isnan(C_all[:, 1:11]), axis=1)
    progression_gate = prog10 >= 6

    tradable = (survives10 & magnitude_gate & lifetime_ratio & early_risk_defense & high_closer & (~flip_open_violation) & progression_gate)
    df["is_tradable"] = tradable.astype(int)
    
    # Baseline 2 components
    bar1_confirmed = np.where(d == 1, C_all[:, 1] > O_all[:, 1], C_all[:, 1] < O_all[:, 1])
    df["bar1_confirmed"] = (bar1_confirmed & (npost >= 2)).astype(int)

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
    
    return df

def sim_trade(row, entry_bar, exit_model):
    d = row["direction"]
    atr = row["atr_base"]
    n_post = int(row["n_post"])
    
    if n_post < entry_bar:
        return None
        
    post_o = list(row["post_o"])
    post_h = list(row["post_h"])
    post_l = list(row["post_l"])
    post_c = list(row["post_c"])
    
    entry = post_o[entry_bar - 1]
    if not np.isfinite(entry):
        return None
        
    entry_fill = entry + d * ENTRY_SLIP
    stop = entry_fill - d * 1.0 * atr  # Stop variant 3
    
    exit_px = None
    last_bar = min(n_post, 10) if exit_model == 1 else n_post
    
    for i in range(entry_bar, last_bar + 1):
        bh, bl, bc = post_h[i - 1], post_l[i - 1], post_c[i - 1]
        
        # Check stop
        if (d == 1 and bl <= stop) or (d == -1 and bh >= stop):
            exit_px = stop - d * EXIT_SLIP
            break
            
        # Exit due to time-stop
        if exit_model == 1 and i == 10:
            exit_px = bc - d * EXIT_SLIP
            break
            
    if exit_px is None:
        bc = post_c[last_bar - 1]
        exit_px = bc - d * EXIT_SLIP
        
    return (exit_px - entry_fill) * d * MULT - COMM

def main():
    if not CAPSULE_FILE.exists():
        print(f"Error: {CAPSULE_FILE} does not exist.")
        return
        
    df = pd.read_parquet(CAPSULE_FILE)
    df = compute_labels_features(df)
    
    # Replicate variables for mask helpers
    d = df["direction"].values.astype(float)
    atr = df["atr_base"].values.astype(float)
    fo = df["flip_o"].values.astype(float)
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

    # OOS Mask
    oos_mask = df["year"].isin([2025, 2026])
    total_potl = int(df["is_tradable"].values[oos_mask].sum())

    # Build masks
    # Bar 2 masks
    mask_b2_surv = oos_mask & (npost >= 2)
    mask_b2_health = oos_mask & (df["bar1_confirmed"] == 1)

    # Bar 4 masks
    mask_b4_surv = oos_mask & (npost >= 4)
    # Version B Causal Health
    mask_b4_health = oos_mask & (npost >= 3) & (df["early_mfe_expansion"] >= 0.75) & (df["early_mae_peak"] <= 0.50) & \
                     (df["early_health_ratio"] >= 2.0) & (df["flip_open_violation_b"] == 0) & \
                     (df["progress_count_3"] >= 2) & (df["close_progression_ratio"] >= 0.67)

    # Bar 5 masks
    mask_b5_surv = oos_mask & (npost >= 5)
    mask_b5_health = oos_mask & (npost >= 5) & (mfe4_cum >= 1.0) & (mae4_cum <= 0.5) & (~flip_open_violation_4)

    # Bar 6 masks
    mask_b6_surv = oos_mask & (npost >= 6)
    mask_b6_health = oos_mask & (npost >= 6) & (mfe5_cum >= 1.25) & (mae5_cum <= 0.5) & (~flip_open_violation_5)

    policies = [
        ("Bar 2 Open", "Survival-Only", 2, mask_b2_surv),
        ("Bar 2 Open", "Causal (Bar 1 Confirm)", 2, mask_b2_health),
        ("Bar 4 Open", "Survival-Only", 4, mask_b4_surv),
        ("Bar 4 Open", "Causal Health Filter", 4, mask_b4_health),
        ("Bar 5 Open", "Survival-Only", 5, mask_b5_surv),
        ("Bar 5 Open", "Causal Health Filter", 5, mask_b5_health),
        ("Bar 6 Open", "Survival-Only", 6, mask_b6_surv),
        ("Bar 6 Open", "Causal Health Filter", 6, mask_b6_health),
    ]

    print("POLICIES EVALUATION (OOS 2025-2026)")
    print("=" * 80)
    
    # Save the base bad trades for comparisons
    # Survival-only Bar 2 has 34,262 bad trades.
    # Survival-only Bar 4 has 29,502 bad trades.
    base_b2_bad = 34262
    base_b4_bad = 29502

    results_data = []

    for entry_name, policy_name, entry_bar, mask in policies:
        # Filter is_tradable
        sub_df = df[mask]
        total_trades = len(sub_df)
        potl = int(sub_df["is_tradable"].sum())
        bad = total_trades - potl
        cap_rate = potl / total_potl * 100 if total_potl > 0 else 0
        fpr = bad / total_trades * 100 if total_trades > 0 else 0
        
        avoid_b2 = base_b2_bad - bad
        avoid_b4 = base_b4_bad - bad
        
        avoid_b2_pct = avoid_b2 / base_b2_bad * 100
        avoid_b4_pct = avoid_b4 / base_b4_bad * 100

        # Sim PnL
        # Exit 1 (Tactical)
        pnls_t10 = []
        # Exit 2 (Macro)
        pnls_opp = []
        
        for _, row in sub_df.iterrows():
            res_t10 = sim_trade(row, entry_bar, exit_model=1)
            res_opp = sim_trade(row, entry_bar, exit_model=2)
            if res_t10 is not None:
                pnls_t10.append(res_t10)
            if res_opp is not None:
                pnls_opp.append(res_opp)

        p_t10 = np.array(pnls_t10)
        p_opp = np.array(pnls_opp)
        
        net_t10 = p_t10.sum() if len(p_t10) > 0 else 0
        avg_t10 = p_t10.mean() if len(p_t10) > 0 else 0
        pf_t10 = p_t10[p_t10 > 0].sum() / (-p_t10[p_t10 < 0].sum()) if (p_t10 < 0).any() else np.inf
        win_t10 = (p_t10 > 0).mean() * 100 if len(p_t10) > 0 else 0

        net_opp = p_opp.sum() if len(p_opp) > 0 else 0
        avg_opp = p_opp.mean() if len(p_opp) > 0 else 0
        pf_opp = p_opp[p_opp > 0].sum() / (-p_opp[p_opp < 0].sum()) if (p_opp < 0).any() else np.inf
        win_opp = (p_opp > 0).mean() * 100 if len(p_opp) > 0 else 0

        print(f"\nEntry: {entry_name} | Policy: {policy_name}")
        print(f"  Total Trades: {total_trades:,}")
        print(f"  POTL Captured: {potl:,} / {total_potl:,} ({cap_rate:.1f}%)")
        print(f"  Bad Trades: {bad:,} (FPR: {fpr:.1f}%)")
        print(f"  Bad Avoided vs B2 Open: {avoid_b2:,} ({avoid_b2_pct:.1f}%)")
        print(f"  Bad Avoided vs B4 Open: {avoid_b4:,} ({avoid_b4_pct:.1f}%)")
        print(f"  Tactical-Bar10 Exit: Net = ${net_t10:+,.0f} | Avg = ${avg_t10:+.2f} | Win% = {win_t10:.1f}% | PF = {pf_t10:.2f}")
        print(f"  Macro-OppFlip Exit:  Net = ${net_opp:+,.0f} | Avg = ${avg_opp:+.2f} | Win% = {win_opp:.1f}% | PF = {pf_opp:.2f}")

        results_data.append({
            "entry": entry_name,
            "policy": policy_name,
            "trades": total_trades,
            "potl": potl,
            "bad": bad,
            "fpr": fpr,
            "avoid_b2": avoid_b2,
            "avoid_b2_pct": avoid_b2_pct,
            "avoid_b4": avoid_b4,
            "avoid_b4_pct": avoid_b4_pct,
            "t10_net": net_t10,
            "t10_avg": avg_t10,
            "t10_pf": pf_t10,
            "t10_win": win_t10,
            "opp_net": net_opp,
            "opp_avg": avg_opp,
            "opp_pf": pf_opp,
            "opp_win": win_opp
        })

    # Save to a summary dataframe or markdown
    res_df = pd.DataFrame(results_data)
    res_df.to_pickle(OUT / "all_entries_results.pkl")

if __name__ == "__main__":
    main()

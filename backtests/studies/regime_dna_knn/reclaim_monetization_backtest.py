"""Reclaim Entry Monetization Backtest (OOS 2025-2026).

Simulates actual trading performance of the pullback-reclaim entry:
1. Entry on first 0.50 ATR pullback-reclaim event after Bar 4 Open.
2. Stops: 0.3, 0.5, 0.75 ATR from entry fill.
3. Targets: +0.5, +1.0, +2.0 ATR, and hold-to-flip.
4. Frictions: $5 RT commission, 0.5-tick entry slippage, 1.0-tick exit slippage.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E  # noqa: E402
import progressive_separability as P  # noqa: E402  (build, feats_through)
from rejection_power import MODEL_B  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")

MULT = 20.0
TICK = 0.25
COMM = 5.0
ENTRY_SLIP = 0.5 * TICK
EXIT_SLIP = 1.0 * TICK
ENTRY_BAR = 4
BMAX = 61

def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df)
    H, L, C, O, V, n = M
    d = df.direction.values.astype(float)
    atr = df.atr_base.values.astype(float)
    yr = df.year.values
    lab = df.label.values

    # Model B features through Bar 3
    XB = P.feats_through(df, M, 3)
    
    # Population: survivors alive at Bar 3 (n_post >= 4)
    alive = n >= ENTRY_BAR
    is_m = alive & (yr < 2025)
    oos_m = alive & (yr >= 2025)
    yQ = (lab == "QuickFailure").astype(int)

    # Train Model B QuickFailure head on IS survivors
    clf = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=31,
                             class_weight="balanced", random_state=0, verbose=-1)
    clf.fit(XB[is_m][MODEL_B].values, yQ[is_m])
    pQ = clf.predict_proba(XB[oos_m][MODEL_B].values)[:, 1]
    health_oos = 1.0 - pQ

    # Restrict to OOS survivor pool
    gi = np.where(oos_m)[0]
    dd = d[gi]
    aa = atr[gi]
    nn = n[gi]
    ll = lab[gi]
    yy = yr[gi]
    Hs, Ls, Cs, Os = H[gi], L[gi], C[gi], O[gi]
    entry_raw = O[gi, ENTRY_BAR]  # Bar 4 open
    fill = entry_raw + dd * ENTRY_SLIP

    # Health groups
    res_df = pd.DataFrame({"health": health_oos})
    q80 = res_df["health"].quantile(0.80)
    top_group_mask = health_oos >= q80

    # We backtest on:
    # 1. Top 20% Health Survivors (to evaluate the high-quality cohort)
    # 2. All OOS Survivors (to see if the edge is robust across all survivors)
    cohorts = [
        ("Top 20% Health survivors", np.where(top_group_mask)[0]),
        ("All OOS survivors", np.arange(len(gi)))
    ]

    STOPS = [0.3, 0.5, 0.75]
    TARGETS = [0.5, 1.0, 2.0, "flip"]

    for cohort_name, idx_pool in cohorts:
        print(f"\nCOHORT: {cohort_name} (Total pool: {len(idx_pool):,})")
        print("=" * 105)
        
        # Identify the reclaim events for this cohort
        reclaim_events = []
        for idx in idx_pool:
            d_val = dd[idx]
            a_val = aa[idx]
            n_val = nn[idx]
            f_val = fill[idx]
            
            # Walk bar-by-bar after Bar 4 open
            # We must use actual high/low prices to track peak and pullback
            last_bar = min(n_val, BMAX)
            
            # Reached +1.0 ATR MFE check (measured from fill)
            reaches_10 = False
            first_10_bar = None
            for j in range(ENTRY_BAR, last_bar + 1):
                hj = Hs[idx, j]
                lj = Ls[idx, j]
                if np.isnan(hj):
                    continue
                mfe_j = (hj - f_val) / a_val if d_val == 1 else (f_val - lj) / a_val
                if mfe_j >= 1.0:
                    reaches_10 = True
                    first_10_bar = j
                    break
                    
            if not reaches_10 or first_10_bar is None:
                continue
                
            # Track running peak MFE and look for 0.50 ATR pullback + recovery
            running_peak_mfe = (Hs[idx, first_10_bar] - f_val) / a_val if d_val == 1 else (f_val - Ls[idx, first_10_bar]) / a_val
            pb_active = False
            pb_start_peak_mfe = None
            pb_hit_bar = None
            recovered = False
            rec_bar = None
            
            for j in range(first_10_bar + 1, last_bar + 1):
                hj = Hs[idx, j]
                lj = Ls[idx, j]
                if np.isnan(hj):
                    continue
                    
                mfe_j = (hj - f_val) / a_val if d_val == 1 else (f_val - lj) / a_val
                pb_mfe_j = (lj - f_val) / a_val if d_val == 1 else (f_val - hj) / a_val
                
                if not pb_active:
                    if running_peak_mfe - pb_mfe_j >= 0.50:
                        pb_active = True
                        pb_start_peak_mfe = running_peak_mfe
                        pb_hit_bar = j
                    else:
                        running_peak_mfe = max(running_peak_mfe, mfe_j)
                else:
                    # Look for recovery back to the pullback start peak
                    if mfe_j >= pb_start_peak_mfe:
                        recovered = True
                        rec_bar = j
                        break
            
            if recovered and rec_bar is not None and pb_start_peak_mfe is not None:
                # Reclaim event found! We enter at the reclaim price (running peak) on rec_bar
                reclaim_px = f_val + d_val * pb_start_peak_mfe * a_val
                reclaim_fill = reclaim_px + d_val * ENTRY_SLIP
                
                reclaim_events.append({
                    "idx": idx,
                    "reclaim_fill": reclaim_fill,
                    "rec_bar": rec_bar,
                    "d_val": d_val,
                    "a_val": a_val,
                    "n_val": n_val,
                    "year": yy[idx]
                })

        print(f"Total pullback-reclaim trades found: {len(reclaim_events):,}")
        print("-" * 105)
        print(f"{'Stop':<6} | {'Target':<6} | {'Trades':<8} | {'Win%':<6} | {'PF':<5} | {'$/trade':<10} | {'Net PnL':<10} | {'2025 Net':<10} | {'2026 Net':<10}")
        print("-" * 105)
        
        # Simulate each stop/target configuration
        for stop_level in STOPS:
            for target_level in TARGETS:
                pnls = []
                years_list = []
                wins = 0
                
                for ev in reclaim_events:
                    rec_fill = ev["reclaim_fill"]
                    d_val = ev["d_val"]
                    a_val = ev["a_val"]
                    n_val = ev["n_val"]
                    r_bar = ev["rec_bar"]
                    
                    sl_px = rec_fill - d_val * stop_level * a_val
                    pt_px = None
                    if target_level != "flip":
                        pt_px = rec_fill + d_val * target_level * a_val
                        
                    trade_pnl = None
                    last_bar = min(n_val, BMAX)
                    
                    # Walk from r_bar onwards (including entry bar)
                    for j in range(r_bar, last_bar + 1):
                        hj = Hs[ev["idx"], j]
                        lj = Ls[ev["idx"], j]
                        cj = Cs[ev["idx"], j]
                        if np.isnan(hj):
                            continue
                            
                        # Check stop
                        sl_hit = (d_val == 1 and lj <= sl_px) or (d_val == -1 and hj >= sl_px)
                        
                        # Check target
                        pt_hit = False
                        if pt_px is not None:
                            pt_hit = (d_val == 1 and hj >= pt_px) or (d_val == -1 and lj <= pt_px)
                            
                        if sl_hit and pt_hit:
                            # Adverse-first on same bar collision
                            trade_pnl = (sl_px - d_val * EXIT_SLIP - rec_fill) * d_val * MULT - COMM
                            break
                        elif sl_hit:
                            trade_pnl = (sl_px - d_val * EXIT_SLIP - rec_fill) * d_val * MULT - COMM
                            break
                        elif pt_hit:
                            # Resting limit fill, no slippage
                            trade_pnl = (pt_px - rec_fill) * d_val * MULT - COMM
                            wins += 1
                            break
                            
                    if trade_pnl is None:
                        # Exited at the opposite flip (close of last bar)
                        cj_flip = Cs[ev["idx"], last_bar]
                        trade_pnl = (cj_flip - d_val * EXIT_SLIP - rec_fill) * d_val * MULT - COMM
                        if trade_pnl > 0:
                            wins += 1
                            
                    pnls.append(trade_pnl)
                    years_list.append(ev["year"])
                    
                p_arr = np.array(pnls)
                y_arr = np.array(years_list)
                n_trades = len(p_arr)
                
                if n_trades > 0:
                    win_pct = (p_arr > 0).mean() * 100
                    pf = p_arr[p_arr > 0].sum() / (-p_arr[p_arr < 0].sum()) if (p_arr < 0).any() else np.inf
                    net = p_arr.sum()
                    n25 = p_arr[y_arr == 2025].sum()
                    n26 = p_arr[y_arr == 2026].sum()
                    avg_pnl = p_arr.mean()
                    
                    target_str = f"+{target_level}" if target_level != "flip" else "flip"
                    print(f"{stop_level:<6.2f} | {target_str:<6} | {n_trades:<8} | {win_pct:<5.1f}% | {pf:<5.2f} | {f'${avg_pnl:+.2f}':<10} | {f'${net:+,.0f}':<10} | {f'${n25:+,.0f}':<10} | {f'${n26:+,.0f}':<10}")
                else:
                    print(f"{stop_level:<6.2f} | {target_level:<6} | 0        | 0.0%   | 0.00  | $0.00      | $0         | $0         | $0")

if __name__ == "__main__":
    main()

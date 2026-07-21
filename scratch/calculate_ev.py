import pandas as pd
import numpy as np

# Load excursion paths
df = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
df_oos = df[df["year"].isin([2023, 2024, 2025, 2026])].copy()

# Filtered cohort: kmeans_4_state == 0
df_filtered = df_oos[df_oos["kmeans_4_state"] == 0].copy()

print(f"Loaded {len(df_oos):,} OOS raw flips (Baseline)")
print(f"Filtered to {len(df_filtered):,} OOS flips in KMeans_4 State 0")

targets = [0.5, 0.75, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0]
stops = [0.5, 0.75, 1.0, 1.2, 1.5]

def evaluate_bracket(data, tf_prefix, tgt, stp):
    mfe = data[f"mfe_{tf_prefix}"].to_numpy()
    mae = data[f"mae_{tf_prefix}"].to_numpy()
    
    # Causal race simulation:
    # 1. If MFE >= tgt and MAE < stp: Win (+tgt)
    # 2. If MAE >= stp and MFE < tgt: Loss (-stp)
    # 3. If both are hit: Conservative assumption is Loss (-stp)
    # 4. If neither is hit: Exited at the end of the window.
    #    Since we don't have the exact price at the end of the window in ATR units in the file,
    #    we can approximate it: if it didn't hit target or stop, it's a neutral/flat exit (0.0).
    #    Let's calculate both: Hard Bracket (where we assume it eventually hits stop if it doesn't hit target)
    #    and Soft Window (where neither hit = 0.0).
    
    wins = (mfe >= tgt) & (mae < stp)
    losses = (mae >= stp) | ((mfe >= tgt) & (mae >= stp)) # conservative: both hit = loss
    flats = ~(wins | losses)
    
    # Soft window EV: wins * tgt - losses * stp + flats * 0.0
    ev_soft = (wins.sum() * tgt - losses.sum() * stp) / len(data)
    
    # Hard bracket EV: assuming a trade must hit either target or stop eventually (wins * tgt - (1 - wins) * stp)
    ev_hard = (wins.sum() * tgt - (len(data) - wins.sum()) * stp) / len(data)
    
    win_rate = wins.sum() / len(data)
    loss_rate = losses.sum() / len(data)
    flat_rate = flats.sum() / len(data)
    
    return win_rate, loss_rate, flat_rate, ev_soft, ev_hard

for tf in ["1m", "5m", "10m"]:
    print(f"\n==============================================================")
    print(f"  TIMEFRAME: {tf} (KMeans_4 State 0 OOS)")
    print(f"==============================================================")
    print(f"  {'PT':<5} {'SL':<5} {'Win%':>8} {'Loss%':>8} {'Flat%':>8} {'EV (Soft)':>10} {'EV (Hard)':>10}")
    print(f"  {'-'*60}")
    
    results = []
    for tgt in targets:
        for stp in stops:
            wr, lr, fr, ev_s, ev_h = evaluate_bracket(df_filtered, tf, tgt, stp)
            results.append((tgt, stp, wr, lr, fr, ev_s, ev_h))
            
    # Sort by EV (Soft) descending to find the best
    results.sort(key=lambda x: -x[3] if x[3] != 0 else 0) # sort by ev_s
    results.sort(key=lambda x: -x[5]) # sort by EV (Soft)
    
    for r in results[:10]:
        print(f"  {r[0]:<5.2f} {r[1]:<5.2f} {r[2]:>7.1%} {r[3]:>7.1%} {r[4]:>7.1%} {r[5]:>+10.3f} {r[6]:>+10.3f}")

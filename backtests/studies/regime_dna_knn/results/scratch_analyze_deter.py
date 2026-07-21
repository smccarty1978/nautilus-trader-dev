"""Temporary scratch script to analyze DETER state dynamics in NQ Regime DNA KNN.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E
import progressive_separability as P
import bar4_knn_path_atlas as A

OUT = Path("studies/regime_dna_knn/results")
NS = 1_000_000_000
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY = 0.5 * TICK; EXIT = 1.0 * TICK
CONT = ("Continuation", "Runner"); DETER_STATES = ("Failure", "Chop")
KNN_K = 500; IS_REF_CAP = 40000
RNG = np.random.default_rng(0)
STATES = ["Healthy", "SoftStall", "HardStall", "DETER"]

def main():
    print("Loading data...")
    A.BARS = list(range(4, 29))
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    entry4 = O[:, 4]; flip_c = df.post_c.apply(lambda x: float(x[-1])).values
    rididx = {r: i for i, r in enumerate(df.regime_id.values)}
    
    print("Building states...")
    S = A.build_states(df, M)
    isS = S[S.year < 2025]; oos = S[S.year >= 2025].reset_index(drop=True)
    
    print("Running per-bar KNN...")
    pNH3 = np.full(len(oos), np.nan); pFL3 = np.full(len(oos), np.nan); predA = np.empty(len(oos), dtype=object)
    for k in sorted(oos.k.unique()):
        isk = isS[isS.k == k]; om = (oos.k == k).values
        if len(isk) < 200 or om.sum() == 0:
            continue
        if len(isk) > IS_REF_CAP:
            isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
        Xis = isk[A.FEATS].values.astype(np.float32); Xoo = oos.loc[om, A.FEATS].values.astype(np.float32)
        mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
        nn = NearestNeighbors(n_neighbors=min(KNN_K, len(isk)), n_jobs=-1).fit((Xis - mu) / sd)
        _, idx = nn.kneighbors((Xoo - mu) / sd)
        nbc = isk.cls.values[idx]; oi = np.where(om)[0]
        pNH3[oi] = isk.newhigh3.values[idx].mean(1); pFL3[oi] = isk.flip3.values[idx].mean(1)
        predA[oi] = [max(Counter(r), key=Counter(r).get) for r in nbc]
        
    oos["pNH3"] = pNH3; oos["pFL3"] = pFL3; oos["pred"] = predA
    oos = oos[oos.pred.notna()].copy().sort_values(["rid", "k"]).reset_index(drop=True)
    oos["hC"] = oos.pNH3 - oos.pFL3
    g = oos.groupby("rid")
    oos["hC_pk"] = g.hC.cummax()
    oos["dd"] = 1 - oos.hC / oos.hC_pk.clip(lower=1e-6)
    
    def classify(row):
        if row.pred in DETER_STATES:
            return "DETER"
        if row.dd >= 0.20:
            return "HardStall"
        if row.dd >= 0.10:
            return "SoftStall"
        return "Healthy"
    oos["state"] = oos.apply(classify, axis=1)
    
    print("\n================================================")
    print("ANALYSIS OF DETER AND REIGNITION DYNAMICS")
    print("================================================\n")
    
    # 1. Reignite rates at different thresholds
    print("1. Reignition Rates at Various Thresholds")
    print("-----------------------------------------")
    print("Reignite = tot_mfe > mfe_sofar + epsilon")
    epsilons = [0.0, 0.05, 0.10, 0.25, 0.50, 1.00]
    
    for eps in epsilons:
        oos[f"reignite_{eps:.2f}"] = (oos.tot_mfe > oos.mfe_sofar + eps).astype(int)
        
    cols = ["state"] + [f"reignite_{eps:.2f}" for eps in epsilons]
    reignite_summary = oos[cols].groupby("state").mean() * 100
    print(reignite_summary.round(1).to_string())
    print()

    # 2. DETER state flip horizons
    print("2. DETER Flip Horizons (Time from DETER bar to flip)")
    print("-----------------------------------------------------")
    deter_rows = oos[oos.state == "DETER"]
    n_deter = len(deter_rows)
    print(f"Total DETER bars in OOS: {n_deter}")
    for h in [1, 3, 5, 10]:
        pct = (deter_rows.rem_bars <= h).mean() * 100
        print(f"  Flip within {h:2d} bars: {pct:.1f}%")
    print()

    # 3. Recovery vs. Direct Flip from DETER
    print("3. State Path from DETER: Recovery vs. Direct Flip")
    print("--------------------------------------------------")
    # For each DETER bar, check what states are visited in the future
    # Let's map each row to its index within the group to look ahead
    oos["group_idx"] = oos.groupby("rid").cumcount()
    
    # Let's construct a list of future states for each row
    rid_groups = oos.groupby("rid")
    recovered_bars = 0
    direct_flip_bars = 0
    
    # To speed up, we can find for each DETER bar if any subsequent bar in the same rid has state in ["Healthy", "SoftStall"]
    # We can do this efficiently using a shift/grouped loop
    future_healths = []
    
    # Group states into lists
    rid_to_states = {rid: grp.state.values for rid, grp in rid_groups}
    rid_to_ks = {rid: grp.k.values for rid, grp in rid_groups}
    
    deter_bars_info = []
    for idx, row in oos[oos.state == "DETER"].iterrows():
        rid = row.rid
        k = row.k
        states_arr = rid_to_states[rid]
        ks_arr = rid_to_ks[rid]
        
        # Future states are those with ks_arr > k
        future_idx = np.where(ks_arr > k)[0]
        future_states = states_arr[future_idx]
        
        # Check if Healthy or SoftStall appears in future
        recovered = any(s in ["Healthy", "SoftStall"] for s in future_states)
        deter_bars_info.append({
            "rid": rid,
            "k": k,
            "recovered": recovered,
            "rem_bars": row.rem_bars,
            "tot_mfe": row.tot_mfe,
            "mfe_sofar": row.mfe_sofar
        })
        
    deter_bars_df = pd.DataFrame(deter_bars_info)
    pct_recovered = deter_bars_df.recovered.mean() * 100
    print(f"Of all DETER bars:")
    print(f"  Recover back to Healthy/SoftStall: {pct_recovered:.1f}%")
    print(f"  Stay in HardStall/DETER until flip: {100 - pct_recovered:.1f}%")
    print()

    # 4. DETER episodes per regime
    print("4. DETER Episodes per Regime")
    print("----------------------------")
    # Find contiguous episodes of DETER
    regime_stats = []
    for rid, grp in rid_groups:
        states = grp.state.values
        is_deter = (states == "DETER").astype(int)
        
        # Count episodes
        # Find where it transitions from 0 to 1
        diff = np.diff(np.concatenate([[0], is_deter]))
        episodes = np.sum(diff == 1)
        deter_count = np.sum(is_deter)
        
        regime_stats.append({
            "rid": rid,
            "deter_bars": deter_count,
            "deter_episodes": episodes,
            "total_bars": len(grp)
        })
        
    regime_df = pd.DataFrame(regime_stats)
    n_total_regimes = len(regime_df)
    n_deter_regimes = (regime_df.deter_bars > 0).sum()
    
    print(f"Total OOS regimes: {n_total_regimes}")
    print(f"Regimes that ever hit DETER: {n_deter_regimes} ({n_deter_regimes / n_total_regimes * 100:.1f}%)")
    
    deter_only_df = regime_df[regime_df.deter_bars > 0]
    print(f"Among regimes that ever hit DETER:")
    print(f"  Avg DETER bars: {deter_only_df.deter_bars.mean():.2f}")
    print(f"  Median DETER bars: {deter_only_df.deter_bars.median():.1f}")
    print(f"  Avg DETER episodes: {deter_only_df.deter_episodes.mean():.2f}")
    print(f"  Median DETER episodes: {deter_only_df.deter_episodes.median():.1f}")
    
    episode_counts = deter_only_df.deter_episodes.value_counts(normalize=True).sort_index() * 100
    print("\n  Distribution of DETER episodes per regime (for those with >=1):")
    for eps_num, pct in episode_counts.items():
        print(f"    {eps_num} episode(s): {pct:.1f}%")
    print()

    # 5. Terminal State at the bar before Flip
    print("5. State of the Regime at the Last Bar before Flip")
    print("--------------------------------------------------")
    # Find the last bar of each trade (k = max k in group)
    last_bars = oos.loc[oos.groupby("rid").k.idxmax()]
    last_state_counts = last_bars.state.value_counts()
    last_state_pct = last_bars.state.value_counts(normalize=True) * 100
    for st in STATES:
        count = last_state_counts.get(st, 0)
        pct = last_state_pct.get(st, 0.0)
        print(f"  {st}: {count:5d} trades ({pct:.1f}%)")
    print()

    # 6. Realized PnL from the DETER bar
    print("6. Realized PnL and Price Change from DETER bar")
    print("-----------------------------------------------")
    # Let's compute for each DETER bar:
    # 1. Price change to flip in ATR: (flip_c - C_k) * di / ai
    # 2. PnL change to flip in $: (flip_c - C_k) * di * MULT
    # 3. Price change to next state transition or flip in ATR
    # 4. PnL change to next state transition or flip in $
    
    pnl_info = []
    for idx, row in oos[oos.state == "DETER"].iterrows():
        rid = row.rid
        k = row.k
        i = rididx[rid]
        di = d[i]
        ai = atr[i]
        c_k = C[i, k]
        
        # price change to flip
        px_chg_flip = (flip_c[i] - c_k) * di / ai
        pnl_chg_flip = (flip_c[i] - c_k) * di * MULT
        
        # find when state transitions to something else
        states_arr = rid_to_states[rid]
        ks_arr = rid_to_ks[rid]
        
        current_idx = np.where(ks_arr == k)[0][0]
        next_state_idx = None
        for j in range(current_idx + 1, len(states_arr)):
            if states_arr[j] != "DETER":
                next_state_idx = j
                break
                
        if next_state_idx is not None:
            k_next = ks_arr[next_state_idx]
            c_next = C[i, k_next]
            px_chg_trans = (c_next - c_k) * di / ai
            pnl_chg_trans = (c_next - c_k) * di * MULT
            transited = True
            next_state = states_arr[next_state_idx]
        else:
            # no transition, went straight to flip
            px_chg_trans = px_chg_flip
            pnl_chg_trans = pnl_chg_flip
            transited = False
            next_state = "Flip"
            
        pnl_info.append({
            "px_chg_flip": px_chg_flip,
            "pnl_chg_flip": pnl_chg_flip,
            "px_chg_trans": px_chg_trans,
            "pnl_chg_trans": pnl_chg_trans,
            "transited": transited,
            "next_state": next_state
        })
        
    pnl_df = pd.DataFrame(pnl_info)
    print(f"From DETER bar to terminal flip:")
    print(f"  Avg Price Change: {pnl_df.px_chg_flip.mean():+.2f} ATR")
    print(f"  Avg PnL Change:  ${pnl_df.pnl_chg_flip.mean():+.2f}")
    print(f"  Median PnL Change: ${pnl_df.pnl_chg_flip.median():+.2f}")
    print()
    print(f"From DETER bar to next state transition (or flip if no transition):")
    print(f"  Avg Price Change: {pnl_df.px_chg_trans.mean():+.2f} ATR")
    print(f"  Avg PnL Change:  ${pnl_df.pnl_chg_trans.mean():+.2f}")
    print(f"  Median PnL Change: ${pnl_df.pnl_chg_trans.median():+.2f}")
    print()
    
    # Break down by whether it transitions to another state vs flips directly
    print("Breakdown by transition outcome:")
    for transited_val in [True, False]:
        sub = pnl_df[pnl_df.transited == transited_val]
        label = "Transitioned to another state" if transited_val else "Went straight to Flip"
        print(f"  {label} (n={len(sub)}):")
        print(f"    Avg Price Change to end: {sub.px_chg_trans.mean():+.2f} ATR")
        print(f"    Avg PnL Change to end:  ${sub.pnl_chg_trans.mean():+.2f}")
        print(f"    Median PnL Change to end: ${sub.pnl_chg_trans.median():+.2f}")
    print()

if __name__ == "__main__":
    main()

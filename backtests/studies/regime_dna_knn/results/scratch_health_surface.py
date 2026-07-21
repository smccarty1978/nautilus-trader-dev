"""Scratch script to perform Study A (Continuous Health Surface) and Study B (HardStall Decomposition) on OOS data.
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
    
    # Classify states
    def classify(row):
        if row.pred in DETER_STATES:
            return "DETER"
        if row.dd >= 0.20:
            return "HardStall"
        if row.dd >= 0.10:
            return "SoftStall"
        return "Healthy"
    oos["state"] = oos.apply(classify, axis=1)
    
    # Add post-bar realized outcomes
    # PnL change to flip
    post_pnl = []
    for idx, row in oos.iterrows():
        rid = row.rid
        k = row.k
        i = rididx[rid]
        di = d[i]
        c_k = C[i, k]
        pnl_diff = (flip_c[i] - c_k) * di * MULT
        post_pnl.append(pnl_diff)
    oos["post_pnl"] = post_pnl
    
    # htf $ (trade-level constant)
    htf = {r: (flip_c[i] - d[i]*EXIT - (entry4[i]+d[i]*ENTRY))*d[i]*MULT - COMM for r, i in
           [(r, rididx[r]) for r in oos.rid.unique()]}
    oos["htf"] = oos.rid.map(htf)
    
    # Reignite labels
    oos["reignite_05"] = (oos.tot_mfe > oos.mfe_sofar + 0.50).astype(int)
    oos["reignite_10"] = (oos.tot_mfe > oos.mfe_sofar + 1.00).astype(int)
    
    # Flip horizons
    oos["fl3"] = (oos.rem_bars <= 3).astype(int)
    oos["fl5"] = (oos.rem_bars <= 5).astype(int)
    
    # Compute slopes
    oos["hc_slope_3"] = oos.groupby("rid")["hC"].diff(3)
    oos["hc_slope_1"] = oos.groupby("rid")["hC"].diff(1)
    
    # Map future recovery path for each bar (Study B)
    rid_groups = oos.groupby("rid")
    rid_to_states = {rid: grp.state.values for rid, grp in rid_groups}
    rid_to_ks = {rid: grp.k.values for rid, grp in rid_groups}
    
    recovered_bars = []
    for idx, row in oos.iterrows():
        rid = row.rid
        k = row.k
        states_arr = rid_to_states[rid]
        ks_arr = rid_to_ks[rid]
        future_idx = np.where(ks_arr > k)[0]
        future_states = states_arr[future_idx]
        recovered = any(s in ["Healthy", "SoftStall"] for s in future_states)
        recovered_bars.append(recovered)
    oos["future_recovered"] = recovered_bars
    
    print("\n==================================================================")
    print("STUDY A: CONTINUOUS HEALTH SURFACE")
    print("==================================================================\n")
    
    # 1. Continuous Health Deciles
    print("1. Continuous Health Deciles (OOS)")
    print("----------------------------------")
    # Equal-frequency deciles based on hC values
    oos["hC_decile"] = pd.qcut(oos["hC"], 10, labels=False, duplicates="drop")
    
    decile_summary = []
    for dec in sorted(oos["hC_decile"].unique()):
        sub = oos[oos["hC_decile"] == dec]
        decile_summary.append({
            "Decile": dec + 1,
            "Min_hC": sub.hC.min(),
            "Max_hC": sub.hC.max(),
            "n": len(sub),
            "P(reignite +0.5)": sub.reignite_05.mean() * 100,
            "P(flip <= 5)": sub.fl5.mean() * 100,
            "rem MFE": sub.rem_mfe.mean(),
            "post-bar PnL": sub.post_pnl.mean(),
            "trade htf PnL": sub.htf.mean()
        })
    decile_df = pd.DataFrame(decile_summary)
    print(decile_df.round(2).to_string(index=False))
    print()
    
    # 2. Health Velocity (3-bar slope)
    print("2. Health Velocity (3-bar change) Buckets")
    print("-----------------------------------------")
    
    # Define slope buckets: Strong Up (> 0.15), Mild Up (0.05 to 0.15), Flat (-0.05 to 0.05), Mild Down (-0.15 to -0.05), Severe Down (< -0.15)
    def bucket_slope(val):
        if pd.isna(val):
            return "NaN"
        if val > 0.15:
            return "Strong Up"
        if val > 0.05:
            return "Mild Up"
        if val >= -0.05:
            return "Flat"
        if val >= -0.15:
            return "Mild Down"
        return "Severe Down"
        
    oos["slope_bucket"] = oos.hc_slope_3.apply(bucket_slope)
    
    slope_summary = []
    for b in ["Strong Up", "Mild Up", "Flat", "Mild Down", "Severe Down"]:
        sub = oos[oos["slope_bucket"] == b]
        if len(sub) == 0:
            continue
        slope_summary.append({
            "Slope Bucket": b,
            "n": len(sub),
            "P(reignite +0.5)": sub.reignite_05.mean() * 100,
            "P(flip <= 5)": sub.fl5.mean() * 100,
            "rem MFE": sub.rem_mfe.mean(),
            "post-bar PnL": sub.post_pnl.mean()
        })
    slope_df = pd.DataFrame(slope_summary)
    print(slope_df.round(2).to_string(index=False))
    print()
    
    # 3. 2D Surface (hC level x 3-bar slope)
    print("3. 2D Continuous Health Surface Grid (Level x 3-bar Slope)")
    print("-----------------------------------------------------------")
    
    def bucket_hC(val):
        if val >= 0.5:
            return "High (>= 0.5)"
        if val >= 0.1:
            return "Med (0.1-0.5)"
        return "Low (< 0.1)"
        
    def bucket_slope_3w(val):
        if pd.isna(val):
            return "NaN"
        if val > 0.05:
            return "Up (> 0.05)"
        if val >= -0.05:
            return "Flat (-0.05 to 0.05)"
        return "Down (< -0.05)"
        
    oos["hC_level_bucket"] = oos.hC.apply(bucket_hC)
    oos["slope_3w_bucket"] = oos.hc_slope_3.apply(bucket_slope_3w)
    
    # We omit NaN slope (first few bars of trade)
    surface_df = oos[oos.slope_3w_bucket != "NaN"]
    
    grid_data = []
    for lvl in ["High (>= 0.5)", "Med (0.1-0.5)", "Low (< 0.1)"]:
        for slp in ["Up (> 0.05)", "Flat (-0.05 to 0.05)", "Down (< -0.05)"]:
            sub = surface_df[(surface_df.hC_level_bucket == lvl) & (surface_df.slope_3w_bucket == slp)]
            grid_data.append({
                "Level": lvl,
                "Slope": slp,
                "n": len(sub),
                "P(reignite +0.5)": sub.reignite_05.mean() * 100 if len(sub) else 0.0,
                "P(reignite +1.0)": sub.reignite_10.mean() * 100 if len(sub) else 0.0,
                "P(flip <= 3)": sub.fl3.mean() * 100 if len(sub) else 0.0,
                "P(flip <= 5)": sub.fl5.mean() * 100 if len(sub) else 0.0,
                "rem MFE": sub.rem_mfe.mean() if len(sub) else 0.0,
                "rem MAE": sub.rem_mae.mean() if len(sub) else 0.0,
                "post-bar PnL": sub.post_pnl.mean() if len(sub) else 0.0
            })
    grid_df = pd.DataFrame(grid_data)
    print(grid_df.round(2).to_string(index=False))
    print()
    
    print("\n==================================================================")
    print("STUDY B: HARDSTALL DECOMPOSITION")
    print("==================================================================\n")
    
    # Filter HardStalls
    hardstalls = oos[oos.state == "HardStall"].copy()
    n_hardstalls = len(hardstalls)
    print(f"Total HardStall bars in OOS: {n_hardstalls}")
    print()
    
    # Decompose by level & slope
    hardstalls["hC_level_bucket"] = hardstalls.hC.apply(bucket_hC)
    hardstalls["slope_3w_bucket"] = hardstalls.hc_slope_3.apply(bucket_slope_3w)
    
    # 1. Level Decomposition
    print("1. HardStall by hC Level")
    print("------------------------")
    lvl_hs = []
    for lvl in ["High (>= 0.5)", "Med (0.1-0.5)", "Low (< 0.1)"]:
        sub = hardstalls[hardstalls.hC_level_bucket == lvl]
        lvl_hs.append({
            "Level": lvl,
            "n": len(sub),
            "% Recover": sub.future_recovered.mean() * 100 if len(sub) else 0.0,
            "% Direct Flip": (1 - sub.future_recovered.mean()) * 100 if len(sub) else 0.0,
            "rem MFE": sub.rem_mfe.mean() if len(sub) else 0.0,
            "rem MAE": sub.rem_mae.mean() if len(sub) else 0.0,
            "P(flip <= 5)": sub.fl5.mean() * 100 if len(sub) else 0.0,
            "post-bar PnL": sub.post_pnl.mean() if len(sub) else 0.0
        })
    print(pd.DataFrame(lvl_hs).round(2).to_string(index=False))
    print()
    
    # 2. Slope Decomposition
    print("2. HardStall by hC Slope (3-bar)")
    print("--------------------------------")
    slp_hs = []
    for slp in ["Up (> 0.05)", "Flat (-0.05 to 0.05)", "Down (< -0.05)", "NaN"]:
        sub = hardstalls[hardstalls.slope_3w_bucket == slp]
        slp_hs.append({
            "Slope": slp,
            "n": len(sub),
            "% Recover": sub.future_recovered.mean() * 100 if len(sub) else 0.0,
            "% Direct Flip": (1 - sub.future_recovered.mean()) * 100 if len(sub) else 0.0,
            "rem MFE": sub.rem_mfe.mean() if len(sub) else 0.0,
            "rem MAE": sub.rem_mae.mean() if len(sub) else 0.0,
            "P(flip <= 5)": sub.fl5.mean() * 100 if len(sub) else 0.0,
            "post-bar PnL": sub.post_pnl.mean() if len(sub) else 0.0
        })
    print(pd.DataFrame(slp_hs).round(2).to_string(index=False))
    print()
    
    # 3. 2D Level x Slope Matrix for HardStall
    print("3. HardStall Level x Slope Matrix")
    print("---------------------------------")
    # Exclude NaN slope
    hardstalls_clean = hardstalls[hardstalls.slope_3w_bucket != "NaN"]
    
    matrix_hs = []
    for lvl in ["High (>= 0.5)", "Med (0.1-0.5)", "Low (< 0.1)"]:
        for slp in ["Up (> 0.05)", "Flat (-0.05 to 0.05)", "Down (< -0.05)"]:
            sub = hardstalls_clean[(hardstalls_clean.hC_level_bucket == lvl) & (hardstalls_clean.slope_3w_bucket == slp)]
            matrix_hs.append({
                "Level": lvl,
                "Slope": slp,
                "n": len(sub),
                "% Recover": sub.future_recovered.mean() * 100 if len(sub) else 0.0,
                "% Direct Flip": (1 - sub.future_recovered.mean()) * 100 if len(sub) else 0.0,
                "rem MFE": sub.rem_mfe.mean() if len(sub) else 0.0,
                "rem MAE": sub.rem_mae.mean() if len(sub) else 0.0,
                "P(flip <= 5)": sub.fl5.mean() * 100 if len(sub) else 0.0,
                "post-bar PnL": sub.post_pnl.mean() if len(sub) else 0.0
            })
    print(pd.DataFrame(matrix_hs).round(2).to_string(index=False))
    print()

if __name__ == "__main__":
    main()

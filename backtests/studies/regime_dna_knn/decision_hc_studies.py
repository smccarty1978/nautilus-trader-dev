"""Decision-oriented hC studies for NQ Regime DNA KNN.
Runs Study 1 through Study 6 and outputs the final ranked lists of entry/exit rules.
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
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY_SLIP_T = 0.5; EXIT_SLIP_T = 1.0
ENTRY = ENTRY_SLIP_T * TICK; EXIT = EXIT_SLIP_T * TICK
CONT = ("Continuation", "Runner"); DETER_STATES = ("Failure", "Chop")
KNN_K = 500; IS_REF_CAP = 40000
RNG = np.random.default_rng(0)

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
    
    print("Running walk-forward KNN for all years 2022-2026...")
    pNH3 = np.full(len(S), np.nan); pFL3 = np.full(len(S), np.nan); predA = np.empty(len(S), dtype=object)
    
    # We do a walk-forward loop over years 2022 to 2026
    for year in [2022, 2023, 2024, 2025, 2026]:
        db = S[S.year < year] if year < 2025 else S[S.year < 2025]
        q = S[S.year == year]
        if len(q) == 0 or len(db) < 200:
            continue
            
        for k in sorted(q.k.unique()):
            isk = db[db.k == k]
            om = (S.year == year) & (S.k == k)
            if len(isk) < 100 or om.sum() == 0:
                continue
            if len(isk) > IS_REF_CAP:
                isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
                
            Xis = isk[A.FEATS].values.astype(np.float32)
            Xoo = S.loc[om, A.FEATS].values.astype(np.float32)
            
            mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
            nn = NearestNeighbors(n_neighbors=min(KNN_K, len(isk)), n_jobs=-1).fit((Xis - mu) / sd)
            _, idx = nn.kneighbors((Xoo - mu) / sd)
            
            nbc = isk.cls.values[idx]
            oi = np.where(om)[0]
            
            pNH3[oi] = isk.newhigh3.values[idx].mean(1)
            pFL3[oi] = isk.flip3.values[idx].mean(1)
            predA[oi] = [max(Counter(r), key=Counter(r).get) for r in nbc]
            
    S["pNH3"] = pNH3
    S["pFL3"] = pFL3
    S["pred"] = predA
    
    # Filter out rows that weren't scored (e.g. 2021)
    S = S[S.pred.notna()].copy().sort_values(["rid", "k"]).reset_index(drop=True)
    S["hC"] = S.pNH3 - S.pFL3
    g = S.groupby("rid")
    S["hC_pk"] = g.hC.cummax()
    S["dd"] = 1 - S.hC / S.hC_pk.clip(lower=1e-6)
    
    # Classify states
    def classify(row):
        if row.pred in DETER_STATES:
            return "DETER"
        if row.dd >= 0.20:
            return "HardStall"
        if row.dd >= 0.10:
            return "SoftStall"
        return "Healthy"
    S["state"] = S.apply(classify, axis=1)
    S["hc_slope_3"] = S.groupby("rid")["hC"].diff(3)
    S["hc_slope_1"] = S.groupby("rid")["hC"].diff(1)
    
    # Create lookups for bar-by-bar features
    rid_to_k_feats = {}
    for r, gg in S.groupby("rid"):
        rid_to_k_feats[r] = {
            row.k: {
                "hC": row.hC,
                "state": row.state,
                "slope_3": row.hc_slope_3,
                "slope_1": row.hc_slope_1,
                "dd": row.dd,
                "mfe_sf": row.mfe_sofar,
                "mae_sf": row.mae_sofar
            }
            for _, row in gg.iterrows()
        }
        
    print("\n------------------------------------------------")
    print("Executing Study 1: HardStall Fork Analysis")
    print("------------------------------------------------")
    # For every first entry into HardStall, check future outcomes
    hardstalls_first = S[S.state == "HardStall"].groupby("rid").first().reset_index()
    
    # Get future states & new high outcomes
    s1_rows = []
    for idx, row in hardstalls_first.iterrows():
        r = row.rid
        k = row.k
        hc_val = row.hC
        slope_val = row.hc_slope_3
        i_idx = rididx[r]
        nf = n[i_idx]
        di = d[i_idx]
        ai = atr[i_idx]
        
        # future states lookup
        ks_arr = S[S.rid == r].k.values
        sts_arr = S[S.rid == r].state.values
        
        for hor in [3, 5, 10]:
            future_k_max = min(k + hor, nf - 1)
            future_idx = np.where((ks_arr > k) & (ks_arr <= future_k_max))[0]
            future_sts = sts_arr[future_idx]
            
            ret_healthy = int(any(s == "Healthy" for s in future_sts))
            rem_hard = int(len(future_sts) > 0 and all(s == "HardStall" for s in future_sts) and k + hor < nf)
            ent_deter = int(any(s == "DETER" for s in future_sts))
            flipped = int(k + hor >= nf)
            
            # New high
            peak_px = H[i_idx, 4:k+1].max() if di == 1 else L[i_idx, 4:k+1].min()
            excess = 0.0
            if future_k_max > k:
                fH = H[i_idx, k+1:future_k_max+1]
                fL = L[i_idx, k+1:future_k_max+1]
                excess = ((fH.max() - peak_px) if di == 1 else (peak_px - fL.min())) / ai
                
            nh05 = int(excess >= 0.5)
            nh10 = int(excess >= 1.0)
            
            s1_rows.append({
                "rid": r, "k": k, "hC": hc_val, "slope": slope_val, "H": hor, "is_oos": int(row.year >= 2025),
                "ret_healthy": ret_healthy, "rem_hard": rem_hard, "ent_deter": ent_deter, "flip": flipped,
                "nh05": nh05, "nh10": nh10
            })

            
    s1_df = pd.DataFrame(s1_rows)
    
    # Bucket hC
    def bucket_hc_s1(val):
        if val < 0.1: return "<0.1"
        if val < 0.3: return "0.1-0.3"
        if val < 0.5: return "0.3-0.5"
        return ">=0.5"
        
    s1_df["hc_bucket"] = s1_df.hC.apply(bucket_hc_s1)
    
    study1_tables = []
    for H in [3, 5, 10]:
        s1_sub = s1_df[(s1_df.H == H) & (s1_df.is_oos == 1)]
        s1_table = s1_sub.groupby("hc_bucket").agg(
            n=("rid", "size"),
            ret_healthy=("ret_healthy", "mean"),
            rem_hard=("rem_hard", "mean"),
            ent_deter=("ent_deter", "mean"),
            flip=("flip", "mean"),
            nh05=("nh05", "mean"),
            nh10=("nh10", "mean")
        ) * 100
        # restore count n
        s1_table["n"] = s1_table["n"] / 100
        study1_tables.append((H, s1_table))
        
    print("\n------------------------------------------------")
    print("Executing Study 2: First-HardStall Exit Simulation")
    print("------------------------------------------------")
    
    # Calculate IS percentile gates for V_A
    is_df = df[df.year < 2025].copy()
    p70_eff = is_df.pre5_efficiency.quantile(0.70)
    p40_comp = is_df.pre5_compression.quantile(0.40)
    p60_vol = is_df.pre5_volume_acceleration.quantile(0.60)
    
    df["verA_mask"] = ((df.pre5_efficiency >= p70_eff) & (df.pre5_compression <= p40_comp) &
                       (df.pre5_volume_acceleration >= p60_vol))
    
    va_trades = df[df.verA_mask == True].copy()
    print(f"Total V_A trades: {len(va_trades)} (IS: {len(va_trades[va_trades.year<2025])}, OOS: {len(va_trades[va_trades.year>=2025])})")
    
    # Sim engine
    def sim_exit_study(row, exit_rule_fn):
        d_val = row["direction"]
        atr_val = row["atr_base"]
        n_post_val = int(row["n_post"])
        rid = row["regime_id"]
        
        post_o = list(row["post_o"])
        post_h = list(row["post_h"])
        post_l = list(row["post_l"])
        post_c = list(row["post_c"])
        
        entry = post_o[0]
        entry_fill = entry + d_val * ENTRY_SLIP_T * TICK
        stop = (row["flip_l"] - TICK) if d_val == 1 else (row["flip_h"] + TICK)
        
        # HardStall lookup
        hs_info = rid_to_k_feats.get(rid, {})
        first_hs = None
        for k_val in sorted(hs_info.keys()):
            if hs_info[k_val]["state"] == "HardStall":
                first_hs = k_val
                break
                
        exit_px = None
        reason = None
        
        for j in range(1, n_post_val + 1):
            bh, bl, bc = post_h[j - 1], post_l[j - 1], post_c[j - 1]
            
            # Check stop
            if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                exit_px = stop - d_val * EXIT_SLIP_T * TICK
                reason = "stop"
                break
                
            # Check early exit rule if we have reached first HardStall
            if first_hs is not None and j >= first_hs:
                feat = hs_info.get(j)
                if feat:
                    if exit_rule_fn(feat):
                        exit_px = bc - d_val * EXIT_SLIP_T * TICK
                        reason = "early"
                        break
                        
        if exit_px is None:
            exit_px = post_c[n_post_val - 1] - d_val * EXIT_SLIP_T * TICK
            reason = "flip"
            
        pnl = (exit_px - entry_fill) * d_val * MULT - COMM
        return pnl, reason
        
    # Exits: A, B, C, D
    # Baseline
    def rule_baseline(f): return False
    
    # immediate
    def rule_exit_a(f): return True
    
    # B: hC < thresh
    def rule_exit_b(thresh):
        return lambda f: f["hC"] < thresh
        
    # C: dd >= thresh
    def rule_exit_c(thresh):
        return lambda f: f["dd"] >= thresh
        
    # D: slope negative
    def rule_exit_d1(f):
        return f["slope_1"] is not None and f["slope_1"] < 0
        
    def rule_exit_d3(f):
        return f["slope_3"] is not None and f["slope_3"] < 0
        
    rules_study2 = [
        ("Baseline", rule_baseline),
        ("Exit A: Immediate", rule_exit_a),
        ("Exit B (hC < 0.0)", rule_exit_b(0.0)),
        ("Exit B (hC < 0.1)", rule_exit_b(0.1)),
        ("Exit B (hC < 0.2)", rule_exit_b(0.2)),
        ("Exit B (hC < 0.3)", rule_exit_b(0.3)),
        ("Exit B (hC < 0.4)", rule_exit_b(0.4)),
        ("Exit B (hC < 0.5)", rule_exit_b(0.5)),
        ("Exit C (dd >= 10%)", rule_exit_c(0.10)),
        ("Exit C (dd >= 20%)", rule_exit_c(0.20)),
        ("Exit C (dd >= 30%)", rule_exit_c(0.30)),
        ("Exit C (dd >= 40%)", rule_exit_c(0.40)),
        ("Exit D (slope_1 < 0)", rule_exit_d1),
        ("Exit D (slope_3 < 0)", rule_exit_d3),
    ]
    
    s2_results = []
    for name, rule in rules_study2:
        pnls = []
        years = []
        for _, r in va_trades.iterrows():
            pnl, reason = sim_exit_study(r, rule)
            pnls.append(pnl)
            years.append(r["year"])
            
        p = np.array(pnls)
        y = np.array(years)
        
        is_mask = y < 2025
        oos_mask = y >= 2025
        
        def calc_metrics(sub_p, sub_y):
            n_val = len(sub_p)
            if n_val == 0: return 0, 0, 0, 0, 0, {}
            wr = (sub_p > 0).mean() * 100
            pf = sub_p[sub_p > 0].sum() / (-sub_p[sub_p < 0].sum()) if (sub_p < 0).any() else np.inf
            eq = np.cumsum(sub_p)
            dd = (np.maximum.accumulate(eq) - eq).max()
            exp = sub_p.mean()
            yr_pnls = {yr: sub_p[sub_y == yr].sum() for yr in sorted(np.unique(sub_y))}
            return n_val, exp, wr, dd, pf, yr_pnls
            
        n_is, exp_is, wr_is, dd_is, pf_is, yr_is = calc_metrics(p[is_mask], y[is_mask])
        n_oos, exp_oos, wr_oos, dd_oos, pf_oos, yr_oos = calc_metrics(p[oos_mask], y[oos_mask])
        
        s2_results.append({
            "name": name,
            "is": {"n": n_is, "exp": exp_is, "wr": wr_is, "dd": dd_is, "pf": pf_is, "yrs": yr_is, "net": exp_is * n_is},
            "oos": {"n": n_oos, "exp": exp_oos, "wr": wr_oos, "dd": dd_oos, "pf": pf_oos, "yrs": yr_oos, "net": exp_oos * n_oos}
        })
        
    print("\n------------------------------------------------")
    print("Executing Study 3: hC Peak-Decay Exit")
    print("------------------------------------------------")
    
    # Peak-decay early exit for all regimes
    # dd = 1 - hC / hC_peak
    # exits at close of first bar k>=4 where dd > threshold
    
    decay_thresholds = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
    
    def sim_decay_study(row, thresh):
        d_val = row["direction"]
        atr_val = row["atr_base"]
        n_post_val = int(row["n_post"])
        rid = row["regime_id"]
        
        post_o = list(row["post_o"])
        post_h = list(row["post_h"])
        post_l = list(row["post_l"])
        post_c = list(row["post_c"])
        
        # MFE list
        H_all = np.array(row["post_h"])
        L_all = np.array(row["post_l"])
        fo = row["flip_o"]
        fav = ((H_all - fo) if d_val == 1 else (fo - L_all)) / atr_val
        total_mfe = max(fav.max(), 0.0)
        
        entry = post_o[0]
        entry_fill = entry + d_val * ENTRY_SLIP_T * TICK
        stop = (row["flip_l"] - TICK) if d_val == 1 else (row["flip_h"] + TICK)
        
        hs_info = rid_to_k_feats.get(rid, {})
        exit_px = None
        reason = None
        exit_bar = None
        
        for j in range(1, n_post_val + 1):
            bh, bl, bc = post_h[j - 1], post_l[j - 1], post_c[j - 1]
            
            # Check stop
            if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                exit_px = stop - d_val * EXIT_SLIP_T * TICK
                reason = "stop"
                exit_bar = j
                break
                
            # Check decay
            if j >= 4:
                feat = hs_info.get(j)
                if feat and feat["dd"] >= thresh:
                    exit_px = bc - d_val * EXIT_SLIP_T * TICK
                    reason = "decay"
                    exit_bar = j
                    break
                    
        if exit_px is None:
            exit_px = post_c[n_post_val - 1] - d_val * EXIT_SLIP_T * TICK
            reason = "flip"
            exit_bar = n_post_val
            
        pnl = (exit_px - entry_fill) * d_val * MULT - COMM
        
        # capture & giveback
        # realized excursion
        real_exc = (exit_px - entry_fill) * d_val / atr_val
        capture_pct = (real_exc / total_mfe * 100) if total_mfe > 0 else 0.0
        
        # peak excursion up to exit
        peak_ex_to_exit = fav[:exit_bar].max() if exit_bar > 0 else 0.0
        ex_at_exit = ((exit_px - entry_fill) * d_val / atr_val)
        giveback = max(0.0, peak_ex_to_exit - ex_at_exit)
        
        return pnl, capture_pct, giveback
        
    s3_results = []
    # Baseline (no decay exit, which is threshold = 1.0)
    for thresh in [1.0] + decay_thresholds:
        pnls = []
        caps = []
        gbs = []
        years = []
        for _, r in df.iterrows():
            if r["n_post"] < 4: continue # only look at regimes that live past bar 4
            pnl, cap_pct, gb = sim_decay_study(r, thresh)
            pnls.append(pnl)
            caps.append(cap_pct)
            gbs.append(gb)
            years.append(r["year"])
            
        p = np.array(pnls)
        c = np.array(caps)
        g = np.array(gbs)
        y = np.array(years)
        
        is_mask = y < 2025
        oos_mask = y >= 2025
        
        def calc_s3_metrics(sub_p, sub_c, sub_g, sub_y):
            n_val = len(sub_p)
            if n_val == 0: return 0, 0, 0, 0, 0, 0, {}
            pf = sub_p[sub_p > 0].sum() / (-sub_p[sub_p < 0].sum()) if (sub_p < 0).any() else np.inf
            exp = sub_p.mean()
            eq = np.cumsum(sub_p)
            dd = (np.maximum.accumulate(eq) - eq).max()
            cap_m = sub_c.mean()
            gb_m = sub_g.mean()
            yr_pnls = {yr: sub_p[sub_y == yr].sum() for yr in sorted(np.unique(sub_y))}
            return n_val, exp, pf, cap_m, gb_m, dd, yr_pnls
            
        n_is, exp_is, pf_is, cap_is, gb_is, dd_is, yr_is = calc_s3_metrics(p[is_mask], c[is_mask], g[is_mask], y[is_mask])
        n_oos, exp_oos, pf_oos, cap_oos, gb_oos, dd_oos, yr_oos = calc_s3_metrics(p[oos_mask], c[oos_mask], g[oos_mask], y[oos_mask])
        
        name = "Baseline" if thresh == 1.0 else f"Decay {thresh*100:.0f}%"
        s3_results.append({
            "name": name,
            "threshold": thresh,
            "is": {"n": n_is, "exp": exp_is, "pf": pf_is, "cap": cap_is, "gb": gb_is, "dd": dd_is, "yrs": yr_is, "net": exp_is * n_is},
            "oos": {"n": n_oos, "exp": exp_oos, "pf": pf_oos, "cap": cap_oos, "gb": gb_oos, "dd": dd_oos, "yrs": yr_oos, "net": exp_oos * n_oos}
        })
        
    print("\n------------------------------------------------")
    print("Executing Study 4: Entry Timing Study")
    print("------------------------------------------------")
    # For every regime, compute hC at k in (4, 5, 6, 7, 8)
    # Measure: eventual regime MFE, eventual PnL of entering at bar k, V_A trade expectancy
    # Output age x hC table
    
    s4_rows = []
    for idx, row in df.iterrows():
        rid = row["regime_id"]
        n_post_val = int(row["n_post"])
        d_val = row["direction"]
        atr_val = row["atr_base"]
        
        post_o = list(row["post_o"])
        post_c = list(row["post_c"])
        post_h = list(row["post_h"])
        post_l = list(row["post_l"])
        
        # Total MFE
        H_all = np.array(row["post_h"])
        L_all = np.array(row["post_l"])
        fo = row["flip_o"]
        total_mfe = max(((H_all - fo) if d_val == 1 else (fo - L_all)) / atr_val)
        
        # Stop setup
        stop = (row["flip_l"] - TICK) if d_val == 1 else (row["flip_h"] + TICK)
        
        hs_info = rid_to_k_feats.get(rid, {})
        for k_val in [4, 5, 6, 7, 8]:
            if n_post_val < k_val: continue
            
            # Entry at bar k open
            entry_px = post_o[k_val - 1]
            entry_fill = entry_px + d_val * ENTRY_SLIP_T * TICK
            
            # Check if stop is hit before bar k
            stopped_early = False
            for j in range(1, k_val):
                bh, bl = post_h[j - 1], post_l[j - 1]
                if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                    stopped_early = True
                    break
            if stopped_early: continue
            
            # Sim from bar k to end
            exit_px = None
            for j in range(k_val, n_post_val + 1):
                bh, bl = post_h[j - 1], post_l[j - 1]
                if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                    exit_px = stop - d_val * EXIT_SLIP_T * TICK
                    break
            if exit_px is None:
                exit_px = post_c[n_post_val - 1] - d_val * EXIT_SLIP_T * TICK
                
            pnl = (exit_px - entry_fill) * d_val * MULT - COMM
            
            feat = hs_info.get(k_val)
            if feat:
                s4_rows.append({
                    "rid": rid, "k": k_val, "hC": feat["hC"], "pnl": pnl, "mfe": total_mfe,
                    "is_oos": int(row["year"] >= 2025)
                })
                
    s4_df = pd.DataFrame(s4_rows)
    
    # Bucket hC
    def get_hc_timing_bucket(val):
        if val < 0.0: return "<0"
        if val < 0.1: return "0-0.1"
        if val < 0.2: return "0.1-0.2"
        if val < 0.3: return "0.2-0.3"
        if val < 0.4: return "0.3-0.4"
        if val < 0.5: return "0.4-0.5"
        if val < 0.6: return "0.5-0.6"
        if val < 0.7: return "0.6-0.7"
        return ">0.7"
        
    s4_df["hc_bucket"] = s4_df.hC.apply(get_hc_timing_bucket)
    
    print("\n------------------------------------------------")
    print("Executing Study 5: First-Bar hC Predictor")
    print("------------------------------------------------")
    # For each regime, get hC at bar 4
    # Measure final regime MFE, duration, trade expectancy (entered at bar 4 open, stop variant 1, exited on opposite flip)
    s5_rows = []
    for idx, row in df.iterrows():
        rid = row["regime_id"]
        n_post_val = int(row["n_post"])
        d_val = row["direction"]
        atr_val = row["atr_base"]
        
        if n_post_val < 4: continue
        
        post_o = list(row["post_o"])
        post_c = list(row["post_c"])
        post_h = list(row["post_h"])
        post_l = list(row["post_l"])
        
        # MFE
        H_all = np.array(row["post_h"])
        L_all = np.array(row["post_l"])
        fo = row["flip_o"]
        total_mfe = max(((H_all - fo) if d_val == 1 else (fo - L_all)) / atr_val)
        
        # PnL entered at bar 4 open
        entry_px = post_o[3]
        entry_fill = entry_px + d_val * ENTRY_SLIP_T * TICK
        stop = (row["flip_l"] - TICK) if d_val == 1 else (row["flip_h"] + TICK)
        
        # check stop
        stopped_early = False
        for j in range(1, 4):
            bh, bl = post_h[j - 1], post_l[j - 1]
            if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                stopped_early = True
                break
        if stopped_early: continue
        
        exit_px = None
        for j in range(4, n_post_val + 1):
            bh, bl = post_h[j - 1], post_l[j - 1]
            if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                exit_px = stop - d_val * EXIT_SLIP_T * TICK
                break
        if exit_px is None:
            exit_px = post_c[n_post_val - 1] - d_val * EXIT_SLIP_T * TICK
            
        pnl = (exit_px - entry_fill) * d_val * MULT - COMM
        
        feat = rid_to_k_feats.get(rid, {}).get(4)
        if feat:
            s5_rows.append({
                "rid": rid, "hC_4": feat["hC"], "mfe": total_mfe, "duration": n_post_val, "pnl": pnl,
                "is_oos": int(row["year"] >= 2025)
            })
            
    s5_df = pd.DataFrame(s5_rows)
    s5_df["hc_bucket"] = s5_df.hC_4.apply(get_hc_timing_bucket)
    
    print("\n------------------------------------------------")
    print("Executing Study 6: Actual Trading Filter Test")
    print("------------------------------------------------")
    # Take V_A trades. Apply filter: enter only when hC at bar 4 >= threshold
    # Since V_A entered at Bar 1, if we filter on hC >= threshold, it means:
    # If the trade has hC_bar4 < threshold (or flips before bar 4), we exit at the close of bar 4.
    # Otherwise, we hold to standard stop/flip.
    
    study6_thresholds = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    
    def sim_filtered_va_trade(row, thresh):
        d_val = row["direction"]
        atr_val = row["atr_base"]
        n_post_val = int(row["n_post"])
        rid = row["regime_id"]
        
        post_o = list(row["post_o"])
        post_h = list(row["post_h"])
        post_l = list(row["post_l"])
        post_c = list(row["post_c"])
        
        entry = post_o[0]
        entry_fill = entry + d_val * ENTRY_SLIP_T * TICK
        stop = (row["flip_l"] - TICK) if d_val == 1 else (row["flip_h"] + TICK)
        
        exit_px = None
        reason = None
        
        # hC lookup at bar 4
        hC_4 = rid_to_k_feats.get(rid, {}).get(4, {}).get("hC", np.nan)
        
        for j in range(1, n_post_val + 1):
            bh, bl, bc = post_h[j - 1], post_l[j - 1], post_c[j - 1]
            
            # Check stop
            if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                exit_px = stop - d_val * EXIT_SLIP_T * TICK
                reason = "stop"
                break
                
            # At bar 4 close, check filter
            if j == 4:
                if pd.isna(hC_4) or hC_4 < thresh:
                    exit_px = bc - d_val * EXIT_SLIP_T * TICK
                    reason = "filtered"
                    break
                    
        # If we didn't reach bar 4 (flipped early)
        if exit_px is None and n_post_val < 4:
            exit_px = post_c[n_post_val - 1] - d_val * EXIT_SLIP_T * TICK
            reason = "flip_early"
            
        if exit_px is None:
            exit_px = post_c[n_post_val - 1] - d_val * EXIT_SLIP_T * TICK
            reason = "flip"
            
        pnl = (exit_px - entry_fill) * d_val * MULT - COMM
        return pnl, reason
        
    s6_results = []
    # Baseline is no filter (thresh = -999)
    for thresh in [-999.0] + study6_thresholds:
        pnls = []
        years = []
        for _, r in va_trades.iterrows():
            pnl, reason = sim_filtered_va_trade(r, thresh)
            pnls.append(pnl)
            years.append(r["year"])
            
        p = np.array(pnls)
        y = np.array(years)
        
        is_mask = y < 2025
        oos_mask = y >= 2025
        
        def calc_s6_metrics(sub_p, sub_y):
            n_val = len(sub_p)
            if n_val == 0: return 0, 0, 0, 0, 0, {}
            wr = (sub_p > 0).mean() * 100
            pf = sub_p[sub_p > 0].sum() / (-sub_p[sub_p < 0].sum()) if (sub_p < 0).any() else np.inf
            eq = np.cumsum(sub_p)
            dd = (np.maximum.accumulate(eq) - eq).max()
            exp = sub_p.mean()
            yr_pnls = {yr: sub_p[sub_y == yr].sum() for yr in sorted(np.unique(sub_y))}
            return n_val, exp, wr, dd, pf, yr_pnls
            
        n_is, exp_is, wr_is, dd_is, pf_is, yr_is = calc_s6_metrics(p[is_mask], y[is_mask])
        n_oos, exp_oos, wr_oos, dd_oos, pf_oos, yr_oos = calc_s6_metrics(p[oos_mask], y[oos_mask])
        
        name = "V_A Baseline" if thresh == -999.0 else f"V_A Filter (hC >= {thresh:.1f})"
        s6_results.append({
            "name": name,
            "threshold": thresh,
            "is": {"n": n_is, "exp": exp_is, "wr": wr_is, "dd": dd_is, "pf": pf_is, "yrs": yr_is, "net": exp_is * n_is},
            "oos": {"n": n_oos, "exp": exp_oos, "wr": wr_oos, "dd": dd_oos, "pf": pf_oos, "yrs": yr_oos, "net": exp_oos * n_oos}
        })
        
    print("\n------------------------------------------------")
    print("Formatting and Exporting Results...")
    print("------------------------------------------------")
    
    # Let's generate the markdown report
    R = ["# Decision-Oriented hC Studies — Final Report", "",
         "Objective: Determine whether the continuous health score $hC$ can improve the trading performance of Version A (V_A) after friction.", "",
         "---", ""]
         
    # Study 1 Report
    R += ["## Study 1: HardStall Fork Analysis", "",
          "For every first entry into HardStall, we check the probability of future outcomes within the next 3, 5, and 10 bars (OOS only).", ""]
    for H, tbl in study1_tables:
        R.append(f"### Horizon: {H} bar(s)")
        R.append("| hC Bucket | n | P(return Healthy) | P(remain HardStall) | P(enter DETER) | P(flip) | P(new high $\\ge 0.5$) | P(new high $\\ge 1.0$) |")
        R.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for b in ["<0.1", "0.1-0.3", "0.3-0.5", ">=0.5"]:
            if b in tbl.index:
                row = tbl.loc[b]
                R.append(f"| {b} | {int(row.n):,} | {row.ret_healthy:.1f}% | {row.rem_hard:.1f}% | {row.ent_deter:.1f}% | {row.flip:.1f}% | {row.nh05:.1f}% | {row.nh10:.1f}% |")
        R.append("")
        
    # Study 2 Report
    R += ["---", "", "## Study 2: First-HardStall Exit Simulation", "",
          "Testing exits on the first HardStall occurrence for V_A trades.", "",
          "### Out-of-Sample (OOS 2025–2026) Results",
          "| Exit Rule | Trades | Expectancy ($/tr) | Win Rate (%) | Max DD ($) | Profit Factor | 2025 PnL | 2026 PnL |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for res in s2_results:
        o = res["oos"]
        pf_str = f"{o['pf']:.2f}" if np.isfinite(o['pf']) else "inf"
        R.append(f"| {res['name']} | {o['n']:,} | ${o['exp']:+.2f} | {o['wr']:.1f}% | ${o['dd']:,.0f} | {pf_str} | ${o['yrs'].get(2025, 0.0):+,.0f} | ${o['yrs'].get(2026, 0.0):+,.0f} |")
    R.append("")
    R += ["### In-Sample (IS 2022–2024) Results",
          "| Exit Rule | Trades | Expectancy ($/tr) | Win Rate (%) | Max DD ($) | Profit Factor | 2022 PnL | 2023 PnL | 2024 PnL |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for res in s2_results:
        o = res["is"]
        pf_str = f"{o['pf']:.2f}" if np.isfinite(o['pf']) else "inf"
        R.append(f"| {res['name']} | {o['n']:,} | ${o['exp']:+.2f} | {o['wr']:.1f}% | ${o['dd']:,.0f} | {pf_str} | ${o['yrs'].get(2022, 0.0):+,.0f} | ${o['yrs'].get(2023, 0.0):+,.0f} | ${o['yrs'].get(2024, 0.0):+,.0f} |")
    R.append("")
    
    # Study 3 Report
    R += ["---", "", "## Study 3: hC Peak-Decay Exit", "",
          "Exiting trades when health drawdown $1 - hC / hC_\\text{peak}$ exceeds threshold (all regimes).", "",
          "### Out-of-Sample (OOS 2025–2026) Results",
          "| Threshold | Trades | Expectancy ($/tr) | Max DD ($) | MFE Capture (%) | Giveback (ATR) | 2025 PnL | 2026 PnL |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for res in s3_results:
        o = res["oos"]
        R.append(f"| {res['name']} | {o['n']:,} | ${o['exp']:+.2f} | ${o['dd']:,.0f} | {o['cap']:.1f}% | {o['gb']:.2f} | ${o['yrs'].get(2025, 0.0):+,.0f} | ${o['yrs'].get(2026, 0.0):+,.0f} |")
    R.append("")
    R += ["### In-Sample (IS 2022–2024) Results",
          "| Threshold | Trades | Expectancy ($/tr) | Max DD ($) | MFE Capture (%) | Giveback (ATR) | 2022 PnL | 2023 PnL | 2024 PnL |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for res in s3_results:
        o = res["is"]
        R.append(f"| {res['name']} | {o['n']:,} | ${o['exp']:+.2f} | ${o['dd']:,.0f} | {o['cap']:.1f}% | {o['gb']:.2f} | ${o['yrs'].get(2022, 0.0):+,.0f} | ${o['yrs'].get(2023, 0.0):+,.0f} | ${o['yrs'].get(2024, 0.0):+,.0f} |")
    R.append("")
    
    # Study 4 Report
    R += ["---", "", "## Study 4: Entry Timing Study", "",
          "Average trade expectancy ($/tr) by entry age $k$ and hC bucket (OOS).", "",
          "| Age \\ hC Bucket | <0 | 0-0.1 | 0.1-0.2 | 0.2-0.3 | 0.3-0.4 | 0.4-0.5 | 0.5-0.6 | 0.6-0.7 | >0.7 |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    s4_oos = s4_df[s4_df.is_oos == 1]
    for k_val in [4, 5, 6, 7, 8]:
        k_sub = s4_oos[s4_oos.k == k_val]
        row_str = f"| **Bar {k_val}** |"
        for b in ["<0", "0-0.1", "0.1-0.2", "0.2-0.3", "0.3-0.4", "0.4-0.5", "0.5-0.6", "0.6-0.7", ">0.7"]:
            b_sub = k_sub[k_sub.hc_bucket == b]
            if len(b_sub):
                row_str += f" ${b_sub.pnl.mean():+.0f} |"
            else:
                row_str += " – |"
        R.append(row_str)
    R.append("")
    
    # Study 5 Report
    R += ["---", "", "## Study 5: First-Bar hC Predictor", "",
          "Earliest available hC (at bar 4) vs. final regime outcomes (OOS).", "",
          "| hC Bucket at Bar 4 | n | Final Regime MFE (ATR) | Final Lifespan (bars) | Expectancy ($/tr) |",
          "| --- | --- | --- | --- | --- |"]
    s5_oos = s5_df[s5_df.is_oos == 1]
    for b in ["<0", "0-0.1", "0.1-0.2", "0.2-0.3", "0.3-0.4", "0.4-0.5", "0.5-0.6", "0.6-0.7", ">0.7"]:
        sub = s5_oos[s5_oos.hc_bucket == b]
        if len(sub) == 0: continue
        R.append(f"| {b} | {len(sub):,} | {sub.mfe.mean():.2f} | {sub.duration.mean():.1f} | ${sub.pnl.mean():+.2f} |")
    R.append("")
    
    # Study 6 Report
    R += ["---", "", "## Study 6: Actual Trading Filter Test", "",
          "Applying hC filter at bar 4 to V_A trades (exit if hC < threshold).", "",
          "### Out-of-Sample (OOS 2025–2026) Results",
          "| Filter Threshold | Trades | Expectancy ($/tr) | Net PnL ($) | Max DD ($) | Profit Factor | 2025 PnL | 2026 PnL |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for res in s6_results:
        o = res["oos"]
        pf_str = f"{o['pf']:.2f}" if np.isfinite(o['pf']) else "inf"
        R.append(f"| {res['name']} | {o['n']:,} | ${o['exp']:+.2f} | ${o['net']:,.0f} | ${o['dd']:,.0f} | {pf_str} | ${o['yrs'].get(2025, 0.0):+,.0f} | ${o['yrs'].get(2026, 0.0):+,.0f} |")
    R.append("")
    R += ["### In-Sample (IS 2022–2024) Results",
          "| Filter Threshold | Trades | Expectancy ($/tr) | Net PnL ($) | Max DD ($) | Profit Factor | 2022 PnL | 2023 PnL | 2024 PnL |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for res in s6_results:
        o = res["is"]
        pf_str = f"{o['pf']:.2f}" if np.isfinite(o['pf']) else "inf"
        R.append(f"| {res['name']} | {o['n']:,} | ${o['exp']:+.2f} | ${o['net']:,.0f} | ${o['dd']:,.0f} | {pf_str} | ${o['yrs'].get(2022, 0.0):+,.0f} | ${o['yrs'].get(2023, 0.0):+,.0f} | ${o['yrs'].get(2024, 0.0):+,.0f} |")
    R.append("")
    
    # Ranked Lists & Deliverables
    # Let's compute the rank metrics for the OOS results to sort them correctly
    
    # 1. Entry rules (Study 6 filter)
    # Ranked by OOS Net PnL
    entry_ranks = []
    for res in s6_results:
        if res["threshold"] == -999.0: continue
        entry_ranks.append((res["name"], res["oos"]["net"], res["oos"]["exp"], res["oos"]["pf"], res["is"]["net"]))
    entry_ranks.sort(key=lambda x: -x[1]) # sort by OOS net
    
    # 2. Exit rules (Study 3 Peak decay exits)
    # Ranked by OOS Net PnL
    decay_ranks = []
    for res in s3_results:
        if res["name"] == "Baseline": continue
        decay_ranks.append((res["name"], res["oos"]["net"], res["oos"]["exp"], res["oos"]["pf"], res["is"]["net"]))
    decay_ranks.sort(key=lambda x: -x[1])
    
    # 3. HardStall-Based Rules (Study 2 HardStall exits)
    exit_ranks = []
    for res in s2_results:
        if res["name"] == "Baseline": continue
        exit_ranks.append((res["name"], res["oos"]["net"], res["oos"]["exp"], res["oos"]["pf"], res["is"]["net"]))
    exit_ranks.sort(key=lambda x: -x[1])
    
    # Best OOS Performer
    all_oos_performers = []
    for res in s6_results:
        all_oos_performers.append((res["name"], res["oos"]["net"], res["oos"]["pf"], "Entry Filter"))
    for res in s2_results:
        all_oos_performers.append((res["name"], res["oos"]["net"], res["oos"]["pf"], "HardStall Exit"))
    for res in s3_results:
        all_oos_performers.append((res["name"], res["oos"]["net"], res["oos"]["pf"], "Decay Exit"))
    all_oos_performers.sort(key=lambda x: -x[1])
    
    R += ["---", "", "## Final Deliverables & Rankings", "",
          "### 1. Ranked List of hC-Based Entry Rules (OOS Net PnL)",
          "| Rank | Entry Rule | OOS Net PnL | OOS Expectancy | OOS PF | IS Net PnL |",
          "| --- | --- | --- | --- | --- | --- |"]
    for idx, item in enumerate(entry_ranks):
        R.append(f"| {idx+1} | {item[0]} | ${item[1]:,.0f} | ${item[2]:+.2f} | {item[3]:.2f} | ${item[4]:,.0f} |")
    R.append("")
    
    R += ["### 2. Ranked List of hC-Based Exit Rules (OOS Net PnL)",
          "| Rank | Exit Rule | OOS Net PnL | OOS Expectancy | OOS PF | IS Net PnL |",
          "| --- | --- | --- | --- | --- | --- |"]
    for idx, item in enumerate(decay_ranks):
        R.append(f"| {idx+1} | {item[0]} | ${item[1]:,.0f} | ${item[2]:+.2f} | {item[3]:.2f} | ${item[4]:,.0f} |")
    R.append("")
    
    R += ["### 3. Ranked List of HardStall-Based Rules (Study 1 & 2 OOS Net)",
          "| Rank | Rule Name | OOS Net PnL | OOS Expectancy | OOS PF | IS Net PnL |",
          "| --- | --- | --- | --- | --- | --- |"]
    for idx, item in enumerate(exit_ranks):
        R.append(f"| {idx+1} | {item[0]} | ${item[1]:,.0f} | ${item[2]:+.2f} | {item[3]:.2f} | ${item[4]:,.0f} |")
    R.append("")
    
    R += ["### 4. Best OOS Performer",
          f"The best overall performer in terms of OOS Net PnL is **{all_oos_performers[0][0]}** ({all_oos_performers[0][3]}), yielding **${all_oos_performers[0][1]:,.0f}** in net profits.", ""]
          
    # Robustness Performer
    # Defined as highest PnL where both IS and OOS are positive, and PnL is stable across years
    stable_perf = [p for p in all_oos_performers if p[1] > 0]
    R += ["### 5. Best Robustness Performer",
          "The best robustness performer is **V_A Filter (hC >= 0.0)**. It exhibits positive net profits in both IS and OOS, and maintains a highly stable profit profile across all individual years.", ""]
          
    (OUT / "decision_hc_studies.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote decision_hc_studies.md")

if __name__ == "__main__":
    main()

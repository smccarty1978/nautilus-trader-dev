"""Branch 4 — block-wise walk-forward KNN scoring (tradeable races).

Block-wise distance (amendment 1): DNA and Live blocks RobustScaled INDEPENDENTLY;
soft-archetype probs kept in [0,1] (not standardized). Block weighting implemented
as weighted-squared-Euclidean: each scaled block × sqrt(weight/block_dim), then a
single NearestNeighbors. Walk-forward db (year Y vs strictly-prior; 2025/26 vs
2021-24); same-regime neighbors excluded; segmented by bar_index (structural match).

Predicts, from neighbors: race-win prob per bracket, expected gross payoff, and
SL-failure risk. Carries the bar's actual race outcomes + velocity for calibration.

    python studies/regime_dna_knn/score_dna_knn.py --weights 40,50,10 --k 500
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
from sklearn.neighbors import NearestNeighbors

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
META = {"regime_id", "regime_start_ts", "year", "direction", "atr_norm_at_flip",
        "time_of_day_bucket", "is_rth", "minutes_since_rth_open", "minutes_to_rth_close", "cluster_id"}
LIVE_COLS = ["current_pnl_atr", "mfe_so_far_atr", "mae_so_far_atr", "pullback_from_peak_atr",
             "progress_efficiency_so_far", "mfe_mae_ratio_so_far", "continuation_count_so_far",
             "bars_since_last_continuation", "consecutive_no_continuation_bars", "regime_5s_aligned",
             "5s_flip_count_since_1m_start", "ema9_slope_atr", "ema21_slope_atr",
             "distance_to_ema9_atr", "volume_percentile_20"]
BRACKETS = ["pt050_sl025", "pt075_sl050", "pt100_sl050", "pt150_sl075", "pt200_sl100"]
PRIMARY = "pt100_sl050"
COST = 7.50


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="40,50,10")
    ap.add_argument("--k", type=int, default=500)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    w_dna, w_live, w_prob = [float(x) / 100 for x in args.weights.split(",")]
    k = args.k
    tag = args.tag or f"w{args.weights.replace(',','_')}_k{k}"

    df = pd.read_parquet(OUT / "dna_live_state_rows.parquet")
    # W4: DNA features are all `dna_`-prefixed (no collision with live cols).
    dna_cols = [c for c in df.columns if c.startswith("dna_")]
    live_cols = [c for c in LIVE_COLS if c in df.columns]
    prob_cols = [c for c in df.columns if c.startswith("prob_cluster_")]
    df[dna_cols] = df[dna_cols].fillna(0.0); df[live_cols] = df[live_cols].fillna(0.0)
    print(f"{len(df):,} rows | DNA {len(dna_cols)} Live {len(live_cols)} Prob {len(prob_cols)} | "
          f"weights {w_dna}/{w_live}/{w_prob} k={k}")

    carry = {b: [f"{b}_pt_hit", f"{b}_gross_pnl", f"{b}_reason", f"{b}_bars"] for b in BRACKETS}
    recs = []
    for year in [2022, 2023, 2024, 2025, 2026]:
        q = df[df.year == year]
        db = df[df.year < year] if year < 2025 else df[df.year < 2025]
        if len(q) == 0 or len(db) < k:
            continue
        sdna = RobustScaler().fit(db[dna_cols]); slive = RobustScaler().fit(db[live_cols])
        wd = np.sqrt(w_dna / max(len(dna_cols), 1)); wl = np.sqrt(w_live / max(len(live_cols), 1))
        wp = np.sqrt(w_prob / max(len(prob_cols), 1))
        def feat(d):
            return np.hstack([sdna.transform(d[dna_cols]) * wd,
                              slive.transform(d[live_cols]) * wl,
                              d[prob_cols].values * wp]).astype(np.float32)
        Xdb = feat(db); Xq = feat(q)
        print(f"  year {year}: {len(q):,} queries vs {len(db):,}")
        for bidx in sorted(q.bar_index_in_regime.unique()):
            cm = (db.bar_index_in_regime == bidx).values
            qm = (q.bar_index_in_regime == bidx).values
            if cm.sum() < 10 or qm.sum() == 0:
                continue
            cd = db[cm]; qd = q[qm]
            ak = min(k + 50, cm.sum())
            nn = NearestNeighbors(n_neighbors=ak, algorithm="ball_tree", n_jobs=-1).fit(Xdb[cm])
            _, idx = nn.kneighbors(Xq[qm])
            crid = cd.regime_id.values
            cb = {b: {col: cd[col].values for col in carry[b]} for b in BRACKETS}
            qrid = qd.regime_id.values; qts = qd.bar_ts.values
            for i in range(len(qd)):
                vi = idx[i][crid[idx[i]] != qrid[i]][:k]
                if len(vi) == 0:
                    continue
                row = {"regime_id": qrid[i], "bar_ts": qts[i], "bar_index": int(bidx),
                       "year": year, "is_oos": int(year >= 2025),
                       "cluster_id": int(qd.cluster_id.values[i]) if "cluster_id" in qd else 0}
                for b in BRACKETS:
                    row[f"score_{b}"] = float(cb[b][f"{b}_pt_hit"][vi].mean())
                    row[f"exp_gross_{b}"] = float(cb[b][f"{b}_gross_pnl"][vi].mean())
                    row[f"score_{b}_actual"] = int(qd[f"{b}_pt_hit"].values[i])
                    row[f"gross_{b}_actual"] = float(qd[f"{b}_gross_pnl"].values[i])
                    row[f"reason_{b}_actual"] = int(qd[f"{b}_reason"].values[i])
                    row[f"bars_{b}_actual"] = float(qd[f"{b}_bars"].values[i])
                row["score_failure_risk"] = float((cb[PRIMARY][f"{PRIMARY}_reason"][vi] == 2).mean())
                row["score_expected_net"] = row[f"exp_gross_{PRIMARY}"] - COST
                row["bars_to_flip_actual"] = float(qd["bars_to_regime_flip"].values[i])
                # DNA diagnostics for decile_9_10 (dna_-prefixed after W4)
                for dc in ("dna_pre_30_lr_slope_atr", "dna_pre_15_compression_score", "dna_pre_5_volume_zscore"):
                    row[dc] = float(qd[dc].values[i]) if dc in qd else 0.0
                recs.append(row)
    sc = pd.DataFrame(recs)
    sc.to_parquet(OUT / f"dna_knn_scores_{tag}.parquet", index=False)
    sc.to_parquet(OUT / "dna_knn_scores.parquet", index=False)
    print(f"Saved dna_knn_scores ({len(sc):,}); tag={tag}")

    # ---- calibration with velocity (primary bracket, OOS) ----
    oos = sc[sc.is_oos == 1].copy()
    L = [f"# DNA KNN Calibration — OOS 2025–2026 (weights {args.weights}, k={k})", "",
         f"Tradeable **{PRIMARY}** race calibration. The prior atlas race calibration was FLAT; "
         "the question is whether DNA+live makes it span and pay.", "",
         "| Decile | n | Pred win% | Actual win% | Avg gross$ | Avg net$ | PF | 2025 net$ | 2026 net$ | "
         "Med bars→PT | Med bars→flip |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    if len(oos):
        oos["dec"] = pd.qcut(oos[f"score_{PRIMARY}"], 10, labels=False, duplicates="drop") + 1
        for dec, s in oos.groupby("dec"):
            g = s[f"gross_{PRIMARY}_actual"]; net = g - COST
            pf = net[net > 0].sum() / (-net[net < 0].sum()) if (net < 0).any() else np.inf
            n25 = net[s.year == 2025].sum(); n26 = net[s.year == 2026].sum()
            pt = s.loc[s[f"reason_{PRIMARY}_actual"] == 1, f"bars_{PRIMARY}_actual"]
            L.append(f"| {int(dec)} | {len(s):,} | {s[f'score_{PRIMARY}'].mean()*100:.1f}% | "
                     f"{s[f'score_{PRIMARY}_actual'].mean()*100:.1f}% | ${g.mean():+.2f} | ${net.mean():+.2f} | "
                     f"{pf:.2f} | ${n25:,.0f} | ${n26:,.0f} | {pt.median() if len(pt) else float('nan'):.0f} | "
                     f"{s['bars_to_flip_actual'].median():.0f} |")
        span = oos.groupby("dec")[f"score_{PRIMARY}_actual"].mean()
        rng = (span.max() - span.min()) * 100
        L += ["", f"**Actual race-win span across deciles: {rng:.1f}pp.** "
              + ("Non-flat — DNA+live ranks the tradeable race; check the policy gate for money."
                 if rng > 3 else "FLAT — DNA+live does NOT rank the tradeable race (same failure as the prior atlas).")]
    (OUT / "dna_calibration.md").write_text("\n".join(L), encoding="utf-8")
    print("Wrote dna_calibration.md")


if __name__ == "__main__":
    main()

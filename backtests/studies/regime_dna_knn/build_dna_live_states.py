"""Branch 3 — assemble DNA + soft-archetype + live-state rows.

Soft archetype (amendment 3): a walk-forward multiclass classifier maps frozen
DNA -> cluster label; predict_proba gives the soft vector (year Y trained on
strictly-prior years; OOS on 2021-2024). Bars 1-4 of a regime use a uniform 1/K
vector; bars 5+ use the classifier proba. Hard label kept for reporting only.

Then merge: atlas live-state rows + frozen DNA + soft probs + the new 5-bracket
race labels -> dna_live_state_rows.parquet.

    python studies/regime_dna_knn/build_dna_live_states.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import RobustScaler

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
ATLAS = Path("studies/regime_state_transition_atlas/results")
META = {"regime_id", "regime_start_ts", "year", "direction", "atr_norm_at_flip",
        "time_of_day_bucket", "is_rth", "minutes_since_rth_open", "minutes_to_rth_close", "cluster_id"}
LIVE_COLS = ["current_pnl_atr", "mfe_so_far_atr", "mae_so_far_atr", "pullback_from_peak_atr",
             "progress_efficiency_so_far", "mfe_mae_ratio_so_far", "continuation_count_so_far",
             "bars_since_last_continuation", "consecutive_no_continuation_bars", "regime_5s_aligned",
             "5s_flip_count_since_1m_start", "ema9_slope_atr", "ema21_slope_atr",
             "distance_to_ema9_atr", "volume_percentile_20"]


def main():
    dna = pd.read_parquet(OUT / "regime_dna.parquet")
    clu = pd.read_parquet(OUT / "regime_dna_clusters.parquet", columns=["regime_id", "cluster_id"])
    dna = dna.merge(clu, on="regime_id", how="inner")
    feats = [c for c in dna.columns if c not in META and dna[c].dtype.kind in "fi"]
    K = int(dna.cluster_id.nunique())
    print(f"{len(dna):,} regimes, {len(feats)} DNA feats, K={K}")

    # walk-forward soft archetype classifier
    prob_rows = []
    classes = sorted(dna.cluster_id.unique())
    for Y in range(2021, 2027):
        if Y == 2021:
            continue   # W3: no prior-year data -> 2021 stays uniform 1/K (no self-fit leak)
        tr = dna[dna.year < Y] if Y < 2025 else dna[dna.year < 2025]
        te = dna[dna.year == Y]
        if len(tr) == 0 or len(te) == 0:
            continue
        Xtr = tr[feats].copy(); Xte = te[feats].copy()
        for c in feats:
            lo, hi = Xtr[c].quantile(0.01), Xtr[c].quantile(0.99)
            Xtr[c] = Xtr[c].clip(lo, hi).fillna(0.0); Xte[c] = Xte[c].clip(lo, hi).fillna(0.0)
        sc = RobustScaler().fit(Xtr)
        clf = LogisticRegression(max_iter=1000).fit(sc.transform(Xtr), tr.cluster_id)
        P = clf.predict_proba(sc.transform(Xte))
        for i, rid in enumerate(te.regime_id.values):
            row = {"regime_id": rid}
            for j, cl in enumerate(clf.classes_):
                row[f"prob_cluster_{cl}"] = P[i, j]
            prob_rows.append(row)
    probs = pd.DataFrame(prob_rows)
    for cl in classes:
        if f"prob_cluster_{cl}" not in probs:
            probs[f"prob_cluster_{cl}"] = 0.0
    pcols = [f"prob_cluster_{cl}" for cl in classes]
    probs[pcols] = probs[pcols].fillna(1.0 / K)

    # Robust cross-build joins: this DNA build used a different lead-in than the
    # atlas, so regime_id INDICES differ. bar_ts (1m close) and regime_start_ts
    # (flip close) are build-independent, so we key on those and use the ATLAS
    # state_rows regime_id as canonical throughout.
    dna_full = dna.merge(probs[["regime_id"] + pcols], on="regime_id", how="left")  # dna already has cluster_id
    dna_full[pcols] = dna_full[pcols].fillna(1.0 / K)
    rename_map = {f: f"dna_{f}" for f in feats}   # W4: prefix DNA feats so they never collide with live cols
    dna_carry = (dna_full[["regime_start_ts"] + feats + pcols + ["cluster_id"]]
                 .rename(columns=rename_map).drop_duplicates("regime_start_ts"))

    sr = pd.read_parquet(ATLAS / "state_rows.parquet")
    keep = ["regime_id", "bar_ts", "regime_start_ts", "bar_index_in_regime", "year", "direction"] + \
           [c for c in LIVE_COLS if c in sr.columns]
    sr = sr[keep]
    lab = pd.read_parquet(OUT / "dna_race_labels.parquet")
    df = sr.merge(lab.drop(columns=["regime_id", "bar_index_in_regime", "direction"], errors="ignore"),
                  on="bar_ts", how="inner")                       # per-bar key
    df = df.merge(dna_carry, on="regime_start_ts", how="inner")   # per-regime key
    df[pcols] = df[pcols].fillna(1.0 / K)
    # bars 1-4 uniform
    early = df.bar_index_in_regime <= 4
    df.loc[early, pcols] = 1.0 / K
    df.to_parquet(OUT / "dna_live_state_rows.parquet", index=False)
    print(f"Saved dna_live_state_rows.parquet ({len(df):,} rows, {df.shape[1]} cols)")


if __name__ == "__main__":
    main()

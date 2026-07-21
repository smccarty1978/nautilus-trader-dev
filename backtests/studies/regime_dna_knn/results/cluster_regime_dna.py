"""Branch 2 — DNA archetype clustering (frozen DNA only; no post-flip outcomes).

Winsorize 1/99 (edges fit on the 2021-2024 discovery set only), RobustScaler,
KMeans k-sweep 4-16 by silhouette. KMeans fit on discovery; applied unchanged to
OOS (no leakage). Stability audit per archetype: yearly prevalence, yearly outcome
profile, drift. Outcomes are joined ONLY for description (not used in clustering).

    python studies/regime_dna_knn/cluster_regime_dna.py [--k 0]
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
ATLAS = Path("studies/regime_state_transition_atlas/results")
META = {"regime_id", "regime_start_ts", "year", "direction", "atr_norm_at_flip",
        "time_of_day_bucket", "is_rth", "minutes_since_rth_open", "minutes_to_rth_close"}


def dna_feature_cols(df):
    return [c for c in df.columns if c not in META and df[c].dtype.kind in "fi"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--k", type=int, default=0)
    args = ap.parse_args()
    df = pd.read_parquet(OUT / "regime_dna.parquet")
    feats = dna_feature_cols(df)
    print(f"{len(df):,} regimes, {len(feats)} DNA features")

    disc = df[df.year < 2025].copy()
    edges = {}
    Xd = disc[feats].copy()
    for c in feats:
        lo, hi = Xd[c].quantile(0.01), Xd[c].quantile(0.99)
        edges[c] = (lo, hi)
        Xd[c] = Xd[c].clip(lo, hi).fillna(0.0)
    scaler = RobustScaler().fit(Xd)
    Xs = scaler.transform(Xd)

    if args.k <= 0:
        rs = np.random.RandomState(42)
        samp = rs.choice(len(Xs), min(12000, len(Xs)), replace=False)
        best_k, best_s = 8, -1
        for k in range(4, 17):
            km = KMeans(k, n_init=4, random_state=42).fit(Xs[samp])
            s = silhouette_score(Xs[samp], km.labels_)
            print(f"  k={k} sil={s:.3f}")
            if s > best_s:
                best_k, best_s = k, s
        k = best_k
    else:
        k = args.k
    km = KMeans(k, n_init=10, random_state=42).fit(Xs)
    disc["cluster_id"] = km.labels_
    print(f"k={k}")

    oos = df[df.year >= 2025].copy()
    if len(oos):
        Xo = oos[feats].copy()
        for c in feats:
            lo, hi = edges[c]
            Xo[c] = Xo[c].clip(lo, hi).fillna(0.0)
        oos["cluster_id"] = km.predict(scaler.transform(Xo))
        final = pd.concat([disc, oos], ignore_index=True)
    else:
        final = disc
    final.to_parquet(OUT / "regime_dna_clusters.parquet", index=False)

    # outcomes for description, keyed by build-independent regime_start_ts
    # (atlas regime_id indices differ from this build's; final has regime_start_ts).
    sr = pd.read_parquet(ATLAS / "state_rows.parquet",
                         columns=["regime_id", "regime_start_ts", "bar_index_in_regime",
                                  "mfe_so_far_atr", "mae_so_far_atr"])
    id2start = sr[["regime_id", "regime_start_ts"]].drop_duplicates()
    oc = sr.groupby("regime_start_ts").agg(duration=("bar_index_in_regime", "max"),
                                           mfe=("mfe_so_far_atr", "max"),
                                           mae=("mae_so_far_atr", "max")).reset_index()
    fl = pd.read_parquet(ATLAS / "forward_labels.parquet",
                         columns=["regime_id", "bar_ts", "future_mfe_from_here_atr",
                                  "forward_pnl_to_regime_exit_dollars"])
    fl = fl.merge(id2start, on="regime_id", how="left")
    bar1 = fl.sort_values("bar_ts").groupby("regime_start_ts").first()
    oc = oc.merge(bar1[["future_mfe_from_here_atr", "forward_pnl_to_regime_exit_dollars"]],
                  on="regime_start_ts", how="left")
    rep = final.merge(oc, on="regime_start_ts", how="left")

    L = [f"# DNA Archetype Report (k={k}, discovery 2021–2024)", "",
         "Clustered on frozen pre-flip DNA ONLY. Outcomes below are descriptive joins "
         "(NOT used in clustering). Clean-trend = MFE>2 & MAE<1; Chop = MFE<1 & MAE<1.", "",
         "## Stability audit — yearly prevalence (%)",
         "| Archetype | " + " | ".join(str(y) for y in range(2021, 2027)) + " | drift(max−min) |",
         "| --- | " + " | ".join("---" for _ in range(7)) + " |"]
    prof = []
    for cid in sorted(final.cluster_id.unique()):
        sub = rep[rep.cluster_id == cid]
        shares = []
        for y in range(2021, 2027):
            tot = (rep.year == y).sum()
            shares.append(100 * (sub.year == y).sum() / tot if tot else 0.0)
        drift = max(shares) - min(shares)
        L.append(f"| {cid} | " + " | ".join(f"{s:.1f}" for s in shares) + f" | {drift:.1f} |")
        prof.append((cid, len(sub), sub["mfe"].mean(), sub["mae"].mean(), sub["duration"].mean(),
                     sub["forward_pnl_to_regime_exit_dollars"].mean(),
                     100 * ((sub.mfe > 2) & (sub.mae < 1)).mean(),
                     100 * ((sub.mfe < 1) & (sub.mae < 1)).mean(), drift))
    L += ["", "## Archetype outcome profile (descriptive)",
          "| Archetype | n | % | Avg MFE | Avg MAE | Avg dur | Avg fwd PnL$ | %CleanTrend | %Chop | Drift |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for cid, n, mfe, mae, dur, pnl, ct, ch, drift in sorted(prof, key=lambda x: -x[2]):
        L.append(f"| {cid} | {n:,} | {100*n/len(rep):.1f}% | {mfe:.2f} | {mae:.2f} | {dur:.0f} | "
                 f"${pnl:+.0f} | {ct:.0f}% | {ch:.0f}% | {drift:.1f} |")
    L += ["", f"Archetypes with drift < 3pp are structurally stable across 2021–2026; "
          "higher-drift clusters mutate/disappear and should not be trusted as recurring shapes."]
    (OUT / "dna_archetype_report.md").write_text("\n".join(L), encoding="utf-8")
    print(f"Wrote dna_archetype_report.md; clusters={k}")


if __name__ == "__main__":
    main()

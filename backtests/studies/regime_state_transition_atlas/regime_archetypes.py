"""Branch B — Regime Archetype Discovery. Cluster WHOLE 1m regimes into recurring
shapes (opening drive / grind / chop / explosive / exhaustion ...), then cross-
reference with the KNN atlas scores to explain the Decile-9/10 rollover.

Discovery uses full-regime (retrospective) descriptors — it labels what KIND of
regime each was. Whether the archetype is identifiable EARLY (causally, by bar
3-5) is tested separately at the end; that is what determines tradeability.

    python studies/regime_state_transition_atlas/regime_archetypes.py [--k 0]
(k=0 -> sweep 6..14 and pick best silhouette.)
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_state_transition_atlas/results")

CLUSTER_FEATS = [
    "length_bars", "total_mfe_atr", "total_mae_atr", "efficiency", "mfe_mae_ratio",
    "num_pullbacks", "largest_pullback_atr", "continuation_count", "flip_count_5s",
    "mean_ema9_dist", "mean_ema9_slope", "slope_decay", "mean_vol_vs20", "bar1_return_atr",
]
# Early (causal, bars<=5) features for the identifiability test
EARLY_FEATS = [
    "e_bar1_return_atr", "e_mfe5", "e_mae5", "e_pullback5", "e_cont5",
    "e_flip5", "e_ema9_slope5", "e_ema9_dist5", "e_vol5",
]


def build_regime_vectors():
    sr = pd.read_parquet(OUT / "state_rows.parquet")
    fl = pd.read_parquet(OUT / "forward_labels.parquet",
                         columns=["regime_id", "bar_ts", "future_mfe_from_here_atr",
                                  "future_mae_from_here_atr", "remaining_regime_bars"])
    df = pd.merge(sr, fl, on=["regime_id", "bar_ts"])
    df["pb_start"] = ((df["made_continuation_this_bar"] == 0) &
                      (df["prior_bar_made_continuation"] == 1)).astype(int)
    df["reg_len_est"] = df["bar_index_in_regime"] + df["remaining_regime_bars"]

    bar1 = df[df.bar_index_in_regime == 1].set_index("regime_id")
    g = df.groupby("regime_id")
    vec = pd.DataFrame(index=bar1.index)
    vec["year"] = bar1["year"]
    vec["direction"] = bar1["direction"]
    vec["is_rth"] = bar1["is_rth"]
    vec["bar1_confirmed"] = bar1["bar1_confirmed_flag"]
    vec["bar1_return_atr"] = bar1["bar_return_atr"]
    vec["length_bars"] = g["reg_len_est"].max()
    vec["total_mfe_atr"] = bar1["future_mfe_from_here_atr"]
    vec["total_mae_atr"] = bar1["future_mae_from_here_atr"]
    denom = vec["total_mfe_atr"] + vec["total_mae_atr"]
    vec["efficiency"] = np.where(denom > 1e-9, vec["total_mfe_atr"] / denom, 0.0)
    vec["mfe_mae_ratio"] = np.where(vec["total_mae_atr"] > 1e-9,
                                    vec["total_mfe_atr"] / vec["total_mae_atr"], 0.0)
    vec["num_pullbacks"] = g["pb_start"].sum()
    vec["largest_pullback_atr"] = g["max_pullback_depth_so_far_atr"].max()
    vec["continuation_count"] = g["continuation_count_so_far"].max()
    vec["flip_count_5s"] = g["5s_flip_count_since_1m_start"].max()
    vec["mean_ema9_dist"] = g["distance_to_ema9_atr"].mean()
    vec["mean_ema9_slope"] = g["ema9_slope_atr"].mean()
    # slope decay: early slope (bar<=3) minus late slope (last third)
    early = df[df.bar_index_in_regime <= 3].groupby("regime_id")["ema9_slope_atr"].mean()
    late = df.sort_values("bar_index_in_regime").groupby("regime_id")["ema9_slope_atr"].last()
    vec["slope_decay"] = (early - late).reindex(vec.index).fillna(0.0)
    vec["mean_vol_vs20"] = g["bar_volume_vs_20avg"].mean()

    # Early causal features (bars 1..5 only) for identifiability test
    e = df[df.bar_index_in_regime <= 5].groupby("regime_id")
    vec["e_bar1_return_atr"] = bar1["bar_return_atr"]
    vec["e_mfe5"] = e["mfe_so_far_atr"].max()
    vec["e_mae5"] = e["mae_so_far_atr"].max()
    vec["e_pullback5"] = e["max_pullback_depth_so_far_atr"].max()
    vec["e_cont5"] = e["continuation_count_so_far"].max()
    vec["e_flip5"] = e["5s_flip_count_since_1m_start"].max()
    vec["e_ema9_slope5"] = e["ema9_slope_atr"].mean()
    vec["e_ema9_dist5"] = e["distance_to_ema9_atr"].mean()
    vec["e_vol5"] = e["bar_volume_vs_20avg"].mean()

    vec = vec.reset_index()
    for c in CLUSTER_FEATS + EARLY_FEATS:
        vec[c] = vec[c].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    # Winsorize at [1,99] pct to neutralize low-entry-ATR normalization blow-ups
    # (a handful of regimes show 90-ATR MFE / negative MAE / multi-thousand-bar
    # length). These artifacts otherwise form their own degenerate clusters and
    # stretch the StandardScaler. Length is also hard-capped (>120 bars = 2h is
    # an overnight/gap artifact, not a tradeable intraday regime shape).
    vec["length_bars"] = vec["length_bars"].clip(upper=120)
    for c in CLUSTER_FEATS + EARLY_FEATS:
        lo, hi = vec[c].quantile(0.01), vec[c].quantile(0.99)
        if hi > lo:
            vec[c] = vec[c].clip(lo, hi)
    return vec


def name_archetype(row):
    mfe, length, eff, pb = row["total_mfe_atr"], row["length_bars"], row["efficiency"], row["num_pullbacks"]
    if mfe >= 4.0 and length <= 14:
        return "Explosive/Opening drive"
    if mfe >= 3.0 and eff >= 0.80:
        return "Clean trend"
    if mfe >= 2.0 and length >= 16:
        return "Grind trend"
    if mfe >= 2.0 and pb >= 3:
        return "Pullback trend"
    if mfe < 1.2 and eff < 0.6:
        return "Chop/reversal"
    if mfe < 2.0:
        return "Weak/stall"
    return "Mixed trend"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=0)
    args = ap.parse_args()
    vec = build_regime_vectors()
    print(f"Built {len(vec):,} regime vectors.")

    X = StandardScaler().fit_transform(vec[CLUSTER_FEATS].values)

    if args.k <= 0:
        best_k, best_s = None, -1
        samp = np.random.RandomState(0).choice(len(X), min(20000, len(X)), replace=False)
        for k in range(6, 15):
            km = KMeans(n_clusters=k, n_init=4, random_state=0).fit(X)
            s = silhouette_score(X[samp], km.labels_[samp])
            print(f"  k={k} silhouette={s:.3f}")
            if s > best_s:
                best_k, best_s = k, s
        k = best_k
    else:
        k = args.k
    km = KMeans(n_clusters=k, n_init=8, random_state=0).fit(X)
    vec["cluster"] = km.labels_
    print(f"Chosen k={k}")

    # Profile clusters
    prof = vec.groupby("cluster").agg(
        n=("cluster", "size"),
        length_bars=("length_bars", "mean"),
        total_mfe_atr=("total_mfe_atr", "mean"),
        total_mae_atr=("total_mae_atr", "mean"),
        efficiency=("efficiency", "mean"),
        num_pullbacks=("num_pullbacks", "mean"),
        largest_pullback_atr=("largest_pullback_atr", "mean"),
        flip_count_5s=("flip_count_5s", "mean"),
        slope_decay=("slope_decay", "mean"),
        bar1_return_atr=("bar1_return_atr", "mean"),
        pct_long=("direction", lambda s: (s == 1).mean() * 100),
    ).reset_index()
    prof["pct"] = prof["n"] / len(vec) * 100
    prof["archetype"] = prof.apply(name_archetype, axis=1)
    prof = prof.sort_values("total_mfe_atr", ascending=False).reset_index(drop=True)
    name_map = dict(zip(prof["cluster"], prof["archetype"]))
    vec["archetype"] = vec["cluster"].map(name_map)

    # Year stability of each cluster's prevalence
    yr_share = (vec.groupby(["year", "cluster"]).size() /
                vec.groupby("year").size()).unstack(fill_value=0.0) * 100

    # Cross-reference with KNN atlas scores
    sc = pd.read_parquet(OUT / "scored_state_rows.parquet",
                         columns=["regime_id", "year", "is_oos", "bar_index_in_regime",
                                  "score_opportunity", "actual_forward_pnl",
                                  "remaining_regime_bars"])
    sc = sc.merge(vec[["regime_id", "cluster", "archetype"]], on="regime_id", how="inner")
    oos = sc[sc.is_oos == 1].copy()
    # archetype-level score / pnl
    arch_xref = oos.groupby("archetype").agg(
        bars=("archetype", "size"),
        mean_score=("score_opportunity", "mean"),
        mean_fwd_pnl=("actual_forward_pnl", "mean"),
    ).reset_index().sort_values("mean_score", ascending=False)
    # decile -> archetype mix + maturity (explains 9/10 rollover)
    oos["dec"] = pd.qcut(oos["score_opportunity"], 10, labels=False, duplicates="drop") + 1
    dec_rows = []
    for dec, s in oos.groupby("dec"):
        top_arch = s["archetype"].value_counts(normalize=True)
        dec_rows.append(dict(decile=int(dec), n=len(s),
                             mean_bar_idx=s["bar_index_in_regime"].mean(),
                             mean_rem_bars=s["remaining_regime_bars"].mean(),
                             mean_fwd_pnl=s["actual_forward_pnl"].mean(),
                             top_archetype=top_arch.index[0],
                             top_share=top_arch.iloc[0] * 100))
    dec_df = pd.DataFrame(dec_rows)

    # Early identifiability: can bars 1-5 predict the archetype? (time split: IS train, OOS test)
    vec_is = vec[vec.year < 2025]
    vec_oos = vec[vec.year >= 2025]
    rf = RandomForestClassifier(n_estimators=120, max_depth=12, n_jobs=-1, random_state=0)
    rf.fit(vec_is[EARLY_FEATS].values, vec_is["cluster"].values)
    oos_acc = rf.score(vec_oos[EARLY_FEATS].values, vec_oos["cluster"].values)
    baseline = vec_oos["cluster"].value_counts(normalize=True).max()

    # PCA 2D scatter
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        p2 = PCA(n_components=2, random_state=0).fit_transform(X)
        fig, axp = plt.subplots(figsize=(9, 7))
        samp = np.random.RandomState(1).choice(len(X), min(30000, len(X)), replace=False)
        scat = axp.scatter(p2[samp, 0], p2[samp, 1], c=km.labels_[samp], cmap="tab20", s=3, alpha=0.4)
        axp.set_title(f"Regime archetypes (k={k}) — PCA projection")
        axp.set_xlabel("PC1"); axp.set_ylabel("PC2")
        fig.savefig(OUT / "regime_archetypes_pca.png", dpi=110, bbox_inches="tight")
        plt.close(fig)
        png = True
    except Exception as ex:
        png = False
        print("PCA plot skipped:", ex)

    vec.to_parquet(OUT / "regime_archetypes.parquet", index=False)

    # ---- report ----
    L = [f"# Regime Archetype Discovery (k={k} KMeans on whole-regime shape)", "",
         f"{len(vec):,} 1m regimes (2021–2026) clustered on {len(CLUSTER_FEATS)} full-regime "
         "shape descriptors (length, total MFE/MAE, efficiency, pullbacks, 5s flips, slope decay, "
         "volume, opening-bar return). Discovery is **retrospective** (uses the whole regime). "
         "Early causal identifiability is tested in §4.", "",
         "## 1. Archetypes", "",
         "| Archetype | % | n | Avg len | Avg MFE | Avg MAE | Eff | Pullbacks | 5s flips | Slope decay | %Long |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for _, r in prof.iterrows():
        L.append(f"| {r['archetype']} (c{int(r['cluster'])}) | {r['pct']:.1f}% | {int(r['n']):,} | "
                 f"{r['length_bars']:.0f} | {r['total_mfe_atr']:.2f} | {r['total_mae_atr']:.2f} | "
                 f"{r['efficiency']:.2f} | {r['num_pullbacks']:.1f} | {r['flip_count_5s']:.1f} | "
                 f"{r['slope_decay']:+.3f} | {r['pct_long']:.0f}% |")
    L.append("")
    L.append("## 2. Atlas cross-reference — archetype vs KNN score & forward PnL (OOS)")
    L.append("| Archetype | OOS bars | Mean score_opportunity | Mean actual fwd PnL ($) |")
    L.append("| --- | --- | --- | --- |")
    for _, r in arch_xref.iterrows():
        L.append(f"| {r['archetype']} | {int(r['bars']):,} | {r['mean_score']:.3f} | ${r['mean_fwd_pnl']:+.2f} |")
    L.append("")
    L.append("## 3. Does archetype explain the Decile-9-positive / Decile-10-negative rollover?")
    L.append("| Score decile | n | Mean bar idx | Mean rem. bars | Mean fwd PnL ($) | Dominant archetype (share) |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for _, r in dec_df.iterrows():
        L.append(f"| {int(r['decile'])} | {int(r['n']):,} | {r['mean_bar_idx']:.1f} | "
                 f"{r['mean_rem_bars']:.1f} | ${r['mean_fwd_pnl']:+.2f} | "
                 f"{r['top_archetype']} ({r['top_share']:.0f}%) |")
    L.append("")
    L.append("## 4. Are archetypes identifiable EARLY (causally, bars 1–5)? — the tradeability bridge")
    L.append(f"RandomForest on bars-1–5 features only, trained on 2021–2024, tested on 2025–2026.")
    L.append(f"- OOS archetype accuracy: **{oos_acc*100:.1f}%** vs majority-class baseline {baseline*100:.1f}% "
             f"({len(prof)} classes).")
    lift = oos_acc - baseline
    L.append(f"- Lift over baseline: **{lift*100:+.1f}pp**. "
             + ("Archetypes ARE partly recognizable early → a causal 'which regime am I in?' "
                "classifier is worth building." if lift > 0.08 else
                "Weak early separability → archetypes are mostly defined by what happens LATER; "
                "recognizing them in real time (the tradeable form) is the hard open problem."))
    L.append("")
    if png:
        L.append("![PCA projection](regime_archetypes_pca.png)")
    L.append("")
    L.append("## Year-stability of archetype prevalence (%)")
    L.append("| Year | " + " | ".join(f"c{c}" for c in yr_share.columns) + " |")
    L.append("| --- | " + " | ".join("---" for _ in yr_share.columns) + " |")
    for yr, row in yr_share.iterrows():
        L.append(f"| {int(yr)} | " + " | ".join(f"{v:.0f}" for v in row.values) + " |")

    (OUT / "regime_archetypes.md").write_text("\n".join(L), encoding="utf-8")
    print(f"Archetypes: {len(prof)}; early OOS acc {oos_acc*100:.1f}% vs base {baseline*100:.1f}%")
    print("Wrote results/regime_archetypes.md + regime_archetypes.parquet")


if __name__ == "__main__":
    main()

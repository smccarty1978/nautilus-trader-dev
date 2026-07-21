"""Phase 3 -- feature importance: repeated permutation importance on the
regime-stratified 2025 sample, monthly stability, grouped-by-family and
grouped-by-canonical-runtime-source importance, threshold-side importance,
correlation clusters. Produces the two required raw/canonical ranking CSVs.
"""
from __future__ import annotations

import json
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from common import (ARTIFACTS, RESULTS, CONFIG, SRC_STUDY, WORK, TARGET,
                     classify_feature, DUMMY_SUFFIX_RE, sha256_obj)

SEED = 42
CKPT = WORK / "phase3_checkpoint.json"


def _load_ckpt() -> dict:
    return json.loads(CKPT.read_text()) if CKPT.exists() else {}


def _save_ckpt(ckpt: dict) -> None:
    CKPT.write_text(json.dumps(ckpt))


def canonical_base(name: str) -> str:
    m = DUMMY_SUFFIX_RE.match(name)
    return m.group(1) if m else name


def main() -> None:
    t0 = time.time()
    model = joblib.load(ARTIFACTS / "F3_695_baseline" / "model.joblib")
    feats = json.loads((ARTIFACTS / "F3_695_baseline" / "feature_list.json").read_text())["ordered_features"]

    dev_df = pd.read_parquet(SRC_STUDY / "_work" / "prepared_2025.parquet")
    dev_df["month"] = pd.to_datetime(dev_df["observation_time"], unit="ns", utc=True).dt.month
    row_idx = np.load(CONFIG / "importance_sample_row_index.npy")
    sample = dev_df.loc[row_idx]
    X_sample, y_sample = sample[feats], sample[TARGET].astype(int).to_numpy()
    print(f"sample: {len(sample)} rows, loaded in {time.time()-t0:.1f}s")

    ckpt = _load_ckpt()

    # 1. Overall permutation importance on the full regime-stratified sample.
    if "importances_mean" in ckpt:
        print("overall permutation importance: loaded from checkpoint")
        importances_mean = np.array(ckpt["importances_mean"])
        importances_std = np.array(ckpt["importances_std"])
    else:
        t1 = time.time()
        r_overall = permutation_importance(model, X_sample, y_sample, n_repeats=5,
                                           random_state=SEED, scoring="roc_auc", n_jobs=1)
        print(f"overall permutation importance done in {time.time()-t1:.1f}s")
        importances_mean, importances_std = r_overall.importances_mean, r_overall.importances_std
        ckpt["importances_mean"] = importances_mean.tolist()
        ckpt["importances_std"] = importances_std.tolist()
        _save_ckpt(ckpt)

    class _R:
        pass
    r_overall = _R()
    r_overall.importances_mean, r_overall.importances_std = importances_mean, importances_std

    # 2. Monthly stability: per-month permutation importance -> rank correlation vs overall.
    overall_rank = pd.Series(r_overall.importances_mean, index=feats).rank(ascending=False)
    if "monthly_importance" in ckpt:
        print("monthly stability: loaded from checkpoint")
        monthly_importance = {int(k): v for k, v in ckpt["monthly_importance"].items()}
    else:
        t2 = time.time()
        monthly_importance = {}
        for month, m_df in sample.groupby("month"):
            Xm, ym = m_df[feats], m_df[TARGET].astype(int).to_numpy()
            if len(np.unique(ym)) < 2:
                continue
            rm = permutation_importance(model, Xm, ym, n_repeats=3, random_state=SEED,
                                        scoring="roc_auc", n_jobs=1)
            monthly_importance[int(month)] = rm.importances_mean.tolist()
        print(f"monthly stability done in {time.time()-t2:.1f}s")
        ckpt["monthly_importance"] = monthly_importance
        _save_ckpt(ckpt)

    monthly_rank_corr = {}
    monthly_ranks = pd.DataFrame(index=feats)
    for month, vals in monthly_importance.items():
        m_rank = pd.Series(vals, index=feats).rank(ascending=False)
        monthly_ranks[int(month)] = m_rank
        monthly_rank_corr[int(month)] = float(overall_rank.corr(m_rank, method="spearman"))
    print(f"mean spearman-vs-overall={np.mean(list(monthly_rank_corr.values())):.3f}")
    monthly_rank_median = monthly_ranks.median(axis=1)
    monthly_rank_worst = monthly_ranks.max(axis=1)

    # 3. Threshold-side importance: top-5% and top-2.5% bands, by FULL-population quantile.
    if "threshold_importance" in ckpt:
        print("threshold-side importance: loaded from checkpoint")
        threshold_importance = ckpt["threshold_importance"]
    else:
        t3 = time.time()
        full_scores = model.predict_proba(dev_df[feats])[:, 1]
        q95 = np.quantile(full_scores, 0.95)
        q975 = np.quantile(full_scores, 0.975)
        sample_scores = model.predict_proba(X_sample)[:, 1]
        threshold_importance = {}
        for label, q in (("top5pct", q95), ("top2_5pct", q975)):
            mask = sample_scores >= q
            n_rows = int(mask.sum())
            if n_rows < 200 or len(np.unique(y_sample[mask])) < 2:
                threshold_importance[label] = {"n_rows": n_rows, "importances_mean": None,
                                               "note": "insufficient rows/class-diversity in sample band"}
                continue
            rt = permutation_importance(model, X_sample[mask], y_sample[mask], n_repeats=3,
                                        random_state=SEED, scoring="roc_auc", n_jobs=1)
            threshold_importance[label] = {"n_rows": n_rows, "importances_mean": rt.importances_mean.tolist()}
        print(f"threshold-side importance done in {time.time()-t3:.1f}s")
        ckpt["threshold_importance"] = threshold_importance
        _save_ckpt(ckpt)

    # 4. Grouped importance by family / canonical runtime source.
    inv = pd.read_csv(RESULTS / "f3_feature_inventory_v2.csv").set_index("name")
    family_of = inv["family"].to_dict()
    imp_series = pd.Series(r_overall.importances_mean, index=feats)
    by_family = imp_series.groupby(lambda f: family_of.get(f, "UNKNOWN")).sum().sort_values(ascending=False)
    canonical_of = {f: canonical_base(f) for f in feats}
    by_canonical = imp_series.groupby(lambda f: canonical_of[f]).sum().sort_values(ascending=False)
    n_unique_canonical = len(set(canonical_of.values()))

    # 5. Correlation/substitutability clusters (Spearman, on the sample).
    # Zero-variance columns in this sample (e.g. features that never vary within
    # the regime-stratified 30k rows) produce NaN correlations with everything,
    # including a NaN on their own diagonal -- treat as "uncorrelated with
    # everything" (distance=1) rather than crashing linkage on non-finite input.
    t5 = time.time()
    corr = X_sample.corr(method="spearman")
    n_nan_features = int(corr.isna().all(axis=1).sum())
    corr = corr.fillna(0.0)
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import squareform
    dist = (1 - corr.abs()).clip(lower=0)
    np.fill_diagonal(dist.values, 0)
    dist_vals = dist.values
    dist_vals[~np.isfinite(dist_vals)] = 1.0
    np.fill_diagonal(dist_vals, 0)
    # symmetrize defensively (fillna could have broken exact symmetry at
    # floating-point precision, which squareform requires)
    dist_vals = (dist_vals + dist_vals.T) / 2.0
    condensed = squareform(dist_vals, checks=False)
    Z = linkage(condensed, method="average")
    cluster_ids = fcluster(Z, t=0.15, criterion="distance")
    clusters: dict[int, list[str]] = {}
    for feat, cid in zip(feats, cluster_ids):
        clusters.setdefault(int(cid), []).append(feat)
    multi_member_clusters = {k: v for k, v in clusters.items() if len(v) > 1}
    print(f"correlation clustering done in {time.time()-t5:.1f}s, "
          f"{len(multi_member_clusters)} multi-member clusters out of {len(clusters)} total, "
          f"{n_nan_features} zero-variance-in-sample features treated as uncorrelated")
    (RESULTS / "feature_correlation_groups.json").write_text(json.dumps({
        "method": "1 - |spearman correlation| distance, average linkage, cutoff=0.15",
        "n_clusters_total": len(clusters), "n_multi_member_clusters": len(multi_member_clusters),
        "clusters": clusters,
    }, indent=2))

    # 6. Raw column ranking (top 100).
    rows = []
    for fi, feat in enumerate(feats):
        d = inv.loc[feat] if feat in inv.index else None
        rows.append({
            "feature_name": feat, "family": family_of.get(feat, "UNKNOWN"),
            "importance_mean": float(r_overall.importances_mean[fi]),
            "importance_std": float(r_overall.importances_std[fi]),
            "monthly_rank_median": float(monthly_rank_median.get(feat, np.nan)),
            "monthly_rank_worst": float(monthly_rank_worst.get(feat, np.nan)),
            "threshold_side_impact_top5pct": (
                float(threshold_importance["top5pct"]["importances_mean"][fi])
                if threshold_importance["top5pct"]["importances_mean"] else None),
            "threshold_side_impact_top2_5pct": (
                float(threshold_importance["top2_5pct"]["importances_mean"][fi])
                if threshold_importance["top2_5pct"]["importances_mean"] else None),
            "in_registry": bool(d["in_registry"]) if d is not None else None,
            "registry_match_kind": d["registry_match_kind"] if d is not None else None,
            "canonical_source_feature": canonical_of[feat],
            "live_tracker_exists": bool(d["live_tracker_exists"]) if d is not None else None,
            "timing_status": d["timing_status"] if d is not None else None,
            "source_timeframe": d.get("source_timeframe") if d is not None else None,
            "window": None, "window_unit": None, "reset_policy": None,
            "normalizer": None, "snapshot_anchor": d.get("snapshot_anchor") if d is not None else None,
        })
    rank_df = pd.DataFrame(rows).sort_values("importance_mean", ascending=False).reset_index(drop=True)
    rank_df.insert(0, "rank", np.arange(1, len(rank_df) + 1))
    rank_df.to_csv(RESULTS / "full_raw_feature_ranking_695.csv", index=False)
    rank_df.head(100).to_csv(RESULTS / "top_100_raw_feature_columns.csv", index=False)

    canon_df = by_canonical.reset_index()
    canon_df.columns = ["canonical_feature", "importance_sum"]
    canon_df.insert(0, "rank", np.arange(1, len(canon_df) + 1))
    canon_df["family"] = canon_df["canonical_feature"].map(
        lambda c: family_of.get(c, family_of.get(next((f for f in feats if canonical_of[f] == c), ""), "UNKNOWN")))
    canon_df.to_csv(RESULTS / "top_canonical_runtime_sources.csv", index=False)

    # rank-correlation vs the existing (uniform-sample) evidence from Phase 1, as a sanity cross-check.
    existing = pd.read_csv(SRC_STUDY / "results" / "feature_importance.csv")
    existing_f3_gbt = existing[(existing["feature_set"] == "F3_volume_delta_plus_price_levels")
                               & (existing["model"] == "gbt")].set_index("feature")["coefficient"]
    cross_check_corr = imp_series.rank(ascending=False).corr(
        existing_f3_gbt.reindex(feats).rank(ascending=False), method="spearman")

    summary = {
        "n_model_columns": len(feats),
        "n_unique_canonical_runtime_calculations": n_unique_canonical,
        "by_family_importance_sum": by_family.to_dict(),
        "monthly_rank_correlation_vs_overall": monthly_rank_corr,
        "mean_monthly_rank_correlation": float(np.mean(list(monthly_rank_corr.values()))),
        "threshold_importance_band_sizes": {k: v["n_rows"] for k, v in threshold_importance.items()},
        "cross_check_spearman_vs_existing_uniform_sample_evidence": (
            float(cross_check_corr) if not pd.isna(cross_check_corr) else None),
        "runtime_s": round(time.time() - t0, 1),
    }
    (RESULTS / "phase3_importance_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"Phase 3 total runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

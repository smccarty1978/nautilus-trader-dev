"""Model-free information-content diagnostics per gate x feature family x
label, on the first-eligible-per-regime surface (the deployable-candidate
framing). No thresholds selected, no model trained here.

Per feature: AUC (oriented so >=0.5 always means "more separating"), Cohen's
d, computed per-year then aggregated (mean/std across years = stability).
Decile monotonicity computed on the pooled (all 6 years) surface per gate,
using the Spearman correlation between a feature's decile rank and the
label rate within that decile (captures both direction and smoothness).
Family-level rollups aggregate the per-feature stats.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK, RESULTS = HERE / "_work", HERE / "results"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from features.registry import FEATURE_REGISTRY  # noqa: E402

GATES = ["gate_a_120s", "bridge_180s", "gate_b_240s"]
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
LABELS = ["bearish_flip_within_300s", "bearish_flip_within_300s_and_followthrough_1A",
          "adverse_move_1p25A_before_bearish_flip"]


def feature_family(feat: str, f0_feats: set[str]) -> str:
    if feat in f0_feats:
        return "existing"
    base = feat.split("__")[0] if "__" in feat else feat
    d = FEATURE_REGISTRY.get(feat) or FEATURE_REGISTRY.get(base)
    if d is not None:
        return "volume_delta" if d.family == "ohlcv_est_delta" else "price_level"
    raise RuntimeError(f"could not classify feature family for {feat!r}")


def cohens_d(x: np.ndarray, y_bin: np.ndarray) -> float:
    a, b = x[y_bin == 1], x[y_bin == 0]
    if len(a) < 2 or len(b) < 2:
        return np.nan
    n1, n2 = len(a), len(b)
    pooled_std = np.sqrt(((n1 - 1) * a.std(ddof=1) ** 2 + (n2 - 1) * b.std(ddof=1) ** 2) / (n1 + n2 - 2))
    if pooled_std == 0 or not np.isfinite(pooled_std):
        return np.nan
    return float((a.mean() - b.mean()) / pooled_std)


def oriented_auc(x: np.ndarray, y_bin: np.ndarray) -> float:
    mask = np.isfinite(x)
    if mask.sum() < 20 or y_bin[mask].sum() == 0 or y_bin[mask].sum() == mask.sum():
        return np.nan
    auc = roc_auc_score(y_bin[mask], x[mask])
    return max(auc, 1 - auc)


def main() -> None:
    feature_sets = json.loads((WORK / "feature_sets.json").read_text(encoding="utf-8"))
    f0_feats = set(feature_sets["F0_existing_only"])
    all_feats = feature_sets["F3_volume_delta_plus_price_levels"]
    family_of = {f: feature_family(f, f0_feats) for f in all_feats}

    per_feature_rows = []
    decile_rows = []

    for gate in GATES:
        year_frames = {y: pd.read_parquet(WORK / f"first_eligible_{gate}_{y}.parquet",
                                          columns=all_feats + LABELS + ["year"])
                       for y in YEARS}
        pooled = pd.concat(year_frames.values(), ignore_index=True)

        for label in LABELS:
            y_pooled = pooled[label].astype(int).to_numpy()
            for feat in all_feats:
                x_pooled = pooled[feat].to_numpy(dtype=float) if pooled[feat].dtype != object else None
                if x_pooled is None:
                    continue
                aucs, ds = [], []
                for y in YEARS:
                    df_y = year_frames[y]
                    xy = df_y[feat].to_numpy(dtype=float)
                    yy = df_y[label].astype(int).to_numpy()
                    aucs.append(oriented_auc(xy, yy))
                    ds.append(cohens_d(xy, yy))
                aucs_arr = np.array(aucs, dtype=float)
                ds_arr = np.array(ds, dtype=float)

                mask = np.isfinite(x_pooled)
                if mask.sum() >= 50:
                    dec = pd.qcut(pd.Series(x_pooled[mask]), 10, labels=False, duplicates="drop")
                    rate_by_dec = pd.Series(y_pooled[mask]).groupby(dec).mean()
                    if len(rate_by_dec) >= 3:
                        rho, _ = spearmanr(rate_by_dec.index, rate_by_dec.values)
                    else:
                        rho = np.nan
                else:
                    rho = np.nan

                per_feature_rows.append({
                    "gate": gate, "label": label, "feature": feat, "family": family_of[feat],
                    "auc_pooled": oriented_auc(x_pooled, y_pooled),
                    "auc_mean_across_years": float(np.nanmean(aucs_arr)),
                    "auc_std_across_years": float(np.nanstd(aucs_arr)),
                    "auc_min_across_years": float(np.nanmin(aucs_arr)) if np.isfinite(aucs_arr).any() else np.nan,
                    "auc_max_across_years": float(np.nanmax(aucs_arr)) if np.isfinite(aucs_arr).any() else np.nan,
                    "cohens_d_pooled": cohens_d(x_pooled, y_pooled),
                    "cohens_d_mean_across_years": float(np.nanmean(ds_arr)),
                    "decile_monotonicity_spearman_rho": float(rho) if pd.notna(rho) else np.nan,
                })

    per_feature = pd.DataFrame(per_feature_rows)
    per_feature.to_csv(WORK / "feature_separation_per_feature.csv", index=False)

    family_summary = (per_feature.groupby(["gate", "label", "family"])
                      .agg(n_features=("feature", "size"),
                           mean_auc_pooled=("auc_pooled", "mean"),
                           median_auc_pooled=("auc_pooled", "median"),
                           n_features_auc_ge_055=("auc_pooled", lambda s: int((s >= 0.55).sum())),
                           mean_abs_cohens_d=("cohens_d_pooled", lambda s: float(np.nanmean(np.abs(s)))),
                           mean_auc_stability_std=("auc_std_across_years", "mean"),
                           mean_decile_monotonicity_abs_rho=(
                               "decile_monotonicity_spearman_rho", lambda s: float(np.nanmean(np.abs(s)))),
                           )
                      .reset_index())
    family_summary.to_csv(RESULTS / "gate_feature_separation.csv", index=False)
    print(family_summary.to_string(index=False))


if __name__ == "__main__":
    main()

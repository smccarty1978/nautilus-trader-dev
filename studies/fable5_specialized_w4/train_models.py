"""Train specialized W4 candidate-selection models on 2025-H1, select on 2025-H2.

Structures: A pooled, B side-specific, C side/session (sample-gated), D
hierarchical isotonic recalibration of the frozen w4_score, and the frozen
score-margin baseline. Families and hyperparameters are predeclared in
SPEC.md; per-structure selection uses 2025-H2 independent-candidate net PnL
at the top-30% retention band only. 2026 is never read here.
"""
from __future__ import annotations

import json
import pickle

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import fable5_common as C

CONFIGS = [("logit", {"C": 0.1}), ("logit", {"C": 1.0}),
           ("gbt", {"max_iter": 100}), ("gbt", {"max_iter": 200})]

STRUCTURE_FEATURES = {
    "A_pooled": C.RAW_FEATURES + C.POOLED_CONTEXT,
    "B_side": C.RAW_FEATURES + ["session_flag"],
    "C_side_session": C.RAW_FEATURES,
}


def segment_masks(structure: str, d: pd.DataFrame) -> dict[str, pd.Series]:
    if structure in ("A_pooled", "baseline_w4"):
        return {"ALL": pd.Series(True, index=d.index)}
    if structure in ("B_side", "D_hier"):
        return {s: d.direction.eq(s) for s in ("long_fade", "short_fade")}
    if structure == "C_side_session":
        return {f"{s}_{x}": d.direction.eq(s) & d.session.eq(x)
                for s in ("long_fade", "short_fade") for x in ("ETH", "RTH")}
    raise ValueError(structure)


def make_model(family: str, params: dict):
    if family == "logit":
        return Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(C=params["C"], penalty="l2",
                                       max_iter=2000, random_state=C.SEED)),
        ])
    return HistGradientBoostingClassifier(
        max_depth=3, learning_rate=0.05, max_iter=params["max_iter"],
        random_state=C.SEED)


def fit_structure(structure: str, family: str, params: dict,
                  train: pd.DataFrame) -> dict | None:
    """Fit one model per segment; None if any C cell fails the sample gate."""
    if structure == "D_hier":
        segments = {}
        for name, mask in segment_masks(structure, train).items():
            g = train[mask]
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(g["w4_score"].to_numpy(float),
                    g["label_net_positive"].to_numpy(float))
            segments[name] = iso
        return {"segments": segments, "family": "isotonic", "params": {}}
    if structure == "baseline_w4":
        return {"segments": {"ALL": None}, "family": "frozen_margin", "params": {}}
    features = STRUCTURE_FEATURES[structure]
    segments = {}
    for name, mask in segment_masks(structure, train).items():
        g = train[mask]
        pos = int((g.label_net_positive == 1).sum())
        neg = int((g.label_net_positive == 0).sum())
        if structure == "C_side_session" and (pos < C.MIN_CELL_POS
                                              or neg < C.MIN_CELL_NEG):
            return None
        model = make_model(family, params)
        model.fit(g[features].to_numpy(float),
                  g["label_net_positive"].to_numpy(int))
        segments[name] = model
    return {"segments": segments, "family": family, "params": params,
            "features": features}


def score_structure(structure: str, fitted: dict, d: pd.DataFrame) -> np.ndarray:
    out = np.full(len(d), np.nan)
    positions = pd.Series(np.arange(len(d)), index=d.index)
    for name, mask in segment_masks(structure, d).items():
        g = d[mask]
        if not len(g):
            continue
        if name not in fitted["segments"]:
            raise RuntimeError(f"unscored segment {name} for {structure}")
        model = fitted["segments"][name]
        idx = positions[mask.to_numpy()].to_numpy()
        if structure == "baseline_w4":
            out[idx] = g["score_margin"].to_numpy(float)
        elif structure == "D_hier":
            out[idx] = model.predict(g["w4_score"].to_numpy(float))
        else:
            out[idx] = model.predict_proba(
                g[fitted["features"]].to_numpy(float))[:, 1]
    if np.isnan(out).any():
        raise RuntimeError(f"unscored candidate rows for {structure}")
    return out


def retention_cutoffs(structure: str, dev: pd.DataFrame,
                      scores: np.ndarray) -> dict:
    cutoffs = {}
    s = pd.Series(scores, index=dev.index)
    for name, mask in segment_masks(structure, dev).items():
        seg = s[mask]
        if not len(seg):
            raise RuntimeError(f"empty dev segment {name}")
        cutoffs[name] = {f"top_{int(b * 100)}": float(np.percentile(
            seg.to_numpy(float), 100 * (1 - b))) for b in C.RETENTION_BANDS}
    return cutoffs


def selection_pnl(structure: str, dev: pd.DataFrame, scores: np.ndarray,
                  band: float) -> float:
    """Independent-candidate dev net PnL at one retention band."""
    s = pd.Series(scores, index=dev.index)
    total = 0.0
    for name, mask in segment_masks(structure, dev).items():
        seg = s[mask]
        if not len(seg):
            continue
        cutoff = float(np.percentile(seg.to_numpy(float), 100 * (1 - band)))
        accepted = dev[mask & (s >= cutoff)]
        total += float(accepted.net_pnl_usd.sum())
    return total


def metric_rows(structure: str, config_label: str, dev: pd.DataFrame,
                scores: np.ndarray, selected: bool) -> list[dict]:
    rows = []
    s = pd.Series(scores, index=dev.index)
    groups = {"ALL": pd.Series(True, index=dev.index)}
    groups.update({x: dev.direction.eq(x) for x in ("long_fade", "short_fade")})
    groups.update({x: dev.session.eq(x) for x in ("ETH", "RTH")})
    for name, mask in segment_masks("C_side_session", dev).items():
        groups[name] = mask
    for name, mask in groups.items():
        g = dev[mask]
        y = g["label_net_positive"].to_numpy(float)
        p = s[mask].to_numpy(float)
        if len(np.unique(y)) < 2:
            continue
        clip = np.clip(p, 0.0, 1.0)
        rows.append({"structure": structure, "config": config_label,
                     "segment": name, "window": "2025_H2_dev",
                     "count": len(g), "base_rate": float(y.mean()),
                     "roc_auc": float(roc_auc_score(y, p)),
                     "pr_auc": float(average_precision_score(y, p)),
                     "brier": float(brier_score_loss(y, clip))
                     if structure != "baseline_w4" else np.nan,
                     "selected": selected})
    return rows


def decile_rows(structure: str, dev: pd.DataFrame,
                scores: np.ndarray) -> list[dict]:
    rows = []
    s = pd.Series(scores, index=dev.index)
    for name, mask in segment_masks(structure, dev).items():
        g = dev[mask].copy()
        if len(g) < 50:
            continue
        seg_scores = s[mask]
        g["decile"] = pd.qcut(seg_scores.rank(method="first"), 10,
                              labels=range(1, 11)).astype(int)
        for decile, x in g.groupby("decile"):
            rows.append({"structure": structure, "segment": name,
                         "window": "2025_H2_dev", "decile": int(decile),
                         "count": len(x),
                         "mean_score": float(seg_scores[x.index].mean()),
                         "net_positive_rate": float(x.label_net_positive.mean()),
                         "mean_net_pnl_usd": float(x.net_pnl_usd.mean()),
                         "total_net_pnl_usd": float(x.net_pnl_usd.sum()),
                         "prestop_rate": float(
                             (x.exit_reason == "preflip_policy_stop").mean()),
                         "alignment_rate": float(x.label_alignment_5m.mean())})
    return rows


def calibration_rows(structure: str, dev: pd.DataFrame,
                     scores: np.ndarray) -> list[dict]:
    if structure == "baseline_w4":
        return []
    rows = []
    p = np.clip(scores, 0.0, 1.0)
    bins = np.clip((p * 10).astype(int), 0, 9)
    y = dev["label_net_positive"].to_numpy(float)
    pnl = dev["net_pnl_usd"].to_numpy(float)
    for b in range(10):
        m = bins == b
        if m.sum() == 0:
            continue
        rows.append({"structure": structure, "window": "2025_H2_dev",
                     "bin": b, "count": int(m.sum()),
                     "mean_predicted": float(p[m].mean()),
                     "realized_rate": float(y[m].mean()),
                     "mean_net_pnl_usd": float(pnl[m].mean())})
    return rows


def importance_rows(structure: str, fitted: dict,
                    dev: pd.DataFrame) -> list[dict]:
    if structure in ("baseline_w4", "D_hier"):
        return []
    rows = []
    features = fitted["features"]
    for name, mask in segment_masks(structure, dev).items():
        g = dev[mask]
        if len(g) < 100:
            continue
        model = fitted["segments"][name]
        x = g[features].to_numpy(float)
        y = g["label_net_positive"].to_numpy(int)
        if fitted["family"] == "logit":
            coefs = np.abs(model.named_steps["clf"].coef_[0])
            order = np.argsort(coefs)[::-1][:20]
            for rank, i in enumerate(order, 1):
                rows.append({"structure": structure, "segment": name,
                             "method": "abs_std_coef", "rank": rank,
                             "feature": features[i],
                             "importance": float(coefs[i])})
        else:
            imp = permutation_importance(model, x, y, n_repeats=3,
                                         random_state=C.SEED,
                                         scoring="roc_auc")
            order = np.argsort(imp.importances_mean)[::-1][:20]
            for rank, i in enumerate(order, 1):
                rows.append({"structure": structure, "segment": name,
                             "method": "permutation_auc", "rank": rank,
                             "feature": features[i],
                             "importance": float(imp.importances_mean[i])})
    return rows


def stability_rows(train: pd.DataFrame,
                   importance: pd.DataFrame) -> list[dict]:
    """Single-feature AUC per H1 month for the top-20 pooled features."""
    top = importance[importance.structure == "A_pooled"]
    features = list(dict.fromkeys(top.sort_values("rank").feature))[:20]
    months = pd.to_datetime(train.candidate_time, unit="ns", utc=True).dt.month
    rows = []
    for feature in features:
        for month, g in train.groupby(months):
            y = g["label_net_positive"].to_numpy(float)
            v = g[feature].to_numpy(float)
            ok = np.isfinite(v)
            if len(np.unique(y[ok])) < 2 or ok.sum() < 100:
                continue
            rows.append({"structure": "A_pooled", "segment": "ALL",
                         "method": "single_feature_auc_month",
                         "feature": feature, "month": int(month),
                         "auc": float(roc_auc_score(y[ok], v[ok])),
                         "count": int(ok.sum())})
    return rows


def main() -> None:
    C.ensure_dirs()
    C.require_authorization()
    C.freeze_inputs_or_verify()
    if C.FIRST_2026_OPEN_PATH.exists():
        raise RuntimeError("cannot refreeze after 2026 has been opened")
    d = pd.read_parquet(C.dataset_path(2025))
    labeled = d[d.replayable].copy()
    train = labeled[(labeled.window == "2025_H1_train")
                    & ~labeled.purged_from_train].copy()
    dev = labeled[labeled.window == "2025_H2_dev"].copy()
    if train.empty or dev.empty:
        raise RuntimeError("empty train/dev window")
    if int(train.candidate_time.max()) >= C.BOUNDARY_NS:
        raise RuntimeError("train window crosses boundary")
    quintiles = np.percentile(train.net_pnl_usd.to_numpy(float), [20, 80])

    selection_table, fitted_selected = [], {}
    metrics, deciles, calibration, importance = [], [], [], []
    insufficient = []
    for structure in C.STRUCTURES:
        candidates = []
        configs = (CONFIGS if structure in STRUCTURE_FEATURES
                   else [(None, {})])
        for family, params in configs:
            fitted = fit_structure(structure, family, params, train)
            if fitted is None:
                insufficient.append(structure)
                break
            scores = score_structure(structure, fitted, dev)
            pnl = selection_pnl(structure, dev, scores, C.SELECTION_BAND)
            label = (f"{family}_{json.dumps(params, sort_keys=True)}"
                     if family else fitted["family"])
            candidates.append({"structure": structure, "config": label,
                               "dev_top30_net_pnl_usd": pnl,
                               "fitted": fitted, "scores": scores})
        if structure in insufficient:
            continue
        best = max(candidates, key=lambda c: c["dev_top30_net_pnl_usd"])
        for c in candidates:
            selected = c is best
            selection_table.append({k: c[k] for k in
                                    ("structure", "config",
                                     "dev_top30_net_pnl_usd")}
                                   | {"selected": selected})
            metrics.extend(metric_rows(structure, c["config"], dev,
                                       c["scores"], selected))
        fitted_selected[structure] = {
            "fitted": best["fitted"], "config": best["config"],
            "cutoffs": retention_cutoffs(structure, dev, best["scores"])}
        deciles.extend(decile_rows(structure, dev, best["scores"]))
        calibration.extend(calibration_rows(structure, dev, best["scores"]))
        importance.extend(importance_rows(structure, best["fitted"], dev))

    importance_frame = pd.DataFrame(importance)
    stability = stability_rows(train, importance_frame) if len(importance_frame) else []

    bundle = {"structures": fitted_selected, "quintile_edges": list(quintiles),
              "raw_features": C.RAW_FEATURES, "seed": C.SEED,
              "insufficient": insufficient}
    with C.BUNDLE_PATH.open("wb") as f:
        pickle.dump(bundle, f)
    pd.DataFrame(selection_table).to_parquet(
        C.WORK / "selection_table.parquet", index=False)
    pd.DataFrame(metrics).to_parquet(C.WORK / "model_metrics_dev.parquet",
                                     index=False)
    pd.DataFrame(deciles).to_parquet(C.WORK / "decile_lift_dev.parquet",
                                     index=False)
    pd.DataFrame(calibration).to_parquet(C.WORK / "calibration_dev.parquet",
                                         index=False)
    pd.concat([importance_frame, pd.DataFrame(stability)],
              ignore_index=True).to_parquet(
        C.WORK / "feature_importance.parquet", index=False)
    manifest = {
        "status": "FROZEN_ON_2025_ONLY",
        "train_window": "2025_H1_train_purged", "dev_window": "2025_H2_dev",
        "train_rows": len(train), "dev_rows": len(dev),
        "boundary_ns": C.BOUNDARY_NS,
        "selection_rule": "dev top-30% independent net PnL; ties by config order",
        "quintile_edges_usd": list(map(float, quintiles)),
        "insufficient_sample_structures": insufficient,
        "selected": {s: {"config": v["config"], "cutoffs": v["cutoffs"]}
                     for s, v in fitted_selected.items()},
        "bundle_sha256": C.sha256_file(C.BUNDLE_PATH),
        "dataset_2025_sha256": C.sha256_file(C.dataset_path(2025)),
    }
    C.MODEL_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2),
                                     encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in
                      ("status", "train_rows", "dev_rows",
                       "insufficient_sample_structures")}, indent=2))
    print(pd.DataFrame(selection_table)[
        ["structure", "config", "dev_top30_net_pnl_usd", "selected"]])


if __name__ == "__main__":
    main()

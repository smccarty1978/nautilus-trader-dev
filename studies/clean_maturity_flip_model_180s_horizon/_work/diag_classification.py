"""TRAIN-only classification + timing diagnostics: frozen 180s winner vs frozen 300s parent.

Recomputes metrics from FROZEN model predictions only -- no retraining of either study.
LONG  <=> regime_direction == -1  (matches parent's LONG_* arms exactly)
SHORT <=> regime_direction == +1
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, joblib

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
sys.path.insert(0, str(ROOT))
from research.analysis.metrics import classification_bundle

S180 = ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"
SPAR = ROOT / "studies" / "clean_maturity_flip_model_rolling_productivity"
JOIN = ["observation_ts", "regime_start_ns", "checkpoint_index"]
ARM_C = ["arrival_velocity", "arrival_acceleration", "ema_slope",
         "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr", "prior_1m_regime_range_atr",
         "prior_5m_regime_efficiency", "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr",
         "rolling_300s_retention_ratio", "rolling_300s_current_progress_atr",
         "rolling_300s_max_progress_atr", "rolling_300s_giveback_atr"]
DIR_SIGN = {"LONG": -1, "SHORT": 1}
MATURITY_EDGES = [(0, 300), (300, 600), (600, 900), (900, 1800), (1800, 10**9)]


def maturity_bucket(age):
    for lo, hi in MATURITY_EDGES:
        if lo <= age < hi:
            return f"{lo}-{hi}" if hi < 10**8 else f"{lo}+"
    return "na"


def _mb(y, s):
    b = classification_bundle(pd.Series(np.asarray(y)), np.asarray(s, dtype=float))
    return {k: (b[k]["value"] if b[k]["status"] == "ok" else None) for k in ("roc_auc", "pr_auc", "brier", "positive_rate", "sample_count")}


def load_180s():
    c = pd.read_parquet(S180 / "artifacts" / "train_candidates_merged.parquet")
    o = pd.read_parquet(S180 / "artifacts" / "train_observations_merged.parquet")
    df = c.merge(o[JOIN + ["regime_direction", "target_flip_within_horizon", "disposition",
                           "time_to_flip_seconds"]], on=JOIN, how="inner", validate="one_to_one")
    df = df[df.disposition.isin(["LABELED_POSITIVE", "LABELED_NEGATIVE"])].copy()
    df["y"] = df.target_flip_within_horizon.astype(int)
    df["mbucket"] = df.regime_age_seconds.map(maturity_bucket)
    return df


def load_parent():
    c = pd.read_parquet(SPAR / "artifacts" / "train_candidates_repaired_merged.parquet")
    o = pd.read_parquet(SPAR / "artifacts" / "train_observations_repaired_merged.parquet")
    df = c.merge(o[JOIN + ["regime_direction", "target_flip_within_horizon", "disposition",
                           "time_to_flip_seconds"]], on=JOIN, how="inner", validate="one_to_one")
    df = df[df.disposition.isin(["LABELED_POSITIVE", "LABELED_NEGATIVE"])].copy()
    df["y"] = df.target_flip_within_horizon.astype(int)
    df["mbucket"] = df.regime_age_seconds.map(maturity_bucket)
    return df


def frozen_180s_scores(df_dir):
    dr = "long" if (df_dir.regime_direction.iloc[0] == -1) else "short"
    fz = json.loads((S180 / "artifacts" / f"train_experiment_freeze_{dr}.json").read_text())
    mid = fz["model_artifacts"][0]["model_id"]
    est = joblib.load(S180 / "artifacts" / "models" / f"{mid}.joblib")["C"]["estimator"]
    return est.predict_proba(df_dir[ARM_C])[:, 1], fz["thresholds"]["C"]


def frozen_parent_scores(df_dir, direction):
    m = joblib.load(SPAR / "artifacts" / "train_fitted_models.joblib")
    rec = m[f"{direction}_C"]
    feats = rec["provenance"]["ordered_features"]
    s = rec["estimator"].predict_proba(df_dir[feats])[:, 1]
    fz = json.loads((SPAR / "artifacts" / "train_experiment_freeze_repaired.json").read_text())
    return s, fz["thresholds"][f"{direction}_C"]


def crossing_stats(df_dir, scores, thr_val, horizon_label):
    m = df_dir.assign(score=scores)
    hi = m[m.score >= thr_val]
    out = {
        "n_crossings": int(len(hi)),
        "retained_frac": float(len(hi) / len(m)) if len(m) else None,
        "flip_rate": float(hi.y.mean()) if len(hi) else None,
        "base_rate": float(m.y.mean()),
        "precision_lift": (float(hi.y.mean() / m.y.mean()) if len(hi) and m.y.mean() > 0 else None),
        "median_seconds_to_flip": float(hi.loc[hi.y == 1, "time_to_flip_seconds"].median()) if (hi.y == 1).any() else None,
    }
    return out


def _thr(v):
    return float(v["threshold"]) if isinstance(v, dict) else float(v)


def direction_block(d180, dpar, direction):
    s180, thr180 = frozen_180s_scores(d180)
    spar, thrpar = frozen_parent_scores(dpar, direction)
    block = {
        "base_rate_180s": float(d180.y.mean()),
        "base_rate_300s": float(dpar.y.mean()),
        "n_180s": int(len(d180)), "n_300s": int(len(dpar)),
        "classification_180s_full_train": _mb(d180.y, s180),
        "classification_300s_full_train": _mb(dpar.y, spar),
        "by_maturity_180s": {b: _mb(g.y, s180[d180.mbucket == b]) for b, g in d180.groupby("mbucket")},
        "by_maturity_300s": {b: _mb(g.y, spar[dpar.mbucket == b]) for b, g in dpar.groupby("mbucket")},
        "score_pct_180s": {p: float(np.quantile(s180, p / 100)) for p in (50, 75, 90, 95, 97.5, 99)},
        "score_pct_300s": {p: float(np.quantile(spar, p / 100)) for p in (50, 75, 90, 95, 97.5, 99)},
        "thresholds_180s": {k: _thr(v) for k, v in thr180.items()},
        "thresholds_300s": {k: _thr(v) for k, v in thrpar.items()},
        "crossing_180s": {k: crossing_stats(d180, s180, _thr(v), "180s") for k, v in thr180.items()},
        "crossing_300s": {k: crossing_stats(dpar, spar, _thr(v), "300s") for k, v in thrpar.items()},
    }
    # deltas (180s - 300s) on full-train classification
    c1, c3 = block["classification_180s_full_train"], block["classification_300s_full_train"]
    block["delta_180s_minus_300s"] = {k: (c1[k] - c3[k]) if (c1[k] is not None and c3[k] is not None) else None
                                      for k in ("roc_auc", "pr_auc", "brier", "positive_rate")}
    return block


def main():
    d180 = load_180s(); dpar = load_parent()
    result = {"generated_at": "2026-08-29", "note": "TRAIN-only; both models frozen; parent recomputed from frozen predictions"}
    for direction in ("LONG", "SHORT"):
        sign = DIR_SIGN[direction]
        result[direction] = direction_block(
            d180[d180.regime_direction == sign].reset_index(drop=True),
            dpar[dpar.regime_direction == sign].reset_index(drop=True),
            direction,
        )
    (S180 / "artifacts" / "diag_classification_180s_vs_300s.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({d: {"180s_pr_auc": result[d]["classification_180s_full_train"]["pr_auc"],
                          "300s_pr_auc": result[d]["classification_300s_full_train"]["pr_auc"],
                          "180s_roc_auc": result[d]["classification_180s_full_train"]["roc_auc"],
                          "300s_roc_auc": result[d]["classification_300s_full_train"]["roc_auc"],
                          "180s_brier": result[d]["classification_180s_full_train"]["brier"],
                          "300s_brier": result[d]["classification_300s_full_train"]["brier"],
                          "base_180": result[d]["base_rate_180s"], "base_300": result[d]["base_rate_300s"]}
                      for d in ("LONG", "SHORT")}, indent=2))


if __name__ == "__main__":
    main()

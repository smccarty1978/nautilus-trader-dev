"""Phase 1 — train, score, and evaluate short-RTH entry-selection models.

Target: hit_pre_alignment_stop (1 = bad, hit the 1.25A pre-alignment stop).
Score: stop_survival_score = 1 - P(hit_pre_alignment_stop); rank/retain by
HIGHEST stop_survival_score. Train on 2021-2024, retention-band cutoffs are
computed on 2025 (dev) and frozen before being applied to 2026 (sealed).

Three model families:
  A. Regularized logistic regression (train-only median impute + standardize).
  B. HistGradientBoostingClassifier, capped depth 3 (native NaN handling).
  C. Frozen W4 score/rank comparator, 2025-2026 only -- NOT trained on
     2021-2024 (per SPEC, this family is never retrained).

Layer 1: row-level diagnostics on all eligible rows (descriptive only, NOT
deployable PnL). Layer 2: one-entry-per-regime deployable policy (primary
economic comparison). Both are computed here; Layer 3 (fixed-807 overlay)
and final selection/attribution are separate scripts that consume this
script's score outputs.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKFILL = ROOT / "studies" / "short_rth_entry_surface_backfill"
WORK, RESULTS, AUDIT = HERE / "_work", HERE / "results", HERE / "audit"

for p in (ROOT / "studies" / "regime_sequence_chop_context",):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from train_weakness_model import CENTER_FEATS, SEQUENCE_FEATS  # noqa: E402

FEATURE_COLS = CENTER_FEATS + SEQUENCE_FEATS
TARGET = "hit_pre_alignment_stop"
BANDS = [1.00, 0.85, 0.70, 0.50, 0.35, 0.20]
NQ_MULT, COST = 20.0, 10.0
RANDOM_STATE = 42


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def load_split(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df = df[df["label_available"]].reset_index(drop=True)
    df[TARGET] = df[TARGET].astype(int)
    return df


def fit_logistic(train_X: pd.DataFrame, train_y: np.ndarray):
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    Xi = imputer.fit_transform(train_X)
    Xs = scaler.fit_transform(Xi)
    model = LogisticRegression(penalty="l2", C=1.0, max_iter=2000, random_state=RANDOM_STATE)
    model.fit(Xs, train_y)
    return model, imputer, scaler


def score_logistic(model, imputer, scaler, X: pd.DataFrame) -> np.ndarray:
    Xi = imputer.transform(X)
    Xs = scaler.transform(Xi)
    return model.predict_proba(Xs)[:, 1]


def fit_gbt(train_X: pd.DataFrame, train_y: np.ndarray):
    model = HistGradientBoostingClassifier(
        max_depth=3, learning_rate=0.05, max_iter=200, random_state=RANDOM_STATE)
    model.fit(train_X, train_y)
    return model


def precision_recall_at_band(y: np.ndarray, retained: np.ndarray) -> dict:
    """Retained = predicted-negative (predicted to avoid the stop)."""
    n_retained = int(retained.sum())
    n_total = len(y)
    n_actual_negative = int((y == 0).sum())
    tp_neg = int(((retained) & (y == 0)).sum())  # retained AND actually avoided
    precision = tp_neg / n_retained if n_retained else np.nan
    recall = tp_neg / n_actual_negative if n_actual_negative else np.nan
    return {"precision_avoid_stop": precision, "recall_avoid_stop": recall,
            "n_retained": n_retained, "n_total": n_total}


def calibration_deciles(score: np.ndarray, y: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame({"score": score, "y": y})
    df["decile"] = pd.qcut(df["score"], 10, labels=False, duplicates="drop")
    return df.groupby("decile").agg(
        n=("y", "size"), mean_score=("score", "mean"), actual_hit_rate=("y", "mean")
    ).reset_index()


def feature_importance_logistic(model, imputer, scaler) -> pd.DataFrame:
    coefs = model.coef_[0]
    return pd.DataFrame({"feature": FEATURE_COLS, "coefficient": coefs,
                        "abs_coefficient": np.abs(coefs)}).sort_values(
        "abs_coefficient", ascending=False)


def feature_importance_gbt(model, X_sample: pd.DataFrame, y_sample: np.ndarray) -> pd.DataFrame:
    from sklearn.inspection import permutation_importance
    r = permutation_importance(model, X_sample, y_sample, n_repeats=3,
                                random_state=RANDOM_STATE, scoring="roc_auc", n_jobs=-1)
    return pd.DataFrame({"feature": FEATURE_COLS, "importance_mean": r.importances_mean,
                        "importance_std": r.importances_std}).sort_values(
        "importance_mean", ascending=False)


def main() -> None:
    t0 = time.time()
    train_df = load_split(WORK / "train_2021_2024_featured.parquet")
    dev_df = load_split(WORK / "labeled_featured_2025.parquet")
    test_df = load_split(WORK / "labeled_featured_2026.parquet")

    train_X, train_y = train_df[FEATURE_COLS], train_df[TARGET].to_numpy()
    dev_X, dev_y = dev_df[FEATURE_COLS], dev_df[TARGET].to_numpy()
    test_X, test_y = test_df[FEATURE_COLS], test_df[TARGET].to_numpy()

    print(f"train={len(train_df):,} dev={len(dev_df):,} test={len(test_df):,} "
          f"train_hit_rate={train_y.mean():.4f} dev={dev_y.mean():.4f} test={test_y.mean():.4f}")

    # --- Model A: logistic regression ---
    lr_model, lr_imputer, lr_scaler = fit_logistic(train_X, train_y)
    lr_score_train = score_logistic(lr_model, lr_imputer, lr_scaler, train_X)
    lr_score_dev = score_logistic(lr_model, lr_imputer, lr_scaler, dev_X)
    lr_score_test = score_logistic(lr_model, lr_imputer, lr_scaler, test_X)

    # --- Model B: HistGradientBoosting ---
    gbt_model = fit_gbt(train_X, train_y)
    gbt_score_train = gbt_model.predict_proba(train_X)[:, 1]
    gbt_score_dev = gbt_model.predict_proba(dev_X)[:, 1]
    gbt_score_test = gbt_model.predict_proba(test_X)[:, 1]

    train_df["score_logreg"] = lr_score_train
    dev_df["score_logreg"] = lr_score_dev
    test_df["score_logreg"] = lr_score_test
    train_df["score_gbt"] = gbt_score_train
    dev_df["score_gbt"] = gbt_score_dev
    test_df["score_gbt"] = gbt_score_test

    # --- Model C: frozen W4 comparator, 2025-2026 only ---
    w4_25 = pd.read_parquet(
        ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair" / "results"
        / "CODEX_5_X_repaired_w4_scores_2025.parquet",
        columns=["regime_start_ns", "observation_time", "direction", "w4_score"])
    w4_26 = pd.read_parquet(
        ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair" / "results"
        / "CODEX_5_X_repaired_w4_scores_2026.parquet",
        columns=["regime_start_ns", "observation_time", "direction", "w4_score"])
    dev_df = dev_df.merge(
        w4_25[w4_25.direction == 1].drop(columns="direction"),
        on=["regime_start_ns", "observation_time"], how="left", validate="one_to_one")
    test_df = test_df.merge(
        w4_26[w4_26.direction == 1].drop(columns="direction"),
        on=["regime_start_ns", "observation_time"], how="left", validate="one_to_one")
    if dev_df["w4_score"].isna().any() or test_df["w4_score"].isna().any():
        raise RuntimeError("W4 comparator score join incomplete")

    # stop_survival_score for each model: higher = better (lower predicted stop risk)
    for split_df, name in ((train_df, "train"), (dev_df, "dev"), (test_df, "test")):
        split_df["stop_survival_score_logreg"] = 1 - split_df["score_logreg"]
        split_df["stop_survival_score_gbt"] = 1 - split_df["score_gbt"]
    # W4 comparator: higher w4_score = stronger candidate under the ORIGINAL design
    # (crossing UPWARD triggers entry) -- retain by highest w4_score, same convention.
    dev_df["stop_survival_score_w4"] = dev_df["w4_score"]
    test_df["stop_survival_score_w4"] = test_df["w4_score"]

    # --- Diagnostics ---
    diag_rows = []
    for name, tr_s, dv_s, te_s in (
        ("logreg", lr_score_train, lr_score_dev, lr_score_test),
        ("gbt", gbt_score_train, gbt_score_dev, gbt_score_test),
    ):
        diag_rows.append({
            "model": name,
            "train_auc": roc_auc_score(train_y, tr_s),
            "dev_2025_auc": roc_auc_score(dev_y, dv_s),
            "test_2026_auc": roc_auc_score(test_y, te_s),
            "train_score_mean": float(tr_s.mean()), "train_score_std": float(tr_s.std()),
            "dev_score_mean": float(dv_s.mean()), "dev_score_std": float(dv_s.std()),
            "test_score_mean": float(te_s.mean()), "test_score_std": float(te_s.std()),
        })
    diag_rows.append({
        "model": "w4_comparator",
        "train_auc": np.nan,
        "dev_2025_auc": roc_auc_score(dev_y, dev_df["w4_score"]),
        "test_2026_auc": roc_auc_score(test_y, test_df["w4_score"]),
        "train_score_mean": np.nan, "train_score_std": np.nan,
        "dev_score_mean": float(dev_df["w4_score"].mean()), "dev_score_std": float(dev_df["w4_score"].std()),
        "test_score_mean": float(test_df["w4_score"].mean()), "test_score_std": float(test_df["w4_score"].std()),
    })
    pd.DataFrame(diag_rows).to_csv(RESULTS / "model_diagnostics.csv", index=False)

    # precision/recall + calibration deciles at 2025/2026 per model (using
    # each band's 2025-derived cutoff, computed below) -- written after bands.
    calib_frames = []
    for name, dv_s, te_s in (("logreg", lr_score_dev, lr_score_test),
                             ("gbt", gbt_score_dev, gbt_score_test),
                             ("w4_comparator", dev_df["w4_score"].to_numpy(),
                              test_df["w4_score"].to_numpy())):
        c25 = calibration_deciles(dv_s, dev_y)
        c25["model"], c25["split"] = name, "2025"
        c26 = calibration_deciles(te_s, test_y)
        c26["model"], c26["split"] = name, "2026"
        calib_frames.append(c25)
        calib_frames.append(c26)
    pd.concat(calib_frames, ignore_index=True).to_csv(RESULTS / "calibration_deciles.csv", index=False)

    # --- Feature importance ---
    lr_imp = feature_importance_logistic(lr_model, lr_imputer, lr_scaler)
    lr_imp["model"] = "logreg"
    rng = np.random.default_rng(RANDOM_STATE)
    sample_idx = rng.choice(len(dev_X), size=min(20000, len(dev_X)), replace=False)
    gbt_imp = feature_importance_gbt(gbt_model, dev_X.iloc[sample_idx], dev_y[sample_idx])
    gbt_imp["model"] = "gbt"
    pd.concat([lr_imp, gbt_imp], ignore_index=True).to_csv(
        RESULTS / "feature_importance.csv", index=False)

    # --- Retention-band cutoffs, computed on 2025 (dev), frozen ---
    cutoffs = {}
    for model_name, score_col in (("logreg", "stop_survival_score_logreg"),
                                 ("gbt", "stop_survival_score_gbt"),
                                 ("w4_comparator", "stop_survival_score_w4")):
        cutoffs[model_name] = {
            band: float(np.quantile(dev_df[score_col].dropna(), 1 - band)) for band in BANDS
        }
    (WORK / "retention_cutoffs.json").write_text(json.dumps(cutoffs, indent=2), encoding="utf-8")

    # --- Layer 1: row-level diagnostics per model/band/split ---
    layer1_rows = []
    splits = {"train": train_df, "2025": dev_df, "2026": test_df}
    for model_name, score_col in (("logreg", "stop_survival_score_logreg"),
                                 ("gbt", "stop_survival_score_gbt"),
                                 ("w4_comparator", "stop_survival_score_w4")):
        if model_name == "w4_comparator":
            eval_splits = {"2025": dev_df, "2026": test_df}
        else:
            eval_splits = splits
        for split_name, df in eval_splits.items():
            y = df[TARGET].to_numpy()
            for band in BANDS:
                cutoff = cutoffs[model_name][band]
                retained = (df[score_col] >= cutoff).to_numpy()
                pr = precision_recall_at_band(y, retained)
                row = {
                    "model": model_name, "split": split_name, "retention_band": band,
                    "cutoff_score": cutoff, "n_total": len(df), "n_retained": int(retained.sum()),
                    "retention_rate": float(retained.mean()),
                    "hit_rate_retained": float(y[retained].mean()) if retained.any() else np.nan,
                    "hit_rate_all": float(y.mean()),
                    "net_pnl_retained_sum_DESCRIPTIVE_ONLY": float(df.loc[retained, "net_pnl"].sum()),
                    **pr,
                }
                layer1_rows.append(row)
    pd.DataFrame(layer1_rows).to_csv(RESULTS / "retention_band_results.csv", index=False)

    # Persist scored splits for layer2/layer3/selection scripts.
    train_df.to_parquet(WORK / "scored_train.parquet", index=False, compression="zstd")
    dev_df.to_parquet(WORK / "scored_dev_2025.parquet", index=False, compression="zstd")
    test_df.to_parquet(WORK / "scored_test_2026.parquet", index=False, compression="zstd")

    manifest = {
        "runtime_s": round(time.time() - t0, 1),
        "train_rows": len(train_df), "dev_rows": len(dev_df), "test_rows": len(test_df),
        "train_hit_rate": float(train_y.mean()), "dev_hit_rate": float(dev_y.mean()),
        "test_hit_rate": float(test_y.mean()),
        "bands": BANDS,
        "model_diagnostics_summary": diag_rows,
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    (RESULTS / "train_and_evaluate_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print("Model diagnostics:")
    print(pd.DataFrame(diag_rows).to_string(index=False))
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

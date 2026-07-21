"""Phase 1 -- train, score, and evaluate the enriched short-RTH entry-selection
models across four feature sets (F0 existing / F1 volume-delta / F2 price-level
/ F3 combined) and two model families (regularized multinomial logistic
regression, capped-depth HistGradientBoostingClassifier), on the 5-class
`outcome_class` target built in Phase 0.

entry_quality_score = P(opposing_flip_winner) - P(pre_alignment_stop)
                     - 0.25 * P(confirmation_timeout) - 0.50 * P(post_alignment_stop)

Train: 2021-2024. Retention-band cutoffs computed on 2025 (dev), frozen
before being applied unchanged to 2026 (sealed). No 2026 involvement in any
selection or cutoff computation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
WORK, RESULTS = HERE / "_work", HERE / "results"

CLASSES = ["opposing_flip_winner", "opposing_flip_loser", "pre_alignment_stop",
           "confirmation_timeout", "post_alignment_stop"]
SCORE_WEIGHTS = {"opposing_flip_winner": 1.0, "pre_alignment_stop": -1.0,
                 "confirmation_timeout": -0.25, "post_alignment_stop": -0.50}
BANDS = [1.00, 0.85, 0.70, 0.50, 0.35, 0.20]
RANDOM_STATE = 42


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def entry_quality_score(proba: np.ndarray, classes: list[str]) -> np.ndarray:
    score = np.zeros(proba.shape[0], dtype=float)
    for cls, weight in SCORE_WEIGHTS.items():
        idx = classes.index(cls)
        score += weight * proba[:, idx]
    return score


def fit_logistic(train_X: pd.DataFrame, train_y: np.ndarray):
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    Xi = imputer.fit_transform(train_X)
    Xs = scaler.fit_transform(Xi)
    model = LogisticRegression(penalty="l2", C=1.0, max_iter=1000,
                               solver="lbfgs", random_state=RANDOM_STATE)
    model.fit(Xs, train_y)
    return model, imputer, scaler


def score_logistic(model, imputer, scaler, X: pd.DataFrame) -> np.ndarray:
    Xi = imputer.transform(X)
    Xs = scaler.transform(Xi)
    return model.predict_proba(Xs)


def fit_gbt(train_X: pd.DataFrame, train_y: np.ndarray):
    model = HistGradientBoostingClassifier(
        max_depth=3, learning_rate=0.05, max_iter=200, random_state=RANDOM_STATE)
    model.fit(train_X, train_y)
    return model


def per_class_auc(y: np.ndarray, proba: np.ndarray, classes: list[str]) -> dict:
    out = {}
    for i, cls in enumerate(classes):
        y_bin = (y == cls).astype(int)
        if y_bin.sum() == 0 or y_bin.sum() == len(y_bin):
            out[f"auc_{cls}"] = np.nan
        else:
            out[f"auc_{cls}"] = float(roc_auc_score(y_bin, proba[:, i]))
    return out


def calibration_deciles(score: np.ndarray, y: np.ndarray, classes: list[str]) -> pd.DataFrame:
    df = pd.DataFrame({"score": score, "y": y})
    df["decile"] = pd.qcut(df["score"], 10, labels=False, duplicates="drop")
    rows = []
    for decile, g in df.groupby("decile"):
        row = {"decile": int(decile), "n": len(g), "mean_score": float(g["score"].mean())}
        for cls in classes:
            row[f"rate_{cls}"] = float((g["y"] == cls).mean())
        rows.append(row)
    return pd.DataFrame(rows).sort_values("decile")


def compute_combo(fs_name, model_name, cols, train_X, train_y, dev_X, dev_y, test_X, test_y):
    """Fits one (feature_set, model) combo and returns everything needed
    downstream. Pure function of its inputs -- safe to checkpoint."""
    tm0 = time.time()
    importance_rows = []
    if model_name == "logreg":
        model, imputer, scaler = fit_logistic(train_X, train_y)
        classes = list(model.classes_)
        proba_train = score_logistic(model, imputer, scaler, train_X)
        proba_dev = score_logistic(model, imputer, scaler, dev_X)
        proba_test = score_logistic(model, imputer, scaler, test_X)
        coefs = model.coef_  # (n_classes, n_features)
        for ci, cls in enumerate(classes):
            for fi, feat in enumerate(cols):
                importance_rows.append({
                    "feature_set": fs_name, "model": model_name, "class": cls,
                    "feature": feat, "coefficient": float(coefs[ci, fi]),
                })
    else:
        model = fit_gbt(train_X, train_y)
        classes = list(model.classes_)
        proba_train = model.predict_proba(train_X)
        proba_dev = model.predict_proba(dev_X)
        proba_test = model.predict_proba(test_X)
        # Native permutation importance is expensive at 800k+ rows / up to
        # 695 features; use a fixed dev-split sample (documented, matches
        # prior study's precedent). n_jobs=1 (not -1): joblib's loky
        # multiprocessing backend hit a Windows IPC resource ceiling
        # (WinError 1450) spawning workers for 695-feature x 3-repeat runs;
        # single-process permutation importance is slower but immune to it.
        rng = np.random.default_rng(RANDOM_STATE)
        sample_idx = rng.choice(len(dev_X), size=min(20000, len(dev_X)), replace=False)
        from sklearn.inspection import permutation_importance
        r = permutation_importance(model, dev_X.iloc[sample_idx], dev_y[sample_idx],
                                   n_repeats=3, random_state=RANDOM_STATE,
                                   scoring="roc_auc_ovr", n_jobs=1)
        for fi, feat in enumerate(cols):
            importance_rows.append({
                "feature_set": fs_name, "model": model_name, "class": "all_ovr",
                "feature": feat, "coefficient": float(r.importances_mean[fi]),
            })

    score_train = entry_quality_score(proba_train, classes)
    score_dev = entry_quality_score(proba_dev, classes)
    score_test = entry_quality_score(proba_test, classes)

    row = {"feature_set": fs_name, "model": model_name, "n_features": len(cols),
           "fit_time_s": round(time.time() - tm0, 1)}
    for split_name, y, proba in (("train", train_y, proba_train),
                                ("2025", dev_y, proba_dev),
                                ("2026", test_y, proba_test)):
        row[f"{split_name}_logloss"] = float(log_loss(y, proba, labels=classes))
        for k, v in per_class_auc(y, proba, classes).items():
            row[f"{split_name}_{k}"] = v

    calib_frames = []
    for split_name, y, score in (("2025", dev_y, score_dev), ("2026", test_y, score_test)):
        c = calibration_deciles(score, y, CLASSES)
        c["feature_set"], c["model"], c["split"] = fs_name, model_name, split_name
        calib_frames.append(c)

    cutoffs = {band: float(np.quantile(score_dev, 1 - band)) for band in BANDS}

    return {
        "row": row, "calib_frames": calib_frames, "importance_rows": importance_rows,
        "cutoffs": cutoffs, "score_train": score_train, "score_dev": score_dev,
        "score_test": score_test,
    }


def main() -> None:
    import pickle
    t0 = time.time()
    feature_sets = json.loads((WORK / "feature_sets.json").read_text(encoding="utf-8"))
    ckpt_dir = WORK / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    train_df = pd.read_parquet(WORK / "train_2021_2024_prepared.parquet")
    dev_df = pd.read_parquet(WORK / "prepared_2025.parquet")
    test_df = pd.read_parquet(WORK / "prepared_2026.parquet")
    train_y = train_df["outcome_class"].to_numpy()
    dev_y = dev_df["outcome_class"].to_numpy()
    test_y = test_df["outcome_class"].to_numpy()

    print(f"train={len(train_df):,} dev={len(dev_df):,} test={len(test_df):,}")
    print("train class dist:", pd.Series(train_y).value_counts(normalize=True).to_dict())

    diag_rows, calib_frames, cutoffs = [], [], {}
    importance_rows = []

    for fs_name, cols in feature_sets.items():
        train_X, dev_X, test_X = train_df[cols], dev_df[cols], test_df[cols]

        for model_name in ("logreg", "gbt"):
            key = f"{fs_name}__{model_name}"
            ckpt_path = ckpt_dir / f"{key}.pkl"
            if ckpt_path.exists():
                print(f"--- {key}: loading from checkpoint ---")
                result = pickle.loads(ckpt_path.read_bytes())
            else:
                print(f"--- fitting {key} ({len(cols)} features) ---")
                result = compute_combo(fs_name, model_name, cols, train_X, train_y,
                                       dev_X, dev_y, test_X, test_y)
                ckpt_path.write_bytes(pickle.dumps(result))

            train_df[f"score_{key}"] = result["score_train"]
            dev_df[f"score_{key}"] = result["score_dev"]
            test_df[f"score_{key}"] = result["score_test"]
            diag_rows.append(result["row"])
            calib_frames.extend(result["calib_frames"])
            importance_rows.extend(result["importance_rows"])
            cutoffs[key] = result["cutoffs"]

            row = result["row"]
            print(f"    {key}: fit {row['fit_time_s']}s, "
                  f"2025 AUC winner={row.get('2025_auc_opposing_flip_winner'):.4f} "
                  f"prestop={row.get('2025_auc_pre_alignment_stop'):.4f}")

    pd.DataFrame(diag_rows).to_csv(RESULTS / "model_diagnostics.csv", index=False)
    pd.concat(calib_frames, ignore_index=True).to_csv(RESULTS / "calibration_deciles.csv", index=False)
    pd.DataFrame(importance_rows).to_csv(RESULTS / "feature_importance.csv", index=False)
    (WORK / "retention_cutoffs.json").write_text(json.dumps(cutoffs, indent=2), encoding="utf-8")

    train_df.to_parquet(WORK / "scored_train.parquet", index=False, compression="zstd")
    dev_df.to_parquet(WORK / "scored_dev_2025.parquet", index=False, compression="zstd")
    test_df.to_parquet(WORK / "scored_test_2026.parquet", index=False, compression="zstd")

    manifest = {
        "runtime_s": round(time.time() - t0, 1),
        "train_rows": len(train_df), "dev_rows": len(dev_df), "test_rows": len(test_df),
        "feature_sets": {k: len(v) for k, v in feature_sets.items()},
        "classes": CLASSES, "score_weights": SCORE_WEIGHTS, "bands": BANDS,
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    (RESULTS / "train_and_evaluate_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(pd.DataFrame(diag_rows)[["feature_set", "model", "2025_logloss", "2026_logloss",
                                   "2025_auc_opposing_flip_winner", "2026_auc_opposing_flip_winner",
                                   "2025_auc_pre_alignment_stop", "2026_auc_pre_alignment_stop"]
                                   ].to_string(index=False))
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

"""One-time Phase A model and 2025 threshold freeze."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pyarrow.parquet as pq
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

from .phase_a_adapter import EXPECTED_HASH, load_ordered_features


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_year(
    root: Path, year: int, features: list[str], require_observable_label: bool
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
    xs, ys, keys = [], [], []
    for path in sorted((root / f"year={year}").glob("month=*/checkpoints.parquet")):
        manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
        if sha256_file(path) != manifest["checkpoints_sha256"]:
            raise RuntimeError(f"partition hash mismatch: {path}")
        table = pq.read_table(path, columns=features + [
            "feature_complete", "label_censored", "label_flip_le_300",
            "regime_start_ns", "checkpoint_decision_ns",
        ])
        d = table.to_pydict()
        keep = [
            i for i in range(table.num_rows)
            if d["feature_complete"][i] and (
                not require_observable_label or (
                    not d["label_censored"][i] and d["label_flip_le_300"][i] is not None
                )
            )
        ]
        if keep:
            xs.append(np.asarray([[d[f][i] for f in features] for i in keep], dtype=np.float64))
            keys.append(np.asarray([
                (d["regime_start_ns"][i], d["checkpoint_decision_ns"][i]) for i in keep
            ], dtype=np.int64))
            if require_observable_label:
                ys.append(np.asarray([d["label_flip_le_300"][i] for i in keep], dtype=np.int8))
    if not xs:
        raise RuntimeError(f"no eligible rows for year {year}")
    return (
        np.concatenate(xs),
        np.concatenate(ys) if require_observable_label else None,
        np.concatenate(keys),
    )


def atomic_json(payload: dict, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def train(data_root: Path, artifact_dir: Path, repo_root: Path) -> None:
    if artifact_dir.exists():
        raise FileExistsError(f"refusing to overwrite frozen artifact: {artifact_dir}")
    artifact_dir.mkdir(parents=True)
    features = load_ordered_features(repo_root)
    train_parts = [
        load_year(data_root, y, features, require_observable_label=True)
        for y in (2021, 2022, 2023, 2024)
    ]
    x_train = np.concatenate([p[0] for p in train_parts])
    y_train = np.concatenate([p[1] for p in train_parts])
    x_dev_eval, y_dev, _ = load_year(
        data_root, 2025, features, require_observable_label=True
    )
    x_dev_threshold, _, threshold_keys = load_year(
        data_root, 2025, features, require_observable_label=False
    )

    model = HistGradientBoostingClassifier(
        max_depth=3, learning_rate=0.05, max_iter=200, random_state=42
    )
    model.fit(x_train, y_train)
    model_path = artifact_dir / "model.joblib"
    tmp_model = artifact_dir / "model.joblib.tmp"
    joblib.dump(model, tmp_model)
    os.replace(tmp_model, model_path)
    model_hash = sha256_file(model_path)

    # The persisted identity, not the in-memory estimator, owns all dev scores.
    frozen = joblib.load(model_path)
    if list(frozen.classes_) != [0, 1]:
        raise RuntimeError(f"unexpected class order: {frozen.classes_}")
    score = np.asarray(frozen.predict_proba(x_dev_threshold)[:, 1], dtype="<f8")
    eval_score = np.asarray(frozen.predict_proba(x_dev_eval)[:, 1], dtype="<f8")
    if not np.isfinite(score).all() or not np.isfinite(eval_score).all():
        raise RuntimeError("non-finite dev scores")
    thresholds = {
        "top_10": float(np.quantile(score, 0.90, method="linear")),
        "top_5": float(np.quantile(score, 0.95, method="linear")),
        "top_2_5": float(np.quantile(score, 0.975, method="linear")),
    }
    score_hash = hashlib.sha256(score.tobytes(order="C")).hexdigest()
    key_hash = hashlib.sha256(np.asarray(threshold_keys, dtype="<i8").tobytes(order="C")).hexdigest()
    threshold_manifest = {
        "model_id": "BULLISH_STRICT_top25_gbt_v2",
        "model_sha256": model_hash,
        "reference_year": 2025,
        "reference_start": "2025-01-01T00:00:00Z",
        "reference_end_exclusive": "2026-01-01T00:00:00Z",
        "session": "[08:30:00,15:00:00) America/Chicago",
        "cadence_seconds": 5,
        "population": "all feature-complete in-domain established bullish RTH checkpoints",
        "reference_rows": int(len(score)),
        "reference_key_sha256_little_endian_int64_pairs": key_hash,
        "score_sha256_little_endian_float64": score_hash,
        "numpy_version": np.__version__,
        "sklearn_version": sklearn.__version__,
        "numpy_method": "linear",
        "membership_operator": ">=",
        "thresholds": thresholds,
    }
    threshold_manifest["manifest_payload_sha256"] = hashlib.sha256(
        json.dumps(threshold_manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    atomic_json(threshold_manifest, artifact_dir / "thresholds.json")
    atomic_json({
        "method": "NONE_IDENTITY",
        "probability": "predict_proba[:, positive_class=1]",
        "model_sha256": model_hash,
    }, artifact_dir / "calibration.json")
    atomic_json({
        "model_id": "BULLISH_STRICT_top25_gbt_v2",
        "model_sha256": model_hash,
        "feature_list_sha256": EXPECTED_HASH,
        "features": features,
        "train_years": [2021, 2022, 2023, 2024],
        "train_rows": int(len(y_train)),
        "dev_year": 2025,
        "dev_evaluation_rows": int(len(y_dev)),
        "dev_threshold_rows": int(len(score)),
        "positive_class": 1,
        "dev_roc_auc": float(roc_auc_score(y_dev, eval_score)),
        "dev_average_precision": float(average_precision_score(y_dev, eval_score)),
    }, artifact_dir / "model_manifest.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[3]))
    args = parser.parse_args()
    train(Path(args.data_root), Path(args.artifact_dir), Path(args.repo_root))


if __name__ == "__main__":
    main()

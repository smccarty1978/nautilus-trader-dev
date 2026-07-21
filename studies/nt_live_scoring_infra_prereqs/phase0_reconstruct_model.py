"""Phase 0 -- reconstruct and persist the F3_volume_delta_plus_price_levels
+ GBT model that produced `score_F3_volume_delta_plus_price_levels__gbt_raw`
in `short_rth_pure_flip_prediction_enriched/_work/scored_dev_2025.parquet`.

No fitted model object exists anywhere on disk (SPEC.md finding 6 -- a
scout-agent claim that a checkpoint pickle persisted the model was
checked directly and found wrong: the pickle in
`short_rth_enriched_volume_level_retrain` contains only
{row, calib_frames, importance_rows, cutoffs, score_train, score_dev,
score_test}, never the model object, and belongs to a DIFFERENT,
superseded 5-class study (ENRICHED_RETRAIN_OVERFITS_2025), not the binary
`bearish_regime_flip_within_300s` model actually used downstream).

This script refits the exact call path used by
`short_rth_pure_flip_prediction_enriched/train_and_evaluate.py:125`
(`fit_gbt`, imported verbatim from
`short_rth_enriched_volume_level_retrain/train_and_evaluate.py:73-77`),
confirms the refit reproduces the stored `score_dev` column within
tolerance, and ONLY THEN persists the fitted model via joblib -- a
genuinely new artifact this study adds, not a re-derivation.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC_STUDY = ROOT / "studies" / "short_rth_pure_flip_prediction_enriched"
ENRICHED_RETRAIN = ROOT / "studies" / "short_rth_enriched_volume_level_retrain"
WORK, RESULTS = HERE / "_work", HERE / "results"
for d in (WORK, RESULTS):
    d.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ENRICHED_RETRAIN))
sys.path.insert(0, str(HERE))


def _load_module(name: str, path: Path):
    """`train_and_evaluate.py` exists under this literal bare name in both
    `short_rth_enriched_volume_level_retrain` and
    `short_rth_pure_flip_prediction_enriched` -- load under a distinct
    internal name to avoid sys.modules bare-name collision (same pattern
    already used and audited across this session's studies)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_enriched_retrain_train_eval = _load_module(
    "_enriched_retrain_train_eval", ENRICHED_RETRAIN / "train_and_evaluate.py")
fit_gbt = _enriched_retrain_train_eval.fit_gbt

FEATURE_SET_NAME = "F3_volume_delta_plus_price_levels"
TARGET = "bearish_regime_flip_within_300s"
RANDOM_STATE = 42
SCORE_COL = f"score_{FEATURE_SET_NAME}__gbt_raw"
TOLERANCE = 1e-9


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    t0 = time.time()
    feature_sets = json.loads((SRC_STUDY / "_work" / "feature_sets.json").read_text(encoding="utf-8"))
    cols = feature_sets[FEATURE_SET_NAME]
    if not isinstance(cols, list) or len(cols) != 695:
        raise RuntimeError(f"expected 695 ordered F3 features, got {len(cols)} ({type(cols)})")

    train_df = pd.read_parquet(SRC_STUDY / "_work" / "train_2021_2024_prepared.parquet")
    dev_df = pd.read_parquet(SRC_STUDY / "_work" / "prepared_2025.parquet")
    train_X, dev_X = train_df[cols], dev_df[cols]
    train_y = train_df[TARGET].astype(int).to_numpy()

    print(f"train={len(train_df):,} dev={len(dev_df):,} n_features={len(cols)}")
    print(f"train positive rate={train_y.mean():.4f}")

    model = fit_gbt(train_X, train_y)
    reconstructed_proba_dev = model.predict_proba(dev_X)[:, 1]

    stored = pd.read_parquet(
        SRC_STUDY / "_work" / "scored_dev_2025.parquet", columns=[SCORE_COL])[SCORE_COL].to_numpy()
    if len(stored) != len(reconstructed_proba_dev):
        raise RuntimeError(f"row count mismatch: stored={len(stored)} reconstructed={len(reconstructed_proba_dev)}")

    abs_diff = np.abs(stored - reconstructed_proba_dev)
    max_abs_diff = float(abs_diff.max())
    mean_abs_diff = float(abs_diff.mean())
    n_exceeding_tolerance = int((abs_diff > TOLERANCE).sum())
    reproduction_ok = n_exceeding_tolerance == 0

    print(f"max_abs_diff={max_abs_diff:.3e} mean_abs_diff={mean_abs_diff:.3e} "
          f"n_exceeding_tolerance={n_exceeding_tolerance}/{len(stored)}")

    if not reproduction_ok:
        manifest = {
            "reproduction_ok": False,
            "blocking_finding": "reconstructed model does not reproduce stored reference scores within tolerance",
            "max_abs_diff": max_abs_diff, "mean_abs_diff": mean_abs_diff,
            "n_exceeding_tolerance": n_exceeding_tolerance, "n_rows": len(stored),
            "tolerance": TOLERANCE,
        }
        (RESULTS / "phase0_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        raise SystemExit(
            f"BLOCKING: reconstruction diverges from stored reference scores "
            f"(max_abs_diff={max_abs_diff:.3e} > tolerance={TOLERANCE:.0e}) -- "
            f"see {RESULTS / 'phase0_manifest.json'}")

    import joblib
    model_path = WORK / "F3_volume_delta_plus_price_levels__gbt_reconstructed.joblib"
    joblib.dump(model, model_path)

    import sklearn
    manifest = {
        "reproduction_ok": True,
        "model_artifact_path": str(model_path.relative_to(ROOT)),
        "model_artifact_sha256": sha256_file(model_path),
        "reconstruction_script_sha256": sha256_file(Path(__file__).resolve()),
        "feature_sets_json_sha256": sha256_file(SRC_STUDY / "_work" / "feature_sets.json"),
        "train_parquet_sha256": sha256_file(SRC_STUDY / "_work" / "train_2021_2024_prepared.parquet"),
        "dev_parquet_sha256": sha256_file(SRC_STUDY / "_work" / "prepared_2025.parquet"),
        "sklearn_version": sklearn.__version__,
        "numpy_version": np.__version__,
        "hyperparameters": {
            "max_depth": 3, "learning_rate": 0.05, "max_iter": 200, "random_state": RANDOM_STATE},
        "feature_set": FEATURE_SET_NAME, "n_features": len(cols), "target": TARGET,
        "score_method": "predict_proba(...)[:, 1]",
        "positive_class_index": 1,
        "model_classes_": [str(c) for c in model.classes_.tolist()],
        "max_abs_diff_vs_stored_reference": max_abs_diff,
        "mean_abs_diff_vs_stored_reference": mean_abs_diff,
        "n_rows_compared": len(stored), "tolerance": TOLERANCE,
        "runtime_s": round(time.time() - t0, 1),
    }
    (RESULTS / "phase0_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

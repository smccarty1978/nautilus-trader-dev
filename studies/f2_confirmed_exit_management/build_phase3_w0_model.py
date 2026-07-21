"""Phase 3 driver for F2_CONFIRMED: train the W0 (local
progress/giveback only) weakness model.

SCOPE NOTE (user-confirmed 2026-07-11): see the identical note in
studies/all_flips_exit_management/build_phase3_w0_model.py -- W1-W4
require substantial fresh feature engineering and are deferred;
this study proceeds W0-only through Phases 4-8 first.
"""
from __future__ import annotations
import sys, time, pickle
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pandas as pd

from studies._shared_exit_mgmt.w0_features import W0_FEATURES
from studies._shared_exit_mgmt.train_model import train_and_evaluate

STUDY_ROOT = Path(__file__).parent
RESULTS_ROOT = STUDY_ROOT / "results"


def main():
    t0 = time.time()
    atlas = pd.read_parquet(RESULTS_ROOT / "corrected_weakness_atlas.parquet")
    print(f"Loaded atlas: {len(atlas):,} rows ({time.time()-t0:.0f}s)")

    t0 = time.time()
    out = train_and_evaluate(atlas, W0_FEATURES, "W0")
    print(f"Trained W0 model ({time.time()-t0:.0f}s)")
    print(out["metrics_by_split"].to_string())

    out["metrics_by_split"].to_parquet(
        RESULTS_ROOT / "model_comparison.parquet", index=False)
    out["decile_diagnostics"].to_parquet(
        RESULTS_ROOT / "weakness_score_deciles.parquet", index=False)

    calib = out["metrics_by_split"][
        ["model", "split", "calib_slope", "calib_intercept", "brier", "n"]]
    calib.to_parquet(RESULTS_ROOT / "calibration.parquet", index=False)

    ablation = out["metrics_by_split"].copy()
    ablation["feature_family"] = "W0"
    ablation["n_features"] = len(W0_FEATURES)
    ablation["note"] = ("W1-W4 not yet built; see build_phase3_w0_model.py "
                            "docstring for scope decision")
    ablation.to_parquet(
        RESULTS_ROOT / "feature_family_ablation.parquet", index=False)

    model_path = RESULTS_ROOT / "w0_model.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({"model": out["model"], "features": W0_FEATURES,
                        "decile_edges": out["decile_edges"]}, f)
    print(f"Wrote model_comparison.parquet, weakness_score_deciles.parquet, "
             f"calibration.parquet, feature_family_ablation.parquet, "
             f"{model_path}")


if __name__ == "__main__":
    main()

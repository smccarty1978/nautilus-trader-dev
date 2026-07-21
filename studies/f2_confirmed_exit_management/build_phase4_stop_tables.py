"""Phase 4 driver for F2_CONFIRMED: score the full atlas with the W0
model, compute state features (decile/persistence/score-path) and
recovery dynamics, then build the conditional recovery-MAE stop tables
on TRAIN+VALIDATION ONLY (never dev_test/reserved_eval -- that would
be a train/serve leak for the stop distances Phase 5/6 will use).
"""
from __future__ import annotations
import sys, time, pickle
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import numpy as np
import pandas as pd

from studies._shared_exit_mgmt.w0_features import (
    W0_FEATURES, add_target, add_split_label,
)
from studies._shared_exit_mgmt.recovery_dynamics import add_recovery_dynamics
from studies._shared_exit_mgmt.stop_state_features import add_state_features
from studies._shared_exit_mgmt.conditional_stop_tables import (
    build_conditional_tables, path_diagnostics,
)

STUDY_ROOT = Path(__file__).parent
RESULTS_ROOT = STUDY_ROOT / "results"


def main():
    t0 = time.time()
    atlas = pd.read_parquet(RESULTS_ROOT / "corrected_weakness_atlas.parquet")
    print(f"Loaded atlas: {len(atlas):,} rows ({time.time()-t0:.0f}s)")

    with open(RESULTS_ROOT / "w0_model.pkl", "rb") as f:
        model_bundle = pickle.load(f)
    model, edges = model_bundle["model"], model_bundle["decile_edges"]

    atlas = add_target(atlas)
    atlas = add_split_label(atlas)

    t0 = time.time()
    atlas["pred_weakness_prob"] = model.predict_proba(atlas[W0_FEATURES])[:, 1]
    print(f"Scored all rows ({time.time()-t0:.0f}s)")

    atlas["decile"] = pd.cut(
        atlas["pred_weakness_prob"], bins=edges, labels=False,
        include_lowest=True) + 1

    t0 = time.time()
    atlas = add_recovery_dynamics(atlas)
    print(f"Computed recovery dynamics ({time.time()-t0:.0f}s)")

    t0 = time.time()
    atlas = add_state_features(atlas)
    print(f"Computed state features (decile/persistence/score_path) "
             f"({time.time()-t0:.0f}s)")

    train_val = atlas[atlas["split"].isin(["train", "validation"])]
    print(f"train+validation rows for stop-table estimation: "
             f"{len(train_val):,}")

    t0 = time.time()
    cond_tables = build_conditional_tables(train_val)
    diag_tables = path_diagnostics(train_val)
    print(f"Built conditional tables ({time.time()-t0:.0f}s), "
             f"{len(cond_tables)} cells")

    cond_tables.to_parquet(
        RESULTS_ROOT / "conditional_recovery_mae_tables.parquet", index=False)
    diag_tables.to_parquet(
        RESULTS_ROOT / "conditional_path_diagnostics.parquet", index=False)
    print("Wrote conditional_recovery_mae_tables.parquet, "
             "conditional_path_diagnostics.parquet")

    work_dir = STUDY_ROOT / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    scored_path = work_dir / "scored_atlas_with_recovery_dynamics.parquet"
    atlas.to_parquet(scored_path, index=False)
    print(f"Wrote cache: {scored_path}")


if __name__ == "__main__":
    main()

"""Phase 4 driver for ALL_FLIPS: score the full atlas with the W0
model, compute state features (decile/persistence/score-path) and
recovery dynamics, then build the conditional recovery-MAE stop tables
on TRAIN+VALIDATION ONLY (never dev_test/reserved_eval -- that would
be a train/serve leak for the stop distances Phase 5/6 will use).
"""
from __future__ import annotations
import sys, time, pickle, gc
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
    print(f"Loaded atlas: {len(atlas):,} rows ({time.time()-t0:.0f}s)", flush=True)

    with open(RESULTS_ROOT / "w0_model.pkl", "rb") as f:
        model_bundle = pickle.load(f)
    model, edges = model_bundle["model"], model_bundle["decile_edges"]

    atlas = add_target(atlas)
    atlas = add_split_label(atlas)

    t0 = time.time()
    atlas["pred_weakness_prob"] = model.predict_proba(
        atlas[W0_FEATURES])[:, 1].astype("float32")
    print(f"Scored all rows ({time.time()-t0:.0f}s)", flush=True)

    atlas["decile"] = (pd.cut(
        atlas["pred_weakness_prob"], bins=edges, labels=False,
        include_lowest=True) + 1).astype("int8")
    gc.collect()

    t0 = time.time()
    atlas = add_recovery_dynamics(atlas)
    gc.collect()
    print(f"Computed recovery dynamics ({time.time()-t0:.0f}s)", flush=True)

    t0 = time.time()
    atlas = add_state_features(atlas)
    gc.collect()
    print(f"Computed state features (decile/persistence/score_path) "
             f"({time.time()-t0:.0f}s)", flush=True)

    # Write the cache FIRST, before the final aggregation step (which
    # previously got killed here twice, likely a memory spike from
    # holding the full atlas + a ~24M-row boolean-indexed copy
    # simultaneously) -- so the ~27 minutes of per-trade computation
    # above is never lost to a repeat kill.
    work_dir = STUDY_ROOT / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    scored_path = work_dir / "scored_atlas_with_recovery_dynamics.parquet"
    t0 = time.time()
    atlas.to_parquet(scored_path, index=False)
    print(f"Wrote cache: {scored_path} ({time.time()-t0:.0f}s)", flush=True)

    # Free the full atlas; reload only the columns needed for the
    # conditional tables to keep the final aggregation's peak memory low.
    needed_cols = [
        "trade_id", "decile", "persistence_bucket", "score_path", "split",
        "recovery_mae_from_checkpoint_atr", "recovery_mae_from_mfe_atr",
        "time_to_recovery_s", "time_to_failure_s",
        "eventual_recovery_to_prior_mfe", "eventual_new_mfe",
        "terminal_weakness_label", "pred_weakness_prob",
        "is_terminal_weakness",
    ]
    del atlas
    gc.collect()
    slim = pd.read_parquet(scored_path, columns=needed_cols)
    train_val = slim[slim["split"].isin(["train", "validation"])].copy()
    del slim
    gc.collect()
    print(f"train+validation rows for stop-table estimation: "
             f"{len(train_val):,}", flush=True)

    t0 = time.time()
    cond_tables = build_conditional_tables(train_val)
    diag_tables = path_diagnostics(train_val)
    print(f"Built conditional tables ({time.time()-t0:.0f}s), "
             f"{len(cond_tables)} cells", flush=True)

    cond_tables.to_parquet(
        RESULTS_ROOT / "conditional_recovery_mae_tables.parquet", index=False)
    diag_tables.to_parquet(
        RESULTS_ROOT / "conditional_path_diagnostics.parquet", index=False)
    print("Wrote conditional_recovery_mae_tables.parquet, "
             "conditional_path_diagnostics.parquet", flush=True)


if __name__ == "__main__":
    main()

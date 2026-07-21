"""Phase 3: Build dynamic entry/exit targets.

Produces:
  results/entry_targets.parquet  — per-observation entry targets
  results/exit_targets.parquet   — per-observation exit targets (positioned state)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

OUT_DIR    = Path("studies/rl_regime_feasibility/expanded_dynamic/results")
SNAP_FILE  = Path("studies/rl_regime_feasibility/results/feature_snapshots.parquet")
LBL_FILE   = Path("studies/rl_regime_feasibility/results/forward_labels.parquet")
FEAT_FILE  = OUT_DIR / "expanded_features.parquet"

_COMM = 5.0
_MULT = 20.0
_NS   = 1_000_000_000


def build_entry_targets() -> pd.DataFrame:
    """Entry targets: flat -> positioned at each observation step."""
    t0 = time.time()
    print("\nPhase 3a: Building entry targets ...")

    print("  Loading labels ...")
    lbl = pd.read_parquet(LBL_FILE, columns=[
        "observation_time", "entry_px",
        "base__pnl_60s", "base__pnl_120s", "base__pnl_300s",
        "base__stopped_60s", "base__stopped_120s", "base__stopped_300s",
        "base__exit_type_60s", "base__exit_type_120s", "base__exit_type_300s",
    ])

    print("  Loading snapshots for period ...")
    snaps = pd.read_parquet(SNAP_FILE, columns=["observation_time", "period", "step_index"])
    lbl = lbl.merge(snaps, on="observation_time", how="inner")
    print(f"  {len(lbl):,} rows after period join")

    # Entry targets (all steps)
    # y_entry_positive_Xs: binary — would entering now be profitable?
    lbl["y_entry_positive_60s"]   = (lbl["base__pnl_60s"]  > 0).astype(np.int8)
    lbl["y_entry_positive_120s"]  = (lbl["base__pnl_120s"] > 0).astype(np.int8)
    lbl["y_entry_positive_300s"]  = (lbl["base__pnl_300s"] > 0).astype(np.int8)

    # y_entry_adv: continuous advantage (same as pnl label — baseline is $0 for staying flat)
    lbl["y_entry_adv_60s"]   = lbl["base__pnl_60s"]
    lbl["y_entry_adv_120s"]  = lbl["base__pnl_120s"]
    lbl["y_entry_adv_300s"]  = lbl["base__pnl_300s"]

    out_cols = [
        "observation_time", "period", "step_index", "entry_px",
        "y_entry_positive_60s", "y_entry_positive_120s", "y_entry_positive_300s",
        "y_entry_adv_60s", "y_entry_adv_120s", "y_entry_adv_300s",
    ]
    out = lbl[out_cols].copy()

    out.to_parquet(OUT_DIR / "entry_targets.parquet", index=False)
    print(f"  Saved entry_targets.parquet: {len(out):,} rows in {time.time()-t0:.1f}s")

    for p in ["train", "val", "test"]:
        sub = out[out["period"] == p]
        pct_pos = 100 * sub["y_entry_positive_300s"].mean()
        print(f"  [{p}] n={len(sub):,}, y_entry_positive_300s={pct_pos:.1f}%")

    return out


def build_exit_targets() -> pd.DataFrame:
    """Exit targets: positioned -> flat.

    For steps with step_index >= 1, assume we entered at step 0 of the episode.
    Compute:
    - unrealized_pnl_atr: current open price minus step-0 entry price, in ATR units
    - y_exit_adv_h: forward pnl at current step (incremental gain of holding h more seconds)
    - y_exit_positive_h: binary version

    The "exit NOW" pnl relative to episode entry = unrealized_pnl_raw.
    The "hold h more" incremental gain = base__pnl_h at current step.
    So y_exit_adv_h = base__pnl_h (positive = hold is better, negative = exit is better).
    """
    t0 = time.time()
    print("\nPhase 3b: Building exit targets ...")

    print("  Loading labels ...")
    lbl = pd.read_parquet(LBL_FILE, columns=[
        "observation_time", "entry_px",
        "base__pnl_15s", "base__pnl_30s", "base__pnl_60s", "base__pnl_120s",
    ])

    print("  Loading snapshots ...")
    snaps = pd.read_parquet(SNAP_FILE, columns=[
        "observation_time", "episode_id", "step_index", "period",
        "atr_at_flip", "direction", "seconds_since_flip",
    ])
    df = snaps.merge(lbl, on="observation_time", how="inner")
    print(f"  {len(df):,} rows after join")

    # Get step-0 entry price per episode
    step0 = df[df["step_index"] == 0][["episode_id", "entry_px"]].rename(
        columns={"entry_px": "ep_entry_px"}
    )
    df = df.merge(step0, on="episode_id", how="left")

    # Unrealized PnL at current step (relative to episode entry at step 0)
    # direction=1: long, positive if current_open > ep_entry_px
    df["unrealized_pnl_raw"]  = df["direction"] * (df["entry_px"] - df["ep_entry_px"]) * _MULT - _COMM
    df["unrealized_pnl_atr"]  = _safe_div(
        df["unrealized_pnl_raw"],
        df["atr_at_flip"] * _MULT,
        fill=0.0,
    )
    df["time_in_trade_s"]     = df["seconds_since_flip"]  # proxy for time since episode start

    # Exit advantage targets (positive = holding is better, negative = exit is better)
    df["y_exit_adv_15s"]   = df["base__pnl_15s"]
    df["y_exit_adv_30s"]   = df["base__pnl_30s"]
    df["y_exit_adv_60s"]   = df["base__pnl_60s"]
    df["y_exit_adv_120s"]  = df["base__pnl_120s"]

    df["y_exit_positive_15s"]   = (df["base__pnl_15s"]  > 0).astype(np.int8)
    df["y_exit_positive_30s"]   = (df["base__pnl_30s"]  > 0).astype(np.int8)
    df["y_exit_positive_60s"]   = (df["base__pnl_60s"]  > 0).astype(np.int8)
    df["y_exit_positive_120s"]  = (df["base__pnl_120s"] > 0).astype(np.int8)

    # Only keep steps where we could be positioned (step >= 1)
    positioned = df[df["step_index"] >= 1].copy()

    out_cols = [
        "observation_time", "episode_id", "step_index", "period",
        "unrealized_pnl_raw", "unrealized_pnl_atr", "time_in_trade_s",
        "y_exit_adv_15s", "y_exit_adv_30s", "y_exit_adv_60s", "y_exit_adv_120s",
        "y_exit_positive_15s", "y_exit_positive_30s", "y_exit_positive_60s", "y_exit_positive_120s",
    ]
    out = positioned[out_cols].copy()

    out.to_parquet(OUT_DIR / "exit_targets.parquet", index=False)
    print(f"  Saved exit_targets.parquet: {len(out):,} rows in {time.time()-t0:.1f}s")

    for p in ["train", "val", "test"]:
        sub = out[out["period"] == p]
        if len(sub) == 0:
            continue
        pct_pos_60 = 100 * sub["y_exit_positive_60s"].mean()
        print(f"  [{p}] n={len(sub):,}, y_exit_positive_60s={pct_pos_60:.1f}%")

    return out


def _safe_div(a, b, fill=0.0):
    import numpy as np
    if isinstance(b, pd.Series):
        return np.where(b.abs() > 1e-9, a / b, fill)
    return a / b if abs(b) > 1e-9 else fill


if __name__ == "__main__":
    build_entry_targets()
    build_exit_targets()
    print("\nPhase 3 complete.")

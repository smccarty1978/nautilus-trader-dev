"""Shared constants for the established-regime weakness-fade study."""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS = STUDY / "results"
WORK = STUDY / "_work"
AUDIT = STUDY / "audit"

UPSTREAM = ROOT / "studies" / "regime_sequence_chop_context" / "results"
FLIP_ATLAS = UPSTREAM / "flip_context_atlas.parquet"
WEAKNESS_ATLAS = UPSTREAM / "weakness_checkpoint_atlas.parquet"
PRIOR = ROOT / "studies" / "fable5_pre_flip_d10_reversal_entry" / "_work"
MODEL_PATH = PRIOR / "w4_fable5.pkl"
THRESHOLD_PATH = PRIOR / "frozen_threshold.json"

RAW_1S = {
    y: ROOT / "data" / "raw" / (
        f"NQ_v0_1s_{y}_ytd.parquet" if y == 2026 else f"NQ_v0_1s_{y}.parquet"
    )
    for y in range(2021, 2027)
}

NS = 1_000_000_000
NQ_MULTIPLIER = 20.0
COST_RT_USD = 10.0
RTH_START_MIN = 8 * 60 + 30
RTH_END_MIN = 15 * 60

# Frozen before Stage-1 results are generated.  The key contrast is cohort 7
# (real-trend winner) versus cohort 6 (made >=1 ATR MFE but failed to retain
# 0.5 ATR at the flip).  These are descriptive, not live-policy thresholds.
STAGE1_GATE = {
    "duration_ratio_min": 1.25,
    "peak_mfe_ratio_min": 1.25,
    "progress_windows_delta_min": 1.0,
    "retained_m60_delta_min": 0.15,
    "minimum_structural_conditions": 3,
    "minimum_winner_count_train": 500,
    "minimum_winner_count_2025": 100,
    "minimum_paired_w4_count_train": 250,
    "minimum_paired_w4_count_2025": 50,
    "weakness_rise_min": 0.05,
    "minimum_median_peak_to_flip_s": 30.0,
    "minimum_median_giveback_atr": 0.25,
}

COHORTS = {
    "all_regimes": "all",
    "flip_pnl_ge_0p5": "flip>=0.5",
    "flip_pnl_ge_1p0": "flip>=1.0",
    "flip_pnl_lt_0": "flip<0",
    "flip_pnl_0_to_0p5": "0<=flip<0.5",
    "mfe_ge_1_flip_lt_0p5": "mfe>=1 & flip<0.5",
    "mfe_ge_1_flip_ge_0p5": "mfe>=1 & flip>=0.5",
    "mfe_lt_1": "mfe<1",
}

for path in (RESULTS, WORK, AUDIT):
    path.mkdir(parents=True, exist_ok=True)


def load_model_bundle() -> dict:
    with MODEL_PATH.open("rb") as f:
        return pickle.load(f)


def load_threshold() -> dict:
    return json.loads(THRESHOLD_PATH.read_text(encoding="utf-8"))


def is_rth(ts_ns: np.ndarray) -> np.ndarray:
    ct = pd.DatetimeIndex(pd.to_datetime(ts_ns, unit="ns", utc=True)).tz_convert(
        "America/Chicago"
    )
    mins = np.asarray(ct.hour) * 60 + np.asarray(ct.minute)
    return (mins >= RTH_START_MIN) & (mins < RTH_END_MIN)

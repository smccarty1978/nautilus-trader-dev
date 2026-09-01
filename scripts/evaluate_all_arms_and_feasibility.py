"""Phase C Full Evaluation and Feasibility Analysis Script.
=========================================================
Evaluates all three predefined target arms (TP 1.0 / SL 0.5, 1.0, 1.5) across the full
governed 2021-2023 TRAIN population (1,387,411 candidates).
"""

from __future__ import annotations

import gc
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd

from utils.runner.data import CausalDataLoader
from utils.session_boundaries import session_close_ns

REPO_ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = REPO_ROOT / "studies" / "regime_transition_target_before_stop_v1"
WORK_DIR = STUDY_DIR / "_work" / "train_merged_collection"
CATALOG_PATH = REPO_ROOT / "data" / "catalog" / "NQ_v0_2020_2026"

NS = 1_000_000_000

CANONICAL_FEATURES = [
    "arrival_acceleration",
    "arrival_velocity",
    "ema_slope",
    "prior_1m_regime_efficiency",
    "prior_1m_regime_mfe_atr",
    "prior_1m_regime_range_atr",
    "prior_5m_regime_efficiency",
    "prior_5m_regime_mfe_atr",
    "prior_5m_regime_range_atr",
    "rolling_300s_current_progress_atr",
    "rolling_300s_giveback_atr",
    "rolling_300s_max_progress_atr",
    "rolling_300s_retention_ratio",
]

TARGET_ARMS = [
    {"arm_id": "TP_1.0_SL_0.5", "barrier_id": "barrier_tp_1_0_sl_0_5", "fav": 1.0, "adv": 0.5},
    {"arm_id": "TP_1.0_SL_1.0", "barrier_id": "barrier_tp_1_0_sl_1_0", "fav": 1.0, "adv": 1.0},
    {"arm_id": "TP_1.0_SL_1.5", "barrier_id": "barrier_tp_1_0_sl_1_5", "fav": 1.0, "adv": 1.5},
]


def evaluate_candidate_barriers(
    direction: int,
    entry_price: float,
    atr: float,
    fav_mult: float,
    adv_mult: float,
    events_open: np.ndarray,
    events_high: np.ndarray,
    events_low: np.ndarray,
    events_ts: np.ndarray,
    events_gap: np.ndarray,
    session_close_ts: int,
    horizon_ns: int = 300 * NS,
    decision_ts: int = 0,
):
    """Evaluates ordered barrier race for a candidate against a sequence of forward 1s bars."""
    n_bars = len(events_open)
    if n_bars == 0:
        return {"disposition": "CENSORED", "label": None, "censor_reason": "DATA_END", "res_seconds": 300.0, "res_ts": decision_ts + horizon_ns}

    if direction == 1:
        tp_price = entry_price + (fav_mult * atr)
        sl_price = entry_price - (adv_mult * atr)
    else:
        tp_price = entry_price - (fav_mult * atr)
        sl_price = entry_price + (adv_mult * atr)

    for i in range(n_bars):
        bar_ts = events_ts[i]
        
        # 1. Session end censoring: if bar is past session close
        if bar_ts > session_close_ts:
            return {"disposition": "CENSORED", "label": None, "censor_reason": "SESSION_END", "res_seconds": (bar_ts - decision_ts) / NS, "res_ts": bar_ts}

        # 2. Feed continuity gap flag
        if events_gap[i]:
            return {"disposition": "CENSORED", "label": None, "censor_reason": "GAP", "res_seconds": (bar_ts - decision_ts) / NS, "res_ts": bar_ts}

        # 3. Check barrier hits
        b_high = events_high[i]
        b_low = events_low[i]

        if direction == 1:
            hit_tp = b_high >= tp_price
            hit_sl = b_low <= sl_price
        else:
            hit_tp = b_low <= tp_price
            hit_sl = b_high >= sl_price

        if hit_tp and hit_sl:
            return {"disposition": "CENSORED", "label": None, "censor_reason": "AMBIGUOUS_SAME_BAR_TOUCH", "res_seconds": (bar_ts - decision_ts) / NS, "res_ts": bar_ts}
        elif hit_tp:
            return {"disposition": "POSITIVE", "label": 1, "censor_reason": None, "res_seconds": (bar_ts - decision_ts) / NS, "res_ts": bar_ts}
        elif hit_sl:
            return {"disposition": "NEGATIVE", "label": 0, "censor_reason": None, "res_seconds": (bar_ts - decision_ts) / NS, "res_ts": bar_ts}

        # Check horizon expiry
        if bar_ts >= decision_ts + horizon_ns:
            # Reached full horizon without barrier touch -> negative (or timeout)
            return {"disposition": "NEGATIVE", "label": 0, "censor_reason": None, "res_seconds": 300.0, "res_ts": decision_ts + horizon_ns}

    # Data ended before horizon and before session close
    return {"disposition": "CENSORED", "label": None, "censor_reason": "DATA_END", "res_seconds": 300.0, "res_ts": decision_ts + horizon_ns}


def run_full_evaluation():
    print("============================================================")
    print("PHASE C FULL TRAIN TARGET EVALUATION (2021-2023)")
    print("============================================================")

    t0 = time.time()
    c_df = pd.read_parquet(WORK_DIR / "candidates.parquet")
    o_df = pd.read_parquet(WORK_DIR / "observations.parquet")
    print(f"Loaded {len(c_df):,} candidates in {time.time() - t0:.2f}s")

    c_df["ts_dt"] = pd.to_datetime(c_df["observation_ts"], unit="ns", utc=True)
    c_df["year"] = c_df["ts_dt"].dt.year
    c_df["month_str"] = c_df["ts_dt"].dt.strftime("%Y-%m")
    c_df["date_str"] = c_df["ts_dt"].dt.strftime("%Y-%m-%d")

    # Trade direction: LONG from Bearish (-1), SHORT from Bullish (+1)
    # in observations.parquet, regime_direction is the prevailing regime direction
    trade_dir = -o_df["regime_direction"]
    c_df["target_direction"] = trade_dir

    # Extract ATR frozen at decision_ts
    # From observations.parquet or candidates:
    # Notice that running_mfe_atr is candidate feature; the actual ATR is frozen_atr
    # Let's see: what ATR is used? In observation records or computed:
    # Let's inspect frozen_atr from run artifacts:
    pass


if __name__ == "__main__":
    run_full_evaluation()

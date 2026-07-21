"""Shared constants and utilities for the adaptive rank-filter walk-forward study.

Reuses, unchanged, the exact substrate of studies/rank_filter_oos_validation:
  - the F2 population from flip_context_atlas.parquet (bar+1 HH/LL + directional
    close confirmation on a causal 1m EMA3/EMA9 regime engine)
  - the canonical ~30s delayed-entry repair (repair_f2_window / audit_delayed_entry)
  - the E0 (opposite-regime-flip-only) exit and CollectorV2Strategy execution mechanics
  - the R2/R4 exemption formulas (seq_5r_center_migration_slope_atr > 0.005 /
    seq_5r_asym_duration > 1.5) and the frozen static score threshold

This study's only new logic is: (a) rolling monthly retraining of an equivalent
ridge-logistic score on trailing 3m/6m/12m windows, (b) fold-internal threshold
selection on the validation month only, (c) applying the frozen numeric
threshold to the deployment month unchanged. No new features, no new exits, no
new execution mechanics.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "studies" / "rank_filter_oos_validation"))

from studies.regime_sequence_chop_context.train_flip_filter import FEATURES_LIST  # noqa: E402
from common import (  # type: ignore  # rank_filter_oos_validation/common.py
    ATLAS_PATH, load_atlas, get_session, repair_f2_window, audit_delayed_entry,
    load_frozen_config, NQ_MULTIPLIER, CANONICAL_DELAY_NS,
)

OUT = PROJECT_ROOT / "studies/adaptive_rank_filter_walkforward/results"
OUT.mkdir(parents=True, exist_ok=True)
NT_OUT_ROOT = PROJECT_ROOT / "studies/adaptive_rank_filter_walkforward/nt_runs"
NT_OUT_ROOT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Period roles (fixed by the task brief -- not tuned)
# ---------------------------------------------------------------------------
PROTOCOL_START, PROTOCOL_END = "2021-01-01", "2024-12-31"      # protocol/design selection
DEV_START, DEV_END = "2025-01-01", "2026-02-28"                 # historical walk-forward development
RESERVED_START, RESERVED_END = "2026-03-01", "2026-04-29"       # final reserved evaluation (catalog coverage end)

# Deployment months this study reports on: Jan 2025 .. Apr 2026 (16 months)
DEPLOY_MONTHS = pd.period_range("2025-01", "2026-04", freq="M")

WINDOW_SIZES = {"3m": 3, "6m": 6, "12m": 12}
CANDIDATE_SKIP_RATES = (0.05, 0.10, 0.15)

# Frozen static-policy threshold/exemptions (studies/rank_filter_oos_validation,
# unaltered) -- used for the static R2/R4 baselines in this study.
STATIC_FROZEN_THRESHOLD_KEY = "R1"
R2_EXEMPT_COL, R2_EXEMPT_THR = "seq_5r_center_migration_slope_atr", 0.005
R4_EXEMPT_COL, R4_EXEMPT_THR = "seq_5r_asym_duration", 1.5

# NT execution / cost convention (CollectorV2Config defaults -- do not override,
# for exact comparability with the existing study's NT numbers).
COMMISSION_PER_RT = 5.0
TICK_DOLLAR = 5.0

NT_CATALOGS = {
    2025: dict(catalog="data/catalog/NQ_v0_2025_fixed", start="2025-01-01", end="2025-12-31"),
    2026: dict(catalog="data/catalog/NQ_v0_2026_fixed", start="2026-01-01", end="2026-04-29"),
}
ENTRY_DELAY_NS = 30_000_000_000  # matches CANONICAL_DELAY_NS convention used by run_nt_validation.py


def month_bounds(period: pd.Period) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = period.start_time.tz_localize("UTC")
    end = period.end_time.tz_localize("UTC")
    return start, end


def trailing_window_bounds(anchor_month: pd.Period, n_months: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Bounds of the N-month window ending at (and including) `anchor_month`."""
    train_end_p = anchor_month
    train_start_p = anchor_month - (n_months - 1)
    start, _ = month_bounds(train_start_p)
    _, end = month_bounds(train_end_p)
    return start, end


def load_f2_atlas() -> pd.DataFrame:
    """F2 population with episode_id, direction, session, month, and the
    canonical delayed-entry repair applied over the full atlas history
    (2021-01 .. 2026-04), so every fold's train/val/deploy slice is drawn
    from one single, consistently-repaired frame."""
    df_atlas = load_atlas()
    f2, _ = repair_f2_window(df_atlas, "2021-01-01", "2026-04-29")
    return f2


def purge_straddling(df: pd.DataFrame, window_end_ts: pd.Timestamp) -> pd.DataFrame:
    """Leakage control: drop any episode whose terminal outcome (ep_end_time)
    resolves after the given role-window boundary -- its label/PnL would
    depend on information not yet knowable as of the window's own cutoff."""
    return df[df["ep_end_time"] <= window_end_ts.value].copy()


def fit_ridge_logistic(train_df: pd.DataFrame):
    """Same recipe as train_flip_filter.py: train-median impute + StandardScaler
    + LogisticRegression(C=0.1, max_iter=500, penalty='l2')."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    X_raw = train_df[FEATURES_LIST].values
    medians = np.nanmedian(X_raw, axis=0)
    medians = np.nan_to_num(medians, nan=0.0)
    X = np.where(np.isnan(X_raw), medians, X_raw)
    y = (train_df["outcome_class"] == "EARLY_ROTATIONAL_FAILURE").astype(int).values

    pipe = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(C=0.1, max_iter=500, penalty="l2"))])
    pipe.fit(X, y)
    return pipe, medians


def score_with(pipe, medians, df: pd.DataFrame) -> np.ndarray:
    X_raw = df[FEATURES_LIST].values
    X = np.where(np.isnan(X_raw), medians, X_raw)
    return pipe.predict_proba(X)[:, 1]

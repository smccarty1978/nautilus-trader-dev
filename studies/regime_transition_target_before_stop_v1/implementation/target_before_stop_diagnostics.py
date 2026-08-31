"""Target-Before-Stop Diagnostics and Modeling Entrypoint.
======================================================
Study: regime_transition_target_before_stop_v1
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd


def compute_target_feasibility_diagnostics(
    df: pd.DataFrame,
    barrier_prefixes: List[str] = (
        "ordered_barrier_tp_1_0_sl_0_5",
        "ordered_barrier_tp_1_0_sl_1_0",
        "ordered_barrier_tp_1_0_sl_1_5",
    ),
) -> Dict[str, Any]:
    """Computes feasibility diagnostics across the predefined stop arms and yearly partitions."""
    diagnostics = {}
    for prefix in barrier_prefixes:
        disp_col = f"{prefix}_disposition"
        label_col = f"{prefix}_binary_label"
        censor_col = f"{prefix}_censor_reason"

        if disp_col not in df.columns:
            continue

        total_candidates = len(df)
        pos_mask = df[disp_col] == "POSITIVE"
        neg_mask = df[disp_col] == "NEGATIVE"
        censored_mask = df[disp_col] == "CENSORED"

        resolved_count = int((pos_mask | neg_mask).sum())
        pos_count = int(pos_mask.sum())
        neg_count = int(neg_mask.sum())

        pos_rate_resolved = float(pos_count / resolved_count) if resolved_count > 0 else 0.0

        timeout_count = int((df[censor_col] == "TIMEOUT").sum()) if censor_col in df.columns else 0
        session_count = int((df[censor_col] == "SESSION_END").sum()) if censor_col in df.columns else 0
        gap_count = int((df[censor_col] == "GAP").sum()) if censor_col in df.columns else 0
        ambig_count = int((df[censor_col] == "AMBIGUOUS_SAME_BAR_TOUCH").sum()) if censor_col in df.columns else 0

        diagnostics[prefix] = {
            "total_candidates": total_candidates,
            "resolved_count": resolved_count,
            "positive_count": pos_count,
            "negative_count": neg_count,
            "positive_rate_resolved": pos_rate_resolved,
            "timeout_count": timeout_count,
            "timeout_rate": float(timeout_count / total_candidates) if total_candidates > 0 else 0.0,
            "session_censored_count": session_count,
            "session_censored_rate": float(session_count / total_candidates) if total_candidates > 0 else 0.0,
            "gap_censored_count": gap_count,
            "gap_censored_rate": float(gap_count / total_candidates) if total_candidates > 0 else 0.0,
            "ambiguous_count": ambig_count,
            "ambiguous_rate": float(ambig_count / total_candidates) if total_candidates > 0 else 0.0,
        }
    return diagnostics

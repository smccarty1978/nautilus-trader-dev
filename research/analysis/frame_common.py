"""Frame helpers shared by the analysis-op implementations that are NOT ``diagnostic_ops``.

An implementation module may not statically import another (``test_analysis_op_boundary``: every
implementation is reachable only through the capability index), so ``contrast_ops`` cannot borrow
``diagnostic_ops``' private helpers. These are byte-for-byte behavioural copies of
``diagnostic_ops._require`` / ``_scalar`` / ``globex_trading_day`` / ``_cluster_keys``;
``research/analysis/tests/test_contrast_ops.py::test_frame_common_matches_diagnostic_ops`` proves
the session-day clustering is identical, so a clustered statistic means the same thing in every op.
``diagnostic_ops`` keeps its own copies untouched (it is inside sealed studies' execution closures).
"""
from __future__ import annotations

import math
from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd

from research.analysis.ops import AnalysisOpError


def require_columns(frame: pd.DataFrame, columns: Sequence[str], where: str) -> None:
    missing = [c for c in columns if c and c not in frame.columns]
    if missing:
        raise AnalysisOpError(f"ANALYSIS_COLUMN_MISSING: {where} needs {sorted(set(missing))}")


def scalar(v: Any) -> Any:
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def globex_trading_day(ts_ns: pd.Series) -> pd.Series:
    """CME Globex trading day (17:00 America/Chicago opens the NEXT calendar date), ISO ``YYYY-MM-DD``."""
    t = pd.to_datetime(pd.to_numeric(ts_ns, errors="coerce"), utc=True).dt.tz_convert("America/Chicago") + pd.Timedelta(hours=7)
    return t.dt.strftime("%Y-%m-%d").where(t.notna(), None)


def cluster_keys(frame: pd.DataFrame, cluster_column: Optional[str], cluster_ts_column: Optional[str], where: str) -> pd.Series:
    if (cluster_column is None) == (cluster_ts_column is None):
        raise AnalysisOpError(
            f"ANALYSIS_CLUSTER_UNDECLARED: {where} needs exactly one of cluster_column / cluster_ts_column (the session "
            "day); rows from one session are not independent, and a count without its cluster count is not reportable")
    if cluster_column is not None:
        require_columns(frame, [cluster_column], where)
        return frame[cluster_column]
    require_columns(frame, [cluster_ts_column], where)
    return globex_trading_day(frame[cluster_ts_column])


__all__ = ["require_columns", "scalar", "globex_trading_day", "cluster_keys"]

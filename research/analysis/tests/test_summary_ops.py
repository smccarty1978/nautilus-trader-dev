"""A6: grouped descriptive summary and session-day-clustered uncertainty (research.analysis.diagnostic_ops)."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from research.analysis.diagnostic_ops import AnalysisOpError, clustered_uncertainty, globex_trading_day, grouped_summary
from research.analysis.ops import run_op


def _days_frame():
    """4 session days x 10 rows; every row of a day carries the day's value -> perfectly clustered."""
    rows = []
    for d, v in enumerate([1.0, 2.0, 3.0, 4.0]):
        for _ in range(10):
            rows.append({"day": f"2023-01-0{d + 3}", "y": v, "side": "long" if d % 2 == 0 else "short", "cens": False})
    return pd.DataFrame(rows)


def test_clustered_se_is_the_cluster_robust_se_not_the_row_se():
    out = clustered_uncertainty(_days_frame(), value_columns=["y"], cluster_column="day")
    cell = out["payload"]["cells"][0]
    assert (cell["n_rows"], cell["n_clusters"]) == (40, 4)
    assert cell["mean"] == pytest.approx(2.5)
    # residual cluster sums -15,-5,5,15 -> G/(G-1) * 500 / 40^2
    assert cell["se"] == pytest.approx(math.sqrt((4 / 3) * 500 / 1600))
    naive = pd.Series(_days_frame()["y"]).std(ddof=1) / math.sqrt(40)
    assert cell["se"] > 3 * naive
    from scipy import stats
    half = stats.t.ppf(0.975, 3) * cell["se"]
    assert (cell["ci_low"], cell["ci_high"]) == (pytest.approx(2.5 - half), pytest.approx(2.5 + half))
    assert cell["df"] == 3


def test_cluster_count_is_a_required_output_and_a_cluster_is_required_input():
    out = clustered_uncertainty(_days_frame(), value_columns=["y"], cluster_column="day", group_by=["side"])
    assert set(out["frame"].columns) >= {"n_rows", "n_clusters", "mean", "se", "ci_low", "ci_high"}
    assert out["frame"]["n_clusters"].notna().all()
    with pytest.raises(AnalysisOpError, match="ANALYSIS_CLUSTER_UNDECLARED"):
        clustered_uncertainty(_days_frame(), value_columns=["y"])
    with pytest.raises(AnalysisOpError, match="ANALYSIS_CLUSTER_UNDECLARED"):
        grouped_summary(_days_frame(), value_columns=["y"])


def test_difference_between_groups_has_a_clustered_se():
    f = _days_frame()
    out = clustered_uncertainty(f, value_columns=["y"], cluster_column="day", group_by=["side"],
                                differences=[{"name": "long_minus_short", "a": {"side": "long"}, "b": {"side": "short"}}])
    diff = out["payload"]["differences"][0]
    assert diff["estimate"] == pytest.approx(2.0 - 3.0)
    assert (diff["n_rows"], diff["n_clusters"]) == (40, 4)
    # influence: a rows (y-2)/20, b rows -(y-3)/20; cluster sums -0.5, -0.5, +0.5, +0.5 -> 4/3 * 1.0
    assert diff["se"] == pytest.approx(math.sqrt(4 / 3))


def test_single_cluster_reports_counts_and_no_se():
    f = _days_frame()
    out = clustered_uncertainty(f[f["day"] == "2023-01-03"], value_columns=["y"], cluster_column="day")
    cell = out["payload"]["cells"][0]
    assert (cell["n_rows"], cell["n_clusters"], cell["se"], cell["ci_low"]) == (10, 1, None, None)


def test_grouped_summary_is_censoring_aware_and_carries_cluster_count():
    f = _days_frame()
    f.loc[f.index[:5], "cens"] = True
    f.loc[f.index[5], "y"] = None
    out = grouped_summary(f, value_columns=["y"], group_by=["side"], quantiles=[0.1, 0.9], censored_column="cens",
                          cluster_column="day")
    cells = {c["side"]: c for c in out["payload"]["cells"]}
    long = cells["long"]
    assert (long["n_rows"], long["n_censored"], long["n_null"], long["n"], long["n_clusters"]) == (20, 5, 1, 14, 2)
    assert long["median"] == pytest.approx(3.0)
    assert set(long) >= {"mean", "median", "q0.1", "q0.9"}
    assert out["frame"]["n_clusters"].notna().all()


def test_cluster_from_timestamps_is_the_globex_trading_day():
    before = pd.Timestamp("2023-01-03 16:59:59", tz="America/Chicago").tz_convert("UTC").value
    after = pd.Timestamp("2023-01-03 17:00:00", tz="America/Chicago").tz_convert("UTC").value
    days = globex_trading_day(pd.Series([before, after]))
    assert list(days) == ["2023-01-03", "2023-01-04"]
    f = pd.DataFrame({"ts": [before, before, after], "y": [1.0, 1.0, 5.0]})
    cell = clustered_uncertainty(f, value_columns=["y"], cluster_ts_column="ts")["payload"]["cells"][0]
    assert (cell["n_rows"], cell["n_clusters"]) == (3, 2)


def test_ops_are_registered_and_run_through_the_boundary():
    out = run_op("analysis.uncertainty.clustered_mean", _days_frame(), params={"value_columns": ["y"], "cluster_column": "day"})
    assert out["payload"]["cells"][0]["n_clusters"] == 4
    out = run_op("analysis.describe.grouped", _days_frame(), params={"value_columns": ["y"], "cluster_column": "day"})
    assert out["payload"]["cells"][0]["n_rows"] == 40

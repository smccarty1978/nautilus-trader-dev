"""Targeted tests for the three generic Analysis Harness capabilities added for the
YM prerequisite session (Task F):

  1. descriptive summary (count/null/distinct/mean/std/min/quantile-ladder/max)
  2. target-disposition slice (positive/negative, censored excluded from both)
  3. fixed-edge bucketing (declared intervals, never quantile/decile-derived)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.analysis import metrics as M  # noqa: E402
from research.analysis import reporting as R  # noqa: E402
from research.analysis import slices as S  # noqa: E402

# ---------------------------------------------------------------------------
# 1. Descriptive summary
# ---------------------------------------------------------------------------


def test_descriptive_summary_matches_hand_computed_values():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    res = M.descriptive_summary(values)
    assert res.n == 10
    assert res.n_missing == 0
    assert res.extra["count_available"] == 10
    assert res.extra["count_null"] == 0
    assert res.extra["distinct_count"] == 10
    assert res.extra["mean"] == pytest.approx(5.5)
    assert res.extra["std"] == pytest.approx(np.std(values, ddof=1))
    assert res.extra["min"] == pytest.approx(1.0)
    assert res.extra["max"] == pytest.approx(10.0)
    assert res.extra["q50"] == pytest.approx(np.quantile(values, 0.5))


def test_descriptive_summary_counts_nulls_separately_from_available():
    values = [1.0, 2.0, np.nan, 4.0, np.nan]
    res = M.descriptive_summary(values)
    assert res.extra["count_available"] == 3
    assert res.extra["count_null"] == 2
    assert res.n == 3
    assert res.n_missing == 2


def test_descriptive_summary_quantile_ladder_delegates_to_quantiles():
    """The quantile ladder must be numerically identical to a standalone quantiles() call."""
    values = list(np.linspace(0.0, 100.0, 37))
    desc = M.descriptive_summary(values)
    direct = M.quantiles(values)
    for key in ("q10", "q25", "q50", "q75", "q90"):
        assert desc.extra[key] == pytest.approx(direct.extra[key])


def test_descriptive_summary_distinct_count_deduplicates():
    values = [1.0, 1.0, 1.0, 2.0, 2.0, 3.0]
    res = M.descriptive_summary(values)
    assert res.extra["distinct_count"] == 3
    assert res.extra["count_available"] == 6


def test_descriptive_summary_single_value_std_is_none_not_nan():
    res = M.descriptive_summary([5.0])
    assert res.extra["std"] is None
    assert res.extra["mean"] == pytest.approx(5.0)


def test_descriptive_summary_empty_is_not_computable():
    res = M.descriptive_summary([])
    assert res.computable is False
    assert res.n == 0


def test_descriptive_table_is_a_single_row_not_a_partition():
    values = [1.0, 2.0, 3.0, np.nan]
    t = R.build_descriptive_table(values, column_name="my_feature")
    assert len(t.rows) == 1
    assert t.reconciles_rows is False
    row = t.rows[0]
    assert row["column"] == "my_feature"
    assert row["count_available"] == 3
    assert row["count_null"] == 1


# ---------------------------------------------------------------------------
# 2. Target-disposition slice
# ---------------------------------------------------------------------------


def test_target_disposition_splits_positive_and_negative():
    meta = pd.DataFrame({"target_flip_within_horizon": [1, 0, 1, 0, 1]})
    sl = S.slice_target_disposition(meta)
    assert sl.derivable
    assert set(sl.groups) == {"positive", "negative"}
    assert list(sl.labels) == ["positive", "negative", "positive", "negative", "positive"]


def test_target_disposition_excludes_censored_from_both_groups():
    """A censored (NaN) target row must be neither positive nor negative."""
    meta = pd.DataFrame({"target_flip_within_horizon": [1, 0, np.nan, 1, np.nan]})
    sl = S.slice_target_disposition(meta)
    labels = list(sl.labels)
    assert labels[2] is pd.NA or (isinstance(labels[2], float) and math.isnan(labels[2]))
    assert labels[4] is pd.NA or (isinstance(labels[4], float) and math.isnan(labels[4]))
    assert labels[0] == "positive"
    assert labels[1] == "negative"


def test_target_disposition_censored_rows_surface_as_unassigned_not_negative():
    """End-to-end: censored rows must show up in the table's 'unassigned' row,
    never silently inflate the 'negative' group's count."""
    meta = pd.DataFrame({"target_flip_within_horizon": [1, 0, np.nan, 1, 0, np.nan, np.nan]})
    y = pd.Series([1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0])  # some outcome measured per row
    t = R.build_target_disposition_table(y, meta)
    by_group = {r["group"]: r["n"] for r in t.rows}
    assert by_group["positive"] == 2
    assert by_group["negative"] == 2
    assert by_group[R.UNASSIGNED_GROUP] == 3
    # No unreconciled rows: every input row landed in exactly one bucket.
    assert t.unassigned_rows == 0
    assert t.total_n == 7


def test_target_disposition_missing_column_is_reported_not_raised():
    meta = pd.DataFrame({"other_col": [1, 2, 3]})
    sl = S.slice_target_disposition(meta)
    assert sl.derivable is False
    assert "target_flip_within_horizon" in sl.reason


def test_target_disposition_custom_column_name():
    meta = pd.DataFrame({"my_target": [1, 0, 1]})
    sl = S.slice_target_disposition(meta, target_column="my_target")
    assert sl.derivable
    assert set(sl.groups) == {"positive", "negative"}


# ---------------------------------------------------------------------------
# 3. Fixed-edge bucketing
# ---------------------------------------------------------------------------


def test_fixed_edges_study_buckets_partition_correctly():
    values = [-5.0, -0.001, 0.0, 0.5, 1.0, 1.001, 5.0]
    sl = S.slice_fixed_edges(values, S.STUDY_FIXED_EDGES)
    assert list(sl.labels) == ["(-inf,0)", "(-inf,0)", "[0,1]", "[0,1]", "[0,1]", "(1,+inf)", "(1,+inf)"]


def test_fixed_edges_boundary_zero_belongs_to_middle_bucket_not_lower():
    sl = S.slice_fixed_edges([0.0], S.STUDY_FIXED_EDGES)
    assert list(sl.labels) == ["[0,1]"]


def test_fixed_edges_boundary_one_belongs_to_middle_bucket_not_upper():
    sl = S.slice_fixed_edges([1.0], S.STUDY_FIXED_EDGES)
    assert list(sl.labels) == ["[0,1]"]


def test_fixed_edges_nan_is_unassigned_not_bucketed():
    sl = S.slice_fixed_edges([np.nan, 0.5], S.STUDY_FIXED_EDGES)
    labels = list(sl.labels)
    assert labels[0] is pd.NA or (isinstance(labels[0], float) and math.isnan(labels[0]))
    assert labels[1] == "[0,1]"


def test_fixed_edges_are_declared_not_derived_from_data():
    """Edges must stay identical however the data is distributed -- no fitting."""
    narrow = S.slice_fixed_edges([0.4, 0.5, 0.6], S.STUDY_FIXED_EDGES)
    wide = S.slice_fixed_edges([-1000.0, 0.5, 1000.0], S.STUDY_FIXED_EDGES)
    assert narrow.definition == wide.definition
    assert [iv.label for iv in S.STUDY_FIXED_EDGES] == ["(-inf,0)", "[0,1]", "(1,+inf)"]


def test_fixed_edges_is_not_quantile_or_decile_bucketing():
    """A skewed sample must not shift which bucket a given value lands in."""
    skewed = [0.0] * 100 + [50.0]  # heavily skewed toward 0
    sl = S.slice_fixed_edges(skewed, S.STUDY_FIXED_EDGES)
    # Under quantile/decile bucketing, 0.0 (99% of the mass) would spread across
    # several buckets. Under fixed edges, every 0.0 lands in the same bucket.
    labels = list(sl.labels)
    assert all(lbl == "[0,1]" for lbl in labels[:100])
    assert labels[100] == "(1,+inf)"


def test_fixed_edges_generic_primitive_accepts_arbitrary_intervals():
    """The primitive is not hardcoded to the study's three buckets."""
    custom = (
        S.FixedInterval("low", None, 10.0, upper_closed=False),
        S.FixedInterval("high", 10.0, None, lower_closed=True),
    )
    sl = S.slice_fixed_edges([5.0, 10.0, 15.0], custom)
    assert list(sl.labels) == ["low", "high", "high"]


def test_fixed_edges_table_records_declared_edges_in_filters():
    values = [-1.0, 0.5, 2.0]
    y = pd.Series([0.0, 1.0, 0.0])
    t = R.build_fixed_edges_table(y, values, column_name="my_feature")
    assert t.filters["edges"] == ["(-inf,0)", "[0,1]", "(1,+inf)"]
    assert t.filters["column"] == "my_feature"
    by_group = {r["group"]: r["n"] for r in t.rows}
    assert by_group == {"(-inf,0)": 1, "[0,1]": 1, "(1,+inf)": 1}

from pathlib import Path

import pandas as pd
import pytest

from research_workflow.partitioning import (
    PartitionError,
    build_year_partitions,
    merge_partition_outputs,
    reconcile_partitions,
    retain_primary_rows,
)


STUDY = Path("studies/clean_maturity_flip_model_rolling_productivity")


def test_year_partitions_are_authorized_and_disjoint():
    parts = build_year_partitions(STUDY, "train")
    assert [p.partition_id for p in parts] == ["train-2021", "train-2022", "train-2023"]
    assert parts[1].warmup_start == "2021-12-27"
    assert parts[1].lookahead_end == "2023-01-01"
    report = reconcile_partitions([p.to_dict() for p in parts])
    assert report["passed"] is True


def test_merge_rejects_overlapping_primary_keys():
    parts = build_year_partitions(STUDY, "train", years=[2021, 2022])
    frame = pd.DataFrame({"candidate_ts": [1], "regime_start_ns": [2], "direction": ["LONG"], "x": [1.0]})
    with pytest.raises(PartitionError, match="overlapping"):
        merge_partition_outputs([frame, frame.copy()], parts)


def test_merge_is_deterministic_and_preserves_schema():
    parts = build_year_partitions(STUDY, "train", years=[2021, 2022])
    a = pd.DataFrame({"candidate_ts": [2], "regime_start_ns": [2], "direction": ["LONG"], "x": pd.Series([2.0], dtype="float64")})
    b = pd.DataFrame({"candidate_ts": [1], "regime_start_ns": [1], "direction": ["SHORT"], "x": pd.Series([1.0], dtype="float64")})
    out = merge_partition_outputs([a, b], parts)
    assert out["candidate_ts"].tolist() == [1, 2]
    assert str(out["x"].dtype) == "float64"


def test_target_crossing_partition_boundary_stays_on_primary_row():
    part = build_year_partitions(STUDY, "train", years=[2023])[0]
    # A primary candidate whose disposition is resolved by lookahead is retained;
    # a lookahead-only candidate is excluded from the primary output surface.
    part = type(part)(**{**part.to_dict(), "primary_start": "2023-10-02", "primary_end": "2023-10-02", "lookahead_end": "2023-10-03"})
    frame = pd.DataFrame({
        "observation_ts": [pd.Timestamp("2023-10-02 15:14:00", tz="UTC").value,
                            pd.Timestamp("2023-10-03 15:14:00", tz="UTC").value],
        "regime_start_ns": [1, 2], "checkpoint_index": [1, 2],
        "disposition": ["LABELED_POSITIVE", "LABELED_NEGATIVE"],
    })
    out = retain_primary_rows(frame, part)
    assert len(out) == 1
    assert out.iloc[0]["disposition"] == "LABELED_POSITIVE"

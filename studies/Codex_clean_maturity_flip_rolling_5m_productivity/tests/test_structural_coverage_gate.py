import polars as pl
import pytest

from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.collector import STRUCTURAL_FEATURES
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.run_exploratory_models import (
    _assert_structural_coverage,
    _minimum_structural_coverage,
)


def _frame(short_complete: int = 10) -> pl.DataFrame:
    rows = []
    for direction in (1, -1):
        for bucket in ("300-600s", "600-900s", "900-1800s"):
            for index in range(10):
                row = {
                    "prevailing_direction": direction,
                    "maturity_bucket": bucket,
                    "structural_available": not (direction == 1 and bucket == "300-600s" and index >= short_complete),
                }
                row.update({feature: 1.0 for feature in STRUCTURAL_FEATURES})
                rows.append(row)
    return pl.DataFrame(rows)


def test_frozen_structural_coverage_threshold_is_explicitly_configured():
    assert _minimum_structural_coverage() == 0.90


def test_coverage_gate_accepts_all_complete_primary_directional_cells():
    rows = _assert_structural_coverage(_frame(), "TRAIN", 0.90)
    assert len(rows) == 6
    assert all(row["coverage"] == 1.0 for row in rows)


def test_coverage_gate_refuses_a_subthreshold_directional_cell():
    with pytest.raises(RuntimeError, match="SHORT/300-600s structural coverage 80.000%"):
        _assert_structural_coverage(_frame(short_complete=8), "TRAIN", 0.90)

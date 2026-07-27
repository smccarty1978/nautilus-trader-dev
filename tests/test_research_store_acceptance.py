from __future__ import annotations

from studies.full_trade_path_builder.analysis.validate_canonical_research_store import (
    metric_errors,
)


def test_metric_errors_accept_exact_and_bounded_float_noise() -> None:
    result = metric_errors([1.0, 2.0], [1.0, 2.0 + 1e-13], 1e-12, 1e-12)
    assert result["failure_count"] == 0
    assert result["maximum_absolute_error"] > 0


def test_metric_errors_reject_unexplained_difference() -> None:
    result = metric_errors([1.0, 3.0], [1.0, 2.0], 1e-12, 1e-12)
    assert result["failure_count"] == 1
    assert result["failure_indexes"] == [1]

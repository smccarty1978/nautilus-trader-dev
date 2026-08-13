from studies.full_trade_path_builder.implementation.phase_b_grid import (
    canonical_partition_bounds,
    expected_rth_grid_ns,
)
from datetime import datetime, timezone
from studies.full_trade_path_builder.implementation.reconcile_phase_b_missing_grid import (
    target_table,
)


def test_missing_target_is_exact_expected_complement():
    start, end = 0, 24 * 60 * 60 * 1_000_000_000
    expected = expected_rth_grid_ns(start, end)
    emitted = {expected[0], expected[-1]}
    target = target_table(emitted, start, end)
    missing = set(target["checkpoint_decision_ns"].to_pylist())
    assert missing == set(expected) - emitted
    assert not (missing & emitted)


def test_empty_missing_target_preserves_schema():
    start, end = 0, 24 * 60 * 60 * 1_000_000_000
    emitted = set(expected_rth_grid_ns(start, end))
    target = target_table(emitted, start, end)
    assert len(target) == 0
    assert target.column_names == ["checkpoint_decision_ns", "suppression_reason"]


def test_final_partition_ends_at_utc_seal_not_ct_midnight():
    _, end = canonical_partition_bounds(2025, 12)
    assert end == datetime(2026, 1, 1, tzinfo=timezone.utc)

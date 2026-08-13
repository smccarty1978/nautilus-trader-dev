from studies.full_trade_path_builder.implementation.correct_phase_b_missing_scope import (
    filter_partition_rows,
    filter_partition_table,
    prepared_install_action,
)
import pyarrow as pa


def test_filter_partition_rows_is_left_closed_right_open():
    rows = [
        {"checkpoint_decision_ns": 99},
        {"checkpoint_decision_ns": 100},
        {"checkpoint_decision_ns": 199},
        {"checkpoint_decision_ns": 200},
    ]
    assert filter_partition_rows(rows, 100, 200) == rows[1:3]


def test_empty_filter_preserves_arrow_schema():
    table = pa.table(
        {
            "checkpoint_decision_ns": pa.array([1], type=pa.int64()),
            "suppression_reason": pa.array(["missing_dispatch_bar"], type=pa.string()),
        }
    )
    filtered = filter_partition_table(table, 100, 200)
    assert len(filtered) == 0
    assert filtered.schema == table.schema


def test_prepared_equal_hash_installed_target_needs_no_staging():
    assert (
        prepared_install_action(
            current_hash="same",
            source_hash="same",
            target_hash="same",
            staged_exists=False,
        )
        == "target_installed"
    )

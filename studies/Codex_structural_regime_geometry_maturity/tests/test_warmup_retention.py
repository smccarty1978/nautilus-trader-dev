import polars as pl

import pytest

from studies.Codex_structural_regime_geometry_maturity.implementation.run_collect import assert_retained_rows_ready, retain_after_warmup


def test_only_post_warmup_target_rows_are_retained():
    frame = pl.DataFrame({"checkpoint_decision_ns": [99, 100, 105, 199, 200], "structural_available": [False] * 5})
    retained = retain_after_warmup(frame, 100, 200)
    assert retained["checkpoint_decision_ns"].to_list() == [100, 105, 199]


def test_first_retained_snapshot_must_have_completed_tracker_state():
    ready = pl.DataFrame({"checkpoint_decision_ns": [99, 100, 105], "structural_available": [False, True, False]})
    assert_retained_rows_ready(ready, 100, 200)
    not_ready = ready.with_columns(pl.when(pl.col("checkpoint_decision_ns") == 100).then(False).otherwise(pl.col("structural_available")).alias("structural_available"))
    with pytest.raises(RuntimeError, match="first retained snapshot unavailable"):
        assert_retained_rows_ready(not_ready, 100, 200)

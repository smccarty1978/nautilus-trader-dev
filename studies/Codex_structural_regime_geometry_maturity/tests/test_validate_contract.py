import polars as pl

from studies.Codex_structural_regime_geometry_maturity.implementation.validate import expected_auc_cells, snapshot_join_checks


def test_snapshot_validation_uses_canonical_decision_regime_keys_and_keeps_unavailable_rows():
    base = pl.DataFrame({"checkpoint_decision_ns": [5_000_000_000, 10_000_000_000], "regime_id": [11, 12]}).lazy()
    snapshots = pl.DataFrame({"checkpoint_decision_ns": [5_000_000_000, 10_000_000_000], "structural_available": [True, False]}).lazy()
    result = snapshot_join_checks(base, snapshots)
    assert result["missing_snapshot_rows"] == 0
    assert result["duplicate_snapshot_keys"] == 0
    assert result["unavailable_snapshot_rows"] == 1


def test_snapshot_validation_rejects_duplicate_composite_snapshot_keys():
    base = pl.DataFrame({"checkpoint_decision_ns": [5_000_000_000], "regime_id": [11]}).lazy()
    snapshots = pl.DataFrame({"checkpoint_decision_ns": [5_000_000_000, 5_000_000_000], "structural_available": [True, True]}).lazy()
    assert snapshot_join_checks(base, snapshots)["duplicate_snapshot_keys"] > 0


def test_auc_contract_has_exact_directional_and_pooled_grid():
    cells = expected_auc_cells()
    assert len(cells) == 24
    assert ("TOP25", "SHORT", "300-600s") in cells
    assert ("TOP25_PLUS_STRUCTURAL", "POOLED_DIRECTION_LABELLED", ">=1800s") in cells
    assert ("TOP25", "ALIEN", "300-600s") not in cells

import pytest

from studies.Codex_structural_regime_geometry_maturity.implementation.finalize_artifacts import COLLECTION as FINALIZE_COLLECTION
from studies.Codex_structural_regime_geometry_maturity.implementation.paths import COLLECTION_ROOT
from studies.Codex_structural_regime_geometry_maturity.implementation.run_collection_grid import OUT as GRID_COLLECTION, parse_args
from studies.Codex_structural_regime_geometry_maturity.implementation.validate import COLLECTION as VALIDATE_COLLECTION


def test_corrected_collection_root_is_shared_by_producer_and_consumers():
    assert GRID_COLLECTION == COLLECTION_ROOT
    assert VALIDATE_COLLECTION == COLLECTION_ROOT
    assert FINALIZE_COLLECTION == COLLECTION_ROOT


def test_collection_cli_rejects_an_alternate_output_root():
    with pytest.raises(SystemExit):
        parse_args(["--output-root", "discarded_collection"])

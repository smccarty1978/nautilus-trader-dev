"""Contract tests for the materialized model-threshold table."""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from studies.regime_complete_canonical_store.implementation.build_threshold_contracts import (
    FROZEN_REFERENCE,
    PERCENTILES,
    REPO_ROOT,
)

TABLE = REPO_ROOT / "data/canonical/regime_complete_v1/canonical_model_threshold_contracts.parquet"


@pytest.fixture(scope="module")
def contracts() -> pl.DataFrame:
    if not TABLE.exists():
        pytest.skip(f"threshold contract table not built: {TABLE}")
    return pl.read_parquet(TABLE)


def test_every_model_has_every_requested_percentile(contracts: pl.DataFrame) -> None:
    labels = {label for label, _ in PERCENTILES}
    for model_id in FROZEN_REFERENCE:
        got = set(
            contracts.filter(pl.col("model_id") == model_id)["percentile_label"].to_list()
        )
        assert got == labels, f"{model_id} missing {labels - got}"


def test_frozen_values_are_reproduced_bit_exactly(contracts: pl.DataFrame) -> None:
    for model_id, frozen in FROZEN_REFERENCE.items():
        for label, expected in frozen.items():
            row = contracts.filter(
                (pl.col("model_id") == model_id) & (pl.col("percentile_label") == label)
            )
            assert row.height == 1
            assert row["probability_threshold"].item() == expected
            assert row["availability_status"].item() == "AVAILABLE_AND_FROZEN"
            assert row["reproduced_frozen_value_exactly"].item() is True


def test_newly_derived_levels_are_labelled_as_reconstructed(contracts: pl.DataFrame) -> None:
    for model_id, frozen in FROZEN_REFERENCE.items():
        derived = contracts.filter(
            (pl.col("model_id") == model_id)
            & (~pl.col("percentile_label").is_in(list(frozen)))
        )
        assert derived.height == len(PERCENTILES) - len(frozen)
        statuses = set(derived["availability_status"].to_list())
        assert statuses == {"RECONSTRUCTED_FROM_FROZEN_CALIBRATION_DISTRIBUTION"}
        assert derived["frozen_reference_value"].null_count() == derived.height


def test_thresholds_are_monotonic_in_tail_fraction(contracts: pl.DataFrame) -> None:
    """A smaller upper tail must demand a higher probability."""
    for model_id in FROZEN_REFERENCE:
        rows = contracts.filter(pl.col("model_id") == model_id).sort(
            "upper_tail_fraction", descending=True
        )
        values = rows["probability_threshold"].to_list()
        assert values == sorted(values), f"{model_id} thresholds not monotonic: {values}"


def test_models_do_not_share_thresholds(contracts: pl.DataFrame) -> None:
    """Bullish and bearish contracts must be independent, not copied."""
    pivot = contracts.pivot(
        values="probability_threshold", index="percentile_label", on="model_id"
    )
    models = [c for c in pivot.columns if c != "percentile_label"]
    assert len(models) == 2
    shared = pivot.filter(pl.col(models[0]) == pl.col(models[1]))
    assert shared.height == 0, "bullish and bearish thresholds must not be identical"


def test_calibration_never_reads_evaluation_outcomes(contracts: pl.DataFrame) -> None:
    """Calibration must come from a frozen population, and the 2025 overlap
    with the evaluation window must be disclosed on every single row."""
    assert contracts["calibration_start_date"].unique().to_list() == ["2025-01-01"]
    assert contracts["calibration_end_date_exclusive"].unique().to_list() == ["2026-01-01"]
    assert contracts["overlaps_evaluation_window"].all()
    assert contracts["overlap_disclosure"].null_count() == 0
    waiver = REPO_ROOT / contracts["waiver_artifact"][0]
    assert waiver.exists(), f"disclosed waiver artifact missing: {waiver}"


def test_provenance_is_complete_and_frozen(contracts: pl.DataFrame) -> None:
    for column in (
        "model_artifact_hash",
        "calibration_population_key_sha256",
        "calibration_score_sha256",
        "source_artifact",
        "source_artifact_hash",
        "quantile_method",
        "tie_policy",
        "membership_operator",
    ):
        assert contracts[column].null_count() == 0, f"{column} has nulls"
    assert contracts["is_frozen"].all()
    assert contracts["quantile_method"].unique().to_list() == ["linear"]
    assert contracts["membership_operator"].unique().to_list() == [">="]


def test_threshold_contract_ids_are_unique(contracts: pl.DataFrame) -> None:
    ids = contracts["threshold_contract_id"]
    assert ids.n_unique() == contracts.height


def test_no_2026_data_in_calibration_window(contracts: pl.DataFrame) -> None:
    """2026 is reserved for runtime OOS validation and must never calibrate."""
    assert contracts["calibration_end_date_exclusive"].str.starts_with("2026-01-01").all()

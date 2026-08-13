"""Pin the selection predicate against the frozen accepted population.

The backward-parity gate has two independent failure modes: the store could be
wrong, or the query could be wrong. This module removes the second by asserting
the predicate reproduces the accepted 5,836 trades when run against the
*accepted* observations artifact -- no new collector involved.

If these pass and full parity later fails, the defect is in the store.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from studies.regime_complete_canonical_store.analysis.generate_populations import (
    MODELS,
    load_thresholds,
)

ROOT = Path(__file__).resolve().parents[3]
ACCEPTED = (
    ROOT / "studies/full_trade_path_builder/consolidated/canonical_observations_all.parquet"
)

ACCEPTED_TOTAL = 5836
ACCEPTED_SHORT = 3329
ACCEPTED_LONG = 2507
ACCEPTED_BY_YEAR = {2021: 1147, 2022: 1206, 2023: 1187, 2024: 1149, 2025: 1147}

FROZEN_TOP_2_5 = {
    "BULLISH_STRICT_top25_gbt_v2": 0.5697449423968936,
    "LONG_STRICT_top25_gbt_v2": 0.5641320087327389,
}


@pytest.fixture(scope="module")
def accepted() -> pl.LazyFrame:
    if not ACCEPTED.exists():
        pytest.skip(f"accepted observations artifact not present: {ACCEPTED}")
    return pl.scan_parquet(ACCEPTED)


def _first_signal(accepted: pl.LazyFrame, model_id: str, threshold: float) -> pl.DataFrame:
    prefix = MODELS[model_id]["prefix"]
    return (
        accepted.filter(
            pl.col(f"{prefix}_in_domain")
            & pl.col(f"{prefix}_probability").is_not_null()
            & (pl.col(f"{prefix}_probability") >= threshold)
        )
        .sort("checkpoint_decision_ns")
        .group_by("regime_start_ns")
        .first()
        .collect()
    )


def test_threshold_table_matches_the_frozen_selection_thresholds():
    thresholds = load_thresholds()
    for model_id, expected in FROZEN_TOP_2_5.items():
        assert thresholds[(model_id, "top_2_5")] == expected


def test_first_top_2_5_reproduces_the_accepted_population(accepted: pl.LazyFrame):
    counts = {
        model_id: _first_signal(accepted, model_id, FROZEN_TOP_2_5[model_id]).height
        for model_id in MODELS
    }
    assert counts["BULLISH_STRICT_top25_gbt_v2"] == ACCEPTED_SHORT
    assert counts["LONG_STRICT_top25_gbt_v2"] == ACCEPTED_LONG
    assert sum(counts.values()) == ACCEPTED_TOTAL


def test_selection_splits_by_year_exactly(accepted: pl.LazyFrame):
    frames = [
        _first_signal(accepted, model_id, FROZEN_TOP_2_5[model_id]).select("study_year")
        for model_id in MODELS
    ]
    by_year = (
        pl.concat(frames)
        .group_by("study_year")
        .len()
        .sort("study_year")
    )
    assert dict(zip(by_year["study_year"], by_year["len"])) == ACCEPTED_BY_YEAR


def test_membership_operator_is_inclusive(accepted: pl.LazyFrame):
    """`>=` is the frozen operator; `>` would drop exact-threshold rows."""
    model_id = "BULLISH_STRICT_top25_gbt_v2"
    threshold = FROZEN_TOP_2_5[model_id]
    exclusive = (
        accepted.filter(
            pl.col("bullish_in_domain") & (pl.col("bullish_probability") > threshold)
        )
        .sort("checkpoint_decision_ns")
        .group_by("regime_start_ns")
        .first()
        .collect()
        .height
    )
    assert exclusive <= ACCEPTED_SHORT


def test_a_tighter_threshold_selects_a_subset_of_regimes(accepted: pl.LazyFrame):
    """Monotonicity: Top-1% regimes must be a subset of Top-2.5% regimes."""
    thresholds = load_thresholds()
    model_id = "BULLISH_STRICT_top25_gbt_v2"
    loose = set(
        _first_signal(accepted, model_id, thresholds[(model_id, "top_2_5")])[
            "regime_start_ns"
        ].to_list()
    )
    tight = set(
        _first_signal(accepted, model_id, thresholds[(model_id, "top_1")])[
            "regime_start_ns"
        ].to_list()
    )
    assert tight <= loose
    assert len(tight) < len(loose), "a tighter threshold must select fewer regimes"


def test_out_of_domain_scores_never_qualify_an_entry(accepted: pl.LazyFrame):
    """Exploratory scores exist in the store but may not create a candidate."""
    model_id = "BULLISH_STRICT_top25_gbt_v2"
    threshold = FROZEN_TOP_2_5[model_id]
    exploratory = (
        accepted.filter(
            ~pl.col("bullish_in_domain")
            & (pl.col("bullish_probability") >= threshold)
        )
        .select(pl.len())
        .collect()
        .item()
    )
    assert exploratory > 0, "fixture assumes exploratory high scores exist"
    selected = _first_signal(accepted, model_id, threshold)
    assert selected["bullish_in_domain"].all()

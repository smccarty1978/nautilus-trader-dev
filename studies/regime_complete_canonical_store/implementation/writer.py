"""Materialize the frozen wide schemas from the collector's compact output.

The collector carries only genuinely varying values through Python. Everything
constant within a regime, or derivable from an exact key, is expanded here with
vectorized expressions. This is a pure reshape of collector state: it performs
no signal detection, no matching, and no lookup that is not an exact key join.
"""
from __future__ import annotations

import polars as pl

from .collector import PATH_FIELDS
from .identity import CONTRACT_VERSION

NS = 1_000_000_000
CT = "America/Chicago"
RTH_OPEN_MINUTE = 8 * 60 + 30
RTH_CLOSE_MINUTE = 15 * 60

# The v.0 volume-continuous catalog series does not expose per-leg contract
# identity; the continuous series is the contract of record for this store.
CONTINUOUS_CONTRACT_ID = "NQ.XCME.v.0"

PATH_SCHEMA = {
    "regime_sequence_number": pl.Int64,
    "path_event_ns": pl.Int64,
    "path_init_ns": pl.Int64,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "atr_current": pl.Float64,
    "regime_state": pl.Int64,
    "established_state": pl.Boolean,
    "last_score_decision_ns": pl.Int64,
    "last_bullish_probability": pl.Float64,
    "last_bearish_probability": pl.Float64,
}


def _chicago_minute(column: str) -> pl.Expr:
    """Minutes since local midnight.

    `dt.hour()` returns Int8, so `hour * 60` overflows silently: 8 * 60 = 480
    wraps to -32, and the RTH window test is then never true. Every path row in
    the first build was consequently labelled ETH. Cast before multiplying.
    """
    local = pl.from_epoch(pl.col(column), time_unit="ns").dt.convert_time_zone(CT)
    return local.dt.hour().cast(pl.Int32) * 60 + local.dt.minute().cast(pl.Int32)


def _session_expr(column: str) -> pl.Expr:
    minute = _chicago_minute(column)
    return (
        pl.when(pl.col(column).is_null())
        .then(None)
        .when(minute.is_between(RTH_OPEN_MINUTE, RTH_CLOSE_MINUTE, closed="left"))
        .then(pl.lit("RTH"))
        .otherwise(pl.lit("ETH"))
    )


def _year_expr(column: str) -> pl.Expr:
    return (
        pl.from_epoch(pl.col(column), time_unit="ns")
        .dt.convert_time_zone(CT)
        .dt.year()
        .cast(pl.Int32)
    )


def build_regimes(regimes: list[dict], source_partition: str) -> pl.DataFrame:
    """One row per regime. Censored regimes keep null terminal fields."""
    if not regimes:
        return pl.DataFrame(schema=_REGIME_EMPTY_SCHEMA)
    cleaned = [{k: v for k, v in r.items() if not k.startswith("_")} for r in regimes]
    frame = pl.DataFrame(cleaned, infer_schema_length=None)
    return (
        frame.with_columns(
            contract_id=pl.lit(CONTINUOUS_CONTRACT_ID),
            entry_year=_year_expr("regime_start_decision_ns"),
            duration_seconds=(
                pl.col("regime_end_decision_ns") - pl.col("regime_start_decision_ns")
            )
            / NS,
            path_is_complete=pl.col("regime_end_reason") == "opposing_flip",
            path_censor_reason=pl.when(pl.col("regime_end_reason") == "opposing_flip")
            .then(None)
            .otherwise(pl.col("regime_end_reason")),
            source_partition=pl.lit(source_partition),
        )
        .with_columns(
            duration_bars_1m=(pl.col("duration_seconds") / 60).cast(pl.Int64),
        )
        .sort("regime_sequence_number")
    )


def build_paths(
    paths: list[tuple], regimes: pl.DataFrame, source_partition: str
) -> pl.DataFrame:
    """One row per completed 1s bar, keyed to its owning regime.

    Entry-dependent quantities are forbidden here by contract (SPEC 5.3); this
    function computes none and `validate_pilot.py` asserts their absence.
    """
    if not paths:
        return pl.DataFrame(schema=PATH_SCHEMA)
    frame = pl.DataFrame(paths, schema=PATH_SCHEMA, orient="row")

    keys = regimes.select(
        "regime_sequence_number",
        "regime_id",
        "regime_start_decision_ns",
        "regime_established_decision_ns",
        "regime_end_decision_ns",
        "atr_at_regime_start",
        "collector_version",
    )
    frame = frame.join(keys, on="regime_sequence_number", how="left")

    return (
        frame.sort(["regime_sequence_number", "path_init_ns"])
        .with_columns(
            instrument_id=pl.lit("NQ.XCME"),
            contract_id=pl.lit(CONTINUOUS_CONTRACT_ID),
            contract_version=pl.lit(CONTRACT_VERSION),
            path_decision_ns=pl.col("path_init_ns"),
            path_sequence_in_regime=pl.int_range(pl.len()).over(
                "regime_sequence_number"
            ),
            seconds_from_regime_start=(
                pl.col("path_init_ns") - pl.col("regime_start_decision_ns")
            )
            / NS,
            seconds_from_established=(
                pl.col("path_init_ns") - pl.col("regime_established_decision_ns")
            )
            / NS,
            session=_session_expr("path_init_ns"),
            entry_year=_year_expr("path_init_ns"),
            score_age_seconds=(
                pl.col("path_init_ns") - pl.col("last_score_decision_ns")
            )
            / NS,
            source_partition=pl.lit(source_partition),
        )
        .with_columns(
            is_carried_forward=pl.col("score_age_seconds") > 0,
            is_regime_start_row=pl.col("path_sequence_in_regime") == 0,
            is_established_row=(
                pl.col("path_init_ns") == pl.col("regime_established_decision_ns")
            ),
            is_opposing_flip_row=(
                pl.col("path_init_ns") == pl.col("regime_end_decision_ns")
            ).fill_null(False),
            is_terminal_row=pl.col("path_init_ns")
            == pl.col("path_init_ns").max().over("regime_sequence_number"),
        )
        .drop("regime_start_decision_ns", "regime_end_decision_ns")
    )


def build_scores(rows: list[dict], source_partition: str) -> pl.DataFrame:
    """Score rows pass through unchanged; only partition metadata is added.

    The inherited column set and values are preserved exactly so that RTH rows
    can be compared byte-for-byte against the accepted artifact.
    """
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows, infer_schema_length=None).with_columns(
        contract_id=pl.lit(CONTINUOUS_CONTRACT_ID),
        entry_year=_year_expr("checkpoint_decision_ns"),
        source_partition=pl.lit(source_partition),
    )


_REGIME_EMPTY_SCHEMA = {
    "instrument_id": pl.String,
    "regime_id": pl.String,
    "regime_sequence_number": pl.Int64,
    "regime_direction": pl.Int64,
    "regime_start_decision_ns": pl.Int64,
    "regime_start_event_ns": pl.Int64,
    "regime_start_price": pl.Float64,
    "atr_at_regime_start": pl.Float64,
    "regime_established_decision_ns": pl.Int64,
    "atr_at_established": pl.Float64,
    "established_reached": pl.Boolean,
    "regime_end_decision_ns": pl.Int64,
    "regime_end_event_ns": pl.Int64,
    "regime_end_price": pl.Float64,
    "regime_end_reason": pl.String,
    "atr_at_regime_end": pl.Float64,
    "session_at_start": pl.String,
    "session_at_established": pl.String,
    "session_at_end": pl.String,
    "path_start_ns": pl.Int64,
    "path_end_ns": pl.Int64,
    "path_row_count": pl.Int64,
    "collector_version": pl.String,
    "regime_engine_version": pl.String,
    "contract_version": pl.String,
}

"""Aggregation into the frozen deliverable tables (SPEC 6).

One aggregation expression list is shared by every grouping -- the age x progress
matrix, the velocity quartiles, the A/B comparison, and the year/side slices -- so a
metric cannot mean one thing in one table and something else in another.

Three denominators exist and are never interchanged (SPEC 6.1):

    over ALL arms in the group        p_confirm_before_1atr, p_stopped,
                                      p_session_unresolved, p_ambiguous
    over arms with a MEASURABLE flip  p_flip_le_120s/180s/300s, median_secs_to_flip
                                      (the 54 `sealed_boundary_censored` regimes have a
                                      NULL flip time and are right-censored, never
                                      counted as "did not flip" -- `n_flip_censored`
                                      is emitted alongside)
    over CONFIRMERS only              mae_to_confirm_*, return_at_confirm_*,
                                      median_eventual_mfe and every p_mfe_ge_*

Every confirmer-denominated column is emitted next to `n_confirmed` so the reader
can always see which denominator produced it.
"""
from __future__ import annotations

import itertools

import polars as pl

from studies.p90_regime_age_progress_diagnostic.implementation.population import (
    AGE_LABELS,
    MFE_LABELS,
    THIN_CELL_N,
)

VELOCITY_LABELS = ("Q1_slowest", "Q2", "Q3", "Q4_fastest")


def _p(expr: pl.Expr) -> pl.Expr:
    """Share of the non-null values of a boolean column.

    `mean()` skips nulls in polars, which is exactly right here: a right-censored
    flip (null) must not be counted as "did not flip", and a non-confirmer must not
    be counted as a zero-MFE confirmer.
    """
    return expr.mean()


# The confirmers-only denominator, applied explicitly rather than relied upon as a
# side effect of nulls. See the block comment on the Outcome-2 aggregations below.
CONFIRMER = pl.col("confirmed")


AGGS = [
    pl.len().alias("n"),
    pl.col("confirmed").sum().alias("n_confirmed"),
    (~pl.col("walk_valid")).sum().alias("n_walk_invalid"),
    pl.col("flip_censored").sum().alias("n_flip_censored"),
    pl.col("age_ge_1800s").mean().alias("pct_age_ge_1800s"),

    # ---- Outcome 1 (denominator: arms with a measurable flip) -------------
    pl.col("seconds_to_prevailing_flip").median().alias("median_secs_to_flip"),
    _p(pl.col("flip_le_120s")).alias("p_flip_le_120s"),
    _p(pl.col("flip_le_180s")).alias("p_flip_le_180s"),
    _p(pl.col("flip_le_300s")).alias("p_flip_le_300s"),
    _p(pl.col("flip_le_300s_session_gated")).alias("p_flip_le_300s_session_gated"),
    _p(pl.col("flip_window_crosses_session_close")).alias("pct_window_crosses_close"),

    # ---- Outcome 2 (denominator: ALL arms) --------------------------------
    _p(pl.col("confirmed")).alias("p_confirm_before_1atr"),
    (pl.col("terminal_label") == "STOPPED_BEFORE_CONFIRM").mean().alias("p_stopped"),
    (pl.col("terminal_label") == "SESSION_CLOSE_UNRESOLVED").mean().alias("p_session_unresolved"),
    _p(pl.col("ambiguous")).alias("p_ambiguous"),

    # ---- Outcome 2 (denominator: CONFIRMERS) ------------------------------
    # `.filter(CONFIRMER)` is MANDATORY on every one of these and is not redundant
    # with a null check. `measure_to_confirm` populates seconds/mae/return_to_confirm
    # whenever the confirming flip was REACHED inside the window -- including trades
    # that hit the 1 ATR stop FIRST and are labelled STOPPED_BEFORE_CONFIRM. 4,186 of
    # 4,427 population-A non-confirmers carry a non-null `return_at_confirm_atr`.
    # Pooling them inflates MAE (a stopped trade has MAE >= 1.0 by construction:
    # p50 0.965 pooled vs 0.349 confirmers-only) and deflates return (0.558 vs 0.833
    # in the >900s bucket). Found by lookahead-auditor pass 2 (CRITICAL); the leak had
    # reached primary_matrix.csv, the study's main deliverable.
    pl.col("seconds_to_confirm").filter(CONFIRMER).median().alias("median_secs_to_confirm"),
    # `interpolation="linear"` is stated explicitly on every quantile. Polars'
    # `quantile()` defaults to "nearest" while `median()` is linear, so an unqualified
    # `quantile(0.50)` is NOT the median on even-sized samples -- gate V-DENOM caught
    # the two disagreeing in 8 of 40 cells. Fixing the gate to match the table would
    # have hidden the inconsistency; fixing the table makes p50 and the median the
    # same number, which is what a reader assumes.
    pl.col("mae_to_confirm_atr").filter(CONFIRMER)
      .quantile(0.50, interpolation="linear").alias("mae_to_confirm_p50"),
    pl.col("mae_to_confirm_atr").filter(CONFIRMER)
      .quantile(0.75, interpolation="linear").alias("mae_to_confirm_p75"),
    pl.col("mae_to_confirm_atr").filter(CONFIRMER)
      .quantile(0.90, interpolation="linear").alias("mae_to_confirm_p90"),
    pl.col("return_at_confirm_atr").filter(CONFIRMER).median().alias("median_return_at_confirm"),
    pl.col("return_at_confirm_atr").filter(CONFIRMER).mean().alias("mean_return_at_confirm"),

    # ---- Outcome 3 (denominator: CONFIRMERS) ------------------------------
    # `outcomes.py` already leaves these NULL for non-confirmers, so the filter is
    # currently redundant -- it is stated anyway so the denominator is a property of
    # THIS table rather than of an upstream module that could change.
    pl.col("eventual_max_mfe_atr").filter(CONFIRMER).median().alias("median_eventual_mfe"),
    pl.col("mfe_ge_1_0").filter(CONFIRMER).mean().alias("p_mfe_ge_1"),
    pl.col("mfe_ge_2_0").filter(CONFIRMER).mean().alias("p_mfe_ge_2"),
    pl.col("mfe_ge_3_0").filter(CONFIRMER).mean().alias("p_mfe_ge_3"),

    # ---- descriptive state at the arm -------------------------------------
    pl.col("regime_age_s").median().alias("median_age_s"),
    pl.col("running_mfe_atr").median().alias("median_running_mfe"),
    pl.col("velocity_atr_per_min").median().alias("median_velocity"),
]

_ZERO_FILL = ("n", "n_confirmed", "n_walk_invalid", "n_flip_censored")


def _complete(df: pl.DataFrame, keys: dict[str, tuple]) -> pl.DataFrame:
    """Re-attach every frozen cell, including empty ones (SPEC 6.1).

    A dropped empty cell is indistinguishable in a report from a cell that was never
    part of the grid, which is how a partition silently shrinks between studies.
    """
    names = list(keys)
    grid = pl.DataFrame(
        [dict(zip(names, combo)) for combo in itertools.product(*keys.values())]
    ).with_columns(_o=pl.int_range(pl.len()))
    out = grid.join(df, on=names, how="left")
    return (
        out.with_columns([pl.col(c).fill_null(0) for c in _ZERO_FILL if c in out.columns])
        .with_columns(thin_cell=pl.col("n") < THIN_CELL_N)
        .sort("_o").drop("_o")
    )


def cell_table(events: pl.DataFrame) -> pl.DataFrame:
    """The full 2 x 5 x 4 = 40-cell grid, every cell retained."""
    agg = events.group_by(["population", "age_bucket", "mfe_bucket"]).agg(AGGS)
    return _complete(agg, {"population": ("A", "B"),
                           "age_bucket": AGE_LABELS,
                           "mfe_bucket": MFE_LABELS})


def primary_matrix(cells: pl.DataFrame) -> pl.DataFrame:
    """SPEC 6 deliverable #5 -- THE main deliverable, five columns per cell."""
    return cells.select(
        "population", "age_bucket", "mfe_bucket", "n", "n_confirmed", "thin_cell",
        "p_flip_le_300s", "p_confirm_before_1atr",
        "median_return_at_confirm", "median_eventual_mfe",
    )


def outcome1_table(cells: pl.DataFrame) -> pl.DataFrame:
    return cells.select(
        "population", "age_bucket", "mfe_bucket", "n", "n_flip_censored", "thin_cell",
        "median_secs_to_flip", "p_flip_le_120s", "p_flip_le_180s", "p_flip_le_300s",
        "pct_window_crosses_close", "p_flip_le_300s_session_gated", "pct_age_ge_1800s",
    )


def outcome2_table(cells: pl.DataFrame) -> pl.DataFrame:
    return cells.select(
        "population", "age_bucket", "mfe_bucket", "n", "n_confirmed", "thin_cell",
        "p_confirm_before_1atr", "p_stopped", "p_session_unresolved", "p_ambiguous",
        "n_walk_invalid", "median_secs_to_confirm",
        "mae_to_confirm_p50", "mae_to_confirm_p75", "mae_to_confirm_p90",
        "median_return_at_confirm", "mean_return_at_confirm",
    )


def outcome3_table(cells: pl.DataFrame) -> pl.DataFrame:
    return cells.select(
        "population", "age_bucket", "mfe_bucket", "n", "n_confirmed", "thin_cell",
        "median_eventual_mfe", "p_mfe_ge_1", "p_mfe_ge_2", "p_mfe_ge_3",
    )


def velocity_table(events: pl.DataFrame, edges) -> pl.DataFrame:
    """SPEC 3.1 -- quartiles of the population-A velocity distribution, frozen once."""
    q1, q2, q3 = edges
    lo = {"Q1_slowest": None, "Q2": q1, "Q3": q2, "Q4_fastest": q3}
    hi = {"Q1_slowest": q1, "Q2": q2, "Q3": q3, "Q4_fastest": None}
    agg = events.group_by(["population", "velocity_quartile"]).agg(AGGS)
    out = _complete(agg, {"population": ("A", "B"), "velocity_quartile": VELOCITY_LABELS})
    return out.with_columns(
        edge_lo=pl.col("velocity_quartile").replace_strict(lo, return_dtype=pl.Float64),
        edge_hi=pl.col("velocity_quartile").replace_strict(hi, return_dtype=pl.Float64),
    ).select(
        "population", "velocity_quartile", "edge_lo", "edge_hi", "n", "n_confirmed",
        "thin_cell", "median_age_s", "median_running_mfe", "median_velocity",
        "p_flip_le_300s", "p_confirm_before_1atr",
        "median_return_at_confirm", "median_eventual_mfe", "p_mfe_ge_3",
    )


def population_comparison(events: pl.DataFrame, comparison: dict) -> pl.DataFrame:
    """SPEC 5 -- A vs B on identical metrics, computed by the same functions."""
    agg = events.group_by("population").agg(AGGS)
    out = _complete(agg, {"population": ("A", "B")})
    return out.select(
        "population", "n", "n_confirmed", "median_age_s", "median_running_mfe",
        "median_velocity", "p_flip_le_300s", "p_confirm_before_1atr",
        "median_return_at_confirm", "median_eventual_mfe", "p_mfe_ge_3",
        "median_secs_to_confirm", "mae_to_confirm_p90", "pct_age_ge_1800s",
    ).with_columns(
        n_same_timestamp=pl.lit(comparison["n_same_timestamp"]),
        n_different_timestamp=pl.lit(comparison["n_different_timestamp"]),
        n_only_a=pl.lit(comparison["n_only_a"]),
        n_only_b=pl.lit(comparison["n_only_b"]),
    )


def year_side_stability(events: pl.DataFrame, age_buckets: tuple[str, str]) -> pl.DataFrame:
    """SPEC 6 deliverable #11 -- the strongest age contrast only, by year and side.

    Deliberately narrow. The brief asks for enough stability information to tell a
    structural effect from a pooled artifact, not a dozen tables.
    """
    sub = events.filter(
        (pl.col("population") == "A") & pl.col("age_bucket").is_in(list(age_buckets))
    )
    frames = []
    for kind, col in (("side", "side"), ("year", "entry_year")):
        agg = sub.group_by([col, "age_bucket"]).agg(AGGS)
        frames.append(agg.select(
            pl.lit(kind).alias("slice_kind"),
            pl.col(col).cast(pl.Utf8).alias("slice"),
            pl.col("age_bucket").alias("cell"),
            "n", "n_confirmed",
            (pl.col("n") < THIN_CELL_N).alias("thin_cell"),
            "p_flip_le_300s", "p_confirm_before_1atr",
            "median_return_at_confirm", "median_eventual_mfe", "p_mfe_ge_3",
        ))
    return pl.concat(frames).sort(["slice_kind", "cell", "slice"])

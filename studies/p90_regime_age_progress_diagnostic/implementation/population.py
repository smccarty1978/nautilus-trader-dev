"""P90 arm populations A (original model domain) and B (inherited >600s gate).

Only ONE parameter separates the two populations, and it is passed as an argument
to the accepted arming rule rather than reimplemented (SPEC 2.3):

    A  MIN_AGE = 0    -> the model's own eligibility contract gates age (>120s)
    B  MIN_AGE = 600  -> the recent-study population, which must reproduce 8,950

Everything read at the arm -- ``seconds_from_regime_start``, ``running_mfe_atr``,
``current_progress_atr``, ``atr_at_checkpoint`` -- is a column the collector already
computed at that checkpoint's own decision timestamp under the frozen
``feature_source_invariant``. This module computes no new state variable and reads
no path, no future score, and no outcome. The bucket and velocity derivations below
are pure functions of those frozen at-arm columns (SPEC 4).
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.armed_fade_score_path_progression.implementation.arming import (
    ARM_LEVEL,
    _assert_arming_population_is_complete,
    load_observations,
    threshold_expr,
)
from studies.model_driven_entry_exit_discovery.implementation.candidates import STORE

MIN_AGE_A = 0.0
MIN_AGE_B = 600.0

# Frozen before any economics was inspected (SPEC 3). Closed-left / open-right.
# The first edge is LABELLED 120 but the realized in-domain floor is 125s -- the
# 5s grid with a strict `> 120` gate. Recorded in SPEC 1.2(a), not adjusted.
AGE_EDGES = ((120.0, 240.0), (240.0, 300.0), (300.0, 600.0),
             (600.0, 900.0), (900.0, float("inf")))
AGE_LABELS = ("120-240s", "240-300s", "300-600s", "600-900s", ">900s")

# `running_mfe_atr`, whose eligibility floor is 1.0 ATR. There is deliberately NO
# 0.5-1.0 bucket: the 0.5 floor seen in prior discovery belongs to
# `current_progress_atr`, a different column (SPEC 1.3).
MFE_EDGES = ((1.0, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, float("inf")))
MFE_LABELS = ("1-2 ATR", "2-3 ATR", "3-5 ATR", ">5 ATR")

TRAINING_AGE_CEILING_S = 1800.0   # SPEC 1.2(b) extrapolation disclosure
THIN_CELL_N = 30                  # SPEC 6.1


def arm_population(scored: pl.DataFrame, min_age_s: float,
                   *, require_full_population: bool = True) -> pl.DataFrame:
    """First true Top-10 crossing from below, one arm per regime, age > `min_age_s`.

    This is a **parameterised re-statement** of
    `armed_fade_score_path_progression.arming.arm_population`, not a call into it:
    that function hard-codes `MIN_REGIME_AGE_S = 600` at module scope, and widening
    an accepted, already-audited module that other studies import is a worse risk
    than restating six lines here. Equivalence at `min_age_s = 600` is proven twice
    -- by `tests/test_diagnostic_contracts.py::test_matches_accepted_arm_rule_at_600s`
    on a synthetic frame, and by gate `V_PARITY_population_b_8950` reproducing the
    accepted 8,950-arm population on the real store.

    `_assert_arming_population_is_complete` is imported from the accepted module and
    called here rather than reimplemented, so the partial-year guard cannot drift
    from the original. Dropping it was flagged by lookahead-auditor pass 1 (WARNING):
    the from-below test is a `shift(1).over("regime_id")`, so a pre-filtered year
    slice would drop each regime's true predecessor at the boundary and manufacture
    phantom crossings.

    The three accepted conventions are intact:

    * the predecessor dispatch must EXIST -- a regime whose first in-domain dispatch
      already qualifies is not armed, because no crossing was ever observed and
      `fill_value=False` would supply that missing evidence;
    * `prev_q` is the previous in-domain dispatch IN THE SAME REGIME, which is the
      only observation a live trader could have seen;
    * one arm per regime.

    `require_full_population` exists only so unit tests can arm on a synthetic frame;
    production callers must leave it True.
    """
    if require_full_population:
        _assert_arming_population_is_complete(scored)
    df = scored.with_columns(q=(pl.col("probability") >= threshold_expr(ARM_LEVEL)))
    df = df.with_columns(prev_q=pl.col("q").shift(1).over("regime_id"))
    return (
        df.filter(
            pl.col("q")
            & pl.col("prev_q").is_not_null()
            & ~pl.col("prev_q")
            & (pl.col("seconds_from_regime_start") > min_age_s)
        )
        .sort("checkpoint_decision_ns")
        .group_by("regime_id")
        .first()
        .sort("checkpoint_decision_ns")
    )


def attach_eligibility_columns(arms: pl.DataFrame) -> pl.DataFrame:
    """Join `retained_mfe_ratio` and `new_progress_windows` onto the armed rows.

    The accepted `load_scored` BASE_COLUMNS list does not carry these two, and this
    study's Deliverables Manifest requires them on every event row so a reader can
    confirm each arm's eligibility from the artifact itself. Read directly from the
    store on the arm's own (regime_id, checkpoint_decision_ns) key -- these are
    at-checkpoint collector columns, not derived, so the join adds no new state.

    `load_scored` is left untouched: it is shared with accepted studies, and widening
    it here would silently change their memory profile.
    """
    keys = arms.select("regime_id", "checkpoint_decision_ns")
    extra = (
        pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
        .filter(pl.col("bullish_in_domain") | pl.col("bearish_in_domain"))
        .select("regime_id", "checkpoint_decision_ns",
                "retained_mfe_ratio", "new_progress_windows")
        .collect()
    )
    out = arms.join(extra, on=["regime_id", "checkpoint_decision_ns"], how="left")
    if out.height != arms.height:
        raise ValueError(
            f"eligibility join changed row count {arms.height} -> {out.height}; "
            "(regime_id, checkpoint_decision_ns) is not unique in the score store"
        )
    missing = int(out["retained_mfe_ratio"].is_null().sum())
    if missing:
        raise ValueError(f"{missing} armed rows found no eligibility columns")
    return out


def _bucket_expr(col: str, edges, labels) -> pl.Expr:
    """Closed-left / open-right bucket assignment; exhaustive by construction."""
    expr = pl.when(pl.col(col) < edges[0][1]).then(pl.lit(labels[0]))
    for (_, hi), lab in zip(edges[1:-1], labels[1:-1]):
        expr = expr.when(pl.col(col) < hi).then(pl.lit(lab))
    return expr.otherwise(pl.lit(labels[-1]))


def with_dimensions(arms: pl.DataFrame) -> pl.DataFrame:
    """Attach the frozen age / progress buckets and the progress-velocity column.

    `regime_progress_rate` is descriptive (SPEC 3.1). It is a ratio of two values
    frozen at the arm, so it carries no information the arm row did not already have.
    """
    return arms.with_columns(
        regime_age_s=pl.col("seconds_from_regime_start"),
        side=pl.when(pl.col("direction") == 1).then(pl.lit("LONG")).otherwise(pl.lit("SHORT")),
        prevailing_regime=-pl.col("direction"),
        age_bucket=_bucket_expr("seconds_from_regime_start", AGE_EDGES, AGE_LABELS),
        mfe_bucket=_bucket_expr("running_mfe_atr", MFE_EDGES, MFE_LABELS),
        age_ge_1800s=pl.col("seconds_from_regime_start") >= TRAINING_AGE_CEILING_S,
        velocity_atr_per_min=(
            pl.col("running_mfe_atr") / (pl.col("seconds_from_regime_start") / 60.0)
        ),
    )


def velocity_quartile_edges(pop_a: pl.DataFrame) -> tuple[float, float, float]:
    """Frozen ONCE on population A and reused for every velocity table (SPEC 3.1).

    Computing separate edges per population would make the A-vs-B velocity rows
    incomparable -- each population would be measured against its own ruler.
    """
    v = pop_a["velocity_atr_per_min"]
    # `interpolation="linear"` stated explicitly, matching every other quantile in this
    # study (polars defaults to "nearest", which is not the median on even samples).
    # The realised edges are recorded in results/partition_manifest.json.
    return (float(v.quantile(0.25, interpolation="linear")),
            float(v.quantile(0.50, interpolation="linear")),
            float(v.quantile(0.75, interpolation="linear")))


def with_velocity_quartile(df: pl.DataFrame, edges) -> pl.DataFrame:
    q1, q2, q3 = edges
    return df.with_columns(
        velocity_quartile=pl.when(pl.col("velocity_atr_per_min") < q1).then(pl.lit("Q1_slowest"))
        .when(pl.col("velocity_atr_per_min") < q2).then(pl.lit("Q2"))
        .when(pl.col("velocity_atr_per_min") < q3).then(pl.lit("Q3"))
        .otherwise(pl.lit("Q4_fastest"))
    )


def build_populations() -> dict:
    """Both arm populations plus the A-vs-B reconciliation the SPEC 5 comparison needs.

    Returns the UNION of distinct (regime_id, arm_ns) events as `unique_events`, so
    every outcome is simulated exactly once and A and B can never disagree on a
    shared event because of a re-derived window.
    """
    scored = load_observations()
    a = with_dimensions(attach_eligibility_columns(arm_population(scored, MIN_AGE_A)))
    b = with_dimensions(attach_eligibility_columns(arm_population(scored, MIN_AGE_B)))

    edges = velocity_quartile_edges(a)
    a = with_velocity_quartile(a, edges)
    b = with_velocity_quartile(b, edges)

    ja = a.select("regime_id", a_ns=pl.col("checkpoint_decision_ns"),
                  a_age=pl.col("seconds_from_regime_start"))
    jb = b.select("regime_id", b_ns=pl.col("checkpoint_decision_ns"),
                  b_age=pl.col("seconds_from_regime_start"))
    joined = ja.join(jb, on="regime_id", how="full", coalesce=True)

    both = joined.filter(pl.col("a_ns").is_not_null() & pl.col("b_ns").is_not_null())
    comparison = {
        "n_a": a.height,
        "n_b": b.height,
        "n_in_both": both.height,
        "n_same_timestamp": both.filter(pl.col("a_ns") == pl.col("b_ns")).height,
        "n_different_timestamp": both.filter(pl.col("a_ns") != pl.col("b_ns")).height,
        "n_only_a": joined.filter(pl.col("b_ns").is_null()).height,
        "n_only_b": joined.filter(pl.col("a_ns").is_null()).height,
        # Gate-relevant: B requires age > 600, so `<= 600` is exactly what B excludes.
        # Distinct from the bucket-sum (strictly < 600), which is 12 lower because 12
        # arms sit at exactly 600.0s and fall in the closed-left `600-900s` bucket.
        "n_a_arms_excluded_by_600s_gate": a.filter(
            pl.col("seconds_from_regime_start") <= MIN_AGE_B).height,
        "n_a_arms_strictly_below_600s": a.filter(
            pl.col("seconds_from_regime_start") < MIN_AGE_B).height,
    }
    d = both.filter(pl.col("a_ns") != pl.col("b_ns"))
    if d.height:
        comparison["diff_median_a_age_s"] = float(d["a_age"].median())
        comparison["diff_median_b_age_s"] = float(d["b_age"].median())

    # `qualifies_under_600s_gate` marks A rows whose OWN arm timestamp would have
    # survived the inherited gate. It is NOT the same as "this regime appears in B":
    # 354 regimes appear in B at a different, later timestamp (SPEC 5).
    a = a.join(jb.select("regime_id", "b_ns"), on="regime_id", how="left").with_columns(
        qualifies_under_600s_gate=pl.col("seconds_from_regime_start") > MIN_AGE_B
    )
    b = b.with_columns(
        b_ns=pl.col("checkpoint_decision_ns"),
        qualifies_under_600s_gate=pl.lit(True),
    )

    a = a.with_columns(population=pl.lit("A"))
    b = b.with_columns(population=pl.lit("B"))

    unique_events = (
        pl.concat([
            a.select("regime_id", "checkpoint_decision_ns", "direction",
                     "checkpoint_reference_price", "atr_at_checkpoint"),
            b.select("regime_id", "checkpoint_decision_ns", "direction",
                     "checkpoint_reference_price", "atr_at_checkpoint"),
        ])
        .unique(subset=["regime_id", "checkpoint_decision_ns"], keep="first")
        .sort(["regime_id", "checkpoint_decision_ns"])
    )

    return {
        "scored": scored,
        "A": a,
        "B": b,
        "unique_events": unique_events,
        "comparison": comparison,
        "velocity_edges": edges,
    }


def eligibility_base_rates(scored: pl.DataFrame) -> pl.DataFrame:
    """P90 qualify RATE among eligible checkpoints, by age bucket (SPEC 2.5).

    This is the mechanism table: it separates "the >600s gate excluded young
    regimes" from "the model itself almost never scores P90 in young regimes".
    Observation-level, no arming rule applied.
    """
    df = scored.with_columns(
        q=(pl.col("probability") >= threshold_expr(ARM_LEVEL)),
        age_bucket=_bucket_expr("seconds_from_regime_start", AGE_EDGES, AGE_LABELS),
    )
    counts = df.group_by("age_bucket").agg(
        n_eligible_checkpoints=pl.len(),
        n_p90_qualifying=pl.col("q").sum(),
    )
    order = pl.DataFrame({"age_bucket": list(AGE_LABELS),
                          "_o": list(range(len(AGE_LABELS)))})
    return (
        order.join(counts, on="age_bucket", how="left")
        .with_columns(
            n_eligible_checkpoints=pl.col("n_eligible_checkpoints").fill_null(0),
            n_p90_qualifying=pl.col("n_p90_qualifying").fill_null(0),
        )
        .with_columns(
            qualify_rate=pl.when(pl.col("n_eligible_checkpoints") > 0)
            .then(pl.col("n_p90_qualifying") / pl.col("n_eligible_checkpoints"))
            .otherwise(None)
        )
        .sort("_o").drop("_o")
    )


def first_eligible_age_by_regime(scored: pl.DataFrame) -> pl.DataFrame:
    """Age at which each regime FIRST becomes model-eligible (SPEC 2.5 evidence).

    Shows that eligibility itself admits young regimes freely, so the empty young
    P90 cells are a property of the model's scores, not of the eligibility contract.
    """
    first = (
        scored.sort("checkpoint_decision_ns").group_by("regime_id").first()
        .select("regime_id", first_age=pl.col("seconds_from_regime_start"))
        .with_columns(age_bucket=_bucket_expr("first_age", AGE_EDGES, AGE_LABELS))
    )
    counts = first.group_by("age_bucket").agg(n_regimes=pl.len())
    order = pl.DataFrame({"age_bucket": list(AGE_LABELS),
                          "_o": list(range(len(AGE_LABELS)))})
    return (
        order.join(counts, on="age_bucket", how="left")
        .with_columns(n_regimes=pl.col("n_regimes").fill_null(0))
        .sort("_o").drop("_o")
    )

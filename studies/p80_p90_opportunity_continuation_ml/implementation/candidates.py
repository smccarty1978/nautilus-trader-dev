"""Model-A candidates: the first true P80/P90 crossing from below, age > 600 s.

The rule is INHERITED VERBATIM from the accepted arm contract
(`armed_fade_score_path_progression` SPEC 3) and is validated by reproducing that
study's 2024 population exactly (SPEC 4.2 / gate V2). Nothing here is tuned.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from .common import AGE_GATE_S, BEARISH_MODEL, BULLISH_MODEL, PRIMES, assert_2024_only


def _prime_rows(scores: pl.DataFrame, prime: str, thresholds: dict) -> pl.DataFrame:
    """One primed dispatch per regime per (prime, model)."""
    out = []
    for dom, prob, model, side, direction in (
        ("bullish_in_domain", "bullish_probability", BULLISH_MODEL, "SHORT", -1),
        ("bearish_in_domain", "bearish_probability", BEARISH_MODEL, "LONG", 1),
    ):
        thr = thresholds[f"{prime}_{side}"]
        # An UNSCORED dispatch is not an observation (SPEC 4.1). Dropping nulls
        # BEFORE the crossing test is what makes `prev` the true predecessor a
        # live trader would have seen, not a null masquerading as "below".
        sub = (
            scores.filter(pl.col(dom) & pl.col(prob).is_not_null())
            .sort(["regime_id", "checkpoint_decision_ns"])
            .with_columns(
                (pl.col(prob) >= thr).alias("_q"),
                pl.col(prob).alias("_p"),
            )
        )
        sub = sub.with_columns(
            pl.col("_q").shift(1).over("regime_id").alias("_prev_q")
        )
        # `_prev_q` is null for a regime's FIRST in-domain dispatch. A first
        # dispatch that already qualifies is NOT a crossing -- there is no
        # predecessor, so a rise from below would be asserted on zero evidence.
        # `== False` is deliberate and must not become `.not_()` or a fill_value.
        primed = (
            sub.filter(
                pl.col("_q")
                & (pl.col("_prev_q") == False)  # noqa: E712 -- null must NOT pass
                & (pl.col("seconds_from_regime_start") > AGE_GATE_S)
            )
            .group_by("regime_id", maintain_order=True)
            .first()
            .with_columns(
                pl.lit(prime).alias("prime_type"),
                pl.lit(model).alias("model_id"),
                pl.lit(side).alias("side"),
                pl.lit(direction, dtype=pl.Int64).alias("direction"),
                pl.col("_p").alias("score_at_prime"),
                pl.lit(thr).alias("prime_threshold"),
            )
            .drop("_q", "_prev_q", "_p")
        )
        out.append(primed)
    return pl.concat(out, how="vertical_relaxed").sort("checkpoint_decision_ns")


def build_candidates(scores: pl.DataFrame, thresholds: dict) -> pl.DataFrame:
    """All P80 and P90 candidates for 2024, both directions."""
    frames = [_prime_rows(scores, p, thresholds) for p in PRIMES]
    cand = pl.concat(frames, how="vertical_relaxed")

    # Cross-prime state, computed on the candidate table itself so the two
    # independent populations can annotate one another without either being
    # redefined as a subset of the other.
    p80 = (cand.filter(pl.col("prime_type") == "P80")
           .select("regime_id", pl.col("checkpoint_decision_ns").alias("p80_ns"),
                   pl.col("score_at_prime").alias("p80_score")))
    p90 = (cand.filter(pl.col("prime_type") == "P90")
           .select("regime_id", pl.col("checkpoint_decision_ns").alias("p90_ns"),
                   pl.col("score_at_prime").alias("p90_score")))
    cand = cand.join(p80, on="regime_id", how="left").join(p90, on="regime_id", how="left")

    cand = cand.with_columns(
        pl.when(pl.col("p80_ns").is_not_null() & pl.col("p90_ns").is_not_null())
          .then((pl.col("p90_ns") - pl.col("p80_ns")) / 1e9)
          .otherwise(None).alias("p80_to_p90_seconds"),
        pl.col("checkpoint_decision_ns").alias("candidate_ns"),
        pl.col("checkpoint_reference_price").alias("reference_price_at_candidate"),
        pl.col("atr_at_checkpoint").alias("frozen_atr"),
        pl.from_epoch(pl.col("checkpoint_decision_ns"), time_unit="ns")
          .dt.convert_time_zone("America/Chicago").alias("_ct"),
    ).with_columns(
        pl.col("_ct").dt.month().alias("month"),
        pl.col("_ct").dt.quarter().alias("quarter"),
    ).drop("_ct")

    cand = cand.with_columns(
        pl.when(pl.col("p80_ns").is_null()).then(pl.lit("P90_ONLY"))
          .when(pl.col("p90_ns").is_null()).then(pl.lit("P80_ONLY"))
          .otherwise(pl.lit("P80_THEN_P90")).alias("overlap_class")
    )

    assert_2024_only(cand, "candidate_ns", "model A candidates")
    bad = cand.filter(pl.col("frozen_atr").is_null() | (pl.col("frozen_atr") <= 0))
    if bad.height:
        raise AssertionError(f"{bad.height} candidates carry a non-positive frozen ATR")
    return cand.sort(["prime_type", "candidate_ns"])


def reconcile_p90(cand: pl.DataFrame, accepted_arm_path) -> dict:
    """Gate V2. Reproduce the accepted 2024 arm population regime-for-regime.

    A count match is not enough: two different rules can produce the same count on
    different regimes. This compares the (regime_id, timestamp) SETS.
    """
    acc = (
        pl.read_parquet(accepted_arm_path)
        .filter(pl.col("entry_year") == 2024)
        .select("regime_id", "arm_top10_ns", "side")
    )
    mine = (cand.filter(pl.col("prime_type") == "P90")
            .select("regime_id", "candidate_ns", "side"))
    a = set(zip(acc["regime_id"].to_list(), acc["arm_top10_ns"].to_list()))
    m = set(zip(mine["regime_id"].to_list(), mine["candidate_ns"].to_list()))
    return {
        "accepted_n": len(a), "reproduced_n": len(m),
        "exact_matches": len(a & m), "missing": len(a - m), "extra": len(m - a),
        "accepted_by_side": dict(acc["side"].value_counts().iter_rows()),
        "reproduced_by_side": dict(mine["side"].value_counts().iter_rows()),
        "passed": bool(a == m),
    }


def population_breakdown(cand: pl.DataFrame) -> dict:
    """SPEC 4.4."""
    out: dict = {}
    for p in PRIMES:
        s = cand.filter(pl.col("prime_type") == p)
        out[p] = {
            "n": s.height,
            "n_regimes": s["regime_id"].n_unique(),
            "by_side": dict(s["side"].value_counts().iter_rows()),
            "by_quarter": {str(k): v for k, v in
                           sorted(s["quarter"].value_counts().iter_rows())},
            "by_month": {str(k): v for k, v in
                         sorted(s["month"].value_counts().iter_rows())},
            "by_overlap_class": dict(s["overlap_class"].value_counts().iter_rows()),
        }
    p80 = set(cand.filter(pl.col("prime_type") == "P80")["regime_id"].to_list())
    p90 = set(cand.filter(pl.col("prime_type") == "P90")["regime_id"].to_list())
    lag = cand.filter(pl.col("prime_type") == "P90")["p80_to_p90_seconds"].drop_nulls()
    out["overlap"] = {
        "regimes_with_both": len(p80 & p90),
        "p80_only": len(p80 - p90),
        "p90_without_measurable_p80": len(p90 - p80),
        "p80_to_p90_seconds_median": float(lag.median()) if lag.len() else None,
        "p80_to_p90_seconds_p25": float(lag.quantile(0.25)) if lag.len() else None,
        "p80_to_p90_seconds_p75": float(lag.quantile(0.75)) if lag.len() else None,
        "n_p90_before_p80": int((np.asarray(lag.to_list()) < 0).sum()) if lag.len() else 0,
    }
    return out

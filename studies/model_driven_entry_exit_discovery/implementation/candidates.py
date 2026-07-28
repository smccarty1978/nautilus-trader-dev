"""Entry candidate families, generated causally from the score store.

Every family below is a pure function of score observations at or before the
decision timestamp. Nothing reads a path, a future score, or an outcome.

Only true score checkpoints exist in this table — carry-forward lives on path
rows — so a "persistence" or "acceleration" rule here counts distinct model
observations, never forward-filled seconds.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"

# Frozen contracts, reproduced bit-exactly in Phase 0 of the store study.
THRESHOLDS = {
    "top_20": (0.34374423771129053, 0.3745119841718754),
    "top_10": (0.43167249785595935, 0.44559149246408103),
    "top_5": (0.5067081427626979, 0.5084619230529974),
    "top_2_5": (0.5697449423968936, 0.5641320087327389),
    "top_1": (0.6412279079940403, 0.6306416772425602),
    "top_0_5": (0.6886333180788179, 0.6706161496105166),
}

BASE_COLUMNS = [
    "checkpoint_decision_ns", "regime_id", "regime_start_ns", "entry_year",
    "checkpoint_reference_price", "atr_at_checkpoint",
    "confirmed_regime_direction", "seconds_from_regime_start",
    "bullish_probability", "bearish_probability",
    "bullish_in_domain", "bearish_in_domain",
]


def load_scored(years: tuple[int, ...] | None = None) -> pl.DataFrame:
    """In-domain RTH checkpoints, one row per model observation, direction-mapped.

    Fade contract: a bullish model in-domain fades the bullish regime SHORT; a
    bearish model in-domain goes LONG.
    """
    lf = (
        pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
        .filter(pl.col("bullish_in_domain") | pl.col("bearish_in_domain"))
        .select(BASE_COLUMNS)
    )
    if years:
        lf = lf.filter(pl.col("entry_year").is_in(list(years)))
    df = lf.sort("checkpoint_decision_ns").collect()

    return df.with_columns(
        direction=pl.when(pl.col("bullish_in_domain")).then(-1).otherwise(1),
        probability=pl.when(pl.col("bullish_in_domain"))
        .then(pl.col("bullish_probability"))
        .otherwise(pl.col("bearish_probability")),
        opposing_probability=pl.when(pl.col("bullish_in_domain"))
        .then(pl.col("bearish_probability"))
        .otherwise(pl.col("bullish_probability")),
        model_id=pl.when(pl.col("bullish_in_domain"))
        .then(pl.lit("BULLISH_STRICT_top25_gbt_v2"))
        .otherwise(pl.lit("LONG_STRICT_top25_gbt_v2")),
    ).with_columns(
        # Rank and sequence within the regime, causally: expanding, not global.
        obs_index=pl.int_range(pl.len()).over("regime_id"),
        running_max_probability=pl.col("probability").cum_max().over("regime_id"),
        prev_probability=pl.col("probability").shift(1).over("regime_id"),
        prev2_probability=pl.col("probability").shift(2).over("regime_id"),
    )


def _threshold_expr(label: str) -> pl.Expr:
    bull, bear = THRESHOLDS[label]
    return (
        pl.when(pl.col("bullish_in_domain")).then(pl.lit(bull)).otherwise(pl.lit(bear))
    )


def _qualifies(label: str) -> pl.Expr:
    return pl.col("probability") >= _threshold_expr(label)


# --------------------------------------------------------------- families


def first_qualifying(scored: pl.DataFrame, label: str) -> pl.DataFrame:
    """First checkpoint at or above the threshold, once per regime.

    This is the accepted legacy rule and the backward-parity reference.
    """
    return (
        scored.filter(_qualifies(label))
        .group_by("regime_id")
        .first()
        .sort("checkpoint_decision_ns")
        .with_columns(family=pl.lit("first_qualifying"), threshold_label=pl.lit(label))
    )


def true_crossing(scored: pl.DataFrame, label: str) -> pl.DataFrame:
    """Every entry into the band from below — the previous observation in the
    same regime did not qualify. A run of qualifying checkpoints counts once."""
    return (
        scored.with_columns(q=_qualifies(label))
        .with_columns(
            prev_q=pl.col("q").shift(1, fill_value=False).over("regime_id")
        )
        .filter(pl.col("q") & ~pl.col("prev_q"))
        .sort("checkpoint_decision_ns")
        .with_columns(family=pl.lit("true_crossing"), threshold_label=pl.lit(label))
    )


def persistence(scored: pl.DataFrame, label: str, n: int = 2) -> pl.DataFrame:
    """Enter only after `n` consecutive true observations at or above threshold.

    Counts distinct model observations. Carry-forward seconds cannot contribute,
    because they are not rows in this table.
    """
    df = scored.with_columns(q=_qualifies(label))
    run = pl.col("q").cast(pl.Int32)
    for k in range(1, n):
        run = run + pl.col("q").cast(pl.Int32).shift(k, fill_value=0).over("regime_id")
    return (
        df.with_columns(run=run)
        .filter(pl.col("q") & (pl.col("run") >= n))
        .group_by("regime_id")
        .first()
        .sort("checkpoint_decision_ns")
        .with_columns(
            family=pl.lit(f"persistence_{n}"), threshold_label=pl.lit(label)
        )
    )


def acceleration(
    scored: pl.DataFrame, label: str, min_delta: float = 0.05
) -> pl.DataFrame:
    """Qualifying, and rising by at least `min_delta` over the prior observation."""
    return (
        scored.filter(
            _qualifies(label)
            & pl.col("prev_probability").is_not_null()
            & ((pl.col("probability") - pl.col("prev_probability")) >= min_delta)
        )
        .group_by("regime_id")
        .first()
        .sort("checkpoint_decision_ns")
        .with_columns(
            family=pl.lit(f"acceleration_{min_delta}"), threshold_label=pl.lit(label)
        )
    )


def reexpansion(
    scored: pl.DataFrame, label: str, pullback: float = 0.05
) -> pl.DataFrame:
    """Score peaked, pulled back, and re-expanded to a new within-regime high.

    All three legs are measured on observations at or before the decision.
    """
    return (
        scored.filter(
            _qualifies(label)
            & pl.col("prev2_probability").is_not_null()
            & (pl.col("prev_probability") <= pl.col("prev2_probability") - pullback)
            & (pl.col("probability") >= pl.col("running_max_probability"))
        )
        .group_by("regime_id")
        .first()
        .sort("checkpoint_decision_ns")
        .with_columns(
            family=pl.lit(f"reexpansion_{pullback}"), threshold_label=pl.lit(label)
        )
    )


def spread(scored: pl.DataFrame, label: str, min_spread: float = 0.20) -> pl.DataFrame:
    """Qualifying, and the opposing model is at least `min_spread` lower.

    The opposing model is out of its own domain here by construction, so its
    score is exploratory; it conditions the entry but never qualifies one.
    """
    return (
        scored.filter(
            _qualifies(label)
            & ((pl.col("probability") - pl.col("opposing_probability")) >= min_spread)
        )
        .group_by("regime_id")
        .first()
        .sort("checkpoint_decision_ns")
        .with_columns(
            family=pl.lit(f"spread_{min_spread}"), threshold_label=pl.lit(label)
        )
    )


def age_conditioned(
    scored: pl.DataFrame, label: str, min_age_s: float = 300.0,
    max_age_s: float = 1800.0,
) -> pl.DataFrame:
    """Qualifying inside a regime-age window, measured from the regime start."""
    return (
        scored.filter(
            _qualifies(label)
            & (pl.col("seconds_from_regime_start") >= min_age_s)
            & (pl.col("seconds_from_regime_start") <= max_age_s)
        )
        .group_by("regime_id")
        .first()
        .sort("checkpoint_decision_ns")
        .with_columns(
            family=pl.lit(f"age_{int(min_age_s)}_{int(max_age_s)}"),
            threshold_label=pl.lit(label),
        )
    )


def all_crossings(scored: pl.DataFrame, label: str) -> pl.DataFrame:
    """Every crossing, retained for the reentry simulator (not one per regime)."""
    return true_crossing(scored, label)


FAMILIES = {
    "first_qualifying": first_qualifying,
    "true_crossing": true_crossing,
    "persistence_2": lambda s, l: persistence(s, l, 2),
    "persistence_3": lambda s, l: persistence(s, l, 3),
    "acceleration": lambda s, l: acceleration(s, l, 0.05),
    "reexpansion": lambda s, l: reexpansion(s, l, 0.05),
    "spread": lambda s, l: spread(s, l, 0.20),
    "age_300_1800": lambda s, l: age_conditioned(s, l, 300.0, 1800.0),
}

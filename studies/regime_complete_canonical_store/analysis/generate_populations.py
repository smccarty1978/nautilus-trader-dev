"""Analysis layer: turn the policy-free store into trade candidate populations.

Nothing here is part of collection. Every population below is a query, which is
the point of the store: none of them required a collection pass, and none of
them can influence what was retained.

Two things are demonstrated:

* Backward parity -- the accepted first-Top-2.5% population is regenerated from
  the store alone and reconciled row by row against the frozen artifact.
* Capability -- alternate thresholds, repeated crossings, post-establishment
  candidates, opposing-model warnings, and re-entry after a hypothetical stop.

No population is ranked economically and no policy is recommended; these are
data-capability demonstrations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "data/canonical/regime_complete_v1"
ACCEPTED_SUMMARIES = (
    ROOT / "studies/full_trade_path_builder/consolidated/canonical_trade_summaries_all.parquet"
)

NS = 1_000_000_000

# Which model may qualify an entry in which confirmed regime, and the resulting
# trade direction. A fade: a bullish regime is faded short, a bearish long.
MODELS = {
    "BULLISH_STRICT_top25_gbt_v2": {
        "prefix": "bullish",
        "approved_regime": 1,
        "trade_direction": "SHORT",
    },
    "LONG_STRICT_top25_gbt_v2": {
        "prefix": "bearish",
        "approved_regime": -1,
        "trade_direction": "LONG",
    },
}


def load_thresholds() -> dict[tuple[str, str], float]:
    frame = pl.read_parquet(CANONICAL / "canonical_model_threshold_contracts.parquet")
    return {
        (row["model_id"], row["percentile_label"]): row["probability_threshold"]
        for row in frame.iter_rows(named=True)
    }


def _candidates(scores: pl.LazyFrame, model_id: str, threshold: float) -> pl.LazyFrame:
    """Every checkpoint at which this model qualifies. No first-signal rule."""
    prefix = MODELS[model_id]["prefix"]
    return (
        scores.filter(
            pl.col(f"{prefix}_in_domain")
            & pl.col(f"{prefix}_probability").is_not_null()
            & (pl.col(f"{prefix}_probability") >= threshold)
        )
        .select(
            "instrument_id",
            "regime_id",
            "regime_start_ns",
            "checkpoint_decision_ns",
            "checkpoint_reference_price",
            "atr_at_checkpoint",
            "confirmed_regime_direction",
            "session",
            "entry_year",
            "seconds_from_regime_start",
            "seconds_from_established",
            pl.col(f"{prefix}_probability").alias("entry_probability"),
            pl.col(f"{prefix}_in_domain").alias("entry_in_domain"),
            pl.lit(model_id).alias("model_id"),
            pl.lit(MODELS[model_id]["trade_direction"]).alias("trade_direction"),
        )
        .sort("checkpoint_decision_ns")
    )


def first_signal_population(
    scores: pl.LazyFrame, thresholds: dict, label: str
) -> pl.DataFrame:
    """First qualifying checkpoint per regime, per model."""
    frames = []
    for model_id in MODELS:
        threshold = thresholds.get((model_id, label))
        if threshold is None:
            continue
        frames.append(
            _candidates(scores, model_id, threshold)
            .group_by("regime_id")
            .first()
            .with_columns(percentile_label=pl.lit(label))
        )
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="vertical").sort("checkpoint_decision_ns").collect()


def all_crossings_population(
    scores: pl.LazyFrame, thresholds: dict, label: str
) -> pl.DataFrame:
    """Every entry into the band, not only the first.

    A crossing is a qualifying checkpoint whose immediate predecessor in the
    same regime did not qualify, so a run of consecutive qualifying checkpoints
    counts once.
    """
    frames = []
    for model_id, spec in MODELS.items():
        threshold = thresholds.get((model_id, label))
        if threshold is None:
            continue
        prefix = spec["prefix"]
        qualified = (
            scores.filter(pl.col(f"{prefix}_in_domain"))
            .sort("checkpoint_decision_ns")
            .with_columns(
                qualifies=pl.col(f"{prefix}_probability").fill_null(-1.0) >= threshold
            )
            .with_columns(
                previously=pl.col("qualifies")
                .shift(1, fill_value=False)
                .over("regime_id")
            )
            .filter(pl.col("qualifies") & ~pl.col("previously"))
            .select(
                "regime_id",
                "checkpoint_decision_ns",
                "checkpoint_reference_price",
                "atr_at_checkpoint",
                "entry_year",
                "seconds_from_regime_start",
                pl.col(f"{prefix}_probability").alias("entry_probability"),
                pl.lit(model_id).alias("model_id"),
                pl.lit(spec["trade_direction"]).alias("trade_direction"),
                pl.lit(label).alias("percentile_label"),
            )
        )
        frames.append(qualified)
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="vertical").sort("checkpoint_decision_ns").collect()


def highest_score_population(scores: pl.LazyFrame) -> pl.DataFrame:
    """The single best in-domain checkpoint per regime, threshold-free."""
    frames = []
    for model_id, spec in MODELS.items():
        prefix = spec["prefix"]
        frames.append(
            scores.filter(
                pl.col(f"{prefix}_in_domain")
                & pl.col(f"{prefix}_probability").is_not_null()
            )
            .sort(f"{prefix}_probability", descending=True)
            .group_by("regime_id")
            .first()
            .select(
                "regime_id",
                "checkpoint_decision_ns",
                "entry_year",
                "seconds_from_regime_start",
                pl.col(f"{prefix}_probability").alias("entry_probability"),
                pl.lit(model_id).alias("model_id"),
                pl.lit(spec["trade_direction"]).alias("trade_direction"),
            )
        )
    return pl.concat(frames, how="vertical").sort("checkpoint_decision_ns").collect()


def first_after_established_population(scores: pl.LazyFrame) -> pl.DataFrame:
    """First in-domain checkpoint at or after the established milestone."""
    frames = []
    for model_id, spec in MODELS.items():
        prefix = spec["prefix"]
        frames.append(
            scores.filter(
                pl.col(f"{prefix}_in_domain")
                & pl.col("seconds_from_established").is_not_null()
                & (pl.col("seconds_from_established") >= 0)
            )
            .sort("checkpoint_decision_ns")
            .group_by("regime_id")
            .first()
            .select(
                "regime_id",
                "checkpoint_decision_ns",
                "entry_year",
                "seconds_from_established",
                pl.col(f"{prefix}_probability").alias("entry_probability"),
                pl.lit(model_id).alias("model_id"),
            )
        )
    return pl.concat(frames, how="vertical").sort("checkpoint_decision_ns").collect()


def opposing_warning_population(
    scores: pl.LazyFrame, thresholds: dict, label: str
) -> pl.DataFrame:
    """First checkpoint at which the model opposing the trade crosses its band.

    In a bullish regime the trade is short, so the opposing signal is the
    bearish-fade model firing -- a warning that the regime may turn against the
    short. The opposing model is out of its own domain there by construction,
    so its score is exploratory; that is recorded, not hidden.
    """
    frames = []
    for model_id, spec in MODELS.items():
        opposing = next(m for m in MODELS if m != model_id)
        threshold = thresholds.get((opposing, label))
        if threshold is None:
            continue
        opposing_prefix = MODELS[opposing]["prefix"]
        frames.append(
            scores.filter(
                (pl.col("confirmed_regime_direction") == spec["approved_regime"])
                & pl.col("seconds_from_established").is_not_null()
                & (pl.col("seconds_from_established") >= 0)
                & (pl.col(f"{opposing_prefix}_probability").fill_null(-1.0) >= threshold)
            )
            .sort("checkpoint_decision_ns")
            .group_by("regime_id")
            .first()
            .select(
                "regime_id",
                "checkpoint_decision_ns",
                "entry_year",
                "seconds_from_established",
                pl.col(f"{opposing_prefix}_probability").alias("warning_probability"),
                pl.col(f"{opposing_prefix}_in_domain").alias("warning_model_in_domain"),
                pl.lit(model_id).alias("trade_model_id"),
                pl.lit(opposing).alias("warning_model_id"),
                pl.lit(label).alias("percentile_label"),
            )
        )
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="vertical").sort("checkpoint_decision_ns").collect()


def reentry_capability(
    scores: pl.LazyFrame, paths: pl.LazyFrame, thresholds: dict, label: str,
    stop_atr: float,
) -> dict:
    """Structural test: after a hypothetical stop, does the store still hold
    later checkpoints and later path rows in the same regime?

    This is not an economic study. The stop width is arbitrary and no attempt is
    made to tune it or to count profitability.
    """
    crossings = all_crossings_population(scores, thresholds, label)
    if crossings.is_empty():
        return {"status": "no candidates"}

    per_regime = crossings.group_by("regime_id").len().rename({"len": "candidates"})
    first = crossings.group_by("regime_id").first()

    later = (
        crossings.join(
            first.select("regime_id", first_ns=pl.col("checkpoint_decision_ns")),
            on="regime_id",
        )
        .filter(pl.col("checkpoint_decision_ns") > pl.col("first_ns"))
        .group_by("regime_id")
        .len()
    )

    path_after = (
        paths.join(
            first.select("regime_id", first_ns=pl.col("checkpoint_decision_ns")).lazy(),
            on="regime_id",
        )
        .filter(pl.col("path_init_ns") > pl.col("first_ns"))
        .group_by("regime_id")
        .len()
        .collect()
    )

    return {
        "percentile_label": label,
        "hypothetical_stop_atr": stop_atr,
        "regimes_with_candidates": per_regime.height,
        "regimes_with_one_candidate": per_regime.filter(
            pl.col("candidates") == 1
        ).height,
        "regimes_with_multiple_candidates": per_regime.filter(
            pl.col("candidates") > 1
        ).height,
        "median_candidates_per_regime": float(per_regime["candidates"].median()),
        "max_candidate_sequence_count": int(per_regime["candidates"].max()),
        "regimes_with_a_post_first_candidate": later.height,
        "regimes_with_path_rows_after_first_candidate": path_after.height,
        "median_path_rows_after_first_candidate": float(
            path_after["len"].median()
        ) if path_after.height else None,
    }


# ------------------------------------------------------------ backward parity


def backward_parity(population: pl.DataFrame) -> dict:
    """Reconcile the regenerated first-Top-2.5% population against the frozen
    accepted artifact, row by row rather than by count."""
    accepted = pl.read_parquet(ACCEPTED_SUMMARIES).select(
        "instrument_id",
        "checkpoint_decision_ns",
        "regime_start_ns",
        "entry_model_id",
        "trade_direction_name",
        "checkpoint_reference_price",
        "atr_at_entry",
        "entry_probability",
        "entry_year",
    )
    mine = population.select(
        "instrument_id",
        "checkpoint_decision_ns",
        "regime_start_ns",
        pl.col("model_id").alias("entry_model_id"),
        pl.col("trade_direction").alias("trade_direction_name"),
        "checkpoint_reference_price",
        pl.col("atr_at_checkpoint").alias("atr_at_entry"),
        "entry_probability",
        "entry_year",
    )

    key = ["instrument_id", "checkpoint_decision_ns", "entry_model_id"]
    a_keys = accepted.select(key).unique()
    m_keys = mine.select(key).unique()

    missing = a_keys.join(m_keys, on=key, how="anti")
    extra = m_keys.join(a_keys, on=key, how="anti")
    duplicated = (
        mine.group_by(key).len().filter(pl.col("len") > 1)
    )

    joined = accepted.join(mine, on=key, how="inner", suffix="_mine")
    mismatches = {}
    for column, tolerance in (
        ("regime_start_ns", 0),
        ("trade_direction_name", None),
        ("checkpoint_reference_price", 0.0),
        ("atr_at_entry", 0.0),
        ("entry_probability", 0.0),
        ("entry_year", 0),
    ):
        left, right = joined[column], joined[f"{column}_mine"]
        if tolerance is None:
            differs = int((left != right).sum())
        else:
            differs = int(((left - right).abs() > tolerance).sum())
        if differs:
            mismatches[column] = differs

    return {
        "accepted_trades": accepted.height,
        "regenerated_trades": mine.height,
        "matched": joined.height,
        "missing_vs_accepted": missing.height,
        "extra_vs_accepted": extra.height,
        "duplicated_keys": duplicated.height,
        "value_mismatches": mismatches,
        "by_year": mine.group_by("entry_year").len().sort("entry_year").to_dicts(),
        "by_direction": mine.group_by("trade_direction_name").len().to_dicts(),
        "verdict": "PASS"
        if not missing.height
        and not extra.height
        and not duplicated.height
        and not mismatches
        and accepted.height == mine.height
        else "FAIL",
    }


# -------------------------------------------------------------------- driver


def describe(population: pl.DataFrame, label: str) -> dict:
    if population.is_empty():
        return {"population": label, "candidates": 0}
    timing = population["seconds_from_regime_start"] if (
        "seconds_from_regime_start" in population.columns
    ) else None
    out = {
        "population": label,
        "candidate_observations": population.height,
        "unique_regimes": population["regime_id"].n_unique(),
        "multiple_candidate_regimes": population.group_by("regime_id")
        .len()
        .filter(pl.col("len") > 1)
        .height,
        "median_candidates_per_regime": float(
            population.group_by("regime_id").len()["len"].median()
        ),
        "by_year": population.group_by("entry_year").len().sort("entry_year").to_dicts(),
    }
    if "trade_direction" in population.columns:
        out["by_direction"] = population.group_by("trade_direction").len().to_dicts()
    if timing is not None and timing.null_count() < timing.len():
        out["candidate_timing_seconds"] = {
            "p25": float(timing.quantile(0.25)),
            "median": float(timing.median()),
            "p75": float(timing.quantile(0.75)),
        }
    return out


def run(store: Path, out_path: Path, parity: bool) -> dict:
    scores = pl.scan_parquet(store / "canonical_regime_scores_all.parquet")
    paths = pl.scan_parquet(store / "canonical_regime_paths_all.parquet")
    thresholds = load_thresholds()

    report: dict = {"first_signal": [], "all_crossings": [], "reentry": []}

    for label in ("top_20", "top_10", "top_5", "top_2_5", "top_1", "top_0_5"):
        population = first_signal_population(scores, thresholds, label)
        report["first_signal"].append(describe(population, f"first_{label}"))
        if label == "top_2_5" and parity:
            report["backward_parity"] = backward_parity(population)

    for label in ("top_5", "top_2_5", "top_1"):
        report["all_crossings"].append(
            describe(all_crossings_population(scores, thresholds, label), f"crossings_{label}")
        )

    report["highest_score_per_regime"] = describe(
        highest_score_population(scores), "highest_score"
    )
    report["first_after_established"] = describe(
        first_after_established_population(scores), "first_after_established"
    )
    for label in ("top_10", "top_5", "top_2_5"):
        report.setdefault("opposing_warnings", []).append(
            describe(
                opposing_warning_population(scores, thresholds, label),
                f"opposing_warning_{label}",
            )
        )

    report["reentry"].append(
        reentry_capability(scores, paths, thresholds, "top_2_5", stop_atr=1.0)
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=str(CANONICAL))
    parser.add_argument(
        "--out",
        default=str(
            ROOT / "studies/regime_complete_canonical_store/results/population_coverage_summary.json"
        ),
    )
    parser.add_argument(
        "--no-parity",
        action="store_true",
        help="skip backward parity (for partial-store pilots)",
    )
    args = parser.parse_args()
    report = run(Path(args.store), Path(args.out), parity=not args.no_parity)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()

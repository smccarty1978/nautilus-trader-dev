"""Bounded analyst-facing acceptance validation for the canonical store."""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import polars as pl
import yaml

from studies.full_trade_path_builder.implementation.canonical_research_loader import (
    scan_canonical_research_population,
)
from studies.full_trade_path_builder.implementation.run_phase_a_collect import (
    atomic_json,
)


def timed_count(path: Path, **filters: object) -> dict:
    started = time.perf_counter()
    frame = scan_canonical_research_population(str(path), **filters)
    lazy_scan_seconds = time.perf_counter() - started
    started = time.perf_counter()
    rows = frame.select(pl.len()).collect(engine="streaming").item()
    collect_seconds = time.perf_counter() - started
    return {
        "filter_applied": filters or {"filter": "none"},
        "row_count_returned": int(rows),
        "lazy_scan_seconds": lazy_scan_seconds,
        "count_collect_seconds": collect_seconds,
        "elapsed_seconds": lazy_scan_seconds + collect_seconds,
    }


def metric_errors(
    actual: list[float],
    expected: list[float],
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict:
    errors = [abs(float(left) - float(right)) for left, right in zip(actual, expected)]
    failures = [
        index
        for index, (left, right) in enumerate(zip(actual, expected))
        if not math.isclose(
            float(left),
            float(right),
            abs_tol=absolute_tolerance,
            rel_tol=relative_tolerance,
        )
    ]
    return {
        "maximum_absolute_error": max(errors, default=0.0),
        "mean_absolute_error": sum(errors) / len(errors) if errors else 0.0,
        "failure_indexes": failures,
        "failure_count": len(failures),
    }


def validate(
    observations_path: Path,
    summaries_path: Path,
    paths_path: Path,
    config_path: Path,
    output_path: Path,
) -> dict:
    config = yaml.safe_load(config_path.read_text())
    seed = int(config["random_seed"])
    sample_size = int(config["sample_completed_trades"])
    absolute_tolerance = float(config["absolute_tolerance"])
    relative_tolerance = float(config["relative_tolerance"])
    load_config = config["load_test"]

    phase_1 = {
        "full_observations": timed_count(observations_path),
        "full_trade_summaries": timed_count(summaries_path),
        "full_trade_paths": timed_count(paths_path),
        "one_year_summaries": timed_count(
            summaries_path,
            start=f"{load_config['year']}-01-01T00:00:00Z",
            end=f"{load_config['year'] + 1}-01-01T00:00:00Z",
        ),
        "one_model_summaries": timed_count(
            summaries_path,
            model_ids=[load_config["model_id"]],
        ),
        "one_direction_summaries": timed_count(
            summaries_path,
            directions=[load_config["direction"]],
        ),
        "bounded_date_summaries": timed_count(
            summaries_path,
            start=load_config["bounded_start"],
            end=load_config["bounded_end"],
        ),
    }

    observations = scan_canonical_research_population(str(observations_path))
    summaries = scan_canonical_research_population(str(summaries_path))
    paths = scan_canonical_research_population(str(paths_path))

    observation_stats = observations.select(
        pl.len().alias("rows"),
        pl.struct("instrument_id", "checkpoint_decision_ns")
        .n_unique()
        .alias("unique_semantic_observation_keys"),
        pl.col("checkpoint_decision_ns").min().alias("minimum_timestamp_ns"),
        pl.col("checkpoint_decision_ns").max().alias("maximum_timestamp_ns"),
    ).collect(engine="streaming").row(0, named=True)
    summary_stats = summaries.select(
        pl.len().alias("rows"),
        pl.col("trade_id").n_unique().alias("unique_trade_ids"),
        pl.col("checkpoint_decision_ns").min().alias("minimum_timestamp_ns"),
        pl.col("checkpoint_decision_ns").max().alias("maximum_timestamp_ns"),
        pl.col("path_is_complete").sum().alias("complete_trades"),
        pl.col("is_right_censored").sum().alias("censored_trades"),
    ).collect(engine="streaming").row(0, named=True)
    path_stats = paths.select(
        pl.len().alias("rows"),
        pl.col("trade_id").n_unique().alias("unique_trade_ids"),
        pl.col("timestamp_close_ns").min().alias("minimum_timestamp_ns"),
        pl.col("timestamp_close_ns").max().alias("maximum_timestamp_ns"),
    ).collect(engine="streaming").row(0, named=True)

    observation_duplicate_count = (
        observations.group_by("instrument_id", "checkpoint_decision_ns")
        .len()
        .filter(pl.col("len") > 1)
        .select(pl.len())
        .collect(engine="streaming")
        .item()
    )
    summary_duplicate_count = (
        summaries.group_by("trade_id")
        .len()
        .filter(pl.col("len") != 1)
        .select(pl.len())
        .collect(engine="streaming")
        .item()
    )
    final_path_counts = (
        paths.filter(pl.col("is_final_path_bar"))
        .group_by("trade_id")
        .agg(pl.len().alias("final_rows"))
        .collect(engine="streaming")
    )
    final_path_duplicate_trades = final_path_counts.filter(
        pl.col("final_rows") != 1
    ).height
    trades_missing_final_path = (
        int(summary_stats["unique_trade_ids"]) - final_path_counts["trade_id"].n_unique()
    )
    counts_by_model_direction = (
        summaries.group_by("model_id", "trade_direction_name")
        .agg(
            pl.len().alias("trade_count"),
            pl.col("path_is_complete").sum().alias("complete_count"),
            pl.col("is_right_censored").sum().alias("censored_count"),
        )
        .sort("model_id", "trade_direction_name")
        .collect(engine="streaming")
        .to_dicts()
    )
    phase_2 = {
        "observations": observation_stats,
        "trade_summaries": summary_stats,
        "trade_paths": path_stats,
        "observation_id_status": (
            "ABSENT; exact semantic key is instrument_id + checkpoint_decision_ns"
        ),
        "duplicate_semantic_observation_keys": int(observation_duplicate_count),
        "duplicate_trade_summary_keys": int(summary_duplicate_count),
        "trades_with_non_one_final_path_rows": int(final_path_duplicate_trades),
        "trades_missing_final_path_row": int(trades_missing_final_path),
        "counts_by_model_direction": counts_by_model_direction,
    }

    completed_ids = (
        summaries.filter(pl.col("path_is_complete"))
        .select("trade_id")
        .sort("trade_id")
        .collect(engine="streaming")["trade_id"]
        .to_list()
    )
    sampled_ids = sorted(random.Random(seed).sample(completed_ids, sample_size))
    sampled_summaries = (
        summaries.filter(pl.col("trade_id").is_in(sampled_ids))
        .select(
            "trade_id",
            "checkpoint_decision_ns",
            "path_row_count",
            "seconds_entry_to_fallback_exit",
            "full_trade_mfe_atr",
            "full_trade_mae_atr",
            "fallback_exit_mark_return_atr",
        )
        .collect(engine="streaming")
    )
    sampled_paths = (
        paths.filter(pl.col("trade_id").is_in(sampled_ids))
        .select(
            "trade_id",
            "timestamp_close_ns",
            "running_mfe_atr",
            "running_mae_atr",
            "close_pnl_atr",
            "is_final_path_bar",
        )
        .collect(engine="streaming")
    )
    recalculated = sampled_paths.group_by("trade_id").agg(
        pl.len().alias("actual_path_row_count"),
        pl.col("timestamp_close_ns").max().alias("actual_final_timestamp_ns"),
        pl.col("running_mfe_atr").max().alias("actual_mfe_atr"),
        (-pl.col("running_mae_atr").min()).alias("actual_mae_atr"),
        pl.col("close_pnl_atr")
        .filter(pl.col("is_final_path_bar"))
        .first()
        .alias("actual_final_return_atr"),
    )
    comparison = sampled_summaries.join(
        recalculated, on="trade_id", how="left", validate="1:1"
    ).with_columns(
        (
            (pl.col("actual_final_timestamp_ns") - pl.col("checkpoint_decision_ns"))
            / 1e9
        ).alias("actual_duration_seconds")
    )
    metric_mapping = {
        "path_row_count": ("actual_path_row_count", "path_row_count"),
        "trade_duration_seconds": (
            "actual_duration_seconds",
            "seconds_entry_to_fallback_exit",
        ),
        "maximum_favorable_excursion_atr": (
            "actual_mfe_atr",
            "full_trade_mfe_atr",
        ),
        "maximum_adverse_excursion_atr": (
            "actual_mae_atr",
            "full_trade_mae_atr",
        ),
        "final_path_return_atr": (
            "actual_final_return_atr",
            "fallback_exit_mark_return_atr",
        ),
    }
    reconciliation_metrics = {}
    failure_trade_ids = set()
    for metric, (actual_field, expected_field) in metric_mapping.items():
        errors = metric_errors(
            comparison[actual_field].to_list(),
            comparison[expected_field].to_list(),
            absolute_tolerance,
            relative_tolerance,
        )
        for index in errors.pop("failure_indexes"):
            failure_trade_ids.add(comparison["trade_id"][index])
        reconciliation_metrics[metric] = {
            "path_field": actual_field,
            "summary_field": expected_field,
            **errors,
        }
    phase_3 = {
        "sample_seed": seed,
        "sample_size": sample_size,
        "sampled_trade_ids": sampled_ids,
        "normalization": (
            "Path running_mae_atr is signed/nonpositive; summary "
            "full_trade_mae_atr is the positive magnitude."
        ),
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "field_mapping": metric_mapping,
        "metrics": reconciliation_metrics,
        "failure_trade_ids": sorted(failure_trade_ids),
        "failure_count": len(failure_trade_ids),
    }

    observation_link_fields = observations.select(
        "instrument_id",
        "checkpoint_decision_ns",
        pl.col("checkpoint_decision_ns").alias("__observation_present_ns"),
        "regime_start_ns",
        "confirmed_regime_direction",
        "bullish_model_id",
        "bearish_model_id",
        "bullish_raw_score",
        "bearish_raw_score",
    )
    linkage = (
        summaries.select(
            "trade_id",
            "instrument_id",
            "checkpoint_decision_ns",
            "regime_start_ns",
            "entry_regime_direction",
            "trade_direction",
            "entry_model_id",
            "entry_raw_score",
        )
        .join(
            observation_link_fields,
            on=["instrument_id", "checkpoint_decision_ns"],
            how="left",
            suffix="_observation",
            validate="m:1",
        )
        .with_columns(
            pl.when(pl.col("trade_direction") == -1)
            .then(pl.col("bullish_model_id"))
            .otherwise(pl.col("bearish_model_id"))
            .alias("__observation_entry_model_id"),
            pl.when(pl.col("trade_direction") == -1)
            .then(pl.col("bullish_raw_score"))
            .otherwise(pl.col("bearish_raw_score"))
            .alias("__observation_entry_raw_score"),
        )
    )
    linkage_counts = linkage.select(
        pl.col("__observation_present_ns").is_null().sum().alias("missing_entry_observations"),
        (pl.col("regime_start_ns") != pl.col("regime_start_ns_observation"))
        .sum()
        .alias("regime_start_ns"),
        (
            pl.col("entry_regime_direction")
            != pl.col("confirmed_regime_direction")
        )
        .sum()
        .alias("regime_direction"),
        (
            pl.col("entry_model_id") != pl.col("__observation_entry_model_id")
        )
        .sum()
        .alias("model_id"),
        (
            (pl.col("entry_raw_score") - pl.col("__observation_entry_raw_score")).abs()
            > absolute_tolerance
        )
        .sum()
        .alias("model_score"),
    ).collect(engine="streaming").row(0, named=True)
    phase_4 = {
        "link_key": ["instrument_id", "checkpoint_decision_ns"],
        "fuzzy_matching_used": False,
        "observation_id_status": "ABSENT",
        "shared_field_mapping": {
            "checkpoint_timestamp": "checkpoint_decision_ns",
            "regime_id_equivalent": "regime_start_ns",
            "regime_direction": (
                "entry_regime_direction -> confirmed_regime_direction"
            ),
            "model_id": (
                "SHORT -> bullish_model_id; LONG -> bearish_model_id"
            ),
            "model_score": (
                "SHORT entry_raw_score -> bullish_raw_score; "
                "LONG entry_raw_score -> bearish_raw_score"
            ),
        },
        "missing_entry_observations": int(
            linkage_counts["missing_entry_observations"]
        ),
        "field_mismatches_by_column": {
            key: int(value)
            for key, value in linkage_counts.items()
            if key != "missing_entry_observations"
        },
    }

    confirmation_paths = (
        paths.select(
            "trade_id",
            "timestamp_close_ns",
            "running_mfe_atr",
            "running_mae_atr",
            "close_pnl_atr",
            "is_confirm_flip_boundary",
        )
        .join(
            summaries.select("trade_id", "confirm_flip_ns"),
            on="trade_id",
            how="inner",
            validate="m:1",
        )
        .filter(pl.col("timestamp_close_ns") <= pl.col("confirm_flip_ns"))
        .group_by("trade_id")
        .agg(
            pl.col("running_mfe_atr").max().alias("mfe_to_confirmation_atr"),
            (-pl.col("running_mae_atr").min()).alias("mae_to_confirmation_atr"),
            pl.col("close_pnl_atr")
            .filter(pl.col("is_confirm_flip_boundary"))
            .first()
            .alias("return_at_confirmation_atr"),
        )
    )
    phase_5_rows = (
        summaries.with_columns(
            (
                (pl.col("checkpoint_decision_ns") - pl.col("regime_start_ns"))
                / 1e9
            ).alias("regime_age_at_entry_seconds")
        )
        .join(confirmation_paths, on="trade_id", how="left", validate="1:1")
        .group_by("model_id", "trade_direction_name")
        .agg(
            pl.len().alias("trade_count"),
            pl.col("path_is_complete").sum().alias("complete_count"),
            pl.col("is_right_censored").sum().alias("censored_count"),
            pl.col("regime_age_at_entry_seconds")
            .median()
            .alias("median_regime_age_at_entry_seconds"),
            (
                pl.col("confirmed_within_300s").mean() * 100
            ).alias("percentage_confirming_within_300_seconds"),
            pl.col("mae_to_confirmation_atr")
            .median()
            .alias("median_mae_to_confirmation_atr"),
            pl.col("mfe_to_confirmation_atr")
            .median()
            .alias("median_mfe_to_confirmation_atr"),
            pl.col("return_at_confirmation_atr")
            .median()
            .alias("median_return_at_confirmation_atr"),
        )
        .sort("model_id", "trade_direction_name")
        .collect(engine="streaming")
        .to_dicts()
    )
    phase_5 = {
        "grouped_by": ["model_id", "trade_direction_name"],
        "rows": phase_5_rows,
        "descriptive_only": True,
    }

    failures = {
        "phase_2_integrity": (
            observation_duplicate_count
            + summary_duplicate_count
            + final_path_duplicate_trades
            + trades_missing_final_path
        ),
        "phase_3_reconciliation": len(failure_trade_ids),
        "phase_4_missing_links": int(linkage_counts["missing_entry_observations"]),
        "phase_4_field_mismatches": sum(
            int(value)
            for key, value in linkage_counts.items()
            if key != "missing_entry_observations"
        ),
    }
    verdict = (
        "READY FOR RESEARCH"
        if sum(failures.values()) == 0
        else "NOT READY"
    )
    result = {
        "status": "PASS" if verdict == "READY FOR RESEARCH" else "FAIL",
        "verdict": verdict,
        "schemas": {
            "observations": observations.collect_schema().names(),
            "trade_summaries": summaries.collect_schema().names(),
            "trade_paths": paths.collect_schema().names(),
        },
        "phase_1_analyst_load_test": phase_1,
        "phase_2_dataset_integrity": phase_2,
        "phase_3_summary_path_reconciliation": phase_3,
        "phase_4_observation_trade_linkage": phase_4,
        "phase_5_minimal_research_demonstration": phase_5,
        "failure_summary": failures,
        "limitations": [
            "No observation_id column exists; exact semantic observation keys are used.",
            (
                "Confirmation MAE/MFE/return are reconstructed from path rows "
                "because they are not stored directly in summaries."
            ),
        ],
    }
    atomic_json(result, output_path)
    if result["status"] != "PASS":
        raise RuntimeError(f"canonical research store acceptance failed: {failures}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", required=True)
    parser.add_argument("--summaries", required=True)
    parser.add_argument("--paths", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = validate(
        Path(args.observations),
        Path(args.summaries),
        Path(args.paths),
        Path(args.config),
        Path(args.output),
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "verdict": result["verdict"],
                "output": args.output,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

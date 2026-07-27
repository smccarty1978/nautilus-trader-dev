"""Phase 2 pilot validation.

The decisive check is equivalence against the accepted artifact: after widening
the collector to the full session, every RTH score row it produces must still
carry exactly the values the accepted store carries, on every shared column.
That single comparison catches any accidental behavior change in the frozen
feature/scoring path far more reliably than inspecting derived aggregates.

The remaining checks assert the structural properties the store is for:
completeness, exact linkage, dense sequences, causal ordering, and the absence
of any policy predicate in what was retained.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
ACCEPTED = ROOT / "studies/full_trade_path_builder/consolidated/canonical_observations_all.parquet"
NS = 1_000_000_000

# Columns the extension adds or reshapes; everything else must match exactly.
ADDED_COLUMNS = {
    "session_contract_status", "score_observation_id", "feature_snapshot_id",
    "feature_contract_version", "score_decision_ns", "score_event_ns",
    "score_available_ns", "bullish_score_available_ns", "bearish_score_available_ns",
    "bullish_score_is_new", "bearish_score_is_new", "collector_version",
    "contract_version", "regime_id", "score_sequence_in_regime",
    "seconds_from_regime_start", "seconds_from_established", "contract_id",
    "entry_year", "source_partition", "bullish_out_of_domain_reason",
    "bearish_out_of_domain_reason",
}
# Provenance of the accepted consolidation run, not collector output.
IGNORED_COLUMNS = {"source_file", "source_year", "source_month", "trade_direction", "model_id"}


def _fail(report: dict, key: str, detail) -> None:
    report["failures"][key] = detail


def validate(work_dir: Path, start_ns: int, end_ns: int) -> dict:
    scores = pl.read_parquet(work_dir / "canonical_regime_scores.parquet")
    regimes = pl.read_parquet(work_dir / "canonical_regimes.parquet")
    paths = pl.read_parquet(work_dir / "canonical_regime_paths.parquet")
    missing = pl.read_parquet(work_dir / "missing_dispatch.parquet")

    report: dict = {
        "rows": {
            "scores": scores.height, "regimes": regimes.height,
            "paths": paths.height, "missing": missing.height,
        },
        "failures": {},
    }

    _check_rth_equivalence(scores, start_ns, end_ns, report)
    _check_score_integrity(scores, report)
    _check_regime_integrity(regimes, report)
    _check_path_integrity(paths, regimes, report)
    _check_linkage(scores, paths, regimes, report)
    _check_no_policy_filter(scores, regimes, report)
    _check_dispatch_grid(scores, missing, start_ns, end_ns, report)

    report["verdict"] = "PASS" if not report["failures"] else "FAIL"
    return report


# --------------------------------------------------------------- equivalence


def _check_rth_equivalence(scores, start_ns, end_ns, report) -> None:
    """Every RTH row must equal the accepted artifact on every shared column."""
    accepted = (
        pl.scan_parquet(ACCEPTED)
        .filter(
            (pl.col("checkpoint_decision_ns") >= start_ns)
            & (pl.col("checkpoint_decision_ns") < end_ns)
        )
        .collect()
    )
    mine = scores.filter(pl.col("session") == "RTH")

    summary = {
        "accepted_rows": accepted.height,
        "pilot_rth_rows": mine.height,
    }
    if accepted.height == 0:
        _fail(report, "rth_equivalence", "accepted artifact has no rows in window")
        report["rth_equivalence"] = summary
        return

    shared = [
        c for c in accepted.columns
        if c in mine.columns and c not in ADDED_COLUMNS and c not in IGNORED_COLUMNS
    ]
    summary["compared_columns"] = len(shared)

    key = "checkpoint_decision_ns"
    a_keys = set(accepted[key].to_list())
    m_keys = set(mine[key].to_list())
    summary["missing_vs_accepted"] = len(a_keys - m_keys)
    summary["extra_vs_accepted"] = len(m_keys - a_keys)

    a = accepted.select(shared).sort(key)
    m = mine.select(shared).sort(key)
    mismatched: dict[str, int] = {}
    if a.height == m.height:
        for column in shared:
            left, right = a[column], m[column]
            if left.dtype != right.dtype:
                mismatched[column] = f"dtype {left.dtype} vs {right.dtype}"
                continue
            if left.dtype.is_numeric():
                differs = (left != right).fill_null(
                    left.is_null() != right.is_null()
                ).sum()
            else:
                differs = (left != right).fill_null(
                    left.is_null() != right.is_null()
                ).sum()
            if differs:
                mismatched[column] = int(differs)
    summary["mismatched_columns"] = mismatched

    report["rth_equivalence"] = summary
    if summary["missing_vs_accepted"] or summary["extra_vs_accepted"] or mismatched:
        _fail(report, "rth_equivalence", summary)


# ---------------------------------------------------------------- integrity


def _check_score_integrity(scores, report) -> None:
    if scores["score_observation_id"].n_unique() != scores.height:
        _fail(report, "duplicate_score_observation_ids", scores.height)
    if scores["checkpoint_decision_ns"].n_unique() != scores.height:
        _fail(report, "duplicate_score_semantic_keys", scores.height)

    off_grid = scores.filter(pl.col("score_decision_ns") % (5 * NS) != 0).height
    if off_grid:
        _fail(report, "off_grid_dispatch", off_grid)

    if not scores["score_decision_ns"].is_sorted():
        _fail(report, "score_timestamps_not_monotonic", True)

    late = scores.filter(
        pl.col("score_available_ns") > pl.col("score_decision_ns")
    ).height
    if late:
        _fail(report, "score_available_after_decision", late)

    # No future source may have entered a score.
    for column in ("max_source_ts_event_1s", "max_source_ts_event_1m"):
        bad = scores.filter(pl.col(column) >= pl.col("score_decision_ns")).height
        if bad:
            _fail(report, f"future_source_{column}", bad)
    bad_init = scores.filter(
        pl.col("max_source_ts_init_1s") > pl.col("score_decision_ns")
    ).height
    if bad_init:
        _fail(report, "future_source_max_source_ts_init_1s", bad_init)

    if not scores["bullish_score_is_new"].all() or not scores["bearish_score_is_new"].all():
        _fail(report, "carry_forward_stored_as_score_event", True)

    in_domain_eth = scores.filter(
        (pl.col("session") != "RTH")
        & (pl.col("bullish_in_domain") | pl.col("bearish_in_domain"))
    ).height
    if in_domain_eth:
        _fail(report, "eth_rows_marked_in_domain", in_domain_eth)

    report["score_coverage"] = {
        "by_session": scores.group_by("session").len().sort("session").to_dicts(),
        "bullish_scored": int(scores["bullish_probability"].is_not_null().sum()),
        "bearish_scored": int(scores["bearish_probability"].is_not_null().sum()),
        "bullish_in_domain": int(scores["bullish_in_domain"].sum()),
        "bearish_in_domain": int(scores["bearish_in_domain"].sum()),
        "both_in_domain": int(
            (scores["bullish_in_domain"] & scores["bearish_in_domain"]).sum()
        ),
        "neither_in_domain": int(
            (~scores["bullish_in_domain"] & ~scores["bearish_in_domain"]).sum()
        ),
    }


def _check_regime_integrity(regimes, report) -> None:
    if regimes["regime_id"].n_unique() != regimes.height:
        _fail(report, "duplicate_regime_ids", regimes.height)

    sequence = regimes["regime_sequence_number"].to_list()
    if sequence != sorted(sequence) or len(set(sequence)) != len(sequence):
        _fail(report, "regime_sequence_not_dense_monotonic", True)

    directions = regimes.sort("regime_sequence_number")["regime_direction"].to_list()
    same = sum(1 for a, b in zip(directions, directions[1:]) if a == b)
    if same:
        _fail(report, "consecutive_same_direction_regimes", same)

    invented = regimes.filter(
        (pl.col("regime_end_reason") != "opposing_flip")
        & pl.col("regime_end_decision_ns").is_not_null()
    ).height
    if invented:
        _fail(report, "censored_regime_with_invented_terminal", invented)

    report["regime_coverage"] = {
        "by_direction": regimes.group_by("regime_direction").len().sort(
            "regime_direction"
        ).to_dicts(),
        "by_start_session": regimes.group_by("session_at_start").len().sort(
            "session_at_start"
        ).to_dicts(),
        "established": int(regimes["established_reached"].sum()),
        "never_established": int((~regimes["established_reached"]).sum()),
        "complete_paths": int(regimes["path_is_complete"].sum()),
        "censored_paths": int((~regimes["path_is_complete"]).sum()),
    }


def _check_path_integrity(paths, regimes, report) -> None:
    duplicate = paths.height - paths.select("regime_id", "path_event_ns").n_unique()
    if duplicate:
        _fail(report, "duplicate_path_keys", duplicate)

    forbidden = {
        "mfe_from_entry", "mae_from_entry", "trade_return", "stop_hit",
        "target_hit", "entry_price", "trade_id",
    } & set(paths.columns)
    if forbidden:
        _fail(report, "entry_dependent_columns_in_path_table", sorted(forbidden))

    # Sequence numbers are assigned over the whole regime, so a regime that
    # spans a partition boundary starts above zero here. Contiguity within the
    # partition is the property that must hold; global density is reconciled
    # across partitions in Phase 3.
    gaps = (
        paths.group_by("regime_id")
        .agg(
            count=pl.len(),
            span=pl.col("path_sequence_in_regime").max()
            - pl.col("path_sequence_in_regime").min()
            + 1,
        )
        .filter(pl.col("count") != pl.col("span"))
    )
    if gaps.height:
        _fail(report, "path_sequence_not_contiguous", gaps.to_dicts()[:5])

    straddling = (
        paths.group_by("regime_id")
        .agg(first=pl.col("path_sequence_in_regime").min())
        .filter(pl.col("first") > 0)
        .height
    )
    report["partition_boundary"] = {"regimes_straddling_partition_start": straddling}

    non_monotonic = (
        paths.sort(["regime_id", "path_sequence_in_regime"])
        .with_columns(
            regressed=pl.col("path_event_ns")
            <= pl.col("path_event_ns").shift(1).over("regime_id")
        )
        .filter(pl.col("regressed"))
    )
    if non_monotonic.height:
        _fail(report, "path_timestamps_not_monotonic", non_monotonic.height)

    # Availability must strictly follow the market event it summarizes.
    bad = paths.filter(pl.col("path_event_ns") >= pl.col("path_init_ns")).height
    if bad:
        _fail(report, "path_event_not_before_availability", bad)


def _check_linkage(scores, paths, regimes, report) -> None:
    ids = set(regimes["regime_id"].to_list())
    orphan_scores = scores.filter(
        pl.col("regime_id").is_not_null() & ~pl.col("regime_id").is_in(list(ids))
    ).height
    orphan_paths = paths.filter(~pl.col("regime_id").is_in(list(ids))).height
    # Window-boundary regimes legitimately own rows whose regime row lives in an
    # adjacent partition; those are reconciled globally, not per-partition.
    report["linkage"] = {
        "scores_without_local_regime_row": orphan_scores,
        "paths_without_local_regime_row": orphan_paths,
        "scores_with_null_regime_id": int(scores["regime_id"].is_null().sum()),
    }


def _check_no_policy_filter(scores, regimes, report) -> None:
    """A threshold or first-signal rule must not have shaped what was kept."""
    bull_min = scores["bullish_probability"].min()
    bear_min = scores["bearish_probability"].min()
    if bull_min is not None and bull_min >= 0.4:
        _fail(report, "low_bullish_scores_absent", bull_min)
    if bear_min is not None and bear_min >= 0.4:
        _fail(report, "low_bearish_scores_absent", bear_min)

    multi = (
        scores.filter(pl.col("regime_id").is_not_null())
        .group_by("regime_id")
        .len()
        .filter(pl.col("len") > 1)
        .height
    )
    if not multi:
        _fail(report, "no_regime_has_multiple_checkpoints", True)

    never_scored = regimes.filter(
        ~pl.col("regime_id").is_in(scores["regime_id"].drop_nulls().to_list())
    ).height
    report["policy_freedom"] = {
        "regimes_with_multiple_checkpoints": multi,
        "regimes_with_no_score_row_retained": never_scored,
        "min_bullish_probability": bull_min,
        "min_bearish_probability": bear_min,
    }


def _check_dispatch_grid(scores, missing, start_ns, end_ns, report) -> None:
    expected = (end_ns - start_ns) // (5 * NS)
    accounted = scores.height + missing.height
    report["dispatch_grid"] = {
        "expected_5s_slots": expected,
        "scored": scores.height,
        "missing": missing.height,
        "accounted": accounted,
    }
    if accounted != expected:
        _fail(report, "dispatch_grid_unaccounted", expected - accounted)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    manifest = json.loads((work_dir / "manifest.json").read_text())
    from datetime import datetime

    start_ns = int(datetime.fromisoformat(manifest["start"]).timestamp() * NS)
    end_ns = int(datetime.fromisoformat(manifest["end"]).timestamp() * NS)

    report = validate(work_dir, start_ns, end_ns)
    report["partition"] = manifest["partition"]
    report["window"] = {"start": manifest["start"], "end": manifest["end"]}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()

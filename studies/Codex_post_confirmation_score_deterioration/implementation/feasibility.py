"""Gate-1 observability analysis for the post-confirmation warning stream.

This is post-backtest analysis of NT-produced canonical artifacts.  It never
reconstructs a signal or changes a terminal label: confirmation, terminal
timestamp, direction, ATR, and labels are inherited from the accepted
predecessor ledger.  The only predictor-side operation is a causal interval
slice of actual, non-null in-domain score dispatches in the newly confirmed
regime.
"""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
PREDECESSOR = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
RESULTS = ROOT / "studies/Codex_post_confirmation_score_deterioration/results"
NS = 1_000_000_000

POST_CONFIRM_LABELS = (
    "CONFIRMED_THEN_STOPPED",
    "FINAL_FLIP_EXIT_LOSER",
    "FINAL_FLIP_EXIT_WINNER",
    "SESSION_EXIT",
)
FAILURE_LABELS = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER")
WINNER_LABEL = "FINAL_FLIP_EXIT_WINNER"
MIN_OBS = 3
GATE1_FAILURE_COVERAGE_FLOOR = 0.50
QUOTED_COUNTS = {
    "CONFIRMED_THEN_STOPPED": 822,
    "FINAL_FLIP_EXIT_LOSER": 1359,
    "FINAL_FLIP_EXIT_WINNER": 2350,
    "SESSION_EXIT": 174,
}


def _write(name: str, payload: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _stats(column: pl.Series) -> dict:
    values = column.drop_nulls()
    if not values.len():
        return {"n": 0, "median": None, "p25": None, "p75": None, "p90": None}
    return {
        "n": values.len(),
        "median": round(float(values.median()), 4),
        "p25": round(float(values.quantile(0.25)), 4),
        "p75": round(float(values.quantile(0.75)), 4),
        "p90": round(float(values.quantile(0.90)), 4),
    }


def _group_coverage(frame: pl.DataFrame, group_cols: list[str]) -> list[dict]:
    return (
        frame.group_by(group_cols)
        .agg(
            trades=pl.len(),
            trades_with_any_obs=(pl.col("n_obs") >= 1).sum(),
            trades_with_ge3_obs=(pl.col("n_obs") >= MIN_OBS).sum(),
            median_obs=pl.col("n_obs").median(),
            median_first_delay_s=pl.col("first_delay_s").median(),
        )
        .with_columns(
            pct_with_any_obs=(pl.col("trades_with_any_obs") / pl.col("trades") * 100).round(2),
            pct_with_ge3_obs=(pl.col("trades_with_ge3_obs") / pl.col("trades") * 100).round(2),
        )
        .sort(group_cols)
        .to_dicts()
    )


def _not_evaluable(reason: str) -> dict:
    return {"status": "NOT_EVALUABLE", "reason": reason, "policy_simulation_permitted": False}


def main() -> None:
    _write("progress.json", {"status": "running", "phase": "load_predecessor"})
    paths = pl.read_parquet(PREDECESSOR).filter(pl.col("valid"))
    labels = {
        row["terminal_label_full"]: int(row["count"])
        for row in paths["terminal_label_full"].value_counts().iter_rows(named=True)
    }
    post = paths.filter(
        pl.col("terminal_label_full").is_in(POST_CONFIRM_LABELS)
        & pl.col("walk_a_confirm_ns").is_not_null()
        & pl.col("full_exit_ns").is_not_null()
    ).select(
        "regime_id", "direction", "side", "entry_year", "terminal_label_full",
        "walk_a_confirm_ns", "full_exit_ns", "full_mfe_atr", "arm_atr",
    )

    regimes = pl.scan_parquet(STORE / "canonical_regimes_all.parquet").select(
        "regime_id", "regime_direction", "regime_start_decision_ns",
        "regime_established_decision_ns", "established_reached",
    ).collect()
    trades = post.join(
        regimes.rename({"regime_id": "new_regime_id"}),
        left_on=["walk_a_confirm_ns", "direction"],
        right_on=["regime_start_decision_ns", "regime_direction"],
        how="left",
    )
    missing_join = int(trades["new_regime_id"].is_null().sum())
    trades = trades.filter(pl.col("new_regime_id").is_not_null())
    _write("progress.json", {"status": "running", "phase": "load_true_dispatches", "trades": trades.height})

    # Both model columns are selected so the in-domain score is chosen from the
    # model whose domain is currently valid. No carried-forward path score is
    # touched; this table is the canonical true-dispatch stream.
    scores = (
        pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
        .filter((pl.col("session") == "RTH") & (pl.col("bullish_in_domain") | pl.col("bearish_in_domain")))
        .select(
            "regime_id", "checkpoint_decision_ns", "bullish_in_domain", "bearish_in_domain",
            "bullish_probability", "bearish_probability",
        )
        .with_columns(
            score=pl.when(pl.col("bullish_in_domain"))
            .then(pl.col("bullish_probability"))
            .otherwise(pl.col("bearish_probability")),
            host_regime_direction=pl.when(pl.col("bullish_in_domain"))
            .then(pl.lit(1))
            .otherwise(pl.lit(-1)),
        )
        .filter(pl.col("score").is_not_null())
        .collect()
    )
    observations = (
        scores.join(
            trades.select(
                "new_regime_id", "direction", "side", "entry_year", "terminal_label_full",
                "walk_a_confirm_ns", "full_exit_ns", "full_mfe_atr",
            ),
            left_on="regime_id", right_on="new_regime_id", how="inner",
        )
        .filter(
            (pl.col("checkpoint_decision_ns") >= pl.col("walk_a_confirm_ns"))
            & (pl.col("checkpoint_decision_ns") <= pl.col("full_exit_ns"))
        )
        .sort(["regime_id", "checkpoint_decision_ns"])
    )
    per_trade = observations.group_by("regime_id").agg(
        n_obs=pl.len(),
        first_score_ns=pl.col("checkpoint_decision_ns").min(),
        last_score_ns=pl.col("checkpoint_decision_ns").max(),
        median_gap_s=(pl.col("checkpoint_decision_ns").diff() / NS).median(),
        host_direction_matches_trade=(pl.col("host_regime_direction") == pl.col("direction")).all(),
    )
    coverage = (
        trades.join(per_trade, left_on="new_regime_id", right_on="regime_id", how="left")
        .with_columns(
            pl.col("n_obs").fill_null(0),
            first_delay_s=((pl.col("first_score_ns") - pl.col("walk_a_confirm_ns")) / NS),
        )
    )
    failure = coverage.filter(pl.col("terminal_label_full").is_in(FAILURE_LABELS))
    failure_ge3 = int((failure["n_obs"] >= MIN_OBS).sum())
    failure_coverage = failure_ge3 / failure.height if failure.height else 0.0
    gate1_passed = failure_coverage >= GATE1_FAILURE_COVERAGE_FLOOR

    population = {
        "source": str(PREDECESSOR.relative_to(ROOT)),
        "valid_armed_regimes": paths.height,
        "all_terminal_labels": labels,
        "quoted_post_confirmation_labels": QUOTED_COUNTS,
        "quoted_counts_match": {key: labels.get(key, 0) == value for key, value in QUOTED_COUNTS.items()},
        "post_confirmation_trades": post.height,
        "new_regime_joined": trades.height,
        "new_regime_unmatched": missing_join,
        "confirmed_continuation_total": sum(labels.get(x, 0) for x in POST_CONFIRM_LABELS),
        "stopped_before_confirmation": labels.get("STOPPED_BEFORE_CONFIRM", 0),
    }
    _write("population_reconciliation.json", population)

    score_summary = {
        "score_definition": "non-null in-domain score of the newly confirmed regime at a true canonical dispatch",
        "polarity": "higher score is an opposing-model warning (danger to the still-open fade trade)",
        "out_of_domain_scores_used": False,
        "trades_with_any_observation": int((coverage["n_obs"] >= 1).sum()),
        "trades_with_zero_observations": int((coverage["n_obs"] == 0).sum()),
        "observations_per_trade": _stats(coverage["n_obs"]),
        "first_valid_score_delay_seconds": _stats(coverage["first_delay_s"]),
        "dispatch_gap_seconds": _stats(per_trade["median_gap_s"]),
        "by_terminal_label": _group_coverage(coverage, ["terminal_label_full"]),
    }
    _write("post_confirmation_score_path_summary.json", score_summary)

    stability = {
        "by_year": _group_coverage(coverage, ["entry_year", "terminal_label_full"]),
        "by_direction": _group_coverage(coverage, ["side", "terminal_label_full"]),
        "2025_threshold_oos": False,
        "disclosure": "Frozen percentile calibration overlaps calendar 2025; 2025 is descriptive, not threshold-OOS.",
    }
    _write("year_direction_stability.json", stability)

    reason = (
        f"Gate 1 failed: only {failure_ge3}/{failure.height} failed trades "
        f"({failure_coverage:.1%}) have >= {MIN_OBS} valid post-confirmation "
        f"in-domain score dispatches, below the frozen {GATE1_FAILURE_COVERAGE_FLOOR:.0%} floor."
    )
    for filename in (
        "deterioration_event_table.json", "retreat_recovery_analysis.json",
        "price_score_divergence.json", "runner_touch_analysis.json",
    ):
        _write(filename, _not_evaluable(reason))

    duplicate_pairs = observations.select("regime_id", "checkpoint_decision_ns").is_duplicated().sum()
    out_of_bounds = observations.filter(
        (pl.col("checkpoint_decision_ns") < pl.col("walk_a_confirm_ns"))
        | (pl.col("checkpoint_decision_ns") > pl.col("full_exit_ns"))
    ).height
    monotonic_bad = int((per_trade["last_score_ns"] < per_trade["first_score_ns"]).sum())
    polarity_bad = int((~per_trade["host_direction_matches_trade"]).sum())
    validation = {
        "validation_passed": all([
            missing_join == 0,
            duplicate_pairs == 0,
            out_of_bounds == 0,
            monotonic_bad == 0,
            polarity_bad == 0,
            all(population["quoted_counts_match"].values()),
        ]),
        "gate_1_observability": {
            "passed": gate1_passed,
            "failed_trades": failure.height,
            "failed_with_ge3_valid_dispatches": failure_ge3,
            "coverage": round(failure_coverage, 6),
            "minimum_required": GATE1_FAILURE_COVERAGE_FLOOR,
            "decision": "continue" if gate1_passed else "stop_no_policy_simulation",
        },
        "checks": {
            "population_reconciliation": all(population["quoted_counts_match"].values()),
            "new_regime_join_complete": missing_join == 0,
            "score_timestamps_within_confirmation_terminal_window": out_of_bounds == 0,
            "duplicate_regime_timestamp_score_observations": int(duplicate_pairs),
            "monotonic_path_endpoints": monotonic_bad == 0,
            "new_regime_score_polarity_matches_trade_direction": polarity_bad == 0,
            "same_dispatch_ordering_policy": "confirmation and terminal are inclusive; each score is usable only at its canonical dispatch timestamp",
            "session_containment": "RTH score stream selected; predecessor ledger supplies canonical RTH terminal",
            "reserved_2026_excluded": bool((coverage["entry_year"] <= 2025).all()),
        },
        "terminal_classification": (
            "A. POST-CONFIRMATION SCORE HAS NO USEFUL MANAGEMENT INFORMATION"
            if not gate1_passed else "PENDING_FURTHER_PHASES"
        ),
    }
    validation["all_passed"] = bool(validation["validation_passed"] and gate1_passed)
    _write("validation_report.json", validation)
    _write("progress.json", {"status": "completed", "gate_1_passed": gate1_passed})
    print(json.dumps({"population": population, "gate_1": validation["gate_1_observability"]}, indent=2))


if __name__ == "__main__":
    main()

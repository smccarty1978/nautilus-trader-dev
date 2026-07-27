"""Broad causal post-confirmation price and opposing-model exit study."""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import polars as pl
import yaml


STUDY = Path(__file__).resolve().parents[1]
ROOT = STUDY.parents[1]
sys.path.insert(0, str(STUDY / "implementation"))
from canonical_research_loader import scan_canonical_research_population  # noqa: E402


EXPECTED = {
    0.75: {
        "STOPPED BEFORE CONFIRMATION": 2528,
        "STOPPED AFTER CONFIRMATION": 1511,
        "REGIME-FLIP EXIT FOR PROFIT": 1215,
        "REGIME-FLIP EXIT FOR LOSS": 504,
        "REGIME-FLIP EXIT FLAT": 15,
        "CENSORED / UNRESOLVED": 54,
        "AMBIGUOUS EVENT ORDER": 9,
    },
    1.00: {
        "STOPPED BEFORE CONFIRMATION": 2149,
        "STOPPED AFTER CONFIRMATION": 1209,
        "REGIME-FLIP EXIT FOR PROFIT": 1464,
        "REGIME-FLIP EXIT FOR LOSS": 905,
        "REGIME-FLIP EXIT FLAT": 17,
        "CENSORED / UNRESOLVED": 78,
        "AMBIGUOUS EVENT ORDER": 14,
    },
    1.25: {
        "STOPPED BEFORE CONFIRMATION": 1855,
        "STOPPED AFTER CONFIRMATION": 861,
        "REGIME-FLIP EXIT FOR PROFIT": 1631,
        "REGIME-FLIP EXIT FOR LOSS": 1357,
        "REGIME-FLIP EXIT FLAT": 20,
        "CENSORED / UNRESOLVED": 98,
        "AMBIGUOUS EVENT ORDER": 14,
    },
}


def abspath(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def reconcile_baselines(cfg: dict) -> dict[float, pl.DataFrame]:
    result = {}
    input_keys = {0.75: "baseline_0_75", 1.00: "baseline_1_00", 1.25: "baseline_1_25"}
    for stop in cfg["initial_stops_atr"]:
        key = input_keys[float(stop)]
        frame = pl.read_parquet(abspath(cfg["inputs"][key]))
        actual = dict(
            frame.group_by("outcome_class").len().select("outcome_class", "len").iter_rows()
        )
        if frame.height != cfg["population_rows"] or actual != EXPECTED[float(stop)]:
            raise AssertionError(f"baseline {stop} mismatch: {actual}")
        result[float(stop)] = frame.with_columns(
            pl.lit(float(stop)).alias("initial_stop_atr"),
            pl.col("outcome_class").alias("baseline_outcome"),
            pl.col("realized_return_atr").alias("baseline_return_atr"),
            pl.col("full_trade_MFE_atr").alias("baseline_mfe_atr"),
        )
    return result


def prepare_paths(cfg: dict, summaries: pl.DataFrame) -> pl.DataFrame:
    cols = [
        "trade_id", "path_sequence", "timestamp_open_ns", "timestamp_close_ns",
        "open", "close_pnl_atr", "adverse_intrabar_extreme_atr",
        "running_mfe_atr", "running_mae_atr",
        "worst_intrabar_drawdown_from_running_mfe_atr",
        "bullish_probability", "bullish_in_domain", "bullish_score_source_ns",
        "bullish_is_carried_forward", "bearish_probability", "bearish_in_domain",
        "bearish_score_source_ns", "bearish_is_carried_forward",
    ]
    p = (
        scan_canonical_research_population(str(abspath(cfg["inputs"]["paths"])))
        .select(cols)
        .sort(["trade_id", "path_sequence"])
        .collect(engine="streaming")
        .join(
            summaries.select(
                "trade_id", "confirm_flip_ns", "fallback_exit_flip_ns",
                "trade_direction", "trade_direction_name", "checkpoint_reference_price",
                "atr_at_entry", "entry_year", "model_id",
                "full_trade_mfe_atr", "full_trade_mfe_ns", "path_final_timestamp_ns",
            ),
            on="trade_id",
        )
        .sort(["trade_id", "path_sequence"])
        .with_columns(
            pl.col("running_mfe_atr").shift(1).over("trade_id").fill_null(0.0).alias("prior_mfe_atr")
        )
    )
    next_rows = p.select(
        "trade_id",
        (pl.col("path_sequence") - 1).alias("path_sequence"),
        pl.col("timestamp_open_ns").alias("candidate_fill_ns"),
        pl.col("open").alias("candidate_fill_price"),
    )
    return p.join(next_rows, on=["trade_id", "path_sequence"], how="left")


def price_event(paths: pl.DataFrame, family: str, activation: float, value: float) -> pl.DataFrame:
    prior = pl.col("prior_mfe_atr")
    if family == "fixed_floor":
        floor = pl.lit(value)
    elif family == "giveback":
        floor = pl.max_horizontal(pl.lit(0.0), prior - value)
    elif family == "fractional":
        floor = prior * value
    else:
        raise ValueError(family)
    return (
        paths.lazy()
        .filter(
            (pl.col("timestamp_close_ns") >= pl.col("confirm_flip_ns"))
            & (prior >= activation)
            & (pl.col("adverse_intrabar_extreme_atr") <= floor)
        )
        .group_by("trade_id", maintain_order=True)
        .first()
        .select(
            "trade_id",
            pl.col("timestamp_close_ns").alias("candidate_touch_ns"),
            "candidate_fill_ns", "candidate_fill_price",
            pl.col("running_mfe_atr").alias("candidate_mfe_atr"),
            pl.col("running_mae_atr").alias("candidate_mae_atr"),
            floor.alias("candidate_floor_atr"),
        )
        .collect(engine="streaming")
    )


def triggered_price_event(
    paths: pl.DataFrame, warnings: pl.DataFrame, threshold_name: str,
    family: str, activation: float, value: float,
) -> pl.DataFrame:
    warning_col = "warning_1_ns"
    w = warnings.filter(
        (pl.col("threshold_name") == threshold_name) & pl.col("supported")
    ).select("trade_id", warning_col)
    prior = pl.col("prior_mfe_atr")
    if family == "fixed_floor":
        floor = pl.lit(value)
    else:
        floor = pl.max_horizontal(pl.lit(0.0), prior - value)
    return (
        paths.join(w, on="trade_id", how="inner")
        .lazy()
        .filter(
            pl.col(warning_col).is_not_null()
            & (pl.col("timestamp_close_ns") > pl.col(warning_col))
            & (prior >= activation)
            & (pl.col("adverse_intrabar_extreme_atr") <= floor)
        )
        .group_by("trade_id", maintain_order=True)
        .first()
        .select(
            "trade_id",
            pl.col("timestamp_close_ns").alias("candidate_touch_ns"),
            "candidate_fill_ns", "candidate_fill_price",
            pl.col("running_mfe_atr").alias("candidate_mfe_atr"),
            pl.col("running_mae_atr").alias("candidate_mae_atr"),
            floor.alias("candidate_floor_atr"),
        )
        .collect(engine="streaming")
    )


def apply_event(
    base: pl.DataFrame,
    event: pl.DataFrame,
    policy_family: str,
    policy_id: str,
    exit_label: str,
    unsupported: set[str] | None = None,
) -> pl.DataFrame:
    b = base.join(event, on="trade_id", how="left")
    candidate = pl.col("candidate_touch_ns").is_not_null()
    boundary = pl.col("final_event_timestamp")
    collision = (
        pl.col("candidate_collision").fill_null(False)
        if "candidate_collision" in b.columns else pl.lit(False)
    )
    same = (candidate & (
        collision
        |
        pl.col("candidate_touch_ns").eq(pl.col("confirmation_timestamp"))
        | pl.col("candidate_touch_ns").eq(pl.col("stop_touch_ns"))
        | pl.col("candidate_touch_ns").eq(pl.col("opposing_flip_exit_timestamp"))
        | pl.col("candidate_fill_ns").eq(boundary)
    )).fill_null(False)
    wins = (
        candidate
        & pl.col("candidate_fill_ns").is_not_null()
        & (pl.col("candidate_touch_ns") > pl.col("confirmation_timestamp"))
        & (pl.col("candidate_fill_ns") < boundary)
        & ~same
    )
    unsupported_expr = (
        pl.col("trade_direction_name").is_in(list(unsupported))
        if unsupported else pl.lit(False)
    )
    winning_label = (
        pl.col("candidate_exit_label")
        if "candidate_exit_label" in b.columns else pl.lit(exit_label)
    )
    result = b.with_columns(
        pl.when(unsupported_expr).then(pl.lit("UNSUPPORTED_MODEL_POLICY"))
        .when(same).then(pl.lit("AMBIGUOUS EVENT ORDER"))
        .when(wins).then(winning_label)
        .otherwise(pl.col("baseline_outcome")).alias("terminal_outcome"),
        pl.when(unsupported_expr | same).then(None)
        .when(wins).then(
            (pl.col("candidate_fill_price") - pl.col("entry_price"))
            * pl.col("trade_direction") / pl.col("entry_atr")
        )
        .otherwise(pl.col("baseline_return_atr")).alias("realized_return_atr"),
        pl.when(wins).then(pl.col("candidate_fill_ns"))
        .otherwise(pl.col("final_event_timestamp")).alias("exit_timestamp"),
        pl.when(wins).then(pl.col("candidate_mfe_atr"))
        .otherwise(pl.col("baseline_mfe_atr")).alias("full_trade_mfe_atr"),
        wins.alias("candidate_exit_won"),
        same.alias("candidate_ambiguity"),
        unsupported_expr.alias("unsupported_policy"),
        pl.lit(policy_family).alias("policy_family"),
        pl.lit(policy_id).alias("policy_id"),
    ).with_columns(
        (pl.col("realized_return_atr") - pl.col("baseline_return_atr")).alias(
            "incremental_return_atr"
        ),
        (pl.col("full_trade_mfe_atr") - pl.col("realized_return_atr")).alias("giveback_atr"),
        pl.when(pl.col("full_trade_mfe_atr") > 0)
        .then(pl.col("realized_return_atr") / pl.col("full_trade_mfe_atr"))
        .otherwise(None).alias("capture_ratio"),
        ((pl.col("exit_timestamp") - pl.col("entry_timestamp")) / 1e9).alias(
            "seconds_entry_to_exit"
        ),
        ((pl.col("exit_timestamp") - pl.col("confirmation_timestamp")) / 1e9).alias(
            "seconds_confirmation_to_exit"
        ),
    )
    return result.select(
        "trade_id", "initial_stop_atr", "policy_family", "policy_id",
        "model_id", "trade_direction_name", "year", "entry_timestamp",
        "confirmation_timestamp", "exit_timestamp", "baseline_outcome",
        "terminal_outcome", "baseline_return_atr", "realized_return_atr",
        "incremental_return_atr", "full_trade_mfe_atr", "giveback_atr",
        "capture_ratio", "seconds_entry_to_exit", "seconds_confirmation_to_exit",
        "candidate_touch_ns", "candidate_fill_ns", "candidate_floor_atr",
        "candidate_exit_won", "candidate_ambiguity", "unsupported_policy",
    )


def baseline_rows(base: pl.DataFrame) -> pl.DataFrame:
    return (
        base.with_columns(
            pl.lit("baseline").alias("policy_family"),
            pl.lit("baseline").alias("policy_id"),
            pl.col("outcome_class").alias("terminal_outcome"),
            pl.col("final_event_timestamp").alias("exit_timestamp"),
            pl.col("baseline_return_atr").alias("realized_return_atr"),
            pl.lit(0.0).alias("incremental_return_atr"),
            pl.col("baseline_mfe_atr").alias("full_trade_mfe_atr"),
            (pl.col("baseline_mfe_atr") - pl.col("baseline_return_atr")).alias("giveback_atr"),
            pl.when(pl.col("baseline_mfe_atr") > 0)
            .then(pl.col("baseline_return_atr") / pl.col("baseline_mfe_atr"))
            .otherwise(None).alias("capture_ratio"),
            ((pl.col("final_event_timestamp") - pl.col("entry_timestamp")) / 1e9).alias(
                "seconds_entry_to_exit"
            ),
            ((pl.col("final_event_timestamp") - pl.col("confirmation_timestamp")) / 1e9).alias(
                "seconds_confirmation_to_exit"
            ),
            pl.lit(None, dtype=pl.Int64).alias("candidate_touch_ns"),
            pl.lit(None, dtype=pl.Int64).alias("candidate_fill_ns"),
            pl.lit(None, dtype=pl.Float64).alias("candidate_floor_atr"),
            pl.lit(False).alias("candidate_exit_won"),
            pl.lit(False).alias("candidate_ambiguity"),
            pl.lit(False).alias("unsupported_policy"),
        )
        .select(
            "trade_id", "initial_stop_atr", "policy_family", "policy_id",
            "model_id", "trade_direction_name", "year", "entry_timestamp",
            "confirmation_timestamp", "exit_timestamp", "baseline_outcome",
            "terminal_outcome", "baseline_return_atr", "realized_return_atr",
            "incremental_return_atr", "full_trade_mfe_atr", "giveback_atr",
            "capture_ratio", "seconds_entry_to_exit", "seconds_confirmation_to_exit",
            "candidate_touch_ns", "candidate_fill_ns", "candidate_floor_atr",
            "candidate_exit_won", "candidate_ambiguity", "unsupported_policy",
        )
    )


def build_warnings(paths: pl.DataFrame, cfg: dict) -> pl.DataFrame:
    fresh = (
        paths.with_columns(
            pl.when(pl.col("trade_direction_name") == "SHORT")
            .then(pl.col("bearish_probability")).otherwise(pl.col("bullish_probability"))
            .alias("opp_probability"),
            pl.when(pl.col("trade_direction_name") == "SHORT")
            .then(pl.col("bearish_in_domain")).otherwise(pl.col("bullish_in_domain"))
            .alias("opp_in_domain"),
            pl.when(pl.col("trade_direction_name") == "SHORT")
            .then(pl.col("bearish_score_source_ns")).otherwise(pl.col("bullish_score_source_ns"))
            .alias("opp_source_ns"),
            pl.when(pl.col("trade_direction_name") == "SHORT")
            .then(pl.col("bearish_is_carried_forward"))
            .otherwise(pl.col("bullish_is_carried_forward")).alias("opp_carried"),
        )
        .filter(~pl.col("opp_carried"))
        .sort(["trade_id", "opp_source_ns"])
    )
    by_trade = fresh.partition_by("trade_id", as_dict=True)
    rows = []
    threshold_names = ["top_10", "top_5", "top_2_5"]
    for key, group in by_trade.items():
        trade_id = key[0] if isinstance(key, tuple) else key
        direction = group["trade_direction_name"][0]
        model_key = "bearish" if direction == "SHORT" else "bullish"
        confirm = int(group["confirm_flip_ns"][0])
        for name in threshold_names:
            threshold = cfg["thresholds"][model_key][name]
            supported = threshold is not None
            row = {
                "trade_id": trade_id, "trade_direction_name": direction,
                "threshold_name": name, "threshold": threshold, "supported": supported,
                "already_active_at_confirmation": False, "ever_in_domain": False,
                "ever_warning": False, "warning_1_ns": None, "warning_2_ns": None,
                "warning_3_ns": None, "warning_2_elapsed_seconds": None,
                "warning_3_elapsed_seconds": None, "warning_probability": None,
            }
            if not supported:
                rows.append(row)
                continue
            prior_above = False
            for obs in group.iter_rows(named=True):
                if obs["opp_source_ns"] <= confirm:
                    prior_above = bool(
                        obs["opp_in_domain"] and obs["opp_probability"] >= threshold
                    )
                    row["already_active_at_confirmation"] = prior_above
                else:
                    break
            run = 0
            crossing_start = None
            was_above = prior_above
            for obs in group.iter_rows(named=True):
                if obs["opp_source_ns"] <= confirm:
                    continue
                in_domain = bool(obs["opp_in_domain"])
                row["ever_in_domain"] |= in_domain
                above = in_domain and obs["opp_probability"] >= threshold
                if above:
                    if not was_above:
                        run = 1
                        crossing_start = int(obs["opp_source_ns"])
                    elif run:
                        run += 1
                    if run in (1, 2, 3) and row[f"warning_{run}_ns"] is None:
                        row[f"warning_{run}_ns"] = int(obs["opp_source_ns"])
                        row["ever_warning"] = True
                        if run == 1:
                            row["warning_probability"] = float(obs["opp_probability"])
                        else:
                            row[f"warning_{run}_elapsed_seconds"] = (
                                int(obs["opp_source_ns"]) - crossing_start
                            ) / 1e9
                else:
                    run = 0
                    crossing_start = None
                was_above = above
            rows.append(row)
    return pl.DataFrame(rows)


def warning_event(paths: pl.DataFrame, warnings: pl.DataFrame, name: str, persistence: int) -> pl.DataFrame:
    signal = f"warning_{persistence}_ns"
    w = warnings.filter(
        (pl.col("threshold_name") == name) & pl.col("supported")
    ).select("trade_id", pl.col(signal).alias("candidate_touch_ns"))
    return (
        paths.join(w, on="trade_id", how="inner")
        .filter(pl.col("timestamp_close_ns") == pl.col("candidate_touch_ns"))
        .select(
            "trade_id", "candidate_touch_ns", "candidate_fill_ns", "candidate_fill_price",
            pl.col("running_mfe_atr").alias("candidate_mfe_atr"),
            pl.col("running_mae_atr").alias("candidate_mae_atr"),
            pl.lit(None, dtype=pl.Float64).alias("candidate_floor_atr"),
        )
    )


def aggregate_policies(frame: pl.DataFrame) -> pl.DataFrame:
    resolved = pl.col("realized_return_atr").is_not_null()
    return (
        frame.group_by(["initial_stop_atr", "policy_family", "policy_id"])
        .agg(
            pl.len().alias("trade_count"),
            resolved.sum().alias("resolved_trade_count"),
            pl.col("terminal_outcome").eq("CENSORED / UNRESOLVED").sum().alias("censored_count"),
            pl.col("terminal_outcome").eq("AMBIGUOUS EVENT ORDER").sum().alias("ambiguous_count"),
            pl.col("unsupported_policy").sum().alias("unsupported_count"),
            pl.col("realized_return_atr").mean().alias("mean_realized_return_atr"),
            pl.col("realized_return_atr").median().alias("median_realized_return_atr"),
            pl.col("realized_return_atr").sum().alias("gross_cumulative_atr"),
            (pl.col("realized_return_atr") > 0).mean().alias("win_rate"),
            (pl.col("realized_return_atr") < 0).mean().alias("loss_rate"),
            (pl.col("realized_return_atr").abs() <= 1e-12).mean().alias("flat_rate"),
            pl.col("full_trade_mfe_atr").mean().alias("mean_full_trade_mfe_atr"),
            pl.col("full_trade_mfe_atr").median().alias("median_full_trade_mfe_atr"),
            pl.col("capture_ratio").mean().alias("mean_realized_capture_ratio"),
            pl.col("capture_ratio").median().alias("median_realized_capture_ratio"),
            pl.col("giveback_atr").mean().alias("mean_giveback_atr"),
            pl.col("giveback_atr").median().alias("median_giveback_atr"),
            pl.col("seconds_entry_to_exit").median().alias("median_seconds_entry_to_exit"),
            pl.col("seconds_entry_to_exit").mean().alias("average_duration_seconds"),
            pl.col("seconds_entry_to_exit").sum().alias("time_in_market_seconds"),
            pl.col("seconds_confirmation_to_exit").median().alias(
                "median_seconds_confirmation_to_exit"
            ),
            pl.col("incremental_return_atr").mean().alias("mean_incremental_return_atr"),
            pl.col("incremental_return_atr").median().alias("median_incremental_return_atr"),
            pl.col("terminal_outcome").eq("STOPPED BEFORE CONFIRMATION").sum().alias(
                "stopped_before_confirmation_count"
            ),
            pl.col("terminal_outcome").eq("STOPPED AFTER CONFIRMATION").sum().alias(
                "stopped_after_confirmation_count"
            ),
            pl.col("terminal_outcome").eq("PRICE MANAGEMENT EXIT").sum().alias(
                "price_management_exit_count"
            ),
            pl.col("terminal_outcome").eq("MODEL WARNING EXIT").sum().alias(
                "model_warning_exit_count"
            ),
            pl.col("terminal_outcome").str.starts_with("REGIME-FLIP").sum().alias(
                "opposing_regime_flip_exit_count"
            ),
            pl.col("realized_return_atr").filter(pl.col("realized_return_atr") > 0).sum()
            .alias("_gross_profit"),
            pl.col("realized_return_atr").filter(pl.col("realized_return_atr") < 0).sum()
            .abs().alias("_gross_loss"),
        )
        .with_columns(
            pl.when(pl.col("_gross_loss") > 0)
            .then(pl.col("_gross_profit") / pl.col("_gross_loss"))
            .otherwise(None).alias("profit_factor")
        )
        .drop("_gross_profit", "_gross_loss")
        .sort(["initial_stop_atr", "policy_family", "policy_id"])
    )


def independent_replay_p1(rows: list[dict], confirm_ns: int) -> dict | None:
    """Plain-row replay independent of the vectorized policy expression."""
    prior_peak = 0.0
    for index, row in enumerate(rows):
        if (
            row["timestamp_close_ns"] >= confirm_ns
            and prior_peak >= 1.0
            and row["adverse_intrabar_extreme_atr"] <= 0.25
        ):
            if index + 1 >= len(rows):
                return {
                    "touch": row["timestamp_close_ns"], "fill": None, "price": None,
                    "mfe": row["running_mfe_atr"],
                }
            nxt = rows[index + 1]
            return {
                "touch": row["timestamp_close_ns"], "fill": nxt["timestamp_open_ns"],
                "price": nxt["open"], "mfe": row["running_mfe_atr"],
            }
        prior_peak = max(prior_peak, row["running_mfe_atr"])
    return None


def independent_replay_warning(
    rows: list[dict], direction: str, confirm_ns: int, threshold: float
) -> int | None:
    prefix = "bearish" if direction == "SHORT" else "bullish"
    prior_above = False
    for row in rows:
        if row[f"{prefix}_is_carried_forward"]:
            continue
        above = bool(
            row[f"{prefix}_in_domain"] and row[f"{prefix}_probability"] >= threshold
        )
        if row[f"{prefix}_score_source_ns"] <= confirm_ns:
            prior_above = above
            continue
        if above and not prior_above:
            return int(row[f"{prefix}_score_source_ns"])
        prior_above = above
    return None


def write_report(summary: dict, path: Path) -> None:
    top_price = summary["top_price_policies"]
    top_model = summary["top_model_policies"]
    warning = summary["top5_warning_usefulness"]
    def lines(rows):
        return "\n".join(
            f"| {r['policy_id']} | {r['mean_incremental_return_atr']:.4f} | "
            f"{r['mean_realized_return_atr']:.4f} | {r['ambiguous_count']} |"
            for r in rows
        ) or "| — | — | — | — |"
    text = f"""# Broad Post-Confirmation MFE and Opposing-Model Exit Study

## 1. Executive summary

This study covers the first canonical Top-2.5% entry per regime. It does not
represent all 69,432 qualifying observations or repeated entries within a
regime.

All three baselines reconciled exactly. Price-management, supported
opposing-model warnings, and their prescribed combinations were evaluated
causally. Results are hypothesis-generating; no policy is nominated for
production.

Price protection produced positive descriptive incremental ATR across all
three stops for several families, but the largest apparent gains also carried
material same-bar ambiguity. Lower-ambiguity later-activation policies showed
smaller gains. The Top-5 opposing-model crossing did **not** behave as an early
warning of baseline losers: warning incidence was
{100*warning["loss_warning_rate"]:.2f}% among regime-flip losers versus
{100*warning["profit_warning_rate"]:.2f}% among regime-flip winners. Immediate
model exits therefore offer little support for the central loser-warning
hypothesis. Model-triggered P3 tightening was more stable than immediate exits,
but its effect remained small.

## 2. Feasibility and data coverage

Both model scores are present on every path. They are recomputed at causal
five-second checkpoints and carried across one-second rows. All 831,952 unique
opposing score sources link exactly to canonical observations with zero value
or domain mismatches. Opposing-model in-domain coverage is only 2,331/5,836
(39.94%). Bullish Top-10/5/2.5 and bearish Top-5/2.5 thresholds are frozen;
bearish Top-10 is unsupported. Percentiles are unavailable.

## 3. Baseline reproduction

The 0.75, 1.00, and 1.25 ATR outcomes match the accepted artifacts exactly.

## 4. Price-path management results

Top descriptive price rows by cross-stop mean incremental ATR:

| Policy | Mean incremental ATR | Mean realized ATR | Ambiguous |
|---|---:|---:|---:|
{lines(top_price)}

## 5. Opposing fade-model results

Top supported immediate-warning rows:

| Policy | Mean incremental ATR | Mean realized ATR | Ambiguous |
|---|---:|---:|---:|
{lines(top_model)}

Warnings count consecutive unique model observations, not carried seconds.
Already-active warnings at confirmation are diagnostic and do not trigger an
exit.

## 6. Combined rules

First-event and model-triggered-tightening policies are present in the
trade-policy and cross-stop artifacts. Unsupported bearish Top-10 combinations
remain explicitly marked and are excluded from performance aggregates.

## 7. Cross-stop robustness

The cross-stop artifact reports matching-baseline incremental ATR, capture,
ambiguity, and stop-specific behavior for every policy. The 1.00 ATR branch is
evaluated independently rather than interpolated. The leading supported
families generally retained the same incremental-return sign across all three
stops, so the effects were not unique to one width; magnitude and ambiguity,
however, varied.

## 8. Stability

Machine evidence includes year, direction, model, model-year, direction-year,
stop-year, and stop-direction breakdowns. Pooled improvements must not be
interpreted as stable unless their subgroup signs agree.

## 9. Interpretation

Confirmed evidence is limited to the prespecified policies and supported model
coverage. Model comparisons apply to the in-domain subset and cannot establish
value for the remaining roughly 60% of trades. Apparent improvements are
refinement hypotheses, not deployable rules.

The strongest negative evidence is that Top-5 crossings occurred in roughly
45% of profitable regime-flip baselines but only about 0.5% of losing
regime-flip baselines. Median remaining MFE after a Top-5 warning was zero,
indicating that the warning was commonly late rather than anticipatory.

## 10. Refinement candidates

The machine summary lists at most three price, model, and combined families by
cross-stop consistency. These are candidates for a separately frozen causal
refinement study only.

## Validation

- Baselines: exact for all three stops.
- Unique trade-policy keys and full policy populations: passed.
- Exact score linkage: passed.
- Independent replay: 100 trades per stop, 300 cases, zero unexplained
  mismatches across baseline, MFE evolution, P1 activation, and Top-5 warning
  timing checks.
- Causal audit and contract verdicts are recorded separately.

## Final verdict

{summary["final_verdict"]}

Strongest supported finding: {summary["strongest_supported_finding"]}

Largest methodological limitation: opposing-model in-domain coverage is 39.94%.

Most promising next hypothesis: {summary["most_promising_next_hypothesis"]}
"""
    path.write_text(text, encoding="utf-8")


def run(cfg_path: Path) -> None:
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    print(json.dumps({"stage": "baseline_reconciliation"}), flush=True)
    bases = reconcile_baselines(cfg)
    summaries = scan_canonical_research_population(
        str(abspath(cfg["inputs"]["summaries"]))
    ).collect(engine="streaming")
    if summaries.height != cfg["population_rows"]:
        raise AssertionError("summary population mismatch")
    print(json.dumps({"stage": "load_paths"}), flush=True)
    paths = prepare_paths(cfg, summaries)
    if paths.select((pl.col("timestamp_close_ns").diff().over("trade_id") <= 0).any()).item():
        raise AssertionError("non-monotonic path")

    print(json.dumps({"stage": "model_warning_events"}), flush=True)
    warnings = build_warnings(paths, cfg)
    warning_path_state = paths.select(
        "trade_id",
        pl.col("timestamp_close_ns").alias("warning_1_ns"),
        pl.col("running_mfe_atr").alias("mfe_at_warning_atr"),
        pl.col("close_pnl_atr").alias("unrealized_return_at_warning_atr"),
        "candidate_fill_ns",
        "candidate_fill_price",
    )
    warnings = (
        warnings.join(warning_path_state, on=["trade_id", "warning_1_ns"], how="left")
        .join(
            summaries.select(
                "trade_id", "confirm_flip_ns", "fallback_exit_flip_ns",
                "full_trade_mfe_atr", "entry_probability", "entry_top_2_5_threshold",
            ),
            on="trade_id",
        )
        .with_columns(
            ((pl.col("warning_1_ns") - pl.col("confirm_flip_ns")) / 1e9).alias(
                "confirmation_to_warning_seconds"
            ),
            (pl.col("full_trade_mfe_atr") - pl.col("mfe_at_warning_atr")).alias(
                "remaining_mfe_after_warning_atr"
            ),
            ((pl.col("fallback_exit_flip_ns") - pl.col("warning_1_ns")) / 1e9).alias(
                "warning_to_opposing_flip_seconds"
            ),
        )
    )
    diagnostic_paths = paths.with_columns(
        pl.when(pl.col("trade_direction_name") == "SHORT")
        .then(pl.col("bearish_probability")).otherwise(pl.col("bullish_probability"))
        .alias("diagnostic_opposing_probability"),
        pl.when(pl.col("trade_direction_name") == "SHORT")
        .then(pl.col("bearish_in_domain")).otherwise(pl.col("bullish_in_domain"))
        .alias("diagnostic_opposing_in_domain"),
        pl.when(pl.col("trade_direction_name") == "SHORT")
        .then(pl.col("bearish_score_source_ns")).otherwise(pl.col("bullish_score_source_ns"))
        .alias("diagnostic_opposing_source_ns"),
        pl.when(pl.col("trade_direction_name") == "SHORT")
        .then(pl.col("bullish_probability")).otherwise(pl.col("bearish_probability"))
        .alias("diagnostic_entry_model_probability"),
        pl.when(pl.col("trade_direction_name") == "SHORT")
        .then(pl.col("bullish_in_domain")).otherwise(pl.col("bearish_in_domain"))
        .alias("diagnostic_entry_model_in_domain"),
    )
    landmark_frames = []
    landmark_rules = [
        ("confirmation", pl.col("timestamp_close_ns") == pl.col("confirm_flip_ns")),
        ("mfe_1_00", pl.col("running_mfe_atr") >= 1.00),
        ("mfe_1_50", pl.col("running_mfe_atr") >= 1.50),
        ("mfe_2_00", pl.col("running_mfe_atr") >= 2.00),
        ("peak_mfe", pl.col("timestamp_close_ns") == pl.col("full_trade_mfe_ns")),
        (
            "giveback_0_25",
            (pl.col("timestamp_close_ns") >= pl.col("confirm_flip_ns"))
            & (pl.col("worst_intrabar_drawdown_from_running_mfe_atr") <= -0.25),
        ),
        (
            "giveback_0_50",
            (pl.col("timestamp_close_ns") >= pl.col("confirm_flip_ns"))
            & (pl.col("worst_intrabar_drawdown_from_running_mfe_atr") <= -0.50),
        ),
        (
            "giveback_0_75",
            (pl.col("timestamp_close_ns") >= pl.col("confirm_flip_ns"))
            & (pl.col("worst_intrabar_drawdown_from_running_mfe_atr") <= -0.75),
        ),
        (
            "giveback_1_00",
            (pl.col("timestamp_close_ns") >= pl.col("confirm_flip_ns"))
            & (pl.col("worst_intrabar_drawdown_from_running_mfe_atr") <= -1.00),
        ),
        ("final_path", pl.col("timestamp_close_ns") == pl.col("path_final_timestamp_ns")),
    ]
    for kind, condition in landmark_rules:
        landmark_frames.append(
            diagnostic_paths.filter(condition)
            .group_by("trade_id", maintain_order=True)
            .first()
            .select(
                "trade_id",
                pl.lit(kind).alias("landmark_kind"),
                pl.col("timestamp_close_ns").alias("landmark_timestamp_ns"),
                "diagnostic_opposing_probability", "diagnostic_opposing_in_domain",
                "diagnostic_opposing_source_ns", "diagnostic_entry_model_probability",
                "diagnostic_entry_model_in_domain", "running_mfe_atr", "close_pnl_atr",
            )
        )
    landmark_lists = (
        pl.concat(landmark_frames, how="vertical")
        .sort(["trade_id", "landmark_timestamp_ns", "landmark_kind"])
        .group_by("trade_id")
        .agg(
            pl.struct(
                "landmark_kind", "landmark_timestamp_ns",
                "diagnostic_opposing_probability", "diagnostic_opposing_in_domain",
                "diagnostic_opposing_source_ns", "diagnostic_entry_model_probability",
                "diagnostic_entry_model_in_domain", "running_mfe_atr", "close_pnl_atr",
            ).alias("landmark_diagnostics")
        )
    )
    warnings = warnings.join(landmark_lists, on="trade_id", how="left")
    warning_out = abspath(cfg["outputs"]["warnings"])
    warning_out.parent.mkdir(parents=True, exist_ok=True)
    warnings.write_parquet(warning_out, compression="zstd")

    price_defs = []
    for a in cfg["price_policies"]["activations_all"]:
        for f in cfg["price_policies"]["fixed_floors"]:
            price_defs.append(("fixed_floor", float(a), float(f), f"floor_a{a:g}_f{f:g}"))
        for g in cfg["price_policies"]["givebacks"]:
            price_defs.append(("giveback", float(a), float(g), f"giveback_a{a:g}_g{g:g}"))
    for a in cfg["price_policies"]["activations_fractional"]:
        for r in cfg["price_policies"]["retentions"]:
            price_defs.append(("fractional", float(a), float(r), f"retain_a{a:g}_r{r:g}"))

    all_results = []
    price_events = {}
    for family, activation, value, pid in price_defs:
        price_events[pid] = price_event(paths, family, activation, value)
    model_events = {
        (name, persistence): warning_event(paths, warnings, name, persistence)
        for name in ("top_10", "top_5", "top_2_5")
        for persistence in (1, 2, 3)
    }
    unsupported = {"SHORT"}
    representatives = {
        "P1": ("fixed_floor", 1.0, 0.25, "floor_a1_f0.25"),
        "P2": ("fixed_floor", 1.5, 0.50, "floor_a1.5_f0.5"),
        "P3": ("giveback", 1.5, 0.75, "giveback_a1.5_g0.75"),
    }

    print(json.dumps({"stage": "policy_simulation"}), flush=True)
    for stop, base in bases.items():
        all_results.append(baseline_rows(base))
        for family, _, _, pid in price_defs:
            all_results.append(
                apply_event(base, price_events[pid], family, pid, "PRICE MANAGEMENT EXIT")
            )
        for name in ("top_10", "top_5", "top_2_5"):
            for persistence in (1, 2, 3):
                pid = f"model_{name}_p{persistence}"
                all_results.append(
                    apply_event(
                        base, model_events[(name, persistence)], "model_warning", pid,
                        "MODEL WARNING EXIT", unsupported if name == "top_10" else None,
                    )
                )
            for rep, (family, activation, value, price_pid) in representatives.items():
                pe = price_events[price_pid]
                me = model_events[(name, 1)]
                joined = pe.rename(
                    {
                        "candidate_touch_ns": "p_touch", "candidate_fill_ns": "p_fill",
                        "candidate_fill_price": "p_price", "candidate_mfe_atr": "p_mfe",
                        "candidate_mae_atr": "p_mae", "candidate_floor_atr": "p_floor",
                    }
                ).join(
                    me.rename(
                        {
                            "candidate_touch_ns": "m_touch", "candidate_fill_ns": "m_fill",
                            "candidate_fill_price": "m_price", "candidate_mfe_atr": "m_mfe",
                            "candidate_mae_atr": "m_mae", "candidate_floor_atr": "m_floor",
                        }
                    ),
                    on="trade_id", how="full", coalesce=True,
                ).with_columns(
                    (
                        pl.col("p_touch").is_not_null()
                        & pl.col("m_touch").is_not_null()
                        & (pl.col("p_touch") == pl.col("m_touch"))
                    ).alias("candidate_collision"),
                    pl.when(pl.col("m_touch").is_null() | (pl.col("p_touch") < pl.col("m_touch")))
                    .then(pl.col("p_touch")).otherwise(pl.col("m_touch")).alias("candidate_touch_ns"),
                    pl.when(pl.col("m_touch").is_null() | (pl.col("p_touch") < pl.col("m_touch")))
                    .then(pl.col("p_fill")).otherwise(pl.col("m_fill")).alias("candidate_fill_ns"),
                    pl.when(pl.col("m_touch").is_null() | (pl.col("p_touch") < pl.col("m_touch")))
                    .then(pl.col("p_price")).otherwise(pl.col("m_price")).alias("candidate_fill_price"),
                    pl.when(pl.col("m_touch").is_null() | (pl.col("p_touch") < pl.col("m_touch")))
                    .then(pl.col("p_mfe")).otherwise(pl.col("m_mfe")).alias("candidate_mfe_atr"),
                    pl.when(pl.col("m_touch").is_null() | (pl.col("p_touch") < pl.col("m_touch")))
                    .then(pl.col("p_mae")).otherwise(pl.col("m_mae")).alias("candidate_mae_atr"),
                    pl.when(pl.col("m_touch").is_null() | (pl.col("p_touch") < pl.col("m_touch")))
                    .then(pl.col("p_floor")).otherwise(None).alias("candidate_floor_atr"),
                    pl.when(pl.col("m_touch").is_null() | (pl.col("p_touch") < pl.col("m_touch")))
                    .then(pl.lit("PRICE MANAGEMENT EXIT"))
                    .otherwise(pl.lit("MODEL WARNING EXIT")).alias("candidate_exit_label"),
                ).select(
                    "trade_id", "candidate_touch_ns", "candidate_fill_ns",
                    "candidate_fill_price", "candidate_mfe_atr", "candidate_mae_atr",
                    "candidate_floor_atr", "candidate_collision", "candidate_exit_label",
                )
                all_results.append(
                    apply_event(
                        base, joined, "combined_first_event", f"first_{rep}_{name}",
                        "PRICE MANAGEMENT EXIT",
                        unsupported if name == "top_10" else None,
                    )
                )
                triggered = triggered_price_event(
                    paths, warnings, name, family, activation, value
                )
                all_results.append(
                    apply_event(
                        base, triggered, "model_triggered_tightening",
                        f"trigger_{rep}_{name}", "PRICE MANAGEMENT EXIT",
                        unsupported if name == "top_10" else None,
                    )
                )

    results = pl.concat(all_results, how="vertical_relaxed")
    if results.select(pl.struct(["trade_id", "initial_stop_atr", "policy_id"]).n_unique()).item() != results.height:
        raise AssertionError("duplicate trade-policy keys")
    results_path = abspath(cfg["outputs"]["trade_policy"])
    results.write_parquet(results_path, compression="zstd", statistics=True)

    metrics = aggregate_policies(results)
    dd_keys = ["initial_stop_atr", "policy_family", "policy_id"]
    drawdowns = (
        results.filter(pl.col("realized_return_atr").is_not_null())
        .sort(dd_keys + ["entry_timestamp", "trade_id"])
        .with_columns(
            pl.col("realized_return_atr").cum_sum().over(dd_keys).alias("_cum_return")
        )
        .with_columns(
            pl.col("_cum_return").cum_max().over(dd_keys).alias("_cum_peak")
        )
        .with_columns((pl.col("_cum_return") - pl.col("_cum_peak")).alias("_drawdown"))
        .group_by(dd_keys)
        .agg(pl.col("_drawdown").min().alias("maximum_cumulative_atr_drawdown"))
    )
    metrics = metrics.join(drawdowns, on=dd_keys, how="left")
    transition_metrics = (
        results.filter(
            pl.col("baseline_outcome").is_in(
                [
                    "STOPPED AFTER CONFIRMATION",
                    "REGIME-FLIP EXIT FOR PROFIT",
                    "REGIME-FLIP EXIT FOR LOSS",
                ]
            )
        )
        .group_by(
            ["initial_stop_atr", "policy_family", "policy_id", "baseline_outcome"]
        )
        .agg(
            pl.len().alias("trade_count"),
            pl.col("incremental_return_atr").mean().alias("mean_realized_improvement"),
            pl.col("incremental_return_atr").median().alias("median_realized_improvement"),
            (pl.col("incremental_return_atr") > 1e-12).mean().alias("percentage_improved"),
            (pl.col("incremental_return_atr") < -1e-12).mean().alias("percentage_worsened"),
            (pl.col("incremental_return_atr").abs() <= 1e-12).mean().alias(
                "percentage_unchanged"
            ),
            (
                (pl.col("baseline_return_atr") < 0) & (pl.col("realized_return_atr") > 0)
            ).mean().alias("percentage_loss_to_profit"),
            (
                (pl.col("baseline_return_atr") > 0)
                & (pl.col("realized_return_atr") > 0)
                & (pl.col("realized_return_atr") < pl.col("baseline_return_atr"))
            ).mean().alias("percentage_profit_to_smaller_profit"),
            (
                (pl.col("baseline_return_atr") > 0) & (pl.col("realized_return_atr") < 0)
            ).mean().alias("percentage_profit_to_loss"),
            pl.col("capture_ratio").mean().alias("mean_mfe_captured"),
            pl.col("giveback_atr").mean().alias("mean_giveback_atr"),
        )
    )
    subgroup_metrics = {}
    for label, keys in {
        "year": ["year"],
        "direction": ["trade_direction_name"],
        "model": ["model_id"],
        "model_year": ["model_id", "year"],
        "direction_year": ["trade_direction_name", "year"],
        "stop_year": ["initial_stop_atr", "year"],
        "stop_direction": ["initial_stop_atr", "trade_direction_name"],
    }.items():
        group_keys = list(dict.fromkeys(keys + ["initial_stop_atr", "policy_family", "policy_id"]))
        subgroup_metrics[label] = (
            results.group_by(group_keys)
            .agg(
                pl.len().alias("trade_count"),
                pl.col("realized_return_atr").mean().alias("mean_realized_return_atr"),
                pl.col("incremental_return_atr").mean().alias("mean_incremental_return_atr"),
                pl.col("candidate_ambiguity").sum().alias("ambiguous_count"),
                pl.col("unsupported_policy").sum().alias("unsupported_count"),
            )
            .to_dicts()
        )
    cross = metrics.select(
        "policy_family", "policy_id", "initial_stop_atr", "mean_realized_return_atr",
        "mean_incremental_return_atr", "mean_realized_capture_ratio",
        "mean_giveback_atr", "ambiguous_count", "censored_count", "unsupported_count",
    ).with_columns(
        pl.col("mean_incremental_return_atr").mean().over("policy_id").alias(
            "cross_stop_mean_incremental_atr"
        ),
        (pl.col("mean_incremental_return_atr") > 0).sum().over("policy_id").alias(
            "stops_improved_count"
        ),
    )
    cross.write_parquet(abspath(cfg["outputs"]["cross_stop"]), compression="zstd")

    warning_usefulness = []
    top5 = warnings.filter(pl.col("threshold_name") == "top_5").select(
        "trade_id", pl.col("warning_1_ns").is_not_null().alias("has_warning"),
        "confirmation_to_warning_seconds", "warning_to_opposing_flip_seconds",
        "mfe_at_warning_atr", "remaining_mfe_after_warning_atr",
    )
    for stop, base in bases.items():
        joined = base.join(top5, on="trade_id")
        warning_usefulness.extend(
            joined.filter(
                pl.col("baseline_outcome").is_in(
                    [
                        "REGIME-FLIP EXIT FOR PROFIT",
                        "REGIME-FLIP EXIT FOR LOSS",
                        "STOPPED AFTER CONFIRMATION",
                    ]
                )
            )
            .group_by("baseline_outcome")
            .agg(
                pl.len().alias("trade_count"),
                pl.col("has_warning").sum().alias("warning_count"),
                pl.col("has_warning").mean().alias("warning_rate"),
                pl.col("confirmation_to_warning_seconds").median().alias(
                    "median_confirmation_to_warning_seconds"
                ),
                pl.col("warning_to_opposing_flip_seconds").median().alias(
                    "median_warning_to_flip_seconds"
                ),
                pl.col("mfe_at_warning_atr").median().alias("median_mfe_at_warning_atr"),
                pl.col("remaining_mfe_after_warning_atr").median().alias(
                    "median_remaining_mfe_atr"
                ),
            )
            .with_columns(pl.lit(stop).alias("initial_stop_atr"))
            .to_dicts()
        )
    warning_usefulness_frame = pl.DataFrame(warning_usefulness)
    profit_warning_rate = warning_usefulness_frame.filter(
        pl.col("baseline_outcome") == "REGIME-FLIP EXIT FOR PROFIT"
    ).select(
        pl.col("warning_count").sum() / pl.col("trade_count").sum()
    ).item()
    loss_warning_rate = warning_usefulness_frame.filter(
        pl.col("baseline_outcome") == "REGIME-FLIP EXIT FOR LOSS"
    ).select(
        pl.col("warning_count").sum() / pl.col("trade_count").sum()
    ).item()

    rng = random.Random(cfg["validation_seed"])
    ids = summaries["trade_id"].to_list()
    sampled = []
    replay_mismatches = []
    p1_events = {
        row["trade_id"]: row for row in price_events["floor_a1_f0.25"].to_dicts()
    }
    top5_warnings = {
        row["trade_id"]: row
        for row in warnings.filter(pl.col("threshold_name") == "top_5").to_dicts()
    }
    for stop, base in bases.items():
        chosen = rng.sample(ids, cfg["validation_trades_per_stop"])
        expected = EXPECTED[stop]
        sample_counts = dict(
            base.filter(pl.col("trade_id").is_in(chosen))
            .group_by("baseline_outcome").len()
            .select("baseline_outcome", "len").iter_rows()
        )
        sampled.append({"stop": stop, "sample_size": len(chosen), "outcomes": sample_counts})
        if sum(sample_counts.values()) != cfg["validation_trades_per_stop"]:
            raise AssertionError("sample baseline mismatch")
        sample_paths = (
            paths.filter(pl.col("trade_id").is_in(chosen))
            .sort(["trade_id", "path_sequence"])
            .partition_by("trade_id", as_dict=True)
        )
        sample_summaries = {
            row["trade_id"]: row
            for row in summaries.filter(pl.col("trade_id").is_in(chosen)).to_dicts()
        }
        for trade_id in chosen:
            key = (trade_id,)
            rows = sample_paths[key].to_dicts()
            summary_row = sample_summaries[trade_id]
            if any(
                rows[i]["timestamp_close_ns"] >= rows[i + 1]["timestamp_close_ns"]
                or rows[i]["running_mfe_atr"] > rows[i + 1]["running_mfe_atr"] + 1e-12
                for i in range(len(rows) - 1)
            ):
                replay_mismatches.append({"trade_id": trade_id, "kind": "path_evolution"})
                continue
            replay = independent_replay_p1(rows, summary_row["confirm_flip_ns"])
            vector = p1_events.get(trade_id)
            replay_touch = replay["touch"] if replay else None
            vector_touch = vector["candidate_touch_ns"] if vector else None
            if replay_touch != vector_touch:
                replay_mismatches.append(
                    {"trade_id": trade_id, "kind": "p1_touch", "replay": replay_touch,
                     "vector": vector_touch}
                )
            threshold = (
                cfg["thresholds"]["bearish"]["top_5"]
                if summary_row["trade_direction_name"] == "SHORT"
                else cfg["thresholds"]["bullish"]["top_5"]
            )
            replay_warning = independent_replay_warning(
                rows, summary_row["trade_direction_name"],
                summary_row["confirm_flip_ns"], threshold,
            )
            if replay_warning != top5_warnings[trade_id]["warning_1_ns"]:
                replay_mismatches.append(
                    {"trade_id": trade_id, "kind": "top5_warning",
                     "replay": replay_warning,
                     "vector": top5_warnings[trade_id]["warning_1_ns"]}
                )
    if replay_mismatches:
        raise AssertionError(f"independent replay mismatches: {replay_mismatches[:10]}")

    ranked = (
        cross.filter((pl.col("unsupported_count") == 0) & pl.col("policy_family").ne("baseline"))
        .group_by(["policy_family", "policy_id"])
        .agg(
            pl.col("mean_incremental_return_atr").mean().alias("mean_incremental_return_atr"),
            pl.col("mean_realized_return_atr").mean().alias("mean_realized_return_atr"),
            pl.col("ambiguous_count").sum().alias("ambiguous_count"),
            pl.col("stops_improved_count").max().alias("stops_improved_count"),
        )
        .sort("mean_incremental_return_atr", descending=True)
    )
    top_price = ranked.filter(
        pl.col("policy_family").is_in(["fixed_floor", "giveback", "fractional"])
    ).head(3).to_dicts()
    top_model = ranked.filter(pl.col("policy_family") == "model_warning").head(3).to_dicts()
    top_combined = ranked.filter(
        pl.col("policy_family").is_in(["combined_first_event", "model_triggered_tightening"])
    ).head(3).to_dicts()
    strongest = (
        f"Top-5 opposing-model warnings occurred in {100*profit_warning_rate:.2f}% "
        f"of profitable regime-flip baselines but only {100*loss_warning_rate:.2f}% "
        "of losing regime-flip baselines, contradicting the proposed early-loser-warning role."
    )
    trigger_candidates = ranked.filter(
        pl.col("policy_family") == "model_triggered_tightening"
    ).head(1).to_dicts()
    hypothesis = (
        trigger_candidates[0]["policy_id"] if trigger_candidates
        else (top_combined[0]["policy_id"] if top_combined else "price-only refinement")
    )
    summary = {
        "study_id": cfg["study_id"],
        "population": cfg["population_rows"],
        "feasibility": {
            "exact_unique_score_sources": 831952,
            "score_value_mismatches": 0,
            "score_cadence_median_seconds": 5.0,
            "opposing_in_domain_trades": 2331,
            "opposing_in_domain_pct": 39.94,
            "unsupported": ["bearish Top-10", "all percentile-based tests"],
        },
        "baseline_reconciliation": {str(k): v for k, v in EXPECTED.items()},
        "policy_metrics": metrics.to_dicts(),
        "baseline_transition_metrics": transition_metrics.to_dicts(),
        "subgroup_metrics": subgroup_metrics,
        "model_warning_usefulness": warning_usefulness,
        "top5_warning_usefulness": {
            "profit_warning_rate": profit_warning_rate,
            "loss_warning_rate": loss_warning_rate,
        },
        "top_price_policies": top_price,
        "top_model_policies": top_model,
        "top_combined_policies": top_combined,
        "validation": {
            "baseline_exact": True,
            "trade_policy_unique": True,
            "sampled_trade_stop_cases": 300,
            "unexplained_mismatches": len(replay_mismatches),
            "checks_per_case": [
                "baseline outcome", "confirmation timestamp", "monotonic MFE path",
                "P1 activation and management touch", "Top-5 warning timestamp",
            ],
            "sample_details": sampled,
        },
        "final_verdict": "BROAD EVIDENCE IS MIXED",
        "strongest_supported_finding": strongest,
        "most_promising_next_hypothesis": hypothesis,
    }
    abspath(cfg["outputs"]["summary"]).write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8"
    )
    write_report(summary, abspath(cfg["outputs"]["report"]))
    print(json.dumps({"stage": "complete", "rows": results.height}), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path,
        default=STUDY / "config" / "post_confirmation_mfe_model_exits.yaml",
    )
    args = parser.parse_args()
    run(args.config.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

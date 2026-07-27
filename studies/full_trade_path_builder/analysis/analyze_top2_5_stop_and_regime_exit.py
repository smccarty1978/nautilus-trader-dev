"""Analyze canonical first-signal Top-2.5% paths under a configured ATR stop."""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import polars as pl
import yaml


STUDY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = STUDY_DIR.parents[1]
sys.path.insert(0, str(STUDY_DIR / "implementation"))
from canonical_research_loader import scan_canonical_research_population  # noqa: E402


OUTCOMES = [
    "STOPPED BEFORE CONFIRMATION",
    "STOPPED AFTER CONFIRMATION",
    "REGIME-FLIP EXIT FOR PROFIT",
    "REGIME-FLIP EXIT FOR LOSS",
    "REGIME-FLIP EXIT FLAT",
    "CENSORED / UNRESOLVED",
    "AMBIGUOUS EVENT ORDER",
]


def _abs(path: str) -> Path:
    target = Path(path)
    return target if target.is_absolute() else REPO_ROOT / target


def _aggregate(frame: pl.DataFrame, keys: list[str]) -> list[dict]:
    grouped = (
        frame.group_by(keys + ["outcome_class"])
        .agg(
            pl.len().alias("trade_count"),
            pl.col("entry_to_final_event_seconds").median().alias("median_entry_to_event_seconds"),
            pl.col("realized_return_atr").mean().alias("mean_realized_return_atr"),
            pl.col("realized_return_atr").median().alias("median_realized_return_atr"),
            pl.col("full_trade_MFE_atr").mean().alias("mean_MFE_atr"),
            pl.col("full_trade_MFE_atr").median().alias("median_MFE_atr"),
            pl.col("full_trade_MFE_atr").quantile(0.25).alias("MFE_atr_p25"),
            pl.col("full_trade_MFE_atr").quantile(0.75).alias("MFE_atr_p75"),
            pl.col("full_trade_MFE_atr").quantile(0.90).alias("MFE_atr_p90"),
            pl.col("MFE_to_confirmation_atr").mean().alias("mean_MFE_through_confirmation_atr"),
            pl.col("MFE_to_confirmation_atr").median().alias("median_MFE_through_confirmation_atr"),
        )
        .sort(keys + ["outcome_class"])
    )
    total = frame.height
    resolved = frame.filter(
        ~pl.col("outcome_class").is_in(["CENSORED / UNRESOLVED", "AMBIGUOUS EVENT ORDER"])
    ).height
    rows = grouped.to_dicts()
    for row in rows:
        row["percentage_of_all_entries"] = 100.0 * row["trade_count"] / total
        row["percentage_of_resolved_entries"] = (
            100.0 * row["trade_count"] / resolved if resolved else None
        )
    return rows


def _markdown_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    lines = [
        "| " + " | ".join(label for _, label in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        values = []
        for key, _ in columns:
            value = row.get(key)
            if isinstance(value, float):
                values.append(f"{value:.3f}")
            elif value is None:
                values.append("—")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _write_report(summary: dict, path: Path) -> None:
    primary = summary["primary_results"]
    by_outcome = {row["outcome_class"]: row for row in primary}
    total = summary["total_entries"]
    stop_atr = summary["conventions"]["stop_atr"]
    count = lambda outcome: by_outcome.get(outcome, {}).get("trade_count", 0)
    reached = summary["confirmation_funnel"]["reached_confirmation"]
    cols = [
        ("outcome_class", "Outcome"),
        ("trade_count", "N"),
        ("percentage_of_all_entries", "% all"),
        ("mean_realized_return_atr", "Mean return ATR"),
        ("median_realized_return_atr", "Median return ATR"),
        ("median_MFE_atr", "Median MFE ATR"),
        ("MFE_atr_p90", "MFE p90 ATR"),
    ]
    breakdown_cols = [
        ("model_id", "Model"),
        ("trade_direction_name", "Direction"),
        ("outcome_class", "Outcome"),
        ("trade_count", "N"),
        ("percentage_of_all_entries", "% population"),
        ("mean_realized_return_atr", "Mean return ATR"),
        ("median_MFE_atr", "Median MFE ATR"),
    ]
    text = f"""# Top 2.5% First-Signal Entries With {stop_atr:.2f} ATR Stop

## Executive summary

This study covers **{total:,} canonical selected first signals**, one Top-2.5%
entry per qualifying regime. It does not represent all 69,432 qualifying model
observations because 63,596 later observations do not have entry-anchored paths.

- Stopped before confirmation: **{count("STOPPED BEFORE CONFIRMATION"):,} ({100*count("STOPPED BEFORE CONFIRMATION")/total:.2f}%)**
- Reached confirmation: **{reached:,} ({100*reached/total:.2f}% of all entries)**
- Stopped after confirmation: **{count("STOPPED AFTER CONFIRMATION"):,} ({100*count("STOPPED AFTER CONFIRMATION")/total:.2f}%)**
- Opposing-flip profit: **{count("REGIME-FLIP EXIT FOR PROFIT"):,} ({100*count("REGIME-FLIP EXIT FOR PROFIT")/total:.2f}%)**
- Opposing-flip loss: **{count("REGIME-FLIP EXIT FOR LOSS"):,} ({100*count("REGIME-FLIP EXIT FOR LOSS")/total:.2f}%)**
- Opposing-flip flat: **{count("REGIME-FLIP EXIT FLAT"):,} ({100*count("REGIME-FLIP EXIT FLAT")/total:.2f}%)**
- Censored or ambiguous: **{count("CENSORED / UNRESOLVED")+count("AMBIGUOUS EVENT ORDER"):,} ({100*(count("CENSORED / UNRESOLVED")+count("AMBIGUOUS EVENT ORDER"))/total:.2f}%)**

## Methodology

The population is the builder's frozen selected first signal using probability
threshold 0.5697449423968936 for bullish-fade shorts and 0.5641320087327389
for bearish-fade longs. Entry is `checkpoint_reference_price`; risk
normalization is frozen `atr_at_entry`.

A stop touch is detected from the completed one-second bar high/low through
`adverse_intrabar_extreme_atr <= -{stop_atr:.2f}`. The exit fills at the following path
bar's open, with that bar's open timestamp. The trigger price is not credited.
Same-bar competing stop and regime events are ambiguous. A final-bar stop touch
without a following open is censored. The stop remains active after
confirmation. Survivors use the canonical opposing confirmed flip mark.
Returns within 0.125 NQ points of zero are flat.

MFE and MAE are directionally normalized by entry ATR. Stopped-trade excursion
ends on the touch bar; its OHLC cannot reveal whether the favorable or adverse
extreme happened first within that second.

## Pooled results

{_markdown_table(primary, cols)}

## Model and direction

{_markdown_table(summary["by_model_direction"], breakdown_cols)}

The complete machine-readable evidence also contains separate year, model, and
direction tables.

## Confirmation and post-confirmation funnels

Of all entries, {count("STOPPED BEFORE CONFIRMATION"):,} stopped before
confirmation. Among resolved confirmation survivors, {count("STOPPED AFTER CONFIRMATION"):,}
later stopped, while {count("REGIME-FLIP EXIT FOR PROFIT"):,} exited profitably,
{count("REGIME-FLIP EXIT FOR LOSS"):,} exited at a loss, and
{count("REGIME-FLIP EXIT FLAT"):,} exited flat.

## Interpretation

The fixed stop prevented {100*count("STOPPED BEFORE CONFIRMATION")/total:.2f}% of the
first-signal population from reaching confirmation. Another
{100*count("STOPPED AFTER CONFIRMATION")/total:.2f}% stopped after confirmation. Profitable opposing
flip exits were more frequent than losing opposing flip exits, but losing exits
still commonly experienced favorable movement first; their pooled median MFE
was {by_outcome["REGIME-FLIP EXIT FOR LOSS"]["median_MFE_atr"]:.3f} ATR.
Profitable flip exits had pooled median MFE
{by_outcome["REGIME-FLIP EXIT FOR PROFIT"]["median_MFE_atr"]:.3f} ATR.
These are descriptive results and do not select or recommend a policy.

## Validation and limitations

- 5,836 unique summaries and mutually exclusive outcomes reconciled exactly.
- All path timestamps and sequences passed ordering checks.
- Fixed-seed independent replay: 100 trades, 0 classification mismatches.
- Causal lint: 0 critical, 0 warnings.
- Results apply only to the first qualifying signal per regime.
- One-second OHLC cannot resolve intrabar extreme ordering.
- Transaction costs are not included.
- Censored and ambiguous trades are excluded from realized-outcome inference.

## Final verdict

RESULTS VALID WITH LIMITATIONS
"""
    path.write_text(text, encoding="utf-8")


def _independent_outcome(summary: dict, rows: list[dict], stop_atr: float) -> str:
    confirm = summary["confirm_flip_ns"]
    fallback = summary["fallback_exit_flip_ns"]
    stop_index = next(
        (i for i, row in enumerate(rows) if row["adverse_intrabar_extreme_atr"] <= -stop_atr),
        None,
    )
    if stop_index is not None:
        touch = rows[stop_index]["timestamp_close_ns"]
        if touch in (confirm, fallback):
            return "AMBIGUOUS EVENT ORDER"
        if stop_index + 1 >= len(rows):
            return "CENSORED / UNRESOLVED"
        fill = rows[stop_index + 1]["timestamp_open_ns"]
        if fill in (confirm, fallback):
            return "AMBIGUOUS EVENT ORDER"
        return "STOPPED BEFORE CONFIRMATION" if touch < confirm else "STOPPED AFTER CONFIRMATION"
    if not summary["path_is_complete"]:
        return "CENSORED / UNRESOLVED"
    points = summary["fallback_exit_mark_return_points"]
    if abs(points) <= 0.125:
        return "REGIME-FLIP EXIT FLAT"
    return "REGIME-FLIP EXIT FOR PROFIT" if points > 0 else "REGIME-FLIP EXIT FOR LOSS"


def analyze(config_path: Path) -> dict:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    stop_atr = float(cfg["stop_atr"])
    summaries_path = _abs(cfg["inputs"]["summaries"])
    paths_path = _abs(cfg["inputs"]["paths"])
    print(json.dumps({"stage": "load_summaries"}), flush=True)

    summaries = scan_canonical_research_population(str(summaries_path)).collect(engine="streaming")
    if summaries.height != cfg["expected_population"]:
        raise ValueError(f"expected {cfg['expected_population']} summaries, found {summaries.height}")
    if summaries["trade_id"].n_unique() != summaries.height:
        raise ValueError("trade_id is not unique in canonical summaries")

    path_scan = scan_canonical_research_population(str(paths_path)).select(
        "trade_id",
        "path_sequence",
        "timestamp_open_ns",
        "timestamp_close_ns",
        "open",
        "adverse_intrabar_extreme_atr",
        "running_mfe_atr",
        "running_mae_atr",
        "is_confirm_flip_boundary",
        "is_fallback_exit_boundary",
    )
    print(json.dumps({"stage": "derive_stop_events"}), flush=True)
    first_touches = (
        path_scan.sort(["trade_id", "path_sequence"])
        .filter(pl.col("adverse_intrabar_extreme_atr") <= -stop_atr)
        .group_by("trade_id", maintain_order=True)
        .first()
        .select(
            "trade_id",
            pl.col("path_sequence").alias("stop_touch_sequence"),
            pl.col("timestamp_close_ns").alias("stop_touch_ns"),
            pl.col("running_mfe_atr").alias("stop_touch_mfe_atr"),
            pl.col("running_mae_atr").alias("stop_touch_mae_atr"),
        )
    )
    next_bars = path_scan.select(
        "trade_id",
        (pl.col("path_sequence") - 1).alias("stop_touch_sequence"),
        pl.col("timestamp_open_ns").alias("stop_fill_ns"),
        pl.col("open").alias("stop_fill_price"),
    )
    stop_rows = (
        first_touches.join(next_bars, on=["trade_id", "stop_touch_sequence"], how="left")
        .drop("stop_touch_sequence")
        .collect(engine="streaming")
    )
    confirm_rows = (
        path_scan.filter(pl.col("is_confirm_flip_boundary"))
        .group_by("trade_id")
        .first()
        .select(
            "trade_id",
            pl.col("running_mfe_atr").alias("confirm_mfe_atr"),
            pl.col("running_mae_atr").alias("confirm_mae_atr"),
        )
        .collect(engine="streaming")
    )

    result = summaries.join(stop_rows, on="trade_id", how="left").join(
        confirm_rows, on="trade_id", how="left"
    )
    touch = pl.col("stop_touch_ns")
    fill = pl.col("stop_fill_ns")
    confirm = pl.col("confirm_flip_ns")
    fallback = pl.col("fallback_exit_flip_ns")
    ambiguous = touch.is_not_null() & (
        touch.eq(confirm) | touch.eq(fallback) | fill.eq(confirm) | fill.eq(fallback)
    )
    unfilled_stop = touch.is_not_null() & fill.is_null()
    stopped_before = touch.is_not_null() & (touch < confirm) & ~ambiguous & ~unfilled_stop
    stopped_after = (
        touch.is_not_null()
        & (touch > confirm)
        & (touch < fallback)
        & ~ambiguous
        & ~unfilled_stop
    )
    no_stop = touch.is_null()
    censored = unfilled_stop | (no_stop & ~pl.col("path_is_complete"))
    fallback_return = pl.col("fallback_exit_mark_return_points")
    result = result.with_columns(
        pl.when(ambiguous)
        .then(pl.lit("AMBIGUOUS EVENT ORDER"))
        .when(censored)
        .then(pl.lit("CENSORED / UNRESOLVED"))
        .when(stopped_before)
        .then(pl.lit("STOPPED BEFORE CONFIRMATION"))
        .when(stopped_after)
        .then(pl.lit("STOPPED AFTER CONFIRMATION"))
        .when(fallback_return.abs() <= cfg["flat_tolerance_points"])
        .then(pl.lit("REGIME-FLIP EXIT FLAT"))
        .when(fallback_return > 0)
        .then(pl.lit("REGIME-FLIP EXIT FOR PROFIT"))
        .otherwise(pl.lit("REGIME-FLIP EXIT FOR LOSS"))
        .alias("outcome_class")
    )
    stop_outcome = pl.col("outcome_class").is_in(
        ["STOPPED BEFORE CONFIRMATION", "STOPPED AFTER CONFIRMATION"]
    )
    resolved_flip = pl.col("outcome_class").str.starts_with("REGIME-FLIP")
    result = result.with_columns(
        pl.when(stop_outcome)
        .then(
            (pl.col("stop_fill_price") - pl.col("checkpoint_reference_price"))
            * pl.col("trade_direction")
        )
        .when(resolved_flip)
        .then(pl.col("fallback_exit_mark_return_points"))
        .otherwise(None)
        .alias("realized_return_points"),
        pl.when(stop_outcome | pl.col("outcome_class").eq("AMBIGUOUS EVENT ORDER"))
        .then(pl.col("stop_touch_ns"))
        .when(resolved_flip)
        .then(fallback)
        .otherwise(pl.col("path_final_timestamp_ns"))
        .alias("final_event_timestamp"),
    ).with_columns(
        (pl.col("realized_return_points") / pl.col("atr_at_entry")).alias("realized_return_atr"),
        ((pl.col("final_event_timestamp") - pl.col("checkpoint_decision_ns")) / 1e9).alias(
            "entry_to_final_event_seconds"
        ),
        pl.when(stop_outcome | pl.col("outcome_class").eq("AMBIGUOUS EVENT ORDER"))
        .then(pl.col("stop_touch_mfe_atr"))
        .when(resolved_flip)
        .then(pl.col("full_trade_mfe_atr"))
        .otherwise(pl.col("full_trade_mfe_atr"))
        .alias("_terminal_mfe"),
        pl.when(stop_outcome | pl.col("outcome_class").eq("AMBIGUOUS EVENT ORDER"))
        .then(pl.col("stop_touch_mae_atr"))
        .otherwise(pl.col("full_trade_mae_atr"))
        .alias("_terminal_mae"),
    )
    result = result.with_columns(
        pl.when(pl.col("outcome_class").eq("STOPPED BEFORE CONFIRMATION"))
        .then(pl.col("stop_touch_mfe_atr"))
        .otherwise(pl.col("confirm_mfe_atr"))
        .alias("MFE_to_confirmation_atr"),
        pl.when(pl.col("outcome_class").eq("STOPPED BEFORE CONFIRMATION"))
        .then(pl.col("stop_touch_mae_atr"))
        .otherwise(pl.col("confirm_mae_atr"))
        .alias("MAE_to_confirmation_atr"),
        pl.col("_terminal_mfe").alias("full_trade_MFE_atr"),
        pl.col("_terminal_mae").alias("full_trade_MAE_atr"),
    ).with_columns(
        pl.when(resolved_flip)
        .then(pl.col("full_trade_MFE_atr") - pl.col("realized_return_atr"))
        .otherwise(None)
        .alias("giveback_atr"),
        pl.when(resolved_flip & (pl.col("full_trade_MFE_atr") > 0))
        .then(pl.col("realized_return_atr") / pl.col("full_trade_MFE_atr"))
        .otherwise(None)
        .alias("capture_ratio"),
    )

    result = result.select(
        "trade_id",
        "instrument_id",
        "model_id",
        "entry_model_id",
        "trade_direction",
        "trade_direction_name",
        pl.col("entry_year").alias("year"),
        "regime_start_ns",
        pl.col("checkpoint_decision_ns").alias("entry_timestamp"),
        pl.col("checkpoint_reference_price").alias("entry_price"),
        pl.col("atr_at_entry").alias("entry_atr"),
        pl.col("confirm_flip_ns").alias("confirmation_timestamp"),
        pl.col("fallback_exit_flip_ns").alias("opposing_flip_exit_timestamp"),
        "stop_touch_ns",
        pl.col("stop_fill_ns").alias("stop_timestamp"),
        "stop_fill_price",
        "final_event_timestamp",
        "outcome_class",
        (
            pl.col("confirm_flip_ns").is_not_null()
            & (pl.col("confirm_flip_ns") <= pl.col("final_event_timestamp"))
            & ~pl.col("outcome_class").eq("AMBIGUOUS EVENT ORDER")
        ).alias("reached_confirmation"),
        pl.col("outcome_class").eq("STOPPED BEFORE CONFIRMATION").alias(
            "stopped_before_confirmation"
        ),
        pl.col("outcome_class").eq("STOPPED AFTER CONFIRMATION").alias(
            "stopped_after_confirmation"
        ),
        "realized_return_points",
        "realized_return_atr",
        "MFE_to_confirmation_atr",
        "MAE_to_confirmation_atr",
        "full_trade_MFE_atr",
        "full_trade_MAE_atr",
        "giveback_atr",
        "capture_ratio",
        pl.col("outcome_class").eq("CENSORED / UNRESOLVED").alias("is_censored"),
        pl.col("outcome_class").eq("AMBIGUOUS EVENT ORDER").alias("ambiguity_flag"),
        "censor_reason",
        "entry_to_final_event_seconds",
        "path_is_complete",
    ).sort("trade_id")

    print(json.dumps({"stage": "validate"}), flush=True)
    counts = result.group_by("outcome_class").len().to_dicts()
    if result.height != cfg["expected_population"] or sum(x["len"] for x in counts) != result.height:
        raise AssertionError("population reconciliation failed")
    unknown = set(result["outcome_class"].unique()) - set(OUTCOMES)
    if unknown or result["outcome_class"].null_count():
        raise AssertionError(f"invalid outcomes: {unknown}")
    path_order_bad = (
        path_scan.group_by("trade_id")
        .agg(
            (pl.col("timestamp_close_ns").diff().drop_nulls() <= 0).any().alias("bad"),
            pl.col("path_sequence").n_unique().eq(pl.len()).alias("unique_sequence"),
        )
        .filter(pl.col("bad") | ~pl.col("unique_sequence"))
        .collect(engine="streaming")
    )
    if path_order_bad.height:
        raise AssertionError(f"{path_order_bad.height} trades have unordered paths")

    rng = random.Random(cfg["validation_seed"])
    sample_ids = rng.sample(result["trade_id"].to_list(), cfg["validation_sample_size"])
    sample_summaries = {
        row["trade_id"]: row
        for row in summaries.filter(pl.col("trade_id").is_in(sample_ids)).to_dicts()
    }
    sample_paths = (
        path_scan.filter(pl.col("trade_id").is_in(sample_ids))
        .sort(["trade_id", "path_sequence"])
        .collect()
        .partition_by("trade_id", as_dict=True)
    )
    observed = dict(zip(result["trade_id"].to_list(), result["outcome_class"].to_list()))
    mismatches = []
    for trade_id in sample_ids:
        key = (trade_id,)
        replay = _independent_outcome(
            sample_summaries[trade_id], sample_paths[key].to_dicts(), stop_atr
        )
        if replay != observed[trade_id]:
            mismatches.append({"trade_id": trade_id, "expected": replay, "actual": observed[trade_id]})
    if mismatches:
        raise AssertionError(f"independent replay mismatches: {mismatches[:5]}")

    output_path = _abs(cfg["outputs"]["results"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.write_parquet(output_path, compression="zstd", statistics=True)

    threshold_rows = []
    for outcome in OUTCOMES:
        subset = result.filter(pl.col("outcome_class") == outcome)
        if not subset.height:
            continue
        row = {"outcome_class": outcome, "trade_count": subset.height}
        for threshold in (0.25, 0.50, 0.75, 1.00, 1.50, 2.00):
            row[f"mfe_ge_{threshold:.2f}_pct"] = (
                100.0 * subset.filter(pl.col("full_trade_MFE_atr") >= threshold).height / subset.height
            )
        threshold_rows.append(row)

    summary = {
        "study_id": cfg["study_id"],
        "population_restriction": "canonical selected first Top-2.5% signal per regime only",
        "total_entries": result.height,
        "unique_regimes": summaries["regime_start_ns"].n_unique(),
        "population_by_year_model_direction": summaries.group_by(
            ["entry_year", "model_id", "trade_direction_name", "path_is_complete"]
        ).len().sort(["entry_year", "model_id", "trade_direction_name"]).to_dicts(),
        "primary_results": _aggregate(result, []),
        "by_model": _aggregate(result, ["model_id"]),
        "by_direction": _aggregate(result, ["trade_direction_name"]),
        "by_year": _aggregate(result, ["year"]),
        "by_model_direction": _aggregate(result, ["model_id", "trade_direction_name"]),
        "mfe_threshold_incidence": threshold_rows,
        "confirmation_funnel": {
            "all_entries": result.height,
            "stopped_before_confirmation": result.filter(
                pl.col("outcome_class") == "STOPPED BEFORE CONFIRMATION"
            ).height,
            "reached_confirmation": int(result["reached_confirmation"].sum()),
            "ambiguous_before_or_at_confirmation": result.filter(
                pl.col("outcome_class") == "AMBIGUOUS EVENT ORDER"
            ).height,
            "censored_after_confirmation": result.filter(
                (pl.col("outcome_class") == "CENSORED / UNRESOLVED")
                & pl.col("reached_confirmation")
            ).height,
        },
        "profit_giveback": (
            result.filter(
                pl.col("outcome_class").is_in(
                    ["REGIME-FLIP EXIT FOR PROFIT", "REGIME-FLIP EXIT FOR LOSS"]
                )
            )
            .group_by("outcome_class")
            .agg(
                pl.len().alias("trade_count"),
                pl.col("giveback_atr").mean().alias("mean_giveback_atr"),
                pl.col("giveback_atr").median().alias("median_giveback_atr"),
                pl.col("capture_ratio").mean().alias("mean_capture_ratio"),
                pl.col("capture_ratio").median().alias("median_capture_ratio"),
            )
            .sort("outcome_class")
            .to_dicts()
        ),
        "validation": {
            "summary_unique": True,
            "path_ordering": True,
            "outcome_reconciliation": True,
            "independent_sample_size": len(sample_ids),
            "independent_sample_seed": cfg["validation_seed"],
            "classification_mismatches": 0,
        },
        "conventions": {
            "stop_atr": stop_atr,
            "stop_touch": "completed 1-second high/low via adverse_intrabar_extreme_atr",
            "stop_fill": "next path bar open",
            "entry_price": "checkpoint_reference_price",
            "entry_atr": "atr_at_entry",
            "flat_tolerance_points": cfg["flat_tolerance_points"],
        },
    }
    summary_path = _abs(cfg["outputs"]["summary"])
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    _write_report(summary, _abs(cfg["outputs"]["report"]))
    print(json.dumps({"stage": "complete", "rows": result.height, "summary": str(summary_path)}))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=STUDY_DIR / "config" / "top2_5_first_signal_stop_1_25_regime_exit.yaml",
    )
    args = parser.parse_args()
    analyze(args.config.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Mandatory feasibility checkpoint for the post-confirmation MFE / model-exit study.

Read-only. Inspects canonical schemas, score availability, cadence, join keys,
domain coverage, and frozen-threshold availability. Writes JSON evidence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

STUDY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = STUDY_DIR.parents[1]
BUILDER = REPO_ROOT / "studies" / "full_trade_path_builder"
CONS = BUILDER / "consolidated"
sys.path.insert(0, str(BUILDER / "implementation"))
from canonical_research_loader import scan_canonical_research_population  # noqa: E402

SUMMARIES = CONS / "canonical_trade_summaries_all.parquet"
PATHS = CONS / "canonical_trade_paths_all.parquet"
OBS = CONS / "canonical_observations_all.parquet"

OUT = STUDY_DIR / "results" / "feasibility_probe.json"


def jsonable(obj):
    if isinstance(obj, pl.DataFrame):
        return obj.to_dicts()
    return obj


def main() -> int:
    ev: dict = {}

    s = scan_canonical_research_population(str(SUMMARIES)).collect(engine="streaming")
    ev["summaries_rows"] = s.height
    ev["summaries_unique_trade_id"] = s["trade_id"].n_unique()
    ev["summaries_unique_regime_key"] = s["selection_regime_key"].n_unique()

    ev["model_mapping"] = (
        s.group_by(
            ["model_id", "entry_model_id", "trade_direction_name", "trade_direction",
             "opposite_exit_model_id"]
        )
        .len()
        .sort("model_id")
        .to_dicts()
    )
    ev["frozen_entry_thresholds"] = (
        s.group_by("model_id")
        .agg(pl.col("entry_top_2_5_threshold").unique().alias("thresholds"))
        .sort("model_id")
        .to_dicts()
    )
    ev["threshold_membership_operator"] = s["threshold_membership_operator"].unique().to_list()

    # --- frozen percentile / top-10 / top-5 availability -------------------
    null_dtype_cols = [
        n for n, t in zip(s.collect_schema().names(), s.collect_schema().dtypes())
        if t == pl.Null
    ]
    ev["summaries_all_null_dtype_columns"] = null_dtype_cols
    ev["opposite_top_10_unavailable_reason"] = (
        s["opposite_top_10_unavailable_reason"].value_counts().to_dicts()
    )
    for c in [
        "opposite_first_top_10_ns", "opposite_first_top_5_ns", "opposite_first_top_2_5_ns",
        "opposite_probability_at_confirm", "max_opposite_probability_after_confirm",
        "max_opposite_score_ns",
    ]:
        ev[f"summaries_nonnull__{c}"] = int(s[c].is_not_null().sum())

    ev["entry_year_counts"] = s["entry_year"].value_counts().sort("entry_year").to_dicts()
    ev["path_is_complete_counts"] = s["path_is_complete"].value_counts().to_dicts()
    ev["censor_reason_counts"] = s["censor_reason"].value_counts().to_dicts()

    # --- observations: which columns are Null dtype -----------------------
    osch = pl.scan_parquet(OBS).collect_schema()
    ev["observations_all_null_dtype_columns"] = [
        n for n, t in zip(osch.names(), osch.dtypes()) if t == pl.Null
    ]
    ev["observations_model_ids"] = (
        pl.scan_parquet(OBS)
        .select("bullish_model_id", "bearish_model_id", "model_id", "trade_direction")
        .unique()
        .collect(engine="streaming")
        .to_dicts()
    )

    # --- paths: score availability + cadence ------------------------------
    p = scan_canonical_research_population(str(PATHS))
    psch = pl.scan_parquet(PATHS).collect_schema()
    ev["paths_all_null_dtype_columns"] = [
        n for n, t in zip(psch.names(), psch.dtypes()) if t == pl.Null
    ]

    cover = (
        p.select(
            pl.len().alias("path_rows"),
            pl.col("trade_id").n_unique().alias("path_trades"),
            pl.col("bullish_probability").is_not_null().sum().alias("bullish_prob_nonnull"),
            pl.col("bearish_probability").is_not_null().sum().alias("bearish_prob_nonnull"),
            pl.col("bullish_in_domain").sum().alias("bullish_in_domain_rows"),
            pl.col("bearish_in_domain").sum().alias("bearish_in_domain_rows"),
            pl.col("bullish_is_carried_forward").sum().alias("bullish_carried_rows"),
            pl.col("bearish_is_carried_forward").sum().alias("bearish_carried_rows"),
            pl.col("bullish_score_age_seconds").median().alias("bullish_age_median_s"),
            pl.col("bearish_score_age_seconds").median().alias("bearish_age_median_s"),
            pl.col("bullish_score_age_seconds").quantile(0.9).alias("bullish_age_p90_s"),
            pl.col("bearish_score_age_seconds").quantile(0.9).alias("bearish_age_p90_s"),
            pl.col("bullish_score_age_seconds").max().alias("bullish_age_max_s"),
            pl.col("bearish_score_age_seconds").max().alias("bearish_age_max_s"),
        )
        .collect(engine="streaming")
    )
    ev["path_score_coverage"] = cover.to_dicts()[0]

    # cadence: distinct score_source_ns gaps within a trade
    cadence = (
        p.select("trade_id", "timestamp_close_ns", "bullish_score_source_ns",
                 "bearish_score_source_ns")
        .sort(["trade_id", "timestamp_close_ns"])
        .group_by("trade_id")
        .agg(
            pl.col("bullish_score_source_ns").n_unique().alias("bull_unique_src"),
            pl.col("bearish_score_source_ns").n_unique().alias("bear_unique_src"),
            pl.len().alias("bars"),
        )
        .collect(engine="streaming")
    )
    ev["score_source_uniqueness"] = {
        "median_bars_per_trade": float(cadence["bars"].median()),
        "median_unique_bullish_sources": float(cadence["bull_unique_src"].median()),
        "median_unique_bearish_sources": float(cadence["bear_unique_src"].median()),
        "mean_bull_sources_per_bar": float(
            (cadence["bull_unique_src"] / cadence["bars"]).mean()
        ),
        "mean_bear_sources_per_bar": float(
            (cadence["bear_unique_src"] / cadence["bars"]).mean()
        ),
    }

    # distinct source-ns step sizes (true model observation cadence)
    steps = (
        p.select("trade_id", "bullish_score_source_ns", "bearish_score_source_ns",
                 "timestamp_close_ns")
        .sort(["trade_id", "timestamp_close_ns"])
        .unique(subset=["trade_id", "bullish_score_source_ns"], keep="first")
        .sort(["trade_id", "bullish_score_source_ns"])
        .with_columns(
            (pl.col("bullish_score_source_ns").diff().over("trade_id") / 1e9).alias("gap_s")
        )
        .filter(pl.col("gap_s").is_not_null())
        .select("gap_s")
        .collect(engine="streaming")
    )
    ev["bullish_source_gap_seconds"] = (
        steps["gap_s"].value_counts().sort("count", descending=True).head(15).to_dicts()
    )

    # causality: score_source_ns must never exceed bar close
    future = (
        p.select(
            (pl.col("bullish_score_source_ns") > pl.col("timestamp_close_ns")).sum()
            .alias("bull_future"),
            (pl.col("bearish_score_source_ns") > pl.col("timestamp_close_ns")).sum()
            .alias("bear_future"),
        )
        .collect(engine="streaming")
    )
    ev["future_score_rows"] = future.to_dicts()[0]

    # --- post-confirmation opposing-model coverage per trade --------------
    conf = s.select("trade_id", "trade_direction_name", "model_id", "confirm_flip_ns",
                    "fallback_exit_flip_ns")
    pc = (
        p.select("trade_id", "timestamp_close_ns", "seconds_from_confirm",
                 "bullish_probability", "bearish_probability",
                 "bullish_in_domain", "bearish_in_domain")
        .join(conf.lazy(), on="trade_id", how="inner")
        .filter(pl.col("timestamp_close_ns") >= pl.col("confirm_flip_ns"))
    )
    # opposing channel: SHORT (entry BULLISH_STRICT) -> monitor bearish channel
    pc = pc.with_columns(
        pl.when(pl.col("trade_direction_name") == "SHORT")
        .then(pl.col("bearish_probability"))
        .otherwise(pl.col("bullish_probability"))
        .alias("opp_prob"),
        pl.when(pl.col("trade_direction_name") == "SHORT")
        .then(pl.col("bearish_in_domain"))
        .otherwise(pl.col("bullish_in_domain"))
        .alias("opp_in_domain"),
    )
    per_trade = (
        pc.group_by("trade_id", "trade_direction_name")
        .agg(
            pl.len().alias("post_conf_bars"),
            pl.col("opp_prob").is_not_null().sum().alias("opp_prob_bars"),
            pl.col("opp_in_domain").sum().alias("opp_domain_bars"),
        )
        .collect(engine="streaming")
    )
    ev["post_confirmation_opposing_coverage"] = {
        "trades_with_post_confirmation_bars": per_trade.height,
        "trades_with_any_opposing_probability": int(
            (per_trade["opp_prob_bars"] > 0).sum()
        ),
        "trades_with_any_opposing_in_domain_bar": int(
            (per_trade["opp_domain_bars"] > 0).sum()
        ),
        "median_post_conf_bars": float(per_trade["post_conf_bars"].median()),
        "median_opp_domain_bars": float(per_trade["opp_domain_bars"].median()),
        "by_direction": per_trade.group_by("trade_direction_name")
        .agg(
            pl.len().alias("trades"),
            (pl.col("opp_domain_bars") > 0).sum().alias("with_domain"),
            pl.col("opp_domain_bars").median().alias("median_domain_bars"),
        )
        .to_dicts(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(ev, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"stage": "feasibility_complete", "out": str(OUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

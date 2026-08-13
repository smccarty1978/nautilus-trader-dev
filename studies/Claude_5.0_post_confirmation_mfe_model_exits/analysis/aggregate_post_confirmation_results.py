"""Aggregation, baseline-transition analysis, model-warning usefulness and
cross-stop robustness for the post-confirmation study."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

STUDY_DIR = Path(__file__).resolve().parents[1]
RES = STUDY_DIR / "results"
TRADES = RES / "post_confirmation_mfe_model_exit_trade_policy_results.parquet"
WARN = RES / "post_confirmation_model_warning_events.parquet"
ANCH = RES / "post_confirmation_model_diagnostic_anchors.parquet"

FLAT = 0.125
RESOLVED = pl.col("realized_return_atr").is_not_null()
STOPS = [0.75, 1.00, 1.25]
YEARS = [2021, 2022, 2023, 2024, 2025]


# ------------------------------------------------------------------ helpers
def _mdd(df: pl.DataFrame) -> float | None:
    """Max drawdown of the cumulative ATR curve, trades ordered by exit time."""
    d = df.filter(RESOLVED).sort("exit_timestamp")
    if not d.height:
        return None
    cum = np.cumsum(d["realized_return_atr"].to_numpy())
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    return float(np.max(peak - cum))


AGG = [
    pl.len().alias("trade_count"),
    RESOLVED.sum().alias("resolved_trade_count"),
    (pl.col("outcome_class") == "CENSORED / UNRESOLVED").sum().alias("censored_count"),
    (pl.col("outcome_class") == "AMBIGUOUS EVENT ORDER").sum().alias("ambiguous_count"),
    pl.col("realized_return_atr").mean().alias("mean_realized_return_atr"),
    pl.col("realized_return_atr").median().alias("median_realized_return_atr"),
    pl.col("realized_return_atr").sum().alias("gross_cumulative_atr"),
    pl.col("realized_return_atr").filter(pl.col("realized_return_atr") > 0).sum()
      .alias("_gross_win"),
    pl.col("realized_return_atr").filter(pl.col("realized_return_atr") < 0).sum()
      .alias("_gross_loss"),
    (pl.col("realized_return_points") > FLAT).sum().alias("_wins"),
    (pl.col("realized_return_points") < -FLAT).sum().alias("_losses"),
    (pl.col("realized_return_points").abs() <= FLAT).sum().alias("_flats"),
    pl.col("mfe_at_exit_atr").mean().alias("mean_full_trade_MFE_atr"),
    pl.col("mfe_at_exit_atr").median().alias("median_full_trade_MFE_atr"),
    pl.col("capture_ratio").mean().alias("mean_realized_capture_ratio"),
    pl.col("capture_ratio").median().alias("median_realized_capture_ratio"),
    pl.col("giveback_atr").mean().alias("mean_giveback_atr"),
    pl.col("giveback_atr").median().alias("median_giveback_atr"),
    pl.col("seconds_entry_to_exit").median().alias("median_seconds_entry_to_exit"),
    pl.col("seconds_entry_to_exit").mean().alias("mean_seconds_entry_to_exit"),
    pl.col("seconds_entry_to_exit").sum().alias("time_in_market_seconds"),
    pl.col("seconds_confirmation_to_exit").median()
      .alias("median_seconds_confirmation_to_exit"),
    (pl.col("outcome_class") == "STOPPED BEFORE CONFIRMATION").sum()
      .alias("stopped_before_confirmation_count"),
    (pl.col("outcome_class") == "STOPPED AFTER CONFIRMATION").sum()
      .alias("stopped_after_confirmation_count"),
    (pl.col("outcome_class") == "PRICE MANAGEMENT EXIT").sum()
      .alias("price_management_exit_count"),
    (pl.col("outcome_class") == "MODEL WARNING EXIT").sum()
      .alias("model_warning_exit_count"),
    pl.col("outcome_class").str.starts_with("REGIME-FLIP").sum()
      .alias("opposing_regime_flip_exit_count"),
    pl.col("same_bar_activation_and_violation").sum()
      .alias("same_bar_activation_and_violation_count"),
    pl.col("price_model_tie").sum().alias("price_model_tie_count"),
]


def summarize(df: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    g = df.group_by(keys).agg(AGG).sort(keys)
    g = g.with_columns(
        (pl.col("_gross_win") / pl.col("_gross_loss").abs()).alias("profit_factor"),
        (pl.col("_wins") / pl.col("resolved_trade_count")).alias("win_rate"),
        (pl.col("_losses") / pl.col("resolved_trade_count")).alias("loss_rate"),
        (pl.col("_flats") / pl.col("resolved_trade_count")).alias("flat_rate"),
    ).drop("_gross_win", "_gross_loss", "_wins", "_losses", "_flats")
    # max cumulative drawdown per group
    mdds = []
    for row in g.select(keys).iter_rows(named=True):
        sub = df
        for k, v in row.items():
            sub = sub.filter(pl.col(k) == v)
        mdds.append(_mdd(sub))
    return g.with_columns(pl.Series("max_cumulative_drawdown_atr", mdds))


def main() -> int:
    t = pl.read_parquet(TRADES)
    print(json.dumps({"stage": "loaded", "rows": t.height}), flush=True)

    meta = (
        t.group_by("policy_id")
        .agg(pl.col("policy_family").first(), pl.col("policy_scope").first(),
             pl.col("activation_mfe_atr").first(), pl.col("policy_param").first(),
             pl.col("threshold_name").first(), pl.col("persistence_k").first())
        .sort("policy_id")
    )

    out: dict = {
        "study_id": "Claude_5.0_post_confirmation_mfe_model_exits",
        "population_restriction": (
            "canonical selected FIRST Top-2.5% signal per regime only; "
            "does not represent all 69,432 qualifying observations"),
        "total_trades": t.filter(
            (pl.col("policy_id") == "BASE") & (pl.col("initial_stop_atr") == 1.00)
        ).height,
        "policy_catalog": meta.to_dicts(),
    }

    # ------------------------------------------------ primary policy results
    print(json.dumps({"stage": "primary"}), flush=True)
    primary = summarize(t, ["initial_stop_atr", "policy_id"])
    primary = primary.join(meta, on="policy_id", how="left")
    out["policy_results"] = primary.to_dicts()

    # ---------------------------------------------------------- breakdowns
    for name, keys in [
        ("by_model", ["initial_stop_atr", "policy_id", "model_id"]),
        ("by_direction", ["initial_stop_atr", "policy_id", "trade_direction_name"]),
        ("by_year", ["initial_stop_atr", "policy_id", "entry_year"]),
        ("by_model_year", ["initial_stop_atr", "policy_id", "model_id", "entry_year"]),
        ("by_direction_year",
         ["initial_stop_atr", "policy_id", "trade_direction_name", "entry_year"]),
    ]:
        print(json.dumps({"stage": name}), flush=True)
        g = t.group_by(keys).agg(AGG).sort(keys).with_columns(
            (pl.col("_gross_win") / pl.col("_gross_loss").abs()).alias("profit_factor"),
            (pl.col("_wins") / pl.col("resolved_trade_count")).alias("win_rate"),
        ).drop("_gross_win", "_gross_loss", "_wins", "_losses", "_flats")
        out[name] = g.to_dicts()

    # ------------------------------------------- baseline-transition analysis
    print(json.dumps({"stage": "transitions"}), flush=True)
    base = t.filter(pl.col("policy_id") == "BASE").select(
        "trade_id", "initial_stop_atr", "entry_year", "trade_direction_name",
        "model_id",
        pl.col("outcome_class").alias("baseline_outcome"),
        pl.col("realized_return_atr").alias("baseline_return_atr"),
        pl.col("mfe_at_exit_atr").alias("baseline_mfe_atr"),
        pl.col("giveback_atr").alias("baseline_giveback_atr"),
        pl.col("capture_ratio").alias("baseline_capture_ratio"),
        pl.col("peak_mfe_full_path_atr").alias("path_peak_mfe_atr"),
    )
    j = t.filter(pl.col("policy_id") != "BASE").join(
        base, on=["trade_id", "initial_stop_atr"], how="inner")
    j = j.with_columns(
        (pl.col("realized_return_atr") - pl.col("baseline_return_atr"))
        .alias("delta_return_atr"),
        (pl.col("baseline_giveback_atr") - pl.col("giveback_atr"))
        .alias("giveback_prevented_atr"),
    )
    comparable = pl.col("delta_return_atr").is_not_null()

    p90 = {
        s: float(base.filter((pl.col("initial_stop_atr") == s)
                             & pl.col("baseline_return_atr").is_not_null())
                 ["baseline_return_atr"].quantile(0.90))
        for s in STOPS
    }
    out["baseline_right_tail_p90_atr"] = p90
    j = j.with_columns(
        pl.col("initial_stop_atr").replace_strict(p90, default=None).alias("_p90"))

    trans = (
        j.group_by(["initial_stop_atr", "policy_id", "baseline_outcome"])
        .agg(
            pl.len().alias("trade_count"),
            comparable.sum().alias("comparable_count"),
            pl.col("delta_return_atr").mean().alias("mean_realized_improvement_atr"),
            pl.col("delta_return_atr").median().alias("median_realized_improvement_atr"),
            (pl.col("delta_return_atr") > 1e-9).sum().alias("_improved"),
            (pl.col("delta_return_atr") < -1e-9).sum().alias("_worsened"),
            (pl.col("delta_return_atr").abs() <= 1e-9).sum().alias("_unchanged"),
            ((pl.col("baseline_return_atr") < 0) & (pl.col("realized_return_atr") > 0))
            .sum().alias("_loss_to_profit"),
            ((pl.col("baseline_return_atr") > 0) & (pl.col("realized_return_atr") > 0)
             & (pl.col("realized_return_atr") < pl.col("baseline_return_atr")))
            .sum().alias("_profit_to_smaller_profit"),
            ((pl.col("baseline_return_atr") > 0) & (pl.col("realized_return_atr") < 0))
            .sum().alias("_profit_to_loss"),
            pl.col("delta_return_atr")
              .filter(pl.col("baseline_return_atr") >= pl.col("_p90")).sum()
              .alias("right_tail_return_delta_atr"),
            comparable.filter(pl.col("baseline_return_atr") >= pl.col("_p90")).sum()
              .alias("right_tail_trade_count"),
            pl.col("capture_ratio").mean().alias("mean_capture_ratio"),
            pl.col("baseline_capture_ratio").mean().alias("baseline_mean_capture_ratio"),
            pl.col("giveback_prevented_atr").mean().alias("mean_giveback_prevented_atr"),
            pl.col("giveback_prevented_atr").median()
              .alias("median_giveback_prevented_atr"),
        )
        .sort(["initial_stop_atr", "policy_id", "baseline_outcome"])
    )
    trans = trans.with_columns(
        (100 * pl.col("_improved") / pl.col("comparable_count")).alias("pct_improved"),
        (100 * pl.col("_worsened") / pl.col("comparable_count")).alias("pct_worsened"),
        (100 * pl.col("_unchanged") / pl.col("comparable_count")).alias("pct_unchanged"),
        (100 * pl.col("_loss_to_profit") / pl.col("comparable_count"))
        .alias("pct_loss_to_profit"),
        (100 * pl.col("_profit_to_smaller_profit") / pl.col("comparable_count"))
        .alias("pct_profit_to_smaller_profit"),
        (100 * pl.col("_profit_to_loss") / pl.col("comparable_count"))
        .alias("pct_profit_to_loss"),
    ).drop("_improved", "_worsened", "_unchanged", "_loss_to_profit",
           "_profit_to_smaller_profit", "_profit_to_loss")
    out["baseline_transition_analysis"] = trans.filter(
        pl.col("baseline_outcome").is_in([
            "STOPPED AFTER CONFIRMATION", "REGIME-FLIP EXIT FOR PROFIT",
            "REGIME-FLIP EXIT FOR LOSS"])).to_dicts()

    # ------------------- primary MFE-conservation population: losing flip exits
    print(json.dumps({"stage": "mfe_conservation"}), flush=True)
    cons = []
    lose = j.filter(pl.col("baseline_outcome") == "REGIME-FLIP EXIT FOR LOSS")
    for lvl in (0.75, 1.00, 1.50, 2.00):
        g = (
            lose.filter(pl.col("baseline_mfe_atr") >= lvl)
            .group_by(["initial_stop_atr", "policy_id"])
            .agg(
                pl.lit(lvl).alias("mfe_threshold_atr"),
                pl.len().alias("trade_count"),
                pl.col("delta_return_atr").mean().alias("mean_improvement_atr"),
                pl.col("delta_return_atr").median().alias("median_improvement_atr"),
                pl.col("delta_return_atr").sum().alias("total_improvement_atr"),
                (pl.col("delta_return_atr") > 1e-9).mean().alias("frac_improved"),
                pl.col("realized_return_atr").mean().alias("mean_policy_return_atr"),
                pl.col("baseline_return_atr").mean().alias("mean_baseline_return_atr"),
                pl.col("capture_ratio").mean().alias("mean_capture_ratio"),
            )
        )
        cons.append(g)
    out["losing_flip_mfe_conservation"] = pl.concat(cons).sort(
        ["mfe_threshold_atr", "initial_stop_atr", "policy_id"]).to_dicts()
    out["losing_flip_population"] = (
        lose.filter(pl.col("policy_id") == "A1_act1_00_floor0_25")
        .group_by("initial_stop_atr")
        .agg(
            pl.len().alias("baseline_losing_flip_trades"),
            *[(pl.col("baseline_mfe_atr") >= lvl).sum().alias(f"reached_mfe_{lvl:.2f}")
              for lvl in (0.75, 1.00, 1.50, 2.00)],
        ).sort("initial_stop_atr").to_dicts()
    )

    # ------------------------------------------- model-warning usefulness
    print(json.dumps({"stage": "warnings"}), flush=True)
    w = pl.read_parquet(WARN)
    b100 = base.filter(pl.col("initial_stop_atr") == 1.00).select(
        "trade_id", "baseline_outcome", "baseline_return_atr", "baseline_mfe_atr")
    wj = w.join(b100, on="trade_id", how="left")
    out["warning_state_distribution"] = (
        wj.group_by(["threshold_name", "trade_direction_name", "threshold_state"])
        .len().sort(["threshold_name", "trade_direction_name", "threshold_state"])
        .to_dicts()
    )
    sup = wj.filter(pl.col("threshold_state") != "THRESHOLD NOT FROZEN")
    out["warning_usefulness"] = (
        sup.group_by("threshold_name").agg(
            pl.len().alias("trades"),
            (pl.col("post_confirmation_eligible_obs") > 0).mean()
              .alias("post_confirmation_coverage"),
            (pl.col("max_opposing_probability_post_confirmation")
             >= pl.col("threshold_value")).mean().alias("ever_warning_rate"),
            pl.col("warning_timestamp").is_not_null().mean().alias("crossing_rate"),
            pl.col("already_active_at_confirmation").mean()
              .alias("already_active_at_confirmation_rate"),
            ((pl.col("post_confirmation_eligible_obs") > 0)
             & (pl.col("max_opposing_probability_post_confirmation")
                < pl.col("threshold_value"))).mean().alias("never_warning_rate"),
            (pl.col("post_confirmation_eligible_obs") == 0).mean()
              .alias("out_of_domain_rate"),
            pl.col("seconds_confirmation_to_warning").median()
              .alias("median_confirmation_to_warning_seconds"),
            pl.col("mfe_at_warning_atr").median().alias("median_mfe_at_warning_atr"),
            pl.col("unrealized_return_at_warning_atr").median()
              .alias("median_unrealized_return_at_warning_atr"),
            pl.col("remaining_mfe_after_warning_atr").median()
              .alias("median_remaining_mfe_after_warning_atr"),
            pl.col("seconds_warning_to_fallback_exit").median()
              .alias("median_warning_to_opposing_flip_seconds"),
            pl.col("seconds_k1_to_k2").median().alias("median_seconds_k1_to_k2"),
            pl.col("seconds_k1_to_k3").median().alias("median_seconds_k1_to_k3"),
        ).sort("threshold_name").to_dicts()
    )
    out["warning_incidence_by_baseline_outcome"] = (
        sup.filter(pl.col("baseline_outcome").is_in([
            "REGIME-FLIP EXIT FOR PROFIT", "REGIME-FLIP EXIT FOR LOSS",
            "STOPPED AFTER CONFIRMATION"]))
        .group_by(["threshold_name", "baseline_outcome"]).agg(
            pl.len().alias("trades"),
            pl.col("warning_timestamp").is_not_null().mean().alias("crossing_rate"),
            (pl.col("post_confirmation_eligible_obs") == 0).mean()
              .alias("no_eligible_obs_rate"),
            pl.col("seconds_confirmation_to_warning").median()
              .alias("median_warning_lead_seconds"),
            pl.col("unrealized_return_at_warning_atr").median()
              .alias("median_unrealized_at_warning_atr"),
            pl.col("remaining_mfe_after_warning_atr").median()
              .alias("median_remaining_mfe_after_warning_atr"),
        ).sort(["threshold_name", "baseline_outcome"]).to_dicts()
    )
    out["warning_winner_vs_loser"] = (
        sup.with_columns(
            pl.when(pl.col("baseline_return_atr") > 0).then(pl.lit("EVENTUAL WINNER"))
            .when(pl.col("baseline_return_atr") < 0).then(pl.lit("EVENTUAL LOSER"))
            .otherwise(pl.lit("FLAT/UNRESOLVED")).alias("baseline_sign"))
        .group_by(["threshold_name", "baseline_sign"]).agg(
            pl.len().alias("trades"),
            pl.col("warning_timestamp").is_not_null().mean().alias("crossing_rate"),
            pl.col("seconds_confirmation_to_warning").median()
              .alias("median_warning_lead_seconds"),
        ).sort(["threshold_name", "baseline_sign"]).to_dicts()
    )

    # ------------------------------------------------- cross-stop robustness
    print(json.dumps({"stage": "cross_stop"}), flush=True)
    yearly = (
        j.group_by(["initial_stop_atr", "policy_id", "entry_year"])
        .agg(pl.col("delta_return_atr").mean().alias("mean_delta"))
    )
    years_pos = (
        yearly.group_by(["initial_stop_atr", "policy_id"])
        .agg((pl.col("mean_delta") > 0).sum().alias("years_improved"),
             pl.col("mean_delta").min().alias("worst_year_delta"),
             pl.col("mean_delta").max().alias("best_year_delta"))
    )
    dirs = (
        j.group_by(["initial_stop_atr", "policy_id", "trade_direction_name"])
        .agg(pl.col("delta_return_atr").mean().alias("mean_delta"))
        .pivot(on="trade_direction_name", index=["initial_stop_atr", "policy_id"],
               values="mean_delta")
        .rename({"LONG": "mean_delta_long", "SHORT": "mean_delta_short"})
    )
    overall = (
        j.group_by(["initial_stop_atr", "policy_id"]).agg(
            pl.col("delta_return_atr").mean().alias("mean_incremental_return_atr"),
            pl.col("delta_return_atr").median().alias("median_incremental_return_atr"),
            pl.col("delta_return_atr").sum().alias("total_incremental_return_atr"),
            (pl.col("delta_return_atr").std() / comparable.sum().sqrt())
              .alias("incremental_return_stderr"),
            (pl.col("delta_return_atr").mean()
             / (pl.col("delta_return_atr").std() / comparable.sum().sqrt()))
              .alias("incremental_return_tstat"),
            comparable.sum().alias("comparable_trades"),
            (pl.col("delta_return_atr") > 1e-9).mean().alias("frac_trades_improved"),
            pl.col("capture_ratio").mean().alias("mean_capture_ratio"),
            pl.col("baseline_capture_ratio").mean().alias("baseline_mean_capture_ratio"),
            (pl.col("outcome_class") == "AMBIGUOUS EVENT ORDER").sum()
              .alias("ambiguous_count"),
            (pl.col("outcome_class") == "CENSORED / UNRESOLVED").sum()
              .alias("censored_count"),
            ((pl.col("baseline_return_atr") >= pl.col("_p90"))
             & (pl.col("delta_return_atr") < -1e-9)).sum()
              .alias("right_tail_trades_truncated"),
            pl.col("delta_return_atr")
              .filter(pl.col("baseline_return_atr") >= pl.col("_p90")).mean()
              .alias("right_tail_mean_delta_atr"),
            ((pl.col("baseline_return_atr") < 0) & (pl.col("realized_return_atr") > 0))
              .sum().alias("loss_to_profit_conversions"),
        )
    )
    # Scope-matched baselines: LONG_ONLY policies must be compared against the
    # baseline restricted to LONG trades, never the full population.
    base_all = summarize(t.filter(pl.col("policy_id") == "BASE"),
                         ["initial_stop_atr"]).with_columns(
        pl.lit("ALL").alias("policy_scope"))
    base_long = summarize(
        t.filter((pl.col("policy_id") == "BASE")
                 & (pl.col("trade_direction_name") == "LONG")),
        ["initial_stop_atr"]).with_columns(pl.lit("LONG_ONLY").alias("policy_scope"))
    base_stats = pl.concat([base_all, base_long]).select(
        "initial_stop_atr", "policy_scope",
        pl.col("mean_realized_return_atr").alias("baseline_mean_return_atr"),
        pl.col("gross_cumulative_atr").alias("baseline_gross_cumulative_atr"),
        pl.col("profit_factor").alias("baseline_profit_factor"),
        pl.col("max_cumulative_drawdown_atr").alias("baseline_max_drawdown_atr"),
        pl.col("ambiguous_count").alias("baseline_ambiguous_count"),
        pl.col("censored_count").alias("baseline_censored_count"),
        pl.col("mean_realized_capture_ratio").alias("baseline_scope_mean_capture_ratio"),
    )
    cross = (
        primary.join(overall, on=["initial_stop_atr", "policy_id"], how="left")
        .join(years_pos, on=["initial_stop_atr", "policy_id"], how="left")
        .join(dirs, on=["initial_stop_atr", "policy_id"], how="left")
        .join(base_stats, on=["initial_stop_atr", "policy_scope"], how="left")
        .with_columns(
            (pl.col("mean_realized_return_atr") - pl.col("baseline_mean_return_atr"))
            .alias("incremental_mean_return_vs_baseline_atr"),
            (pl.col("profit_factor") - pl.col("baseline_profit_factor"))
            .alias("incremental_profit_factor"),
            (pl.col("max_cumulative_drawdown_atr") - pl.col("baseline_max_drawdown_atr"))
            .alias("incremental_max_drawdown_atr"),
            (pl.col("mean_capture_ratio") - pl.col("baseline_mean_capture_ratio"))
            .alias("incremental_capture_ratio"),
            (pl.col("ambiguous_count") - pl.col("baseline_ambiguous_count"))
            .alias("incremental_ambiguous_count"),
            (pl.col("censored_count") - pl.col("baseline_censored_count"))
            .alias("incremental_censored_count"),
        )
    )
    # Robustness verdict across the three stops, driven by the PAIRED per-trade
    # delta (mean_incremental_return_atr), which is scope-safe by construction.
    signs = (
        cross.filter(pl.col("policy_id") != "BASE")
        .group_by("policy_id")
        .agg(
            (pl.col("mean_incremental_return_atr") > 0).sum().alias("stops_improved"),
            pl.col("mean_incremental_return_atr").min().alias("worst_stop_delta"),
            pl.col("mean_incremental_return_atr").max().alias("best_stop_delta"),
            pl.col("years_improved").min().alias("min_years_improved_across_stops"),
        )
        .with_columns(
            pl.when(pl.col("stops_improved") == 3).then(pl.lit("IMPROVES ALL THREE"))
            .when(pl.col("stops_improved") == 0).then(pl.lit("IMPROVES NONE"))
            .otherwise(pl.lit("STOP-SPECIFIC")).alias("cross_stop_verdict"))
    )
    cross = cross.join(signs, on="policy_id", how="left").sort(
        ["policy_id", "initial_stop_atr"])
    cross.write_parquet(RES / "post_confirmation_policy_cross_stop_comparison.parquet",
                        compression="zstd", statistics=True)
    out["cross_stop_comparison"] = cross.to_dicts()

    # ------------------------------------------------- diagnostic anchors
    print(json.dumps({"stage": "anchors"}), flush=True)
    a = pl.read_parquet(ANCH)
    out["anchor_diagnostics"] = (
        a.group_by(["anchor", "trade_direction_name"]).agg(
            pl.len().alias("n"),
            pl.col("opposing_in_domain").mean().alias("opposing_in_domain_rate"),
            pl.col("opposing_probability").median().alias("median_opposing_probability"),
            pl.col("opposing_change_30s").median().alias("median_change_30s"),
            pl.col("opposing_change_60s").median().alias("median_change_60s"),
            pl.col("entry_model_probability").median()
              .alias("median_entry_model_probability"),
            pl.col("entry_model_in_domain").mean().alias("entry_model_in_domain_rate"),
            pl.col("seconds_from_confirmation").median()
              .alias("median_seconds_from_confirmation"),
            pl.col("running_mfe_atr").median().alias("median_running_mfe_atr"),
        ).sort(["anchor", "trade_direction_name"]).to_dicts()
    )

    # ------------------------------------------------------------ validation
    val = json.loads((RES / "post_confirmation_validation.json").read_text("utf-8"))
    rec = json.loads((RES / "baseline_reconciliation.json").read_text("utf-8"))
    dup = t.group_by(["trade_id", "initial_stop_atr", "policy_id"]).len().filter(
        pl.col("len") > 1).height
    scope_ok = (
        t.group_by(["policy_id", "policy_scope", "initial_stop_atr"]).len()
        .with_columns(
            pl.when(pl.col("policy_scope") == "ALL").then(pl.lit(5836))
            .otherwise(pl.lit(2507)).alias("expected"))
        .filter(pl.col("len") != pl.col("expected")).height
    )
    out["validation"] = {
        "duplicate_trade_policy_keys": dup,
        "policy_population_violations": scope_ok,
        "baseline_reconciliation_exact": rec["all_exact"],
        "baseline_reconciliation": {
            k: {kk: vv for kk, vv in v.items()
                if kk in ("population", "counts_exact",
                          "classification_mismatches_vs_stored",
                          "realized_return_mismatches_vs_stored", "exact")}
            for k, v in rec["per_stop"].items()},
        "independent_recompute": {
            "seed": val["seed"],
            "trade_stop_cases": val["trade_stop_cases"],
            "policy_checks_performed": val["policy_checks_performed"],
            "unexplained_mismatches": val["unexplained_mismatches"],
        },
        "outcome_classes_mutually_exclusive": True,
        "unique_outcome_classes": sorted(t["outcome_class"].unique().to_list()),
    }
    out["conventions"] = {
        "entry_price": "checkpoint_reference_price",
        "entry_atr": "atr_at_entry",
        "stop_touch": "completed 1s bar, adverse_intrabar_extreme_atr <= -S",
        "floor_violation": "completed 1s bar, adverse_intrabar_extreme_atr <= F",
        "fill": "next path-bar open",
        "flat_tolerance_points": FLAT,
        "execution_window": "first path bar with timestamp_open_ns >= confirm_flip_ns",
        "floor_information_set": "running_mfe_atr through bar i-1 (lagged floor)",
        "eligible_model_observation":
            "opposing channel is_carried_forward=false AND in_domain=true",
        "top_10_scope": "LONG trades only; bearish top_10 threshold is not frozen",
    }

    p = RES / "post_confirmation_mfe_model_exit_summary.json"
    p.write_text(json.dumps(out, indent=2, allow_nan=False, default=str),
                 encoding="utf-8")
    print(json.dumps({"stage": "complete", "summary": str(p),
                      "policy_rows": primary.height}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

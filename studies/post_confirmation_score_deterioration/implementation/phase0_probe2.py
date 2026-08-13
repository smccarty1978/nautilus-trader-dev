"""Phase 0, probe 2: is the post-confirmation score available in time to act?

Probe 1 established that only 1,875 of 4,705 confirmed trades carry ANY
post-confirmation in-domain score observation, and that the first one arrives a
median 400s after confirmation. This probe answers the question that turns that
into a verdict:

    How much of each trade is already over by the time the first
    post-confirmation score exists?

It also tests the two escape hatches before the study is declared infeasible:

  (a) the OUT-OF-DOMAIN (exploratory) score of either model, which the
      predecessor study used as a conditioning variable and which may be
      populated before the new regime is established; and
  (b) whether any score row exists at all at those timestamps.

If neither rescues the failure populations, the deterioration signal the brief
asks about cannot be observed on the trades it is meant to protect, and that is
a structural feasibility result rather than a modelling choice.
"""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
PRIOR = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
OUT = ROOT / "studies/post_confirmation_score_deterioration/results"
NS = 1_000_000_000

LABELS = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER",
          "FINAL_FLIP_EXIT_WINNER", "SESSION_EXIT")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {}

    paths = pl.read_parquet(PRIOR).filter(pl.col("valid"))
    regimes = (
        pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
        .select("regime_id", "regime_direction", "regime_start_decision_ns",
                "regime_established_decision_ns", "established_reached")
        .collect()
    )
    conf = (
        paths.filter(
            pl.col("terminal_label_full").is_in(list(LABELS))
            & pl.col("walk_a_confirm_ns").is_not_null()
        )
        .select("regime_id", "direction", "side", "entry_year",
                "terminal_label_full", "walk_a_confirm_ns", "full_exit_ns",
                "full_mfe_atr", "full_gross_atr")
        .join(
            regimes.rename({"regime_id": "new_regime_id"}),
            left_on=["walk_a_confirm_ns", "direction"],
            right_on=["regime_start_decision_ns", "regime_direction"],
            how="left",
        )
        .with_columns(
            hold_s=((pl.col("full_exit_ns") - pl.col("walk_a_confirm_ns")) / NS),
            est_delay_s=((pl.col("regime_established_decision_ns")
                          - pl.col("walk_a_confirm_ns")) / NS),
        )
    )

    # --- how long does each outcome actually last after confirmation? -----
    report["hold_seconds_after_confirmation"] = (
        conf.group_by("terminal_label_full")
        .agg(
            n=pl.len(),
            median_hold_s=pl.col("hold_s").median().round(1),
            p25=pl.col("hold_s").quantile(0.25).round(1),
            p75=pl.col("hold_s").quantile(0.75).round(1),
            p90=pl.col("hold_s").quantile(0.90).round(1),
            median_mfe_atr=pl.col("full_mfe_atr").median().round(4),
        )
        .sort("n", descending=True)
        .to_dicts()
    )

    # --- what fraction of the trade is over before the gate opens? --------
    gated = conf.with_columns(
        gate_after_exit=(pl.col("regime_established_decision_ns").is_null()
                         | (pl.col("regime_established_decision_ns")
                            > pl.col("full_exit_ns"))),
        frac_elapsed_at_gate=(pl.col("est_delay_s") / pl.col("hold_s")),
    )
    report["established_gate_vs_trade"] = (
        gated.group_by("terminal_label_full")
        .agg(
            n=pl.len(),
            pct_gate_never_opens_before_exit=(
                pl.col("gate_after_exit").mean() * 100).round(2),
            median_gate_delay_s=pl.col("est_delay_s").median().round(1),
            median_frac_of_trade_elapsed_at_gate=(
                pl.col("frac_elapsed_at_gate").median().round(3)),
        )
        .sort("n", descending=True)
        .to_dicts()
    )

    # --- escape hatch: ANY score row, in-domain or not --------------------
    scores = (
        pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
        .filter(pl.col("session") == "RTH")
        .select("regime_id", "checkpoint_decision_ns",
                "bullish_in_domain", "bearish_in_domain",
                "bullish_probability", "bearish_probability")
        .collect()
        .with_columns(
            any_score=(pl.col("bullish_probability").is_not_null()
                       | pl.col("bearish_probability").is_not_null()),
            in_domain=(pl.col("bullish_in_domain") | pl.col("bearish_in_domain")),
            out_of_domain_score=(
                (~pl.col("bullish_in_domain") & pl.col("bullish_probability").is_not_null())
                | (~pl.col("bearish_in_domain") & pl.col("bearish_probability").is_not_null())
            ),
        )
    )
    win = conf.select("new_regime_id", "terminal_label_full",
                      "walk_a_confirm_ns", "full_exit_ns").drop_nulls("new_regime_id")
    post = scores.join(
        win, left_on="regime_id", right_on="new_regime_id", how="inner"
    ).filter(
        (pl.col("checkpoint_decision_ns") >= pl.col("walk_a_confirm_ns"))
        & (pl.col("checkpoint_decision_ns") <= pl.col("full_exit_ns"))
    )

    cover = (
        post.group_by(["regime_id", "terminal_label_full"])
        .agg(
            rows=pl.len(),
            any_score_rows=pl.col("any_score").sum(),
            in_domain_rows=pl.col("in_domain").sum(),
            ood_rows=pl.col("out_of_domain_score").sum(),
        )
    )
    totals = conf.group_by("terminal_label_full").agg(total=pl.len())
    summary = (
        cover.group_by("terminal_label_full")
        .agg(
            trades_with_any_row=pl.len(),
            trades_with_any_score=(pl.col("any_score_rows") > 0).sum(),
            trades_with_in_domain=(pl.col("in_domain_rows") > 0).sum(),
            trades_with_ood_score=(pl.col("ood_rows") > 0).sum(),
            trades_with_ge3_in_domain=(pl.col("in_domain_rows") >= 3).sum(),
        )
        .join(totals, on="terminal_label_full", how="right")
        .with_columns(
            pct_any_score=(pl.col("trades_with_any_score") / pl.col("total") * 100).round(2),
            pct_in_domain=(pl.col("trades_with_in_domain") / pl.col("total") * 100).round(2),
            pct_ge3_in_domain=(pl.col("trades_with_ge3_in_domain") / pl.col("total") * 100).round(2),
        )
        .sort("total", descending=True)
    )
    report["score_coverage_by_outcome"] = summary.to_dicts()

    failed = ["CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER"]
    f = summary.filter(pl.col("terminal_label_full").is_in(failed))
    w = summary.filter(pl.col("terminal_label_full") == "FINAL_FLIP_EXIT_WINNER")
    report["headline"] = {
        "failed_trades_total": int(f["total"].sum()),
        "failed_trades_with_any_in_domain_score": int(
            f["trades_with_in_domain"].fill_null(0).sum()),
        "failed_trades_with_ge3_in_domain_scores": int(
            f["trades_with_ge3_in_domain"].fill_null(0).sum()),
        "winner_trades_total": int(w["total"].sum()),
        "winner_trades_with_ge3_in_domain_scores": int(
            w["trades_with_ge3_in_domain"].fill_null(0).sum()),
    }

    (OUT / "phase0_probe2.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()

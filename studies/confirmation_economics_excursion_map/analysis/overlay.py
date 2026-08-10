"""Phase 9 — model overlay. EXPLORATORY OUT-OF-DOMAIN. Not deployable.

The gate in SPEC 4 is satisfied but only narrowly, and the label matters more
than the numbers. `studies/post_confirmation_score_deterioration/reconciliation/`
(verdict **B**) established that the raw post-confirmation score is:

  * a true model dispatch -- `*_score_is_new` true for 100% of RTH rows;
  * causally available at its decision timestamp --
    `*_score_available_ns - checkpoint_decision_ns == 0` for all 5,665,103 rows;
  * and read almost entirely OUTSIDE the frozen model's domain contract --
    contract-valid in-domain share is 0.0% / 0.0% / 1.6% / 16.4% at
    60 / 120 / 180 / 300s after confirmation.

So the score is real and knowable, and the frozen percentile thresholds do NOT
transfer to it. Every split below is therefore **distribution-free** -- the
median of the alive cross-section at the event, never a calibrated threshold.

The question is narrow and deliberately so: at a price state the price-only
analysis has already shown to be interesting, does adding model danger improve
separation? No optimization, no grid, no policy.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
OUT = ROOT / "studies/confirmation_economics_excursion_map/results"
PANEL = OUT / "excursion_panel.parquet"
NS = 1_000_000_000

FULL = ("top_2_5", "armed")
CTS, FLIP_W, FLIP_L = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_WINNER",
                       "FINAL_FLIP_EXIT_LOSER")
# The price states the price-only work flags as economically meaningful.
STATES = (("B", 0.25), ("B", 0.50), ("B", 0.75), ("A", 0.50))


def _tag(x: float) -> str:
    return f"{x:+.2f}".replace(".", "_").replace("+", "p").replace("-", "m")


def load_scores(new_regime_ids: list[str]) -> pl.DataFrame:
    return (
        pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
        .filter((pl.col("session") == "RTH")
                & pl.col("regime_id").is_in(new_regime_ids))
        .select("regime_id", "checkpoint_decision_ns",
                "bullish_probability", "bearish_probability",
                "bullish_in_domain", "bearish_in_domain")
        .collect()
    )


def main() -> None:
    panel = pl.read_parquet(PANEL)
    regimes = (
        pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
        .select("regime_id", "regime_direction", "regime_start_decision_ns")
        .collect()
    )
    report = {
        "STATUS": "EXPLORATORY OUT-OF-DOMAIN — NOT DEPLOYABLE",
        "provenance": (
            "Raw domain-model score, read ungated. Causally available and a true "
            "dispatch (reconciliation verdict B), but contract-valid in-domain "
            "share is 0.0%/0.0%/1.6%/16.4% at 60/120/180/300s post-confirmation. "
            "Frozen percentile thresholds do not transfer, so all splits here are "
            "distribution-free medians of the alive cross-section."
        ),
        "populations": {},
    }

    for pop in FULL:
        c = panel.filter((pl.col("population") == pop)
                         & (pl.col("path_mode") == "unconstrained")
                         & pl.col("confirmed")
                         & pl.col("measurable_post_confirm"))
        if c.height == 0:
            continue
        # The NEW regime is the one starting at the confirming flip in our
        # direction -- the same join the reconciliation verified.
        c = c.join(regimes.rename({"regime_id": "new_regime_id"}),
                   left_on=["confirm_ns", "direction"],
                   right_on=["regime_start_decision_ns", "regime_direction"],
                   how="left").drop_nulls("new_regime_id")
        scores = load_scores(c["new_regime_id"].unique().to_list())
        # Domain-model raw score: the model whose domain IS the new regime.
        scores = scores.join(
            c.select("new_regime_id", "direction").unique(),
            left_on="regime_id", right_on="new_regime_id", how="inner",
        ).with_columns(
            score_b=pl.when(pl.col("direction") == 1)
            .then(pl.col("bullish_probability")).otherwise(pl.col("bearish_probability")),
            in_domain=pl.when(pl.col("direction") == 1)
            .then(pl.col("bullish_in_domain")).otherwise(pl.col("bearish_in_domain")),
        ).filter(pl.col("score_b").is_not_null()).sort("checkpoint_decision_ns")

        blocks = {}
        for method, level in STATES:
            key = f"{method}_{_tag(level)}"
            ns_col = f"det{method}_{_tag(level)}_ns"
            fired = c.filter(pl.col(ns_col).is_not_null())
            if fired.height < 40:
                blocks[key] = {"n": fired.height, "note": "too few to split"}
                continue
            # As-of join: the most recent REAL dispatch at or before the moment
            # the price state occurs. Never a future score.
            j = fired.select("new_regime_id", "terminal_label_constrained",
                             "eventual_mfe_atr", event_ns=pl.col(ns_col)).sort("event_ns")
            j = j.join_asof(
                scores.select("regime_id", "score_b", "in_domain",
                              score_ns="checkpoint_decision_ns").sort("score_ns"),
                left_on="event_ns", right_on="score_ns",
                by_left="new_regime_id", by_right="regime_id",
                strategy="backward",
            ).drop_nulls("score_b")
            if j.height < 40:
                blocks[key] = {"n": j.height, "note": "too few with a score"}
                continue

            med = float(np.median(j["score_b"].to_numpy()))
            hi = j.filter(pl.col("score_b") >= med)
            lo = j.filter(pl.col("score_b") < med)

            def stats(s):
                if s.height == 0:
                    return {"n": 0}
                lab = s["terminal_label_constrained"]
                e = s["eventual_mfe_atr"]
                return {
                    "n": s.height,
                    "p_failure": round(float(lab.is_in([CTS, FLIP_L]).mean()), 4),
                    "p_flip_winner": round(float((lab == FLIP_W).mean()), 4),
                    "p_runner_ge_2_5atr": round(float((e >= 2.5).mean()), 4),
                    "median_eventual_mfe_atr": round(float(e.median()), 4),
                }

            price_only = stats(j)
            blocks[key] = {
                "price_state": f"method {method}, deterioration >= {level} ATR",
                "n_price_only": j.height,
                "score_median_split": round(med, 4),
                "in_domain_share_at_event": round(
                    float(j["in_domain"].fill_null(False).mean()), 4),
                "PRICE_ONLY": price_only,
                "PRICE_PLUS_HIGH_MODEL_DANGER": stats(hi),
                "PRICE_PLUS_LOW_MODEL_DANGER": stats(lo),
                "failure_precision_lift_vs_price_only": (
                    round(stats(hi)["p_failure"] - price_only["p_failure"], 4)
                    if hi.height else None),
                "runner_protection_cost": (
                    round(stats(hi)["p_runner_ge_2_5atr"]
                          - price_only["p_runner_ge_2_5atr"], 4)
                    if hi.height else None),
            }
        report["populations"][pop] = {"confirmed": c.height, "states": blocks}

    (OUT / "price_model_overlay.json").write_text(json.dumps(report, indent=2, default=str))
    for pop, b in report["populations"].items():
        print(f"\n=== {pop} (confirmed {b['confirmed']:,})")
        for k, v in b["states"].items():
            if "PRICE_ONLY" not in v:
                print(f"  {k}: {v.get('note')}")
                continue
            print(f"  {k}: n={v['n_price_only']:>5} in_domain={v['in_domain_share_at_event']} "
                  f"| price-only p_fail={v['PRICE_ONLY']['p_failure']} "
                  f"-> +danger {v['PRICE_PLUS_HIGH_MODEL_DANGER']['p_failure']} "
                  f"(lift {v['failure_precision_lift_vs_price_only']}) "
                  f"runner cost {v['runner_protection_cost']}")
    print("\nwrote price_model_overlay.json")


if __name__ == "__main__":
    main()

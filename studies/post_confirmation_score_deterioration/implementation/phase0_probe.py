"""Phase 0 feasibility probe: which score is live after confirmation, and when.

Three questions must be answered before any of this study can be specified,
and none of them is answerable from the predecessor study's artifacts:

1. **Population reconciliation.** The brief quotes terminal counts
   (822 / 1,359 / 2,350 / 174). Reproduce them from the event table rather
   than assuming them, and reconcile against the Walk A confirmation count.

2. **Which score is live post-confirmation, and from when.** A regime's model
   only scores while that model is in-domain, and the domain contract has an
   established-regime gate. If the new regime does not become in-domain until
   well after confirmation, the usable observation window is much shorter than
   the trade.

3. **Polarity.** This is the one that can invert the entire study. Fading a
   bullish regime SHORT means confirmation is a *bearish* regime starting. In
   that new bearish regime the in-domain model is the BEARISH model -- whose
   own fade direction is LONG, i.e. it is predicting that OUR regime ends. A
   rising in-domain score post-confirmation is therefore plausibly *danger*,
   not conviction, which is the opposite of the pre-confirmation reading and
   the opposite of the brief's "deterioration = score falling" framing.

Nothing is written except a JSON checkpoint. No policy, no events.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
PRIOR = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
OUT = ROOT / "studies/post_confirmation_score_deterioration/results"
NS = 1_000_000_000


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {}

    paths = pl.read_parquet(PRIOR).filter(pl.col("valid"))
    report["armed_regimes"] = paths.height

    # --- Q1 population reconciliation -------------------------------------
    counts = {
        r["terminal_label_full"]: r["count"]
        for r in paths["terminal_label_full"].value_counts().iter_rows(named=True)
    }
    quoted = {
        "CONFIRMED_THEN_STOPPED": 822,
        "FINAL_FLIP_EXIT_LOSER": 1359,
        "FINAL_FLIP_EXIT_WINNER": 2350,
        "SESSION_EXIT": 174,
    }
    confirmed_continuation = sum(counts.get(k, 0) for k in quoted)
    walk_a_confirmed = int(paths["walk_a_confirm_reached_censored"].sum())
    report["reconciliation"] = {
        "observed_terminal_labels": counts,
        "quoted_in_brief": quoted,
        "matches_brief": {k: counts.get(k, 0) == v for k, v in quoted.items()},
        "confirmed_via_continuation_walk": confirmed_continuation,
        "confirmed_via_walk_a": walk_a_confirmed,
        "delta": confirmed_continuation - walk_a_confirmed,
    }

    # --- identify the NEW regime for each confirmed trade -----------------
    regimes = (
        pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
        .select(
            "regime_id", "regime_direction", "regime_start_decision_ns",
            "regime_end_decision_ns", "regime_established_decision_ns",
            "established_reached", "duration_seconds", "session_at_start",
        )
        .collect()
    )
    conf = paths.filter(
        pl.col("terminal_label_full").is_in(list(quoted))
        & pl.col("walk_a_confirm_ns").is_not_null()
    ).select(
        "regime_id", "direction", "side", "entry_year", "terminal_label_full",
        "arm_top10_ns", "walk_a_confirm_ns", "full_exit_ns", "full_mfe_atr",
        "full_gross_atr", "arm_atr",
    )
    new = conf.join(
        regimes.rename({"regime_id": "new_regime_id"}),
        left_on=["walk_a_confirm_ns", "direction"],
        right_on=["regime_start_decision_ns", "regime_direction"],
        how="left",
    )
    report["new_regime_join"] = {
        "confirmed_trades": conf.height,
        "matched_new_regime": int(new["new_regime_id"].is_not_null().sum()),
        "unmatched": int(new["new_regime_id"].is_null().sum()),
        "established_reached_pct": round(
            100 * float(new["established_reached"].fill_null(False).mean()), 2
        ),
    }
    new = new.filter(pl.col("new_regime_id").is_not_null())

    # Delay from confirmation to the established gate.
    est_delay = (
        (new["regime_established_decision_ns"] - new["walk_a_confirm_ns"]) / NS
    ).drop_nulls()
    report["established_gate_delay_s"] = {
        "n": est_delay.len(),
        "median": float(est_delay.median()) if est_delay.len() else None,
        "p25": float(est_delay.quantile(0.25)) if est_delay.len() else None,
        "p75": float(est_delay.quantile(0.75)) if est_delay.len() else None,
        "p95": float(est_delay.quantile(0.95)) if est_delay.len() else None,
    }

    # --- Q2 post-confirmation score availability --------------------------
    scores = (
        pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
        .filter(
            (pl.col("bullish_in_domain") | pl.col("bearish_in_domain"))
            & (pl.col("session") == "RTH")
        )
        .select(
            "regime_id", "checkpoint_decision_ns", "checkpoint_reference_price",
            "atr_at_checkpoint", "bullish_in_domain", "bearish_in_domain",
            "bullish_probability", "bearish_probability",
            "seconds_from_regime_start",
        )
        .collect()
    )
    # The in-domain score of whatever regime this row belongs to.
    scores = scores.with_columns(
        in_domain_probability=pl.when(pl.col("bullish_in_domain"))
        .then(pl.col("bullish_probability"))
        .otherwise(pl.col("bearish_probability")),
        host_regime_direction=pl.when(pl.col("bullish_in_domain"))
        .then(pl.lit(1))
        .otherwise(pl.lit(-1)),
    ).filter(pl.col("in_domain_probability").is_not_null())

    win = new.select(
        "new_regime_id", "direction", "side", "entry_year",
        "terminal_label_full", "walk_a_confirm_ns", "full_exit_ns",
        "full_mfe_atr", "arm_atr",
    )
    post = (
        scores.join(win, left_on="regime_id", right_on="new_regime_id", how="inner")
        .filter(
            (pl.col("checkpoint_decision_ns") >= pl.col("walk_a_confirm_ns"))
            & (pl.col("checkpoint_decision_ns") <= pl.col("full_exit_ns"))
        )
    )
    per = post.group_by("regime_id").agg(
        n_obs=pl.len(),
        first_gap_s=((pl.col("checkpoint_decision_ns").min()
                      - pl.col("walk_a_confirm_ns").first()) / NS),
        label=pl.col("terminal_label_full").first(),
    )
    report["post_confirm_observations"] = {
        "trades_with_at_least_one_obs": per.height,
        "trades_with_zero_obs": new.height - per.height,
        "obs_per_trade": {
            "median": float(per["n_obs"].median()),
            "p25": float(per["n_obs"].quantile(0.25)),
            "p75": float(per["n_obs"].quantile(0.75)),
            "p90": float(per["n_obs"].quantile(0.90)),
        },
        "first_obs_delay_s": {
            "median": float(per["first_gap_s"].median()),
            "p25": float(per["first_gap_s"].quantile(0.25)),
            "p75": float(per["first_gap_s"].quantile(0.75)),
            "p90": float(per["first_gap_s"].quantile(0.90)),
        },
        "obs_median_by_label": {
            r["label"]: r["med"]
            for r in per.group_by("label")
            .agg(med=pl.col("n_obs").median(), n=pl.len())
            .iter_rows(named=True)
        },
        "trades_with_ge_3_obs": int((per["n_obs"] >= 3).sum()),
        "trades_with_ge_5_obs": int((per["n_obs"] >= 5).sum()),
        "trades_with_ge_10_obs": int((per["n_obs"] >= 10).sum()),
    }

    # --- Q3 polarity ------------------------------------------------------
    # Does the new regime's in-domain model score OUR trade direction, or the
    # opposite? Compare the host regime's direction against our trade's.
    pol = post.select(
        agree=(pl.col("host_regime_direction") == pl.col("direction")).mean()
    ).item()
    report["polarity"] = {
        "host_regime_direction_equals_trade_direction_rate": round(float(pol), 6),
        "interpretation": (
            "host_regime_direction is the fade direction the in-domain model "
            "implies for the NEW regime. If it never equals our trade direction, "
            "the live post-confirmation score is predicting the END of our own "
            "regime: HIGH score = danger, and 'deterioration' for our position "
            "is the score RISING, not falling."
        ),
    }

    # Empirical separation: mean in-domain score by outcome, early vs late.
    post = post.with_columns(
        elapsed_s=((pl.col("checkpoint_decision_ns") - pl.col("walk_a_confirm_ns")) / NS)
    )
    buckets = post.with_columns(
        bucket=pl.when(pl.col("elapsed_s") <= 60).then(pl.lit("0-60s"))
        .when(pl.col("elapsed_s") <= 180).then(pl.lit("60-180s"))
        .otherwise(pl.lit(">180s"))
    )
    sep = (
        buckets.group_by(["bucket", "terminal_label_full"])
        .agg(n=pl.len(), mean_score=pl.col("in_domain_probability").mean().round(4),
             med_score=pl.col("in_domain_probability").median().round(4))
        .sort(["bucket", "terminal_label_full"])
    )
    report["score_by_outcome_and_elapsed"] = sep.to_dicts()

    # Per-trade summary: does peak/final in-domain score separate C from A+B?
    tsum = post.group_by("regime_id").agg(
        label=pl.col("terminal_label_full").first(),
        score_first=pl.col("in_domain_probability").sort_by("checkpoint_decision_ns").first(),
        score_max=pl.col("in_domain_probability").max(),
        score_last=pl.col("in_domain_probability").sort_by("checkpoint_decision_ns").last(),
        n_obs=pl.len(),
    )
    report["per_trade_score_by_outcome"] = (
        tsum.group_by("label")
        .agg(
            n=pl.len(),
            med_first=pl.col("score_first").median().round(4),
            med_max=pl.col("score_max").median().round(4),
            med_last=pl.col("score_last").median().round(4),
        )
        .sort("n", descending=True)
        .to_dicts()
    )

    (OUT / "phase0_probe.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()

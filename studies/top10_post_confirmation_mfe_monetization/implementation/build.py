"""Assemble the confirmed population, locate P90/P80 events, run every policy."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.candidates import THRESHOLDS
from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, NS, load_market, load_regimes,
)
from .engine import LANDMARKS, PRICE_POLICIES, RUNNER_TIERS, STOP_ATR, walk

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
ARMED = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
OUT = ROOT / "studies/top10_post_confirmation_mfe_monetization/results"

LABELS = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER",
          "FINAL_FLIP_EXIT_WINNER", "SESSION_EXIT")
# One buffer only, derived from observed geometry in Phase 2 (SPEC 4).
BUFFER_ATR = 0.25
# One structural staircase; rungs are broad Phase-2 retracement bands, not tuned.
STAIRSTEP = ((1.0, 1.00), (1.5, 0.75), (2.0, 0.60), (2.5, 0.50))


def confirmed_population() -> pl.DataFrame:
    paths = pl.read_parquet(ARMED).filter(pl.col("valid"))
    reg = (pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
           .select("regime_id", "regime_direction", "regime_start_decision_ns").collect())
    return (
        paths.filter(pl.col("terminal_label_full").is_in(list(LABELS))
                     & pl.col("walk_a_confirm_ns").is_not_null())
        .select("regime_id", "direction", "side", "entry_year",
                terminal_label="terminal_label_full",
                entry_ns="arm_top10_ns", entry_price="arm_price", entry_atr="arm_atr",
                confirm_ns="walk_a_confirm_ns")
        .join(reg.rename({"regime_id": "new_regime_id"}),
              left_on=["confirm_ns", "direction"],
              right_on=["regime_start_decision_ns", "regime_direction"], how="left")
        .drop_nulls("new_regime_id")
    )


def first_events(conf: pl.DataFrame) -> pl.DataFrame:
    """First post-confirmation crossing of the NEW-regime model, streams A and B.

    A crossing is a true dispatch at or above the frozen threshold whose previous
    true dispatch IN THE SAME (new) REGIME was below it. Carry-forward cannot
    contribute: the score table holds one row per real dispatch, and null
    probabilities are dropped before the shift.
    """
    sc = (pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
          .filter(pl.col("session") == "RTH")
          .select("regime_id", "checkpoint_decision_ns", "bullish_in_domain",
                  "bearish_in_domain", "bullish_probability", "bearish_probability")
          .collect())
    j = (sc.join(conf.select("new_regime_id", "direction", "confirm_ns"),
                 left_on="regime_id", right_on="new_regime_id", how="inner")
         .filter(pl.col("checkpoint_decision_ns") >= pl.col("confirm_ns"))
         .with_columns(
             score=pl.when(pl.col("direction") == 1).then(pl.col("bullish_probability"))
                   .otherwise(pl.col("bearish_probability")),
             in_domain=pl.when(pl.col("direction") == 1).then(pl.col("bullish_in_domain"))
                       .otherwise(pl.col("bearish_in_domain")))
         .filter(pl.col("score").is_not_null())
         .sort(["regime_id", "checkpoint_decision_ns"]))
    for lvl in ("top_10", "top_20"):
        b, r = THRESHOLDS[lvl]
        thr = pl.when(pl.col("direction") == 1).then(pl.lit(b)).otherwise(pl.lit(r))
        j = j.with_columns(**{f"ge_{lvl}": pl.col("score") >= thr})
        j = j.with_columns(**{
            f"cross_{lvl}": pl.col(f"ge_{lvl}")
            & ~pl.col(f"ge_{lvl}").shift(1, fill_value=False).over("regime_id")})

    def firsts(cond: pl.Expr, name: str) -> pl.DataFrame:
        return (j.filter(cond).group_by("regime_id")
                .agg(**{name: pl.col("checkpoint_decision_ns").min()}))

    out = conf.select("regime_id", "new_regime_id")
    for name, cond in (
        ("p90a_ns", pl.col("cross_top_10") & pl.col("in_domain")),
        ("p90b_ns", pl.col("cross_top_10")),
        ("p80a_ns", pl.col("cross_top_20") & pl.col("in_domain")),
        ("p80b_ns", pl.col("cross_top_20")),
    ):
        out = out.join(firsts(cond, name).rename({"regime_id": "new_regime_id"}),
                       on="new_regime_id", how="left")
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("loading ...", flush=True)
    market, regimes = load_market(), load_regimes()
    conf = confirmed_population()
    print(f"  confirmed trades: {conf.height:,}", flush=True)
    ev = first_events(conf)
    conf = conf.join(ev.drop("new_regime_id"), on="regime_id", how="left")

    rows = []
    for r in conf.iter_rows(named=True):
        w = walk(market, regimes, r, r.get("p90a_ns"), r.get("p90b_ns"),
                 r.get("p80a_ns"), r.get("p80b_ns"), BUFFER_ATR, STAIRSTEP)
        if w is not None:
            rows.append({**w, "terminal_label": r["terminal_label"],
                         "new_regime_id": r["new_regime_id"]})
    df = pl.DataFrame(rows, infer_schema_length=None)
    df.write_parquet(OUT / "policy_panel.parquet")
    print(f"  wrote policy_panel.parquet ({df.height:,} trades)", flush=True)

    n_entries = int(pl.read_parquet(ARMED).filter(pl.col("valid")).height)
    (OUT / "partition_manifest.json").write_text(json.dumps({
        "study": "top10_post_confirmation_mfe_monetization",
        "original_top10_entries": n_entries,
        "confirmed_trades": df.height,
        "stop_atr": STOP_ATR, "cost_points_round_turn": COST_POINTS,
        "landmarks_from_entry_atr": list(LANDMARKS),
        "runner_tiers_atr": list(RUNNER_TIERS),
        "price_policies": {k: list(v) for k, v in PRICE_POLICIES.items()},
        "p90_price_buffer_atr": BUFFER_ATR,
        "stairstep_rungs_mfe_giveback": [list(x) for x in STAIRSTEP],
        "stream_A": "contract-valid (in-domain) — NOT INTERPRETABLE, SURVIVORSHIP: "
                    "fires on 0.4%/1.0% of losers vs 47.9% of winners",
        "stream_B": "raw causal — EXPLORATORY_OUT_OF_DOMAIN, 97-99.6% coverage",
        "threshold_overlap_disclosure": "2025 is NOT threshold-OOS; waiver "
            "studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json",
    }, indent=2, default=str))


if __name__ == "__main__":
    main()

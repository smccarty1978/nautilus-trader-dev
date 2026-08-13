"""Build the trade panel and the causal landmark-state panel (Phases 0-5, 7, 8, 10)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.candidates import THRESHOLDS
from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, NS, load_market, load_regimes,
)
from .engine import FAST_CUTOFF_S, LANDMARKS_S, STOP_ATR, walk

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
ARMED = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
OUT = ROOT / "studies/top10_fast_confirm_runner_path/results"

CONFIRMED_LABELS = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER",
                    "FINAL_FLIP_EXIT_WINNER", "SESSION_EXIT")
ACCEPTED = {"entries": 8950, "confirmed": 4705, "stopped_before": 4245,
            "pool_per_entry": 0.899, "baseline_per_entry": -0.0742}


def confirmed_population() -> pl.DataFrame:
    """The 4,705 confirmed trades, with the NEW regime resolved at the flip.

    SPEC D2: the <=120 s clock runs from ``arm_top10_ns``, the Top-10 crossing
    decision timestamp, NOT the stored ``walk_a_seconds_to_confirm`` (which
    differs by up to 11 s and whose reference point is not part of this contract).
    """
    paths = pl.read_parquet(ARMED).filter(pl.col("valid"))
    reg = (pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
           .select("regime_id", "regime_direction", "regime_start_decision_ns").collect())
    return (
        paths.filter(pl.col("terminal_label_full").is_in(list(CONFIRMED_LABELS))
                     & pl.col("walk_a_confirm_ns").is_not_null())
        .select("regime_id", "direction", "side", "entry_year",
                terminal_label="terminal_label_full",
                entry_ns="arm_top10_ns", entry_price="arm_price", entry_atr="arm_atr",
                confirm_ns="walk_a_confirm_ns",
                stored_seconds_to_confirm="walk_a_seconds_to_confirm")
        .join(reg.rename({"regime_id": "new_regime_id"}),
              left_on=["confirm_ns", "direction"],
              right_on=["regime_start_decision_ns", "regime_direction"], how="left")
    )


def model_context(fast: pl.DataFrame) -> pl.DataFrame:
    """Phase 10: last TRUE dispatch of the new-regime model at or before each landmark.

    EXPLORATORY_OUT_OF_DOMAIN. Carry-forward is used only to read a level; a
    crossing is never inferred from a carried value, and a landmark with no
    dispatch yields a null that is counted, never imputed.
    """
    sc = (pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
          .filter(pl.col("session") == "RTH")
          .select("regime_id", "checkpoint_decision_ns",
                  "bullish_probability", "bearish_probability")
          .collect()
          .join(fast.select("new_regime_id", "direction", "confirm_ns", "regime_id"),
                left_on="regime_id", right_on="new_regime_id", how="inner",
                suffix="_trade")
          .with_columns(score=pl.when(pl.col("direction") == 1)
                        .then(pl.col("bullish_probability"))
                        .otherwise(pl.col("bearish_probability")))
          .filter(pl.col("score").is_not_null()
                  & (pl.col("checkpoint_decision_ns") >= pl.col("confirm_ns")))
          .sort("checkpoint_decision_ns"))
    if sc.height == 0:
        return pl.DataFrame()

    # score at (and just before) each landmark, per trade
    keys = (fast.select("regime_id", "direction", "confirm_ns")
            .join(pl.DataFrame({"landmark_s": list(LANDMARKS_S)}, schema={"landmark_s": pl.Int64}),
                  how="cross")
            .with_columns(landmark_ns=pl.col("confirm_ns") + pl.col("landmark_s") * NS)
            .sort("landmark_ns"))
    sc = sc.rename({"regime_id_trade": "trade_regime_id"})
    joined = keys.join_asof(
        sc.select("trade_regime_id", "checkpoint_decision_ns", "score")
          .rename({"trade_regime_id": "regime_id"}),
        left_on="landmark_ns", right_on="checkpoint_decision_ns",
        by="regime_id", strategy="backward")

    first = (sc.group_by("trade_regime_id")
             .agg(score_at_confirm=pl.col("score").first())
             .rename({"trade_regime_id": "regime_id"}))
    thr = {lvl: THRESHOLDS[lvl] for lvl in ("top_10", "top_20")}
    return (joined.join(first, on="regime_id", how="left")
            .with_columns(
                delta_score_since_confirm=pl.col("score") - pl.col("score_at_confirm"),
                p90_reached=pl.when(pl.col("direction") == 1)
                    .then(pl.col("score") >= thr["top_10"][0])
                    .otherwise(pl.col("score") >= thr["top_10"][1]),
                p80_reached=pl.when(pl.col("direction") == 1)
                    .then(pl.col("score") >= thr["top_20"][0])
                    .otherwise(pl.col("score") >= thr["top_20"][1]))
            .select("regime_id", "landmark_s", "landmark_ns", "score",
                    "score_at_confirm", "delta_score_since_confirm",
                    "p90_reached", "p80_reached"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("loading market/regimes ...", flush=True)
    market, regimes = load_market(), load_regimes()

    conf = confirmed_population()
    print(f"  confirmed rows: {conf.height:,}", flush=True)

    trades, states = [], []
    dropped = []
    for r in conf.iter_rows(named=True):
        res = walk(market, regimes, r)
        if res is None:
            dropped.append({"regime_id": r["regime_id"],
                            "terminal_label": r["terminal_label"],
                            "entry_year": r["entry_year"]})
            continue
        t, st = res
        t["new_regime_id"] = r["new_regime_id"]
        t["stored_seconds_to_confirm"] = r["stored_seconds_to_confirm"]
        trades.append(t)
        if t["is_fast_confirm"]:
            states.extend(st)

    td = pl.DataFrame(trades, infer_schema_length=None)
    sd = pl.DataFrame(states, infer_schema_length=None)
    td.write_parquet(OUT / "trade_panel.parquet")
    sd.write_parquet(OUT / "time_landmark_states.parquet")
    print(f"  trade_panel: {td.height:,} · landmark states: {sd.height:,}", flush=True)

    fast = td.filter(pl.col("is_fast_confirm"))
    mc = model_context(fast.join(conf.select("regime_id", "new_regime_id"),
                                 on="regime_id", how="left", suffix="_j")
                       .select("regime_id", "new_regime_id", "direction", "confirm_ns"))
    if mc.height:
        mc.write_parquet(OUT / "model_context_raw.parquet")

    armed = pl.read_parquet(ARMED).filter(pl.col("valid"))
    (OUT / "partition_manifest.json").write_text(json.dumps({
        "study": "top10_fast_confirm_runner_path",
        "inputs": {"armed_paths": str(ARMED.relative_to(ROOT)),
                   "store": str(STORE.relative_to(ROOT))},
        "original_top10_entries": int(armed.height),
        "confirmed_rows": int(conf.height),
        "trade_panel_rows": int(td.height),
        "non_measurable_confirmed": len(dropped),
        "non_measurable_by_label": (pl.DataFrame(dropped)["terminal_label"]
                                    .value_counts().to_dicts() if dropped else []),
        "fast_confirm_trades": int(fast.height),
        "landmark_state_rows": int(sd.height),
        "fast_cutoff_seconds": FAST_CUTOFF_S,
        "clock_reference": "arm_top10_ns (SPEC D2)",
        "stop_atr": STOP_ATR,
        "cost_points_round_turn": COST_POINTS,
        "landmarks_s": list(LANDMARKS_S),
        "stop_live_for_economics": True,
        "unconstrained_for_geometry": True,
        "landmark_population": "constant, terminal carry-forward (SPEC D3)",
        "model_score_stream": "raw causal — EXPLORATORY_OUT_OF_DOMAIN",
        "threshold_overlap_disclosure": "2025 is NOT threshold-OOS; waiver "
            "studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json",
        "years": [2021, 2022, 2023, 2024, 2025],
        "note_2026": "untouched",
    }, indent=2, default=str))
    print("  wrote partition_manifest.json", flush=True)


if __name__ == "__main__":
    main()

"""Attach the frozen Walk-A economic labels once to every OOS score event."""
from __future__ import annotations

from pathlib import Path
import json

import polars as pl

from studies.p90_regime_age_progress_diagnostic.implementation import outcomes as O
from studies.Codex_structural_regime_geometry_maturity.implementation.sealed_outcomes import load_engines, load_regime_ends

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/Codex_structural_regime_geometry_maturity/results"
SAMPLE_PER_DECILE = 250


def main() -> None:
    scores = pl.read_parquet(OUT / "oos_scores.parquet")
    group = ["model_set", "direction", "maturity_bucket", "train_score_decile"]
    # The full classification table remains exact.  Walk-A is deliberately expensive,
    # so this is a fixed-seed, stratified diagnostic sample for its economic columns.
    sampled = (scores.with_columns(pl.struct(["regime_id", "checkpoint_decision_ns", "model_set", "direction"]).hash(seed=20_260_814).alias("_sample_hash"))
               .sort(group + ["_sample_hash"])
               .group_by(group, maintain_order=True).head(SAMPLE_PER_DECILE).drop("_sample_hash"))
    event_keys = (
        sampled.with_columns(trade_direction=pl.when(pl.col("direction") == "LONG").then(1).otherwise(-1))
        .select("regime_id", "checkpoint_decision_ns", pl.col("trade_direction").alias("direction"), "checkpoint_reference_price", "atr_at_checkpoint")
        .unique(["regime_id", "checkpoint_decision_ns", "direction"])
    )
    market, regimes = load_engines()
    ends = load_regime_ends()
    outcomes = O.simulate(event_keys, market, regimes, ends, progress_every=500)
    events = event_keys.join(outcomes, on=["regime_id", "checkpoint_decision_ns"], how="left")
    events.write_parquet(OUT / "oos_score_events.parquet")
    joined = sampled.with_columns(trade_direction=pl.when(pl.col("direction") == "LONG").then(1).otherwise(-1)).join(
        events, left_on=["regime_id", "checkpoint_decision_ns", "trade_direction"], right_on=["regime_id", "checkpoint_decision_ns", "direction"], how="left"
    ).with_columns(confirmed=pl.col("confirmed").fill_null(False))
    metrics = (
        joined.group_by(group)
        .agg(
            n=pl.len(),
            p_flip_le_300s=pl.col("label").mean(),
            p_confirm_before_1atr=pl.col("confirmed").mean(),
            median_return_at_confirm_atr=pl.col("return_at_confirm_atr").filter(pl.col("confirmed")).median(),
            median_eventual_opposite_mfe_atr=pl.col("eventual_max_mfe_atr").filter(pl.col("confirmed")).median(),
            p_opposite_mfe_ge_1=pl.col("mfe_ge_1_0").filter(pl.col("confirmed")).mean(),
        )
        .sort("model_set", "direction", "maturity_bucket", "train_score_decile")
    )
    metrics.write_csv(OUT / "oos_decile_economics.csv")
    (OUT / "oos_decile_economics_manifest.json").write_text(json.dumps({"source_score_rows": scores.height, "sampled_score_rows": sampled.height, "sample_per_decile_cap": SAMPLE_PER_DECILE, "sampling": "fixed_seed_hash_stratified_by_model_side_maturity_train_score_decile", "seed": 20260814}, indent=2))
    print({"source_score_rows": scores.height, "sampled_score_rows": sampled.height, "unique_events": event_keys.height, "metrics": metrics.height})


if __name__ == "__main__":
    main()

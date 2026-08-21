"""Phase 1 -- state-at-confirmation freeze (SPEC section 3, 4 Phase 1).

The one new causal computation in this study: 5m regime age/state AT
CONFIRMATION. `p90_classification.parquet` only stored the at-P90 value.
Three existing `Regime5m` method calls at a new timestamp (`walk_a_confirm_ns`
instead of `arm_top10_ns`) -- no new engine code. The causal guarantee
(`close_ts <= walk_a_confirm_ns`) is inherited from the already-parity-tested
`Regime5m.state_at` family (SPEC section 3) and re-verified at this call
site by `tests/test_join_causality.py`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from studies.p90_5m_regime_context.implementation import regime_5m as R5M
from studies.p90_5m_regime_context.implementation.regime_5m import Regime5m
from studies.post_confirm_5m_forward_opportunity.implementation.lineage import (
    load_arms, load_classification, load_panel_trade_ids,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/post_confirm_5m_forward_opportunity/results"


def build_confirmation_state(arms: pl.DataFrame, classification: pl.DataFrame,
                             r5m: Regime5m, panel_ids: set[str]) -> pl.DataFrame:
    """One row per MEASURABLE CONFIRMED trade (4,656)."""
    cls = classification.filter(pl.col("with_5m_at_confirm").is_not_null())
    base = arms.filter(pl.col("regime_id").is_in(list(panel_ids))).select(
        "regime_id", "side", "direction", "entry_year", "arm_score",
        "walk_a_confirm_ns", "walk_a_seconds_to_confirm",
        "walk_a_mae_to_confirm_atr", "walk_a_mfe_to_confirm_atr",
        "walk_a_return_at_confirm_atr", "regime_age_at_arm_s",
    )

    confirm_ns = base["walk_a_confirm_ns"].to_numpy()
    age_s = r5m.age_seconds_at(confirm_ns)
    age_bars = r5m.age_bars_at(confirm_ns)

    base = base.with_columns(
        regime_age_s_at_confirm=pl.Series(age_s),
        regime_age_bars_at_confirm=pl.Series(age_bars),
    )

    state = base.join(
        cls.select("regime_id", "with_5m_at_p90", "with_5m_at_confirm",
                   "regime_age_s_at_p90", "regime_age_bars_at_p90"),
        on="regime_id", how="inner",
    )

    # group_transition/group_stable, identical derivation to lineage.py
    state = state.with_columns(
        transition=pl.when(pl.col("with_5m_at_p90") & pl.col("with_5m_at_confirm"))
        .then(pl.lit("WITH_WITH"))
        .when(pl.col("with_5m_at_p90") & ~pl.col("with_5m_at_confirm"))
        .then(pl.lit("WITH_AGAINST"))
        .when(~pl.col("with_5m_at_p90") & pl.col("with_5m_at_confirm"))
        .then(pl.lit("AGAINST_WITH"))
        .otherwise(pl.lit("AGAINST_AGAINST")),
        group_transition=pl.when(pl.col("with_5m_at_confirm"))
        .then(pl.lit("WITH_5M")).otherwise(pl.lit("AGAINST_5M")),
    )
    state = state.with_columns(
        group_stable=pl.when(pl.col("transition") == "WITH_WITH").then(pl.lit("WITH_5M"))
        .when(pl.col("transition") == "AGAINST_AGAINST").then(pl.lit("AGAINST_5M"))
        .otherwise(None)
    )
    return state


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    arms = load_arms()
    classification = load_classification()
    panel_ids = load_panel_trade_ids()
    r5m = R5M.load()
    state = build_confirmation_state(arms, classification, r5m, panel_ids)

    assert state.height == 4656, f"confirmation_state height {state.height} != 4656"
    bad_causal = int((state["regime_age_s_at_confirm"].fill_nan(0).to_numpy() < 0).sum())
    assert bad_causal == 0, f"{bad_causal} rows have negative regime_age_s_at_confirm"
    n_uninit = int(state["regime_age_s_at_confirm"].is_nan().sum())

    state.write_parquet(OUT / "confirmation_state.parquet")
    print(f"confirmation_state.parquet written -- {state.height} rows, "
          f"{n_uninit} uninitialised-5m-state rows (disclosed, not dropped)")


if __name__ == "__main__":
    main()

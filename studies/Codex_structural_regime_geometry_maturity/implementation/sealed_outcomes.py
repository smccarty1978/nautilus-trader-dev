"""2021-2024-only adapters for the inherited Walk-A outcome implementation."""
from __future__ import annotations

import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import RegimeIndex, load_market

from studies.p90_regime_age_progress_diagnostic.implementation import outcomes as O

SEALED_2025_NS = 1_735_689_600_000_000_000
YEARS = (2021, 2022, 2023, 2024)


def load_engines() -> tuple:
    """Return the inherited path engine restricted before the 2025/2026 seal."""
    market = load_market(years=YEARS)
    regimes = (pl.scan_parquet(O.STORE / "canonical_regimes_all.parquet")
               .filter(pl.col("regime_start_decision_ns") < SEALED_2025_NS)
               .select("regime_start_decision_ns", "regime_direction")
               .sort("regime_start_decision_ns").collect())
    return market, RegimeIndex(start_ns=regimes["regime_start_decision_ns"].to_numpy(), direction=regimes["regime_direction"].to_numpy())


def load_regime_ends() -> pl.DataFrame:
    """Censor a regime that would resolve only after the sealed period begins."""
    return (pl.scan_parquet(O.STORE / "canonical_regimes_all.parquet")
            .filter(pl.col("regime_start_decision_ns") < SEALED_2025_NS)
            .select("regime_id", "regime_start_decision_ns", "regime_end_decision_ns", "regime_end_reason", "regime_direction")
            .with_columns(pl.when(pl.col("regime_end_decision_ns") < SEALED_2025_NS).then(pl.col("regime_end_decision_ns")).otherwise(None).alias("regime_end_decision_ns"))
            .collect())

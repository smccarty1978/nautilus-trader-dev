"""Shared loading, the 2024 seal, and the frozen provenance constants.

Every loader in this study filters ``entry_year == 2024`` at the SOURCE SCAN.
Nothing downstream may widen that: `assert_2024_only` is called on every frame
that leaves this module, and it checks the actual observation timestamps in
America/Chicago, not just the partition column. A partition column can be wrong;
a timestamp cannot.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
STUDY = Path(__file__).resolve().parents[1]
RESULTS = STUDY / "results"

NS = 1_000_000_000
CT = "America/Chicago"
YEAR = 2024
SEALED_YEARS = (2021, 2022, 2023, 2025, 2026)

TICK = 0.25
COST_POINTS = 2 * TICK
FLAT_POINTS = 0.125

# ---------------------------------------------------------------- frozen contract
# SPEC 5.1 / 8.2. None of these is optimisable and none is derived from a result.
RISK_ATR = 0.50
REWARD_ATR = 1.00
HORIZONS_S = (180, 240, 300)
PRIMARY_HORIZON_S = 300

AGE_GATE_S = 600                       # inherited arm contract
RUNGS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
B_FAVOURABLE = (0.50, 1.00)
B_ADVERSE = (0.50, 0.75, 1.00, 1.25)
B_PRIMARY = {"favourable": 0.50, "adverse": 0.75, "horizon_s": 300}

SEED = 20260811
N_BOOT = 1000

GBT_PARAMS = dict(max_depth=3, learning_rate=0.05, max_iter=200, random_state=42)

# Frozen fold calendar (SPEC 7). Half-open on the right.
FOLDS = (
    ("FOLD_1", ("2024-01-01", "2024-07-01"), ("2024-07-01", "2024-10-01")),
    ("FOLD_2", ("2024-01-01", "2024-10-01"), ("2024-10-01", "2025-01-01")),
)

BUCKETS = (("all", 1.00), ("top_50", 0.50), ("top_25", 0.25), ("top_20", 0.20),
           ("top_10", 0.10), ("top_5", 0.05), ("top_2_5", 0.025), ("top_1", 0.01))

# Accepted lineage targets (SPEC 4.2 / 13 V2, V3). Reproduction, not calibration.
ACCEPTED = {
    "p90_candidates_2024": 1771,
    "p90_short_2024": 975,
    "p90_long_2024": 796,
    "b_rung_observations_2024": 2991,
    # 856 is the 2024 MEASURABLE CONFIRMED trade panel; 781 of those reach at
    # least the 1.0 ATR rung and therefore appear in the rung-event population.
    "b_confirmed_trade_panel_2024": 856,
    "b_unique_trades_2024": 781,
    "b_per_rung_2024": {1.0: 781, 1.5: 658, 2.0: 522, 2.5: 426, 3.0: 356, 4.0: 248},
}

PRIMES = ("P80", "P90")
_PERCENTILE_OF_PRIME = {"P80": "top_20", "P90": "top_10"}

# Model ids as they appear in the store. Bullish in-domain => SHORT fade.
BULLISH_MODEL = "BULLISH_STRICT_top25_gbt_v2"
BEARISH_MODEL = "LONG_STRICT_top25_gbt_v2"


# ------------------------------------------------------------------- seal


def assert_2024_only(df: pl.DataFrame, ts_col: str, what: str) -> None:
    """Gate V1. Timestamps, not partition columns, decide the seal."""
    if df.height == 0:
        return
    yrs = (
        df.select(
            pl.from_epoch(pl.col(ts_col), time_unit="ns")
            .dt.convert_time_zone(CT).dt.year().alias("y")
        )["y"].unique().to_list()
    )
    bad = sorted(y for y in yrs if y != YEAR)
    if bad:
        raise AssertionError(
            f"SEAL BREACH in {what}: {ts_col} carries year(s) {bad}; only {YEAR} is permitted"
        )


# --------------------------------------------------------------- provenance


def load_thresholds() -> dict:
    """The frozen prime thresholds, read (never recomputed) from the contract table."""
    t = pl.read_parquet(STORE / "canonical_model_threshold_contracts.parquet")
    out: dict = {"contracts": []}
    for prime, label in _PERCENTILE_OF_PRIME.items():
        for model, side in ((BULLISH_MODEL, "SHORT"), (BEARISH_MODEL, "LONG")):
            row = t.filter(
                (pl.col("model_id") == model) & (pl.col("percentile_label") == label)
            )
            if row.height != 1:
                raise AssertionError(f"threshold contract not unique: {model}/{label}")
            r = row.row(0, named=True)
            out[f"{prime}_{side}"] = float(r["probability_threshold"])
            out["contracts"].append({
                "prime": prime, "percentile_label": label, "model_id": model,
                "fade_side": side,
                "probability_threshold": float(r["probability_threshold"]),
                "upper_tail_fraction": float(r["upper_tail_fraction"]),
                "availability_status": r["availability_status"],
                "is_frozen": bool(r["is_frozen"]),
                "calibration_population_id": r["calibration_population_id"],
                "calibration_start_date": str(r["calibration_start_date"]),
                "calibration_end_date_exclusive": str(r["calibration_end_date_exclusive"]),
                "overlaps_evaluation_window": bool(r["overlaps_evaluation_window"]),
                "waiver_artifact": r["waiver_artifact"],
                "threshold_contract_id": r["threshold_contract_id"],
            })
    return out


# ---------------------------------------------------------------- score rows

_STATE_COLS = [
    "regime_age_seconds", "seconds_from_regime_start", "seconds_from_established",
    "score_sequence_in_regime", "running_mfe_atr", "running_mae_atr",
    "current_progress_atr", "new_progress_windows", "retained_mfe_ratio",
    "established_regime_gate", "atr_at_checkpoint", "reference_price",
    "checkpoint_reference_price", "prevailing_regime", "is_regime_confirmed",
    "regime_start_ns",
]

_ID_COLS = [
    "regime_id", "checkpoint_decision_ns", "checkpoint_availability_ns",
    "score_decision_ns", "score_available_ns", "session", "entry_year",
    "study_month", "bullish_in_domain", "bearish_in_domain",
    "bullish_probability", "bearish_probability",
    "bullish_feature_complete", "bearish_feature_complete",
]


def feature_columns(prefix: str) -> list[str]:
    """The 25 canonical inline features of one model, plus their null flags."""
    import pyarrow.parquet as pq
    names = pq.ParquetFile(STORE / "canonical_regime_scores_all.parquet").schema_arrow.names
    return [n for n in names if n.startswith(f"{prefix}__")]


def load_scores_2024() -> pl.DataFrame:
    """In-domain 2024 score dispatches with both models' inline feature vectors.

    Only in-domain rows are loaded. An out-of-domain row is not an observation of
    either model (the adapter declined to score it), so it can neither create a
    threshold crossing nor contribute to a score-path window -- the accepted arm
    contract, inherited unchanged.
    """
    cols = _ID_COLS + _STATE_COLS + feature_columns("bullish") + feature_columns("bearish")
    df = (
        pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
        .filter(pl.col("entry_year") == YEAR)
        .filter(pl.col("bullish_in_domain") | pl.col("bearish_in_domain"))
        .select(sorted(set(cols)))
        .sort(["regime_id", "checkpoint_decision_ns"])
        .collect()
    )
    assert_2024_only(df, "checkpoint_decision_ns", "canonical scores")
    if df["session"].unique().to_list() != ["RTH"]:
        # Both models are unscored in ETH by construction; assert rather than assume.
        raise AssertionError("in-domain rows outside RTH -- domain contract violated")
    return df


def load_regimes_2024_all() -> pl.DataFrame:
    """Regime starts/directions. NOT year-filtered: the forward walk must be able to
    resolve a confirming or opposing flip that starts after the observation, and a
    2024 observation's flip is always in 2024 or the 2024 session close truncates it.
    Filtering the regime index by year would silently make late-December flips
    invisible and manufacture SESSION terminals."""
    return (
        pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
        .select("regime_id", "regime_sequence_number", "regime_direction",
                "regime_start_decision_ns", "regime_end_decision_ns", "entry_year")
        .sort("regime_start_decision_ns")
        .collect()
    )


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=_default), encoding="utf-8")


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))

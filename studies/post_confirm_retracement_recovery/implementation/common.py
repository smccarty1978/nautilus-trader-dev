"""Frozen constants, population loading, and the statistics every table shares.

Nothing in this module is optimisable. Every threshold that can appear in a
result is a member of one of the grids below (SPEC gate V14), and every grid is
inherited from the accepted predecessor lineage rather than chosen here.

No estimator library may be imported anywhere in this package (SPEC gate V3);
this study trains no model.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parents[1]
RESULTS = STUDY / "results"
STORE = ROOT / "data/canonical/regime_complete_v1"
RATCHET = ROOT / "studies/post_confirm_profit_ratchet/results"
ARMED = ROOT / ("studies/armed_fade_score_path_progression/results"
                "/armed_regime_score_paths.parquet")

STOPPED_BEFORE_CONFIRM = "STOPPED_BEFORE_CONFIRM"
NAT_OPPOSING_FLIP = "OPPOSING_FLIP"

NS = 1_000_000_000
CT = "America/Chicago"

# ---------------------------------------------------------------- frozen grids
RUNGS: tuple[float, ...] = (1.00, 1.50, 2.00, 2.50, 3.00, 4.00)
RETRACEMENTS: tuple[float, ...] = (0.50, 0.75, 1.00, 1.25)
RECOVERY_LEVELS: tuple[str, ...] = ("R25", "R50", "R75", "R100", "NEW_HWM")
# Fraction of DD each level demands. R100/NEW_HWM are absolute reclaims of
# HWM_ARM and are handled separately, so they carry no fraction.
RECOVERY_FRACTION = {"R25": 0.25, "R50": 0.50, "R75": 0.75}
HORIZONS_S: tuple[int, ...] = (15, 30, 60, 120, 180, 300)
CURVE_MAX_S = 300
RUNNER_TIERS: tuple[float, ...] = (3.0, 4.0)
PROGRESS_LOOKBACKS_S: tuple[int, ...] = (15, 30, 60)

COST_POINTS = 0.50                       # 2 ticks round-turn, accepted contract
SEED = 20260811
N_BOOT = 1_000
UNDERPOWERED_TRADES = 20

PLACEBO_OFFSETS_S: tuple[int, ...] = tuple(range(15, 601, 15))
N_PLACEBO = 20

YEARS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)
SEALED_YEARS: tuple[int, ...] = (2020, 2026)

BASIS_POST = "POST_CONFIRM"
PATH_UNC = "UNCONSTRAINED"
PATH_STOP = "STOP_LIVE"

# Arm strata (SPEC 6.3). Exhaustive and mutually exclusive by construction.
ARM_FRESH, ALREADY_AT_D, NO_ARM = "ARM_FRESH", "ALREADY_AT_D", "NO_ARM"

# Frozen failed-recovery states (SPEC 7.3).
FAILED_STATES: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("NO_R25", "R25", (15, 30, 60, 120, 180)),
    ("NO_R50", "R50", (15, 30, 60, 120, 180)),
    ("NO_R75", "R75", (30, 60, 120, 180)),
    ("NO_HWM_RECLAIM", "R100", (30, 60, 120, 180, 300)),
    ("NO_NEW_HWM", "NEW_HWM", (30, 60, 120, 180, 300)),
)

# ---------------------------------------------------------- accepted lineage
# studies/post_confirm_profit_ratchet/REPORT.md sections 1 and 2.
ACCEPTED = {
    "entries": 8950,
    "confirmed": 4705,
    "stopped_before_confirm": 4245,
    "measurable_confirmed": 4656,
    "non_measurable": 49,
    "pool_per_entry": 0.89808,
    "baseline_net_per_entry": -0.07653,
    "trades_reaching_1atr": 4160,
    "rung_events_post_confirm": 15220,
}
ACCEPTED_PER_RUNG = {1.0: 4160, 1.5: 3358, 2.0: 2692, 2.5: 2134, 3.0: 1742,
                     4.0: 1134}
# Tolerances: counts are exact, ATR aggregates match to the published d.p.
TOL_ATR = 5e-5


def tag(x: float) -> str:
    """`0.75 -> '0_75'`. Stable, filename- and column-safe cell labels."""
    return str(x).replace(".", "_")


def first(mask: np.ndarray) -> int:
    """Index of the first True, or -1. The only search primitive in this study."""
    hit = np.flatnonzero(mask)
    return int(hit[0]) if hit.size else -1


# --------------------------------------------------------------- population


def load_rung_events(year_filter: tuple[int, ...] = YEARS) -> pl.DataFrame:
    """The accepted POST_CONFIRM rung population, imported and never re-derived.

    The seal is applied at the SOURCE SCAN. Nothing downstream may widen it, and
    `assert_sealed` re-checks the actual timestamps rather than trusting the
    `entry_year` partition column -- a partition column can be wrong, a timestamp
    cannot.
    """
    ev = (pl.read_parquet(RATCHET / "rung_events.parquet")
          .filter((pl.col("basis") == BASIS_POST)
                  & pl.col("entry_year").is_in(list(year_filter)))
          .sort(["regime_id", "rung_atr"]))
    assert_sealed(ev, "entry_ns", "rung_events")
    assert_sealed(ev, "rung_ts", "rung_events")
    return ev


def load_armed_panel() -> pl.DataFrame:
    """The accepted 8,950-row ARMED entry panel -- the Phase 0 denominator.

    This is the population the entry rule actually produces. `confirmed_population()`
    filters to confirmed labels by construction and can therefore never supply the
    original-entry count or the stopped-before-confirm cohort; reading it as if it
    could is what made Phase 0 report 4,705 entries and 0 stopped trades.
    """
    a = pl.read_parquet(ARMED).filter(pl.col("valid"))
    assert_sealed(a, "arm_top10_ns", "armed_panel")
    return a


def load_trade_panel(year_filter: tuple[int, ...] = YEARS) -> pl.DataFrame:
    """The accepted 4,656-row measurable-confirmed trade panel."""
    t = (pl.read_parquet(RATCHET / "trade_panel.parquet")
         .filter(pl.col("entry_year").is_in(list(year_filter))))
    assert_sealed(t, "entry_ns", "trade_panel")
    return t


def assert_sealed(df: pl.DataFrame, ts_col: str, what: str) -> None:
    """Gate V1. Timestamps in America/Chicago decide the seal, not partitions."""
    if df.height == 0:
        return
    yrs = (df.select(pl.from_epoch(pl.col(ts_col), time_unit="ns")
                     .dt.convert_time_zone(CT).dt.year().alias("y"))["y"]
           .unique().drop_nulls().to_list())
    bad = sorted(y for y in yrs if y not in YEARS)
    if bad:
        raise AssertionError(
            f"SEAL BREACH in {what}: {ts_col} carries year(s) {bad}; "
            f"only {YEARS} is permitted (2026 is sealed and never read)")


# --------------------------------------------------------------- statistics


def trade_clustered_ci(values: np.ndarray, trades: np.ndarray, *,
                       seed: int = SEED,
                       n_boot: int = N_BOOT) -> tuple[float | None, float | None]:
    """Trade-clustered bootstrap CI, identical in construction to the predecessor.

    Resamples unique TRADES with replacement and concatenates each drawn trade's
    observations, so a trade contributing six rung-cells contributes all six or
    none. Observations within a trade are not independent -- they are the same
    path measured at different depths -- and an observation-level bootstrap would
    understate the interval by roughly the square root of that multiplicity.
    """
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return None, None
    uniq, inv = np.unique(np.asarray(trades), return_inverse=True)
    if uniq.size < UNDERPOWERED_TRADES:
        # SPEC 5 / §9: a bootstrap over a handful of clusters resamples the same
        # few trades and yields an interval that looks like evidence without
        # being any. Emitted NULL with the count left visible.
        return None, None
    rng = np.random.default_rng(seed)
    # The mean of a concatenation of drawn clusters is sum(drawn sums) over
    # sum(drawn counts), so the per-cluster (sum, count) pair is a sufficient
    # statistic and the draw never has to materialise the concatenation. This is
    # exactly the estimator the predecessor computed by concatenating arrays --
    # asserted equal in tests/test_bootstrap_equivalence.py -- and it is what
    # makes 6,720 bootstrapped cells finish in minutes rather than hours.
    m = uniq.size
    sums = np.bincount(inv, weights=values, minlength=m)
    counts = np.bincount(inv, minlength=m).astype(float)
    pick = rng.integers(0, m, size=(n_boot, m))
    draws = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    return float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))


def quantiles(values: np.ndarray, n_trades: int,
              qs: tuple[float, ...] = (0.25, 0.50, 0.75, 0.90)) -> dict:
    """Named quantiles, suppressed to NULL when the cell is underpowered."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    out = {f"p{int(q * 100)}": None for q in qs}
    if values.size == 0 or n_trades < UNDERPOWERED_TRADES:
        return out
    for q in qs:
        out[f"p{int(q * 100)}"] = float(np.quantile(values, q))
    return out


def is_underpowered(n_trades: int) -> bool:
    return int(n_trades) < UNDERPOWERED_TRADES


def write_csv(df: pl.DataFrame, name: str) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / name
    df.write_csv(p)
    return p


def write_parquet(df: pl.DataFrame, name: str) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / name
    df.write_parquet(p)
    return p

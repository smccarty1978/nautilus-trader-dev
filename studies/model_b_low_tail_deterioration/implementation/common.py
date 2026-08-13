"""Frozen-artifact loading, cut construction, and economics for the low-tail forensic.

Everything here reads the ACCEPTED result artifacts of
`studies/p80_p90_opportunity_continuation_ml/results/`. Nothing is refit, and no
estimator is ever constructed (gate V3). The one exception to "frozen artifacts only"
is the Phase-7 timing re-derivation, which lives in `timing.py` and is gated by V7.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "studies" / "p80_p90_opportunity_continuation_ml" / "results"
RESULTS = Path(__file__).resolve().parents[1] / "results"

# --- frozen constants, all inherited from the predecessor -------------------------
COST_POINTS = 0.50
SEED = 20260811
N_BOOT = 1_000
PRIMARY_TARGET = "lab_f050_a075_300"

# SPEC 5. Terciles of seconds_since_confirm over the FULL 2,991-row frame, matching
# run_study.py:570. Frozen as literals so the OOS subset can never move them.
SINCECONF_Q1 = 10.0
SINCECONF_Q2 = 194.0

# SPEC 4.1 -- nested cuts, as fractions of the population, ranked LOW score first.
NESTED_CUTS: tuple[float, ...] = (1.00, 0.50, 0.40, 0.30, 0.25, 0.20,
                                  0.15, 0.10, 0.075, 0.05, 0.025)
# SPEC 4.2 -- the disjoint bands the monotonicity gate actually reads.
DISJOINT_BANDS: tuple[tuple[int, int], ...] = tuple(
    (lo, lo + 10) for lo in range(0, 100, 10))

ADVERSE_LEVELS: tuple[float, ...] = (0.50, 0.75, 1.00, 1.25)
HORIZONS_S: tuple[int, ...] = (180, 240, 300)

UNDERPOWERED_TRADES = 20


def cut_name(frac: float) -> str:
    """`0.10 -> 'bottom_10'`, `1.00 -> 'ALL'`. Stable labels for every table."""
    if frac >= 1.0:
        return "ALL"
    pct = frac * 100
    txt = f"{pct:g}".replace(".", "_")
    return f"bottom_{txt}"


def load() -> pd.DataFrame:
    """The 1,410-row OOS analysis population, plus the full frame for provenance.

    Returns the OOS rows only. `load_full()` returns all 2,991 for Phase 0.
    """
    d = load_full()
    return d[d["has_oos"]].reset_index(drop=True)


def load_full() -> pd.DataFrame:
    obs = pd.read_parquet(SRC / "model_b_observations.parquet")
    lab = pd.read_parquet(SRC / "model_b_forward_labels.parquet")
    prd = pd.read_parquet(SRC / "model_b_oos_predictions.parquet")

    key = ["regime_id", "rung_ts", "rung_atr"]
    # `suffixes` guards against a silent column collision between the three frozen
    # frames; any duplicated name is kept under `_lab`/`_prd` and never used.
    d = obs.merge(lab, on=key, how="inner", suffixes=("", "_lab"))
    d = d.merge(prd[key + ["oos_prob", "oos_fold", "has_oos"]], on=key, how="inner")
    if len(d) != len(obs):
        raise AssertionError(f"join changed row count: {len(obs)} -> {len(d)}")

    # SPEC 3. Both exit bases, computed once, used everywhere.
    cost = COST_POINTS / d["entry_atr"]
    d["cost_atr"] = cost
    d["exit_now_hwm_atr"] = d["current_mfe_atr"] - cost
    d["exit_now_mark_atr"] = d["return_from_entry_atr"] - cost
    d["continue_atr"] = d["nat_terminal_return_atr"] - cost
    # Cost cancels in both differences: one exit is taken either way.
    d["cme_hwm"] = d["nat_terminal_return_atr"] - d["current_mfe_atr"]
    d["cme_mark"] = d["nat_terminal_return_atr"] - d["return_from_entry_atr"]

    d["sinceconf_stratum"] = np.where(
        d["seconds_since_confirm"] <= SINCECONF_Q1, "SINCECONF_T1",
        np.where(d["seconds_since_confirm"] <= SINCECONF_Q2,
                 "SINCECONF_T2", "SINCECONF_T3"))
    return d


def assert_2024_seal(d: pd.DataFrame) -> None:
    """Gate V1. Every observation timestamp lands inside calendar-2024 CT."""
    ts = pd.to_datetime(d["rung_ts"], unit="ns", utc=True).dt.tz_convert("America/Chicago")
    if not ((ts.dt.year == 2024).all()):
        bad = ts[ts.dt.year != 2024]
        raise AssertionError(f"V1 seal breach: {len(bad)} rows outside 2024, e.g. {bad.iloc[0]}")


# --- cut construction --------------------------------------------------------------

def low_rank(prob: np.ndarray) -> np.ndarray:
    """Ascending-score order. Stable sort, mirroring the predecessor's tie handling."""
    return np.argsort(prob, kind="stable")


def nested_mask(prob: np.ndarray, frac: float) -> np.ndarray:
    """Boolean mask for the lowest-scoring `frac` of the supplied population."""
    n = prob.size
    k = n if frac >= 1.0 else max(1, int(round(frac * n)))
    m = np.zeros(n, dtype=bool)
    m[low_rank(prob)[:k]] = True
    return m


def band_mask(prob: np.ndarray, lo_pct: int, hi_pct: int) -> np.ndarray:
    """Boolean mask for the disjoint percentile band `[lo_pct, hi_pct)` of score.

    The last band is closed on the right so the ten bands partition the population
    exactly (gate V5).
    """
    n = prob.size
    order = low_rank(prob)
    lo = int(round(lo_pct / 100 * n))
    hi = n if hi_pct >= 100 else int(round(hi_pct / 100 * n))
    m = np.zeros(n, dtype=bool)
    m[order[lo:hi]] = True
    return m


# --- statistics --------------------------------------------------------------------

def trade_clustered_ci(values: np.ndarray, trades: np.ndarray,
                       seed: int = SEED, n_boot: int = N_BOOT) -> tuple[float, float]:
    """Trade-clustered bootstrap CI, bit-identical to the predecessor's gate B-4.

    Resamples unique trades with replacement and concatenates each drawn trade's
    observations, so a trade contributing six rungs contributes all six or none.
    """
    if values.size == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(trades, return_inverse=True)
    parts = [values[inv == i] for i in range(uniq.size)]
    draws = np.array([
        np.concatenate([parts[i] for i in rng.integers(0, uniq.size, uniq.size)]).mean()
        for _ in range(n_boot)])
    return float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))


def spearman(y: np.ndarray) -> tuple[float | None, int]:
    """Rank correlation of `y` against its own index, plus a step-inversion count.

    Index 0 is the most severe (lowest-score) band. A genuine deterioration curve is
    INCREASING in index -- worst economics at index 0 -- so a positive coefficient is
    the deterioration direction. Orientation is pinned by
    `tests/test_gate_orientation.py`; the predecessor shipped this backwards once.
    """
    y = np.asarray(y, dtype=float)
    ok = ~np.isnan(y)
    if ok.sum() < 3:
        return None, 0
    y = y[ok]
    x = np.arange(y.size, dtype=float)
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    sd = rx.std() * ry.std()
    rho = float(np.mean((rx - rx.mean()) * (ry - ry.mean())) / sd) if sd else None
    inversions = int((np.diff(y) < 0).sum())
    return rho, inversions


def auc(score: np.ndarray, label: np.ndarray) -> float | None:
    """Rank AUC of `score` against a binary `label`, ties averaged. No sklearn import,
    because gate V3 forbids an estimator library anywhere in this package."""
    y = np.asarray(label, dtype=float)
    if y.size == 0 or y.min() == y.max():
        return None
    r = pd.Series(np.asarray(score, dtype=float)).rank().to_numpy()
    n1 = y.sum()
    n0 = y.size - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n0 * n1))


# --- the metric block emitted for every cut ------------------------------------------

def metrics(d: pd.DataFrame, mask: np.ndarray, *, cut: str, scope: str,
            cut_basis: str = "WITHIN_SCOPE", pop_obs: int | None = None,
            pop_trades: int | None = None, target: str = PRIMARY_TARGET,
            with_ci: bool = True) -> dict:
    """SPEC 5. One row of the standard economics block."""
    s = d[mask]
    n = len(s)
    pop_obs = pop_obs if pop_obs is not None else len(d)
    pop_trades = pop_trades if pop_trades is not None else d["regime_id"].nunique()
    row: dict = {
        "cut": cut, "scope": scope, "cut_basis": cut_basis,
        "n_obs": n, "n_unique_trades": int(s["regime_id"].nunique()) if n else 0,
        "pct_obs_retained": 100.0 * n / pop_obs if pop_obs else None,
    }
    row["pct_trades_touched"] = (100.0 * row["n_unique_trades"] / pop_trades
                                 if pop_trades else None)
    row["underpowered"] = bool(row["n_unique_trades"] < UNDERPOWERED_TRADES)
    if n == 0:
        row["reason"] = "EMPTY_CELL"
        return row

    lab = s[target].to_numpy()
    row.update({
        "mean_model_score": float(s["oos_prob"].mean()),
        "score_boundary": float(s["oos_prob"].max()),
        "continuation_success_pct": 100.0 * float((lab == "FAVOURABLE").mean()),
        "favourable_pct": 100.0 * float((lab == "FAVOURABLE").mean()),
        "adverse_pct": 100.0 * float((lab == "ADVERSE").mean()),
        "timeout_pct": 100.0 * float((lab == "TIMEOUT").mean()),
        "exit_now_hwm_atr": float(s["exit_now_hwm_atr"].mean()),
        "exit_now_mark_atr": float(s["exit_now_mark_atr"].mean()),
        "continue_atr": float(s["continue_atr"].mean()),
        "continue_minus_exit_hwm_atr": float(s["cme_hwm"].mean()),
        "continue_minus_exit_mark_atr": float(s["cme_mark"].mean()),
        "fwd_mfe_300_mean": float(s["fwd_mfe_300"].mean()),
        "fwd_mae_300_mean": float(s["fwd_mae_300"].mean()),
        "nat_terminal_return_atr_mean": float(s["nat_terminal_return_atr"].mean()),
        "mean_rung": float(s["rung_atr"].mean()),
        "median_seconds_since_confirm": float(s["seconds_since_confirm"].median()),
    })
    if with_ci:
        # SPEC 8: a quantile over fewer than UNDERPOWERED_TRADES unique trades is
        # emitted NULL with the count left visible. A trade-clustered bootstrap over
        # ~17 clusters resamples the same handful of trades and produces an interval
        # that looks like evidence without being any; publishing it invites exactly
        # the over-reading this study exists to prevent.
        tr = s["regime_id"].to_numpy()
        for base in ("mark", "hwm"):
            if row["underpowered"]:
                lo = hi = None
            else:
                lo, hi = trade_clustered_ci(s[f"cme_{base}"].to_numpy(), tr)
            row[f"ci95_lo_{base}"], row[f"ci95_hi_{base}"] = lo, hi
        row["ci_suppressed_underpowered"] = bool(row["underpowered"])
    return row


def curve(d: pd.DataFrame, *, scope: str, cuts=NESTED_CUTS, bands=DISJOINT_BANDS,
          target: str = PRIMARY_TARGET, with_ci: bool = True,
          prob: np.ndarray | None = None) -> list[dict]:
    """Nested cuts followed by the disjoint bands, for one scope."""
    p = d["oos_prob"].to_numpy() if prob is None else prob
    rows = [metrics(d, nested_mask(p, f), cut=cut_name(f), scope=scope,
                    target=target, with_ci=with_ci) for f in cuts]
    rows += [metrics(d, band_mask(p, lo, hi), cut=f"band_{lo}_{hi}", scope=scope,
                     cut_basis="DISJOINT_BAND", target=target, with_ci=with_ci)
             for lo, hi in bands]
    return rows

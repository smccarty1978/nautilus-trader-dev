"""Validation gates V1-V14 and the frozen advancement gates.

Gates V7/V8 are not assertions about the code -- they are HARD-TRUNCATED REPLAYS.
The store is physically cut at the decision second and the quantity is rebuilt
from what remains. A feature that survives the cut could not have read the
future; a label that survives the removal of everything at or before the cut
could not have read the past. Reasoning about the code is what misses these.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import MarketData

from .common import BUCKETS, HORIZONS_S, N_BOOT, SEED
from .features import PathContext, ScoreHistory, score_state


def _truncated_market(m: MarketData, hi_ns: int | None = None,
                      lo_ns: int | None = None) -> MarketData:
    keep = np.ones(m.n, dtype=bool)
    if hi_ns is not None:
        keep &= m.ts <= hi_ns
    if lo_ns is not None:
        keep &= m.ts > lo_ns
    return MarketData(ts=m.ts[keep], open_=m.open_[keep], high=m.high[keep],
                      low=m.low[keep], close=m.close[keep],
                      day_close_ns=m.day_close_ns[keep])


def replay_features(market, scores: pl.DataFrame, hist: ScoreHistory,
                    cand: pl.DataFrame, cfeat: pl.DataFrame, thresholds: dict,
                    n: int = 300, seed: int = SEED) -> dict:
    """Gate V7. Rebuild FAM_PATH and FAM_STATE with the store cut AT the decision
    second, and require bit-equality with what the study stored.

    BOTH time bases are physically truncated. Re-using the production
    `ScoreHistory` here would make the STATE half a self-consistency tautology
    that still reports `passed` if `score_state`'s boundary silently regressed --
    the market half would be a real replay and the score half would not. The
    dispatch rows are therefore filtered to `score_decision_ns <= t0` and a fresh
    ScoreHistory is built from what survives.
    """
    rng = np.random.default_rng(seed)
    idx = rng.choice(cand.height, size=min(n, cand.height), replace=False)
    stored = cfeat.to_dicts()
    key = {(r["regime_id"], r["prime_type"], r["candidate_ns"]): r for r in stored}
    checked = mismatches = quantities = 0
    examples = []
    for i in idx:
        c = cand.row(int(i), named=True)
        t0 = int(c["candidate_ns"])
        tm = _truncated_market(market, hi_ns=t0)
        pc = PathContext(tm)
        got = pc.features(t0, int(c["direction"]), float(c["frozen_atr"]),
                          c.get("regime_start_ns"))
        cut = scores.filter((pl.col("regime_id") == c["regime_id"])
                            & (pl.col("score_decision_ns") <= t0))
        thist = ScoreHistory(cut)
        got.update(score_state(thist, c["regime_id"], t0, thresholds, c["side"]))
        exp = key[(c["regime_id"], c["prime_type"], t0)]
        checked += 1
        for k, v in got.items():
            if k not in exp:
                continue
            quantities += 1
            a, b = exp[k], v
            if a is None and b is None:
                continue
            if a is None or b is None or not np.isclose(float(a), float(b),
                                                        rtol=0, atol=1e-9):
                mismatches += 1
                if len(examples) < 5:
                    examples.append({"regime_id": c["regime_id"], "field": k,
                                     "stored": a, "replayed": b})
    return {"observations_checked": checked, "quantities_checked": quantities,
            "mismatches": mismatches, "examples": examples,
            "passed": mismatches == 0 and checked >= 250 and quantities >= 6 * 250}


def replay_labels(market, regimes, cand: pl.DataFrame, labels: pl.DataFrame,
                  n: int = 300, seed: int = SEED) -> dict:
    """Gate V8. Delete every bar at or before the decision second and require the
    forward labels to be unchanged -- proof the window never reaches backwards."""
    from .labels_a import walk_candidate
    rng = np.random.default_rng(seed + 1)
    idx = rng.choice(cand.height, size=min(n, cand.height), replace=False)
    key = {(r["regime_id"], r["prime_type"], r["candidate_ns"]): r
           for r in labels.to_dicts()}
    fields = ([f"label_{H}" for H in HORIZONS_S] + [f"mfe_{H}" for H in HORIZONS_S]
              + [f"mae_{H}" for H in HORIZONS_S] + ["eventual_mfe_atr",
                                                    "terminal_regime_outcome"])
    checked = mismatches = quantities = 0
    examples = []
    for i in idx:
        c = cand.row(int(i), named=True)
        t0 = int(c["candidate_ns"])
        tm = _truncated_market(market, lo_ns=t0)
        got = walk_candidate(tm, regimes, c)
        exp = key[(c["regime_id"], c["prime_type"], t0)]
        if got is None:
            mismatches += 1
            continue
        checked += 1
        for f in fields:
            quantities += 1
            a, b = exp.get(f), got.get(f)
            same = (a == b if isinstance(a, str) else
                    (a is None and b is None) or
                    (a is not None and b is not None
                     and np.isclose(float(a), float(b), rtol=0, atol=1e-9)))
            if not same:
                mismatches += 1
                if len(examples) < 5:
                    examples.append({"regime_id": c["regime_id"], "field": f,
                                     "stored": a, "replayed": b})
    return {"observations_checked": checked, "quantities_checked": quantities,
            "mismatches": mismatches, "examples": examples,
            "passed": mismatches == 0 and checked >= 250}


def session_containment(market, cand: pl.DataFrame, labels: pl.DataFrame) -> dict:
    """Gate V9. Every label window lies inside the candidate's own RTH session."""
    ts = market.ts
    dc = market.day_close_ns
    bad = 0
    for r in labels.iter_rows(named=True):
        t0 = int(r["candidate_ns"])
        i = int(np.searchsorted(ts, t0, side="right"))
        if i >= ts.size:
            continue
        close_ns = int(dc[i])
        last = t0 + int(r["n_forward_bars_unconstrained"]) * 1_000_000_000
        if last > close_ns + 1_000_000_000:
            bad += 1
    return {"windows_checked": labels.height, "windows_leaving_session": bad,
            "passed": bad == 0}


def bucket_edges(p: np.ndarray, mask: np.ndarray, frac: float, top: bool = True):
    idx = np.flatnonzero(mask & ~np.isnan(p))
    if idx.size == 0:
        return np.zeros(p.size, dtype=bool)
    order = idx[np.argsort(-p[idx] if top else p[idx], kind="stable")]
    k = max(1, int(round(frac * order.size)))
    sel = np.zeros(p.size, dtype=bool)
    sel[order[:k]] = True
    return sel


def boot_mean_ci(v: np.ndarray, groups=None, n=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    if v.size == 0:
        return (None, None)
    if groups is None:
        d = rng.choice(v, size=(n, v.size), replace=True).mean(axis=1)
    else:
        u, inv = np.unique(groups, return_inverse=True)
        parts = [v[inv == i] for i in range(u.size)]
        d = np.array([np.concatenate([parts[i] for i in rng.integers(0, u.size, u.size)]).mean()
                      for _ in range(n)])
    return (float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975)))

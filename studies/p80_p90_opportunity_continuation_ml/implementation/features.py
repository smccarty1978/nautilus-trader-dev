"""Causal feature construction. Nothing here may read past the decision second.

Two independent time bases, and both are bounded above:

* SCORE state reads true in-domain dispatches with ``score_decision_ns <= t0``.
  Windowed statistics use the dispatches that actually fell inside the window; an
  empty window yields null. Nothing is forward-filled -- a carried-forward score
  is not an observation, and imputing one manufactures a trajectory.
* PATH state reads 1s bars with ``path_init_ns <= t0``. Raw bars are open-labelled
  ``[t, t+1s)``, so a bar with ``path_init_ns == t0`` COMPLETED at t0 and is
  legitimately known; the still-forming bar has ``path_init_ns == t0 + 1s`` and is
  excluded by construction. This is the corrected convention of the v2 artifacts.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from .common import BULLISH_MODEL, NS, feature_columns

SCORE_WINDOWS_S = (5, 15, 30, 60)
SLOPE_WINDOWS_S = (15, 30, 60)
RANGE_WINDOWS_S = (30, 60)
PATH_SHORT_S = (15, 30, 60)
PATH_LONG_S = (60, 300)

MARKET_FEATURES = [c.removeprefix("bullish__") for c in feature_columns("bullish")]

FAM_REGIME_COLS = [
    "regime_age_seconds", "seconds_from_regime_start", "seconds_from_established",
    "score_sequence_in_regime", "running_mfe_atr", "running_mae_atr",
    "current_progress_atr", "new_progress_windows", "retained_mfe_ratio",
    "established_regime_gate", "atr_at_checkpoint",
]


class ScoreHistory:
    """Per-regime in-domain dispatch series, plus a global per-model index.

    The global index exists only for Model B, whose observations live in the
    regime AFTER the one that was scored at entry. Every global lookup is guarded
    by a regime-id equality check so a stale dispatch from an unrelated earlier
    regime can never be presented as current state.
    """

    def __init__(self, scores: pl.DataFrame):
        self.by_regime: dict[str, dict] = {}
        self.global_: dict[str, dict] = {}
        for dom, prob, model in (
            ("bullish_in_domain", "bullish_probability", "BULLISH"),
            ("bearish_in_domain", "bearish_probability", "BEARISH"),
        ):
            sub = (scores.filter(pl.col(dom) & pl.col(prob).is_not_null())
                   .sort("score_decision_ns"))
            self.global_[model] = {
                "ns": sub["score_decision_ns"].to_numpy(),
                "p": sub[prob].to_numpy(),
                "rid": np.asarray(sub["regime_id"].to_list(), dtype=object),
            }
            for rid, blk in sub.group_by("regime_id"):
                key = rid[0] if isinstance(rid, tuple) else rid
                b = blk.sort("score_decision_ns")
                self.by_regime[key] = {
                    "ns": b["score_decision_ns"].to_numpy(),
                    "p": b[prob].to_numpy(),
                    "model": model,
                }

    def series(self, regime_id: str):
        return self.by_regime.get(regime_id)

    def latest_global(self, model: str, t0: int, regime_id: str,
                      max_age_s: float = 300.0):
        """Last dispatch of `model` at or before t0, in `regime_id`, not too stale."""
        g = self.global_[model]
        i = int(np.searchsorted(g["ns"], t0, side="right")) - 1
        if i < 0 or g["rid"][i] != regime_id:
            return None
        age = (t0 - int(g["ns"][i])) / NS
        if age > max_age_s:
            return None
        return float(g["p"][i]), age, i, g


def _slope(x_s: np.ndarray, y: np.ndarray) -> float | None:
    if x_s.size < 2 or np.ptp(x_s) == 0:
        return None
    return float(np.polyfit(x_s, y, 1)[0])


def score_state(hist: ScoreHistory, regime_id: str, t0: int, thresholds: dict,
                side: str, prefix: str = "") -> dict:
    """Score trajectory over dispatches at or before t0, within this regime."""
    out: dict = {}
    s = hist.series(regime_id)
    if s is None:
        return out
    ns, p = s["ns"], s["p"]
    i = int(np.searchsorted(ns, t0, side="right")) - 1
    if i < 0:
        return out
    now = float(p[i])
    out[f"{prefix}score_now"] = now
    out[f"{prefix}score_age_s"] = float((t0 - int(ns[i])) / NS)
    out[f"{prefix}distance_above_P80"] = now - thresholds[f"P80_{side}"]
    out[f"{prefix}distance_above_P90"] = now - thresholds[f"P90_{side}"]
    out[f"{prefix}above_P80"] = bool(now >= thresholds[f"P80_{side}"])
    out[f"{prefix}above_P90"] = bool(now >= thresholds[f"P90_{side}"])

    for W in SCORE_WINDOWS_S:
        j = int(np.searchsorted(ns, t0 - W * NS, side="left"))
        seg = p[j:i + 1]
        out[f"{prefix}score_change_{W}s"] = float(now - seg[0]) if seg.size >= 2 else None
        out[f"{prefix}n_dispatches_{W}s"] = int(seg.size)
    for W in SLOPE_WINDOWS_S:
        j = int(np.searchsorted(ns, t0 - W * NS, side="left"))
        seg, segt = p[j:i + 1], (ns[j:i + 1] - t0) / NS
        out[f"{prefix}score_slope_{W}s"] = _slope(segt, seg)
    for W in RANGE_WINDOWS_S:
        j = int(np.searchsorted(ns, t0 - W * NS, side="left"))
        seg = p[j:i + 1]
        if seg.size:
            out[f"{prefix}score_max_{W}s"] = float(seg.max())
            out[f"{prefix}score_min_{W}s"] = float(seg.min())
            out[f"{prefix}score_range_{W}s"] = float(seg.max() - seg.min())

    gaps = np.diff(ns[:i + 1]) / NS
    out[f"{prefix}median_dispatch_gap_s"] = float(np.median(gaps)) if gaps.size else None

    # Crossing history WITHIN this regime, strictly at or before t0.
    for lvl in ("P80", "P90"):
        thr = thresholds[f"{lvl}_{side}"]
        q = p[:i + 1] >= thr
        cross = np.flatnonzero(q[1:] & ~q[:-1]) + 1
        out[f"{prefix}n_{lvl}_crossings"] = int(cross.size)
        if q.any():
            first = int(np.flatnonzero(q)[0])
            out[f"{prefix}seconds_since_{lvl}"] = float((t0 - int(ns[first])) / NS)
        else:
            out[f"{prefix}seconds_since_{lvl}"] = None
    out[f"{prefix}n_recent_prime_crossings"] = (
        (out.get(f"{prefix}n_P80_crossings") or 0) + (out.get(f"{prefix}n_P90_crossings") or 0)
    )
    return out


class PathContext:
    """1s price-path features from COMPLETED bars only."""

    def __init__(self, market):
        self.m = market

    def features(self, t0: int, d: int, atr: float, anchor_ns: int | None,
                 anchor_label: str = "regime_start") -> dict:
        """`anchor_ns` is the reference point for the cumulative-excursion feature:
        the regime start for Model A, the trade entry for Model B. The emitted
        column name follows `anchor_label` so the two are never confused."""
        m = self.m
        i = int(np.searchsorted(m.ts, t0, side="right")) - 1
        out: dict = {}
        if i < 0:
            return out
        # Never cross the overnight gap: clamp the lookback to this session.
        sess_lo = int(np.searchsorted(m.day_close_ns, m.day_close_ns[i], side="left"))
        px = float(m.close[i])
        out["path_bars_available"] = int(i - sess_lo + 1)

        for W in PATH_SHORT_S:
            j = max(int(np.searchsorted(m.ts, t0 - W * NS, side="left")), sess_lo)
            if j > i:
                continue
            ret = (float(m.close[i]) - float(m.close[j])) * d / atr
            out[f"ret_{W}s_atr"] = ret
            seg = m.close[j:i + 1]
            if seg.size >= 3:
                out[f"realized_vol_{W}s_atr"] = float(np.std(np.diff(seg)) / atr)
            out[f"bar_range_{W}s_atr"] = float(
                (m.high[j:i + 1].max() - m.low[j:i + 1].min()) / atr)

        for W in PATH_LONG_S:
            j = max(int(np.searchsorted(m.ts, t0 - W * NS, side="left")), sess_lo)
            if j > i:
                continue
            hi = float(m.high[j:i + 1].max())
            lo = float(m.low[j:i + 1].min())
            out[f"dist_from_high_{W}s_atr"] = (hi - px) * (-d) / atr
            out[f"dist_from_low_{W}s_atr"] = (px - lo) * (-d) / atr
            seg = m.close[j:i + 1]
            if seg.size >= 2:
                gross = float(np.abs(np.diff(seg)).sum())
                out[f"dir_efficiency_{W}s"] = (
                    float((seg[-1] - seg[0]) * d / gross) if gross > 0 else None)

        if anchor_ns is not None:
            k = max(int(np.searchsorted(m.ts, anchor_ns, side="left")), sess_lo)
            if k <= i:
                out[f"excursion_from_{anchor_label}_atr"] = float(
                    (px - float(m.close[k])) * d / atr)
        return out


def market_features(row: dict, model: str) -> dict:
    """The 25 canonical inline features of whichever model is in domain.

    Names are unprefixed so LONG and SHORT rows share one schema. The feature
    VALUES are raw market state, identical in meaning on both sides; the fade
    direction enters the matrix as the `side` indicator and through the
    direction-signed FAM_PATH features. No bespoke sign normalisation is applied,
    because inventing one would be exactly the feature engineering this
    feasibility study is forbidden to do.
    """
    pre = "bullish" if model == "BULLISH" else "bearish"
    out = {}
    for c in feature_columns(pre):
        out[c.removeprefix(f"{pre}__")] = row.get(c)
    return out

"""Causal post-confirmation observation states and their FORWARD opportunity.

The whole study turns on one boundary, enforced structurally rather than by
convention:

    STATE   at observation bar ``j`` reads bars ``[0..j]`` and nothing else.
    LABEL   at observation bar ``j`` reads bars ``(j..unc_i]`` and nothing else.

The label side is built from suffix arrays that literally begin at ``j+1``, so a
forward metric cannot see the observation bar, let alone precede it. The state
side is built from prefix slices bounded above by ``j``. There is no array in
this module that spans the boundary.

Two terminals per trade, inherited unchanged from the accepted study (SPEC D1):

* ``nat_i``  STOP-LIVE -- first of 1 ATR stop / opposing flip / session close.
  The accepted economic baseline. Continuation value is PRIMARY on this track.
* ``unc_i``  UNCONSTRAINED -- first of opposing flip / session close, stop
  released. The observation grid and every forward LABEL resolve here, because
  letting a hypothetical stop truncate a forward-opportunity label is exactly
  the censored-population defect this program has already been burned by.

Forward first-touch is resolved by binary search on monotone suffix arrays --
``cummax`` of the favorable excursion and ``cummin`` of the adverse -- rather
than by scanning. That is not only faster; it makes "first bar at or after j+1
whose extreme crosses X" a single ``searchsorted``, which is much harder to get
subtly wrong than a hand-rolled scan with an off-by-one at the boundary.
"""
from __future__ import annotations

import numpy as np

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, NS,
)
from studies.top10_fast_confirm_runner_path.implementation.engine import (
    STOP_ATR, prepare, runner_bucket,
)

# ---- frozen grid (SPEC D2) ------------------------------------------------
DENSE_STEP_S = 15
DENSE_MAX_S = 600
DENSE_OFFSETS_S = tuple(range(DENSE_STEP_S, DENSE_MAX_S + 1, DENSE_STEP_S))   # 40
SPARSE_OFFSETS_S = (900, 1200, 1800, 2400)
# The brief's mandatory explicit observations; all members of the dense grid.
REQUIRED_OFFSETS_S = (30, 60, 90, 120, 180, 300, 600)

# ---- frozen barriers (SPEC D6) -------------------------------------------
FAV_LEVELS = (0.25, 0.50, 0.75, 1.00, 1.50)
ADV_LEVELS = (0.25, 0.50, 0.75, 1.00)
RACE_PAIRS = ((0.25, 0.25), (0.50, 0.25), (0.50, 0.50), (0.75, 0.25),
              (0.75, 0.50), (1.00, 0.50), (1.00, 0.75), (1.50, 0.50),
              (1.50, 0.75), (1.50, 1.00))

PROGRESS_LOOKBACKS_S = (15, 30, 60)
RUNNER_TIERS = (2.0, 2.5, 3.0, 4.0)
HARVEST_RUNGS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)

FAVORABLE, ADVERSE, UNRESOLVED = "FAVORABLE", "ADVERSE", "UNRESOLVED"


def tag(x: float) -> str:
    return str(x).replace(".", "_")


def _first(mask: np.ndarray) -> int:
    hit = np.flatnonzero(mask)
    return int(hit[0]) if hit.size else -1


def _touch(monotone: np.ndarray, threshold: float) -> int:
    """First index of a NON-DECREASING array at or above `threshold`; -1 if none.

    The caller passes a suffix array that starts at bar ``j+1``, so index 0 here
    is the first bar strictly after the observation. There is no way to return
    the observation bar itself.
    """
    i = int(np.searchsorted(monotone, threshold, side="left"))
    return i if i < monotone.size else -1


class TradeForward:
    """One confirmed trade: its two terminals, and the forward machinery."""

    __slots__ = ("w", "nat_ret", "unc_ret", "eventual_max_mfe", "nat_max_mfe",
                 "meta", "n")

    def __init__(self, w, meta: dict):
        self.w = w
        self.meta = meta
        self.n = w.ts.size
        self.nat_ret = w.realise(w.nat_i, w.nat_fill_next)
        self.unc_ret = w.realise(w.unc_i, False)
        self.eventual_max_mfe = float(w.run_mfe[w.unc_i])
        self.nat_max_mfe = float(w.run_mfe[w.nat_i])

    # ------------------------------------------------------------- state
    def state_at(self, j: int) -> dict:
        """SPEC D4 causal state. Every read is bounded above by `j`."""
        w = self.w
        ci = w.ci
        mark_j = float(w.mark[j])
        mfe_j = float(w.run_mfe[j])
        dd = mfe_j - mark_j
        le = int(w.last_ext[j])
        armed = le >= ci
        anchor = le if armed else ci
        seg_new = w.new_ext[ci + 1:j + 1] if j > ci else np.zeros(0, dtype=bool)

        st = {
            "return_from_entry_atr": mark_j,
            "return_since_confirm_atr": mark_j - float(w.mark[ci]),
            "running_mfe_from_entry_atr": mfe_j,
            "running_mfe_since_confirm_atr": float(
                np.max(w.bar_hi[ci:j + 1]) - w.mark[ci]),
            "running_mae_from_entry_atr": float(w.run_mae[j]),
            "drawdown_from_running_max_atr": dd,
            "retracement_fraction": (dd / mfe_j) if mfe_j >= 0.10 else None,
            "stall_armed": bool(armed),
            "seconds_since_last_favorable_extreme": float(
                (int(w.ts[j]) - int(w.ts[anchor])) / NS),
            "seconds_since_last_extreme_from_any": float(
                (int(w.ts[j]) - int(w.ts[max(le, 0)])) / NS),
            "n_new_favorable_extremes_since_confirm": int(seg_new.sum()),
            "seconds_to_session_close": float(
                (int(w.market.day_close_ns[w.start]) - int(w.ts[j])) / NS),
        }
        for W in PROGRESS_LOOKBACKS_S:
            if (int(w.ts[j]) - w.confirm_ns) < W * NS:
                st[f"favorable_progress_last_{W}s"] = None
                st[f"adverse_progress_last_{W}s"] = None
                st[f"mark_progress_last_{W}s"] = None
            else:
                jw = max(_first(w.ts >= int(w.ts[j]) - W * NS), 0)
                st[f"favorable_progress_last_{W}s"] = float(w.run_mfe[j] - w.run_mfe[jw])
                st[f"adverse_progress_last_{W}s"] = float(w.run_mae[j] - w.run_mae[jw])
                st[f"mark_progress_last_{W}s"] = float(w.mark[j] - w.mark[jw])
        return st

    # ------------------------------------------------------------ labels
    def forward_at(self, j: int) -> dict:
        """SPEC D6/Phase 4 forward labels. Every read starts at `j+1`.

        `fmax` / `amin` are the running favorable maximum and adverse minimum of
        the SUFFIX. They are monotone by construction, which is what makes the
        first-touch a binary search, and they cannot contain the observation bar
        because the slice starts one past it.
        """
        w, unc = self.w, self.w.unc_i
        m = float(w.mark[j])
        out = {"has_forward_bars": j < unc}
        if j >= unc:
            out |= {"forward_mfe_atr": 0.0, "forward_mae_atr": 0.0,
                    "time_to_forward_mfe_s": None, "time_to_forward_mae_s": None,
                    "another_favorable_extreme": False,
                    "forward_net_to_unc_exit_atr": float(self.unc_ret - m),
                    "forward_net_to_nat_exit_atr": (float(self.nat_ret - m)
                                                    if j <= w.nat_i else None)}
            for f, a in RACE_PAIRS:
                out[f"race_{tag(f)}_before_{tag(a)}"] = UNRESOLVED
                out[f"race_{tag(f)}_before_{tag(a)}_ambiguous"] = False
            for f in FAV_LEVELS:
                out[f"secs_to_up_{tag(f)}"] = None
            for a in ADV_LEVELS:
                out[f"secs_to_dn_{tag(a)}"] = None
            return out

        fmax = np.maximum.accumulate(w.bar_hi[j + 1:unc + 1])
        namin = np.maximum.accumulate(-w.bar_lo[j + 1:unc + 1])   # non-decreasing
        ts_f = w.ts[j + 1:unc + 1]
        t0 = int(w.ts[j])

        k_mfe = int(np.searchsorted(fmax, fmax[-1], side="left"))
        k_mae = int(np.searchsorted(namin, namin[-1], side="left"))
        out |= {
            "forward_mfe_atr": float(fmax[-1] - m),
            "forward_mae_atr": float(m + namin[-1]),
            "time_to_forward_mfe_s": float((int(ts_f[k_mfe]) - t0) / NS),
            "time_to_forward_mae_s": float((int(ts_f[k_mae]) - t0) / NS),
            "another_favorable_extreme": bool(fmax[-1] > float(w.run_mfe[j])),
            "forward_net_to_unc_exit_atr": float(self.unc_ret - m),
            "forward_net_to_nat_exit_atr": (float(self.nat_ret - m)
                                            if j <= w.nat_i else None),
        }

        # first-touch indices within the suffix (-1 = never, before the terminal)
        fav_i = {f: _touch(fmax, m + f) for f in FAV_LEVELS}
        adv_i = {a: _touch(namin, a - m) for a in ADV_LEVELS}
        for f, i in fav_i.items():
            out[f"secs_to_up_{tag(f)}"] = (float((int(ts_f[i]) - t0) / NS)
                                           if i >= 0 else None)
        for a, i in adv_i.items():
            out[f"secs_to_dn_{tag(a)}"] = (float((int(ts_f[i]) - t0) / NS)
                                           if i >= 0 else None)

        for f, a in RACE_PAIRS:
            tf, ta = fav_i[f], adv_i[a]
            key = f"race_{tag(f)}_before_{tag(a)}"
            if tf < 0 and ta < 0:
                out[key], out[key + "_ambiguous"] = UNRESOLVED, False
            elif ta < 0 or (tf >= 0 and tf < ta):
                out[key], out[key + "_ambiguous"] = FAVORABLE, False
            elif tf < 0 or ta < tf:
                out[key], out[key + "_ambiguous"] = ADVERSE, False
            else:
                # Same bar. Intra-second ordering is unknowable from OHLC, so the
                # economic reading is adverse; the optimistic bound is recovered
                # from the ambiguity flag downstream.
                out[key], out[key + "_ambiguous"] = ADVERSE, True
        return out

    # ------------------------------------------------------- economics
    def economics_at(self, j: int) -> dict:
        """Exit-now vs continue. Costs cancel on a single unit (SPEC D7)."""
        w = self.w
        exit_now_fill = w.realise(j, True)
        stop_live = j <= w.nat_i
        return {
            "exit_now_mark_atr": float(w.mark[j]),
            "exit_now_fill_atr": float(exit_now_fill),
            "natural_return_stop_live_atr": float(self.nat_ret),
            "natural_return_unconstrained_atr": float(self.unc_ret),
            "cv_stop_live_atr": (float(self.nat_ret - exit_now_fill)
                                 if stop_live else None),
            "cv_unconstrained_atr": float(self.unc_ret - exit_now_fill),
            "secs_to_stop_live_terminal": (
                float((int(w.ts[w.nat_i]) - int(w.ts[j])) / NS) if stop_live else None),
            "secs_to_unc_terminal": float((int(w.ts[w.unc_i]) - int(w.ts[j])) / NS),
        }

    def observation(self, L: int, j: int, dense: bool) -> dict:
        w = self.w
        row = {
            **self.meta,
            "offset_s": int(L),
            "dense": bool(dense),
            "obs_ns": int(w.ts[j]),
            "obs_idx": int(j),
            "alive_stop_live": bool(j <= w.nat_i),
            "seconds_since_confirmation": float((int(w.ts[j]) - w.confirm_ns) / NS),
        }
        row |= self.state_at(j)
        row |= self.forward_at(j)
        row |= self.economics_at(j)
        return row


def trade_meta(w, tr: dict) -> dict:
    """Per-trade constants and RETROSPECTIVE LABELS (never state inputs)."""
    nat_ret = w.realise(w.nat_i, w.nat_fill_next)
    unc_ret = w.realise(w.unc_i, False)
    ev = float(w.run_mfe[w.unc_i])
    dt_confirm_ns = w.confirm_ns - int(tr["entry_ns"])
    meta = {
        "regime_id": tr["regime_id"],
        "entry_year": tr["entry_year"],
        "side": tr["side"],
        "direction": int(tr["direction"]),
        "terminal_label": tr["terminal_label"],
        "entry_ns": int(tr["entry_ns"]),
        "confirm_ns": int(w.confirm_ns),
        "entry_atr": float(w.atr),
        "confirmation_speed_s": float(dt_confirm_ns / NS),
        "natural_kind": w.nat_kind,
        "unc_kind": w.unc_kind,
        "nat_terminal_ns": int(w.ts[w.nat_i]),
        "unc_terminal_ns": int(w.ts[w.unc_i]),
        "trade_nat_return_atr": float(nat_ret),
        "trade_unc_return_atr": float(unc_ret),
        "trade_nat_net_atr": float(nat_ret - COST_POINTS / w.atr),
        # The accepted giveback pool is defined on the STOP-LIVE track and only
        # over OPPOSING_FLIP terminals -- that is how the accepted 0.898/entry
        # was computed, and Phase 0 has to reproduce it exactly.
        "trade_nat_max_mfe_atr": float(w.run_mfe[w.nat_i]),
        "trade_nat_giveback_atr": float(w.run_mfe[w.nat_i] - nat_ret),
        "trade_unc_giveback_atr": float(ev - unc_ret),
        "eventual_max_mfe_atr": ev,
        "runner_bucket": runner_bucket(ev),
        "post_confirm_secs_unc": float((int(w.ts[w.unc_i]) - w.confirm_ns) / NS),
        "post_confirm_secs_nat": float((int(w.ts[w.nat_i]) - w.confirm_ns) / NS),
        "stopped_after_confirm": bool(w.nat_kind == "STOP"),
    }
    for T in RUNNER_TIERS:
        meta[f"reached_{tag(T)}"] = bool(ev >= T)
    return meta


def walk(market, regimes, tr: dict):
    """All dense + sparse observations for one confirmed trade.

    Returns ``(fwd, meta, dense_rows, sparse_rows)`` or ``None`` when the trade
    has no measurable post-entry window (the inherited 49
    SESSION_CLOSE_UNRESOLVED set). The ``TradeForward`` is handed back so that
    the Phase 11/12 diagnostics run against the SAME window object the
    observations came from -- a policy that re-derived its own window could
    silently be looking at different bars.
    """
    w = prepare(market, regimes, tr)
    if w is None:
        return None
    meta = trade_meta(w, tr)
    fwd = TradeForward(w, meta)

    dense, sparse = [], []
    for L in DENSE_OFFSETS_S:
        j = w.index_at_offset(L)
        if j < 0 or j > w.unc_i:
            continue
        dense.append(fwd.observation(L, j, True))
    for L in SPARSE_OFFSETS_S:
        j = w.index_at_offset(L)
        if j < 0 or j > w.unc_i:
            continue
        sparse.append(fwd.observation(L, j, False))
    return fwd, meta, dense, sparse

"""One walk per confirmed trade: two terminals, ten causal landmarks, geometry.

The whole study turns on one discipline: a landmark state at +L seconds may read
bars ``[0..j]`` and nothing else, where ``j`` is the first bar at or after
``confirm_ns + L``. Every state variable below is computed from a slice bounded
above by ``j``. The retrospective outcome (``eventual_max_mfe_atr``) is computed
from the whole window and is a LABEL ONLY -- it never enters a state variable.

Two terminals per trade (SPEC D1):

* ``nat_i``  STOP-LIVE -- first of 1 ATR stop / opposing flip / session close.
  This is the accepted economic baseline and is what Phase 0 reconciles against.
* ``unc_i``  UNCONSTRAINED -- first of opposing flip / session close, stop
  released. All descriptive post-confirmation geometry uses this, per the brief's
  NO CENSORING TRAP section: leaving a stop active while measuring how much room
  a runner needs is exactly the censored-population defect.

The 1 ATR stop still gates *membership* -- a trade stopped before its confirming
flip is ``STOPPED_BEFORE_CONFIRM`` and is not in this population at all.
"""
from __future__ import annotations

import numpy as np

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, FLAT_POINTS, NS, MarketData, RegimeIndex,
)

STOP_ATR = 1.00
FAST_CUTOFF_S = 120

# Cohort edges in SECONDS, applied to integer nanoseconds. Float seconds must
# never decide membership: `(confirm_ns - entry_ns) / 1e9` renders an exact
# 120-second gap as 120.00000000000001, which silently moved 52 trades out of
# the primary population. Comparisons are made as `dt_ns <= edge * NS`, exact
# by construction. Intervals are half-open on the left so the cohorts partition
# the confirmed set exactly: FAST_0_60 + FAST_61_120 == FAST_CONFIRM_120.
COHORT_EDGES_S = (("FAST_0_60", None, 60), ("FAST_61_120", 60, 120),
                  ("SLOW_121_300", 120, 300), ("VERY_SLOW_GT300", 300, None))

LANDMARKS_S = (5, 10, 15, 20, 30, 45, 60, 90, 120, 180)
KEY_LANDMARKS_S = (30, 60, 120)          # Phases 9/11
GIVEBACK_LEVELS = (0.25, 0.50, 0.75, 1.00)
STALL_S = (15, 30, 45, 60, 90, 120)
RUNNER_TIERS = (2.0, 2.5, 3.0, 4.0)
PROGRESS_LOOKBACKS_S = (15, 30, 60)
ADD_MFE_LEVELS = (0.25, 0.50, 1.00)

# Retrospective buckets on the UNCONSTRAINED eventual MaxMFE from original entry.
RUNNER_BUCKETS = (("R0", 0.0, 1.0), ("R1", 1.0, 2.0),
                  ("R2", 2.0, 3.0), ("R3", 3.0, float("inf")))

# The §4 causal state variables carried at every landmark.
STATE_VARS = (
    "ret_from_entry", "ret_since_confirm", "run_mfe_entry", "mfe_since_confirm",
    "dd_from_run_max", "retrace_frac", "made_new_extreme",
    "secs_since_last_extreme", "n_new_extremes",
    "prog_mfe_15s", "prog_mfe_30s", "prog_mfe_60s",
    "prog_mark_15s", "prog_mark_30s", "prog_mark_60s",
)


def _first(mask: np.ndarray) -> int:
    hit = np.flatnonzero(mask)
    return int(hit[0]) if hit.size else -1


def cohort_of(dt_ns: int) -> str:
    """Confirmation-speed cohort from the exact integer nanosecond gap."""
    for name, lo, hi in COHORT_EDGES_S:
        if (lo is None or dt_ns > lo * NS) and (hi is None or dt_ns <= hi * NS):
            return name
    return "VERY_SLOW_GT300"


def runner_bucket(max_mfe: float) -> str:
    for name, lo, hi in RUNNER_BUCKETS:
        if lo <= max_mfe < hi:
            return name
    return "R3"


class Window:
    """The one-second window of a single trade, plus its two terminals.

    Phase 12 policies are evaluated against THIS object, not against a re-derived
    window, so a policy can never see a different set of bars from the one the
    descriptive geometry was measured on -- a subtle window difference is exactly
    how a spurious edge gets manufactured.
    """

    __slots__ = ("ts", "bar_hi", "bar_lo", "mark", "run_mfe", "run_mae", "new_ext",
                 "last_ext", "ci", "nat_i", "unc_i", "nat_fill_next", "nat_kind",
                 "unc_kind", "stop_i", "start", "sess_end", "px", "atr", "d",
                 "market", "confirm_ns")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def realise(self, i: int, fill_next: bool) -> float:
        """Causal fill: a trigger on bar i fills at bar i+1's OPEN, never at i."""
        if fill_next:
            f = self.start + i + 1
            if f < self.sess_end and f < self.market.n:
                p = float(self.market.open_[f])
            else:
                p = float(self.market.close[self.start + i])
        else:
            p = float(self.market.close[self.start + i])
        pts = (p - self.px) * self.d
        return 0.0 if abs(pts) < FLAT_POINTS else pts / self.atr

    def index_at_offset(self, seconds: int) -> int:
        """First bar at or after confirm + `seconds`; -1 if beyond the window."""
        return _first(self.ts >= self.confirm_ns + int(seconds) * NS)


def prepare(market: MarketData, regimes: RegimeIndex, tr: dict) -> Window | None:
    """Build the trade window and both terminals. Shared by walk() and policies."""
    entry_ns, d = int(tr["entry_ns"]), int(tr["direction"])
    px, atr = tr["entry_price"], tr["entry_atr"]
    if atr is None or not np.isfinite(atr) or atr <= 0:
        return None
    start = market.index_strictly_after(entry_ns)
    if start >= market.n:
        return None
    close_ns = int(market.day_close_ns[start])
    sess_end = int(np.searchsorted(market.day_close_ns,
                                   market.day_close_ns[start], side="right"))
    confirm_ns = int(tr["confirm_ns"])
    opposing_ns = regimes.next_start_after(entry_ns, -d, inclusive=True)
    horizon = close_ns if opposing_ns is None else min(close_ns, opposing_ns)
    end = min(max(market.index_at_or_after(horizon) + 1, start + 1), sess_end, market.n)
    if end <= start:
        return None

    hi, lo, cl = market.high[start:end], market.low[start:end], market.close[start:end]
    ts = market.ts[start:end]
    bar_hi = ((hi - px) if d > 0 else (px - lo)) / atr
    bar_lo = ((lo - px) if d > 0 else (px - hi)) / atr
    mark = (cl - px) * d / atr
    run_mfe = np.maximum.accumulate(np.maximum(bar_hi, 0.0))
    run_mae = np.maximum.accumulate(np.maximum(-bar_lo, 0.0))

    ci = _first(ts >= confirm_ns)
    if ci < 0:
        return None
    stop_i = _first(run_mae >= STOP_ATR)
    reached_opp = opposing_ns is not None and int(ts[-1]) >= opposing_ns - NS
    unc_i = ts.size - 1
    unc_kind = "OPPOSING_FLIP" if reached_opp else "SESSION"
    if stop_i >= 0:
        nat_i, nat_fill_next, nat_kind = stop_i, True, "STOP"
    else:
        nat_i, nat_fill_next, nat_kind = unc_i, False, unc_kind

    prev = np.concatenate(([-np.inf], run_mfe[:-1]))
    new_ext = bar_hi > prev
    last_ext = np.maximum.accumulate(np.where(new_ext, np.arange(ts.size), -1))

    return Window(ts=ts, bar_hi=bar_hi, bar_lo=bar_lo, mark=mark, run_mfe=run_mfe,
                  run_mae=run_mae, new_ext=new_ext, last_ext=last_ext, ci=ci,
                  nat_i=nat_i, unc_i=unc_i, nat_fill_next=nat_fill_next,
                  nat_kind=nat_kind, unc_kind=unc_kind, stop_i=stop_i, start=start,
                  sess_end=sess_end, px=float(px), atr=float(atr), d=d,
                  market=market, confirm_ns=confirm_ns)


def walk(market: MarketData, regimes: RegimeIndex, tr: dict) -> dict | None:
    """Evaluate one confirmed trade: economics, geometry, landmark states."""
    entry_ns, d = int(tr["entry_ns"]), int(tr["direction"])
    px, atr = tr["entry_price"], tr["entry_atr"]
    if atr is None or not np.isfinite(atr) or atr <= 0:
        return None
    start = market.index_strictly_after(entry_ns)
    if start >= market.n:
        return None

    close_ns = int(market.day_close_ns[start])
    sess_end = int(np.searchsorted(market.day_close_ns,
                                   market.day_close_ns[start], side="right"))
    confirm_ns = int(tr["confirm_ns"])
    opposing_ns = regimes.next_start_after(entry_ns, -d, inclusive=True)
    horizon = close_ns if opposing_ns is None else min(close_ns, opposing_ns)
    end = min(max(market.index_at_or_after(horizon) + 1, start + 1), sess_end, market.n)
    if end <= start:
        return None

    hi, lo, cl = market.high[start:end], market.low[start:end], market.close[start:end]
    ts = market.ts[start:end]
    bar_hi = ((hi - px) if d > 0 else (px - lo)) / atr
    bar_lo = ((lo - px) if d > 0 else (px - hi)) / atr
    mark = (cl - px) * d / atr
    run_mfe = np.maximum.accumulate(np.maximum(bar_hi, 0.0))
    run_mae = np.maximum.accumulate(np.maximum(-bar_lo, 0.0))

    ci = _first(ts >= confirm_ns)
    if ci < 0:
        return None
    stop_i = _first(run_mae >= STOP_ATR)

    # ---- terminals -------------------------------------------------------
    reached_opp = opposing_ns is not None and int(ts[-1]) >= opposing_ns - NS
    unc_i = ts.size - 1
    unc_kind = "OPPOSING_FLIP" if reached_opp else "SESSION"
    if stop_i >= 0:
        nat_i, nat_fill_next, nat_kind = stop_i, True, "STOP"
    else:
        nat_i, nat_fill_next, nat_kind = unc_i, False, unc_kind

    def realise(i: int, fill_next: bool) -> float:
        if fill_next:
            f = start + i + 1
            if f < sess_end and f < market.n:
                p = float(market.open_[f])
            else:
                p = float(cl[i])
        else:
            p = float(cl[i])
        pts = (p - px) * d
        return 0.0 if abs(pts) < FLAT_POINTS else pts / atr

    nat_ret = realise(nat_i, nat_fill_next)
    unc_ret = realise(unc_i, False)
    nat_max_mfe = float(run_mfe[nat_i])
    eventual_max_mfe = float(run_mfe[unc_i])          # RETROSPECTIVE LABEL ONLY
    k_max = int(np.argmax(run_mfe[:unc_i + 1] >= eventual_max_mfe - 1e-12))

    dt_confirm_ns = confirm_ns - entry_ns          # exact; never floated to decide
    secs_to_confirm = dt_confirm_ns / NS
    out = {
        "regime_id": tr["regime_id"], "direction": d, "side": tr["side"],
        "entry_year": tr["entry_year"], "entry_ns": entry_ns,
        "entry_price": float(px), "entry_atr": float(atr),
        "terminal_label": tr["terminal_label"],
        "confirm_ns": confirm_ns, "confirm_idx": ci,
        "dt_confirm_ns": int(dt_confirm_ns),
        "seconds_to_confirm": float(secs_to_confirm),
        "is_fast_confirm": bool(dt_confirm_ns <= FAST_CUTOFF_S * NS),
        "on_120s_boundary": bool(dt_confirm_ns == FAST_CUTOFF_S * NS),
        "cohort": cohort_of(dt_confirm_ns),
        "stop_idx": stop_i,
        "stop_after_confirm": bool(stop_i > ci) if stop_i >= 0 else None,
        "ambiguous_stop_confirm": bool(stop_i >= 0 and stop_i == ci),

        # entry -> confirming flip
        "return_at_confirm_atr": float(mark[ci]),
        "mfe_to_confirm_atr": float(run_mfe[ci]),
        "mae_to_confirm_atr": float(run_mae[ci]),

        # stop-live economics (the accepted baseline)
        "natural_kind": nat_kind,
        "natural_return_atr": nat_ret,
        "natural_net_atr": nat_ret - COST_POINTS / atr,
        "natural_max_mfe_atr": nat_max_mfe,
        "natural_giveback_atr": nat_max_mfe - nat_ret,
        "natural_capture": (nat_ret / nat_max_mfe) if nat_max_mfe >= 0.10 else None,
        "natural_terminal_ns": int(ts[nat_i]),

        # unconstrained geometry (descriptive)
        "unc_kind": unc_kind,
        "unc_return_atr": unc_ret,
        "unc_net_atr": unc_ret - COST_POINTS / atr,
        "eventual_max_mfe_atr": eventual_max_mfe,
        "unc_giveback_atr": eventual_max_mfe - unc_ret,
        "unc_capture": (unc_ret / eventual_max_mfe) if eventual_max_mfe >= 0.10 else None,
        "unc_terminal_ns": int(ts[unc_i]),
        "runner_bucket": runner_bucket(eventual_max_mfe),

        # post-confirmation opportunity
        "additional_mfe_after_confirm_atr": float(eventual_max_mfe - run_mfe[ci]),
        "seconds_confirm_to_maxmfe": float((int(ts[k_max]) - confirm_ns) / NS),
        "seconds_confirm_to_unc_exit": float((int(ts[unc_i]) - confirm_ns) / NS),
        "frac_maxmfe_at_confirm": (float(run_mfe[ci] / eventual_max_mfe)
                                   if eventual_max_mfe >= 0.10 else None),
    }
    for T in RUNNER_TIERS:
        out[f"reached_{str(T).replace('.', '_')}"] = bool(eventual_max_mfe >= T)

    # ---- Phase 5: causal landmark states ---------------------------------
    # Bounded above by j at every step. `new_ext[k]` marks a bar that set a new
    # entry-relative running favorable extreme; it is computed once over the full
    # window but only ever INDEXED up to j, never scanned past it.
    prev = np.concatenate(([-np.inf], run_mfe[:-1]))
    new_ext = bar_hi > prev
    ext_idx = np.where(new_ext, np.arange(ts.size), -1)
    last_ext = np.maximum.accumulate(ext_idx)

    states = []
    for L in LANDMARKS_S:
        target = confirm_ns + int(L) * NS
        j = _first(ts >= target)
        alive = j >= 0 and j <= unc_i
        if j < 0:
            j = unc_i                     # carried terminal state (SPEC D3)
        st = {
            "regime_id": tr["regime_id"], "landmark_s": L,
            "alive": bool(alive),
            "alive_stop_live": bool(alive and j <= nat_i),
            "landmark_ns": int(ts[j]), "landmark_idx": j,
            "runner_bucket": out["runner_bucket"],
            "eventual_max_mfe_atr": eventual_max_mfe,
            "entry_year": tr["entry_year"], "side": tr["side"],
            "ret_from_entry": float(mark[j]),
            "ret_since_confirm": float(mark[j] - mark[ci]),
            "run_mfe_entry": float(run_mfe[j]),
            "mfe_since_confirm": float(np.max(bar_hi[ci:j + 1]) - mark[ci]),
            "dd_from_run_max": float(run_mfe[j] - mark[j]),
            "retrace_frac": (float((run_mfe[j] - mark[j]) / run_mfe[j])
                             if run_mfe[j] >= 0.10 else None),
        }
        seg_new = new_ext[ci + 1:j + 1] if j > ci else np.zeros(0, dtype=bool)
        st["made_new_extreme"] = bool(seg_new.any())
        st["n_new_extremes"] = int(seg_new.sum())
        le = int(last_ext[j])
        anchor = le if le >= ci else ci
        st["secs_since_last_extreme"] = float((int(ts[j]) - int(ts[anchor])) / NS)
        for W in PROGRESS_LOOKBACKS_S:
            if (int(ts[j]) - confirm_ns) < W * NS:
                st[f"prog_mfe_{W}s"] = None
                st[f"prog_mark_{W}s"] = None
            else:
                jw = _first(ts >= int(ts[j]) - W * NS)
                jw = max(jw, 0)
                st[f"prog_mfe_{W}s"] = float(run_mfe[j] - run_mfe[jw])
                st[f"prog_mark_{W}s"] = float(mark[j] - mark[jw])
        states.append(st)

    # ---- Phase 7: first-giveback geometry (post-confirmation) ------------
    seg = slice(ci, unc_i + 1)
    ext_pc = np.maximum.accumulate(run_mfe[seg])
    dd_pc = ext_pc - bar_lo[seg]
    # Two definitions, because the naive one is degenerate.
    #
    # RAW   `ext - bar_lo >= level` is drawdown from the running maximum, but
    #       running MFE is floored at 0, so a trade that merely trades 1 ATR
    #       BELOW ENTRY without ever going favorable books a "1.00 ATR giveback".
    #       100% / 99.9% of fast trades reach every level, so the event carries
    #       no information. Retained and reported to make the degeneracy visible;
    #       never used as a trigger.
    #
    # ARMED additionally requires `ext >= level` -- you cannot give back
    #       favorable excursion you never accumulated. This is what the brief's
    #       Phase 7 question is about ("current MFE when giveback begins",
    #       "remaining MFE after the giveback event") and is the primary table.
    gb = {}
    for lvl in GIVEBACK_LEVELS:
        t = f"gbraw{str(lvl).replace('.', '_')}"
        h = _first(dd_pc >= lvl)
        gb[f"{t}_reached"] = h >= 0
        if h >= 0:
            gb[f"{t}_mfe_at_event"] = float(ext_pc[h])
            gb[f"{t}_secs_from_confirm"] = float((int(ts[ci + h]) - confirm_ns) / NS)

    for lvl in GIVEBACK_LEVELS:
        tag = f"gb{str(lvl).replace('.', '_')}"
        h = _first((dd_pc >= lvl) & (ext_pc >= lvl))
        gb[f"{tag}_reached"] = h >= 0
        if h < 0:
            continue
        g = ci + h
        mfe_at = float(ext_pc[h])
        after = slice(g + 1, unc_i + 1)
        fwd_max = float(np.max(bar_hi[after])) if g + 1 <= unc_i else -np.inf
        gb[f"{tag}_ns"] = int(ts[g])
        gb[f"{tag}_secs_from_confirm"] = float((int(ts[g]) - confirm_ns) / NS)
        gb[f"{tag}_mfe_at_event"] = mfe_at
        gb[f"{tag}_remaining_mfe"] = float(eventual_max_mfe - mfe_at)
        gb[f"{tag}_new_extreme_after"] = bool(fwd_max > mfe_at)
        for a in ADD_MFE_LEVELS:
            gb[f"{tag}_added_{str(a).replace('.', '_')}"] = bool(
                fwd_max - mfe_at >= a)
    out.update(gb)

    # ---- Phase 8: stall geometry ----------------------------------------
    # First stall of each length per trade: the earliest bar at which W seconds
    # have elapsed since the last new favorable extreme. One observation per
    # trade per W, so long trades cannot dominate the table.
    #
    # RAW anchors the clock at the confirmation bar when no post-confirm extreme
    # has occurred yet, so a trade that NEVER goes favorable is credited with a
    # stall it never earned -- 100% of fast trades "reach" a 15/30/45 s stall,
    # again a degenerate event. Reported, not used.
    #
    # ARMED requires the clock to run from a genuine post-confirmation new
    # favorable extreme, which is what the brief specifies ("after confirmation
    # AND AFTER EACH NEW FAVORABLE EXTREME"). Primary.
    last_seg = last_ext[seg]
    since_raw = (ts[seg] - ts[np.maximum(last_seg, ci)]) / NS
    armed = last_seg >= ci
    since_armed = (ts[seg] - ts[np.maximum(last_seg, 0)]) / NS
    stall = {}
    for W in STALL_S:
        t = f"straw{W}"
        h = _first(since_raw >= W)
        stall[f"{t}_reached"] = h >= 0

    for W in STALL_S:
        tag = f"st{W}"
        h = _first(armed & (since_armed >= W))
        stall[f"{tag}_reached"] = h >= 0
        if h < 0:
            continue
        s_i = ci + h
        after = slice(s_i + 1, unc_i + 1)
        fwd_max = float(np.max(bar_hi[after])) if s_i + 1 <= unc_i else -np.inf
        stall[f"{tag}_secs_from_confirm"] = float((int(ts[s_i]) - confirm_ns) / NS)
        stall[f"{tag}_ret"] = float(mark[s_i])
        stall[f"{tag}_mfe"] = float(run_mfe[s_i])
        stall[f"{tag}_dd"] = float(run_mfe[s_i] - mark[s_i])
        stall[f"{tag}_additional_mfe"] = float(eventual_max_mfe - run_mfe[s_i])
        stall[f"{tag}_new_extreme_after"] = bool(fwd_max > float(run_mfe[s_i]))
    out.update(stall)

    return out, states

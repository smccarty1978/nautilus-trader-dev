"""One walk per confirmed trade; every policy evaluated inline on that walk.

Building the path once and testing all policies against it is what keeps this
study cheap and, more importantly, guarantees every policy sees exactly the same
bars — a per-policy re-walk would let a subtle window difference masquerade as an
edge.

Conventions that carry the results (SPEC 2):

* The 1.00 ATR initial stop is LIVE IN EVERY POLICY. Policies may only exit
  EARLIER than the natural exit, never later, and never past the stop.
* A trigger seen on a completed bar, or at a score decision timestamp, fills at
  the FOLLOWING bar's open. The trigger price is never credited.
* Excursions are normalised by the ENTRY ATR throughout, so Phase 2 landmarks,
  Phase 4 MFE fractions and Phase 11 recovery are commensurable.
* The new-regime model score RISING means danger: it is the model whose domain is
  the new regime, predicting that regime's own flip.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, FLAT_POINTS, NS, MarketData, RegimeIndex,
)

STOP_ATR = 1.00
LANDMARKS = (0.50, 0.75, 1.00, 1.50, 2.00, 2.50, 3.00)
GIVEBACK_FLOORS = (0.0, 0.25, 0.50, 0.75, 1.00)   # "gave back to" reference levels
RUNNER_TIERS = (2.0, 2.5, 3.0, 4.0)

# Price-only MFE-retention family (SPEC 4, policies 3-6).
PRICE_POLICIES = {
    "PRICE_A_mfe1_0_gb0_75": (1.0, 0.75),
    "PRICE_B_mfe1_5_gb0_75": (1.5, 0.75),
    "PRICE_C_mfe2_0_gb0_75": (2.0, 0.75),
    "PRICE_D_mfe2_0_gb1_00": (2.0, 1.00),
}


def _tag(x: float) -> str:
    return f"{x:.2f}".replace(".", "_")


def _first(mask: np.ndarray) -> int:
    hit = np.flatnonzero(mask)
    return int(hit[0]) if hit.size else -1


def walk(market: MarketData, regimes: RegimeIndex, tr: dict,
         p90a_ns, p90b_ns, p80a_ns, p80b_ns, buffer_atr: float,
         stair: tuple) -> dict | None:
    """Evaluate one confirmed trade under baseline and every policy."""
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

    hi, lo, cl, op = (market.high[start:end], market.low[start:end],
                      market.close[start:end], market.open_[start:end])
    ts = market.ts[start:end]
    # Entry-relative, direction-normalised, unfloored.
    bar_hi = ((hi - px) if d > 0 else (px - lo)) / atr
    bar_lo = ((lo - px) if d > 0 else (px - hi)) / atr
    mark = (cl - px) * d / atr
    run_mfe = np.maximum.accumulate(np.maximum(bar_hi, 0.0))
    run_mae = np.maximum.accumulate(np.maximum(-bar_lo, 0.0))

    stop_i = _first(run_mae >= STOP_ATR)
    ci = _first(ts >= confirm_ns)
    if ci < 0:
        return None
    # Natural (baseline) terminal: stop, opposing flip, or session close.
    reached_opp = opposing_ns is not None and int(ts[-1]) >= opposing_ns - NS
    if stop_i >= 0:
        nat_i, nat_fill_next, nat_kind = stop_i, True, "STOP"
    elif reached_opp:
        nat_i, nat_fill_next, nat_kind = ts.size - 1, False, "OPPOSING_FLIP"
    else:
        nat_i, nat_fill_next, nat_kind = ts.size - 1, False, "SESSION"

    def exit_at(i: int, fill_next: bool) -> tuple[float, int]:
        if fill_next:
            f = start + i + 1
            if f < sess_end and f < market.n:
                return float(market.open_[f]), int(market.ts[f])
        return float(cl[i]), int(ts[i])

    def realise(i: int, fill_next: bool) -> float:
        p, _ = exit_at(i, fill_next)
        pts = (p - px) * d
        return 0.0 if abs(pts) < FLAT_POINTS else pts / atr

    base_ret = realise(nat_i, nat_fill_next)
    max_mfe = float(run_mfe[nat_i])

    out = {
        "regime_id": tr["regime_id"], "direction": d, "side": tr["side"],
        "entry_year": tr["entry_year"], "entry_ns": entry_ns, "entry_atr": float(atr),
        "confirm_ns": confirm_ns, "confirm_idx": ci,
        "confirm_close_mark_atr": float(mark[ci]),
        "mfe_at_confirm_atr": float(run_mfe[ci]),
        "mae_at_confirm_atr": float(run_mae[ci]),
        "natural_kind": nat_kind,
        "baseline_return_atr": base_ret,
        "baseline_net_atr": base_ret - COST_POINTS / atr,
        "baseline_max_mfe_atr": max_mfe,
        "baseline_post_confirm_max_mfe_atr": float(np.max(run_mfe[ci:nat_i + 1])),
        "baseline_giveback_atr": max_mfe - base_ret,
        "baseline_capture": (base_ret / max_mfe) if max_mfe >= 0.10 else None,
        "baseline_terminal_ns": int(ts[nat_i]),
        "seconds_confirm_to_exit": float((int(ts[nat_i]) - int(ts[ci])) / NS),
        "ambiguous_stop_confirm": bool(stop_i >= 0 and stop_i == ci),
    }

    # ---- Phase 2: landmarks from ORIGINAL ENTRY, first causal touch
    lm_idx: dict[float, int] = {}
    for L in LANDMARKS:
        i = _first(bar_hi >= L)
        i = i if (i >= 0 and i <= nat_i) else -1
        lm_idx[L] = i
        t = _tag(L)
        out[f"lm{t}_reached"] = i >= 0
        out[f"lm{t}_ns"] = int(ts[i]) if i >= 0 else None
        out[f"lm{t}_after_confirm"] = bool(i >= ci) if i >= 0 else None
        if i >= 0:
            seg = slice(i, nat_i + 1)
            out[f"lm{t}_additional_mfe_atr"] = float(run_mfe[nat_i] - run_mfe[i])
            # Worst retrace from the running extreme after achieving the landmark.
            out[f"lm{t}_max_giveback_after_atr"] = float(
                np.max(np.maximum.accumulate(run_mfe[seg]) - bar_lo[seg]))
            for F in GIVEBACK_FLOORS:
                out[f"lm{t}_gaveback_to_{_tag(F)}"] = bool(np.any(bar_lo[seg] <= F))
            out[f"lm{t}_gaveback_to_confirm_close"] = bool(
                np.any(bar_lo[seg] <= mark[ci]))

    # ---- Phase 3/4: P90 and P80 event geometry, streams A and B
    def event_block(prefix: str, ev_ns):
        if ev_ns is None:
            out[f"{prefix}_fired"] = False
            return -1
        j = _first(ts >= int(ev_ns))
        if j < 0 or j > nat_i:
            out[f"{prefix}_fired"] = False
            return -1
        out[f"{prefix}_fired"] = True
        out[f"{prefix}_ns"] = int(ts[j])
        out[f"{prefix}_idx"] = j
        out[f"{prefix}_seconds_from_confirm"] = float((int(ts[j]) - int(ts[ci])) / NS)
        out[f"{prefix}_mark_atr"] = float(mark[j])
        out[f"{prefix}_run_mfe_atr"] = float(run_mfe[j])
        out[f"{prefix}_remaining_mfe_atr"] = float(max_mfe - run_mfe[j])
        out[f"{prefix}_giveback_before_atr"] = float(run_mfe[j] - mark[j])
        out[f"{prefix}_frac_of_final_mfe_realised"] = (
            float(run_mfe[j] / max_mfe) if max_mfe >= 0.10 else None)
        out[f"{prefix}_frac_final_mfe_by_mark"] = (
            float(mark[j] / max_mfe) if max_mfe >= 0.10 else None)
        k = int(np.argmax(run_mfe[:nat_i + 1] >= max_mfe - 1e-12))
        out[f"{prefix}_seconds_to_maxmfe"] = float((int(ts[k]) - int(ts[j])) / NS)
        out[f"{prefix}_price_to_maxmfe_atr"] = float(max_mfe - bar_hi[j])
        return j

    ja = event_block("p90a", p90a_ns)
    jb = event_block("p90b", p90b_ns)
    ka = event_block("p80a", p80a_ns)
    kb = event_block("p80b", p80b_ns)

    # ---- policy machinery ------------------------------------------------
    def finish(trig_i: int | None, fill_next: bool, name: str):
        """A policy may only exit at or before the natural terminal."""
        if trig_i is None or trig_i < 0 or trig_i >= nat_i:
            i, fn, kind = nat_i, nat_fill_next, nat_kind
        else:
            i, fn, kind = trig_i, fill_next, "POLICY"
        r = realise(i, fn)
        out[f"{name}_return_atr"] = r
        out[f"{name}_net_atr"] = r - COST_POINTS / atr
        out[f"{name}_exit_kind"] = kind
        out[f"{name}_exit_idx"] = i
        out[f"{name}_mfe_at_exit_atr"] = float(run_mfe[i])
        out[f"{name}_capture"] = (r / max_mfe) if max_mfe >= 0.10 else None
        out[f"{name}_delta_vs_baseline_atr"] = r - base_ret
        # Phase 10: did we cut a runner off before it reached its tier?
        for T in RUNNER_TIERS:
            if max_mfe >= T:
                li = lm_idx.get(T, _first(bar_hi >= T))
                out[f"{name}_cut_before_{_tag(T)}"] = bool(li >= 0 and i < li)

    def trail_from(arm_i: int, give: float, floor_mfe: float | None) -> int:
        """First bar at or after `arm_i` giving back `give` from running MaxMFE."""
        if arm_i < 0 or arm_i > nat_i:
            return -1
        seg = slice(arm_i, nat_i + 1)
        ext = np.maximum.accumulate(run_mfe[seg])
        if floor_mfe is not None:
            armed = ext >= floor_mfe
        else:
            armed = np.ones(ext.size, dtype=bool)
        hit = _first(armed & ((ext - bar_lo[seg]) >= give))
        return arm_i + hit if hit >= 0 else -1

    finish(None, False, "BASELINE")
    finish(ja, True, "P90A_EXIT")
    finish(jb, True, "P90B_EXIT")
    for name, (floor, give) in PRICE_POLICIES.items():
        finish(trail_from(ci, give, floor), True, name)
    finish(trail_from(jb, 0.50, None), True, "P90ARM_GB050")
    finish(trail_from(jb, 0.75, None), True, "P90ARM_GB075")

    # P90 observation price as the protection anchor.
    if jb >= 0:
        # The scan must start on the bar AFTER the P90 observation. `ref` is bar
        # jb's own close and `bar_lo[jb]` is that same bar's worst level, so
        # including jb reduces the test to `low <= close`, true for essentially
        # every OHLC bar -- which collapsed this policy into a duplicate of
        # P90B_EXIT rather than testing a genuine subsequent reversal.
        # (lookahead-auditor pass 1, CRITICAL.)
        ref = float(mark[jb])
        seg = slice(jb + 1, nat_i + 1)
        h = _first(bar_lo[seg] <= ref)
        finish(jb + 1 + h if h >= 0 else -1, True, "P90ARM_PRICE")
        h2 = _first(bar_lo[seg] <= ref - buffer_atr)
        finish(jb + 1 + h2 if h2 >= 0 else -1, True, "P90ARM_PRICE_BUF")
    else:
        finish(-1, True, "P90ARM_PRICE")
        finish(-1, True, "P90ARM_PRICE_BUF")

    finish(trail_from(kb, 0.75, None), True, "P80ARM_075")
    finish(trail_from(kb, 1.00, None), True, "P80ARM_100")
    # P80 arms a loose trail; a subsequent P90 exits outright, whichever first.
    t1 = trail_from(kb, 1.00, None)
    cand = [x for x in (t1, jb) if x >= 0]
    finish(min(cand) if cand else -1, True, "P80ARM_P90EXIT")

    # Landmark-adaptive ladder: one structural staircase, rungs from Phase 2.
    stair_i = -1
    for floor, give in stair:
        h = trail_from(ci, give, floor)
        if h >= 0 and (stair_i < 0 or h < stair_i):
            stair_i = h
    finish(stair_i, True, "STAIRSTEP")
    return out

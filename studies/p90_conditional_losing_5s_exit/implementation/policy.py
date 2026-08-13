"""Baseline FULL lifecycle, the conditional losing-5s exit, and the matched control.

The baseline is a parameterised re-expression of the accepted
`armed_fade_score_path_progression/implementation/walks.py::continuation_label`
(hold through confirmation, exit at the opposing flip). At `stop_atr = 1.00` with
the arm-price fill it must reproduce that function's labels and metrics exactly;
`validate.py` gate V2 enforces this on all 8,950 arms. It is re-expressed rather
than called because the study needs a second stop distance and an extra exit
term, neither of which that function accepts.

The conditional rule, and why each piece is where it is:

* **The mark is the close of the 1s bar whose `path_init_ns == C`**, where `C` is
  the flip bucket's `close_ts`. That bar covers `(C-5s, C]` and is the last bar
  inside the flip bucket, so its close is the price at the instant the flip
  becomes knowable -- available at `C`, and not one second earlier.
* **The fill is the open of the first bar with `path_init_ns > C`.** The mark
  decides, the next bar fills; the trigger price is never credited. Same
  separation the stop uses.
* **Every adverse flip is tested, not just the first.** Ignoring a flip because
  the trade is above entry does not disarm the rule. This is the whole
  hypothesis: tolerate profitable 5s oscillation, fire on the first counter-regime
  that finds the trade below entry.
* **Confirmation appears in no exit rule.** It is recorded only so Phase 8 can
  split BEFORE/AFTER.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, FLAT_POINTS, NS, MarketData, RegimeIndex,
)
from studies.p90_5s_regime_impulse.implementation.regime_5s import Regime5s

# Accepted FULL-lifecycle labels (walks.py), plus this study's one new label.
STOPPED_BEFORE_CONFIRM = "STOPPED_BEFORE_CONFIRM"
CONFIRMED_THEN_STOPPED = "CONFIRMED_THEN_STOPPED"
FINAL_FLIP_EXIT_WINNER = "FINAL_FLIP_EXIT_WINNER"
FINAL_FLIP_EXIT_LOSER = "FINAL_FLIP_EXIT_LOSER"
SESSION_EXIT = "SESSION_EXIT"
LOSING_5S_FLIP_EXIT = "LOSING_5S_FLIP_EXIT"
CENSORED = "CENSORED"

BASELINE_LABELS = frozenset({
    STOPPED_BEFORE_CONFIRM, CONFIRMED_THEN_STOPPED,
    FINAL_FLIP_EXIT_WINNER, FINAL_FLIP_EXIT_LOSER, SESSION_EXIT,
})
CONDITIONAL_LABELS = BASELINE_LABELS | {LOSING_5S_FLIP_EXIT}


@dataclass
class Walk:
    regime_id: str
    side: str
    direction: int
    entry_year: int
    arm_ns: int
    atr: float
    entered: bool
    entry_ns: int | None = None
    entry_price: float | None = None
    exit_ns: int | None = None
    exit_price: float | None = None
    outcome: str = CENSORED
    gross_atr: float = 0.0
    net_atr: float = 0.0
    mfe_atr: float = float("nan")
    mae_atr: float = float("nan")
    hold_s: float = float("nan")
    ambiguous: bool = False
    confirm_ns: int | None = None
    confirmed_before_exit: bool = False
    n_adverse_flips: int = 0
    n_losing_flips: int = 0
    fired_flip_number: int | None = None
    return_at_fire_atr: float = float("nan")
    adverse_075_ns: int | None = None
    adverse_100_ns: int | None = None
    n_placebo_candidates: int = 0
    n_placebo_unreached: int = 0
    flips: list = field(default_factory=list)


def adverse_flip_times(r5: Regime5s, after_ns: int, until_ns: int,
                       direction: int) -> np.ndarray:
    """close_ts of every completed 5s bucket in (after_ns, until_ns] that is
    AGAINST the trade. The engine is sticky binary, so a bucket whose regime is
    `-direction` is exactly a flip away from the trade direction."""
    lo = int(np.searchsorted(r5.close_ts, after_ns, side="right"))
    hi = int(np.searchsorted(r5.close_ts, until_ns, side="right"))
    if hi <= lo:
        return np.empty(0, dtype=np.int64)
    window = r5.close_ts[lo:hi]
    return window[r5.regime[lo:hi] == -direction]


def simulate(
    market: MarketData,
    regimes: RegimeIndex,
    r5: Regime5s,
    arm_ns: int,
    direction: int,
    atr: float,
    stop_atr: float,
    entry_price_override: float | None = None,
    conditional: bool = False,
    placebo_times_s: np.ndarray | None = None,
) -> dict | None:
    """One trade under the accepted FULL lifecycle, optionally with the rule.

    `entry_price_override` supports the parity gate (arm-price fill); the study
    itself uses the predecessor's next-1s-open fill.
    `placebo_times_s` replaces the adverse-flip times with matched draws while
    keeping the losing test identical (SPEC section 7).
    """
    if not np.isfinite(atr) or atr <= 0:
        return None
    start = market.index_strictly_after(arm_ns)
    if start >= market.n:
        return None

    session_close_ns = int(market.day_close_ns[start])
    session_end = int(np.searchsorted(
        market.day_close_ns, market.day_close_ns[start], side="right"))
    if start >= session_end:
        return None

    entry_ns = int(market.ts[start])
    entry_price = (float(market.open_[start]) if entry_price_override is None
                   else float(entry_price_override))

    confirm_ns = regimes.next_start_after(arm_ns, direction, inclusive=True)
    opposing_ns = regimes.next_start_after(arm_ns, -direction, inclusive=True)

    horizon_ns = session_close_ns
    if opposing_ns is not None:
        horizon_ns = min(horizon_ns, opposing_ns)
    end = min(market.index_at_or_after(horizon_ns) + 1, session_end, market.n)
    if end <= start:
        return None

    hi, lo, ts = market.high[start:end], market.low[start:end], market.ts[start:end]
    favorable = (hi - entry_price) if direction > 0 else (entry_price - lo)
    adverse = (entry_price - lo) if direction > 0 else (hi - entry_price)
    run_mfe = np.maximum.accumulate(np.maximum(favorable, 0.0)) / atr
    run_mae = np.maximum.accumulate(np.maximum(adverse, 0.0)) / atr
    closes = market.close[start:end]

    stop_hits = np.flatnonzero(run_mae >= stop_atr)
    stop_idx = int(stop_hits[0]) if stop_hits.size else -1
    confirm_idx = -1
    if confirm_ns is not None and confirm_ns <= int(ts[-1]):
        f = np.flatnonzero(ts >= confirm_ns)
        confirm_idx = int(f[0]) if f.size else -1
    reached_opposing = opposing_ns is not None and int(ts[-1]) >= opposing_ns - NS

    # ---- adverse flips over the BASELINE window (descriptive base, Phase 1) ----
    n_cand = n_unreached = 0
    if placebo_times_s is None:
        flip_ts = adverse_flip_times(r5, arm_ns, int(ts[-1]), direction)
    else:
        # Anchored on entry_ns, because the pooled draws are ELAPSED-SINCE-ENTRY
        # seconds (`seconds_since_entry` below). Anchoring on arm_ns instead put
        # every placebo check ~1s early relative to the real flips it is matched
        # against -- immaterial at typical holds, but it made the control and
        # the treatment use two different clocks. Raised as NOTE N1 by
        # lookahead-auditor pass 1.
        cand = entry_ns + np.round(np.asarray(placebo_times_s) * NS).astype(np.int64)
        n_cand = int(cand.size)
        keep = (cand > entry_ns) & (cand <= int(ts[-1]))
        # Draws landing past the trade's natural end are never reached. They are
        # COUNTED, not silently dropped: `p_unreached` is the length-blindness
        # diagnostic SPEC section 7 mandates -- a placebo whose draws mostly fall
        # outside the window is not actually matched, and the count is the only
        # way to see that.
        n_unreached = int((~keep).sum())
        flip_ts = np.unique(cand[keep])
    # index of each flip's mark bar: the bar whose path_init_ns == close_ts
    pos = np.searchsorted(ts, flip_ts, side="left")
    ok = (pos < ts.size) & (ts[np.minimum(pos, ts.size - 1)] == flip_ts)
    flip_ts, pos = flip_ts[ok], pos[ok]

    flips = []
    fire_at = -1
    fired_number = None
    return_at_fire = float("nan")
    for n, (fts, p) in enumerate(zip(flip_ts, pos), start=1):
        cur = (float(closes[p]) - entry_price) * direction / atr
        rec = {
            "flip_number": n, "flip_ns": int(fts),
            "seconds_since_entry": (int(fts) - entry_ns) / NS,
            "current_return_atr": cur,
            "current_mfe_atr": float(run_mfe[p]),
            "current_mae_atr": float(run_mae[p]),
            "giveback_from_hwm_atr": float(run_mfe[p]) - cur,
            "is_losing": bool(cur < 0),
            "before_confirm": bool(confirm_idx < 0 or p < confirm_idx),
        }
        flips.append(rec)
        if conditional and fire_at < 0 and cur < 0:
            fire_at = int(p)
            fired_number = n
            return_at_fire = cur

    # ---- resolve the terminal event -------------------------------------
    # Fill indices are compared, not trigger indices: a stop and a conditional
    # exit that fill on the same bar are the same price, and SPEC 4.3 resolves
    # that tie to the stop (adverse).
    stop_fill = start + stop_idx + 1 if stop_idx >= 0 else np.inf
    cond_fill = start + fire_at + 1 if fire_at >= 0 else np.inf
    ambiguous = bool(np.isfinite(stop_fill) and stop_fill == cond_fill)

    if stop_idx >= 0 and stop_fill <= cond_fill:
        idx, fills_next = stop_idx, True
        label = (STOPPED_BEFORE_CONFIRM
                 if (confirm_idx < 0 or stop_idx <= confirm_idx)
                 else CONFIRMED_THEN_STOPPED)
    elif fire_at >= 0:
        idx, fills_next, label = fire_at, True, LOSING_5S_FLIP_EXIT
    elif reached_opposing:
        idx, fills_next, label = ts.size - 1, False, FINAL_FLIP_EXIT_WINNER
    else:
        idx, fills_next, label = ts.size - 1, False, SESSION_EXIT

    if fills_next:
        fill = start + idx + 1
        if fill < session_end and fill < market.n:
            exit_price, exit_ns = float(market.open_[fill]), int(market.ts[fill])
        else:
            exit_price, exit_ns = float(market.close[end - 1]), int(market.ts[end - 1])
    else:
        exit_price, exit_ns = float(market.close[start + idx]), int(ts[idx])

    points = (exit_price - entry_price) * direction
    gross = 0.0 if abs(points) < FLAT_POINTS else points / atr
    if label == FINAL_FLIP_EXIT_WINNER and gross <= 0:
        label = FINAL_FLIP_EXIT_LOSER

    # Descriptive path landmarks: when the trade first reached each adverse
    # level. Used only by Phase 2 coverage (SPEC manifest item 4); no policy
    # reads them.
    def _first_reach(level: float) -> int | None:
        h = np.flatnonzero(run_mae >= level)
        return int(ts[int(h[0])]) if h.size else None

    return {
        "entry_ns": entry_ns, "entry_price": entry_price,
        "exit_ns": exit_ns, "exit_price": exit_price, "outcome": label,
        "adverse_075_ns": _first_reach(0.75), "adverse_100_ns": _first_reach(1.00),
        "n_placebo_candidates": n_cand, "n_placebo_unreached": n_unreached,
        "gross_atr": gross, "net_atr": gross - COST_POINTS / atr,
        "mfe_atr": float(run_mfe[idx]), "mae_atr": float(run_mae[idx]),
        "hold_s": (exit_ns - entry_ns) / NS, "ambiguous": ambiguous,
        "confirm_ns": None if confirm_ns is None else int(confirm_ns),
        "confirmed_before_exit": bool(confirm_idx >= 0 and confirm_idx <= idx),
        "n_adverse_flips": len(flips),
        "n_losing_flips": int(sum(f["is_losing"] for f in flips)),
        "fired_flip_number": fired_number,
        "return_at_fire_atr": return_at_fire,
        "flips": flips,
    }


def run_policy(entries: pl.DataFrame, market: MarketData, regimes: RegimeIndex,
               r5: Regime5s, stop_atr: float, *, conditional: bool,
               arm_price_fill: bool = False,
               placebo_draws: list | None = None) -> list[Walk]:
    """Every entered arm walked once. Non-entries are NOT in `entries` -- the
    denominator is restored downstream by carrying all 8,950 arms with 0.0."""
    walks: list[Walk] = []
    for i, r in enumerate(entries.iter_rows(named=True)):
        w = Walk(regime_id=r["regime_id"], side=r["side"],
                 direction=int(r["direction"]), entry_year=int(r["entry_year"]),
                 arm_ns=int(r["arm_top10_ns"]), atr=float(r["arm_atr"]),
                 entered=True)
        res = simulate(
            market, regimes, r5, w.arm_ns, w.direction, w.atr, stop_atr,
            entry_price_override=(float(r["arm_price"]) if arm_price_fill else None),
            conditional=conditional,
            placebo_times_s=(placebo_draws[i] if placebo_draws is not None else None),
        )
        if res is None:
            w.entered = False
            w.outcome = CENSORED
            walks.append(w)
            continue
        for k, v in res.items():
            setattr(w, k, v)
        walks.append(w)
    return walks


def to_frame(walks: list[Walk]) -> pl.DataFrame:
    return pl.DataFrame([{
        "regime_id": w.regime_id, "side": w.side, "direction": w.direction,
        "entry_year": w.entry_year, "arm_ns": w.arm_ns, "atr": w.atr,
        "entered": w.entered, "entry_ns": w.entry_ns, "entry_price": w.entry_price,
        "exit_ns": w.exit_ns, "exit_price": w.exit_price, "outcome": w.outcome,
        "gross_atr": w.gross_atr, "net_atr": w.net_atr, "mfe_atr": w.mfe_atr,
        "mae_atr": w.mae_atr, "hold_s": w.hold_s, "ambiguous": w.ambiguous,
        "confirm_ns": w.confirm_ns, "confirmed_before_exit": w.confirmed_before_exit,
        "n_adverse_flips": w.n_adverse_flips, "n_losing_flips": w.n_losing_flips,
        "fired_flip_number": w.fired_flip_number,
        "return_at_fire_atr": w.return_at_fire_atr,
        "adverse_075_ns": w.adverse_075_ns, "adverse_100_ns": w.adverse_100_ns,
        "n_placebo_candidates": w.n_placebo_candidates,
        "n_placebo_unreached": w.n_placebo_unreached,
    } for w in walks])


def flip_events_frame(walks: list[Walk], arms: pl.DataFrame) -> pl.DataFrame:
    """Every adverse flip over the BASELINE window -- the descriptive base for
    Phase 1. Enumerating on the baseline (not the conditional) is deliberate:
    it keeps the flips the conditional rule would have cut short in view."""
    meta = {r["regime_id"]: r for r in arms.select(
        "regime_id", "walk_a_confirm_reached_censored", "terminal_label_full"
    ).iter_rows(named=True)}
    rows = []
    for w in walks:
        if not w.entered:
            continue
        m = meta.get(w.regime_id, {})
        for f in w.flips:
            rows.append({
                "regime_id": w.regime_id, "side": w.side,
                "entry_year": w.entry_year, **f,
                "walk_a_confirmed": bool(m.get("walk_a_confirm_reached_censored", False)),
                "terminal_label_full": m.get("terminal_label_full"),
            })
    return pl.DataFrame(rows)

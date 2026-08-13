"""The P90 + 5s-aligned impulse policy, its two stops, and its two controls.

Everything here is a forward walk from a P90 arm timestamp over completed 1s
bars. The rules that keep it causal (SPEC sections 4.3-4.4):

* **Entry fills at the open of the first 1s bar with `path_init_ns > arm_ns`.**
  That bar covers `(arm_ns, arm_ns+1s]`, so its open is the first price reachable
  after the decision. The position is live for that bar, so MFE/MAE measurement
  starts AT it, not after it.
* **A stop trigger is detected on a completed bar and fills at the NEXT bar's
  open.** The stop price itself is never credited (checklist H4).
* **The 5s exit fills at the open of the first 1s bar after the flip bucket's
  `close_ts`** -- the flip is not knowable until its bucket closes, so no price
  at or before `close_ts` may be used.
* **The 1m confirmation flip appears nowhere in the exit set.** It is carried as
  a diagnostic column only. `OUTCOMES` is the complete, asserted set.

The 5s exit always resolves at least 5 seconds out: `arm_ns` is a 5s clock
boundary (SPEC 3.3) and `first_non_aligned_after` searches strictly after it, so
the earliest possible flip bucket closes at `arm_ns + 5s`. No zero-length trade
can be manufactured.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, FLAT_POINTS, NS, MarketData, RegimeIndex,
)
from studies.p90_5s_regime_impulse.implementation.regime_5s import Regime5s

STOP, FIVE_S_EXIT, SESSION_CLOSE, NO_ENTRY = (
    "STOP", "FIVE_S_EXIT", "SESSION_CLOSE", "NO_ENTRY",
)
#: SPEC section 8, stop condition 5 -- any label outside this set means a
#: confirmation term leaked into management and the study aborts.
OUTCOMES = frozenset({STOP, FIVE_S_EXIT, SESSION_CLOSE})

ALIGNED, OPPOSITE, UNINIT = "ALIGNED", "OPPOSITE", "UNINIT"


@dataclass
class Walk:
    """One simulated trade, or one recorded non-entry."""

    regime_id: str
    side: str
    direction: int
    entry_year: int
    arm_ns: int
    atr: float
    alignment: str
    entered: bool
    entry_ns: int | None = None
    entry_price: float | None = None
    exit_ns: int | None = None
    exit_price: float | None = None
    outcome: str = NO_ENTRY
    mfe_atr: float = float("nan")
    mae_atr: float = float("nan")
    hold_s: float = float("nan")
    ambiguous: bool = False
    # diagnostics -- never used by any rule
    confirm_ns: int | None = None
    confirmed_before_exit: bool = False
    return_at_confirm_atr: float = float("nan")
    mfe_at_confirm_atr: float = float("nan")
    five_s_flip_ns: int | None = None
    age_5s_at_arm_s: float = float("nan")
    extra: dict = field(default_factory=dict)

    @property
    def gross_atr(self) -> float:
        if not self.entered or self.exit_price is None:
            return 0.0
        pts = (self.exit_price - self.entry_price) * self.direction
        return 0.0 if abs(pts) < FLAT_POINTS else pts / self.atr

    @property
    def net_atr(self) -> float:
        return 0.0 if not self.entered else self.gross_atr - COST_POINTS / self.atr


def alignment_at_arm(r5: Regime5s, arm_ns: int, direction: int) -> str:
    """The completed 5s state available AT the arm, classified.

    `direction` is the intended TRADE direction (opposite the 1m regime), so
    ALIGNED means the 5s regime already agrees with the fade.
    """
    state = int(r5.state_at(arm_ns))
    if state == 0:
        return UNINIT
    return ALIGNED if state == direction else OPPOSITE


def simulate_impulse(
    market: MarketData,
    regimes: RegimeIndex,
    r5: Regime5s,
    arm_ns: int,
    direction: int,
    atr: float,
    stop_atr: float,
    forced_hold_s: float | None = None,
) -> tuple[str, dict]:
    """Walk one trade. `forced_hold_s` replaces the 5s exit (PLACEBO_EXIT only).

    Returns `(outcome, fields)`; the caller assembles the `Walk`.
    """
    start = market.index_strictly_after(arm_ns)
    if start >= market.n or not np.isfinite(atr) or atr <= 0:
        return SESSION_CLOSE, {"censored": True}

    session_close_ns = int(market.day_close_ns[start])
    session_end = int(np.searchsorted(
        market.day_close_ns, market.day_close_ns[start], side="right"))
    if start >= session_end:
        return SESSION_CLOSE, {"censored": True}

    entry_ns = int(market.ts[start])
    entry_price = float(market.open_[start])

    # --- the exit that ends the hold, other than the stop -------------------
    if forced_hold_s is None:
        flip_ns = r5.first_non_aligned_after(arm_ns, direction)
        exit_signal_ns = None if flip_ns < 0 else int(flip_ns)
    else:
        exit_signal_ns = arm_ns + int(round(forced_hold_s * NS))

    # Fill bar for that signal: the first bar whose open is reachable after it.
    if exit_signal_ns is None:
        f = session_end
    else:
        f = market.index_strictly_after(exit_signal_ns)
    f = min(f, session_end)
    if f <= start:
        # Cannot happen for the real 5s exit (>= arm_ns + 5s), but a degenerate
        # placebo draw must still hold at least the fill bar.
        f = min(start + 1, session_end)

    # --- stop scan over the bars actually held ------------------------------
    hi = market.high[start:f]
    lo = market.low[start:f]
    if hi.size == 0:
        return SESSION_CLOSE, {"censored": True}

    favorable = (hi - entry_price) if direction > 0 else (entry_price - lo)
    adverse = (entry_price - lo) if direction > 0 else (hi - entry_price)
    run_mfe = np.maximum.accumulate(np.maximum(favorable, 0.0)) / atr
    run_mae = np.maximum.accumulate(np.maximum(adverse, 0.0)) / atr

    stop_hits = np.flatnonzero(run_mae >= stop_atr)
    trigger = int(stop_hits[0]) if stop_hits.size else -1

    tie = False
    if trigger >= 0:
        fill = start + trigger + 1
        # Same-instant tie with the 5s exit resolves ADVERSELY (SPEC 4.4). The
        # two fill at the same bar open, so the price is identical and only the
        # label differs -- it is flagged, not silently absorbed.
        tie = fill == f
        if fill >= session_end or fill >= market.n:
            outcome = SESSION_CLOSE
            exit_idx = min(f, session_end) - 1
            exit_price = float(market.close[exit_idx])
            exit_ns = int(market.ts[exit_idx])
        else:
            outcome = STOP
            exit_price = float(market.open_[fill])
            exit_ns = int(market.ts[fill])
        held = trigger
    elif f < session_end:
        # The placebo's drawn hold occupies the same slot as the real 5s flip, so
        # it carries the same label; the two are never mixed in one run.
        outcome = FIVE_S_EXIT
        exit_price = float(market.open_[f])
        exit_ns = int(market.ts[f])
        held = hi.size - 1
    else:
        outcome = SESSION_CLOSE
        exit_idx = session_end - 1
        exit_price = float(market.close[exit_idx])
        exit_ns = int(market.ts[exit_idx])
        held = hi.size - 1

    # --- diagnostics: the 1m confirmation, which no rule above consulted -----
    confirm_ns = regimes.next_start_after(arm_ns, direction, inclusive=True)
    ret_conf, mfe_conf, confirmed_before_exit = float("nan"), float("nan"), False
    if confirm_ns is not None and confirm_ns <= exit_ns:
        ci = market.index_at_or_after(int(confirm_ns))
        if start <= ci < session_end:
            confirmed_before_exit = True
            pts = (float(market.close[ci]) - entry_price) * direction
            ret_conf = 0.0 if abs(pts) < FLAT_POINTS else pts / atr
            mfe_conf = float(run_mfe[min(ci - start, run_mfe.size - 1)])

    return outcome, {
        "entry_ns": entry_ns,
        "entry_price": entry_price,
        "exit_ns": exit_ns,
        "exit_price": exit_price,
        "mfe_atr": float(run_mfe[held]),
        "mae_atr": float(run_mae[held]),
        "hold_s": (exit_ns - entry_ns) / NS,
        "ambiguous": bool(tie),
        "confirm_ns": None if confirm_ns is None else int(confirm_ns),
        "confirmed_before_exit": confirmed_before_exit,
        "return_at_confirm_atr": ret_conf,
        "mfe_at_confirm_atr": mfe_conf,
        "five_s_flip_ns": exit_signal_ns,
        "session_close_ns": session_close_ns,
    }


def run_policy(
    arms: pl.DataFrame,
    market: MarketData,
    regimes: RegimeIndex,
    r5: Regime5s,
    stop_atr: float,
    forced_holds: np.ndarray | None = None,
) -> list[Walk]:
    """Every arm walked once. Non-entries are RETAINED as `Walk(entered=False)`.

    Keeping them is not bookkeeping -- it is the denominator. Dropping them is
    exactly the defect recorded in `baseline_must_include_prefilter_losers`.
    `forced_holds` (PLACEBO_EXIT) is indexed by ENTERED-trade order.
    """
    walks: list[Walk] = []
    k = 0
    for r in arms.iter_rows(named=True):
        direction = int(r["direction"])
        arm_ns = int(r["arm_top10_ns"])
        atr = float(r["arm_atr"])
        align = alignment_at_arm(r5, arm_ns, direction)
        w = Walk(
            regime_id=r["regime_id"], side=r["side"], direction=direction,
            entry_year=int(r["entry_year"]), arm_ns=arm_ns, atr=atr,
            alignment=align, entered=(align == ALIGNED),
            age_5s_at_arm_s=_age_5s(r5, arm_ns),
        )
        if not w.entered:
            walks.append(w)
            continue
        hold = None
        if forced_holds is not None:
            hold = float(forced_holds[k])
        k += 1
        outcome, f = simulate_impulse(
            market, regimes, r5, arm_ns, direction, atr, stop_atr, hold)
        if f.get("censored"):
            # No reachable bar after the arm inside its own session. Retained as
            # a non-entry so the denominator stays 8,950; counted separately.
            w.entered = False
            w.alignment = align
            w.outcome = NO_ENTRY
            w.extra["censored_no_fill_bar"] = True
            walks.append(w)
            continue
        w.outcome = outcome
        for key, val in f.items():
            if hasattr(w, key):
                setattr(w, key, val)
        w.extra["session_close_ns"] = f["session_close_ns"]
        walks.append(w)
    return walks


def _age_5s(r5: Regime5s, t_ns: int) -> float:
    """Seconds the live 5s regime has been in force at `t_ns`."""
    flip = int(r5.flip_ts_at(t_ns))
    return float("nan") if flip < 0 else (t_ns - flip) / NS


def walks_to_frame(walks: list[Walk]) -> pl.DataFrame:
    rows = []
    for w in walks:
        rows.append({
            "regime_id": w.regime_id, "side": w.side, "direction": w.direction,
            "entry_year": w.entry_year, "arm_ns": w.arm_ns, "atr": w.atr,
            "alignment": w.alignment, "entered": w.entered,
            "entry_ns": w.entry_ns, "entry_price": w.entry_price,
            "exit_ns": w.exit_ns, "exit_price": w.exit_price,
            "outcome": w.outcome, "gross_atr": w.gross_atr, "net_atr": w.net_atr,
            "mfe_atr": w.mfe_atr, "mae_atr": w.mae_atr, "hold_s": w.hold_s,
            "ambiguous": w.ambiguous, "confirm_ns": w.confirm_ns,
            "confirmed_before_exit": w.confirmed_before_exit,
            "return_at_confirm_atr": w.return_at_confirm_atr,
            "mfe_at_confirm_atr": w.mfe_at_confirm_atr,
            "five_s_flip_ns": w.five_s_flip_ns,
            "age_5s_at_arm_s": w.age_5s_at_arm_s,
            "censored_no_fill_bar": bool(w.extra.get("censored_no_fill_bar", False)),
        })
    return pl.DataFrame(rows)

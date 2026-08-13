"""Causal path measurement for the two walks defined in SPEC 5.

Both walks share one primitive, `measure_to_confirm`. The only thing that
distinguishes them is *where the measurement origin sits*:

* **Walk A** measures once per armed regime, always from the Top-10 arm. Deeper
  levels subset the population; they never move the origin.
* **Walk B** measures once per level reached, each from that level's own
  first-reach dispatch with its own reference price, its own frozen ATR, and its
  own 1.0 ATR stop.

Two conventions in here are load-bearing and were both defects in the
predecessor study:

* The confirming flip resolves with `inclusive=True`. A regime flip stamped at
  second T is knowable only *after* a decision made at T, under the project's
  1s-before-1m dispatch convention, so it is genuinely in the trade's future.
  The superseded strictly-after resolver skipped exactly those boundary flips
  and then matched a much later same-direction regime instead.
* Every window is clamped to the entry's own RTH session. Only RTH bars are
  loaded, so array index i+1 after 14:59:59 is the *next session's* 08:30 --
  a horizon lookup alone runs straight through the overnight gap and collects a
  move the forced 15:00 flat exists to exclude.
"""
from __future__ import annotations

import numpy as np

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS,
    FLAT_POINTS,
    NS,
    MarketData,
    RegimeIndex,
)

STOP_ATR = 1.0

CONFIRMED = "CONFIRMED"
STOPPED_BEFORE_CONFIRM = "STOPPED_BEFORE_CONFIRM"
SESSION_CLOSE_UNRESOLVED = "SESSION_CLOSE_UNRESOLVED"
CENSORED = "CENSORED"

PRIMARY_LABELS = (
    CONFIRMED,
    STOPPED_BEFORE_CONFIRM,
    SESSION_CLOSE_UNRESOLVED,
    CENSORED,
)

# Descriptive continuation labels (SPEC 8.7). Non-winners are never collapsed
# into one ambiguous bucket.
CONFIRMED_THEN_STOPPED = "CONFIRMED_THEN_STOPPED"
FINAL_FLIP_EXIT_WINNER = "FINAL_FLIP_EXIT_WINNER"
FINAL_FLIP_EXIT_LOSER = "FINAL_FLIP_EXIT_LOSER"
SESSION_EXIT = "SESSION_EXIT"

FULL_LABELS = (
    STOPPED_BEFORE_CONFIRM,
    CONFIRMED_THEN_STOPPED,
    FINAL_FLIP_EXIT_WINNER,
    FINAL_FLIP_EXIT_LOSER,
    SESSION_EXIT,
    CENSORED,
)


def _session_bounds(market: MarketData, start: int) -> tuple[int, int]:
    """(session close ns, exclusive index of the last bar in this session)."""
    session_close_ns = int(market.day_close_ns[start])
    session_end = int(
        np.searchsorted(market.day_close_ns, market.day_close_ns[start], side="right")
    )
    return session_close_ns, session_end


def _excursions(
    market: MarketData, start: int, end: int, entry_price: float, atr: float, direction: int
):
    hi = market.high[start:end]
    lo = market.low[start:end]
    ts = market.ts[start:end]
    favorable = (hi - entry_price) if direction > 0 else (entry_price - lo)
    adverse = (entry_price - lo) if direction > 0 else (hi - entry_price)
    run_mfe = np.maximum.accumulate(np.maximum(favorable, 0.0)) / atr
    run_mae = np.maximum.accumulate(np.maximum(adverse, 0.0)) / atr
    return ts, run_mfe, run_mae


def _first(mask: np.ndarray) -> int:
    hits = np.flatnonzero(mask)
    return int(hits[0]) if hits.size else -1


def _exit_price(
    market: MarketData, start: int, end: int, session_end: int, idx: int, fills_next_bar: bool
) -> tuple[float, int]:
    """Exit price and timestamp.

    A stop touch is detected on a completed 1s bar and fills at the *following*
    bar's open; the trigger price is never credited. If the trigger lands on the
    final bar of the session there is no next open to fill against, and
    borrowing the next session's open would import the overnight gap -- so the
    trade closes at that session's last close instead.
    """
    if fills_next_bar:
        fill = start + idx + 1
        if fill < session_end and fill < market.n:
            return float(market.open_[fill]), int(market.ts[fill])
        return float(market.close[end - 1]), int(market.ts[end - 1])
    return float(market.close[start + idx]), int(market.ts[start + idx])


def measure_to_confirm(
    market: MarketData,
    regimes: RegimeIndex,
    entry_ns: int,
    direction: int,
    entry_price: float,
    atr: float,
) -> dict:
    """Walk forward from one hypothetical entry to the confirming flip.

    The window runs to the confirming flip or the session close, whichever comes
    first. The 1.0 ATR stop is *observed* inside that window but does not
    truncate it, which is what lets the same pass produce both MAE populations
    SPEC 8.2 requires:

    * `uncensored` -- every entry reaching the confirming flip before the session
      close, no stop applied. This is the honest answer to "how much stop room do
      successful flips need", because a population defined by surviving 1 ATR is
      bounded above by 1 ATR and can only ever answer its own premise.
    * `censored_1atr` -- the subset that confirmed before a 1 ATR adverse
      excursion, which is the Walk A survivor population.

    A bar satisfying both the stop and the confirming flip is not resolvable from
    OHLC. It resolves adversely for the conservative bound and is flagged
    `ambiguous`; the optimistic bound is reported alongside.
    """
    invalid = {"valid": False, "terminal_label": CENSORED}
    if atr is None or not np.isfinite(atr) or atr <= 0:
        return invalid
    if entry_price is None or not np.isfinite(entry_price):
        return invalid

    start = market.index_strictly_after(entry_ns)
    if start >= market.n:
        return invalid

    session_close_ns, session_end = _session_bounds(market, start)
    confirm_ns = regimes.next_start_after(entry_ns, direction, inclusive=True)

    horizon_ns = session_close_ns
    if confirm_ns is not None:
        horizon_ns = min(horizon_ns, confirm_ns)
    # At least one bar. A confirming flip stamped at the entry second puts the
    # horizon *at* the entry, which would otherwise produce an empty window and
    # silently censor exactly the boundary case the inclusive resolver exists to
    # capture. The flip is knowable only on the following bar, so that bar is
    # the confirmation bar.
    end = min(
        max(market.index_at_or_after(horizon_ns) + 1, start + 1), session_end, market.n
    )
    if end <= start:
        return invalid

    ts, run_mfe, run_mae = _excursions(market, start, end, entry_price, atr, direction)

    stop_idx = _first(run_mae >= STOP_ATR)
    confirm_idx = -1
    if confirm_ns is not None and confirm_ns <= int(ts[-1]):
        confirm_idx = _first(ts >= confirm_ns)

    ambiguous = stop_idx >= 0 and confirm_idx >= 0 and stop_idx == confirm_idx

    confirm_uncensored = confirm_idx >= 0
    # Conservative bound: a tie resolves adversely, so the trade did not confirm.
    confirm_censored = confirm_idx >= 0 and (stop_idx < 0 or confirm_idx < stop_idx)
    confirm_censored_optimistic = confirm_idx >= 0 and (
        stop_idx < 0 or confirm_idx <= stop_idx
    )
    stop_before_confirm = stop_idx >= 0 and (confirm_idx < 0 or stop_idx <= confirm_idx)

    if stop_before_confirm:
        label, idx, fills_next = STOPPED_BEFORE_CONFIRM, stop_idx, True
    elif confirm_idx >= 0:
        label, idx, fills_next = CONFIRMED, confirm_idx, False
    else:
        label, idx, fills_next = SESSION_CLOSE_UNRESOLVED, ts.size - 1, False

    exit_price, exit_ns = _exit_price(market, start, end, session_end, idx, fills_next)
    points = (exit_price - entry_price) * direction
    gross = 0.0 if abs(points) < FLAT_POINTS else points / atr

    out = {
        "valid": True,
        "entry_ns": int(entry_ns),
        "entry_price": float(entry_price),
        "atr": float(atr),
        "confirm_ns": int(confirm_ns) if confirm_ns is not None else None,
        "confirm_reached_uncensored": bool(confirm_uncensored),
        "confirm_reached_censored": bool(confirm_censored),
        "confirm_reached_censored_optimistic": bool(confirm_censored_optimistic),
        "stop_before_confirm": bool(stop_before_confirm),
        "stop_ns": int(ts[stop_idx]) if stop_idx >= 0 else None,
        "session_close_unresolved": bool(label == SESSION_CLOSE_UNRESOLVED),
        "ambiguous": bool(ambiguous),
        "terminal_label": label,
        "terminal_ns": int(exit_ns),
        "gross_atr": float(gross),
        "net_atr": float(gross - COST_POINTS / atr),
        "mae_at_terminal_atr": float(run_mae[idx]),
        "mfe_at_terminal_atr": float(run_mfe[idx]),
        "bars": int(idx + 1),
    }

    if confirm_uncensored:
        confirm_close = float(market.close[start + confirm_idx])
        confirm_points = (confirm_close - entry_price) * direction
        out.update(
            seconds_to_confirm=float((int(ts[confirm_idx]) - entry_ns) / NS),
            mae_to_confirm_atr=float(run_mae[confirm_idx]),
            mfe_to_confirm_atr=float(run_mfe[confirm_idx]),
            return_at_confirm_atr=float(confirm_points / atr),
            net_return_at_confirm_atr=float(confirm_points / atr - COST_POINTS / atr),
        )
    return out


def continuation_label(
    market: MarketData,
    regimes: RegimeIndex,
    entry_ns: int,
    direction: int,
    entry_price: float,
    atr: float,
) -> dict:
    """Descriptive post-confirmation outcome (SPEC 8.7), held to the opposing flip.

    This is context only -- the study's primary split is CONFIRMED vs
    STOPPED_BEFORE_CONFIRM from `measure_to_confirm`. It exists so that
    "confirmed" is not reported as a synonym for "profitable": a trade can reach
    its thesis confirmation and still be stopped out, or ride to the opposing
    flip and lose.
    """
    invalid = {"valid": False, "terminal_label_full": CENSORED}
    if atr is None or not np.isfinite(atr) or atr <= 0:
        return invalid

    start = market.index_strictly_after(entry_ns)
    if start >= market.n:
        return invalid

    session_close_ns, session_end = _session_bounds(market, start)
    confirm_ns = regimes.next_start_after(entry_ns, direction, inclusive=True)
    opposing_ns = regimes.next_start_after(entry_ns, -direction, inclusive=True)

    horizon_ns = session_close_ns
    if opposing_ns is not None:
        horizon_ns = min(horizon_ns, opposing_ns)
    end = min(market.index_at_or_after(horizon_ns) + 1, session_end, market.n)
    if end <= start:
        return invalid

    ts, run_mfe, run_mae = _excursions(market, start, end, entry_price, atr, direction)
    stop_idx = _first(run_mae >= STOP_ATR)
    confirm_idx = -1
    if confirm_ns is not None and confirm_ns <= int(ts[-1]):
        confirm_idx = _first(ts >= confirm_ns)
    reached_opposing = opposing_ns is not None and int(ts[-1]) >= opposing_ns - NS

    if stop_idx >= 0 and (confirm_idx < 0 or stop_idx <= confirm_idx):
        label, idx, fills_next = STOPPED_BEFORE_CONFIRM, stop_idx, True
    elif stop_idx >= 0:
        label, idx, fills_next = CONFIRMED_THEN_STOPPED, stop_idx, True
    elif reached_opposing:
        label, idx, fills_next = FINAL_FLIP_EXIT_WINNER, ts.size - 1, False
    else:
        label, idx, fills_next = SESSION_EXIT, ts.size - 1, False

    exit_price, exit_ns = _exit_price(market, start, end, session_end, idx, fills_next)
    points = (exit_price - entry_price) * direction
    gross = 0.0 if abs(points) < FLAT_POINTS else points / atr
    if label == FINAL_FLIP_EXIT_WINNER and gross <= 0:
        label = FINAL_FLIP_EXIT_LOSER

    return {
        "valid": True,
        "terminal_label_full": label,
        "full_exit_ns": int(exit_ns),
        "full_gross_atr": float(gross),
        "full_net_atr": float(gross - COST_POINTS / atr),
        "full_mfe_atr": float(run_mfe[idx]),
        "full_mae_atr": float(run_mae[idx]),
    }

"""Per-trade raw-bar path scanning for path diagnostics -- genuinely new
logic (not reused from any prior study), kept separate and testable per
project pre-execution-testing discipline.

All trades in this population are SHORT (entry_direction == -1): favorable
= price falling. Every function here operates on a SINGLE trade's raw-bar
window and is intentionally direction-agnostic in its parameters (takes
`direction` explicitly) even though this population never exercises the
long branch, so a hand-computed test can cover both without special-casing.
"""
from __future__ import annotations

import numpy as np

NS = 1_000_000_000
MULTIPLIER = 20.0


def excursion_atr(direction: int, entry_px: float, price, atr: float, favorable: bool):
    """Favorable or adverse excursion in ATR units (distance, never
    signed) at the given price(s) (the running low for favorable-short /
    running high for adverse-short, etc. -- caller passes the correct price
    array). `direction` picks the subtraction order ONCE -- do not also
    multiply the result by `direction`, that double-negates it (the exact
    bug this project's own `compute_running_excursions` docstring warns
    about: 'the former bearish branch multiplied already-aligned distances
    by direction a second time')."""
    if direction == -1:
        move = (entry_px - price) if favorable else (price - entry_px)
    elif direction == 1:
        move = (price - entry_px) if favorable else (entry_px - price)
    else:
        raise ValueError(f"direction must be -1 or 1, got {direction}")
    return np.maximum(0.0, move) / atr


def scan_trade_path(ts: np.ndarray, opens: np.ndarray, highs: np.ndarray, lows: np.ndarray,
                    entry_ts: int, entry_px: float, exit_ts: int, direction: int, atr: float,
                    flip_ts: int | None = None) -> dict:
    """Scans raw bars from entry_ts to exit_ts (Policy A's own realized
    exit). Returns running-max favorable/adverse excursion (ATR) over that
    window, plus (if flip_ts is given and falls within [entry_ts, exit_ts]
    or beyond) the max adverse excursion measured up to flip_ts specifically
    (unbounded by Policy A's own exit -- may need bars beyond exit_ts)."""
    i0 = int(np.searchsorted(ts, entry_ts, side="left"))
    if i0 >= len(ts) or int(ts[i0]) != entry_ts:
        raise RuntimeError(f"entry_ts {entry_ts} not found in raw bars")
    if exit_ts > int(ts[-1]):
        raise RuntimeError(f"exit_ts {exit_ts} beyond available raw bars (max {int(ts[-1])})")
    i1 = int(np.searchsorted(ts, exit_ts, side="left"))
    if i1 < i0 or int(ts[i1]) != exit_ts:
        raise RuntimeError(f"exit_ts {exit_ts} not found in raw bars (or precedes entry_ts {entry_ts})")
    window_highs = highs[i0:i1 + 1]
    window_lows = lows[i0:i1 + 1]

    fav_running = excursion_atr(direction, entry_px, window_lows if direction == -1 else window_highs, atr, True)
    adv_running = excursion_atr(direction, entry_px, window_highs if direction == -1 else window_lows, atr, False)
    max_fav_running = np.maximum.accumulate(fav_running)

    result = {
        "max_favorable_excursion_atr": float(fav_running.max()) if len(fav_running) else np.nan,
        "max_adverse_excursion_atr_to_exit": float(adv_running.max()) if len(adv_running) else np.nan,
        "ever_up_atr": {
            th: bool((max_fav_running >= th).any()) for th in (0.25, 0.50, 0.75, 1.00)
        },
    }

    if flip_ts is not None:
        # NaN (unavailable), never a silent truncation, if flip_ts falls
        # beyond this raw-bar file's range -- e.g. a late-December trade
        # whose regime confirms its flip in the next calendar year's file,
        # which is not loaded here. Matches post_flip_mfe_by_regime's own
        # `end_ts > ts_max -> NaN` convention in the pure-flip study.
        if flip_ts > int(ts[-1]):
            result["max_adverse_excursion_atr_before_flip"] = np.nan
        else:
            i_flip = int(np.searchsorted(ts, flip_ts, side="left"))
            if i_flip < i0:
                raise RuntimeError("flip_ts precedes entry_ts")
            flip_highs = highs[i0:i_flip]  # strictly before flip_ts (exclusive
            # upper bound), consistent with the gap-safety fix already applied
            # to post_flip_mfe_by_regime in the pure-flip study.
            max_adverse_before_flip = (
                float(excursion_atr(direction, entry_px,
                                    flip_highs if direction == -1 else lows[i0:i_flip], atr, False).max())
                if i_flip > i0 else 0.0)
            result["max_adverse_excursion_atr_before_flip"] = max_adverse_before_flip

    return result


def align_open_price(ts: np.ndarray, opens: np.ndarray, alignment_ts: int) -> float:
    """First bar at or after alignment_ts -- the raw 1s tick data has
    occasional single-second gaps (confirmed empirically: a quiet second
    with no trade), so an exact-match requirement would spuriously reject
    valid alignment timestamps. Matches `entry_surface.build_surface`'s own
    established "first available bar at or after" fill convention (never
    requires an exact tick at the decision boundary)."""
    i = int(np.searchsorted(ts, alignment_ts, side="left"))
    if i >= len(ts):
        raise RuntimeError(f"alignment_ts {alignment_ts} beyond available raw bars")
    return float(opens[i])


def post_flip_giveback_atr(direction: int, align_open: float, exit_px: float, atr: float,
                           post_align_mfe_atr: float) -> float:
    """post_align_mfe_atr (already computed, reused) minus the realized
    post-alignment move at actual exit, in ATR -- how much of the peak
    favorable move after alignment was given back by exit time."""
    realized_atr = ((align_open - exit_px) if direction == -1
                    else (exit_px - align_open)) / atr
    realized_atr = max(0.0, realized_atr)
    return float(post_align_mfe_atr - realized_atr)

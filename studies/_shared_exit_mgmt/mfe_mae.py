"""Population-agnostic MFE/MAE/giveback canonicalization.

Pure functions only. No population-specific assumptions (no reference
to F2, all-flips, entry delay, etc). Used identically by:
  - the live NT strategy (causal, per-1s-bar running state update)
  - offline atlas builders (post-hoc, over a completed trade's full path)

Sign convention: all magnitudes are canonicalized to be POSITIVE
regardless of trade direction. For a short trade, "favorable" means
price fell, so MFE is measured as (entry_px - low) and MAE as
(high - entry_px) -- the mirror image of a long trade.
"""

from __future__ import annotations


def bar_pnl_mfe_mae(
    direction: int, entry_px: float, bar_high: float,
    bar_low: float, bar_close: float,
) -> dict:
    """Canonical per-bar contribution, anchored to entry_px.

    direction: +1 (long) or -1 (short)
    Returns dict with keys: pnl_close, mfe_bar, mae_bar (all in price
    points, positive-canonicalized per the module docstring).
    """
    if direction == 1:
        pnl_close = bar_close - entry_px
        mfe_bar = bar_high - entry_px
        mae_bar = entry_px - bar_low
    elif direction == -1:
        pnl_close = entry_px - bar_close
        mfe_bar = entry_px - bar_low
        mae_bar = bar_high - entry_px
    else:
        raise ValueError(f"direction must be +1 or -1, got {direction}")
    return {
        "pnl_close": pnl_close,
        "mfe_bar": mfe_bar,
        "mae_bar": mae_bar,
    }


def update_running_extremes(
    running_mfe: float, running_mae: float,
    direction: int, entry_px: float, bar_high: float,
    bar_low: float, bar_close: float,
) -> tuple[float, float]:
    """Advance running (cumulative-max) MFE/MAE given a new bar.

    Causal: caller must only pass bars with ts_init <= current
    decision_ts. Returns (new_running_mfe, new_running_mae).
    """
    contrib = bar_pnl_mfe_mae(direction, entry_px, bar_high, bar_low,
                                 bar_close)
    new_mfe = max(running_mfe, contrib["mfe_bar"])
    new_mae = max(running_mae, contrib["mae_bar"])
    return new_mfe, new_mae


def giveback_atr(mfe_pts: float, current_pnl_pts: float,
                     atr_at_entry: float) -> float:
    """Giveback = distance retraced from the MFE peak, in ATR units.
    Always >= 0 by construction (mfe is a running max of pnl)."""
    safe_atr = atr_at_entry if atr_at_entry and atr_at_entry > 0 else 1.0
    return (mfe_pts - current_pnl_pts) / safe_atr


def to_atr(pts: float, atr_at_entry: float) -> float:
    safe_atr = atr_at_entry if atr_at_entry and atr_at_entry > 0 else 1.0
    return pts / safe_atr

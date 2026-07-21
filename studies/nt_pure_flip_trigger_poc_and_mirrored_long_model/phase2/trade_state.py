"""Pure-Python, NT-independent state machine for the simplified fixed-
stop/regime-flip exit logic -- extracted so it can be hand-tested before
being wired into the NT `Strategy` (per project pre-execution-test
discipline; NT `Strategy` objects are not directly unit-testable without a
running `BacktestEngine`).

Exit logic (per SPEC.md, a strict subset of
`fable5_nt_short_rth_policy_a/strategy.py`'s already-audited state
machine):
  - ONE fixed stop at entry_px + 1.25*atr, placed once, never moved.
  - No confirmation timeout: wait indefinitely for the bearish flip.
  - Once the bearish flip (regime -> -1, confirming the short thesis) has
    been observed, wait for the NEXT opposing bullish flip (regime -> +1)
    and exit there.
  - If the stop touches at ANY point before the opposing-flip exit
    (whether before or after the bearish flip was confirmed), that is the
    exit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FlipTradeState:
    entry_direction: int  # -1 = short (this population); +1 = long (mirrored)
    entry_px: float
    atr: float
    stop_atr_mult: float = 1.25

    bearish_flip_confirmed: bool = False
    bearish_flip_ts: Optional[int] = None
    closed: bool = False
    exit_reason: Optional[str] = None

    stop_px: float = field(init=False)

    def __post_init__(self):
        if self.entry_direction not in (-1, 1):
            raise ValueError(f"entry_direction must be -1 or 1, got {self.entry_direction}")
        if not (self.atr > 0):
            raise ValueError(f"atr must be positive, got {self.atr}")
        # Short: stop is ABOVE entry (price rising is adverse).
        # Long:  stop is BELOW entry (price falling is adverse).
        self.stop_px = (self.entry_px + self.stop_atr_mult * self.atr if self.entry_direction == -1
                        else self.entry_px - self.stop_atr_mult * self.atr)

    def on_regime_update(self, new_regime: int, ts: int) -> Optional[str]:
        """new_regime is the CONFIRMING regime direction (+1 bullish, -1
        bearish) at this 1m close. Returns 'opposing_flip_exit' if this
        update should trigger the exit; None otherwise. Raises if called
        after the trade is already closed (caller bug)."""
        if self.closed:
            raise RuntimeError("on_regime_update called after trade already closed")
        # entry_direction IS the thesis regime: short (-1) theses a bearish
        # (-1) flip; long (+1) theses a bullish (+1) flip. The opposing
        # (exit-triggering) regime is the flip back the other way.
        thesis_regime = self.entry_direction
        opposing_regime = -self.entry_direction
        if not self.bearish_flip_confirmed and new_regime == thesis_regime:
            self.bearish_flip_confirmed = True
            self.bearish_flip_ts = ts
            return None
        if self.bearish_flip_confirmed and new_regime == opposing_regime:
            return "opposing_flip_exit"
        return None

    def on_stop_touch(self) -> str:
        if self.closed:
            raise RuntimeError("on_stop_touch called after trade already closed")
        return "fixed_stop_before_bearish_flip" if not self.bearish_flip_confirmed else "fixed_stop_after_bearish_flip"

    def stop_would_touch(self, high: float, low: float) -> bool:
        """Short: stop touches if bar high >= stop_px. Long: bar low <= stop_px."""
        if self.entry_direction == -1:
            return high >= self.stop_px
        return low <= self.stop_px


def favorable_adverse_points(direction: int, entry_px: float, high: float, low: float) -> tuple[float, float]:
    """(favorable_pts, adverse_pts) at this bar, both >= 0, direction picked
    ONCE via branching -- never multiply the result by `direction` again
    afterward (that double-negates it; this exact bug has recurred multiple
    times this session in path_logic.py's excursion_atr/post_flip_giveback_atr
    and must not recur here)."""
    if direction == -1:
        return max(0.0, entry_px - low), max(0.0, high - entry_px)
    return max(0.0, high - entry_px), max(0.0, entry_px - low)


def unrealized_pnl(direction: int, entry_px: float, close: float, multiplier: float) -> float:
    move = (entry_px - close) if direction == -1 else (close - entry_px)
    return move * multiplier


def realized_favorable_atr(direction: int, entry_px: float, exit_px: float, atr: float) -> float:
    move = (entry_px - exit_px) if direction == -1 else (exit_px - entry_px)
    return max(0.0, move) / atr

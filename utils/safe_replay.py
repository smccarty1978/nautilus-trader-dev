"""Safe Exit Replay Framework.

Permanent methodology gate for offline exit-rule replay studies.
Prevents the "phantom fill" class of bug where a replay credits
fills at a trigger price that never actually traded during the
exit bar.

Core rule: replay may NEVER assume "if price crossed a trigger,
fill at the trigger price." Fills must come from the bar's
actual OHLC range OR from a real tick stream.

Three fill models:
  - `conservative_ohlc`: fill from bar OHLC at trigger time
  - `tick_replay`: fill from tick stream (preferred when available)
  - `idealized`: fill at trigger price exactly (DIAGNOSTIC ONLY,
     never report as tradable economics)

Two stop_invalid_at_arm policies:
  - `market_exit_now` (default, live-realistic): if protect level
    is already breached at arm time, exit at current price (bar
    close in OHLC mode, next tick in tick mode)
  - `skip_rule_and_hold` (diagnostic only): pretend the rule
    didn't arm; fall through to regime exit

Three OHLC fill conventions (when fill_model='conservative_ohlc'):
  - `at_or_worse_close` (default): long fills at min(stop_px, close);
    short fills at max(stop_px, close)
  - `bar_close`: always fill at bar close
  - `worst_in_bar`: long fills at bar.low; short fills at bar.high
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Sequence, Callable
import math


# ---------------- Constants ----------------
NQ_TICK = 0.25
NQ_MULT = 20.0


# ---------------- Validation policies ----------------
class FillModel:
    CONSERVATIVE_OHLC = "conservative_ohlc"
    TICK_REPLAY = "tick_replay"
    IDEALIZED = "idealized"   # diagnostic only

    ALL = (CONSERVATIVE_OHLC, TICK_REPLAY, IDEALIZED)


class OHLCConvention:
    AT_OR_WORSE_CLOSE = "at_or_worse_close"
    BAR_CLOSE = "bar_close"
    WORST_IN_BAR = "worst_in_bar"

    ALL = (AT_OR_WORSE_CLOSE, BAR_CLOSE, WORST_IN_BAR)


class InvalidStopPolicy:
    MARKET_EXIT_NOW = "market_exit_now"           # default
    SKIP_RULE_AND_HOLD = "skip_rule_and_hold"     # diagnostic

    ALL = (MARKET_EXIT_NOW, SKIP_RULE_AND_HOLD)


# ---------------- Config ----------------
@dataclass(frozen=True)
class SafeReplayConfig:
    fill_model: str = FillModel.CONSERVATIVE_OHLC
    ohlc_convention: str = OHLCConvention.AT_OR_WORSE_CLOSE
    invalid_stop_policy: str = InvalidStopPolicy.MARKET_EXIT_NOW
    tick_size: float = NQ_TICK
    multiplier: float = NQ_MULT

    def __post_init__(self):
        # Validate enum-like fields
        if self.fill_model not in FillModel.ALL:
            raise ValueError(
                f"Invalid fill_model: {self.fill_model}; "
                f"must be one of {FillModel.ALL}")
        if self.ohlc_convention not in OHLCConvention.ALL:
            raise ValueError(
                f"Invalid ohlc_convention: {self.ohlc_convention}; "
                f"must be one of {OHLCConvention.ALL}")
        if self.invalid_stop_policy not in InvalidStopPolicy.ALL:
            raise ValueError(
                f"Invalid invalid_stop_policy: "
                f"{self.invalid_stop_policy}; "
                f"must be one of {InvalidStopPolicy.ALL}")


# ---------------- Stop validation ----------------
def round_protect_to_tick(
    protect_px_raw: float, direction: int,
    tick_size: float = NQ_TICK,
) -> float:
    """Round protect_px to a valid tick. Round in the direction
    that makes the stop fire SOONER (more conservative for trader).

    Long protective stop (SELL stop, locks in profit above entry):
      protect is BELOW current price. Round DOWN to nearest tick =
      protect fires sooner if price dips. = round(protect/tick) * tick
      using floor for long (protect_px >= entry).

    Short protective stop (BUY stop, locks in profit below entry):
      protect is ABOVE current price. Round UP to nearest tick =
      protect fires sooner if price rises.
    """
    n_ticks = protect_px_raw / tick_size
    if direction == 1:
        # long: round DOWN (toward zero is fine since prices > 0)
        rounded = math.floor(n_ticks) * tick_size
    elif direction == -1:
        # short: round UP
        rounded = math.ceil(n_ticks) * tick_size
    else:
        raise ValueError(f"direction must be ±1, got {direction}")
    return rounded


def is_on_tick_grid(price: float,
                       tick_size: float = NQ_TICK,
                       atol: float = 1e-9) -> bool:
    """Verify price is a valid tick (multiple of tick_size)."""
    return abs(round(price / tick_size) * tick_size - price) < atol


def validate_stop_at_arm(
    direction: int, current_price: float,
    stop_px: float,
) -> tuple[bool, str | None]:
    """Returns (is_valid, reason_if_invalid).

    Long protective stop is valid iff stop_px < current_price (waits
    for price to fall to stop). Short protective stop is valid iff
    stop_px > current_price (waits for price to rise to stop).

    Strict inequality: equality means "would trigger this tick" =
    "in the market" = invalid.
    """
    if direction == 1:
        if stop_px < current_price:
            return True, None
        return False, (
            f"long stop_px {stop_px:.4f} >= "
            f"current_price {current_price:.4f}; "
            "would trigger immediately ('in market')")
    elif direction == -1:
        if stop_px > current_price:
            return True, None
        return False, (
            f"short stop_px {stop_px:.4f} <= "
            f"current_price {current_price:.4f}; "
            "would trigger immediately ('in market')")
    else:
        raise ValueError(f"direction must be ±1, got {direction}")


# ---------------- Stop fill on OHLC bar ----------------
@dataclass(frozen=True)
class StopFillResult:
    fired: bool                    # did the stop trigger on this bar?
    fill_px: float | None          # fill price (None if not fired)
    fill_ts: int | None            # fill timestamp
    convention_used: str | None    # which OHLC convention applied
    reason: str                    # explanatory tag

    def to_dict(self) -> dict:
        return asdict(self)


def replay_stop_on_bar_ohlc(
    *, direction: int, stop_px: float,
    bar_high: float, bar_low: float, bar_close: float,
    bar_ts_init: int,
    convention: str = OHLCConvention.AT_OR_WORSE_CLOSE,
) -> StopFillResult:
    """Check if a stop triggered on this 1s bar. Return fill details.

    Long stop: triggers if bar.low <= stop_px (price fell to stop).
    Short stop: triggers if bar.high >= stop_px (price rose to stop).

    Fill price by convention:
      - at_or_worse_close: fill at min(stop_px, close) for long;
        max(stop_px, close) for short. Captures most cases —
        if bar closes worse than stop, fill there; else fill at stop.
      - bar_close: always fill at bar close (most pessimistic-realistic).
      - worst_in_bar: long fills at bar.low; short at bar.high
        (assumes you got the worst price in the bar).
    """
    if direction == 1:
        triggered = bar_low <= stop_px
    elif direction == -1:
        triggered = bar_high >= stop_px
    else:
        raise ValueError(f"direction must be ±1, got {direction}")
    if not triggered:
        return StopFillResult(
            fired=False, fill_px=None, fill_ts=None,
            convention_used=None, reason="bar_did_not_cross_stop")

    if convention == OHLCConvention.AT_OR_WORSE_CLOSE:
        if direction == 1:
            fill_px = min(stop_px, bar_close)
        else:
            fill_px = max(stop_px, bar_close)
    elif convention == OHLCConvention.BAR_CLOSE:
        fill_px = bar_close
    elif convention == OHLCConvention.WORST_IN_BAR:
        if direction == 1:
            fill_px = bar_low
        else:
            fill_px = bar_high
    else:
        raise ValueError(f"unknown convention: {convention}")

    return StopFillResult(
        fired=True, fill_px=float(fill_px), fill_ts=int(bar_ts_init),
        convention_used=convention, reason="bar_triggered")


# ---------------- Tick replay ----------------
def replay_stop_on_tick_window(
    *, direction: int, stop_px: float,
    tick_ts: Sequence[int], tick_px: Sequence[float],
) -> StopFillResult:
    """Tick-replay version: scan ticks for first crossing protect_px.
    Fill at THAT tick's price (NOT at stop_px unless they're equal).

    A real broker fills the next tick after trigger. Here we
    approximate by filling at the first tick that crosses (which
    represents the tick that took out the stop).
    """
    if len(tick_ts) == 0:
        return StopFillResult(
            fired=False, fill_px=None, fill_ts=None,
            convention_used=FillModel.TICK_REPLAY,
            reason="no_ticks_in_window")
    for i in range(len(tick_ts)):
        px = tick_px[i]
        if direction == 1 and px <= stop_px:
            return StopFillResult(
                fired=True, fill_px=float(px),
                fill_ts=int(tick_ts[i]),
                convention_used=FillModel.TICK_REPLAY,
                reason="first_tick_crossed")
        if direction == -1 and px >= stop_px:
            return StopFillResult(
                fired=True, fill_px=float(px),
                fill_ts=int(tick_ts[i]),
                convention_used=FillModel.TICK_REPLAY,
                reason="first_tick_crossed")
    return StopFillResult(
        fired=False, fill_px=None, fill_ts=None,
        convention_used=FillModel.TICK_REPLAY,
        reason="no_tick_crossed_stop")


# ---------------- Idealized (diagnostic) ----------------
def replay_stop_on_bar_idealized(
    *, direction: int, stop_px: float,
    bar_high: float, bar_low: float, bar_close: float,
    bar_ts_init: int,
) -> StopFillResult:
    """IDEALIZED diagnostic mode: fill at stop_px exactly when
    bar h/l crosses.

    NEVER report this as tradable economics — it credits fills at
    prices that may not have traded. Used only for sensitivity
    analysis vs realistic models.
    """
    if direction == 1:
        triggered = bar_low <= stop_px
    elif direction == -1:
        triggered = bar_high >= stop_px
    else:
        raise ValueError(f"direction must be ±1, got {direction}")
    if not triggered:
        return StopFillResult(
            fired=False, fill_px=None, fill_ts=None,
            convention_used=FillModel.IDEALIZED,
            reason="bar_did_not_cross_stop")
    return StopFillResult(
        fired=True, fill_px=float(stop_px),
        fill_ts=int(bar_ts_init),
        convention_used=FillModel.IDEALIZED,
        reason="IDEALIZED_NON_EXECUTABLE_at_stop_px")


# ---------------- Invalid-stop policy ----------------
@dataclass(frozen=True)
class InvalidStopAction:
    """What to do when a stop is invalid at arm (already in
    the market). Output is a fill-or-skip directive."""
    action: str            # "exit_now" or "skip"
    fill_px: float | None  # None if skip
    fill_ts: int | None
    reason: str            # human-readable


def apply_invalid_stop_policy(
    *, policy: str, direction: int,
    arm_bar_close: float, arm_bar_ts_init: int,
    invalid_reason: str,
) -> InvalidStopAction:
    """Translate the policy into a concrete action.

    For OHLC mode: "current price" at arm = bar_close at arm bar.
    For tick mode: caller should pass the actual tick price as
    arm_bar_close.
    """
    if policy == InvalidStopPolicy.MARKET_EXIT_NOW:
        return InvalidStopAction(
            action="exit_now",
            fill_px=float(arm_bar_close),
            fill_ts=int(arm_bar_ts_init),
            reason=(f"stop_invalid_at_arm; market exit now at "
                      f"arm-bar close {arm_bar_close:.4f}. "
                      f"Cause: {invalid_reason}"))
    elif policy == InvalidStopPolicy.SKIP_RULE_AND_HOLD:
        return InvalidStopAction(
            action="skip", fill_px=None, fill_ts=None,
            reason=(f"stop_invalid_at_arm; rule SKIPPED, hold "
                      f"to regime exit. Cause: {invalid_reason}"))
    else:
        raise ValueError(f"unknown policy: {policy}")


# ---------------- High-level helper for HH/LL-style rules ----------------
@dataclass(frozen=True)
class StopReplayOutcome:
    """Final outcome for one armed trade after applying safe
    replay logic. Captures all fields needed by audit_replay_fills."""
    fired: bool
    fired_via: str            # "stop_triggered" / "invalid_market_exit"
                              # / "regime_fallback" / "skipped_held_regime"
    arm_ts: int
    arm_price: float          # bar.close at arm time (or current tick px)
    stop_px: float
    stop_invalid_at_arm: bool
    invalid_reason: str | None
    fill_ts: int | None
    fill_px: float | None
    convention_used: str | None
    fill_outside_arm_bar_ohlc: bool   # diagnostic for audit


def safe_stop_replay_armed(
    *, direction: int, stop_px: float, arm_ts: int,
    arm_bar_high: float, arm_bar_low: float, arm_bar_close: float,
    bars_after_arm: list[dict],   # [{ts_init, h, l, c}, ...]
    config: SafeReplayConfig,
) -> StopReplayOutcome:
    """Apply safe replay logic to a single armed stop.

    Steps:
      1. Validate stop at arm (using arm_bar_close as current price proxy)
      2. If invalid → apply policy
      3. If valid → walk forward through bars_after_arm, check trigger
      4. If never triggers → return fired=False (caller falls through
         to regime exit; that's NOT this function's responsibility)
    """
    # Validate
    is_valid, invalid_reason = validate_stop_at_arm(
        direction, arm_bar_close, stop_px)
    if not is_valid:
        action = apply_invalid_stop_policy(
            policy=config.invalid_stop_policy,
            direction=direction,
            arm_bar_close=arm_bar_close,
            arm_bar_ts_init=arm_ts,
            invalid_reason=invalid_reason)
        if action.action == "exit_now":
            return StopReplayOutcome(
                fired=True, fired_via="invalid_market_exit",
                arm_ts=arm_ts, arm_price=arm_bar_close,
                stop_px=stop_px,
                stop_invalid_at_arm=True,
                invalid_reason=invalid_reason,
                fill_ts=action.fill_ts, fill_px=action.fill_px,
                convention_used=config.invalid_stop_policy,
                # market exit at arm bar close: by definition the
                # close is within the arm bar OHLC. Fine.
                fill_outside_arm_bar_ohlc=False)
        else:  # skip
            return StopReplayOutcome(
                fired=False, fired_via="skipped_held_regime",
                arm_ts=arm_ts, arm_price=arm_bar_close,
                stop_px=stop_px,
                stop_invalid_at_arm=True,
                invalid_reason=invalid_reason,
                fill_ts=None, fill_px=None,
                convention_used=config.invalid_stop_policy,
                fill_outside_arm_bar_ohlc=False)

    # Valid stop. Walk forward.
    # First, also check the arm bar itself — same-bar arm + trigger
    # is allowed (matches strategy logic).
    arm_bar_check = replay_stop_on_bar_ohlc(
        direction=direction, stop_px=stop_px,
        bar_high=arm_bar_high, bar_low=arm_bar_low,
        bar_close=arm_bar_close, bar_ts_init=arm_ts,
        convention=config.ohlc_convention)
    if arm_bar_check.fired:
        return StopReplayOutcome(
            fired=True, fired_via="stop_triggered",
            arm_ts=arm_ts, arm_price=arm_bar_close,
            stop_px=stop_px,
            stop_invalid_at_arm=False, invalid_reason=None,
            fill_ts=arm_bar_check.fill_ts,
            fill_px=arm_bar_check.fill_px,
            convention_used=arm_bar_check.convention_used,
            fill_outside_arm_bar_ohlc=False)

    # Walk forward through subsequent bars
    for b in bars_after_arm:
        if config.fill_model == FillModel.IDEALIZED:
            res = replay_stop_on_bar_idealized(
                direction=direction, stop_px=stop_px,
                bar_high=b["h"], bar_low=b["l"],
                bar_close=b["c"], bar_ts_init=b["ts_init"])
        else:
            res = replay_stop_on_bar_ohlc(
                direction=direction, stop_px=stop_px,
                bar_high=b["h"], bar_low=b["l"],
                bar_close=b["c"], bar_ts_init=b["ts_init"],
                convention=config.ohlc_convention)
        if res.fired:
            # Sanity: fill must be in this bar's OHLC range
            outside = not (b["l"] <= res.fill_px <= b["h"])
            return StopReplayOutcome(
                fired=True, fired_via="stop_triggered",
                arm_ts=arm_ts, arm_price=arm_bar_close,
                stop_px=stop_px,
                stop_invalid_at_arm=False, invalid_reason=None,
                fill_ts=res.fill_ts, fill_px=res.fill_px,
                convention_used=res.convention_used,
                fill_outside_arm_bar_ohlc=outside)
    # No trigger ever
    return StopReplayOutcome(
        fired=False, fired_via="regime_fallback",
        arm_ts=arm_ts, arm_price=arm_bar_close, stop_px=stop_px,
        stop_invalid_at_arm=False, invalid_reason=None,
        fill_ts=None, fill_px=None,
        convention_used=None,
        fill_outside_arm_bar_ohlc=False)


# ---------------- MFE-derived protect helpers ----------------
def compute_protect_px_from_mfe(
    entry_price: float, direction: int,
    mfe_pts: float, lock_pct: float,
    tick_size: float = NQ_TICK,
) -> tuple[float, float]:
    """Given MFE-at-arm in points and lock_pct, compute protect_px.

    Returns (raw_protect_px, tick_rounded_protect_px).

    For a long: protect_px = entry + lock_pct * MFE (above entry,
      below MFE peak).
    For a short: protect_px = entry - lock_pct * MFE (below entry,
      above MFE bottom).
    """
    if direction not in (1, -1):
        raise ValueError(f"direction must be ±1, got {direction}")
    raw = entry_price + lock_pct * mfe_pts * direction
    rounded = round_protect_to_tick(raw, direction, tick_size)
    return raw, rounded


def stale_mfe_diagnostic(
    *, entry_price: float, direction: int,
    current_price: float, running_mfe_pts: float,
    protect_px: float,
) -> dict:
    """Diagnostic snapshot at arm time. Helps detect 'stale MFE'
    cases where protect_px is no longer near current price."""
    current_pnl_pts = (current_price - entry_price) * direction
    mfe_to_current_gap_pts = running_mfe_pts - current_pnl_pts
    is_valid, invalid_reason = validate_stop_at_arm(
        direction, current_price, protect_px)
    return {
        "entry_price": float(entry_price),
        "current_price": float(current_price),
        "running_mfe_pts": float(running_mfe_pts),
        "current_pnl_pts": float(current_pnl_pts),
        "mfe_to_current_gap_pts": float(mfe_to_current_gap_pts),
        "protect_px": float(protect_px),
        "protect_px_valid_at_arm": bool(is_valid),
        "invalid_reason": invalid_reason,
    }

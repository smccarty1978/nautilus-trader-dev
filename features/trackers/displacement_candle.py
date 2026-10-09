"""tracker.candle.displacement_1m -- 1-minute displacement candle detector.

Detects when completed 1-minute bar t is a displacement candle relative to prior bar t-1:
- Opposite color: sign(close_t - open_t) != sign(close_{t-1} - open_{t-1})
- Body expansion: abs(close_t - open_t) > abs(close_{t-1} - open_{t-1})
- Wick extreme break:
    If bullish (close_t > open_t): close_t > high_{t-1}
    If bearish (close_t < open_t): close_t < low_{t-1}
- Reversion toward anchor reference price:
    If reference price is provided (or resolved at epoch):
    Reversion requires candle direction toward anchor:
    - Long displacement (close_t > open_t) must be below anchor (close_t < anchor)
    - Short displacement (close_t < open_t) must be above anchor (close_t > anchor)

Fields exposed:
- is_displacement (int): 1 if displacement criteria met on completed bar, else 0
- displacement_dir (int): +1 for bullish displacement, -1 for bearish displacement, 0 if none
- toward_anchor (int): 1 if displacement direction is toward anchor reference price, else 0
- signal (int): 1 if is_displacement and toward_anchor (or no anchor required), else 0
- signal_dir (int): displacement_dir if signal == 1 else 0
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from features.trackers.base import BarView, BaseBinding, EpochView

FIELDS = (
    "is_displacement",
    "displacement_dir",
    "toward_anchor",
    "signal",
    "signal_dir",
    "last_bar_close_ts",
)


class DisplacementCandleBinding(BaseBinding):
    CAPABILITY = "tracker.candle.displacement_1m"
    PARAMS = {"reference": None}  # Optional reference price expression or tracker ref
    INPUTS = {"bars": "stream"}
    FIELDS = FIELDS
    EPOCH_FIELDS = ("signal", "signal_dir", "is_displacement", "toward_anchor")
    EVENTS = ("displacement",)
    WARMUP_BARS = 2
    CADENCE = "per_source_bar"

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        self.prev_bar: Optional[BarView] = None
        self.is_displacement: int = 0
        self.displacement_dir: int = 0
        self.toward_anchor: int = 0
        self.signal: int = 0
        self.signal_dir: int = 0
        self.last_bar_close_ts: Optional[int] = None
        self.last_bar: Optional[BarView] = None

    def on_bar(self, input_key: str, bar: BarView) -> None:
        if input_key != "bars":
            return
        self.last_bar_close_ts = bar.ts_init
        self.last_bar = bar
        self.is_displacement = 0
        self.displacement_dir = 0
        self.toward_anchor = 0
        self.signal = 0
        self.signal_dir = 0

        if self.prev_bar is None:
            self.prev_bar = bar
            return

        p_bar = self.prev_bar
        self.prev_bar = bar

        # 1. Colors
        curr_body = bar.close - bar.open
        prev_body = p_bar.close - p_bar.open

        curr_color = 1 if curr_body > 0 else (-1 if curr_body < 0 else 0)
        prev_color = 1 if prev_body > 0 else (-1 if prev_body < 0 else 0)

        # Opposite color requirement (neither may be a doji with 0 body)
        if curr_color == 0 or prev_color == 0 or curr_color == prev_color:
            return

        # 2. Body expansion: abs(curr_body) > abs(prev_body)
        if abs(curr_body) <= abs(prev_body):
            return

        # 3. Wick extreme break:
        # Bullish: close > prev_high
        # Bearish: close < prev_low
        if curr_color == 1 and bar.close <= p_bar.high:
            return
        if curr_color == -1 and bar.close >= p_bar.low:
            return

        self.is_displacement = 1
        self.displacement_dir = curr_color

        # Toward anchor evaluation if anchor reference price is available on the tracker
        # If no static reference is given, toward_anchor evaluates dynamically in epoch_value.
        # But emit event if displacement occurred:
        self.emit(
            "displacement",
            {
                "ts": bar.ts_init,
                "direction": self.displacement_dir,
                "close": bar.close,
                "open": bar.open,
            },
        )

    def epoch_value(self, name: str, epoch: EpochView) -> Any:
        if name == "is_displacement":
            return self.is_displacement
        if name == "displacement_dir":
            return self.displacement_dir

        # For toward_anchor and signal, check anchor price:
        anchor_val = None
        # Try finding anchor from epoch trackers if available
        for t_name, t_obj in (epoch.trackers or {}).items():
            if t_obj is not self and hasattr(t_obj, "epoch_value"):
                try:
                    anchor_val = t_obj.epoch_value("rth_open", epoch)
                    if anchor_val is not None:
                        break
                except (KeyError, AttributeError):
                    pass

        toward = 0
        if self.is_displacement and anchor_val is not None:
            # Bullish displacement (+1) is toward anchor if bar.close < anchor
            # Bearish displacement (-1) is toward anchor if bar.close > anchor
            c = float(epoch.price)
            a = float(anchor_val)
            if self.displacement_dir == 1 and c < a:
                toward = 1
            elif self.displacement_dir == -1 and c > a:
                toward = 1
        elif self.is_displacement and anchor_val is None:
            # If no anchor tracked, toward is 1 by default
            toward = 1

        if name == "toward_anchor":
            return toward
        if name == "signal":
            return 1 if (self.is_displacement and toward) else 0
        if name == "signal_dir":
            return self.displacement_dir if (self.is_displacement and toward) else 0

        raise KeyError(name)

"""tracker.structure.bos_1m -- 1-minute 3-bar swing pivot and Break-of-Structure (BOS) tracker.

Identifies:
1. 3-bar swing pivots:
   - Swing high at bar i: high[i-1] < high[i] and high[i+1] < high[i].
     Confirmed at completion of bar i+1.
   - Swing low at bar i: low[i-1] > low[i] and low[i+1] > low[i].
     Confirmed at completion of bar i+1.
2. Break of Structure (BOS):
   Occurs strictly AFTER pivot confirmation (i.e. on bar k >= i+2):
   - Bullish BOS: bar k close > confirmed swing high price.
   - Bearish BOS: bar k close < confirmed swing low price.
3. Reversion toward anchor reference price:
   - Bullish BOS (+1) is toward anchor if bar k close < anchor.
   - Bearish BOS (-1) is toward anchor if bar k close > anchor.

Fields exposed:
- is_bos (int): 1 if BOS break occurred on completed bar, else 0
- bos_dir (int): +1 if bullish BOS, -1 if bearish BOS, 0 if none
- toward_anchor (int): 1 if BOS direction is toward anchor, else 0
- signal (int): 1 if is_bos and toward_anchor, else 0
- signal_dir (int): bos_dir if signal == 1 else 0
- last_pivot_price (float): price of the swing pivot that was broken
- last_pivot_ts (int): completion timestamp (ts_init) of the confirmed pivot bar
- last_bar_close_ts (int): completion timestamp of the current bar
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional

from features.trackers.base import BarView, BaseBinding, EpochView

FIELDS = (
    "is_bos",
    "bos_dir",
    "toward_anchor",
    "signal",
    "signal_dir",
    "last_pivot_price",
    "last_pivot_ts",
    "last_bar_close_ts",
)


class StructureBosBinding(BaseBinding):
    CAPABILITY = "tracker.structure.bos_1m"
    PARAMS = {"reference": None}
    INPUTS = {"bars": "stream"}
    FIELDS = FIELDS
    EPOCH_FIELDS = ("signal", "signal_dir", "is_bos", "toward_anchor", "last_pivot_price")
    EVENTS = ("pivot_confirmed", "bos")
    WARMUP_BARS = 3
    CADENCE = "per_source_bar"

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        # Ring buffer of recent bars: [bar_{t-2}, bar_{t-1}, bar_t]
        self._history: List[BarView] = []

        # Confirmed pivots: active swing high and swing low waiting to be broken
        # tuple of (pivot_bar_high, pivot_bar_ts_init, confirmation_bar_ts_init)
        self.active_swing_high: Optional[tuple[float, int, int]] = None
        # tuple of (pivot_bar_low, pivot_bar_ts_init, confirmation_bar_ts_init)
        self.active_swing_low: Optional[tuple[float, int, int]] = None

        # Per-bar state
        self.is_bos: int = 0
        self.bos_dir: int = 0
        self.toward_anchor: int = 0
        self.signal: int = 0
        self.signal_dir: int = 0
        self.last_pivot_price: float = 0.0
        self.last_pivot_ts: int = 0
        self.last_bar_close_ts: Optional[int] = None

    def on_bar(self, input_key: str, bar: BarView) -> None:
        if input_key != "bars":
            return
        self.last_bar_close_ts = bar.ts_init
        self.is_bos = 0
        self.bos_dir = 0
        self.toward_anchor = 0
        self.signal = 0
        self.signal_dir = 0

        self._history.append(bar)
        if len(self._history) < 3:
            return

        # 1. First, check if current bar triggers a BOS against previously confirmed active pivots
        # A pivot confirmed at or before bar_{t-1} is eligible to be broken by bar_t
        # Note: A pivot confirmed on bar_t itself CANNOT be broken on bar_t by definition (requires k >= i+2).
        if self.active_swing_high is not None:
            p_price, p_ts, conf_ts = self.active_swing_high
            # Must be strictly after confirmation bar
            if bar.ts_init > conf_ts and bar.close > p_price:
                self.is_bos = 1
                self.bos_dir = 1
                self.last_pivot_price = p_price
                self.last_pivot_ts = p_ts
                # Consume / clear active swing high once broken
                self.active_swing_high = None
                self.emit(
                    "bos",
                    {
                        "ts": bar.ts_init,
                        "direction": 1,
                        "pivot_price": p_price,
                        "pivot_ts": p_ts,
                        "close": bar.close,
                    },
                )

        if not self.is_bos and self.active_swing_low is not None:
            p_price, p_ts, conf_ts = self.active_swing_low
            if bar.ts_init > conf_ts and bar.close < p_price:
                self.is_bos = 1
                self.bos_dir = -1
                self.last_pivot_price = p_price
                self.last_pivot_ts = p_ts
                # Consume / clear active swing low once broken
                self.active_swing_low = None
                self.emit(
                    "bos",
                    {
                        "ts": bar.ts_init,
                        "direction": -1,
                        "pivot_price": p_price,
                        "pivot_ts": p_ts,
                        "close": bar.close,
                    },
                )

        # 2. Check if the completed bar_t confirms a 3-bar pivot at bar_{t-1}
        # The 3 bars in window are:
        # b0 = bar_{t-2} (index -3)
        # b1 = bar_{t-1} (index -2) -> potential pivot
        # b2 = bar_t (index -1) -> confirmation bar
        b0 = self._history[-3]
        b1 = self._history[-2]
        b2 = self._history[-1]

        # Swing high check: b1.high > b0.high and b1.high > b2.high
        if b1.high > b0.high and b1.high > b2.high:
            self.active_swing_high = (float(b1.high), b1.ts_init, b2.ts_init)
            self.emit(
                "pivot_confirmed",
                {
                    "type": "swing_high",
                    "pivot_ts": b1.ts_init,
                    "confirmation_ts": b2.ts_init,
                    "price": float(b1.high),
                },
            )

        # Swing low check: b1.low < b0.low and b1.low < b2.low
        if b1.low < b0.low and b1.low < b2.low:
            self.active_swing_low = (float(b1.low), b1.ts_init, b2.ts_init)
            self.emit(
                "pivot_confirmed",
                {
                    "type": "swing_low",
                    "pivot_ts": b1.ts_init,
                    "confirmation_ts": b2.ts_init,
                    "price": float(b1.low),
                },
            )

        # Keep history bounded (only last 3 needed for 3-bar pivot detection)
        if len(self._history) > 10:
            self._history = self._history[-5:]

    def epoch_value(self, name: str, epoch: EpochView) -> Any:
        if name == "is_bos":
            return self.is_bos
        if name == "bos_dir":
            return self.bos_dir
        if name == "last_pivot_price":
            return self.last_pivot_price
        if name == "last_pivot_ts":
            return self.last_pivot_ts
        if name == "last_bar_close_ts":
            return self.last_bar_close_ts

        # Anchor lookup for toward_anchor and signal
        anchor_val = None
        for t_name, t_obj in (epoch.trackers or {}).items():
            if hasattr(t_obj, "epoch_value"):
                try:
                    anchor_val = t_obj.epoch_value("rth_open", epoch)
                    if anchor_val is not None:
                        break
                except (KeyError, AttributeError):
                    pass

        toward = 0
        if self.is_bos and anchor_val is not None:
            c = float(epoch.price)
            a = float(anchor_val)
            if self.bos_dir == 1 and c < a:
                toward = 1
            elif self.bos_dir == -1 and c > a:
                toward = 1
        elif self.is_bos and anchor_val is None:
            toward = 1

        if name == "toward_anchor":
            return toward
        if name == "signal":
            return 1 if (self.is_bos and toward) else 0
        if name == "signal_dir":
            return self.bos_dir if (self.is_bos and toward) else 0

        raise KeyError(name)

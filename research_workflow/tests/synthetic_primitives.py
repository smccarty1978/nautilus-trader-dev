"""Synthetic primitives for host tests and the golden fixture.

Deliberately trivial science: a level-based regime with a constant ATR, a pullback depth
counter, and a feature host that copies tracker fields into columns.  If the host cannot
be exercised end-to-end with these, it knows too much.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from features.trackers.host_bindings import BaseBinding
from research_workflow.host.interfaces import REQUIRED, BarView, EmittedEvent, EpochView

NS = 1_000_000_000


class SyntheticRegimeBinding(BaseBinding):
    """dir = +1 when the completed bar close is above ``level``, else -1; ATR is constant."""

    CAPABILITY = "tracker.synthetic.level_regime"
    PARAMS = {"timeframe": REQUIRED, "level": REQUIRED, "atr": 1.0, "instrument": None}
    INPUTS = {"bars": "stream"}
    FIELDS = ("dir", "prev_dir", "atr", "frozen_atr", "start_ns", "start_price", "changed", "flipped", "changed_seq",
              "flipped_seq", "bars", "last_close", "dir_pre_bar_or_current")
    EPOCH_FIELDS = ("age_s",)
    EVENTS = ("regime_bar", "changed", "flipped")

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        self.level = float(self.params["level"])
        self.atr = float(self.params["atr"])
        self.frozen_atr = self.atr
        self.dir = 0
        self.prev_dir = 0
        self.start_ns: Optional[int] = None
        self.start_price: Optional[float] = None
        self.changed = self.flipped = False
        self.changed_seq = self.flipped_seq = 0
        self.bars = 0
        self.last_close: Optional[float] = None
        self._last_close_ts: Optional[int] = None

    @property
    def dir_pre_bar_or_current(self) -> int:
        return self.prev_dir if self.prev_dir != 0 else self.dir

    def on_bar(self, input_key: str, bar: BarView) -> None:
        new = 1 if bar.close > self.level else -1
        old = self.dir
        self.prev_dir, self.dir = old, new
        self.bars += 1
        self.last_close = bar.close
        self.emit("regime_bar", {"close_ts": bar.ts_init, "available_ts": bar.ts_init, "open_ts": bar.ts_event, "direction": new,
                                 "prev_direction": old, "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
                                 "volume": bar.volume, "atr": self.atr, "prev_close_ts": self._last_close_ts})
        self.changed = new != old
        self.flipped = self.changed and old != 0
        if self.changed:
            self.start_ns, self.start_price = bar.ts_init, bar.open
            self.changed_seq += 1
            payload = {"direction": new, "prev_direction": old, "start_ns": bar.ts_init, "close_ts": bar.ts_init,
                       "prev_close_ts": self._last_close_ts, "start_price": bar.open, "atr_start": self.atr,
                       "prior_end_close": bar.close}
            self.emit("changed", payload)
            if self.flipped:
                self.flipped_seq += 1
                self.emit("flipped", payload)
        self._last_close_ts = bar.ts_init

    def epoch_value(self, name: str, epoch: EpochView) -> Any:
        if name == "age_s":
            return None if self.start_ns is None else (epoch.T - self.start_ns) / NS
        raise KeyError(name)


class SyntheticPullbackBinding(BaseBinding):
    """Adverse excursion from the running favorable extreme since the regime start, in ATR."""

    CAPABILITY = "tracker.synthetic.pullback"
    PARAMS = {"threshold_atr": 1.0}
    INPUTS = {"bars": "stream", "regime": "tracker"}
    FIELDS = ("depth_atr", "start_known", "armed", "arm_ts", "favorable_extreme", "new_leg_seq", "arming_cycle_index", "entries")
    EVENTS = ("new_leg",)
    SUBSCRIBES = ("changed",)

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        self.dir = 0
        self.favorable_extreme: Optional[float] = None
        self.depth_atr = 0.0
        self.arm_ts: Optional[int] = None
        self._armed_from: Optional[float] = None
        self.new_leg_seq = 0
        self.arming_cycle_index = -1
        self.entries = 0
        self.start_known = True

    @property
    def armed(self) -> bool:
        return self.arm_ts is not None

    def on_event(self, input_key: str, event: EmittedEvent) -> None:
        if input_key == "regime" and event.name == "changed":
            self.dir = int(event.payload["direction"])
            self.favorable_extreme = float(event.payload["start_price"])
            self.depth_atr = 0.0
            self.arm_ts = None
            self._armed_from = None
            self.arming_cycle_index = -1
            self.entries = 0

    def on_bar(self, input_key: str, bar: BarView) -> None:
        if self.dir == 0 or self.favorable_extreme is None:
            return
        d = self.dir
        ext = bar.high if d == 1 else bar.low
        if (ext > self.favorable_extreme) if d == 1 else (ext < self.favorable_extreme):
            self.favorable_extreme = ext
            if self.arm_ts is not None and self._armed_from is not None and ((ext > self._armed_from) if d == 1 else (ext < self._armed_from)):
                self.new_leg_seq += 1
                self._armed_from = None
                self.emit("new_leg", {"ts": bar.ts_init})
        adverse = bar.low if d == 1 else bar.high
        raw = max(0.0, (self.favorable_extreme - adverse) if d == 1 else (adverse - self.favorable_extreme))
        atr = float(self.inputs["regime"].atr)
        self.depth_atr = raw / atr if atr > 0 else 0.0

    def on_trigger_transition(self, state: str, kind: str, ts: int, epoch: EpochView) -> None:
        if state == "WATCH" and kind == "enter":
            self.arm_ts = int(ts)
            self._armed_from = self.favorable_extreme
            self.arming_cycle_index += 1
        elif state == "WATCH" and kind == "expire":
            self.arm_ts = None
            self._armed_from = None
        elif kind == "entry":
            self.entries += 1


class SyntheticFeatureHost(BaseBinding):
    """Columns are plain references resolved at the epoch (``{column: ref}``)."""

    CAPABILITY = "feature_host.synthetic"
    PARAMS = {"columns": REQUIRED}
    INPUTS = {}
    FIELDS = ("aliases",)
    CADENCE = "per_candidate"

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        self.columns: Dict[str, str] = dict(self.params["columns"])
        self.aliases = tuple(self.columns)

    def snapshot(self, epoch: EpochView, resolve) -> Dict[str, Any]:
        return {col: resolve(ref, epoch) for col, ref in self.columns.items()}


SYNTHETIC_BINDINGS = {
    SyntheticRegimeBinding.CAPABILITY: SyntheticRegimeBinding,
    SyntheticPullbackBinding.CAPABILITY: SyntheticPullbackBinding,
    SyntheticFeatureHost.CAPABILITY: SyntheticFeatureHost,
}

__all__ = ["SyntheticRegimeBinding", "SyntheticPullbackBinding", "SyntheticFeatureHost", "SYNTHETIC_BINDINGS"]

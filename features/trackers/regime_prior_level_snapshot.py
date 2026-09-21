"""tracker.regime.prior_level_snapshot -- the immediately-completed regime, frozen.

One binding per regime tracker (any timeframe ``regime.dual_ema`` supports; nothing here knows the
timeframe). It owns ONE canonical ``RegimeExcursionBinding`` fed exactly like a sibling
``{tracker: regime.excursion, bars: <same>, regime: <same>}``: every source bar, then the regime's
``changed``. On ``changed`` it reads that accumulator BEFORE forwarding the reset, freezes the reading as
the prior regime, then lets the accumulator start the new regime. There is no second extreme/ATR
calculation: every price and ratio below is the excursion object's own state or property at that instant.

Snapshot (all null until the first regime completes; ``rotation_seq`` counts completions):

====================== ====================================================================================
dir                    direction of the completed regime (+1/-1), not of its successor
start_ns               ``start_ns`` of the completed regime (close ts of the bar that established it)
end_ns                 close ts of the ``<tf>`` bar whose ``changed`` terminated it (= successor start_ns)
start_price            the completed regime's ``regime.excursion.start_price`` (= establishing bar OPEN)
end_price              ``regime.excursion.last_close`` immediately before the reset: the close of the LAST
                       source bar the completed regime's accumulator observed (see "end price" below)
end_price_ts           ``ts_init`` of that source bar (``regime.excursion.last_ts``); always <= end_ns
transition_close       close of the terminating ``<tf>`` bar (the ``changed`` payload ``close_price``) --
                       a different quantity from end_price, exposed under its own name, never mixed into it
frozen_atr             the completed regime's frozen ATR (``regime.excursion.frozen_atr``); null if not > 0
duration_s             (end_ns - start_ns) / 1e9
bars                   ``regime.dual_ema.bars_in_regime`` after the last ``<tf>`` bar the regime survived
mfe_price, mae_price   ``highest_high``/``lowest_low`` (dir +1) or ``lowest_low``/``highest_high`` (dir -1)
mfe_atr, mae_atr       ``regime.excursion.mfe_atr``/``mae_atr`` immediately before the reset (bit-equal);
                       null when frozen_atr is null (the excursion tracker reports 0.0 there)
terminal_displacement_atr  ``regime.excursion.pnl_atr`` immediately before the reset
                       = dir * (end_price - start_price) / frozen_atr (bit-equal); null as above
regime_seq             the regime tracker's ``changed_seq`` that established the completed regime
frozen_at_ns           availability clock: the instant the snapshot became readable (= end_ns)
rotation_seq           monotone count of rotations (0 = no completed regime yet)
====================== ====================================================================================

End price.  The mux publishes a closed ``<tf>`` window BEFORE the source bar that closed it, so the regime
tracker's ``changed`` -- and the accumulator's reset -- happen before the terminating window's last source
bar is applied; that bar belongs to the SUCCESSOR's accumulator (and when bars and regime share one stream
the whole terminating bar does). ``end_price`` is therefore the close of the completed regime's last own
source bar, the same set of bars its MFE/MAE came from: ``mae_price <= end_price <= mfe_price`` and
``-mae_atr <= terminal_displacement_atr <= mfe_atr`` always hold. ``transition_close`` (the terminating
bar close at end_ns), the successor's start price (the terminating bar OPEN) and the next bar's open are
three other prices; none of them is ``end_price`` and none is silently substituted for it.

Reset/gap policy.  Rotation happens on the input regime's ``changed`` and nothing else. ``regime.dual_ema``
has no session/day/gap reset and never returns to 0, so the snapshot persists across sessions, halts,
weekends and data gaps. The first ``changed`` (0 -> +/-1) completes no regime and rotates nothing. A
zero-volume closed-window fill bar is a regime bar like any other and can terminate a regime. If no source
bar reached the completed regime's accumulator (its ``last_ts`` predates ``start_ns``), ``end_price``,
``end_price_ts`` and ``terminal_displacement_atr`` are null rather than a pre-regime close.

State is O(1): the current regime's start identity plus one snapshot. No history is retained.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from features.trackers.base import BarView, BaseBinding, EmittedEvent, EpochView

NS = 1_000_000_000

SNAPSHOT_FIELDS = ("dir", "start_ns", "end_ns", "start_price", "end_price", "end_price_ts", "transition_close",
                   "frozen_atr", "duration_s", "bars", "mfe_price", "mae_price", "mfe_atr", "mae_atr",
                   "terminal_displacement_atr", "regime_seq", "frozen_at_ns")


class RegimePriorLevelSnapshotBinding(BaseBinding):
    CAPABILITY = "tracker.regime.prior_level_snapshot"
    PARAMS: Mapping[str, Any] = {}
    INPUTS = {"bars": "stream", "regime": "tracker"}
    FIELDS = SNAPSHOT_FIELDS + ("rotation_seq",)
    EPOCH_FIELDS = ()
    EVENTS = ()
    SUBSCRIBES = ("changed", "regime_bar")
    WARMUP_BARS = 0
    CADENCE = "per_source_bar"

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        from features.trackers.host_bindings import RegimeExcursionBinding
        # the canonical accumulator; progress_gap only drives progress_windows, which is not snapshotted
        self._excursion = RegimeExcursionBinding({}, {"bars": inputs.get("bars"), "regime": inputs.get("regime")})
        self._current_start_ns: Optional[int] = None
        self._current_regime_seq: Optional[int] = None
        self._current_bars = 0
        self.rotation_seq = 0
        for name in SNAPSHOT_FIELDS:
            setattr(self, name, None)

    def on_bar(self, input_key: str, bar: BarView) -> None:
        if input_key == "bars":
            self._excursion.on_bar(input_key, bar)

    def on_event(self, input_key: str, event: EmittedEvent) -> None:
        if input_key != "regime":
            return
        regime = self.inputs["regime"]
        if event.name == "regime_bar":
            # after a bar the regime survived, bars_in_regime is the count the completed regime will carry
            if not regime.changed:
                self._current_bars = int(regime.bars_in_regime)
            return
        if event.name != "changed":
            return
        p = event.payload
        if self._excursion.dir != 0:
            self._freeze(p)
        self._excursion.on_event(input_key, event)   # the reset happens only after the freeze
        self._current_start_ns = int(p["start_ns"])
        self._current_regime_seq = int(regime.changed_seq)
        self._current_bars = 0

    def _freeze(self, p: Mapping[str, Any]) -> None:
        ex = self._excursion
        d = int(ex.dir)
        start_ns = self._current_start_ns
        end_ns = int(p["close_ts"])
        atr_ok = ex.frozen_atr > 0
        observed = ex.last_ts is not None and start_ns is not None and ex.last_ts >= start_ns
        snap = {
            "dir": d,
            "start_ns": start_ns,
            "end_ns": end_ns,
            "start_price": ex.start_price,
            "end_price": ex.last_close if observed else None,
            "end_price_ts": ex.last_ts if observed else None,
            "transition_close": float(p["close_price"]),
            "frozen_atr": ex.frozen_atr if atr_ok else None,
            "duration_s": (end_ns - start_ns) / NS if start_ns is not None else None,
            "bars": self._current_bars,
            "mfe_price": ex.highest_high if d == 1 else ex.lowest_low,
            "mae_price": ex.lowest_low if d == 1 else ex.highest_high,
            "mfe_atr": ex.mfe_atr if atr_ok else None,
            "mae_atr": ex.mae_atr if atr_ok else None,
            "terminal_displacement_atr": ex.pnl_atr if (atr_ok and observed) else None,
            "regime_seq": self._current_regime_seq,
            "frozen_at_ns": end_ns,
        }
        for name in SNAPSHOT_FIELDS:       # replaced whole: every field comes from the same completed regime
            setattr(self, name, snap[name])
        self.rotation_seq += 1

    def snapshot(self) -> dict:
        """The published prior-regime snapshot (read-only copy, for audits and tests)."""
        return {name: getattr(self, name) for name in self.FIELDS}

    def epoch_value(self, name: str, epoch: EpochView) -> Any:
        raise KeyError(name)

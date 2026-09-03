"""Registered tracker bindings for the platform-v2 host.

Each binding is the runtime face of ONE registered primitive.  It wraps -- never
rewrites -- the accepted implementation (``DualEmaRegimeTracker``, the generic feature
providers behind ``ProviderHost``, ``GenericEpisodeGeometryProvider``) and declares, at
class level, everything the static compiler needs: parameters, inputs, readable fields,
emitted/consumed events, warmup and cadence.  The host never imports this module by
name; it loads the ``implementation`` path the compiled plan carries.

Scientific semantics live HERE (or in the provider a binding wraps), not in the host:
the regime formula, the excursion/progress-window rule, the pullback arming rule, the
calendar 5m regime-bar convention, the feature snapshot ATR conventions.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional

from research_workflow.host.interfaces import REQUIRED, BarView, EmittedEvent, EpochView

NS = 1_000_000_000


def _finite_pos(x: Any) -> bool:
    try:
        return x is not None and math.isfinite(float(x)) and float(x) > 0.0
    except (TypeError, ValueError):
        return False


class BaseBinding:
    CAPABILITY = ""
    PARAMS: Mapping[str, Any] = {}
    INPUTS: Mapping[str, str] = {}
    FIELDS: tuple = ()
    EPOCH_FIELDS: tuple = ()
    EVENTS: tuple = ()
    SUBSCRIBES: tuple = ()
    WARMUP_BARS = 0
    CADENCE = "per_source_bar"

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        self.params = dict(params)
        self.inputs = dict(inputs)
        self._events: List[EmittedEvent] = []
        for name, default in self.PARAMS.items():
            if name not in self.params:
                if default is REQUIRED:
                    raise ValueError(f"{self.CAPABILITY}: parameter {name!r} is required")
                self.params[name] = default

    def emit(self, name: str, payload: Mapping[str, Any]) -> None:
        self._events.append(EmittedEvent(name, payload))

    def drain_events(self) -> List[EmittedEvent]:
        out, self._events = self._events, []
        return out

    def on_bar(self, input_key: str, bar: BarView) -> None:  # pragma: no cover - overridden
        return None

    def on_event(self, input_key: str, event: EmittedEvent) -> None:
        return None

    def epoch_value(self, name: str, epoch: EpochView) -> Any:
        raise KeyError(name)

    def on_trigger_transition(self, state: str, kind: str, ts: int, epoch: EpochView) -> None:
        return None


# --------------------------------------------------------------------------- #
# tracker.regime.dual_ema
# --------------------------------------------------------------------------- #
class DualEmaRegimeBinding(BaseBinding):
    """Completed-bar dual-EMA regime with Wilder ATR (``features.trackers.regime_dual_ema``).

    Fields follow the accepted collector vocabulary: ``dir`` is the sticky regime after
    the latest bar, ``prev_dir`` the regime before it, ``start_ns``/``start_price`` the
    close timestamp and OPEN of the bar that established the current regime,
    ``frozen_atr`` the ATR at that bar (0.0 when unwarmed), ``atr`` the latest ATR.
    ``changed`` is true for the bar that established a new non-zero regime (legacy
    ``new_regime != old_regime and new_regime != 0``); ``flipped`` additionally requires
    the old regime to be non-zero.

    Events: ``regime_bar`` on every completed bar (bucket OHLCV + regime + ATR, the
    payload the completed-regime feature adapters consume) and ``changed`` on a regime
    change (payload = the legacy ``_on_regime_flip`` arguments).
    """

    CAPABILITY = "tracker.regime.dual_ema"
    PARAMS = {"timeframe": REQUIRED, "short_period": 3, "long_period": 9, "atr_period": 14, "instrument": None}
    INPUTS = {"bars": "stream", "reference": "stream?"}
    FIELDS = ("dir", "prev_dir", "dir_pre_bar_or_current", "atr", "start_ns", "start_price", "frozen_atr",
              "changed", "flipped", "changed_seq", "flipped_seq", "bars_in_regime", "last_bar_close_ts",
              "last_bar_close", "last_reference_close", "prev_bar_close_ts")
    EPOCH_FIELDS = ("age_s",)
    EVENTS = ("regime_bar", "changed", "flipped")
    SUBSCRIBES = ()
    WARMUP_BARS = 14

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        from features.trackers.regime_dual_ema import DualEmaRegimeTracker
        self._tracker = DualEmaRegimeTracker(
            timeframe=str(self.params["timeframe"]), instrument=self.params.get("instrument"),
            short_period=int(self.params["short_period"]), long_period=int(self.params["long_period"]),
            atr_period=int(self.params["atr_period"]),
        )
        self.WARMUP_BARS = int(self.params["atr_period"])
        self.dir = 0
        self.prev_dir = 0
        self.atr: Optional[float] = None
        self.start_ns: Optional[int] = None
        self.start_price: Optional[float] = None
        self.frozen_atr = 0.0
        self.changed = False
        self.flipped = False
        self.changed_seq = 0
        self.flipped_seq = 0
        self.bars_in_regime = 0
        self.last_bar_close_ts: Optional[int] = None
        self.prev_bar_close_ts: Optional[int] = None
        self.last_bar_close: Optional[float] = None
        self.last_reference_close: Optional[float] = None

    @property
    def dir_pre_bar_or_current(self) -> int:
        return self.prev_dir if self.prev_dir != 0 else self.dir

    def on_bar(self, input_key: str, bar: BarView) -> None:
        if input_key == "reference":
            self.last_reference_close = bar.close
            return
        upd = self._tracker.observe(bar.high, bar.low, bar.close)
        old = upd.previous_regime
        new = upd.regime
        self.prev_dir, self.dir = old, new
        self.atr = upd.atr
        self.prev_bar_close_ts, self.last_bar_close_ts = self.last_bar_close_ts, bar.ts_init
        self.last_bar_close = bar.close
        atr_val = float(self.atr) if self.atr is not None else 0.0
        self.emit("regime_bar", {
            "close_ts": bar.ts_init, "available_ts": bar.ts_init, "open_ts": bar.ts_event,
            "direction": new, "prev_direction": old, "open": bar.open, "high": bar.high,
            "low": bar.low, "close": bar.close, "volume": bar.volume,
            "atr": atr_val if self.atr is not None else float("nan"), "bars_in_regime": upd.bars_in_regime,
        })
        self.changed = new != old and new != 0
        self.flipped = self.changed and old != 0
        if self.changed:
            prior_end_close = self.last_reference_close if self.last_reference_close is not None else bar.close
            self.start_ns = bar.ts_init
            self.start_price = bar.open
            self.frozen_atr = atr_val if atr_val > 0 else 0.0
            self.bars_in_regime = 0
            self.changed_seq += 1
            payload = {"direction": new, "prev_direction": old, "start_ns": bar.ts_init, "close_ts": bar.ts_init,
                       "prev_close_ts": self.prev_bar_close_ts, "start_price": bar.open, "close_price": bar.close,
                       "atr_start": atr_val, "prior_end_close": prior_end_close}
            self.emit("changed", payload)
            if self.flipped:
                self.flipped_seq += 1
                self.emit("flipped", payload)
        else:
            self.bars_in_regime += 1

    def epoch_value(self, name: str, epoch: EpochView) -> Any:
        if name == "age_s":
            return None if self.start_ns is None else (epoch.T - self.start_ns) / NS
        raise KeyError(name)


# --------------------------------------------------------------------------- #
# tracker.regime.excursion
# --------------------------------------------------------------------------- #
class RegimeExcursionBinding(BaseBinding):
    """Running MFE/MAE since the regime start in regime-frozen-ATR units, with the
    legacy progress-window count (a new running MFE extreme counts as a new window when
    at least ``progress_gap`` has elapsed since the previous extreme's bar OPEN) and the
    retained-MFE ratio at the latest completed source bar.
    """

    CAPABILITY = "tracker.regime.excursion"
    PARAMS = {"progress_gap": "120s"}
    INPUTS = {"bars": "stream", "regime": "tracker"}
    FIELDS = ("dir", "frozen_atr", "atr", "mfe_atr", "mae_atr", "pnl_atr", "retained_ratio", "progress_windows",
              "start_price", "highest_high", "lowest_low", "last_close", "last_ts")
    EPOCH_FIELDS = ()
    EVENTS = ()
    SUBSCRIBES = ("changed",)

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        from research_workflow.grammar.spec import duration_seconds
        self._gap_ns = duration_seconds(self.params["progress_gap"]) * NS
        self.dir = 0
        self.frozen_atr = 0.0
        self.start_price = 0.0
        self.highest_high = -math.inf
        self.lowest_low = math.inf
        self.progress_windows = 0
        self._progress_prev_extreme = 0.0
        self._progress_last_ts: Optional[int] = None
        self.last_close: Optional[float] = None
        self.last_ts: Optional[int] = None

    @property
    def atr(self) -> float:
        return self.frozen_atr

    def on_event(self, input_key: str, event: EmittedEvent) -> None:
        if input_key != "regime" or event.name != "changed":
            return
        p = event.payload
        self.dir = int(p["direction"])
        self.start_price = float(p["start_price"])
        self.frozen_atr = float(p["atr_start"]) if float(p["atr_start"]) > 0 else 0.0
        self.highest_high = self.start_price
        self.lowest_low = self.start_price
        self._progress_prev_extreme = 0.0
        self._progress_last_ts = None
        self.progress_windows = 0

    def on_bar(self, input_key: str, bar: BarView) -> None:
        self.last_close = bar.close
        self.last_ts = bar.ts_init
        if self.dir == 0:
            return
        if bar.high > self.highest_high:
            self.highest_high = bar.high
        if bar.low < self.lowest_low:
            self.lowest_low = bar.low
        current = self.mfe_atr
        if current > self._progress_prev_extreme + 1e-12:
            if self._progress_last_ts is None or (bar.ts_event - self._progress_last_ts) >= self._gap_ns:
                self.progress_windows += 1
            self._progress_last_ts = bar.ts_event
            self._progress_prev_extreme = current

    @property
    def mfe_atr(self) -> float:
        if self.frozen_atr <= 0:
            return 0.0
        if self.dir == 1:
            return max(0.0, self.highest_high - self.start_price) / self.frozen_atr
        return max(0.0, self.start_price - self.lowest_low) / self.frozen_atr

    @property
    def mae_atr(self) -> float:
        if self.frozen_atr <= 0:
            return 0.0
        if self.dir == 1:
            return max(0.0, self.start_price - self.lowest_low) / self.frozen_atr
        return max(0.0, self.highest_high - self.start_price) / self.frozen_atr

    @property
    def pnl_atr(self) -> float:
        if self.frozen_atr <= 0 or self.last_close is None:
            return 0.0
        return (self.dir * (self.last_close - self.start_price)) / self.frozen_atr

    @property
    def retained_ratio(self) -> float:
        mfe = self.mfe_atr
        return (self.pnl_atr / mfe) if mfe > 0 else 0.0


# --------------------------------------------------------------------------- #
# tracker.regime_bar.calendar_bucket
# --------------------------------------------------------------------------- #
class CalendarRegimeBarBinding(BaseBinding):
    """Calendar-boundary regime bars from a lower-timeframe completed stream.

    Accepted compact-collector convention: at a source bar whose ``ts_init`` is a
    multiple of ``bucket``, publish one regime bar carrying the OHLC accumulated since
    the previous boundary (whatever source bars printed), the close of this source bar,
    the regime direction *before* this bar was applied (falling back to the current
    direction while unestablished) and the regime tracker's latest ATR (0.0 while
    unwarmed).  Nothing is published between boundaries and no completeness is
    required -- that is the historical semantics this binding preserves by name.
    """

    CAPABILITY = "tracker.regime_bar.calendar_bucket"
    PARAMS = {"bucket": REQUIRED}
    INPUTS = {"bars": "stream", "regime": "tracker"}
    FIELDS = ("last_close_ts",)
    EVENTS = ("regime_bar",)

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        from research_workflow.grammar.spec import duration_seconds
        self._bucket_ns = duration_seconds(self.params["bucket"]) * NS
        self._open: Optional[float] = None
        self._high = -math.inf
        self._low = math.inf
        self._volume = 0.0
        self.last_close_ts: Optional[int] = None

    def on_bar(self, input_key: str, bar: BarView) -> None:
        if self._open is None:
            self._open = bar.open
        self._high = max(self._high, bar.high)
        self._low = min(self._low, bar.low)
        self._volume += bar.volume
        if bar.ts_init % self._bucket_ns == 0:
            regime = self.inputs["regime"]
            atr = regime.atr if regime.atr is not None else 0.0
            self.last_close_ts = bar.ts_init
            self.emit("regime_bar", {
                "close_ts": bar.ts_init, "available_ts": bar.ts_init, "open_ts": bar.ts_init - self._bucket_ns,
                "direction": int(regime.dir_pre_bar_or_current), "prev_direction": int(regime.prev_dir),
                "open": self._open, "high": self._high, "low": self._low, "close": bar.close,
                "volume": self._volume, "atr": float(atr),
            })
            self._open = None
            self._high, self._low, self._volume = -math.inf, math.inf, 0.0


# --------------------------------------------------------------------------- #
# tracker.pullback.depth_since_extreme  (deep-pullback episode lifecycle state)
# --------------------------------------------------------------------------- #
class PullbackEpisodeBinding(BaseBinding):
    """Directional pullback depth since the prevailing regime's favorable extreme.

    Accepted semantics (sealed deep-pullback contract; ``research_workflow.population_runtime``):

    * favorable extreme tracked from completed source bars since the prevailing regime
      start (start price = the regime's start price); a new extreme resets the pending
      pullback start and terminates any in-progress geometry episode;
    * ``depth_atr`` = raw adverse excursion from that extreme / the latest completed
      ``atr_source`` ATR (0 while unwarmed) -- the ATR of the observation that crosses
      the threshold is frozen as ``frozen_atr_arm`` when the trigger graph enters its
      arming state (``on_trigger_transition('WATCH', 'enter')``);
    * ``start_known`` commits the pending pullback start the first time depth reaches
      ``threshold_atr`` while unarmed (re-checked at every sub-epoch, so a mid-bar
      re-arm never reaches the arming state without a start);
    * a favorable extreme beyond the armed-from extreme while armed starts a new leg
      (``new_leg`` event); a prevailing regime change re-initialises everything
      (``terminated`` event);
    * counter-regime identity from the completed intermediate regime tracker.

    Geometry outputs are produced by ``GenericEpisodeGeometryProvider`` (the same
    provider the sealed study used) and handed to the feature host through
    ``geometry_snapshot``.
    """

    CAPABILITY = "tracker.pullback.depth_since_extreme"
    PARAMS = {"threshold_atr": REQUIRED, "extreme_source": "prevailing_directional_extreme"}
    INPUTS = {"bars": "stream", "regime": "tracker", "atr_source": "tracker", "intermediate": "tracker"}
    FIELDS = ("dir", "depth_atr", "start_known", "armed", "arm_ts", "frozen_atr_arm", "pullback_start_ts",
              "prevailing_extreme_ts", "favorable_extreme", "arming_cycle_index", "prior_deep_pullback_count",
              "episode_id", "counter_regime_direction", "counter_regime_close_ts", "new_leg_seq", "terminated_seq",
              "prevailing_regime_start_ns", "max_depth_points")
    EPOCH_FIELDS = ("counter_close_ts_at", "counter_direction_at", "triggering_event_close_ts")
    EVENTS = ("new_leg", "terminated")
    SUBSCRIBES = ("changed", "regime_bar")

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        from features.trackers.generic_episode_geometry import GenericEpisodeGeometryProvider
        self._threshold = float(self.params["threshold_atr"])
        self._geom = GenericEpisodeGeometryProvider()
        self._geom_active = False
        self.max_depth_points = 0.0
        self.dir = 0
        self.prevailing_regime_start_ns: Optional[int] = None
        self.favorable_extreme: Optional[float] = None
        self.prevailing_extreme_ts: Optional[int] = None
        self._extreme_epoch = 0
        self._armed_from_extreme: Optional[float] = None
        self._pending_start: Optional[int] = None
        self.pullback_start_ts: Optional[int] = None
        self._pending_arm_atr: Optional[float] = None
        self.frozen_atr_arm: Optional[float] = None
        self.arm_ts: Optional[int] = None
        self.arming_cycle_index = -1
        self.prior_deep_pullback_count = 0
        self.episode_id: Optional[str] = None
        self.counter_regime_direction = 0
        self.counter_regime_close_ts: Optional[int] = None
        self.depth_atr = 0.0
        self._raw_adverse = 0.0
        self.new_leg_seq = 0
        self.terminated_seq = 0
        self._last_ts: Optional[int] = None

    # -- inputs ----------------------------------------------------------------
    @property
    def armed(self) -> bool:
        return self.arm_ts is not None

    def on_event(self, input_key: str, event: EmittedEvent) -> None:
        if input_key == "regime" and event.name == "changed":
            p = event.payload
            direction = int(p["direction"])
            if direction not in (-1, 1):
                return
            self.dir = direction
            self.prevailing_regime_start_ns = int(p["start_ns"])
            self.favorable_extreme = float(p["start_price"])
            self.prevailing_extreme_ts = int(p["start_ns"])
            self._extreme_epoch = 0
            self._armed_from_extreme = None
            self._pending_start = None
            self.pullback_start_ts = None
            self._pending_arm_atr = None
            self.frozen_atr_arm = None
            self.arm_ts = None
            self.arming_cycle_index = -1
            self.prior_deep_pullback_count = 0
            self.episode_id = None
            self.counter_regime_direction = 0
            self.counter_regime_close_ts = None
            if self._geom_active:
                self._geom.terminate_episode()
            self._geom_active = False
            self.max_depth_points = 0.0
            self.terminated_seq += 1
            self.emit("terminated", {"ts": int(p["start_ns"])})
        elif input_key == "intermediate" and event.name == "regime_bar":
            # The completed intermediate regime that just closed; the counter identity is
            # the close of the intermediate bar that carries the opposite-prevailing regime
            # when that regime was entered by a transition (legacy: transitions only).
            p = event.payload
            if self.dir in (-1, 1) and int(p["direction"]) == -self.dir and int(p["prev_direction"]) != -self.dir:
                self.counter_regime_direction = -self.dir
                self.counter_regime_close_ts = int(p["close_ts"])

    def on_bar(self, input_key: str, bar: BarView) -> None:
        if input_key != "bars" or self.dir == 0 or self.favorable_extreme is None:
            return
        d = self.dir
        ts_init = bar.ts_init
        self._last_ts = ts_init
        extreme_candidate = bar.high if d == 1 else bar.low
        made_new = extreme_candidate > self.favorable_extreme if d == 1 else extreme_candidate < self.favorable_extreme
        if made_new:
            self.favorable_extreme = extreme_candidate
            self.prevailing_extreme_ts = ts_init
            self._pending_start = None
            if self._geom_active:
                self._geom.terminate_episode()
                self._geom_active = False
                self.max_depth_points = 0.0
            if self.arm_ts is not None and self._armed_from_extreme is not None and (
                extreme_candidate > self._armed_from_extreme if d == 1 else extreme_candidate < self._armed_from_extreme
            ):
                self._extreme_epoch += 1
                self._armed_from_extreme = None
                self.new_leg_seq += 1
                self.emit("new_leg", {"ts": ts_init})
        adverse_price = bar.low if d == 1 else bar.high
        raw_adverse = max(0.0, (self.favorable_extreme - adverse_price) if d == 1 else (adverse_price - self.favorable_extreme))
        self._raw_adverse = raw_adverse
        if raw_adverse > 0.0 and self._pending_start is None:
            self._pending_start = ts_init
        atr_val = self.inputs["atr_source"].atr
        atr = float(atr_val) if atr_val is not None and float(atr_val) > 0.0 else None
        self.depth_atr = (raw_adverse / atr) if atr is not None else 0.0
        self._pending_arm_atr = atr
        self._commit_start()
        if raw_adverse > 0.0 and not self._geom_active and self._pending_start is not None:
            self._geom.start_episode(start_ns=int(self._pending_start), direction=d,
                                     favorable_extreme_price=float(self.favorable_extreme))
            self._geom_active = True
            self.max_depth_points = 0.0
        if self._geom_active:
            self.max_depth_points = max(self.max_depth_points, raw_adverse)
            if atr is not None:
                self._geom.observe_completed_1s(close_ts=ts_init, high=bar.high, low=bar.low,
                                                arm_atr=float(atr), arm_threshold_atr=self._threshold)
        inter = self.inputs["intermediate"]
        if inter.dir in (-1, 1) and int(inter.dir) == -d:
            self.counter_regime_direction = -d

    def _commit_start(self) -> None:
        if (self.arm_ts is None and self.pullback_start_ts is None and self._pending_start is not None
                and self.depth_atr >= self._threshold):
            self.pullback_start_ts = self._pending_start

    @property
    def start_known(self) -> bool:
        self._commit_start()
        return self.pullback_start_ts is not None

    # -- trigger lifecycle ------------------------------------------------------
    def on_trigger_transition(self, state: str, kind: str, ts: int, epoch: EpochView) -> None:
        if kind == "enter" and state == str(self.params.get("arm_state", "WATCH")):
            from research.analysis.identity import canonical_sha256
            self.frozen_atr_arm = self._pending_arm_atr
            self.arm_ts = int(ts)
            self._armed_from_extreme = self.favorable_extreme
            self.arming_cycle_index += 1
            self.episode_id = canonical_sha256({
                "prevailing_regime_id": str(self.prevailing_regime_start_ns),
                "favorable_extreme_id": f"{self.prevailing_regime_start_ns}:{self._extreme_epoch}",
                "arm_ts": int(ts),
            })[:32]
        elif kind == "expire" and state == str(self.params.get("arm_state", "WATCH")):
            self.frozen_atr_arm = None
            self.arm_ts = None
            self._armed_from_extreme = None
            self.pullback_start_ts = None
            self._pending_start = int(ts) if self.depth_atr > 0.0 else None
        elif kind == "entry":
            self.prior_deep_pullback_count += 1

    # -- epoch values -----------------------------------------------------------
    def epoch_value(self, name: str, epoch: EpochView) -> Any:
        ev = epoch.event
        if name == "triggering_event_close_ts":
            return int(ev["close_ts"]) if ev is not None and ev.get("close_ts") is not None else int(epoch.T)
        if name == "counter_close_ts_at":
            if ev is not None and ev.get("prev_direction") == -self.dir and ev.get("prev_close_ts") is not None:
                return int(ev["prev_close_ts"])
            if self.counter_regime_close_ts is not None and self.counter_regime_direction == -self.dir:
                return int(self.counter_regime_close_ts)
            return -1
        if name == "counter_direction_at":
            if ev is not None and ev.get("prev_direction") == -self.dir and ev.get("prev_close_ts") is not None:
                return -self.dir
            if self.counter_regime_close_ts is not None and self.counter_regime_direction == -self.dir:
                return -self.dir
            return 0
        raise KeyError(name)

    def geometry_snapshot(self, *, candidate_ts: int, candidate_price: float, candidate_atr: float) -> Dict[str, Any]:
        base = {
            "max_depth_points": self.max_depth_points,
            "seconds_since_prevailing_directional_extreme": (
                (int(candidate_ts) - int(self.prevailing_extreme_ts)) / NS
                if self.prevailing_extreme_ts is not None else None),
        }
        keys = ("pullback_max_depth_atr", "pullback_current_depth_atr", "pullback_recovery_from_extreme_atr",
                "pullback_fraction_of_structural_move", "pullback_elapsed_seconds", "pullback_post_arm_seconds")
        if not self._geom_active or self.arm_ts is None:
            return {**base, **{k: None for k in keys}}
        geom = self._geom.candidate_snapshot(candidate_ts=int(candidate_ts), candidate_price=float(candidate_price),
                                             candidate_atr=float(candidate_atr), structural_expansion_points=None)
        return {**base, **{k: geom.get(k) for k in keys}}


# --------------------------------------------------------------------------- #
# feature_host.provider_host
# --------------------------------------------------------------------------- #
class FeatureHostBinding(BaseBinding):
    """The declared feature surface, realised by ``research_workflow.provider_host.ProviderHost``.

    Routing (``params['routing']``) names which host stream / tracker event feeds each
    normalized ProviderHost event; ``params['snapshot']`` names the ATR conventions and
    the population-supplied episode state.  Both come from the compiled plan.
    """

    CAPABILITY = "feature_host.provider_host"
    PARAMS = {"instances": REQUIRED, "routing": REQUIRED, "snapshot": REQUIRED, "feature_authority": "active"}
    INPUTS = {}   # dynamic: one input per routing entry (compiler expands)
    FIELDS = ("aliases",)
    EPOCH_FIELDS = ("structural_snapshot_ready",)
    EVENTS = ()
    SUBSCRIBES = ("regime_bar", "changed")
    CADENCE = "per_source_event"

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        from research_workflow.provider_host import ProviderHost
        compiled = {"contracts": {"feature_contract": {"runtime_data_requirements": {
            "resolved_instances": list(self.params["instances"])}}}}
        self._host = ProviderHost.from_feature_contract(compiled, feature_authority=str(self.params["feature_authority"]))
        self.aliases = tuple(spec.physical_alias for spec in self._host.instances)
        self.routing: Dict[str, Dict[str, Any]] = dict(self.params["routing"])
        self.snapshot_spec: Dict[str, Any] = dict(self.params["snapshot"])
        unbound = self._host.verify_bindings()
        if not unbound["passed"]:
            raise RuntimeError(f"FEATURE_OUTPUT_BINDING_MISSING: {unbound['unbound']}")

    def on_bar(self, input_key: str, bar: BarView) -> None:
        from research_workflow.provider_host import STREAM_COMPLETED_1M, STREAM_COMPLETED_1S
        route = self.routing.get(input_key) or {}
        if input_key == "completed_1s":
            self._host.dispatch(STREAM_COMPLETED_1S, {
                "ts_init": bar.ts_init, "open": bar.open, "high": bar.high, "low": bar.low,
                "close": bar.close, "volume": bar.volume})
        elif input_key == "completed_1m":
            regime = self.inputs.get("completed_1m_regime")
            direction = int(regime.dir) if regime is not None else 0
            atr = float(regime.atr) if regime is not None and regime.atr is not None else 0.0
            self._host.dispatch(STREAM_COMPLETED_1M, {
                "ts_init": bar.ts_init, "close_ts": bar.ts_init, "direction": direction,
                "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
                "volume": 0.0, "atr": atr})
        else:
            raise RuntimeError(f"FEATURE_HOST_UNROUTED_BAR: {input_key}")

    def on_event(self, input_key: str, event: EmittedEvent) -> None:
        from research_workflow.provider_host import (
            EVENT_REGIME_TRANSITION_1M, STREAM_COMPLETED_5M, STREAM_COMPLETED_5S)
        route = self.routing.get(input_key) or {}
        p = event.payload
        if input_key in ("completed_5m", "completed_5s") and event.name == "regime_bar":
            if route.get("ready_gate", False):
                if int(p["direction"]) not in (-1, 1) or not _finite_pos(p.get("atr")):
                    return
            self._host.dispatch(STREAM_COMPLETED_5M if input_key == "completed_5m" else STREAM_COMPLETED_5S, {
                "close_ts": int(p["close_ts"]), "available_ts": int(p["available_ts"]),
                "direction": int(p["direction"]), "open": float(p["open"]), "high": float(p["high"]),
                "low": float(p["low"]), "close": float(p["close"]), "atr": float(p["atr"])})
        elif input_key == "regime_transition_1m" and event.name == "changed":
            if route.get("requires_atr", True) and not (float(p["atr_start"]) > 0.0):
                return
            self._host.dispatch(EVENT_REGIME_TRANSITION_1M, {
                "direction": int(p["direction"]), "start_ns": int(p["start_ns"]),
                "start_price": float(p["start_price"]), "atr_start": float(p["atr_start"]),
                "prior_end_close": float(p["prior_end_close"])})

    def epoch_value(self, name: str, epoch: EpochView) -> Any:
        if name == "structural_snapshot_ready":
            # Accepted compact-collector population rule: a checkpoint whose structural
            # geometry cannot be snapshotted (no completed prior 1m/5m regime, forming 5m
            # state, invalid start ATR, non-positive expansion) emits no row.
            from research_workflow.provider_host import StructuralGeometryAdapter
            for adapter in self._host.adapters:
                if isinstance(adapter, StructuralGeometryAdapter):
                    tracker = adapter._provider._tracker
                    return bool(tracker.can_snapshot(int(epoch.T), adapter._five_close_ts))
            return True
        raise KeyError(name)

    def snapshot(self, epoch: EpochView, resolve) -> Dict[str, Any]:
        """Realise the full declared surface at this epoch; ``resolve`` evaluates plan refs."""
        spec = self.snapshot_spec
        atr = resolve(spec["atr"], epoch)
        atr = float(atr) if _finite_pos(atr) else 1e-9
        fam = resolve(spec["family_a_atr"], epoch) if spec.get("family_a_atr") else None
        fam = float(fam) if _finite_pos(fam) else atr
        episode_state: Dict[str, Any] = {}
        for key, ref in (spec.get("episode_state") or {}).items():
            if key == "episode_geometry":
                tracker = resolve(ref, epoch)
                episode_state[key] = tracker.geometry_snapshot(candidate_ts=int(epoch.T), candidate_price=float(epoch.price),
                                                               candidate_atr=atr)
            else:
                episode_state[key] = resolve(ref, epoch)
        return dict(self._host.snapshot(decision_ts=int(epoch.T), price=float(epoch.price), atr=atr,
                                        episode_state=episode_state, family_a_atr=fam))


# --------------------------------------------------------------------------- #
# feature.frozen_external_score  (derived causal input: another study's frozen model)
# --------------------------------------------------------------------------- #
class FrozenExternalScoreBinding(BaseBinding):
    """A frozen parent model's score at the candidate, as one output column.

    Wraps ``research_workflow.external_model_scoring.FrozenExternalModelScorer``: the
    parent's ordered feature surface is read off the realised candidate row, the arm is
    selected by the candidate direction, and a null input yields a null score (never a
    fabricated value).  The parent study directory is resolved under ``studies_root``
    (a machine-local location the runner supplies; never part of the plan identity).
    """

    CAPABILITY = "feature.frozen_external_score"
    PARAMS = {"spec": REQUIRED, "direction": REQUIRED, "studies_root": None}
    INPUTS = {}
    CADENCE = "per_candidate"
    NEEDS_STUDIES_ROOT = True

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        from pathlib import Path
        from research.schemas.study_spec import DerivedCausalInputSpec
        from research_workflow.external_model_scoring import FrozenExternalModelScorer
        spec = DerivedCausalInputSpec.model_validate(self.params["spec"])
        root = self.params.get("studies_root")
        if not root:
            raise RuntimeError("FROZEN_EXTERNAL_SCORE_STUDIES_ROOT_MISSING")
        parent_dir = Path(root) / (spec.parent_study_id or "_model_id_binding")
        self._scorer = FrozenExternalModelScorer.bind(spec, parent_dir=parent_dir)
        self.name = spec.name
        self._surface = {"LONG": self._scorer.ordered_inputs("LONG"), "SHORT": self._scorer.ordered_inputs("SHORT")}
        self.direction_ref = str(self.params["direction"])

    def derive(self, row: Mapping[str, Any], epoch: EpochView, resolve) -> Any:
        direction = "LONG" if int(resolve(self.direction_ref, epoch) or 0) == 1 else "SHORT"
        surf = self._surface.get(direction) or []
        if not surf:
            return None
        inputs = {n: row.get(n) for n in surf}
        if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in inputs.values()):
            return None
        ts = int(epoch.T)
        # RT-B2: `ts` (the completed-bar epoch driving this binding) is both the checkpoint and
        # the instant the score is actually evaluated at (synchronous, in-process scoring) --
        # pass it explicitly as `score_evaluation_ts` rather than relying on the scorer's default.
        # Per-input availability: this binding has no finer-grained per-column availability table
        # wired to it (the row is already causally gated upstream by Feature System V2 visibility
        # rules), so `ts` is used as a documented conservative upper bound for every input, and
        # that provenance is recorded on the observation rather than silently assumed.
        obs = self._scorer.score(
            inputs,
            checkpoint_ts=ts,
            direction=direction,
            availability_ts={n: ts for n in surf},
            score_evaluation_ts=ts,
            availability_source="checkpoint_ts_upper_bound",
        )
        return float(obs.score)


TRACKER_BINDINGS: Dict[str, type] = {
    DualEmaRegimeBinding.CAPABILITY: DualEmaRegimeBinding,
    RegimeExcursionBinding.CAPABILITY: RegimeExcursionBinding,
    CalendarRegimeBarBinding.CAPABILITY: CalendarRegimeBarBinding,
    PullbackEpisodeBinding.CAPABILITY: PullbackEpisodeBinding,
    FeatureHostBinding.CAPABILITY: FeatureHostBinding,
    FrozenExternalScoreBinding.CAPABILITY: FrozenExternalScoreBinding,
}


def implementation_path(cls: type) -> str:
    return f"{cls.__module__}.{cls.__name__}"


__all__ = ["BaseBinding", "DualEmaRegimeBinding", "RegimeExcursionBinding", "CalendarRegimeBarBinding",
           "PullbackEpisodeBinding", "FeatureHostBinding", "FrozenExternalScoreBinding", "TRACKER_BINDINGS", "implementation_path"]

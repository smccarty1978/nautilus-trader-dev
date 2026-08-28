"""Adapter-based generic runtime feature host.

The seven canonical generic feature providers in ``features/trackers/generic_*.py``
are trusted primitives with mature, individually audited causal semantics -- but each
exposes a *different* lifecycle API (``start_episode`` / ``observe_completed_1s`` /
``candidate_snapshot`` vs ``on_5m_bar`` / ``snapshot`` vs ``on_completed_bar`` /
``prior_snapshot`` ...). There is no uniform runtime surface a collector can drive
generically, and no way for ``research_workflow/runtime_bindings.py`` to statically
prove that every compiled ``FeatureInstance`` has an executable binding.

``ProviderHost`` is that uniform surface. It is deliberately thin:

  * a narrow internal ``RuntimeProviderAdapter`` protocol
    (``required_streams`` / ``on_event`` / ``snapshot``);
  * one adapter per canonical provider *family*, wrapping -- never rewriting -- the
    existing provider and translating normalized runtime events to that provider's
    own lifecycle methods;
  * a deterministic ``ADAPTER_REGISTRY`` mapping canonical provider class path ->
    adapter factory (no study-specific branches);
  * ``ProviderHost.from_feature_contract`` which resolves every ``FeatureInstance``
    to an adapter, groups compatible instances, instantiates only required adapters,
    and can produce the full candidate-time snapshot and machine-readable binding
    metadata.

Population runtime (``EpisodePopulationEngine``) is intentionally NOT here -- the
population layer decides *when* a candidate row exists; ``ProviderHost`` decides
*what* feature values that row carries. The two meet only at
``ProviderHost.snapshot(decision_ts, price, atr, episode_state)``, where
``episode_state`` is the population-supplied causal context (armed flag, prevailing
direction, prevailing-extreme timestamp, prior-episode count, counter-regime state).

STAGE 1 SCOPE: this module + adapters + registry + realizability metadata + synthetic
tests only. It is not yet wired into ``FlipPredictionCollector``; existing studies
(compact / fused-ring / exploratory paths) are untouched.
"""
from __future__ import annotations

import importlib
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

NS = 1_000_000_000

# Normalized runtime event vocabulary. Adapters subscribe to a subset of these.
STREAM_COMPLETED_1S = "completed_1s"
STREAM_COMPLETED_1M = "completed_1m"
STREAM_COMPLETED_5M = "completed_5m"
STREAM_COMPLETED_5S = "completed_5s"
ALL_STREAMS = frozenset({
    STREAM_COMPLETED_1S, STREAM_COMPLETED_1M, STREAM_COMPLETED_5M, STREAM_COMPLETED_5S,
})

# Additional normalized lifecycle events (not data streams).
EVENT_REGIME_TRANSITION_1M = "regime_transition_1m"
EVENT_EPISODE_START = "episode_start"
EVENT_EPISODE_TERMINATE = "episode_terminate"


class RuntimeProviderBindingMissing(RuntimeError):
    """A compiled FeatureInstance resolves to a canonical provider with no adapter."""


class FeatureOutputBindingMissing(RuntimeError):
    """An adapter was instantiated for a FeatureInstance but produced no output for it."""


@dataclass(frozen=True)
class InstanceSpec:
    """One compiled FeatureInstance the host must realize at runtime."""

    canonical_name: str
    parameters: Mapping[str, Any]
    physical_alias: str
    canonical_provider: str
    required_streams: Tuple[str, ...]


class RuntimeProviderAdapter(Protocol):
    """Narrow uniform surface every provider-family adapter implements."""

    canonical_provider: str
    physical_aliases: Tuple[str, ...]

    def required_streams(self) -> frozenset[str]:
        ...

    def on_event(self, event_type: str, event: Mapping[str, Any]) -> None:
        ...

    def snapshot(
        self, *, decision_ts: int, price: float, atr: float,
        episode_state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...


# --------------------------------------------------------------------------- #
# Adapters. Each wraps exactly one canonical provider and never reimplements
# its internals. Value-parity notes with the sealed legacy collector paths are
# called out inline; anything a §9 causal review must resolve is prefixed REVIEW.
# --------------------------------------------------------------------------- #

def _finite_pos(x: Optional[float]) -> bool:
    return x is not None and math.isfinite(x) and x > 0.0


def _sign(x: Optional[float]) -> Optional[int]:
    if x is None or not math.isfinite(x):
        return None
    return 1 if x > 0 else (-1 if x < 0 else 0)


def _window_seconds(token: str) -> int:
    token = str(token).strip().lower()
    if token.endswith("s"):
        return int(token[:-1])
    return int(token)


class _BaseAdapter:
    canonical_provider = ""

    def __init__(self, instances: Sequence[InstanceSpec]) -> None:
        self.instances = tuple(instances)
        self.physical_aliases = tuple(i.physical_alias for i in self.instances)

    def required_streams(self) -> frozenset[str]:
        out: set[str] = set()
        for inst in self.instances:
            out.update(inst.required_streams)
        return frozenset(out)

    def on_event(self, event_type: str, event: Mapping[str, Any]) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def snapshot(self, *, decision_ts, price, atr, episode_state) -> Mapping[str, Any]:  # pragma: no cover
        raise NotImplementedError


class ArrivalVelocityAdapter(_BaseAdapter):
    """``GenericArrivalVelocityProvider`` -- completed-1s price velocity/acceleration.

    Value parity: for ``lookback == 20`` this reads the provider's legacy-alias
    projection (``arrival_vel_20s`` / ``arrival_accel_10s``) so values are identical
    to the sealed Model C parent's compact path. Other lookbacks use the provider's
    regular ``velocity(lookback=...)`` form.
    """

    canonical_provider = "features.trackers.generic_arrival.GenericArrivalVelocityProvider"

    def __init__(self, instances: Sequence[InstanceSpec]) -> None:
        super().__init__(instances)
        from features.trackers.generic_arrival import GenericArrivalVelocityProvider

        lookbacks = []
        for inst in self.instances:
            p = inst.parameters
            lookbacks.append(int(p.get("lookback", p.get("short_lookback", 20))))
        self._provider = GenericArrivalVelocityProvider(
            max_lookback_bars=max(60, 2 * max(lookbacks or [20]) + 1)
        )

    def required_streams(self) -> frozenset[str]:
        return frozenset({STREAM_COMPLETED_1S})

    def on_event(self, event_type: str, event: Mapping[str, Any]) -> None:
        if event_type == STREAM_COMPLETED_1S:
            self._provider.update_completed_bar(close=float(event["close"]))

    def _velocity(self, lookback: int, atr: float) -> Optional[float]:
        if lookback == 20:
            return self._provider.snapshot(atr=atr).get("arrival_vel_20s")
        return self._provider.velocity(lookback=lookback, atr=atr)

    def snapshot(self, *, decision_ts, price, atr, episode_state) -> Mapping[str, Any]:
        out: Dict[str, Any] = {}
        for inst in self.instances:
            p = inst.parameters
            if inst.canonical_name == "arrival_velocity":
                out[inst.physical_alias] = self._velocity(int(p.get("lookback", 20)), atr)
            elif inst.canonical_name == "arrival_acceleration":
                short = int(p.get("short_lookback", 20))
                if short == 20:
                    out[inst.physical_alias] = self._provider.snapshot(atr=atr).get("arrival_accel_10s")
                else:
                    fast = self._provider.velocity(lookback=max(1, short // 2), atr=atr)
                    slow = self._provider.velocity(lookback=short, atr=atr)
                    out[inst.physical_alias] = None if fast is None or slow is None else fast - slow
        return out


class ContextAdapter(_BaseAdapter):
    """``GenericContextProvider`` -- EMA slope of the completed-1m dual-EMA midpoint.

    ``GenericContextProvider`` is stateless (its docstring: callers pass completed-bar
    values). This adapter therefore owns the EMA history, mirroring the collector's
    ``RegimeEngine`` exactly: ALPHA3 = 0.5 EMA of the 1m high and low, midpoint per
    completed 1m bar.

    REVIEW (§9): the sealed Model C parent's compact path computes ``ema_slope`` as a
    fixed 5-step lookback ((-1) vs (-6)); the deep-pullback FeatureInstance declares
    ``lookback: 20``. Whether Family A must be byte-parity with the frozen Model C
    inputs or canonically re-parameterized is a scientific question for the review /
    Stage 3 Model C scorer integration -- this adapter computes the declared param.
    """

    canonical_provider = "features.trackers.generic_context.GenericContextProvider"
    ALPHA3 = 0.5

    def __init__(self, instances: Sequence[InstanceSpec]) -> None:
        super().__init__(instances)
        from features.trackers.generic_context import GenericContextProvider

        self._provider = GenericContextProvider()
        self._ema_h: Optional[float] = None
        self._ema_l: Optional[float] = None
        self._midpoints: List[float] = []

    def required_streams(self) -> frozenset[str]:
        return frozenset({STREAM_COMPLETED_1M})

    def on_event(self, event_type: str, event: Mapping[str, Any]) -> None:
        if event_type != STREAM_COMPLETED_1M:
            return
        h, l = float(event["high"]), float(event["low"])
        if self._ema_h is None:
            self._ema_h, self._ema_l = h, l
        else:
            self._ema_h = self.ALPHA3 * h + (1 - self.ALPHA3) * self._ema_h
            self._ema_l = self.ALPHA3 * l + (1 - self.ALPHA3) * self._ema_l
        self._midpoints.append((self._ema_h + self._ema_l) / 2.0)

    def snapshot(self, *, decision_ts, price, atr, episode_state) -> Mapping[str, Any]:
        out: Dict[str, Any] = {}
        for inst in self.instances:
            if inst.canonical_name == "ema_slope":
                lookback = int(inst.parameters.get("lookback", 20))
                out[inst.physical_alias] = self._provider.ema_slope(
                    values=list(self._midpoints), lookback=lookback, atr=atr,
                )
        return out


class StructuralGeometryAdapter(_BaseAdapter):
    """``GenericStructuralGeometryProvider`` -- prior/current 1m & 5m regime geometry.

    Drives the provider with completed-1s geometry, 1m regime transitions and completed
    5m bars, then selects the requested physical aliases from its snapshot. The one
    derived alias is ``current_5m_regime_efficiency`` = |displacement_atr| / range_atr,
    both of which the provider snapshot already emits (it exposes
    ``current_5m_directional_displacement_atr`` and ``current_5m_regime_range_atr`` but
    not their ratio).
    """

    canonical_provider = "features.trackers.generic_structural_geometry.GenericStructuralGeometryProvider"

    def __init__(self, instances: Sequence[InstanceSpec]) -> None:
        super().__init__(instances)
        from features.trackers.generic_structural_geometry import GenericStructuralGeometryProvider

        self._provider = GenericStructuralGeometryProvider()
        self._five_close_ts: Optional[int] = None

    def required_streams(self) -> frozenset[str]:
        streams = {STREAM_COMPLETED_1S, STREAM_COMPLETED_1M}
        if any("5m" in (i.parameters.get("timeframe") or "") for i in self.instances):
            streams.add(STREAM_COMPLETED_5M)
        return frozenset(streams)

    def on_event(self, event_type: str, event: Mapping[str, Any]) -> None:
        if event_type == STREAM_COMPLETED_1S:
            self._provider.on_completed_geometry_bar(
                timeframe="1s", close_ts=int(event["ts_init"]),
                high=float(event["high"]), low=float(event["low"]), close=float(event["close"]),
            )
        elif event_type == EVENT_REGIME_TRANSITION_1M:
            self._provider.on_regime_transition(
                timeframe="1m", direction=int(event["direction"]),
                start_ns=int(event["start_ns"]), start_price=float(event["start_price"]),
                atr_start=float(event["atr_start"]), prior_end_close=float(event["prior_end_close"]),
            )
        elif event_type == STREAM_COMPLETED_5M:
            self._provider.on_completed_regime_bar(
                timeframe="5m", close_ts=int(event["close_ts"]), direction=int(event["direction"]),
                open_=float(event["open"]), high=float(event["high"]), low=float(event["low"]),
                close=float(event["close"]), atr=float(event["atr"]),
            )
            self._five_close_ts = int(event["close_ts"])

    def snapshot(self, *, decision_ts, price, atr, episode_state) -> Mapping[str, Any]:
        snap = self._provider.snapshot(
            checkpoint_ns=int(decision_ts), current_price=float(price),
            checkpoint_atr=float(atr), completed_reference_close_ts=self._five_close_ts,
        )
        # Host-internal (underscore-prefixed): consumed by ProviderHost cross-adapter
        # derivation for pullback_fraction_of_structural_move; never a feature column.
        # structural_max_expansion_checkpoint_atr is normalized by the SAME checkpoint
        # ATR the host passes as `atr`, so `value * atr` recovers the raw point distance
        # the episode provider's max_depth_points is also measured in.
        out: Dict[str, Any] = {
            "_structural_max_expansion_checkpoint_atr": snap.get("structural_max_expansion_checkpoint_atr"),
        }
        for inst in self.instances:
            alias = inst.physical_alias
            if alias == "current_5m_regime_efficiency":
                disp = snap.get("current_5m_directional_displacement_atr")
                rng = snap.get("current_5m_regime_range_atr")
                out[alias] = (
                    abs(disp) / rng if disp is not None and _finite_pos(rng) else None
                )
            else:
                out[alias] = snap.get(alias)
        return out


class RollingProductivityAdapter(_BaseAdapter):
    """``GenericRollingProductivityProvider`` -- rolling completed-1s productivity window.

    The provider yields window-agnostic ``rolling_<metric>`` keys; this adapter renders
    the historical ``rolling_<window>_<metric>`` alias at the boundary (the same mapping
    the sealed compact path performs).
    """

    canonical_provider = "features.trackers.generic_rolling_productivity.GenericRollingProductivityProvider"

    def __init__(self, instances: Sequence[InstanceSpec]) -> None:
        super().__init__(instances)
        from features.trackers.generic_rolling_productivity import GenericRollingProductivityProvider

        windows = {_window_seconds(i.parameters.get("window", "300s")) for i in self.instances}
        if len(windows) != 1:
            raise ValueError(f"RollingProductivityAdapter expects one window, got {sorted(windows)}")
        self._window = next(iter(windows))
        self._provider = GenericRollingProductivityProvider(window_seconds=self._window)

    def required_streams(self) -> frozenset[str]:
        return frozenset({STREAM_COMPLETED_1S})

    def on_event(self, event_type: str, event: Mapping[str, Any]) -> None:
        if event_type == STREAM_COMPLETED_1S:
            self._provider.on_completed_1s(
                int(event["ts_init"]), float(event["high"]), float(event["low"]), float(event["close"]),
            )

    def snapshot(self, *, decision_ts, price, atr, episode_state) -> Mapping[str, Any]:
        direction = int(episode_state.get("prevailing_direction", 0) or 0)
        snap = self._provider.snapshot(
            int(decision_ts), direction, float(atr),
            episode_state.get("regime_expansion_atr_per_min"),
        )
        out: Dict[str, Any] = {}
        for inst in self.instances:
            # rolling_300s_retention_ratio -> provider key rolling_retention_ratio
            metric = inst.physical_alias.replace(f"rolling_{self._window}s_", "rolling_", 1)
            out[inst.physical_alias] = snap.get(metric)
        return out


class EpisodeGeometryAdapter(_BaseAdapter):
    """``GenericEpisodeGeometryProvider`` -- bounded directional pullback episode geometry.

    Consumes ``episode_start`` (from the population layer) and completed-1s bars while an
    episode is active, then reports candidate-time geometry once armed. Six aliases come
    straight from ``candidate_snapshot``. Two are population-supplied context the
    single-episode provider cannot know and are read from ``episode_state``:
    ``seconds_since_prevailing_directional_extreme`` and ``prior_deep_pullback_count``.
    """

    canonical_provider = "features.trackers.generic_episode_geometry.GenericEpisodeGeometryProvider"
    _DIRECT = {
        "pullback_max_depth_atr", "pullback_current_depth_atr",
        "pullback_recovery_from_extreme_atr", "pullback_fraction_of_structural_move",
        "pullback_elapsed_seconds", "pullback_post_arm_seconds",
    }

    def __init__(self, instances: Sequence[InstanceSpec]) -> None:
        super().__init__(instances)
        from features.trackers.generic_episode_geometry import GenericEpisodeGeometryProvider

        self._provider = GenericEpisodeGeometryProvider()
        self._active = False
        self._armed = False
        self._arm_threshold_atr = 1.0
        self._arm_atr: Optional[float] = None

    def required_streams(self) -> frozenset[str]:
        streams = {STREAM_COMPLETED_1S}
        if any(i.required_streams and "completed_1m" in i.required_streams for i in self.instances):
            streams.add(STREAM_COMPLETED_1M)
        return frozenset(streams)

    def on_event(self, event_type: str, event: Mapping[str, Any]) -> None:
        if event_type == EVENT_EPISODE_START:
            self._provider.start_episode(
                start_ns=int(event["start_ns"]), direction=int(event["direction"]),
                favorable_extreme_price=float(event["favorable_extreme_price"]),
            )
            self._active, self._armed, self._arm_atr = True, False, None
            self._arm_threshold_atr = float(event.get("arm_threshold_atr", 1.0))
        elif event_type == EVENT_EPISODE_TERMINATE:
            self._provider.terminate_episode()
            self._active = self._armed = False
            self._arm_atr = None
        elif event_type == STREAM_COMPLETED_1S and self._active:
            # ATR available at the completed observation crossing the arm threshold.
            arm_atr = float(event["arm_atr"])
            became_armed = self._provider.observe_completed_1s(
                close_ts=int(event["ts_init"]), high=float(event["high"]), low=float(event["low"]),
                arm_atr=arm_atr, arm_threshold_atr=self._arm_threshold_atr,
            )
            if became_armed:
                self._armed = True
                self._arm_atr = arm_atr

    def snapshot(self, *, decision_ts, price, atr, episode_state) -> Mapping[str, Any]:
        out: Dict[str, Any] = {i.physical_alias: None for i in self.instances}
        structural_pts = episode_state.get("structural_expansion_points")
        geom: Mapping[str, Any] = {}
        if self._active and self._armed:
            geom = self._provider.candidate_snapshot(
                candidate_ts=int(decision_ts), candidate_price=float(price),
                candidate_atr=float(atr),
                structural_expansion_points=structural_pts,
            )
        for inst in self.instances:
            alias = inst.physical_alias
            if alias in self._DIRECT:
                out[alias] = geom.get(alias) if geom else None
            elif alias == "seconds_since_prevailing_directional_extreme":
                ext_ts = episode_state.get("prevailing_extreme_ts")
                out[alias] = (
                    (int(decision_ts) - int(ext_ts)) / NS if ext_ts is not None else None
                )
            elif alias == "prior_deep_pullback_count":
                out[alias] = episode_state.get("prior_deep_pullback_count")
        return out


class CompletedRegimeGeometryAdapter(_BaseAdapter):
    """``GenericCompletedRegimeGeometryProvider`` -- completed 5s counter-regime + current 5m.

    5s: the "counter regime" is the opposite-prevailing 5s regime that just completed
    before the flip-back. That is exactly the provider's *prior* 5s regime at candidate
    T, so ``prior_snapshot(timeframe="5s", ...)``'s recovery outputs are renamed to the
    ``counter_regime`` aliases.
    5m: ``current_5m_regime_direction`` from the additive ``current_snapshot`` accessor.
    ``regime_alignment`` = agreement of the current completed 1m and 5m regime directions
    (both from this provider's own state, fed the 1m and 5m completed streams).
    """

    canonical_provider = "features.trackers.generic_regime_geometry.GenericCompletedRegimeGeometryProvider"

    def __init__(self, instances: Sequence[InstanceSpec]) -> None:
        super().__init__(instances)
        from features.trackers.generic_regime_geometry import GenericCompletedRegimeGeometryProvider

        self._provider = GenericCompletedRegimeGeometryProvider()
        self._needs_5s = any(i.parameters.get("timeframe") == "5s" for i in self.instances)
        self._needs_5m = any(
            i.parameters.get("timeframe") == "5m"
            or i.parameters.get("reference_timeframe") == "5m"
            for i in self.instances
        )
        self._needs_1m = any(
            i.parameters.get("source_timeframe") == "1m" for i in self.instances
        )

    def required_streams(self) -> frozenset[str]:
        streams: set[str] = set()
        if self._needs_5s:
            streams.add(STREAM_COMPLETED_5S)
        if self._needs_5m:
            streams.add(STREAM_COMPLETED_5M)
        if self._needs_1m:
            streams.add(STREAM_COMPLETED_1M)
        return frozenset(streams)

    def on_event(self, event_type: str, event: Mapping[str, Any]) -> None:
        tf = {
            STREAM_COMPLETED_5S: "5s", STREAM_COMPLETED_5M: "5m", STREAM_COMPLETED_1M: "1m",
        }.get(event_type)
        if tf is None:
            return
        self._provider.on_completed_bar(
            timeframe=tf, close_ts=int(event["close_ts"]), direction=int(event["direction"]),
            open_=float(event["open"]), high=float(event["high"]), low=float(event["low"]),
            close=float(event["close"]), atr=float(event["atr"]),
        )

    def snapshot(self, *, decision_ts, price, atr, episode_state) -> Mapping[str, Any]:
        out: Dict[str, Any] = {i.physical_alias: None for i in self.instances}
        prior5s = (
            self._provider.prior_snapshot(
                timeframe="5s", checkpoint_ns=int(decision_ts),
                candidate_price=float(price), candidate_atr=float(atr),
            )
            if self._needs_5s else {"available": False}
        )
        cur5m = (
            self._provider.current_snapshot(timeframe="5m", checkpoint_ns=int(decision_ts))
            if self._needs_5m else {"available": False}
        )
        cur1m = (
            self._provider.current_snapshot(timeframe="1m", checkpoint_ns=int(decision_ts))
            if self._needs_1m else {"available": False}
        )
        for inst in self.instances:
            alias = inst.physical_alias
            if alias == "recovery_from_counter_regime_extreme_atr":
                out[alias] = prior5s.get("prior_5s_regime_recovery_from_extreme_atr") if prior5s.get("available") else None
            elif alias == "fraction_of_counter_regime_move_recovered":
                out[alias] = prior5s.get("prior_5s_regime_fraction_move_recovered") if prior5s.get("available") else None
            elif alias == "current_5m_regime_direction":
                out[alias] = cur5m.get("current_5m_regime_direction") if cur5m.get("available") else None
            elif alias == "regime_alignment":
                d5 = cur5m.get("current_5m_regime_direction") if cur5m.get("available") else None
                d1 = cur1m.get("current_1m_regime_direction") if cur1m.get("available") else None
                out[alias] = None if d5 is None or d1 is None else (1 if d5 == d1 else -1)
        return out


class OHLCVDeltaAdapter(_BaseAdapter):
    """``GenericOHLCVDeltaProvider`` -- direction-normalized estimated-delta pressure."""

    canonical_provider = "features.trackers.generic_ohlcv_delta.GenericOHLCVDeltaProvider"

    def __init__(self, instances: Sequence[InstanceSpec]) -> None:
        super().__init__(instances)
        from features.trackers.generic_ohlcv_delta import GenericOHLCVDeltaProvider

        windows: set[int] = set()
        for inst in self.instances:
            p = inst.parameters
            for key in ("window", "numerator_window", "denominator_window"):
                if key in p:
                    windows.add(_window_seconds(p[key]))
        self._provider = GenericOHLCVDeltaProvider(windows_seconds=sorted(windows or {5, 60, 300}))

    def required_streams(self) -> frozenset[str]:
        return frozenset({STREAM_COMPLETED_1S})

    def on_event(self, event_type: str, event: Mapping[str, Any]) -> None:
        if event_type == STREAM_COMPLETED_1S:
            self._provider.update_completed_bar(
                close_ts=int(event["ts_init"]), open_px=float(event["open"]),
                high=float(event["high"]), low=float(event["low"]), close=float(event["close"]),
                volume=float(event["volume"]),
            )

    def snapshot(self, *, decision_ts, price, atr, episode_state) -> Mapping[str, Any]:
        direction = int(episode_state.get("prevailing_direction", 0) or 0)
        out: Dict[str, Any] = {}
        if direction not in (-1, 1):
            return {i.physical_alias: None for i in self.instances}
        for inst in self.instances:
            p = inst.parameters
            if inst.canonical_name == "trend_normalized_est_delta_sum":
                out[inst.physical_alias] = self._provider.trend_normalized_est_delta_sum(
                    window=str(p["window"]), prevailing_direction=direction, atr=float(atr),
                )
            elif inst.canonical_name == "trend_normalized_est_delta_sum_ratio":
                out[inst.physical_alias] = self._provider.trend_normalized_est_delta_scale_ratio(
                    numerator_window=str(p["numerator_window"]),
                    denominator_window=str(p["denominator_window"]),
                    prevailing_direction=direction, atr=float(atr),
                )
        return out


# canonical provider class path -> adapter factory. Deterministic, no study branches.
ADAPTER_REGISTRY: Dict[str, Callable[[Sequence[InstanceSpec]], RuntimeProviderAdapter]] = {
    ArrivalVelocityAdapter.canonical_provider: ArrivalVelocityAdapter,
    ContextAdapter.canonical_provider: ContextAdapter,
    StructuralGeometryAdapter.canonical_provider: StructuralGeometryAdapter,
    RollingProductivityAdapter.canonical_provider: RollingProductivityAdapter,
    EpisodeGeometryAdapter.canonical_provider: EpisodeGeometryAdapter,
    CompletedRegimeGeometryAdapter.canonical_provider: CompletedRegimeGeometryAdapter,
    OHLCVDeltaAdapter.canonical_provider: OHLCVDeltaAdapter,
}


@dataclass
class ProviderHost:
    """Instantiated adapters for one compiled study's feature surface."""

    instances: Tuple[InstanceSpec, ...]
    adapters: Tuple[RuntimeProviderAdapter, ...]
    _alias_to_provider: Dict[str, str] = field(default_factory=dict)

    # ---- construction ------------------------------------------------------ #
    @classmethod
    def from_feature_contract(
        cls, compiled_study: Mapping[str, Any], *, feature_authority: str = "active",
    ) -> "ProviderHost":
        specs = cls._resolve_instance_specs(compiled_study, feature_authority=feature_authority)
        aliases = [s.physical_alias for s in specs]
        if len(aliases) != len(set(aliases)):
            dupes = sorted({a for a in aliases if aliases.count(a) > 1})
            raise ValueError(f"DUPLICATE_PHYSICAL_ALIAS: {dupes}")

        by_provider: Dict[str, List[InstanceSpec]] = {}
        for spec in specs:
            by_provider.setdefault(spec.canonical_provider, []).append(spec)

        adapters: List[RuntimeProviderAdapter] = []
        alias_to_provider: Dict[str, str] = {}
        for provider_path, group in by_provider.items():
            factory = ADAPTER_REGISTRY.get(provider_path)
            if factory is None:
                raise RuntimeProviderBindingMissing(
                    f"RUNTIME_PROVIDER_BINDING_MISSING: canonical provider {provider_path!r} "
                    f"(needed by {[g.physical_alias for g in group]}) has no registered "
                    f"RuntimeProviderAdapter"
                )
            adapters.append(factory(group))
            for g in group:
                alias_to_provider[g.physical_alias] = provider_path
        return cls(tuple(specs), tuple(adapters), alias_to_provider)

    @staticmethod
    def _resolve_instance_specs(
        compiled_study: Mapping[str, Any], *, feature_authority: str = "active",
    ) -> List[InstanceSpec]:
        contracts = compiled_study.get("contracts", {}) or {}
        fc = contracts.get("feature_contract", {}) or {}
        rdr = (fc.get("runtime_data_requirements") or {}).get("resolved_instances")
        specs: List[InstanceSpec] = []
        if rdr:
            for item in rdr:
                specs.append(InstanceSpec(
                    canonical_name=item["canonical_name"],
                    parameters=dict(item.get("parameters") or {}),
                    physical_alias=item["physical_alias"],
                    canonical_provider=item["provider"],
                    required_streams=tuple(
                        (item.get("input_requirements") or {}).get("required_streams") or ()
                    ),
                ))
            return specs
        # Fall back to resolving from the raw instance list through the registry.
        raw = fc.get("resolved_feature_instances") or (
            (compiled_study.get("spec", {}) or {}).get("features", {}) or {}
        ).get("instances") or []
        from features.registry import (
            FeatureInstance, resolve_feature_instances, derive_instance_input_requirements,
        )
        insts = tuple(
            FeatureInstance(it["canonical_name"] if "canonical_name" in it else it["feature"],
                            it.get("parameters") or {})
            for it in raw
        )
        for it, res in zip(insts, resolve_feature_instances("canonical_verified_definition_universe", insts)):
            reqs = derive_instance_input_requirements(it)
            specs.append(InstanceSpec(
                canonical_name=res["canonical_name"], parameters=dict(res["parameters"]),
                physical_alias=res["physical_alias"], canonical_provider=res["provider"],
                required_streams=tuple(reqs.get("required_streams") or ()),
            ))
        return specs

    # ---- runtime --------------------------------------------------------- #
    def required_streams(self) -> frozenset[str]:
        out: set[str] = set()
        for adapter in self.adapters:
            out |= adapter.required_streams()
        return frozenset(out)

    def dispatch(self, event_type: str, event: Mapping[str, Any]) -> None:
        """Route one normalized event to every adapter that consumes it.

        Lifecycle events (regime transition, episode start/terminate) are delivered to
        every adapter; the adapter ignores what it does not use. Data-stream events go
        only to adapters that declared the stream.
        """
        if event_type in ALL_STREAMS:
            for adapter in self.adapters:
                if event_type in adapter.required_streams():
                    adapter.on_event(event_type, event)
        else:
            for adapter in self.adapters:
                adapter.on_event(event_type, event)

    def snapshot(
        self, *, decision_ts: int, price: float, atr: float,
        episode_state: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Produce the full candidate-time feature row (exactly the declared aliases).

        Raises ``FeatureOutputBindingMissing`` if any declared alias is absent from the
        merged adapter output -- a present key with a ``None`` value is a permitted null
        (feature_null_policies), an absent key is an unbound feature.
        """
        state = dict(episode_state or {})
        merged: Dict[str, Any] = {}
        # Deterministic order: structural first so cross-adapter derivations can read it.
        ordered = sorted(
            self.adapters,
            key=lambda a: 0 if isinstance(a, StructuralGeometryAdapter) else 1,
        )
        for adapter in ordered:
            if isinstance(adapter, EpisodeGeometryAdapter) and "structural_expansion_points" not in state:
                sx = merged.get("_structural_max_expansion_checkpoint_atr")
                # checkpoint-ATR-normalized -> raw points via the same checkpoint ATR.
                state["structural_expansion_points"] = (
                    sx * float(atr) if sx is not None else None
                )
            part = adapter.snapshot(
                decision_ts=int(decision_ts), price=float(price), atr=float(atr),
                episode_state=state,
            )
            merged.update(part)
        row = {}
        missing = []
        for spec in self.instances:
            if spec.physical_alias not in merged:
                missing.append(spec.physical_alias)
            else:
                row[spec.physical_alias] = merged[spec.physical_alias]
        if missing:
            raise FeatureOutputBindingMissing(
                f"FEATURE_OUTPUT_BINDING_MISSING: adapters produced no value key for {missing}"
            )
        return row

    # ---- static realizability metadata --------------------------------- #
    def binding_metadata(self) -> List[Dict[str, Any]]:
        """Machine-readable per-FeatureInstance runtime binding record."""
        adapter_by_provider = {a.canonical_provider: a for a in self.adapters}
        records: List[Dict[str, Any]] = []
        for spec in self.instances:
            adapter = adapter_by_provider.get(spec.canonical_provider)
            records.append({
                "canonical_name": spec.canonical_name,
                "parameters": dict(spec.parameters),
                "canonical_provider": spec.canonical_provider,
                "runtime_adapter": type(adapter).__name__ if adapter else None,
                "required_streams": sorted(
                    adapter.required_streams() if adapter else spec.required_streams
                ),
                "physical_alias": spec.physical_alias,
                "bound": bool(
                    adapter is not None and spec.physical_alias in adapter.physical_aliases
                ),
            })
        return records

    def verify_bindings(self) -> Dict[str, Any]:
        meta = self.binding_metadata()
        unbound = [m["physical_alias"] for m in meta if not m["bound"]]
        return {
            "passed": not unbound,
            "required": len(meta),
            "bound": len(meta) - len(unbound),
            "unbound": unbound,
            "adapters": sorted({m["runtime_adapter"] for m in meta if m["runtime_adapter"]}),
            "metadata": meta,
        }


__all__ = [
    "ProviderHost", "InstanceSpec", "RuntimeProviderAdapter", "ADAPTER_REGISTRY",
    "RuntimeProviderBindingMissing", "FeatureOutputBindingMissing",
    "ArrivalVelocityAdapter", "ContextAdapter", "StructuralGeometryAdapter",
    "RollingProductivityAdapter", "EpisodeGeometryAdapter",
    "CompletedRegimeGeometryAdapter", "OHLCVDeltaAdapter",
    "STREAM_COMPLETED_1S", "STREAM_COMPLETED_1M", "STREAM_COMPLETED_5M", "STREAM_COMPLETED_5S",
    "EVENT_REGIME_TRANSITION_1M", "EVENT_EPISODE_START", "EVENT_EPISODE_TERMINATE",
]

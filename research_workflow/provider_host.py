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


class NonMonotonicRuntimeEvent(RuntimeError):
    """A dispatched data-stream event is not strictly after the last event of its stream."""


class SnapshotBeforeLatestRuntimeEvent(RuntimeError):
    """snapshot(decision_ts) was called with decision_ts earlier than an ingested event."""


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

    @classmethod
    def can_emit(cls, spec: "InstanceSpec") -> bool:
        """Adapter-declared realizability (F-4). Fail closed: an adapter that does not
        override this cannot emit anything. Concrete adapters check the canonical name,
        the parameter combination, and that a snapshot path renders this exact alias --
        it is NOT ``alias in the requested list`` (which would be tautological)."""
        return False

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

    _CANONICAL = frozenset({"arrival_velocity", "arrival_acceleration"})

    @classmethod
    def can_emit(cls, spec: "InstanceSpec") -> bool:
        if spec.canonical_name not in cls._CANONICAL:
            return False
        return str(spec.parameters.get("input_timeframe", "1s")) == "1s"

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
        atr = float(episode_state.get("family_a_atr", atr))  # FLAG B: frozen-parent ATR
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

    FAMILY-A AUTHORITY (F-A). The frozen Model C parent
    (``clean_maturity_flip_model_rolling_productivity``) was trained on its collector's
    compact-path value for this input:

        research_workflow/generic_collector.py :: _get_context_features
        ema_slope = (short_ema_history[-1] - short_ema_history[-6]) / (5 * atr)
        # 0.0 while len(short_ema_history) < 6

    ``short_ema_history`` is exactly this adapter's ``_midpoints`` series. So the realized
    ``ema_slope`` for ``ema_role: short`` on this path is a FIVE-step midpoint slope
    normalized by ``5 * atr`` -- the FeatureInstance ``lookback`` parameter is legacy
    nominal metadata that neither the sealed parent runtime nor this adapter consumes
    (the parent declares ``lookback: 20`` yet computes 5). Model C is
    ``retrain_prohibited``; this adapter reproduces the parent value exactly rather than
    "modernising" it to a 20-step slope. See ``FROZEN_FAMILY_A_EMA_SLOPE_STEPS``.
    ``GenericContextProvider.ema_slope(values, lookback=5, atr)`` is byte-identical to
    the parent formula, including the 0.0-below-6 warmup, so no separate transform is
    introduced -- the canonical provider IS the implementation, called with the frozen
    step count.
    """

    canonical_provider = "features.trackers.generic_context.GenericContextProvider"
    ALPHA3 = 0.5
    # The frozen Model C parent's realized ema_slope step count (see class docstring).
    FROZEN_FAMILY_A_EMA_SLOPE_STEPS = 5

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

    @classmethod
    def can_emit(cls, spec: "InstanceSpec") -> bool:
        return spec.canonical_name == "ema_slope" and spec.parameters.get("ema_role") == "short"

    def snapshot(self, *, decision_ts, price, atr, episode_state) -> Mapping[str, Any]:
        atr = float(episode_state.get("family_a_atr", atr))  # FLAG B: frozen-parent ATR
        out: Dict[str, Any] = {}
        for inst in self.instances:
            if inst.canonical_name == "ema_slope":
                # F-A: frozen Model C parent parity -- 5-step slope / (5*atr), 0.0 below 6.
                # `lookback` in the instance is legacy nominal and is NOT consumed here.
                out[inst.physical_alias] = self._provider.ema_slope(
                    values=list(self._midpoints),
                    lookback=self.FROZEN_FAMILY_A_EMA_SLOPE_STEPS, atr=atr,
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

    # Exact keys StructuralRegimeGeometryTracker.snapshot() can return (+ the one
    # adapter-derived ratio). An alias outside this set has no snapshot path here.
    _SNAPSHOT_KEYS = frozenset({
        f"{ctx}_{tf}_regime_{metric}"
        for ctx, tf in (("prior", "1m"), ("prior", "5m"))
        for metric in ("duration_min", "range_atr", "net_directional_move_atr", "mfe_atr",
                       "range_atr_per_min", "net_move_atr_per_min", "efficiency")
    } | {
        "current_5m_regime_age_min", "current_5m_regime_range_atr", "current_5m_regime_mfe_atr",
        "current_5m_directional_displacement_atr", "current_5m_regime_range_atr_per_min",
        "current_5m_regime_range_checkpoint_atr", "current_5m_regime_efficiency",
        "distance_to_completed_5m_high_atr", "distance_to_completed_5m_low_atr",
        "current_1m_move_outside_completed_5m_range",
        "structural_max_expansion_atr", "structural_current_expansion_atr",
        "structural_giveback_atr", "structural_retention_ratio",
        "structural_expansion_atr_per_min", "regime_expansion_atr_per_min",
        "structural_max_expansion_checkpoint_atr", "structural_current_expansion_checkpoint_atr",
    })

    @classmethod
    def can_emit(cls, spec: "InstanceSpec") -> bool:
        return spec.physical_alias in cls._SNAPSHOT_KEYS

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
        # FLAG B: the sealed Model-C parent passes checkpoint_atr = the prevailing 1m
        # regime frozen ATR (regime_frozen_atr) to the structural tracker. The prior_1m /
        # prior_5m regime features it feeds Model C normalise by each regime's own
        # atr_start, but structural checkpoint-ATR outputs must match the parent.
        atr = float(episode_state.get("family_a_atr", atr))
        snap = self._provider.snapshot(
            checkpoint_ns=int(decision_ts), current_price=float(price),
            checkpoint_atr=float(atr), completed_reference_close_ts=self._five_close_ts,
        )
        # Host-internal (underscore-prefixed): consumed by ProviderHost cross-adapter
        # derivation for pullback_fraction_of_structural_move; never a feature column.
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

    _CANONICAL = frozenset({
        "rolling_retention_ratio", "rolling_current_progress_atr", "rolling_max_progress_atr",
        "rolling_giveback_atr", "rolling_max_speed_atr_per_min", "rolling_current_speed_atr_per_min",
        "rolling_max_speed_vs_lifetime", "rolling_current_speed_vs_lifetime",
    })

    @classmethod
    def can_emit(cls, spec: "InstanceSpec") -> bool:
        return spec.canonical_name in cls._CANONICAL and "window" in spec.parameters

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
        atr = float(episode_state.get("family_a_atr", atr))  # FLAG B: frozen-parent (regime-start) ATR
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
    _POPULATION_SUPPLIED = {
        "seconds_since_prevailing_directional_extreme", "prior_deep_pullback_count",
    }

    @classmethod
    def can_emit(cls, spec: "InstanceSpec") -> bool:
        return spec.physical_alias in (cls._DIRECT | cls._POPULATION_SUPPLIED)

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

        # Stage 3: the population runtime is the episode-lifecycle authority. When it
        # hands its canonical GenericEpisodeGeometryProvider output through
        # `episode_state["episode_geometry"]`, read that -- do NOT independently replay.
        handoff = episode_state.get("episode_geometry")
        if handoff is not None:
            mdp = handoff.get("max_depth_points")
            for inst in self.instances:
                alias = inst.physical_alias
                if alias == "pullback_fraction_of_structural_move":
                    out[alias] = (
                        (mdp / structural_pts)
                        if (mdp is not None and structural_pts not in (None, 0)) else
                        handoff.get(alias)
                    )
                elif alias in self._DIRECT:
                    out[alias] = handoff.get(alias)
                elif alias == "seconds_since_prevailing_directional_extreme":
                    out[alias] = handoff.get(alias)
                elif alias == "prior_deep_pullback_count":
                    out[alias] = episode_state.get("prior_deep_pullback_count")
            return out

        # Stage 1 standalone path: drive this adapter's own provider.
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
    5m: ``current_5m_regime_direction`` from the ``current_snapshot`` accessor.
    ``regime_alignment``: the canonical polarity lives in
    ``GenericCompletedRegimeGeometryProvider.alignment`` (F-D) -- {+1 agree, -1 disagree,
    null if either current completed regime direction is unavailable}; this adapter only
    forwards it.
    """

    canonical_provider = "features.trackers.generic_regime_geometry.GenericCompletedRegimeGeometryProvider"
    _EMITTABLE = frozenset({
        "recovery_from_counter_regime_extreme_atr", "fraction_of_counter_regime_move_recovered",
        "current_5m_regime_direction", "regime_alignment",
    })

    @classmethod
    def can_emit(cls, spec: "InstanceSpec") -> bool:
        return spec.physical_alias in cls._EMITTABLE

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
        direction = int(event.get("direction", 0) or 0)
        atr = float(event.get("atr", 0.0) or 0.0)
        if direction not in (-1, 1) or not math.isfinite(atr) or atr <= 0.0:
            return  # warmup / neutral bar: no completed regime state to record
        self._provider.on_completed_bar(
            timeframe=tf, close_ts=int(event["close_ts"]), direction=direction,
            open_=float(event["open"]), high=float(event["high"]), low=float(event["low"]),
            close=float(event["close"]), atr=atr,
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
        # Stage 3 counter-5s identity guard (§4). The recovery features may only populate
        # when the provider's prior 5s regime IS the opposite-prevailing counter regime the
        # population runtime's counter-event established -- not "whichever prior 5s regime".
        counter_dir = episode_state.get("counter_regime_direction")
        prevailing = episode_state.get("prevailing_direction")
        counter_ok = (
            "counter_regime_direction" not in episode_state  # Stage 1 standalone: no gate
            or (counter_dir is not None and prevailing is not None
                and int(counter_dir) == -int(prevailing))
        )
        counter_close = episode_state.get("counter_regime_close_ts")
        if counter_ok and counter_close not in (None, -1) and prior5s.get("available"):
            # the provider's prior 5s regime must not end BEFORE the counter regime the
            # population saw (they are the same regime; allow provider end_ns >= that close)
            prior_end = prior5s.get("prior_5s_regime_completed_close_ts") or prior5s.get("completed_close_ts")
            if prior_end is not None and int(prior_end) < int(counter_close):
                counter_ok = False
        for inst in self.instances:
            alias = inst.physical_alias
            if alias == "recovery_from_counter_regime_extreme_atr":
                out[alias] = prior5s.get("prior_5s_regime_recovery_from_extreme_atr") if (prior5s.get("available") and counter_ok) else None
            elif alias == "fraction_of_counter_regime_move_recovered":
                out[alias] = prior5s.get("prior_5s_regime_fraction_move_recovered") if (prior5s.get("available") and counter_ok) else None
            elif alias == "current_5m_regime_direction":
                out[alias] = cur5m.get("current_5m_regime_direction") if cur5m.get("available") else None
            elif alias == "regime_alignment":
                src_tf = inst.parameters.get("source_timeframe", "1m")
                ref_tf = inst.parameters.get("reference_timeframe", "5m")
                out[alias] = self._provider.alignment(
                    source_timeframe=src_tf, reference_timeframe=ref_tf,
                    checkpoint_ns=int(decision_ts),
                )["regime_alignment"]
        return out


class OHLCVDeltaAdapter(_BaseAdapter):
    """``GenericOHLCVDeltaProvider`` -- direction-normalized estimated-delta pressure."""

    canonical_provider = "features.trackers.generic_ohlcv_delta.GenericOHLCVDeltaProvider"
    _CANONICAL = frozenset({"trend_normalized_est_delta_sum", "trend_normalized_est_delta_sum_ratio"})

    @classmethod
    def can_emit(cls, spec: "InstanceSpec") -> bool:
        if spec.canonical_name not in cls._CANONICAL:
            return False
        return str(spec.parameters.get("direction_reference", "prevailing_1m")) == "prevailing_1m"

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


# F-5 timestamps for a normalized event:
#   stream_ts -- per-stream monotonic key (strictly increasing within the stream)
#   avail_ts  -- causal availability (when the event became readable); drives the global
#                _latest_event_ts a snapshot may not precede
# For 5s/5m completed buckets the two differ: the bucket close_ts precedes the 1s bar it
# is published through, but the snapshot guard must key off the publication instant.
def _event_stream_ts(event_type: str, event: Mapping[str, Any]) -> Optional[int]:
    if event_type == STREAM_COMPLETED_1S:
        v = event.get("ts_init")
    elif event_type == STREAM_COMPLETED_1M:
        v = event.get("ts_init", event.get("close_ts"))
    elif event_type in (STREAM_COMPLETED_5M, STREAM_COMPLETED_5S):
        v = event.get("close_ts")
    else:
        v = None
    return None if v is None else int(v)


def _event_avail_ts(event_type: str, event: Mapping[str, Any]) -> Optional[int]:
    if event_type in (STREAM_COMPLETED_5M, STREAM_COMPLETED_5S):
        v = event.get("available_ts", event.get("close_ts"))
    elif event_type == STREAM_COMPLETED_1S:
        v = event.get("ts_init")
    elif event_type == STREAM_COMPLETED_1M:
        v = event.get("ts_init", event.get("close_ts"))
    elif event_type in (EVENT_REGIME_TRANSITION_1M, EVENT_EPISODE_START):
        v = event.get("start_ns")
    else:  # EVENT_EPISODE_TERMINATE
        v = None
    return None if v is None else int(v)


# Back-compat alias used by earlier tests.
def _event_ts(event_type: str, event: Mapping[str, Any]) -> Optional[int]:
    return _event_avail_ts(event_type, event)


@dataclass
class ProviderHost:
    """Instantiated adapters for one compiled study's feature surface."""

    instances: Tuple[InstanceSpec, ...]
    adapters: Tuple[RuntimeProviderAdapter, ...]
    _alias_to_provider: Dict[str, str] = field(default_factory=dict)
    _unbound: Dict[str, str] = field(default_factory=dict)
    # F-5 causal ordering state
    _stream_last_ts: Dict[str, int] = field(default_factory=dict)
    _latest_event_ts: int = -1
    # Declared-cadence routing table (platform-v2 item 07, fix C): stream -> the adapters
    # that declared it, computed once from ``required_streams()`` on first dispatch. The
    # previous per-event ``adapter.required_streams()`` call rebuilt a frozenset for every
    # adapter on every 1s bar. Routing semantics are identical (verified by
    # scripts/tests/test_hot_path_equivalence.py).
    _subscribers: Dict[str, Tuple[Any, ...]] = field(default_factory=dict)

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
        unbound: Dict[str, str] = {}
        for provider_path, group in by_provider.items():
            factory = ADAPTER_REGISTRY.get(provider_path)
            if factory is None:
                raise RuntimeProviderBindingMissing(
                    f"RUNTIME_PROVIDER_BINDING_MISSING: canonical provider {provider_path!r} "
                    f"(needed by {[g.physical_alias for g in group]}) has no registered "
                    f"RuntimeProviderAdapter"
                )
            # F-4: an adapter must positively declare it can emit each requested spec --
            # not merely be handed it. A spec its snapshot path cannot render is unbound.
            for g in group:
                if not factory.can_emit(g):
                    unbound[g.physical_alias] = (
                        f"{factory.__name__} does not declare a snapshot path for "
                        f"{g.canonical_name} {dict(g.parameters)}"
                    )
            try:
                adapters.append(factory(group))
            except Exception as exc:  # construction rejected an unsupported combination
                for g in group:
                    unbound.setdefault(g.physical_alias, f"{type(exc).__name__}: {exc}")
                continue
            for g in group:
                alias_to_provider[g.physical_alias] = provider_path
        host = cls(tuple(specs), tuple(adapters), alias_to_provider, unbound)
        return host

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

        F-5 causal guard. Each data stream must be strictly time-monotonic (differing
        timeframe streams may still interleave legitimately -- there is no global event
        order). Every timestamped event advances ``_latest_event_ts``, which
        :meth:`snapshot` then refuses to precede -- so a future event dispatched after a
        historical snapshot request fails closed instead of silently contaminating a
        timestamp-free wrapped provider (arrival/context).
        """
        stream_ts = _event_stream_ts(event_type, event)
        avail_ts = _event_avail_ts(event_type, event)
        if event_type in ALL_STREAMS and stream_ts is not None:
            last = self._stream_last_ts.get(event_type)
            if last is not None and stream_ts <= last:
                raise NonMonotonicRuntimeEvent(
                    f"NON_MONOTONIC_RUNTIME_EVENT: {event_type} close_ts {stream_ts} not strictly after {last}"
                )
            self._stream_last_ts[event_type] = stream_ts
        if avail_ts is not None:
            # 5s/5m bucket close_ts legitimately precedes the 1s bar it is published
            # through; only its availability instant is bound not to precede prior events.
            if avail_ts < self._latest_event_ts and event_type not in (STREAM_COMPLETED_5M, STREAM_COMPLETED_5S):
                raise NonMonotonicRuntimeEvent(
                    f"NON_MONOTONIC_RUNTIME_EVENT: {event_type} avail_ts {avail_ts} precedes an "
                    f"ingested event at {self._latest_event_ts}"
                )
            self._latest_event_ts = max(self._latest_event_ts, avail_ts)

        if event_type in ALL_STREAMS:
            subscribers = self._subscribers.get(event_type)
            if subscribers is None:
                subscribers = tuple(a for a in self.adapters if event_type in a.required_streams())
                self._subscribers[event_type] = subscribers
            for adapter in subscribers:
                adapter.on_event(event_type, event)
        else:
            for adapter in self.adapters:
                adapter.on_event(event_type, event)

    def snapshot(
        self, *, decision_ts: int, price: float, atr: float,
        episode_state: Optional[Mapping[str, Any]] = None,
        family_a_atr: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Produce the full candidate-time feature row (exactly the declared aliases).

        ``atr`` is the candidate-time ATR (ATR_T) used by the pullback / counter-regime /
        direction-normalized-delta geometry. ``family_a_atr`` (FLAG B) is the ATR the
        frozen Model-C parent normalized its Family-A inputs by -- the prevailing 1m
        regime's frozen ATR. When omitted it falls back to ``atr`` (Stage-1 synthetic).
        ArrivalVelocity / Context / RollingProductivity / StructuralGeometry read
        ``episode_state["family_a_atr"]``.

        Raises ``FeatureOutputBindingMissing`` if any declared alias is absent from the
        merged adapter output -- a present key with a ``None`` value is a permitted null
        (feature_null_policies), an absent key is an unbound feature.

        Raises ``SnapshotBeforeLatestRuntimeEvent`` (F-5) if ``decision_ts`` precedes an
        already-dispatched event -- reading provider state at an earlier point than the
        events fed into it would return future-contaminated values.
        """
        if int(decision_ts) < self._latest_event_ts:
            raise SnapshotBeforeLatestRuntimeEvent(
                f"SNAPSHOT_BEFORE_LATEST_RUNTIME_EVENT: decision_ts {int(decision_ts)} < last "
                f"dispatched event ts {self._latest_event_ts}"
            )
        state = dict(episode_state or {})
        state["family_a_atr"] = float(family_a_atr) if family_a_atr is not None else float(atr)
        merged: Dict[str, Any] = {}
        # Deterministic order: structural first so cross-adapter derivations can read it.
        ordered = sorted(
            self.adapters,
            key=lambda a: 0 if isinstance(a, StructuralGeometryAdapter) else 1,
        )
        for adapter in ordered:
            if isinstance(adapter, EpisodeGeometryAdapter) and "structural_expansion_points" not in state:
                sx = merged.get("_structural_max_expansion_checkpoint_atr")
                # _structural_max_expansion_checkpoint_atr was normalized by the structural
                # adapter's ATR (family_a_atr) -> multiply by the same to recover raw points.
                state["structural_expansion_points"] = (
                    sx * state["family_a_atr"] if sx is not None else None
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
        """Machine-readable per-FeatureInstance runtime binding record.

        F-4: ``bound`` is the adapter's own ``can_emit`` verdict (canonical name +
        parameter combination + a snapshot path that renders this exact alias), NOT
        ``alias in the requested list``. ``snapshot_output_binding`` names the concrete
        realization path so the record proves more than "an adapter class exists".
        """
        registry = ADAPTER_REGISTRY
        records: List[Dict[str, Any]] = []
        for spec in self.instances:
            factory = registry.get(spec.canonical_provider)
            adapter = next(
                (a for a in self.adapters if a.canonical_provider == spec.canonical_provider), None
            )
            can_emit = bool(factory is not None and factory.can_emit(spec))
            unbound_reason = self._unbound.get(spec.physical_alias)
            records.append({
                "canonical_name": spec.canonical_name,
                "parameters": dict(spec.parameters),
                "canonical_provider": spec.canonical_provider,
                "runtime_adapter": (factory.__name__ if factory is not None else None),
                "runtime_adapter_instantiated": adapter is not None,
                "required_streams": sorted(
                    adapter.required_streams() if adapter is not None else spec.required_streams
                ),
                "physical_alias": spec.physical_alias,
                "snapshot_output_binding": (
                    f"{factory.__name__}.snapshot -> {spec.physical_alias}" if can_emit else None
                ),
                "bound": can_emit and unbound_reason is None,
                "unbound_reason": unbound_reason if not (can_emit and unbound_reason is None) else None,
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
    "NonMonotonicRuntimeEvent", "SnapshotBeforeLatestRuntimeEvent",
    "ArrivalVelocityAdapter", "ContextAdapter", "StructuralGeometryAdapter",
    "RollingProductivityAdapter", "EpisodeGeometryAdapter",
    "CompletedRegimeGeometryAdapter", "OHLCVDeltaAdapter",
    "STREAM_COMPLETED_1S", "STREAM_COMPLETED_1M", "STREAM_COMPLETED_5M", "STREAM_COMPLETED_5S",
    "EVENT_REGIME_TRANSITION_1M", "EVENT_EPISODE_START", "EVENT_EPISODE_TERMINATE",
]

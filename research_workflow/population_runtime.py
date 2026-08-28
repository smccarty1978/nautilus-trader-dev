"""Generic population runtime dispatch.

The compiled ``population_contract`` decides *when* a candidate row exists. This module
binds each population primitive to its executable runtime:

    population_contract.episode_lifecycle  ->  EpisodePopulationEngine
    (checkpoint / regime_state, no episode)  ->  the collector's existing checkpoint grid

Feature *values* are not this module's concern -- that is ``research_workflow.provider_host``
(Stage 3 integrates the two). ``EpisodePopulationRuntime`` owns the causal state the
sealed deep-pullback episode contract requires:

  * one episode per prevailing accepted 1m regime; reset only on a true prevailing-1m
    regime boundary (TERMINATE) or a new favorable extreme (REARM) -- both are the
    ``EpisodePopulationEngine``'s own declared semantics, driven from ``rearm_on`` /
    ``terminate_on`` in the sealed contract;
  * arm when ``raw adverse excursion / ATR_arm >= threshold``, where ``ATR_arm`` is the
    latest causally completed accepted 1m Wilder ATR available at the 1s completed bar
    that first crosses the threshold, frozen thereafter and never recomputed;
  * ``ATR_arm`` is kept strictly separate from candidate-time ATR (ATR_T);
  * completed 5s regime state via ``CompletedRegimeStateFeed(["5s"])`` -- never a forming
    5s bar; an opposite-prevailing completed 5s regime must actually occur after arm
    before the first completed 5s flip-back to the prevailing direction emits exactly one
    candidate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional

from research.schemas.study_spec import EpisodeLifecycleSpec
from research_workflow.completed_regime_state import CompletedRegimeStateFeed
from research_workflow.episode_population import (
    EpisodeAction,
    EpisodePopulationEngine,
    EpisodeSnapshot,
)

NS = 1_000_000_000

__all__ = [
    "PopulationRuntimeBindingMissing",
    "resolve_population_runtime",
    "CheckpointGridRuntime",
    "EpisodePopulationRuntime",
    "EpisodeCandidateEvent",
]


class PopulationRuntimeBindingMissing(RuntimeError):
    """A compiled population primitive has no executable runtime binding."""


@dataclass(frozen=True)
class EpisodeCandidateEvent:
    """One population-runtime candidate + the governed identity Stage 3 threads through."""

    prevailing_regime_start_ns: int
    prevailing_regime_id: str
    episode_id: str
    arming_cycle_index: int          # 0-based deep-pullback episode index within the regime
    arm_ts: int
    candidate_ts: int
    triggering_completed_5s_ts: int
    prevailing_direction: int
    frozen_atr_arm: float
    pullback_start_ts: int
    prevailing_extreme_ts: int
    counter_regime_close_ts: int     # close_ts of the completed opposite-prevailing 5s regime
    counter_regime_direction: int    # must equal -prevailing_direction
    prior_deep_pullback_count: int


class CheckpointGridRuntime:
    """Non-episode population: the collector's existing causal-checkpoint grid is the
    runtime. This object only signals "keep the legacy path"."""

    mode = "checkpoint_grid"

    def emits_from_checkpoint_grid(self) -> bool:
        return True

    def on_prevailing_regime(self, **_: Any) -> None:  # pragma: no cover - inert
        return None

    def on_completed_1s(self, **_: Any) -> List[EpisodeCandidateEvent]:  # pragma: no cover - inert
        return []


class EpisodePopulationRuntime:
    """Binds ``population_contract.episode_lifecycle`` to ``EpisodePopulationEngine``."""

    mode = "episode_lifecycle"
    engine_class = EpisodePopulationEngine

    def __init__(self, spec: EpisodeLifecycleSpec) -> None:
        self.spec = spec
        self._threshold = float(spec.arm_condition.threshold_atr)
        self._engine = EpisodePopulationEngine(spec)
        self._feed = CompletedRegimeStateFeed(["5s"])
        self._events: List[EpisodeCandidateEvent] = []
        # Canonical episode geometry (Stage 3): the population runtime is the lifecycle
        # authority, so it -- not a second replay in ProviderHost -- drives the canonical
        # GenericEpisodeGeometryProvider.
        from features.trackers.generic_episode_geometry import GenericEpisodeGeometryProvider
        self._geom = GenericEpisodeGeometryProvider()
        self._geom_active = False
        self._max_depth_points = 0.0
        # prevailing 1m regime state
        self._prevailing_direction = 0
        self._prevailing_start_ns: Optional[int] = None
        self._prevailing_regime_id: str = ""
        self._fav_extreme_price: Optional[float] = None
        self._prevailing_extreme_ts: Optional[int] = None
        # favorable_extreme_id epoch. A steady trend makes a new running extreme every
        # bar -- that is NOT the "new_favorable_extreme" rearm trigger. The epoch only
        # advances when, AFTER the episode has armed on a >=1 ATR pullback, price recovers
        # past the extreme the arm was measured from (the pullback failed / new leg).
        self._fav_extreme_epoch = 0
        self._armed_from_extreme: Optional[float] = None
        self._pending_pullback_start: Optional[int] = None
        self._pullback_start_ts: Optional[int] = None
        # arm bookkeeping owned here (the engine stores arm_ts only)
        self._pending_arm_atr: Optional[float] = None
        self._frozen_atr_arm: Optional[float] = None
        self._arm_ts: Optional[int] = None
        self._arming_cycle_index = -1        # bumped to 0 on the first ARMED per regime
        self._prior_deep_pullback_count = 0  # completed arming cycles this prevailing regime
        # counter-event identity (the opposite-prevailing completed 5s regime)
        self._counter_close_ts: Optional[int] = None
        self._counter_direction: Optional[int] = None

    # -- classification --------------------------------------------------- #
    def emits_from_checkpoint_grid(self) -> bool:
        return False

    @property
    def candidate_events(self) -> List[EpisodeCandidateEvent]:
        return list(self._events)

    # -- prevailing 1m regime lifecycle --------------------------------- #
    def on_prevailing_regime(self, *, direction: int, start_ns: int, start_price: float) -> None:
        """A new prevailing accepted 1m regime began (or the first one)."""
        if direction not in (-1, 1):
            raise ValueError("prevailing regime direction must be -1 or +1")
        self._prevailing_direction = int(direction)
        self._prevailing_start_ns = int(start_ns)
        self._prevailing_regime_id = str(int(start_ns))
        self._fav_extreme_price = float(start_price)
        self._prevailing_extreme_ts = int(start_ns)
        self._fav_extreme_epoch = 0
        self._armed_from_extreme = None
        self._pending_pullback_start = None
        self._pullback_start_ts = None
        self._pending_arm_atr = None
        self._frozen_atr_arm = None
        self._arm_ts = None
        self._arming_cycle_index = -1
        self._prior_deep_pullback_count = 0
        self._counter_close_ts = None
        self._counter_direction = None
        if self._geom_active:
            self._geom.terminate_episode()
        self._geom_active = False
        self._max_depth_points = 0.0

    # -- completed 1s driver ------------------------------------------- #
    def on_completed_1s(
        self, *, ts_event: int, ts_init: int, open: float, high: float, low: float,
        close: float, volume: float, completed_1m_atr: Optional[float],
        completed_5s_state: Optional[int] = None,
        completed_5s_transitions: Optional[Any] = None,
    ) -> List[EpisodeCandidateEvent]:
        """Consume one completed 1s bar; return any candidates it establishes.

        ``completed_5s_state`` / ``completed_5s_transitions`` (Stage 3): when the owning
        collector supplies completed 5s regime state from a shared
        ``CompletedRegimeStateFeed``, use it. Absent (Stage 2 / standalone tests), the
        runtime falls back to its own internal 5s feed.
        """
        use_external_5s = completed_5s_state is not None or completed_5s_transitions is not None
        if self._prevailing_direction == 0 or self._prevailing_start_ns is None:
            if not use_external_5s:
                self._feed.on_completed_1s_bar(
                    ts_event=int(ts_event), ts_init=int(ts_init),
                    open=float(open), high=float(high), low=float(low),
                    close=float(close), volume=float(volume),
                )
            return []

        if use_external_5s:
            transitions = tuple(completed_5s_transitions or ())
            inter_state = completed_5s_state
        else:
            transitions = self._feed.on_completed_1s_bar(
                ts_event=int(ts_event), ts_init=int(ts_init),
                open=float(open), high=float(high), low=float(low),
                close=float(close), volume=float(volume),
            )
            st = self._feed.state("5s", decision_ts=int(ts_init))
            inter_state = int(st.regime) if st is not None else None

        d = self._prevailing_direction
        # Running favorable extreme of the prevailing regime, from completed 1s only.
        extreme_candidate = float(high) if d == 1 else float(low)
        made_new_extreme = (
            extreme_candidate > self._fav_extreme_price if d == 1
            else extreme_candidate < self._fav_extreme_price
        )
        if made_new_extreme:
            self._fav_extreme_price = extreme_candidate
            self._prevailing_extreme_ts = int(ts_init)
            self._pending_pullback_start = None
            # canonical episode geometry: a fresh running extreme invalidates any
            # in-progress geometry episode; the next adverse bar starts a new one.
            if self._geom_active:
                self._geom.terminate_episode()
                self._geom_active = False
                self._max_depth_points = 0.0
            # A confirmed pullback that then recovered past its armed-from extreme is a
            # new leg -> new favorable-extreme epoch -> the engine REARMs.
            if self._arm_ts is not None and self._armed_from_extreme is not None and (
                extreme_candidate > self._armed_from_extreme if d == 1
                else extreme_candidate < self._armed_from_extreme
            ):
                self._fav_extreme_epoch += 1
                self._armed_from_extreme = None

        # Adverse excursion from that favorable extreme (completed-1s intrabar).
        adverse_price = float(low) if d == 1 else float(high)
        raw_adverse = max(
            0.0,
            (self._fav_extreme_price - adverse_price) if d == 1
            else (adverse_price - self._fav_extreme_price),
        )
        if raw_adverse > 0.0 and self._pending_pullback_start is None:
            self._pending_pullback_start = int(ts_init)

        atr = (
            float(completed_1m_atr)
            if completed_1m_atr is not None and float(completed_1m_atr) > 0.0
            else None
        )
        arm_depth_atr = (raw_adverse / atr) if atr is not None else 0.0
        self._pending_arm_atr = atr

        if (
            self._arm_ts is None and self._pullback_start_ts is None
            and self._pending_pullback_start is not None
            and arm_depth_atr >= self._threshold
        ):
            self._pullback_start_ts = self._pending_pullback_start

        # --- canonical episode geometry (FLAG A: arm parity) ------------------ #
        # The geometry provider's episode starts at the SAME bar the population runtime
        # records _pending_pullback_start (the first completed-1s adverse excursion from
        # the current favorable extreme) and observes that same bar. It arms itself on
        # exactly the bar the engine arms -- same favorable extreme, same completed-1m
        # ATR, same threshold -- so arm_ts / pullback_start_ts / frozen ATR_arm are
        # identical, with no one-bar offset. A new favorable extreme terminates the
        # geometry episode AND resets _pending_pullback_start together, so a rearm cycle
        # restarts both from the same new first-adverse bar.
        if raw_adverse > 0.0 and not self._geom_active and self._pending_pullback_start is not None:
            self._geom.start_episode(
                start_ns=int(self._pending_pullback_start), direction=d,
                favorable_extreme_price=float(self._fav_extreme_price),
            )
            self._geom_active = True
            self._max_depth_points = 0.0
        if self._geom_active:
            self._max_depth_points = max(self._max_depth_points, raw_adverse)
            if atr is not None:
                self._geom.observe_completed_1s(
                    close_ts=int(ts_init), high=float(high), low=float(low),
                    arm_atr=float(atr), arm_threshold_atr=self._threshold,
                )

        # --- counter-event identity ---------------------------------------- #
        # the opposite-prevailing completed 5s regime (its close_ts) currently active
        if inter_state in (-1, 1) and int(inter_state) == -d:
            # the just-completed 5s bar close is the running counter-regime identity
            self._counter_direction = -d
            for tr in transitions:
                if tr.current is not None and int(tr.current.regime) == -d:
                    self._counter_close_ts = int(tr.current.close_ts)
            if self._counter_close_ts is None and not use_external_5s:
                cs = self._feed.state("5s", decision_ts=int(ts_init))
                if cs is not None and int(cs.regime) == -d:
                    self._counter_close_ts = int(cs.close_ts)

        inter = int(inter_state) if inter_state in (-1, 1) else 0
        emitted: List[EpisodeCandidateEvent] = []
        self._feed_snapshot(ts_init, arm_depth_atr, inter, transition=None,
                            emitted=emitted, triggering_5s_ts=None, prev_state=None)
        for tr in transitions:
            if tr.previous is None or tr.current is None:
                continue
            frm, to = int(tr.previous.regime), int(tr.current.regime)
            if frm not in (-1, 1) or to not in (-1, 1) or frm == to:
                continue
            self._feed_snapshot(
                ts_init, arm_depth_atr, to, transition=(frm, to), emitted=emitted,
                triggering_5s_ts=int(tr.current.close_ts),
                prev_state=tr.previous,
            )
        return emitted

    # -- Stage 3: canonical episode geometry at candidate T -------------- #
    def episode_geometry_snapshot(
        self, *, candidate_ts: int, candidate_price: float, candidate_atr: float,
        structural_expansion_points: Optional[float] = None,
    ) -> dict:
        """Governed pullback-episode geometry at candidate T (candidate ATR = ATR_T)."""
        base = {
            "max_depth_points": self._max_depth_points,
            "seconds_since_prevailing_directional_extreme": (
                (int(candidate_ts) - int(self._prevailing_extreme_ts)) / NS
                if self._prevailing_extreme_ts is not None else None
            ),
            # prior_deep_pullback_count is authoritative on the EpisodeCandidateEvent
            # (captured BEFORE this candidate is counted); the collector threads it.
        }
        if not self._geom_active or self._arm_ts is None:
            return {
                **base,
                "pullback_max_depth_atr": None, "pullback_current_depth_atr": None,
                "pullback_recovery_from_extreme_atr": None,
                "pullback_fraction_of_structural_move": None,
                "pullback_elapsed_seconds": None, "pullback_post_arm_seconds": None,
            }
        geom = self._geom.candidate_snapshot(
            candidate_ts=int(candidate_ts), candidate_price=float(candidate_price),
            candidate_atr=float(candidate_atr),
            structural_expansion_points=structural_expansion_points,
        )
        return {**base, **{k: geom.get(k) for k in (
            "pullback_max_depth_atr", "pullback_current_depth_atr",
            "pullback_recovery_from_extreme_atr", "pullback_fraction_of_structural_move",
            "pullback_elapsed_seconds", "pullback_post_arm_seconds",
        )}}

    # -- engine plumbing --------------------------------------------- #
    def _feed_snapshot(
        self, ts_init: int, arm_depth_atr: float, intermediate_direction: int,
        *, transition, emitted: List[EpisodeCandidateEvent], triggering_5s_ts: Optional[int],
        prev_state=None,
    ) -> None:
        # Recheck-and-commit the pullback start immediately before every snapshot
        # (base and each completed-5s transition in the same bar). Real data can
        # deliver several completed-5s transitions inside one 1s bar; if an earlier
        # transition snapshot drives a REARM/TERMINATE that clears the committed
        # start, a later transition snapshot in the same bar would otherwise reach
        # the engine's arm check with arm_depth_atr >= threshold and no start
        # (PULLBACK_START_REQUIRED_AT_ARM). The pending start is authoritative here.
        if (
            self._arm_ts is None and self._pullback_start_ts is None
            and self._pending_pullback_start is not None
            and float(arm_depth_atr) >= self._threshold
        ):
            self._pullback_start_ts = self._pending_pullback_start

        snap = EpisodeSnapshot(
            timestamp_ns=int(ts_init),
            prevailing_regime_id=str(self._prevailing_start_ns),
            prevailing_direction=self._prevailing_direction,
            favorable_extreme_id=f"{self._prevailing_start_ns}:{self._fav_extreme_epoch}",
            arm_depth_atr=float(arm_depth_atr),
            intermediate_direction=int(intermediate_direction),
            transition_from=transition[0] if transition else None,
            transition_to=transition[1] if transition else None,
            pullback_start_ts=self._pullback_start_ts,
        )
        decision = self._engine.on_event(snap)
        if decision.action is EpisodeAction.ARMED:
            self._frozen_atr_arm = self._pending_arm_atr
            self._arm_ts = int(decision.arm_ts)
            self._armed_from_extreme = self._fav_extreme_price
            self._arming_cycle_index += 1
        elif decision.action in (EpisodeAction.REARM, EpisodeAction.TERMINATE):
            self._frozen_atr_arm = None
            self._arm_ts = None
            self._armed_from_extreme = None
            self._pullback_start_ts = None  # mirrors the engine's own _reset
            # New leg: if this same bar still carries an adverse excursion from the
            # (new) favorable extreme, its pending pullback-start is this bar --
            # do not lose it just because the rearm happened mid-bar.
            self._pending_pullback_start = (
                int(ts_init) if float(arm_depth_atr) > 0.0 else None
            )
        elif decision.action is EpisodeAction.EMIT:
            d = self._prevailing_direction
            # the counter regime is the opposite-prevailing 5s regime that just ended --
            # the `previous` side of the (opposite -> aligned) flip-back transition.
            counter_close = None
            counter_dir = None
            if prev_state is not None and int(prev_state.regime) == -d:
                counter_close = int(prev_state.close_ts)
                counter_dir = -d
            elif self._counter_close_ts is not None and self._counter_direction == -d:
                counter_close = int(self._counter_close_ts)
                counter_dir = -d
            event = EpisodeCandidateEvent(
                prevailing_regime_start_ns=int(self._prevailing_start_ns),
                prevailing_regime_id=str(self._prevailing_regime_id),
                episode_id=str(self._engine.episode_id),
                arming_cycle_index=int(max(0, self._arming_cycle_index)),
                arm_ts=int(self._arm_ts if self._arm_ts is not None else decision.arm_ts),
                candidate_ts=int(decision.timestamp_ns),
                triggering_completed_5s_ts=int(triggering_5s_ts) if triggering_5s_ts is not None else int(decision.timestamp_ns),
                prevailing_direction=int(d),
                frozen_atr_arm=float(self._frozen_atr_arm) if self._frozen_atr_arm is not None else float("nan"),
                pullback_start_ts=int(decision.pullback_start_ts) if decision.pullback_start_ts is not None else int(self._pullback_start_ts or 0),
                prevailing_extreme_ts=int(self._prevailing_extreme_ts if self._prevailing_extreme_ts is not None else self._prevailing_start_ns),
                counter_regime_close_ts=int(counter_close) if counter_close is not None else -1,
                counter_regime_direction=int(counter_dir) if counter_dir is not None else 0,
                prior_deep_pullback_count=int(self._prior_deep_pullback_count),
            )
            self._prior_deep_pullback_count += 1
            self._events.append(event)
            emitted.append(event)


def resolve_population_runtime(population_contract: Mapping[str, Any] | None):
    """compiled population primitive -> executable runtime. Fail closed.

    ``episode_lifecycle`` wins when present (an episode study cannot use the checkpoint
    grid). No study_id branches.
    """
    pc = dict(population_contract or {})
    episode = pc.get("episode_lifecycle")
    if episode:
        spec = episode if isinstance(episode, EpisodeLifecycleSpec) else EpisodeLifecycleSpec.model_validate(episode)
        return EpisodePopulationRuntime(spec)
    if pc.get("causal_checkpoint") or pc.get("qualification") is not None or pc.get("population_type"):
        return CheckpointGridRuntime()
    raise PopulationRuntimeBindingMissing(
        "RUNTIME_POPULATION_BINDING_MISSING: population_contract declares no supported "
        f"primitive (keys={sorted(pc)}); expected episode_lifecycle or a checkpoint/"
        "regime_state population"
    )

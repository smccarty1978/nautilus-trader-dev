"""Generic bounded stateful episode lifecycle for governed candidate populations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from research.analysis.identity import canonical_sha256
from research.schemas.study_spec import EpisodeLifecycleSpec


class EpisodeAction(str, Enum):
    NOOP = "NOOP"
    ARMED = "ARMED"
    INTERMEDIATE_SATISFIED = "INTERMEDIATE_SATISFIED"
    EMIT = "EMIT"
    TERMINATE = "TERMINATE"
    REARM = "REARM"


@dataclass(frozen=True)
class EpisodeSnapshot:
    """Causal state available at one completed input/event timestamp."""

    timestamp_ns: int
    prevailing_regime_id: str
    prevailing_direction: int
    favorable_extreme_id: str
    # This is deliberately the excursion divided by the ATR available at the
    # completed observation that crosses the arm threshold.  It is *not* a
    # candidate-time geometry value and must never be recalculated using a
    # later ATR.
    arm_depth_atr: float
    intermediate_direction: int
    transition_from: Optional[int] = None
    transition_to: Optional[int] = None
    # The caller owns the economically meaningful causal definition of a
    # pullback start (normally the first completed 1s adverse excursion from a
    # prevailing extreme).  Requiring it at arm avoids an implicit or
    # retrospective start convention in this generic lifecycle engine.
    pullback_start_ts: Optional[int] = None

    def __post_init__(self) -> None:
        if self.prevailing_direction not in (-1, 1):
            raise ValueError("prevailing_direction must be -1 or +1")
        if self.intermediate_direction not in (-1, 0, 1):
            raise ValueError("intermediate_direction must be -1, 0, or +1")
        if (self.transition_from is None) != (self.transition_to is None):
            raise ValueError("transition_from and transition_to must be supplied together")
        if self.pullback_start_ts is not None and self.pullback_start_ts > self.timestamp_ns:
            raise ValueError("pullback_start_ts must be causally available at the snapshot")


@dataclass(frozen=True)
class EpisodeDecision:
    action: EpisodeAction
    timestamp_ns: int
    episode_id: Optional[str]
    reason: str
    candidate_number: int = 0
    arm_ts: Optional[int] = None
    pullback_start_ts: Optional[int] = None


class EpisodePopulationEngine:
    """Evaluate one declared directional threshold/transition episode protocol.

    The public states are actions and immutable provenance. Internal booleans are kept
    intentionally small; this is not a universal finite-state-machine DSL.
    """

    def __init__(self, spec: EpisodeLifecycleSpec) -> None:
        self.spec = spec
        self._last_ts: Optional[int] = None
        self._regime_id: Optional[str] = None
        self._extreme_id: Optional[str] = None
        self._episode_id: Optional[str] = None
        self._arm_ts: Optional[int] = None
        self._pullback_start_ts: Optional[int] = None
        self._intermediate_satisfied = False
        self._emitted = 0

    @property
    def episode_id(self) -> Optional[str]:
        return self._episode_id

    @property
    def armed(self) -> bool:
        return self._arm_ts is not None

    def _decision(self, action: EpisodeAction, snapshot: EpisodeSnapshot, reason: str) -> EpisodeDecision:
        return EpisodeDecision(
            action, snapshot.timestamp_ns, self._episode_id, reason, self._emitted,
            self._arm_ts, self._pullback_start_ts,
        )

    def _reset(self, snapshot: EpisodeSnapshot) -> None:
        self._regime_id = snapshot.prevailing_regime_id
        self._extreme_id = snapshot.favorable_extreme_id
        self._episode_id = None
        self._arm_ts = None
        self._pullback_start_ts = None
        self._intermediate_satisfied = False
        self._emitted = 0

    @staticmethod
    def _relation(direction: int, prevailing: int, relation: str) -> bool:
        if relation == "aligned_prevailing":
            return direction == prevailing
        if relation == "opposite_prevailing":
            return direction == -prevailing
        raise ValueError(f"unknown direction relation: {relation!r}")

    def on_event(self, snapshot: EpisodeSnapshot) -> EpisodeDecision:
        ts = int(snapshot.timestamp_ns)
        if self._last_ts is not None and ts < self._last_ts:
            raise ValueError("episode snapshots must be timestamp-monotonic")
        self._last_ts = ts

        if self._regime_id is None:
            self._reset(snapshot)
        elif snapshot.prevailing_regime_id != self._regime_id:
            prior_id = self._episode_id
            self._reset(snapshot)
            return EpisodeDecision(
                EpisodeAction.TERMINATE, ts, prior_id,
                "prevailing_regime_flip", 0,
            )
        elif snapshot.favorable_extreme_id != self._extreme_id:
            prior_id = self._episode_id
            self._reset(snapshot)
            return EpisodeDecision(
                EpisodeAction.REARM, ts, prior_id,
                "new_favorable_extreme", 0, None, None,
            )

        if snapshot.pullback_start_ts is not None:
            start_ts = int(snapshot.pullback_start_ts)
            if self._pullback_start_ts is None:
                self._pullback_start_ts = start_ts
            elif start_ts != self._pullback_start_ts:
                raise ValueError("PULLBACK_START_MUTATED_WITHIN_EPISODE")

        if self._emitted >= self.spec.max_candidates_per_episode:
            return self._decision(EpisodeAction.NOOP, snapshot, "candidate_limit_reached")

        if self._arm_ts is None:
            if snapshot.arm_depth_atr < self.spec.arm_condition.threshold_atr:
                return self._decision(EpisodeAction.NOOP, snapshot, "arm_threshold_not_reached")
            if self._pullback_start_ts is None:
                raise ValueError("PULLBACK_START_REQUIRED_AT_ARM")
            self._arm_ts = ts
            self._episode_id = canonical_sha256({
                "prevailing_regime_id": snapshot.prevailing_regime_id,
                "favorable_extreme_id": snapshot.favorable_extreme_id,
                "arm_ts": ts,
            })[:32]
            if (
                self.spec.required_event.active_at_arm_counts
                and self._relation(
                    snapshot.intermediate_direction,
                    snapshot.prevailing_direction,
                    self.spec.required_event.relation,
                )
            ):
                self._intermediate_satisfied = True
            return self._decision(EpisodeAction.ARMED, snapshot, "arm_threshold_reached")

        if (
            not self._intermediate_satisfied
            and self._relation(
                snapshot.intermediate_direction,
                snapshot.prevailing_direction,
                self.spec.required_event.relation,
            )
        ):
            self._intermediate_satisfied = True
            return self._decision(
                EpisodeAction.INTERMEDIATE_SATISFIED,
                snapshot,
                "required_intermediate_state_observed",
            )

        transition_matches = (
            snapshot.transition_from is not None
            and self._relation(
                snapshot.transition_from,
                snapshot.prevailing_direction,
                self.spec.emit_condition.from_relation,
            )
            and self._relation(
                snapshot.transition_to,
                snapshot.prevailing_direction,
                self.spec.emit_condition.to_relation,
            )
        )
        if (
            self._intermediate_satisfied
            and transition_matches
            and ts > self._arm_ts
        ):
            self._emitted += 1
            return self._decision(EpisodeAction.EMIT, snapshot, "emit_transition_observed")

        return self._decision(EpisodeAction.NOOP, snapshot, "episode_active")


__all__ = [
    "EpisodeAction", "EpisodeDecision", "EpisodeLifecycleSpec",
    "EpisodePopulationEngine", "EpisodeSnapshot",
]

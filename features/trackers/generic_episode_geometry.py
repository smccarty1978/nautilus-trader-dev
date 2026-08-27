"""Causal geometry for a bounded directional pullback episode.

The population lifecycle decides *whether* an episode qualifies.  This provider
only stores completed 1s observations belonging to an already-declared episode
and produces immutable candidate-time geometry.  The two ATR clocks are
explicit by API: ``arm_atr`` determines eligibility once, while
``candidate_atr`` normalizes candidate geometry without changing eligibility.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping


NS = 1_000_000_000


@dataclass
class _Episode:
    direction: int
    start_ns: int
    favorable_extreme_price: float
    max_depth_points: float = 0.0
    deepest_price: float | None = None
    last_completed_ts: int | None = None
    arm_ts: int | None = None
    arm_atr: float | None = None
    arm_depth_points: float | None = None


class GenericEpisodeGeometryProvider:
    """Track one completed-bar directional episode at a time.

    ``start_episode`` intentionally takes a start timestamp from the owning
    population adapter.  It does not infer a pullback start from an arbitrary
    close/change threshold.  This makes elapsed duration reproducible across
    studies that share the lifecycle but declare different start semantics.
    """

    def __init__(self) -> None:
        self._episode: _Episode | None = None

    def start_episode(
        self, *, start_ns: int, direction: int, favorable_extreme_price: float,
    ) -> None:
        if direction not in (-1, 1):
            raise ValueError("episode direction must be -1 or +1")
        if not math.isfinite(favorable_extreme_price):
            raise ValueError("favorable_extreme_price must be finite")
        self._episode = _Episode(
            direction=direction, start_ns=int(start_ns),
            favorable_extreme_price=float(favorable_extreme_price),
        )

    def terminate_episode(self) -> None:
        self._episode = None

    def observe_completed_1s(
        self, *, close_ts: int, high: float, low: float, arm_atr: float,
        arm_threshold_atr: float,
    ) -> bool:
        """Update from one fully completed 1s bar and arm once if qualified.

        Returns whether the episode became armed on this completed bar.  The
        adverse extreme deliberately uses the completed bar low/high, while
        candidate-time current depth is supplied separately from the candidate
        reference price.
        """
        episode = self._require_episode()
        close_ts = int(close_ts)
        if close_ts < episode.start_ns:
            raise ValueError("episode observation precedes pullback start")
        if episode.last_completed_ts is not None and close_ts <= episode.last_completed_ts:
            raise ValueError("NON_MONOTONIC_COMPLETED_1S_OBSERVATION")
        if not math.isfinite(arm_atr) or arm_atr <= 0.0:
            raise ValueError("arm_atr must be finite and positive")
        if not math.isfinite(arm_threshold_atr) or arm_threshold_atr <= 0.0:
            raise ValueError("arm_threshold_atr must be finite and positive")
        adverse_price = float(low) if episode.direction == 1 else float(high)
        raw_depth = (
            episode.favorable_extreme_price - adverse_price
            if episode.direction == 1 else adverse_price - episode.favorable_extreme_price
        )
        if raw_depth > episode.max_depth_points:
            episode.max_depth_points = raw_depth
            episode.deepest_price = adverse_price
        episode.last_completed_ts = close_ts
        if episode.arm_ts is None and raw_depth / arm_atr >= arm_threshold_atr:
            episode.arm_ts = close_ts
            episode.arm_atr = float(arm_atr)
            episode.arm_depth_points = raw_depth
            return True
        return False

    def candidate_snapshot(
        self, *, candidate_ts: int, candidate_price: float, candidate_atr: float,
        structural_expansion_points: float | None = None,
    ) -> Mapping[str, float | int | None]:
        """Return candidate-time geometry without changing the arm decision."""
        episode = self._require_episode()
        candidate_ts = int(candidate_ts)
        if episode.last_completed_ts is None or candidate_ts < episode.last_completed_ts:
            raise ValueError("CANDIDATE_BEFORE_LATEST_COMPLETED_1S_OBSERVATION")
        if episode.arm_ts is None or episode.arm_atr is None:
            raise ValueError("EPISODE_NOT_ARMED")
        if not math.isfinite(candidate_atr) or candidate_atr <= 0.0:
            raise ValueError("candidate_atr must be finite and positive")
        price = float(candidate_price)
        current_depth = (
            episode.favorable_extreme_price - price
            if episode.direction == 1 else price - episode.favorable_extreme_price
        )
        # A price may have recovered beyond the favorable extreme.  Current
        # adverse depth is economic distance, therefore never negative.
        current_depth = max(0.0, current_depth)
        recovery = max(0.0, episode.max_depth_points - current_depth)
        fraction = None
        if structural_expansion_points is not None and structural_expansion_points > 0.0:
            fraction = episode.max_depth_points / float(structural_expansion_points)
        return {
            "pullback_max_depth_atr": episode.max_depth_points / candidate_atr,
            "pullback_current_depth_atr": current_depth / candidate_atr,
            "pullback_recovery_from_extreme_atr": recovery / candidate_atr,
            "pullback_post_arm_seconds": (candidate_ts - episode.arm_ts) / NS,
            "pullback_elapsed_seconds": (candidate_ts - episode.start_ns) / NS,
            "pullback_fraction_of_structural_move": fraction,
            "arm_depth_atr": episode.arm_depth_points / episode.arm_atr,
            "arm_ts": episode.arm_ts,
            "pullback_start_ts": episode.start_ns,
        }

    def _require_episode(self) -> _Episode:
        if self._episode is None:
            raise ValueError("NO_ACTIVE_EPISODE")
        return self._episode


__all__ = ["GenericEpisodeGeometryProvider"]

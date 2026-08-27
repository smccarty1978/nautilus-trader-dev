from __future__ import annotations

import pytest

from research.schemas.study_spec import EpisodeLifecycleSpec
from research_workflow.episode_population import (
    EpisodeAction,
    EpisodePopulationEngine,
    EpisodeSnapshot,
)


def spec():
    return EpisodeLifecycleSpec.model_validate({
        "arm_condition": {
            "kind": "directional_adverse_excursion",
            "threshold_atr": 1.0,
            "price_source": "completed_1s_intrabar",
        },
        "required_event": {
            "kind": "direction_relation", "source": "completed_5s_regime",
            "relation": "opposite_prevailing", "active_at_arm_counts": True,
        },
        "emit_condition": {
            "kind": "direction_transition", "source": "completed_5s_regime",
            "from_relation": "opposite_prevailing",
            "to_relation": "aligned_prevailing", "strictly_after_arm": True,
        },
        "rearm_on": ["new_favorable_extreme"],
        "terminate_on": ["prevailing_regime_flip"],
        "max_candidates_per_episode": 1,
    })


def snap(ts, *, prevailing=1, regime="r1", extreme="e1", depth=0.0,
         state=1, transition=None, pullback_start=1):
    return EpisodeSnapshot(
        timestamp_ns=ts, prevailing_regime_id=regime,
        prevailing_direction=prevailing, favorable_extreme_id=extreme,
        arm_depth_atr=depth, intermediate_direction=state,
        transition_from=transition[0] if transition else None,
        transition_to=transition[1] if transition else None,
        pullback_start_ts=pullback_start,
    )


def test_counter_state_active_before_arm_counts_and_first_later_flip_emits_once():
    engine = EpisodePopulationEngine(spec())
    engine.on_event(snap(1, state=-1))
    armed = engine.on_event(snap(2, depth=1.0, state=-1))
    assert armed.action is EpisodeAction.ARMED
    emitted = engine.on_event(snap(3, depth=0.5, state=1, transition=(-1, 1)))
    assert emitted.action is EpisodeAction.EMIT
    assert engine.on_event(snap(4, state=1, transition=(-1, 1))).action is EpisodeAction.NOOP


def test_counter_state_may_begin_after_arm():
    engine = EpisodePopulationEngine(spec())
    assert engine.on_event(snap(1, depth=1.1, state=1)).action is EpisodeAction.ARMED
    assert engine.on_event(snap(2, depth=1.1, state=-1, transition=(1, -1))).action is EpisodeAction.INTERMEDIATE_SATISFIED
    assert engine.on_event(snap(3, state=1, transition=(-1, 1))).action is EpisodeAction.EMIT


def test_flip_at_same_timestamp_as_arm_is_not_retroactive_candidate():
    engine = EpisodePopulationEngine(spec())
    result = engine.on_event(snap(5, depth=1.0, state=1, transition=(-1, 1)))
    assert result.action is EpisodeAction.ARMED
    assert engine.on_event(snap(6, state=1)).action is EpisodeAction.NOOP


def test_arm_depth_is_the_arm_time_value_not_a_candidate_atr_recalculation():
    engine = EpisodePopulationEngine(spec())
    # The adapter has already divided the raw completed-1s excursion by its
    # current completed 1m ATR.  Candidate ATR is intentionally not part of
    # this lifecycle API, so it cannot retrospectively disqualify the arm.
    armed = engine.on_event(snap(10, depth=1.01, state=-1, pullback_start=4))
    assert armed.action is EpisodeAction.ARMED
    assert armed.arm_ts == 10
    assert armed.pullback_start_ts == 4


def test_arm_requires_an_explicit_causal_pullback_start():
    engine = EpisodePopulationEngine(spec())
    with pytest.raises(ValueError, match="PULLBACK_START_REQUIRED_AT_ARM"):
        engine.on_event(snap(10, depth=1.0, state=-1, pullback_start=None))


@pytest.mark.parametrize("prevailing", [1, -1])
def test_directional_inverse(prevailing):
    engine = EpisodePopulationEngine(spec())
    opposite = -prevailing
    engine.on_event(snap(1, prevailing=prevailing, depth=1.0, state=opposite))
    result = engine.on_event(
        snap(2, prevailing=prevailing, state=prevailing,
             transition=(opposite, prevailing))
    )
    assert result.action is EpisodeAction.EMIT


def test_new_favorable_extreme_rearms_and_prevailing_flip_terminates():
    engine = EpisodePopulationEngine(spec())
    engine.on_event(snap(1, depth=1.0, state=-1))
    old_id = engine.episode_id
    rearm = engine.on_event(snap(2, extreme="e2", state=1))
    assert rearm.action is EpisodeAction.REARM and rearm.episode_id == old_id
    assert engine.armed is False
    engine.on_event(snap(3, extreme="e2", depth=1.0, state=-1))
    terminate = engine.on_event(
        snap(4, prevailing=-1, regime="r2", extreme="e3", state=1)
    )
    assert terminate.action is EpisodeAction.TERMINATE
    assert engine.armed is False

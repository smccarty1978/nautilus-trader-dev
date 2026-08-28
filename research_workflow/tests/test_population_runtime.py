"""Stage 2 -- generic population runtime (EpisodePopulationEngine binding).

Synthetic completed-event streams only. No feature snapshotting (Stage 3), no real
data, no TRAIN/OOS. Exercises the SAME ``EpisodePopulationRuntime`` object that
``GenericStudyCollector.__init__`` builds and drives.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_workflow.population_runtime import (
    CheckpointGridRuntime,
    EpisodePopulationRuntime,
    PopulationRuntimeBindingMissing,
    resolve_population_runtime,
)

NS = 1_000_000_000
REPO = Path(__file__).resolve().parents[2]
STUDY = REPO / "studies" / "deep_pullback_5s_reacceleration_model"
ATR = 10.0


def _episode_spec():
    cs = json.loads((STUDY / "compiled_study.json").read_text(encoding="utf-8"))
    return cs["contracts"]["population_contract"]["episode_lifecycle"]


def _runtime() -> EpisodePopulationRuntime:
    return resolve_population_runtime({"episode_lifecycle": _episode_spec()})


# --------------------------------------------------------------------------- #
# Synthetic 1s tape helpers. The 5s regime is derived by CompletedRegimeStateFeed
# from the 1s bars we feed; we only shape the price path.
# --------------------------------------------------------------------------- #
def _feed_seconds(rt: EpisodePopulationRuntime, t0: int, t1: int, price_fn, *, atr=ATR, low_fn=None):
    """Feed contiguous completed 1s bars for [t0, t1); return all emitted events.

    ``low_fn(t) -> extra downward points`` lets a test spike the intrabar low without
    moving the bar close (to arm on adverse excursion while the 5s regime stays put).
    """
    out = []
    for t in range(t0, t1):
        p0, p1 = price_fn(t), price_fn(t + 1)
        hi, lo = max(p0, p1) + 0.25, min(p0, p1) - 0.25
        if low_fn is not None:
            lo -= max(0.0, low_fn(t))
        ev = rt.on_completed_1s(
            ts_event=t * NS, ts_init=(t + 1) * NS, open=p0, high=hi, low=lo, close=p1,
            volume=100.0, completed_1m_atr=atr,
        )
        out.extend(ev)
    return out


def _bull_pullback_reaccel(t: int) -> float:
    """Prevailing bull: warmup up -> peak -> sharp pullback -> re-accel (stays below peak)."""
    if t <= 300:
        return 20000.0 + 0.5 * t                 # 20000 -> 20150 (peak at t=300)
    if t <= 345:
        return 20150.0 - 2.0 * (t - 300)          # -> 20060  (pullback, ~90 pts / 9 ATR)
    if t <= 400:
        return 20060.0 + 1.4 * (t - 345)          # -> ~20137 (re-accel, still < 20150 peak)
    return 20137.0                                 # plateau below the peak -> no new extreme


# --------------------------------------------------------------------------- #
# 1. dispatch resolution
# --------------------------------------------------------------------------- #
def test_dispatch_binds_episode_lifecycle_to_the_engine():
    rt = _runtime()
    assert isinstance(rt, EpisodePopulationRuntime)
    assert rt.emits_from_checkpoint_grid() is False
    assert rt.engine_class.__name__ == "EpisodePopulationEngine"


def test_dispatch_keeps_non_episode_studies_on_the_checkpoint_grid():
    for pc in ({"population_type": "regime_state"}, {"causal_checkpoint": {"checkpoint_frequency": "5s"}}):
        rt = resolve_population_runtime(pc)
        assert isinstance(rt, CheckpointGridRuntime)
        assert rt.emits_from_checkpoint_grid() is True


def test_dispatch_fails_closed_on_unknown_primitive():
    with pytest.raises(PopulationRuntimeBindingMissing, match="RUNTIME_POPULATION_BINDING_MISSING"):
        resolve_population_runtime({})


# --------------------------------------------------------------------------- #
# 12. synthetic production-path acceptance
# --------------------------------------------------------------------------- #
def test_synthetic_production_path_emits_exactly_one_candidate_per_episode():
    rt = _runtime()
    # warmup: establish the 5s uptrend regime and the prevailing 1m regime
    _feed_seconds(rt, 0, 100, _bull_pullback_reaccel)
    rt.on_prevailing_regime(direction=1, start_ns=100 * NS, start_price=_bull_pullback_reaccel(100))

    # rise to the peak: no adverse excursion -> 0 candidates, not armed
    assert _feed_seconds(rt, 100, 301, _bull_pullback_reaccel) == []
    assert rt._arm_ts is None

    # pullback crossing 1 ATR -> arm; opposite completed-5s regime appears; still 0
    ev_pullback = _feed_seconds(rt, 301, 346, _bull_pullback_reaccel)
    assert ev_pullback == []
    assert rt._arm_ts is not None
    armed_at = rt._arm_ts
    frozen = rt._frozen_atr_arm
    assert frozen == pytest.approx(ATR)

    # first completed-5s flip-back to the prevailing direction -> exactly 1 candidate
    ev_reaccel = _feed_seconds(rt, 346, 401, _bull_pullback_reaccel)
    assert len(ev_reaccel) == 1
    cand = ev_reaccel[0]
    assert cand.prevailing_direction == 1
    assert cand.arm_ts == armed_at
    assert cand.candidate_ts >= cand.arm_ts
    assert cand.candidate_ts >= cand.triggering_completed_5s_ts
    assert cand.frozen_atr_arm == pytest.approx(ATR)
    assert cand.pullback_start_ts <= cand.arm_ts

    # later events in the SAME prevailing episode (plateau below the peak) -> nothing more
    more = _feed_seconds(rt, 401, 480, _bull_pullback_reaccel)
    # add a synthetic extra 5s down-then-up wiggle that does not make a new high
    def _wiggle(t):
        if t <= 500:
            return 20137.0 - 1.2 * (t - 480)
        return 20137.0 - 24.0 + 1.2 * (t - 500)
    more += _feed_seconds(rt, 480, 520, _wiggle)
    assert more == []
    assert len(rt.candidate_events) == 1

    # new prevailing 1m regime -> new episode -> may independently emit exactly 1
    rt.on_prevailing_regime(direction=-1, start_ns=520 * NS, start_price=_wiggle(520))

    def _bear(t):
        if t <= 620:
            return 20113.0 - 0.6 * (t - 520)       # 20113 -> ~20053 (bear trend, new lows)
        if t <= 665:
            return 20053.0 + 2.0 * (t - 620)       # pullback UP ~90 pts (adverse for bear)
        if t <= 720:
            return 20143.0 - 1.4 * (t - 665)       # re-accel DOWN, above the prior low
        return 20066.0
    ev_bear = _feed_seconds(rt, 520, 720, _bear)
    assert len(ev_bear) == 1
    assert ev_bear[0].prevailing_direction == -1
    assert ev_bear[0].candidate_ts >= ev_bear[0].arm_ts
    assert len(rt.candidate_events) == 2


# --------------------------------------------------------------------------- #
# 13. adversarial causal tests
# --------------------------------------------------------------------------- #
def _steady_bull(t: int) -> float:
    return 20000.0 + 0.5 * min(t, 300) + (0.15 * (t - 300) if t > 300 else 0.0)


def _armed_runtime_bull_no_counter():
    """Bull prevailing regime, armed via a one-second intrabar low spike (>1 ATR adverse),
    while the 5s regime never leaves +1 -- so the required counter event has NOT occurred."""
    rt = _runtime()
    _feed_seconds(rt, 0, 100, _steady_bull)
    rt.on_prevailing_regime(direction=1, start_ns=100 * NS, start_price=_steady_bull(100))
    _feed_seconds(rt, 100, 320, _steady_bull)
    # single-second intrabar low 15 pts below the running extreme -> arm_depth 1.5
    _feed_seconds(rt, 320, 321, _steady_bull, low_fn=lambda t: 15.0)
    return rt


def test_A_before_arm_no_flipback_sequence_can_emit():
    rt = _runtime()
    _feed_seconds(rt, 0, 100, _bull_pullback_reaccel)
    rt.on_prevailing_regime(direction=1, start_ns=100 * NS, start_price=_bull_pullback_reaccel(100))

    # a full down-then-up 5s sequence with NO 1-ATR adverse excursion (shallow dip)
    def _shallow(t):
        if t <= 150:
            return 20050.0 + 0.4 * (t - 100)
        if t <= 175:
            return 20070.0 - 0.3 * (t - 150)       # ~7.5 pt dip << 1 ATR
        return 20062.5 + 0.3 * (t - 175)
    ev = _feed_seconds(rt, 100, 260, _shallow)
    assert ev == []
    assert rt._arm_ts is None


def test_B_arm_without_counter_event_cannot_emit():
    rt = _armed_runtime_bull_no_counter()
    assert rt._arm_ts is not None
    # the 5s regime was never -1 after arm; keep rising -> no opposite counter event -> no emit
    ev = _feed_seconds(rt, 321, 460, _steady_bull)
    assert ev == []


def test_C_forming_5s_state_cannot_satisfy_counter_or_flipback():
    # CompletedRegimeStateFeed only ever publishes completed 5s buckets. Feed 1s bars
    # that do not complete a 5s bucket beyond the last boundary and confirm the runtime
    # sees no new 5s regime/transition from the partial bucket.
    rt = _armed_runtime_bull_no_counter()
    before = rt._feed.state("5s", decision_ts=321 * NS)
    _feed_seconds(rt, 321, 324, _steady_bull)  # 3 s only, does not close the 5s bucket at 325
    after = rt._feed.state("5s", decision_ts=324 * NS)
    assert (before.close_ts if before else None) == (after.close_ts if after else None)


def test_D_only_the_first_valid_flipback_emits():
    rt = _runtime()
    _feed_seconds(rt, 0, 100, _bull_pullback_reaccel)
    rt.on_prevailing_regime(direction=1, start_ns=100 * NS, start_price=_bull_pullback_reaccel(100))
    _feed_seconds(rt, 100, 346, _bull_pullback_reaccel)
    first = _feed_seconds(rt, 346, 401, _bull_pullback_reaccel)
    assert len(first) == 1
    # a second identical opposite->aligned 5s cycle, still no new favorable extreme
    def _second_cycle(t):
        if t <= 440:
            return 20137.0 - 1.6 * (t - 401)       # down again
        if t <= 480:
            return 20137.0 - 62.4 + 1.6 * (t - 440)  # back up, still < 20150 peak
        return 20137.0
    second = _feed_seconds(rt, 401, 500, _second_cycle)
    assert second == []


def test_E_atr_arm_is_frozen_and_separate_from_later_atr():
    rt = _runtime()
    _feed_seconds(rt, 0, 100, _bull_pullback_reaccel, atr=10.0)
    rt.on_prevailing_regime(direction=1, start_ns=100 * NS, start_price=_bull_pullback_reaccel(100))
    _feed_seconds(rt, 100, 301, _bull_pullback_reaccel, atr=10.0)
    _feed_seconds(rt, 301, 346, _bull_pullback_reaccel, atr=10.0)   # arms at ATR 10
    assert rt._frozen_atr_arm == pytest.approx(10.0)
    # ATR now changes materially for every later bar
    ev = _feed_seconds(rt, 346, 401, _bull_pullback_reaccel, atr=25.0)
    assert len(ev) == 1
    assert ev[0].frozen_atr_arm == pytest.approx(10.0)   # unchanged by later ATR


def test_F_prevailing_regime_change_does_not_leak_armed_state():
    rt = _armed_runtime_bull_no_counter()
    assert rt._arm_ts is not None
    rt.on_prevailing_regime(direction=-1, start_ns=330 * NS, start_price=_steady_bull(330))
    assert rt._arm_ts is None and rt._frozen_atr_arm is None
    # the first snapshot of the new regime TERMINATEs the old one; no candidate leaks
    def _bear(t):
        return _steady_bull(330) - 0.5 * (t - 330)
    ev = _feed_seconds(rt, 330, 400, _bear)
    assert all(e.prevailing_direction == -1 for e in ev)


def test_G_candidate_ts_never_precedes_its_establishing_5s_event():
    rt = _runtime()
    _feed_seconds(rt, 0, 100, _bull_pullback_reaccel)
    rt.on_prevailing_regime(direction=1, start_ns=100 * NS, start_price=_bull_pullback_reaccel(100))
    _feed_seconds(rt, 100, 346, _bull_pullback_reaccel)
    ev = _feed_seconds(rt, 346, 401, _bull_pullback_reaccel)
    assert len(ev) == 1
    c = ev[0]
    assert c.candidate_ts >= c.triggering_completed_5s_ts >= c.arm_ts
    assert c.arm_ts >= c.pullback_start_ts


@pytest.mark.parametrize("direction", [1, -1])
def test_H_long_short_symmetry(direction):
    rt = _runtime()
    base = 20000.0

    def price(t):
        # normalized: prevailing move, peak, adverse pullback (>=1 ATR), re-accel
        if t <= 300:
            return base + direction * 0.5 * t
        if t <= 345:
            return base + direction * (150.0 - 2.0 * (t - 300))
        if t <= 400:
            return base + direction * (60.0 + 1.4 * (t - 345))
        return base + direction * 137.0

    _feed_seconds(rt, 0, 100, price)
    rt.on_prevailing_regime(direction=direction, start_ns=100 * NS, start_price=price(100))
    _feed_seconds(rt, 100, 346, price)
    ev = _feed_seconds(rt, 346, 401, price)
    assert len(ev) == 1
    assert ev[0].prevailing_direction == direction
    assert ev[0].frozen_atr_arm == pytest.approx(ATR)


# --------------------------------------------------------------------------- #
# 16. legacy isolation -- the collector wiring
# --------------------------------------------------------------------------- #
def test_collector_wiring_episode_vs_legacy():
    import inspect
    from research_workflow.generic_collector import FlipPredictionCollector

    src = inspect.getsource(FlipPredictionCollector)
    # episode dispatch present
    assert "resolve_population_runtime(" in src
    assert "self._population_runtime.on_completed_1s(" in src
    assert "self._population_runtime.on_prevailing_regime(" in src
    # checkpoint grid loop is guarded off for episode mode
    assert 'while self.regime_start_ns > 0 and not getattr(self, "_episode_mode", False):' in src


def test_non_episode_compiled_studies_resolve_checkpoint_grid_runtime():
    import glob
    for cs_path in glob.glob(str(REPO / "studies" / "*" / "compiled_study.json")):
        data = json.loads(Path(cs_path).read_text())
        pc = (data.get("contracts") or {}).get("population_contract") or {}
        if pc.get("episode_lifecycle"):
            continue
        rt = resolve_population_runtime(pc or {"population_type": "regime_state"})
        assert isinstance(rt, CheckpointGridRuntime), Path(cs_path).parent.name

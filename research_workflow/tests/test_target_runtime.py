from research_workflow.target_runtime import (CENSORED, NEGATIVE, POSITIVE, TargetRuntimeError,
    resolve_target_runtime, validate_target_parity)
import pytest
from types import SimpleNamespace

def c(direction=1): return {"observation_ts":0,"horizon_end_ts":10,"entry_price":100.,"atr":2.,"direction":direction,"favorable_atr":1.,"adverse_atr":1.}
@pytest.mark.parametrize("direction,event,disposition", [(1,{"ts":2,"high":103,"low":100},POSITIVE),(1,{"ts":2,"high":100,"low":97},NEGATIVE),(-1,{"ts":2,"high":100,"low":97},POSITIVE),(-1,{"ts":2,"high":103,"low":100},NEGATIVE)])
def test_ordered_barrier_ordering(direction,event,disposition):
    assert resolve_target_runtime({"primitive":"ordered_barrier"}).terminal(c(direction),[event]).disposition == disposition
def test_ordered_barrier_timeout_gap_ambiguous_and_exact_boundary():
    rt=resolve_target_runtime({"primitive":"ordered_barrier"})
    assert rt.terminal(c(),[]).disposition == NEGATIVE
    assert rt.terminal(c(),[{"ts":2,"gap":True}]).disposition == CENSORED
    assert rt.terminal(c(),[{"ts":2,"high":103,"low":97}]).censor_reason == "AMBIGUOUS_SAME_BAR_TOUCH"
    assert rt.terminal(c(),[{"ts":10,"high":103,"low":100}]).disposition == POSITIVE
def test_unknown_target_fails_closed_and_parity_detects_wrong_label():
    with pytest.raises(TargetRuntimeError): resolve_target_runtime({"primitive":"nope"})
    report=validate_target_parity({"primitive":"ordered_barrier"}, [{"candidate":c(),"events":[{"ts":2,"high":103,"low":100}],"actual":{"disposition":NEGATIVE,"label":0}}])
    assert report["passed"] is False and report["disposition_mismatches"] == report["binary_label_mismatches"] == 1

def test_collector_path_ordered_contract_cannot_execute_flip_labels():
    from research_workflow.generic_collector import FlipPredictionCollector
    obj = FlipPredictionCollector.__new__(FlipPredictionCollector)
    obj.cfg = SimpleNamespace(horizon_seconds=10, session="ALL", session_end_censoring=False,
                              target_contract={"primitive":"ordered_barrier", "required_forward_outcomes": []})
    obj._benchmark_mode = ""; obj._target_primitive = "ordered_barrier"
    obj._target_runtime = resolve_target_runtime({"primitive":"ordered_barrier"})
    obj._ordered_barrier = {"favorable_atr":1., "adverse_atr":1.}; obj.regime_frozen_atr=1.
    obj._ordered_barrier_entry_reference = "next_bar_open"; obj._ordered_barrier_max_gap_seconds = None
    obj.active_regime_dir=1; obj.pending_candidates=[]; obj.observations_log=[]; obj._next_pending_horizon_ns=None
    # The population candidate record carries NO entry_price -- only candidate-time ATR.
    obj._track_pending({"observation_ts":0,"regime_start_ns":0,"regime_direction":1,"checkpoint_index":0,"target_frozen_atr":2.}, 0)
    # First 1s bar strictly after T: its OPEN is the execution reference.
    obj._resolve_ordered_barriers({"ts":1_000_000_000,"open":100.,"high":103.,"low":100.,"gap":False}, now_ts=1_000_000_000)
    assert obj.observations_log[0]["disposition"] == "LABELED_POSITIVE"
    parity = validate_target_parity({"primitive":"ordered_barrier"}, [{"candidate": c(), "events":[{"ts":2,"high":103,"low":100}], "actual":{"disposition":"POSITIVE","label":1}}])
    assert parity["passed"] is True

def test_ordered_pending_candidate_survives_regime_flip_then_resolves_ohlc():
    from research_workflow.generic_collector import FlipPredictionCollector
    obj = FlipPredictionCollector.__new__(FlipPredictionCollector)
    obj.cfg = SimpleNamespace(horizon_seconds=10, session="ALL", session_end_censoring=False, target_contract={})
    obj._benchmark_mode=""; obj._target_primitive="ordered_barrier"; obj._target_runtime=resolve_target_runtime({"primitive":"ordered_barrier"})
    obj._ordered_barrier={"favorable_atr":1.,"adverse_atr":1.}; obj.regime_frozen_atr=1.; obj.active_regime_dir=1; obj.is_both_directions=False; obj.target_dir=-1
    obj._ordered_barrier_entry_reference = "next_bar_open"; obj._ordered_barrier_max_gap_seconds = None
    obj.pending_candidates=[]; obj.observations_log=[]; obj._next_pending_horizon_ns=None
    obj.regime_start_ns=0; obj.regime_start_close=0.; obj.highest_high_since_flip=0.; obj.lowest_low_since_flip=0.; obj.mfe_progress_previous_extreme=0.; obj.mfe_progress_last_extreme_ts=None; obj.mfe_progress_count=0; obj.next_checkpoint_index=0
    obj._track_pending({"observation_ts":0,"regime_start_ns":0,"regime_direction":1,"checkpoint_index":0,"target_frozen_atr":2.},0)
    obj._on_regime_flip(-1, 1_000_000_000, 100.,100.,2.)
    assert len(obj.pending_candidates) == 1
    obj._resolve_ordered_barriers({"ts":2_000_000_000,"open":100.,"high":103.,"low":100.,"gap":False},now_ts=2_000_000_000)
    assert obj.observations_log[0]["disposition"] == "LABELED_POSITIVE"

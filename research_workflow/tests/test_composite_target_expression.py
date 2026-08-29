"""Composite target execution: the FULL Boolean expression is conjoined/disjoined.

Regression coverage for the framework defect where a target contract with
``condition_logic: "AND"`` over a ``flip`` condition and an ``ordered_barrier`` condition
compiled to ``primitive: "ordered_barrier"`` and the collector emitted ONLY the
ordered-barrier race -- the ``flip`` child was silently dropped, and the replay oracle
shared the omission so parity falsely passed.

Composition semantics (researcher-authorized 2026-08-28): MONOTONE ``worst_status``, NO
Boolean short-circuit.  A composite is RESOLVED only when every child is resolved; any
CENSORED / AMBIGUOUS / unresolved child -> composite CENSORED.
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from research_workflow.target_expression import (
    And,
    Or,
    PrimitiveTarget,
    TargetExpressionError,
    TargetResult,
    compile_target_expression,
)
from research_workflow.target_runtime import (
    NS,
    CompositeTargetRuntime,
    TargetRuntimeError,
    resolve_target_runtime,
    validate_target_parity,
)
from research_workflow.target_replay_oracle import replay_expression

HORIZON = 60
T0 = int(pd.Timestamp("2023-03-03 10:00:00", tz="America/Chicago").tz_convert("UTC").value)

POS = ("POSITIVE", 1)
NEG = ("NEGATIVE", 0)


def _contract(logic="AND", flip_horizon=HORIZON, favorable=0.25, adverse=0.25,
              barrier_horizon=HORIZON, session_end_censoring=True, max_gap=1):
    return {
        "primitive": "composite",
        "direction": "opposite",
        "horizon_seconds": max(flip_horizon, barrier_horizon),
        "condition_logic": logic,
        "conditions": [
            {"id": "flip_c", "kind": "flip", "event": "opposite_regime_flip",
             "direction": "opposite", "horizon_seconds": flip_horizon},
            {"id": "barrier_c", "kind": "ordered_barrier",
             "forward_outcome_id": "fo", "barrier_id": "b"},
        ],
        "required_forward_outcomes": [{
            "id": "fo", "entry_reference": "next_bar_open",
            "horizon_seconds": barrier_horizon, "session_end_censoring": session_end_censoring,
            "max_gap_seconds": max_gap,
            "ordered_barriers": [{"id": "b", "favorable_atr": favorable,
                                  "adverse_atr": adverse, "horizon_seconds": barrier_horizon}],
        }],
    }


# =====================================================================================
# 1. Expression compilation + truth table (pure, no runtime)
# =====================================================================================
def _R(disp_label, ts=None, cr=None):
    d, l = disp_label
    return TargetResult(d, l, ts, cr)


@pytest.mark.parametrize("logic,a,b,expect", [
    # AND
    ("AND", POS, POS, POS),
    ("AND", NEG, POS, NEG),
    ("AND", POS, NEG, NEG),
    ("AND", NEG, NEG, NEG),
    # OR
    ("OR", POS, POS, POS),
    ("OR", NEG, POS, POS),
    ("OR", POS, NEG, POS),
    ("OR", NEG, NEG, NEG),
])
def test_boolean_truth_table_when_every_child_resolved(logic, a, b, expect):
    expr = compile_target_expression(_contract(logic=logic))
    got = expr.evaluate({"flip_c": _R(a, 5), "barrier_c": _R(b, 7)})
    assert (got.disposition, got.label) == expect


@pytest.mark.parametrize("logic", ["AND", "OR"])
@pytest.mark.parametrize("other", [POS, NEG])
@pytest.mark.parametrize("censor", ["SESSION_END", "GAP", "AMBIGUOUS_SAME_BAR_TOUCH", "DATA_END"])
def test_any_censored_or_ambiguous_child_censors_the_composite_no_short_circuit(logic, other, censor):
    """The authorized rule: NEVER AND(False, censored) -> NEGATIVE, NEVER
    OR(True, censored) -> POSITIVE.  A censored required child always wins."""
    expr = compile_target_expression(_contract(logic=logic))
    got = expr.evaluate({"flip_c": _R(other, 5), "barrier_c": _R(("CENSORED", None), 7, censor)})
    assert got.disposition == "CENSORED"
    assert got.label is None
    assert got.censor_reason == censor


def test_worst_censor_reason_wins_when_multiple_children_censored():
    expr = compile_target_expression(_contract(logic="AND"))
    got = expr.evaluate({
        "flip_c": _R(("CENSORED", None), 5, "SESSION_END"),
        "barrier_c": _R(("CENSORED", None), 7, "AMBIGUOUS_SAME_BAR_TOUCH"),
    })
    assert got.disposition == "CENSORED"
    assert got.censor_reason == "AMBIGUOUS_SAME_BAR_TOUCH"  # strictly more severe


def test_pending_child_keeps_composite_pending_before_final():
    expr = compile_target_expression(_contract())
    got = expr.evaluate({"flip_c": _R(POS, 5), "barrier_c": TargetResult("PENDING", None)})
    assert got.disposition == "PENDING"


def test_unknown_condition_logic_fails_closed():
    bad = _contract(logic="XOR")
    with pytest.raises(TargetExpressionError, match="UNKNOWN_CONDITION_LOGIC"):
        compile_target_expression(bad)


def test_excursion_leaf_is_represented_but_not_runtime_executable():
    contract = {
        "primitive": "composite", "condition_logic": "AND",
        "conditions": [
            {"id": "f", "kind": "flip", "horizon_seconds": 300, "direction": "opposite"},
            {"id": "e", "kind": "excursion", "metric": "mfe_atr", "comparator": ">=",
             "threshold": 1.0, "forward_outcome_id": "fo"},
        ],
        "horizon_seconds": 300,
        "required_forward_outcomes": [{"id": "fo", "horizon_seconds": 300}],
    }
    expr = compile_target_expression(contract)          # compiles fine (provenance)
    assert {leaf.primitive for leaf in expr.leaves()} == {"flip_within_horizon", "excursion"}
    with pytest.raises(TargetRuntimeError, match="UNSUPPORTED_COMPOSITE_CONDITION"):
        resolve_target_runtime(contract)               # runtime fails closed


# =====================================================================================
# 2. CompositeTargetRuntime end-to-end (runtime owns child pendings + composition)
# =====================================================================================
def _runtime(contract):
    return resolve_target_runtime(contract)


def _open(rt, *, T=T0, direction=1, atr=10.0, session_close=None):
    return rt.open_pending({
        "observation_ts": T, "regime_start_ns": T - 300 * NS, "regime_direction": direction,
        "checkpoint_index": 3, "atr": atr, "session_close_ts": session_close,
    })


def _feed_bars(rt, pending, bars):
    for ts, o, h, l in bars:
        rt.ingest_bar(pending, {"ts": ts, "open": o, "high": h, "low": l, "gap": False})


def test_runtime_AND_true_true_positive():
    rt = _runtime(_contract())
    p = _open(rt)
    # ordered-barrier SUCCESS: entry 20000, +0.25*10 = 20002.5 hit on bar 2.
    _feed_bars(rt, p, [(T0 + 1 * NS, 20000.0, 20001.0, 19999.0),
                       (T0 + 2 * NS, 20001.0, 20003.0, 20000.5)])
    # opposing flip (direction -1) within 60s.
    rt.ingest_flip(p, {"ts": T0 + 3 * NS, "direction": -1})
    res = rt.terminal(p, final=True, now_ts=T0 + 70 * NS)
    assert (res.disposition, res.label) == ("POSITIVE", 1)


def test_runtime_AND_barrier_true_but_no_flip_is_negative():
    rt = _runtime(_contract())
    p = _open(rt)
    _feed_bars(rt, p, [(T0 + 1 * NS, 20000.0, 20001.0, 19999.0),
                       (T0 + 2 * NS, 20001.0, 20003.0, 20000.5)])   # barrier SUCCESS
    # no flip fed at all -> flip child times out NEGATIVE at horizon.
    res = rt.terminal(p, final=True, now_ts=T0 + 70 * NS)
    assert (res.disposition, res.label) == ("NEGATIVE", 0)


def test_runtime_AND_flip_true_but_barrier_adverse_is_negative():
    rt = _runtime(_contract())
    p = _open(rt)
    _feed_bars(rt, p, [(T0 + 1 * NS, 20000.0, 20001.0, 19999.0),
                       (T0 + 2 * NS, 20000.0, 20000.4, 19997.4)])   # adverse -0.25*10 hit
    rt.ingest_flip(p, {"ts": T0 + 3 * NS, "direction": -1})
    res = rt.terminal(p, final=True, now_ts=T0 + 70 * NS)
    assert (res.disposition, res.label) == ("NEGATIVE", 0)


def test_runtime_OR_flip_only_is_positive():
    rt = _runtime(_contract(logic="OR"))
    p = _open(rt)
    _feed_bars(rt, p, [(T0 + s * NS, 20000.0, 20000.4, 19999.6) for s in range(1, HORIZON + 2)])
    rt.ingest_flip(p, {"ts": T0 + 3 * NS, "direction": -1})
    res = rt.terminal(p, final=True, now_ts=T0 + 70 * NS)
    assert (res.disposition, res.label) == ("POSITIVE", 1)   # OR: barrier NEG, flip POS


def test_runtime_AND_barrier_ambiguous_censors_even_with_flip_true():
    rt = _runtime(_contract())
    p = _open(rt)
    # same-bar touch of BOTH barriers -> AMBIGUOUS -> child CENSORED.
    _feed_bars(rt, p, [(T0 + 1 * NS, 20000.0, 20003.0, 19997.0)])
    rt.ingest_flip(p, {"ts": T0 + 3 * NS, "direction": -1})
    res = rt.terminal(p, final=True, now_ts=T0 + 70 * NS)
    assert res.disposition == "CENSORED"
    assert res.censor_reason == "AMBIGUOUS_SAME_BAR_TOUCH"


@pytest.mark.parametrize("gap_kind", ["explicit_flag", "implicit_delta"])
def test_runtime_and_oracle_agree_on_GAP_reason_when_tape_breaks_before_flip_horizon(gap_kind):
    """Regression: a tape gap that truncates the barrier tape before the 60s flip
    horizon must read as GAP on BOTH the runtime and the independent oracle -- not
    GAP on one and DATA_END on the other."""
    contract = _contract(logic="AND", max_gap=1)
    rt = _runtime(contract)
    p = _open(rt)
    bars = [(T0 + 1 * NS, 20000.0, 20000.4, 19999.6)]        # entry
    # 25s gap: bar at T0+26s.  For explicit_flag the collector would set gap=True;
    # for implicit_delta only the wall-clock delta exceeds max_gap.
    gap_bar = {"ts": T0 + 26 * NS, "open": 20000.0, "high": 20000.4, "low": 19999.6,
               "gap": gap_kind == "explicit_flag"}
    rt.ingest_bar(p, {"ts": bars[0][0], "open": bars[0][1], "high": bars[0][2], "low": bars[0][3], "gap": False})
    rt.ingest_bar(p, gap_bar)
    res = rt.terminal(p, final=True, now_ts=T0 + 26 * NS)
    row = rt.parity_row(p, {"disposition": res.disposition, "label": res.label,
                            "censor_reason": res.censor_reason})
    oracle = replay_expression(contract, row["candidate"], row["events"], row["flip_events"])
    assert res.disposition == "CENSORED" and res.censor_reason == "GAP"
    assert oracle["disposition"] == "CENSORED" and oracle["censor_reason"] == "GAP"


def test_runtime_AND_flip_child_session_censor_wins_over_resolved_barrier():
    from research_workflow.generic_collector import session_close_ns

    close = session_close_ns(T0, "RTH")
    T = close - 30 * NS   # 60s flip horizon reaches 30s past the RTH close
    rt = _runtime(_contract())
    p = _open(rt, T=T, session_close=close)
    _feed_bars(rt, p, [(T + 1 * NS, 20000.0, 20003.0, 19999.0)])   # barrier SUCCESS
    rt.ingest_flip(p, {"ts": T + 3 * NS, "direction": -1})
    res = rt.terminal(p, final=True, now_ts=T + 70 * NS)
    assert res.disposition == "CENSORED"
    assert res.censor_reason == "SESSION_END"


# =====================================================================================
# 3. Independent replay oracle agrees with the runtime AND catches an injected error
# =====================================================================================
def _row_from_runtime(contract, *, direction=1, flips=(), bars):
    rt = _runtime(contract)
    p = _open(rt, direction=direction)
    tape = []
    for ts, o, h, l in bars:
        ev = {"ts": ts, "open": o, "high": h, "low": l, "gap": False}
        rt.ingest_bar(p, ev)
        tape.append(ev)
    for fts, fdir in flips:
        rt.ingest_flip(p, {"ts": fts, "direction": fdir})
    res = rt.terminal(p, final=True, now_ts=bars[-1][0])
    return res, tape, [{"ts": fts, "direction": fdir} for fts, fdir in flips]


@pytest.mark.parametrize("logic", ["AND", "OR"])
@pytest.mark.parametrize("scenario", ["both_true", "barrier_only", "flip_only", "neither", "barrier_ambiguous"])
def test_runtime_matches_independent_replay_oracle(logic, scenario):
    contract = _contract(logic=logic)
    if scenario == "both_true":
        bars = [(T0 + 1 * NS, 20000.0, 20001.0, 19999.0), (T0 + 2 * NS, 20001.0, 20003.0, 20000.5)]
        flips = [(T0 + 3 * NS, -1)]
    elif scenario == "barrier_only":
        bars = [(T0 + 1 * NS, 20000.0, 20001.0, 19999.0), (T0 + 2 * NS, 20001.0, 20003.0, 20000.5)]
        bars += [(T0 + s * NS, 20001.0, 20001.4, 20000.6) for s in range(3, HORIZON + 2)]
        flips = []
    elif scenario == "flip_only":
        bars = [(T0 + s * NS, 20000.0, 20000.4, 19999.6) for s in range(1, HORIZON + 2)]
        flips = [(T0 + 3 * NS, -1)]
    elif scenario == "neither":
        bars = [(T0 + s * NS, 20000.0, 20000.4, 19999.6) for s in range(1, HORIZON + 2)]
        flips = []
    else:  # barrier_ambiguous
        bars = [(T0 + 1 * NS, 20000.0, 20003.0, 19997.0)]
        bars += [(T0 + s * NS, 20000.0, 20000.4, 19999.6) for s in range(2, HORIZON + 2)]
        flips = [(T0 + 3 * NS, -1)]

    res, tape, flip_events = _row_from_runtime(contract, bars=bars, flips=flips)
    candidate = {"observation_ts": T0, "session_close_ts": None, "atr": 10.0,
                 "direction": 1, "regime_direction": 1}
    report = validate_target_parity(contract, [{
        "candidate": candidate, "events": tape, "flip_events": flip_events,
        "actual": {"disposition": res.disposition, "label": res.label,
                   "censor_reason": res.censor_reason},
    }])
    assert report["passed"], report["examples"]
    assert report["rows_compared"] == 1


def test_parity_oracle_detects_an_intentional_composition_error():
    """A runtime that dropped the flip child (the ORIGINAL defect) would label this
    row POSITIVE off the barrier alone; the oracle -- which conjoins both -- says
    NEGATIVE, so parity fails."""
    contract = _contract(logic="AND")
    # barrier SUCCESS, NO flip -> true composite = NEGATIVE.
    bars = [(T0 + 1 * NS, 20000.0, 20001.0, 19999.0), (T0 + 2 * NS, 20001.0, 20003.0, 20000.5)]
    bars += [(T0 + s * NS, 20001.0, 20001.4, 20000.6) for s in range(3, HORIZON + 2)]
    tape = [{"ts": ts, "open": o, "high": h, "low": l, "gap": False} for ts, o, h, l in bars]
    candidate = {"observation_ts": T0, "session_close_ts": None, "atr": 10.0,
                 "direction": 1, "regime_direction": 1}
    report = validate_target_parity(contract, [{
        "candidate": candidate, "events": tape, "flip_events": [],
        "actual": {"disposition": "LABELED_POSITIVE", "label": 1, "censor_reason": None},
    }])
    assert report["passed"] is False
    assert report["binary_label_mismatches"] == 1


def test_oracle_composition_is_independent_of_target_expression_module():
    """The oracle re-parses conditions/condition_logic itself and re-implements the
    monotone rule -- a mistake in one side is caught by the other."""
    import research_workflow.target_replay_oracle as oracle
    import inspect

    src = inspect.getsource(oracle)
    # It never imports the runtime's expression compiler / composer.
    assert "from research_workflow.target_expression import" not in src
    assert "import research_workflow.target_expression" not in src
    # It carries its own composition + its own censor-severity table.
    assert "_compose_monotone" in src
    assert "_ORACLE_CENSOR_SEVERITY" in src


# =====================================================================================
# 4. Preflight expression binding detects a runtime that would drop one child
# =====================================================================================
def test_expression_binding_detects_drifted_target_expression(tmp_path):
    from research_workflow.runtime_bindings import verify_runtime_contract

    contract = _contract(logic="AND")
    from research.engines.target_engine import compile_target_contract
    from research.schemas.study_spec import StudySpec

    base = dict(study={"id": "x", "type": "flip_prediction", "description": "d"},
                instrument={"symbol": "NQ"}, population={"prevailing_regime": "bearish"})
    target = {
        "type": "composite", "direction": "opposite", "condition_logic": "AND",
        "conditions": [
            {"id": "flip_c", "kind": "flip", "direction": "opposite", "horizon_seconds": 60},
            {"id": "barrier_c", "kind": "ordered_barrier", "forward_outcome_id": "fo", "barrier_id": "b"},
        ],
        "required_forward_outcomes": [{
            "id": "fo", "entry_reference": "next_bar_open", "horizon_seconds": 60,
            "max_gap_seconds": 1, "atr_source": "x", "atr_frozen_at": "decision_ts",
            "ordered_barriers": [{"id": "b", "favorable_atr": 0.25, "adverse_atr": 0.25, "horizon_seconds": 60}],
        }],
    }
    spec = StudySpec.model_validate(dict(base, target=target))
    tc = compile_target_contract(spec.target)
    # Drift: drop the flip child from the embedded expression only.
    tc["target_expression"]["children"] = [
        c for c in tc["target_expression"]["children"] if c["condition_id"] != "flip_c"
    ]
    import json
    (tmp_path / "compiled_study.json").write_text(json.dumps({
        "spec": {"execution": {"strategy_class": "research_workflow.generic_collector.GenericStudyCollector"}},
        "contracts": {"target_contract": tc},
    }))
    verdict = verify_runtime_contract(tmp_path)
    assert verdict["passed"] is False
    assert any("EXPRESSION_DRIFT" in m["reason"] for m in verdict["missing"])


# =====================================================================================
# 5. Collector composite dispatch (checkpoint-grid population)
# =====================================================================================
def _collector(contract, *, direction=1, session="RTH", session_end_censoring=True):
    from research_workflow.generic_collector import FlipPredictionCollector

    obj = FlipPredictionCollector.__new__(FlipPredictionCollector)
    obj.cfg = SimpleNamespace(
        horizon_seconds=contract["horizon_seconds"], session=session,
        session_end_censoring=session_end_censoring, target_contract=contract,
    )
    obj._benchmark_mode = ""
    obj._target_runtime = resolve_target_runtime(contract)
    obj._target_primitive = "composite"
    obj._composite_target = True
    obj._composite_parity_rows = []
    obj._composite_gap_seconds = 1
    obj.active_regime_dir = direction
    obj.is_both_directions = False
    obj.target_dir = -direction
    obj.pending_candidates = []
    obj.observations_log = []
    obj._next_pending_horizon_ns = None
    obj.last_ts_seen = None
    return obj


def _checkpoint_cand(T, atr=10.0, direction=1):
    return {"observation_ts": T, "regime_start_ns": T - 300 * NS, "regime_direction": direction,
            "checkpoint_index": 3, "atr": atr, "target_frozen_atr": atr}


def _drive(obj, T, bars, flips=()):
    obj._track_pending(_checkpoint_cand(T, direction=obj.active_regime_dir), T)
    flips = sorted(flips)
    fi = 0
    for ts, o, h, l in bars:
        while fi < len(flips) and flips[fi][0] <= ts:
            for cand in obj.pending_candidates:
                obj._target_runtime.ingest_flip(cand, {"ts": flips[fi][0], "direction": flips[fi][1]})
            fi += 1
        obj._resolve_composite({"ts": ts, "open": o, "high": h, "low": l, "gap": False}, now_ts=ts)
        obj.last_ts_seen = ts
    obj._resolve_composite(None, now_ts=bars[-1][0], final=True)
    return obj.observations_log[-1] if obj.observations_log else None


def test_collector_composite_AND_positive_needs_both_children():
    obj = _collector(_contract(logic="AND"))
    obs = _drive(obj, T0, [
        (T0 + 1 * NS, 20000.0, 20001.0, 19999.0),
        (T0 + 2 * NS, 20001.0, 20003.0, 20000.5),        # barrier SUCCESS
    ] + [(T0 + s * NS, 20001.0, 20001.4, 20000.6) for s in range(3, HORIZON + 3)],
        flips=[(T0 + 4 * NS, -1)])                        # opposing flip within 60s
    assert obs["disposition"] == "LABELED_POSITIVE"
    assert obs["target_flip_within_horizon"] == 1
    # the collector's own accumulated independent-replay parity must be clean
    parity = obj.get_composite_target_parity()
    assert parity["passed"], parity["examples"]
    assert parity["rows_compared"] == 1


def test_collector_composite_AND_barrier_success_no_flip_is_negative():
    obj = _collector(_contract(logic="AND"))
    obs = _drive(obj, T0, [
        (T0 + 1 * NS, 20000.0, 20001.0, 19999.0),
        (T0 + 2 * NS, 20001.0, 20003.0, 20000.5),
    ] + [(T0 + s * NS, 20001.0, 20001.4, 20000.6) for s in range(3, HORIZON + 3)])
    assert obs["disposition"] == "LABELED_NEGATIVE"
    assert obs["target_flip_within_horizon"] == 0


def test_collector_composite_AND_ambiguous_barrier_censors_row():
    obj = _collector(_contract(logic="AND"))
    obs = _drive(obj, T0, [
        (T0 + 1 * NS, 20000.0, 20003.0, 19997.0),        # both barriers, same bar
    ] + [(T0 + s * NS, 20000.0, 20000.4, 19999.6) for s in range(2, HORIZON + 3)],
        flips=[(T0 + 4 * NS, -1)])
    assert obs["disposition"] == "CENSORED"
    assert obs["censor_reason"] == "AMBIGUOUS_SAME_BAR_TOUCH"
    assert obs["target_flip_within_horizon"] is None


def test_collector_composite_run_end_before_barrier_entry_is_data_end_censored():
    obj = _collector(_contract(logic="AND"))
    obj._track_pending(_checkpoint_cand(T0), T0)
    # no bar strictly after T before the run ends
    obj._resolve_composite(None, now_ts=T0, final=True)
    obs = obj.observations_log[-1]
    assert obs["disposition"] == "CENSORED"
    assert obs["censor_reason"] == "DATA_END"

"""Host unit tests with synthetic primitives only: the multiplexer's watermark and bucket
aggregation, the label kernel against the independent oracle on random tapes, the trigger
engine's edge semantics, and the host boundary lint."""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from research_workflow.host.interfaces import NS, BarView, EpochView
from research_workflow.host.mux import BucketAggregator, CausalOrderViolation, StreamMux
from research_workflow.host.outcomes import LabelOutcomeContract, LabelOutcomeKernel
from research_workflow.host.predicate_eval import compile_predicate
from research_workflow.host.triggers import TriggerEngine
from research_workflow.grammar.predicates import parse_predicate

ROOT = Path(__file__).resolve().parents[2]


def _streams():
    return [{"key": "a_1s", "instrument": "A", "timeframe": "1s", "duration_ns": NS, "role": "execution", "source": "external"},
            {"key": "a_5s", "instrument": "A", "timeframe": "5s", "duration_ns": 5 * NS, "role": "execution", "source": "derived", "derived_from": "a_1s", "aggregation": "complete_bucket"},
            {"key": "b_1m", "instrument": "B", "timeframe": "1m", "duration_ns": 60 * NS, "role": "context", "source": "external"}]


def test_bucket_aggregator_publishes_complete_buckets_only():
    agg = BucketAggregator("a_5s", 5 * NS, NS)
    out = []
    for s in [0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14]:   # second 7 missing -> bucket [5,10) incomplete
        out += agg.on_source_bar(BarView("a_1s", s * NS, (s + 1) * NS, 1, 2, 0, 1, 1))
    assert [b.ts_init // NS for b in out] == [5, 15]
    assert agg.incomplete_close_ts == [10 * NS]


def test_mux_context_stream_visible_strictly_before_epoch():
    delivered = []
    mux = StreamMux(_streams(), delivered.append)
    mux.ingest(BarView("b_1m", 0, 60 * NS, 1, 1, 1, 1, 1))           # context bar closing at T=60
    mux.ingest(BarView("a_1s", 59 * NS, 60 * NS, 1, 1, 1, 1, 1))     # execution bar at T=60: context must NOT be visible
    assert [b.stream for b in delivered] == ["a_1s"]
    mux.assert_epoch_visibility(60 * NS, ["a_1s", "a_5s"])
    mux.ingest(BarView("a_1s", 60 * NS, 61 * NS, 1, 1, 1, 1, 1))     # first execution bar strictly later releases it
    assert [b.stream for b in delivered] == ["a_1s", "b_1m", "a_1s"]
    with pytest.raises(CausalOrderViolation):
        mux.ingest(BarView("a_1s", 60 * NS, 61 * NS, 1, 1, 1, 1, 1))


def test_mux_derived_bucket_delivered_before_source_bar():
    delivered = []
    mux = StreamMux(_streams(), delivered.append)
    for s in range(0, 5):
        mux.ingest(BarView("a_1s", s * NS, (s + 1) * NS, 1, 2, 0, 1, 1))
    assert delivered[-2].stream == "a_5s" and delivered[-1].stream == "a_1s" and delivered[-2].ts_init == delivered[-1].ts_init == 5 * NS


class _Sessions:
    def __init__(self, close=None):
        self.close = close

    def in_session(self, ts):
        return True

    def session_close(self, ts):
        return self.close


def _random_tape(rng, n, start=1000 * NS, sparse=0.15, base=100.0):
    bars, price, ts = [], base, start
    for _ in range(n):
        ts += NS
        if rng.random() < sparse:
            continue
        o = price
        hi = o + rng.random() * 1.5
        lo = o - rng.random() * 1.5
        c = lo + rng.random() * (hi - lo)
        bars.append({"ts": ts, "open": o, "high": hi, "low": lo, "close": c, "gap": False})
        price = c
    return bars


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_barrier_kernel_agrees_with_independent_oracle(seed):
    from research_workflow.target_replay_oracle import replay
    rng = random.Random(seed)
    tape = _random_tape(rng, 900)
    contract = LabelOutcomeContract.from_plan({"contract": "label", "kernel": "barrier", "direction": "d", "atr": "a", "entry_reference": "next_bar_open",
                                               "session_end_censoring": True, "max_gap_ns": 4 * NS, "same_bar_rule": "ambiguous_censor",
                                               "arms": [{"id": "x", "favorable_atr": 1.0, "adverse_atr": 0.75, "horizon_ns": 120 * NS, "expiry": "censor", "prefix": "x"},
                                                        {"id": "y", "favorable_atr": 0.5, "adverse_atr": 1.5, "horizon_ns": 90 * NS, "expiry": "negative", "prefix": "y"}], "primary_arm": "x"})
    close = tape[-1]["ts"] - 60 * NS
    kernel = LabelOutcomeKernel(contract, _Sessions(close))
    cands = []
    for i, b in enumerate(tape[:-200]):
        if i % 7 == 0:
            d = 1 if rng.random() < 0.5 else -1
            atr = 1.0 + rng.random()
            kernel.open({"observation_ts": b["ts"], "regime_start_ns": 0, "checkpoint_index": i}, b["ts"], d, atr)
            cands.append((b["ts"], d, atr))
        kernel.on_bar(BarView("s", b["ts"] - NS, b["ts"], b["open"], b["high"], b["low"], b["close"], 1.0))
    for b in tape[-200:]:
        kernel.on_bar(BarView("s", b["ts"] - NS, b["ts"], b["open"], b["high"], b["low"], b["close"], 1.0))
    kernel.finalize(tape[-1]["ts"])
    rows = {r["observation_ts"]: r for r in kernel.drain_rows()}
    assert len(rows) == len(cands)
    for T, d, atr in cands:
        r = rows[T]
        for arm, fav, adv, hz, pol in (("x", 1.0, 0.75, 120, "censor"), ("y", 0.5, 1.5, 90, "negative")):
            c = {"primitive": "ordered_barrier", "required_forward_outcomes": [{"id": "fo", "entry_reference": "next_bar_open", "session_end_censoring": True, "max_gap_seconds": 4,
                                                                             "ordered_barriers": [{"id": "b", "favorable_atr": fav, "adverse_atr": adv, "horizon_seconds": hz, "horizon_expiry_policy": pol}]}]}
            o = replay(c, {"observation_ts": T, "atr": atr, "direction": d, "session_close_ts": close}, [e for e in tape if T < e["ts"] <= T + 200 * NS])
            got = (r[f"{arm}_disposition"], r[f"{arm}_censor_reason"])
            assert got == (o["disposition"], o["censor_reason"]), (T, arm, got, o)


def test_trigger_engine_edge_events_are_consumed_once():
    class T:
        changed_seq = 0
        depth = 0.0
    t = T()
    spec = {"kind": "graph", "reset_when": {"ast": parse_predicate("t.changed")}, "states": {"WATCH": {"enter_when": {"ast": parse_predicate("t.depth >= 1")}, "expire_when": None, "from": ["OBSERVE"], "chain": False}},
            "entry": None, "precedence": ["WATCH"], "max_transitions_per_epoch": 1, "sub_epochs": "none"}
    eng = TriggerEngine(spec, {})
    ep = lambda T_: EpochView(T=T_, price=1.0, bar=None, trackers={"t": t})
    t.depth = 2.0
    out, _ = eng.evaluate(ep(1 * NS)); assert [x.kind for x in out] == ["enter"] and eng.state == "WATCH"
    t.changed_seq = 1
    out, _ = eng.evaluate(ep(2 * NS)); assert [x.kind for x in out] == ["expire"] and eng.state == "OBSERVE"   # reset consumes the epoch
    out, _ = eng.evaluate(ep(3 * NS)); assert [x.kind for x in out] == ["enter"]                              # the same edge is not fresh twice


def test_predicate_null_semantics():
    class T:
        v = None
    f = compile_predicate(parse_predicate("t.v >= 1"), epoch_fields={})
    g = compile_predicate(parse_predicate("t.v == null"), epoch_fields={})
    e = EpochView(T=0, price=0.0, bar=None, trackers={"t": T()})
    assert f(e) is False and g(e) is True


def test_host_boundary_lint_is_clear():
    from scripts.lint_host import HOST_DIR, lint_file
    findings = [f for p in sorted(HOST_DIR.glob("*.py")) for f in lint_file(p)]
    assert not findings, findings

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


def _cw(key, tf_s, src, *, role="execution", empty="none", visibility=None):
    s = {"key": key, "instrument": "A", "timeframe": f"{tf_s}s", "duration_ns": tf_s * NS, "role": role, "source": "derived",
         "derived_from": src, "aggregation": "closed_window", "empty_window": empty}
    if visibility:
        s["visibility"] = visibility
    return s


_A_1S = {"key": "a_1s", "instrument": "A", "timeframe": "1s", "duration_ns": NS, "role": "execution", "source": "external"}


def test_closed_window_publishes_the_bucket_complete_bucket_rejects():
    """Mirror of the complete-bucket test: the same tape with second 7 missing publishes [5,10)."""
    delivered = []
    mux = StreamMux([_A_1S, _cw("a_5s", 5, "a_1s")], delivered.append)
    for s in [0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14]:
        mux.ingest(BarView("a_1s", s * NS, (s + 1) * NS, 1, 2, 0, 1, 1))
    assert [b.ts_init // NS for b in delivered if b.stream == "a_5s"] == [5, 10, 15]
    assert [b.volume for b in delivered if b.stream == "a_5s"] == [5, 4, 5]


def test_empty_window_is_a_zero_volume_bar_inside_a_trading_day_and_nothing_across_a_closure():
    """D3a/D3b: trading days (0,30] and (60,120].  No bar before the first member; empty windows
    inside a day carry O=H=L=C = previous close and zero volume; the closure (30,60] emits nothing."""
    from research_workflow.sessions import CalendarSessionTable
    days = CalendarSessionTable([(0, 30 * NS), (60 * NS, 120 * NS)], name="TRADING_DAY")
    delivered = []
    mux = StreamMux([_A_1S, _cw("a_5s", 5, "a_1s", empty="zero_volume_in_trading_day")], delivered.append, trading_days=days)
    mux.ingest(BarView("a_1s", 2 * NS, 3 * NS, 10, 12, 9, 11, 3))
    mux.ingest(BarView("a_1s", 17 * NS, 18 * NS, 11, 13, 10, 12, 2))
    mux.ingest(BarView("a_1s", 70 * NS, 71 * NS, 12, 12, 12, 12, 1))
    five = [b for b in delivered if b.stream == "a_5s"]
    assert [b.ts_init // NS for b in five] == [5, 10, 15, 20, 25, 30, 65, 70]
    assert [b.volume for b in five] == [3, 0.0, 0.0, 2, 0.0, 0.0, 0.0, 0.0]
    assert all((b.open, b.high, b.low, b.close) == (11, 11, 11, 11) for b in five[1:3])
    assert all((b.open, b.high, b.low, b.close) == (12, 12, 12, 12) for b in five[4:])
    assert [b.ts_event // NS for b in five] == [0, 5, 10, 15, 20, 25, 60, 65]


def test_zero_volume_fill_without_a_calendar_is_refused_and_unknown_aggregation_raises():
    with pytest.raises(CausalOrderViolation, match="TRADING_DAY_CALENDAR_ABSENT"):
        StreamMux([_A_1S, _cw("a_5s", 5, "a_1s", empty="zero_volume_in_trading_day")], lambda b: None)
    StreamMux([_A_1S, _cw("a_5s", 5, "a_1s", empty="zero_volume_in_trading_day")], lambda b: None, require_calendar=False)
    with pytest.raises(CausalOrderViolation, match="EMPTY_WINDOW_RULE_UNDECLARED"):
        StreamMux([_A_1S, dict(_cw("a_5s", 5, "a_1s"), empty_window=None)], lambda b: None)
    with pytest.raises(CausalOrderViolation, match="UNKNOWN_AGGREGATION"):
        StreamMux([_A_1S, dict(_cw("a_5s", 5, "a_1s"), aggregation="bogus")], lambda b: None)


def test_window_whose_last_second_is_empty_is_visible_at_the_cadence_epoch_closing_it():
    """A 30s window from 1s with no bar in its last second closes at T=60.  The 1m cadence bar at T
    is applied after every 1s bar at T, so the window is published ahead of that epoch -- the set NT's
    timer would have closed at T -- not one epoch later."""
    streams = [_A_1S, _cw("a_30s", 30, "a_1s"),
               {"key": "a_1m", "instrument": "A", "timeframe": "1m", "duration_ns": 60 * NS, "role": "context",
                "source": "external", "visibility": "at_epoch"}]
    delivered, mux = [], None

    def deliver(bar):
        delivered.append(bar)
        if bar.stream == "a_1m":
            mux.assert_epoch_visibility(bar.ts_init)

    mux = StreamMux(streams, deliver)
    for s in range(30, 59):
        mux.ingest(BarView("a_1s", s * NS, (s + 1) * NS, 1, 1, 1, 1, 1))
    mux.ingest(BarView("a_1m", 0, 60 * NS, 1, 1, 1, 1, 29))
    mux.ingest(BarView("a_1s", 61 * NS, 62 * NS, 1, 1, 1, 1, 1))
    tail = [(b.stream, b.ts_init // NS) for b in delivered[-3:]]
    assert tail == [("a_30s", 60), ("a_1m", 60), ("a_1s", 62)]


def test_window_from_a_context_source_closes_when_any_later_bar_arrives():
    """3m from 1m with the last minute empty: nothing on the 1m stream closes it, the next 1s bar does."""
    streams = [_A_1S, {"key": "a_1m", "instrument": "A", "timeframe": "1m", "duration_ns": 60 * NS, "role": "context",
                       "source": "external"}, _cw("a_3m", 180, "a_1m")]
    delivered = []
    mux = StreamMux(streams, delivered.append)
    mux.ingest(BarView("a_1m", 0, 60 * NS, 1, 3, 1, 2, 1))
    mux.ingest(BarView("a_1m", 60 * NS, 120 * NS, 2, 4, 0, 3, 1))
    mux.ingest(BarView("a_1s", 185 * NS, 186 * NS, 1, 1, 1, 1, 1))
    assert [(b.stream, b.ts_init // NS) for b in delivered] == [("a_1m", 60), ("a_1m", 120), ("a_3m", 180), ("a_1s", 186)]
    three = delivered[2]
    assert (three.ts_event, three.open, three.high, three.low, three.close, three.volume) == (0, 1, 4, 0, 3, 2)


def test_four_hour_bar_from_one_minute_is_stamped_open_and_close():
    delivered = []
    a_1m = {"key": "a_1m", "instrument": "A", "timeframe": "1m", "duration_ns": 60 * NS, "role": "execution", "source": "external"}
    mux = StreamMux([a_1m, _cw("a_4h", 4 * 3600, "a_1m")], delivered.append)
    mux.ingest(BarView("a_1m", 0, 60 * NS, 1, 1, 1, 1, 1))
    mux.ingest(BarView("a_1m", (4 * 3600 - 60) * NS, 4 * 3600 * NS, 1, 1, 1, 1, 1))
    four = [b for b in delivered if b.stream == "a_4h"]
    assert [(b.ts_event, b.ts_init) for b in four] == [(0, 4 * 3600 * NS)]


def test_mux_context_stream_visible_strictly_before_epoch():
    delivered = []
    mux = StreamMux(_streams(), delivered.append)
    mux.ingest(BarView("b_1m", 0, 60 * NS, 1, 1, 1, 1, 1))           # context bar closing at T=60
    mux.ingest(BarView("a_1s", 59 * NS, 60 * NS, 1, 1, 1, 1, 1))     # execution bar at T=60: context must NOT be visible
    assert [b.stream for b in delivered] == ["a_1s"]
    mux.assert_epoch_visibility(60 * NS)
    mux.ingest(BarView("a_1s", 60 * NS, 61 * NS, 1, 1, 1, 1, 1))     # first execution bar strictly later releases it
    assert [b.stream for b in delivered] == ["a_1s", "b_1m", "a_1s"]
    with pytest.raises(CausalOrderViolation):
        mux.ingest(BarView("a_1s", 60 * NS, 61 * NS, 1, 1, 1, 1, 1))


def _cadence_streams(visibility: str):
    """The G7 composition: 1s execution, and the coarser EXTERNAL 1m stream that supplies the
    population cadence.  ``visibility`` is the plan field under test."""
    return [{"key": "a_1s", "instrument": "A", "timeframe": "1s", "duration_ns": NS, "role": "execution", "source": "external"},
            {"key": "a_5s", "instrument": "A", "timeframe": "5s", "duration_ns": 5 * NS, "role": "execution", "source": "derived",
             "derived_from": "a_1s", "aggregation": "complete_bucket"},
            {"key": "a_1m", "instrument": "A", "timeframe": "1m", "duration_ns": 60 * NS, "role": "context", "source": "external",
             "visibility": visibility}]


def _run_cadence_tape(visibility: str):
    """Feed 1s bars across a minute boundary with the 1m bar queued, and raise the epoch the way
    ``HostStrategy._deliver`` does -- inside the delivery of the cadence bar, before the execution
    bar that released it is applied."""
    delivered, epochs = [], []
    mux = None

    def deliver(bar):
        delivered.append(bar)
        if bar.stream == "a_1m":
            mux.assert_epoch_visibility(bar.ts_init)
            epochs.append(bar.ts_init)

    mux = StreamMux(_cadence_streams(visibility), deliver)
    mux.ingest(BarView("a_1m", 0, 60 * NS, 1, 1, 1, 1, 1))              # queued: released only ahead of a later execution bar
    for s in (59, 60):
        mux.ingest(BarView("a_1s", s * NS, (s + 1) * NS, 1, 1, 1, 1, 1))
    return delivered, epochs


def test_cadence_context_stream_raises_its_epoch_at_its_own_bar_close():
    """G7a.  A completed-bar cadence stream declared ``at_epoch`` epochs at its own ts_init: the 1s
    bar closing at the same instant is already visible, and nothing is ahead of T."""
    delivered, epochs = _run_cadence_tape("at_epoch")
    assert epochs == [60 * NS]
    # ordering: the 1m bar is delivered after the 1s bar that closes at T and before the next 1s bar
    assert [b.stream for b in delivered] == ["a_1s", "a_1m", "a_1s"]
    assert [b.ts_init for b in delivered] == [60 * NS, 60 * NS, 61 * NS]


def test_strictly_before_stream_still_cannot_be_visible_at_the_epoch():
    """The relaxation is the plan's ``visibility`` field, not a hole in the assertion."""
    with pytest.raises(CausalOrderViolation, match="CONTEXT_STREAM_VISIBLE_AT_EPOCH"):
        _run_cadence_tape("strictly_before")


def test_mux_refuses_a_derived_stream_whose_source_is_absent():
    """G7b backstop: a plan that names a source stream it does not carry cannot be constructed.
    The compiler dry-constructs the mux, so this is what turns that class into a typed gap."""
    streams = [s for s in _cadence_streams("at_epoch") if s["key"] != "a_1s"]
    with pytest.raises(CausalOrderViolation, match="DERIVED_SOURCE_STREAM_ABSENT"):
        StreamMux(streams, lambda bar: None)


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


@pytest.mark.parametrize("rule,expected", [("strict", ("CENSORED", "TIMEOUT")), ("first_bar_at_or_after", ("NEGATIVE", None))])
def test_horizon_end_rule_on_a_sparse_tape(rule, expected):
    """Bar at exactly T+horizon missing; the next bar (T+horizon+1) would hit the adverse barrier."""
    from research_workflow.target_replay_oracle import replay
    T = 1000 * NS
    contract = LabelOutcomeContract.from_plan({"contract": "label", "kernel": "barrier", "direction": "d", "atr": "a", "entry_reference": "next_bar_open",
                                               "session_end_censoring": True, "max_gap_ns": None, "same_bar_rule": "ambiguous_censor", "horizon_end_rule": rule,
                                               "arms": [{"id": "x", "favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_ns": 10 * NS, "expiry": "censor", "prefix": "x"}], "primary_arm": "x"})
    kernel = LabelOutcomeKernel(contract, _Sessions(None))
    kernel.open({"observation_ts": T, "regime_start_ns": 0, "checkpoint_index": 0}, T, 1, 1.0)
    tape = []
    for k in range(1, 15):
        if k == 10:
            continue                      # T+10 (the horizon end) is missing
        lo = 99.0 if k == 11 else 100.0   # adverse barrier hit only on T+11
        tape.append({"ts": T + k * NS, "open": 100.0, "high": 100.5, "low": lo, "close": 100.2, "gap": False})
        kernel.on_bar(BarView("s", T + (k - 1) * NS, T + k * NS, 100.0, 100.5, lo, 100.2, 1.0))
    kernel.finalize(T + 20 * NS)
    row = kernel.drain_rows()[0]
    assert (row["disposition"].replace("LABELED_", ""), row["censor_reason"]) == expected   # single-arm plans emit the primary columns only
    c = {"primitive": "ordered_barrier", "required_forward_outcomes": [{"id": "fo", "entry_reference": "next_bar_open", "session_end_censoring": True, "max_gap_seconds": None,
                                                                     "ordered_barriers": [{"id": "b", "favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_seconds": 10, "horizon_expiry_policy": "censor", "horizon_end_rule": rule}]}]}
    o = replay(c, {"observation_ts": T, "atr": 1.0, "direction": 1, "session_close_ts": None}, tape)
    assert (o["disposition"], o["censor_reason"]) == expected


def test_first_bar_at_or_after_never_crosses_the_session_close():
    """The horizon end falls on a missing second right at the close; the next bar belongs to the next session."""
    from research_workflow.target_replay_oracle import replay
    T = 1000 * NS
    close = T + 10 * NS
    contract = LabelOutcomeContract.from_plan({"contract": "label", "kernel": "barrier", "direction": "d", "atr": "a", "entry_reference": "next_bar_open",
                                               "session_end_censoring": True, "max_gap_ns": None, "same_bar_rule": "ambiguous_censor", "horizon_end_rule": "first_bar_at_or_after",
                                               "arms": [{"id": "x", "favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_ns": 10 * NS, "expiry": "censor", "prefix": "x"}], "primary_arm": "x"})
    kernel = LabelOutcomeKernel(contract, _Sessions(close))
    kernel.open({"observation_ts": T, "regime_start_ns": 0, "checkpoint_index": 0}, T, 1, 1.0)
    tape = []
    for k in list(range(1, 10)) + [18000]:                 # T+10 missing; next bar five hours later would hit the adverse barrier
        lo = 99.0 if k == 18000 else 100.0
        tape.append({"ts": T + k * NS, "open": 100.0, "high": 100.5, "low": lo, "close": 100.2, "gap": False})
        kernel.on_bar(BarView("s", T + (k - 1) * NS, T + k * NS, 100.0, 100.5, lo, 100.2, 1.0))
    kernel.finalize(T + 20000 * NS)
    row = kernel.drain_rows()[0]
    # The first bar the kernel actually observes after the horizon end (k=18000) already
    # lies beyond the session close -- SESSION_END takes precedence over HORIZON_EXPIRY;
    # the arm never resolves via TIMEOUT because no in-session bar was ever evaluated.
    assert (row["disposition"], row["censor_reason"]) == ("CENSORED", "SESSION_END")
    c = {"primitive": "ordered_barrier", "required_forward_outcomes": [{"id": "fo", "entry_reference": "next_bar_open", "session_end_censoring": True, "max_gap_seconds": None,
                                                                     "ordered_barriers": [{"id": "b", "favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_seconds": 10, "horizon_expiry_policy": "censor", "horizon_end_rule": "first_bar_at_or_after"}]}]}
    o = replay(c, {"observation_ts": T, "atr": 1.0, "direction": 1, "session_close_ts": close}, tape)
    assert (o["disposition"], o["censor_reason"]) == ("CENSORED", "SESSION_END")

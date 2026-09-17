"""C0: what a ``closed_window`` derived stream is allowed to fill with a zero-volume bar.

A TRADING_DAY row is the whole session, maintenance halt included, because that is what censoring at
the trading-day close means. The mux filled any window overlapping such a row, so every pre-2021
15:15-15:30 CT equity-index halt received a full set of flat bars on every derived timeframe, every
day, for two years -- and so did a 22-hour data outage, which made a hole indistinguishable from a
calm session.

The fill scope is the narrower table: trading days MINUS the declared maintenance halts (C0a) MINUS
the declared data outages (C0b). Windows it excludes are counted by reason instead of silently
skipped. C0c refuses a closed-window stream built on another derived stream at construction, which is
where the compiler's dry run learns about it.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from research_workflow.host.interfaces import NS, BarView
from research_workflow.host.mux import CausalOrderViolation, ClosedWindowAggregator, StreamMux
from research_workflow.sessions import (CalendarSessionTable, FillScopeTable, TRADING_DAY,
                                        build_session_table, fill_scope_windows, session_windows)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "data" / "catalog" / "NQ_1S_V2_GLOBEX"
needs_catalog = pytest.mark.skipif(not (CATALOG / "reference" / "sessions.parquet").is_file(),
                                   reason="NQ_1S_V2_GLOBEX catalog not present")


def _ct(s: str) -> int:
    return int(pd.Timestamp(s, tz="America/Chicago").tz_convert("UTC").value)


# --------------------------------------------------------------------------- derivation


def test_fill_scope_cuts_the_halt_and_leaves_an_unhalted_day_whole():
    sessions = pd.DataFrame([
        {"session_date": pd.Timestamp("2020-01-03").date(), "open_ns": _ct("2020-01-02 17:00:00"),
         "close_ns": _ct("2020-01-03 16:00:00"), "early_close": False,
         "halt_start_ns": _ct("2020-01-03 15:15:01"), "halt_end_ns": _ct("2020-01-03 15:30:00")},
        {"session_date": pd.Timestamp("2022-01-03").date(), "open_ns": _ct("2022-01-02 17:00:00"),
         "close_ns": _ct("2022-01-03 16:00:00"), "early_close": False,
         "halt_start_ns": None, "halt_end_ns": None},
    ])
    rows, halts, outages = fill_scope_windows(sessions, gaps_df=None, outage_gap_seconds=7200)
    assert outages == []
    # the cut starts at the RTH close second, not at halt_start_ns: 15:15:00 CT is where the product
    # halts, `session_windows(..., "RTH")` already ends there, and the tape never carries that second
    assert halts == [(_ct("2020-01-03 15:15:00"), _ct("2020-01-03 15:30:00"))]
    assert rows == [(_ct("2020-01-02 17:00:00"), _ct("2020-01-03 15:15:00")),
                    (_ct("2020-01-03 15:30:00"), _ct("2020-01-03 16:00:00")),
                    (_ct("2022-01-02 17:00:00"), _ct("2022-01-03 16:00:00"))]
    # the trading-day row itself is untouched -- it is the censoring authority, halt included
    assert session_windows(sessions, TRADING_DAY)[0] == (_ct("2020-01-02 17:00:00"), _ct("2020-01-03 16:00:00"))


def test_only_gap_runs_at_or_above_the_declared_threshold_are_outages():
    sessions = pd.DataFrame([{"session_date": pd.Timestamp("2021-07-01").date(), "open_ns": _ct("2021-06-30 17:00:00"),
                              "close_ns": _ct("2021-07-01 16:00:00"), "early_close": False,
                              "halt_start_ns": None, "halt_end_ns": None}])
    gaps = pd.DataFrame([{"start_ns": _ct("2021-06-30 20:00:00"), "end_ns": _ct("2021-06-30 20:05:00"), "seconds": 300},
                         {"start_ns": _ct("2021-07-01 01:00:00"), "end_ns": _ct("2021-07-01 03:00:00"), "seconds": 7200}])
    rows, _halts, outages = fill_scope_windows(sessions, gaps_df=gaps, outage_gap_seconds=7200)
    assert outages == [(_ct("2021-07-01 01:00:00"), _ct("2021-07-01 03:00:00"))]     # the 300 s run is a quiet market
    assert rows == [(_ct("2021-06-30 17:00:00"), _ct("2021-07-01 01:00:00")),
                    (_ct("2021-07-01 03:00:00"), _ct("2021-07-01 16:00:00"))]
    # every empty window is inside SOME gap run (native rows only), so an unthresholded subtraction
    # would be `empty_window: none`, not a fix
    all_rows, _h, all_out = fill_scope_windows(sessions, gaps_df=gaps, outage_gap_seconds=1)
    assert len(all_out) == 2 and len(all_rows) == 3


def test_subtracting_cuts_from_rows_covers_exactly_the_right_seconds():
    """The cut arithmetic against a brute-force set difference, including cuts that span several rows
    and cuts wholly outside every row. Output must stay sorted and disjoint (CalendarSessionTable
    refuses overlapping rows); abutting pieces are not merged, which changes no coverage."""
    import random
    from research_workflow.sessions import _subtract_intervals
    rng = random.Random(7)
    cover = lambda iv: {x for a, b in iv for x in range(a, b)}
    for _ in range(400):
        rows, t = [], 0
        for _ in range(rng.randint(1, 5)):
            t += rng.randint(0, 4); a = t; t += rng.randint(1, 8); rows.append((a, t))
        cuts, u = [], 0
        for _ in range(rng.randint(0, 6)):
            u += rng.randint(0, 4); a = u; u += rng.randint(1, 6); cuts.append((a, u))
        got = _subtract_intervals(rows, cuts)
        assert cover(got) == cover(rows) - cover(cuts), (rows, cuts, got)
        assert all(b <= c for (_a, b), (c, _d) in zip(got, got[1:])), got


def test_skip_reason_attributes_a_window_to_the_halt_then_the_outage_then_the_closure():
    scope = FillScopeTable([(0, 10 * NS), (40 * NS, 60 * NS)],
                           halts=[(10 * NS, 20 * NS)], outages=[(20 * NS, 40 * NS)])
    assert scope.overlaps(0, 5 * NS) and not scope.overlaps(10 * NS, 15 * NS)
    assert scope.skip_reason(10 * NS, 15 * NS) == "halt"
    assert scope.skip_reason(25 * NS, 30 * NS) == "outage"
    assert scope.skip_reason(70 * NS, 75 * NS) == "closed"
    # a window straddling both is the halt: the scheduled closure is the primary reason
    assert scope.skip_reason(15 * NS, 25 * NS) == "halt"


# --------------------------------------------------------------------------- the mux


def _fill(days, bars_s, bucket_s, sweep_to_s):
    agg = ClosedWindowAggregator("a_5s", bucket_s * NS, NS, trading_days=days)
    out = []
    for s in bars_s:
        out += agg.on_source_bar(BarView("a_1s", s * NS, (s + 1) * NS, 1.0, 1.0, 1.0, 1.0, 1.0))
    out += agg.sweep(sweep_to_s * NS, True)
    return agg.empty_windows_published, dict(agg.windows_suppressed)


def test_windows_inside_a_halt_are_suppressed_and_counted_not_filled():
    rows = [(0, 20 * NS), (40 * NS, 60 * NS)]
    published, suppressed = _fill(FillScopeTable(rows, halts=[(20 * NS, 40 * NS)]), [1, 45], 5, 60)
    assert suppressed == {"halt": 4, "outage": 0}                     # 20..40 s at 5 s = 4 windows
    assert published == 6                                             # 5..20 (3), 40..45 (1), 50..60 (2)
    # the same tape against the trading-day row the censor uses fills straight through the halt
    whole, _ = _fill(CalendarSessionTable([(0, 60 * NS)], name=TRADING_DAY), [1, 45], 5, 60)
    assert whole == 10 and whole - published == 4


def test_windows_inside_an_outage_are_suppressed_and_counted_separately():
    rows = [(0, 20 * NS), (40 * NS, 60 * NS)]
    published, suppressed = _fill(FillScopeTable(rows, outages=[(20 * NS, 40 * NS)]), [1, 45], 5, 60)
    assert suppressed == {"halt": 0, "outage": 4}
    assert published == 6


def test_a_closure_is_not_a_suppression_and_is_not_iterated():
    """D3b: nothing across a weekend/holiday. A closure is skipped in one jump and never counted --
    the counter answers "how much did a hole cost", not "how long was the market shut"."""
    published, suppressed = _fill(FillScopeTable([(0, 20 * NS), (40 * NS, 60 * NS)]), [1, 45], 5, 60)
    assert suppressed == {"halt": 0, "outage": 0}
    assert published == 6


def test_mux_reports_suppression_per_stream_only_when_nonzero():
    a1s = {"key": "a_1s", "instrument": "A", "timeframe": "1s", "duration_ns": NS, "role": "execution", "source": "external"}
    a5s = {"key": "a_5s", "instrument": "A", "timeframe": "5s", "duration_ns": 5 * NS, "role": "execution",
           "source": "derived", "derived_from": "a_1s", "aggregation": "closed_window",
           "empty_window": "zero_volume_in_trading_day"}
    scope = FillScopeTable([(0, 20 * NS), (40 * NS, 60 * NS)], outages=[(20 * NS, 40 * NS)])
    mux = StreamMux([a1s, a5s], lambda b: None, trading_days=scope)
    assert mux.windows_suppressed() == {}
    for s in (1, 45):
        mux.ingest(BarView("a_1s", s * NS, (s + 1) * NS, 1.0, 1.0, 1.0, 1.0, 1.0))
    assert mux.windows_suppressed() == {"a_5s": {"halt": 0, "outage": 4}}
    assert mux.empty_windows_published() == {"a_5s": 4}


# --------------------------------------------------------------------------- C0c


def test_a_closed_window_stream_may_not_aggregate_another_derived_stream():
    a1s = {"key": "a_1s", "instrument": "A", "timeframe": "1s", "duration_ns": NS, "role": "execution", "source": "external"}
    a5s = {"key": "a_5s", "instrument": "A", "timeframe": "5s", "duration_ns": 5 * NS, "role": "execution",
           "source": "derived", "derived_from": "a_1s", "aggregation": "closed_window", "empty_window": "none"}
    a30s = {"key": "a_30s", "instrument": "A", "timeframe": "30s", "duration_ns": 30 * NS, "role": "execution",
            "source": "derived", "derived_from": "a_5s", "aggregation": "closed_window", "empty_window": "none"}
    with pytest.raises(CausalOrderViolation, match="DERIVED_FROM_DERIVED_CLOSED_WINDOW"):
        StreamMux([a1s, a5s, a30s], lambda b: None, require_calendar=False)


# --------------------------------------------------------------------------- fail-closed


def _compile_with_derived_5s(tmp_path, datasets_dir):
    import yaml
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    body = yaml.safe_load((ROOT / "fixtures" / "golden" / "study_flip.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = "fill_scope_gate"
    body["streams"] = [{"dataset": "SYN_A", "timeframes": ["1s", "5s", "1m"]}]        # 5s is DERIVED -> fill is on
    study = tmp_path / "studies" / body["study"]["id"]; study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return compile_study(load_spec(study), repo_root=ROOT, datasets_dir=datasets_dir, extra_bindings=SYNTHETIC_BINDINGS)


def _syn_a_datasets(tmp_path, *, outage_gap_seconds, reference_tables=("sessions", "gaps")):
    import shutil, yaml
    d = tmp_path / "datasets"; d.mkdir(parents=True)
    for f in (ROOT / "fixtures" / "golden" / "datasets").glob("*.yaml"):
        shutil.copy2(f, d / f.name)
    body = yaml.safe_load((d / "SYN_A.yaml").read_text(encoding="utf-8"))
    body["reference_tables"] = list(reference_tables)
    rules = dict(body.get("rules") or {})
    if outage_gap_seconds is not None:
        rules["outage_gap_seconds"] = outage_gap_seconds
    body["rules"] = rules
    (d / "SYN_A.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return d


def test_a_calendar_dataset_with_a_derived_stream_must_declare_the_outage_rule(tmp_path):
    """The compile gate. Fill is switched on by the dataset's calendar, so the dataset is also where
    "what counts as an outage" has to be declared -- otherwise the compile produces a plan that would
    fill a 22-hour hole with flat bars and call it a quiet market."""
    out = _compile_with_derived_5s(tmp_path / "missing", _syn_a_datasets(tmp_path / "missing", outage_gap_seconds=None))
    assert not out.ok
    gaps = out.gaps.to_dict()["gaps"]
    assert any(g["kind"] == "SEMANTIC_DECISION_REQUIRED" and "outage_gap_seconds" in g["message"] for g in gaps), gaps

    # declared but with no gaps table to identify an outage in: also refused
    out = _compile_with_derived_5s(tmp_path / "nogaps",
                                   _syn_a_datasets(tmp_path / "nogaps", outage_gap_seconds=7200, reference_tables=("sessions",)))
    assert not out.ok
    gaps = out.gaps.to_dict()["gaps"]
    assert any(g["kind"] == "SEMANTIC_DECISION_REQUIRED" and "gaps" in g["message"] for g in gaps), gaps

    # declared: the rule travels in the plan, so a run cannot adopt a different one than the audit saw
    out = _compile_with_derived_5s(tmp_path / "ok", _syn_a_datasets(tmp_path / "ok", outage_gap_seconds=7200))
    assert out.ok, out.card()
    plan = out.plan.to_dict()
    assert plan["session"]["outage_gap_seconds"] == 7200
    five = next(s for s in plan["streams"] if s["timeframe"] == "5s")
    assert five["aggregation"] == "closed_window" and five["empty_window"] == "zero_volume_in_trading_day"


def test_no_declared_outage_rule_means_no_fill_scope_and_so_no_fill():
    """A spec without the rule is not an error -- it gets no fill scope, so a stream that wanted to
    fill is refused rather than filling holes. That is also what lets a plan sealed before the rule
    existed replay untouched: it aggregates `complete_bucket` and never fills."""
    a1s = {"key": "a_1s", "instrument": "A", "timeframe": "1s", "duration_ns": NS, "role": "execution", "source": "external"}
    a5s = {"key": "a_5s", "instrument": "A", "timeframe": "5s", "duration_ns": 5 * NS, "role": "execution",
           "source": "derived", "derived_from": "a_1s", "aggregation": "closed_window",
           "empty_window": "zero_volume_in_trading_day"}
    table = build_session_table({"kind": "calendar", "session": "RTH", "rows": [(0, 60 * NS)],
                                 "rows_by_session": {TRADING_DAY: [(0, 60 * NS)]}, "fill_scope": None})
    assert getattr(table, "fill_scope", None) is None and table.trading_day is not None
    with pytest.raises(CausalOrderViolation, match="TRADING_DAY_CALENDAR_ABSENT"):
        StreamMux([a1s, a5s], lambda b: None, trading_days=getattr(table, "fill_scope", None))
    # a sealed complete_bucket plan has no fill at all, so the same table replays it untouched
    sealed = dict(a5s, aggregation="complete_bucket")
    del sealed["empty_window"]
    StreamMux([a1s, sealed], lambda b: None, trading_days=getattr(table, "fill_scope", None))


# --------------------------------------------------------------------------- against the real tape


@needs_catalog
def test_real_catalog_halt_and_outage_and_an_unaffected_year():
    """The three C0 gates on the tape that produced them. 2023 has neither a halt nor an outage, so
    its fill must be bit-for-bit what the pilot collected."""
    ref = CATALOG / "reference"
    sessions = pd.read_parquet(ref / "sessions.parquet")
    gaps = pd.read_parquet(ref / "gaps.parquet")
    rows, halts, outages = fill_scope_windows(sessions, gaps_df=gaps, outage_gap_seconds=7200)
    scope = FillScopeTable(rows, halts=halts, outages=outages)
    whole = CalendarSessionTable([(a, b) for a, b in session_windows(sessions, TRADING_DAY)], name=TRADING_DAY)
    assert len(halts) == 372                                    # 2020-01-02 .. 2021-06-25
    assert len(outages) == 9

    def sweep(days, lo, hi, bucket_ns):
        agg = ClosedWindowAggregator("x", bucket_ns, NS, trading_days=days)
        agg.on_source_bar(BarView("s", lo, lo + NS, 1.0, 1.0, 1.0, 1.0, 1.0))
        agg.sweep(hi, True)
        return agg.empty_windows_published, dict(agg.windows_suppressed)

    # C0a: one halt, every derived timeframe, zero filled windows
    h_lo, h_hi = _ct("2020-01-03 15:15:00"), _ct("2020-01-03 15:30:00")
    for bucket_s, expected in ((5, 180), (30, 30), (180, 5), (300, 3), (900, 1)):
        before, _ = sweep(whole, h_lo - bucket_s * NS, h_hi, bucket_s * NS)
        after, sup = sweep(scope, h_lo - bucket_s * NS, h_hi, bucket_s * NS)
        assert (before, after) == (expected, 0), bucket_s
        assert sup == {"halt": expected, "outage": 0}, bucket_s

    # C0b: the 2020-12-31 outage, counted and not filled
    o_lo, o_hi = _ct("2020-12-30 18:00:00"), _ct("2020-12-31 15:15:00")
    before, _ = sweep(whole, o_lo, o_hi, 3600 * NS)
    after, sup = sweep(scope, o_lo, o_hi, 3600 * NS)
    assert before == 20 and after == 0 and sup["outage"] == 20

    # C0 gate: 2023 has neither, so nothing about it may move
    for lo, hi, bucket_s in ((_ct("2023-03-01 00:00:00"), _ct("2023-04-01 00:00:00"), 5),
                             (_ct("2023-03-01 00:00:00"), _ct("2023-04-01 00:00:00"), 300)):
        before, _ = sweep(whole, lo, hi, bucket_s * NS)
        after, sup = sweep(scope, lo, hi, bucket_s * NS)
        assert before == after and sup == {"halt": 0, "outage": 0}, bucket_s

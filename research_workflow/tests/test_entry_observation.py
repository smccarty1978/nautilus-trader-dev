"""Causal executable-entry observation (``outcome.entry_observation``).

The C1 terminal block publishes ``terminal_entry_ts`` / ``terminal_entry_price`` only beside an
executable EXIT, so a row whose future has no exit (no flip before the close, DATA_END, an exit
GAP) lost an entry that was known one bar after T: missingness selected by the future. The
``executable_entry_*`` block publishes the entry as soon as it is known and depends on nothing
after the entry bar. ``terminal_entry_*`` keeps its historical contract untouched.

Everything drives the production kernel (``LabelOutcomeContract.from_plan`` ->
``LabelOutcomeKernel``) or the production compiler + host (``compile_study`` ->
``run_plan_on_bars``). Nothing re-implements kernel logic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from research_workflow.host.interfaces import BarView
from research_workflow.host.outcomes import (ENTRY_OBSERVATION_COLUMNS, TERMINAL_OBSERVATION_COLUMNS,
                                             LabelOutcomeContract, LabelOutcomeKernel, OutcomeContractError)
from research_workflow.sessions import CalendarSessionTable

NS = 1_000_000_000
T0 = 1_700_000_000 * NS
OPEN_TS = T0 - 60 * NS                 # session open
CLOSE = T0 + 600 * NS                  # a 10-minute trading day: every 24h horizon crosses it
ATR = 20.0
MAX_GAP = 300 * NS
HORIZON_NS = 24 * 3600 * NS
PARKED = 99.0

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"


def _arms(prefix="fp"):
    return [{"id": "fav_0p25", "favorable_atr": 0.25, "adverse_atr": PARKED, "horizon_ns": HORIZON_NS,
             "expiry": "censor", "prefix": f"{prefix}_fav_0p25"},
            {"id": "fav_5p00", "favorable_atr": 5.0, "adverse_atr": PARKED, "horizon_ns": HORIZON_NS,
             "expiry": "censor", "prefix": f"{prefix}_fav_5p00"},
            {"id": "adv_1p00", "favorable_atr": PARKED, "adverse_atr": 1.0, "horizon_ns": HORIZON_NS,
             "expiry": "censor", "prefix": f"{prefix}_adv_1p00"}]


def contract(*, entry_observation=True, kernel="composite", session_end_rule="truncate", terminal=True):
    spec = {
        "contract": "label", "kernel": kernel, "direction": "regime_1m.dir",
        "atr": "excursion_1m.frozen_atr", "entry_reference": "next_bar_open",
        "session_end_censoring": session_end_rule != "ignore", "session_end_rule": session_end_rule,
        "horizon_end_rule": "strict", "max_gap_ns": MAX_GAP, "same_bar_rule": "ambiguous_censor",
        "arms": _arms() if kernel != "flip" else [],
        "flip": ({"horizon_ns": HORIZON_NS, "source": "regime_1m", "role": "opposite", "inclusive_start": True}
                 if kernel != "barrier" else None),
        "primary_arm": "fav_0p25" if kernel != "flip" else None,
        "composition": {"logic": "OR"} if kernel == "composite" else None, "direction_sign": 1,
        "observed_seconds": True, "terminal_outcome": terminal and kernel != "barrier",
        "entry_observation": entry_observation,
    }
    return LabelOutcomeContract.from_plan(spec)


def sessions():
    return CalendarSessionTable([(OPEN_TS, CLOSE)], name="TRADING_DAY")


def bar(i_start_s, o, h, l, c):
    """A 1s bar whose OPEN instant is T0 + i_start_s seconds (ts_init = open + 1s)."""
    ts_event = T0 + int(i_start_s * NS)
    return BarView("1s", ts_event, ts_event + NS, o, h, l, c, 1.0)


# The shared history: the decision bar closes AT T (ts_init == T: never eligible) and the entry
# bar is the first bar strictly after T. Open, high, low and close all differ from each other and
# from the decision bar, so "entry is the OPEN" cannot pass by coincidence.
DECISION = BarView("1s", T0 - NS, T0, 14_990.0, 15_001.0, 14_989.0, 15_000.0, 1.0)
ENTRY_BAR = bar(0, 15_002.0, 15_003.0, 15_001.0, 15_002.5)


def run(bars, *, flip_after_ts=None, direction=1, finalize_ts=None, **ckw):
    k = LabelOutcomeKernel(contract(**ckw), sessions())
    k.open({"observation_ts": T0, "regime_start_ns": T0, "checkpoint_index": 0}, T0, direction, ATR)
    for b in bars:
        k.on_bar(b)
        if flip_after_ts is not None and b.ts_init == flip_after_ts:
            k.on_flip(b.ts_init, -direction, direction)
    k.finalize(finalize_ts if finalize_ts is not None else bars[-1].ts_init)
    rows = k.drain_rows()
    assert len(rows) == 1, len(rows)
    return rows[0], k


def flat(from_s, to_s, px=15_002.5):
    return [bar(s, px, px, px, px) for s in range(from_s, to_s)]


def entry_of(row):
    return row["executable_entry_ts"], row["executable_entry_price"], row["executable_entry_unavailable_reason"]


EXPECTED = (ENTRY_BAR.ts_event, ENTRY_BAR.open, None)


# ------------------------------------------------------------------------------------------ #
# The four futures, sharing their history through the entry bar.
# ------------------------------------------------------------------------------------------ #
def future_normal():
    """A: opposite flip at t=5s, executable exit bar right after it."""
    tail = [bar(1, 15_002.5, 15_010.0, 15_002.0, 15_009.0)] + flat(2, 6, 15_009.0) + [bar(6, 15_011.0, 15_012.0, 15_010.0, 15_011.5)]
    return [DECISION, ENTRY_BAR] + tail, T0 + 6 * NS


def future_never_flips():
    """B: no flip before the trading-day close (terminal SESSION_END under truncate)."""
    return [DECISION, ENTRY_BAR] + flat(1, 605), None


def future_loses_exit_bar():
    """C: the flip lands on the last bar of the run -- no executable exit bar exists."""
    return [DECISION, ENTRY_BAR] + flat(1, 6), T0 + 6 * NS


def future_session_boundary():
    """D: the flip lands AT the close; the next bar is past it, so the exit is SESSION_END."""
    return [DECISION, ENTRY_BAR] + flat(1, 600) + flat(620, 625), CLOSE


FUTURES = {"normal": future_normal, "never_flips": future_never_flips,
           "loses_exit_bar": future_loses_exit_bar, "session_boundary": future_session_boundary}


def test_entry_is_the_open_of_the_first_bar_strictly_after_t_not_a_close():
    bars, flip = future_normal()
    row, _ = run(bars, flip_after_ts=flip)
    assert entry_of(row) == EXPECTED
    assert row["executable_entry_price"] == 15_002.0
    assert row["executable_entry_price"] not in (DECISION.close, DECISION.open, ENTRY_BAR.close, ENTRY_BAR.high, ENTRY_BAR.low)
    # TIMESTAMP CONVENTION (identical to terminal_entry_ts and to the arms' resolution_seconds
    # anchor): executable_entry_ts is the entry bar's OPEN instant (ts_event). The bar is the first
    # with ts_init strictly after T, so its open price is first traded after T; on a contiguous
    # 1s tape its open instant equals T itself.
    assert ENTRY_BAR.ts_init > T0
    assert row["executable_entry_ts"] == ENTRY_BAR.ts_event == T0


def test_normal_flip_and_exit_entry_equals_terminal_entry():
    bars, flip = future_normal()
    row, _ = run(bars, flip_after_ts=flip)
    assert row["terminal_exit_price"] is not None
    assert (row["terminal_entry_ts"], row["terminal_entry_price"]) == (row["executable_entry_ts"], row["executable_entry_price"])


@pytest.mark.parametrize("name", sorted(FUTURES))
def test_future_independence_entry_is_bit_identical_across_futures(name):
    bars, flip = FUTURES[name]()
    row, _ = run(bars, flip_after_ts=flip)
    assert entry_of(row) == EXPECTED, name


def test_future_independence_all_four_futures_publish_the_same_entry_and_differ_elsewhere():
    rows = {}
    for name, fn in FUTURES.items():
        bars, flip = fn()
        rows[name], _ = run(bars, flip_after_ts=flip)
    entries = {name: entry_of(r) for name, r in rows.items()}
    assert len(set(entries.values())) == 1 and entries["normal"] == EXPECTED
    # the futures really are different: the terminal side differs across them
    terminals = {(r["terminal_flip_disposition"], r["terminal_exit_unavailable_reason"]) for r in rows.values()}
    assert len(terminals) >= 3, terminals
    # and the historical C1 entry is present only where an exit exists
    assert rows["normal"]["terminal_entry_price"] is not None
    for name in ("never_flips", "loses_exit_bar", "session_boundary"):
        assert rows[name]["terminal_entry_price"] is None, name


def test_no_terminal_flip_before_the_close():
    bars, _ = future_never_flips()
    row, _ = run(bars)
    assert row["terminal_flip_disposition"] == "CENSORED" and row["terminal_flip_censor_reason"] == "SESSION_END"
    assert entry_of(row) == EXPECTED


def test_flip_with_no_executable_exit_bar_data_end():
    bars, flip = future_loses_exit_bar()
    row, _ = run(bars, flip_after_ts=flip)
    assert row["terminal_flip_disposition"] == "LABELED_POSITIVE"
    assert row["terminal_exit_unavailable_reason"] == "DATA_END"
    assert row["terminal_entry_price"] is None           # historical C1 contract, unchanged
    assert entry_of(row) == EXPECTED


def test_flip_whose_exit_bar_is_a_gap():
    bars = [DECISION, ENTRY_BAR] + flat(1, 6) + flat(400, 403)     # 394 s hole after the flip > max_gap
    row, _ = run(bars, flip_after_ts=T0 + 6 * NS)
    assert row["terminal_exit_unavailable_reason"] == "GAP"
    assert entry_of(row) == EXPECTED


def test_flip_at_session_close_exit_session_end():
    bars, flip = future_session_boundary()
    row, _ = run(bars, flip_after_ts=flip)
    assert row["terminal_exit_unavailable_reason"] == "SESSION_END"
    assert entry_of(row) == EXPECTED


def test_data_end_before_the_close_without_a_flip():
    bars = [DECISION, ENTRY_BAR] + flat(1, 30)                     # tape stops long before the close
    row, _ = run(bars)
    assert row["terminal_flip_censor_reason"] == "DATA_END"
    assert entry_of(row) == EXPECTED


def test_censored_terminal_and_unresolved_milestone_arms_still_publish_entry():
    bars = [DECISION, ENTRY_BAR] + flat(1, 30)
    row, _ = run(bars)
    assert row["censored"] == 1
    assert row["fp_fav_5p00_disposition"] == "CENSORED"            # never touched
    assert row["fp_adv_1p00_disposition"] == "CENSORED"
    assert row["terminal_flip_disposition"] == "CENSORED"
    assert entry_of(row) == EXPECTED


def test_entry_after_a_short_tape_hole_is_the_next_existing_bar():
    later = bar(4, 15_020.0, 15_025.0, 15_019.0, 15_024.0)           # 4 s hole, < max_gap
    row, _ = run([DECISION, later] + flat(5, 20))
    assert entry_of(row) == (later.ts_event, later.open, None)


def test_gap_stale_entry_is_null_with_reason_gap():
    stale = bar(301, 15_020.0, 15_025.0, 15_019.0, 15_024.0)         # entry open 301 s after T > max_gap
    row, _ = run([DECISION, stale] + flat(302, 310))
    assert entry_of(row) == (None, None, "GAP")


def test_entry_bar_exactly_at_max_gap_is_published():
    edge = bar(300, 15_020.0, 15_025.0, 15_019.0, 15_024.0)
    row, _ = run([DECISION, edge] + flat(301, 310))
    assert entry_of(row) == (edge.ts_event, edge.open, None)


def test_no_bar_before_the_trading_day_close_is_session_end():
    # T two seconds before the close; the first bar after T is 30 s past it (inside max_gap, so
    # SESSION_END must be decided by the session, not by the gap rule).
    T = CLOSE - 2 * NS
    k = LabelOutcomeKernel(contract(), sessions())
    k.open({"observation_ts": T, "regime_start_ns": T, "checkpoint_index": 0}, T, 1, ATR)
    late = BarView("1s", CLOSE + 29 * NS, CLOSE + 30 * NS, 15_050.0, 15_051.0, 15_049.0, 15_050.5, 1.0)
    k.on_bar(BarView("1s", T - NS, T, 15_000.0, 15_000.0, 15_000.0, 15_000.0, 1.0))
    k.on_bar(late)
    k.finalize(late.ts_init)
    (row,) = k.drain_rows()
    assert entry_of(row) == (None, None, "SESSION_END")


def test_entry_bar_closing_exactly_at_the_close_is_published():
    T = CLOSE - 2 * NS
    k = LabelOutcomeKernel(contract(), sessions())
    k.open({"observation_ts": T, "regime_start_ns": T, "checkpoint_index": 0}, T, 1, ATR)
    last = BarView("1s", CLOSE - NS, CLOSE, 15_050.0, 15_051.0, 15_049.0, 15_050.5, 1.0)
    k.on_bar(last)
    k.on_bar(BarView("1s", CLOSE + 10 * NS, CLOSE + 11 * NS, 15_060.0, 15_060.0, 15_060.0, 15_060.0, 1.0))
    k.finalize(CLOSE + 11 * NS)
    (row,) = k.drain_rows()
    assert entry_of(row) == (last.ts_event, last.open, None)


def test_no_bar_after_t_at_all_is_data_end():
    row, _ = run([DECISION], finalize_ts=T0)
    assert entry_of(row) == (None, None, "DATA_END")


def test_short_direction_entry_price_is_unsigned():
    bars, flip = future_normal()
    row, _ = run(bars, flip_after_ts=flip, direction=-1)
    assert entry_of(row) == EXPECTED


def test_barrier_kernel_also_publishes_entry():
    row, _ = run([DECISION, ENTRY_BAR] + flat(1, 30), kernel="barrier")
    assert entry_of(row) == EXPECTED


def test_flip_kernel_refuses_entry_observation():
    with pytest.raises(OutcomeContractError, match="ENTRY_OBSERVATION_REQUIRES_EXECUTION_BARS"):
        LabelOutcomeKernel(contract(kernel="flip"), sessions())


def test_deterministic_replay():
    for fn in FUTURES.values():
        bars, flip = fn()
        a, _ = run(bars, flip_after_ts=flip)
        b, _ = run(bars, flip_after_ts=flip)
        assert a == b


# ------------------------------------------------------------------------------------------ #
# Compatibility: a contract that does not request the surface is unchanged.
# ------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("name", sorted(FUTURES))
def test_flag_off_rows_are_identical_minus_the_new_columns(name):
    bars, flip = FUTURES[name]()
    on, k_on = run(bars, flip_after_ts=flip)
    off, k_off = run(bars, flip_after_ts=flip, entry_observation=False)
    assert not set(ENTRY_OBSERVATION_COLUMNS) & set(off)
    assert not set(ENTRY_OBSERVATION_COLUMNS) & set(k_off.observation_columns)
    assert {k: v for k, v in on.items() if k not in ENTRY_OBSERVATION_COLUMNS} == off
    assert [c for c in k_on.observation_columns if c not in ENTRY_OBSERVATION_COLUMNS] == k_off.observation_columns


def test_column_order_terminal_then_entry_then_observed_seconds_last():
    _, k = run([DECISION, ENTRY_BAR] + flat(1, 30))
    cols = k.observation_columns
    assert cols[-1] == "observed_seconds"
    n = len(ENTRY_OBSERVATION_COLUMNS)
    assert cols[-1 - n:-1] == list(ENTRY_OBSERVATION_COLUMNS)
    assert cols[-1 - n - len(TERMINAL_OBSERVATION_COLUMNS):-1 - n] == list(TERMINAL_OBSERVATION_COLUMNS)


def test_every_emitted_entry_key_is_a_declared_column():
    bars, flip = future_normal()
    row, k = run(bars, flip_after_ts=flip)
    assert {c for c in row if c.startswith("executable_entry")} == set(ENTRY_OBSERVATION_COLUMNS)
    assert set(row) <= set(k.observation_columns) | {"observation_ts", "regime_start_ns", "checkpoint_index"}


# ------------------------------------------------------------------------------------------ #
# Production compiler + host, on the golden fixture.
# ------------------------------------------------------------------------------------------ #
@pytest.fixture(scope="module")
def golden():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    session_spec = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    return bars, session_spec


def _compile(tmp_path, name, mutate):
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    body = yaml.safe_load((GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = name
    mutate(body["outcome"])
    study = tmp_path / "studies" / name
    study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return compile_study(load_spec(study), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)


def _composite(o, flag):
    o["event"] = "regime.flipped"
    o["composition"] = "OR"
    o["session_end"] = "truncate"
    if flag:
        o["entry_observation"] = True


def _collect(plan, golden_):
    from research_workflow.host_runner import run_plan_on_bars
    from research_workflow.sessions import build_session_table
    bars, session_spec = golden_
    return run_plan_on_bars(plan, bars, session_table=build_session_table(session_spec))["observations"]


def test_compiled_composite_publishes_entry_equal_to_first_bar_open_after_t(tmp_path, golden):
    out = _compile(tmp_path, "eo_on", lambda o: _composite(o, True))
    assert out.ok, out.card()
    plan = out.plan.to_dict()
    assert plan["outcome"]["entry_observation"] is True
    declared = plan["outcome"]["observation_columns"]
    assert declared[-1] == "observed_seconds" and declared[-4:-1] == list(ENTRY_OBSERVATION_COLUMNS)
    obs = _collect(plan, golden)
    assert len(obs) > 0
    assert set(declared) <= set(obs.columns)                 # persisted-schema: nothing dropped by the sink
    stream = plan["outcome"].get("stream")
    exe = sorted((b for b in golden[0] if b.stream == (stream or b.stream) and b.stream.endswith("1s")), key=lambda b: b.ts_init)
    published = obs[obs["executable_entry_price"].notna()]
    assert len(published) > 0
    for _, r in published.iterrows():
        first = next(b for b in exe if b.ts_init > r["observation_ts"])
        assert r["executable_entry_price"] == first.open
        assert r["executable_entry_ts"] == first.ts_event
        assert r["executable_entry_ts"] >= r["observation_ts"]
    both = obs[obs["terminal_entry_price"].notna()]
    assert (both["terminal_entry_price"] == both["executable_entry_price"]).all()
    assert (both["terminal_entry_ts"] == both["executable_entry_ts"]).all()
    # the decoupled column covers every row the C1 column covers, and more rows are never lost
    assert published.index.isin(obs.index).all() and len(published) >= len(both)
    nulls = obs[obs["executable_entry_price"].isna()]
    assert nulls["executable_entry_unavailable_reason"].notna().all()


def test_compiled_plan_without_the_flag_is_unchanged(tmp_path, golden):
    on = _compile(tmp_path, "eo_cmp", lambda o: _composite(o, True))
    off = _compile(tmp_path, "eo_cmp", lambda o: _composite(o, False))
    assert on.ok and off.ok
    p_on, p_off = on.plan.to_dict(), off.plan.to_dict()
    assert "entry_observation" not in p_off["outcome"]
    assert not set(ENTRY_OBSERVATION_COLUMNS) & set(p_off["outcome"]["observation_columns"])
    o_on, o_off = _collect(p_on, golden), _collect(p_off, golden)
    shared = list(o_off.columns)
    assert list(o_on.drop(columns=list(ENTRY_OBSERVATION_COLUMNS)).columns) == shared
    assert o_on[shared].equals(o_off[shared])


def test_compiler_refuses_entry_observation_without_barrier_arms(tmp_path):
    def flip_only(o):
        o.pop("barrier", None)
        o["event"] = "regime.flipped"
        o["entry_observation"] = True
    out = _compile(tmp_path, "eo_flip", flip_only)
    assert not out.ok
    assert "outcome.entry_observation" in json.dumps(out.card())

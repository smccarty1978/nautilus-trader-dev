"""G2: a calendar dataset's trading-day close as an outcome CENSORING session (``outcome.session:
TRADING_DAY``). The grammar admitted only RTH | ETH | ALL; a census that spans ETH and RTH
(``population.session: ALL``) therefore could not censor at all (ALL has no close) and had to fall
back to ``session_end: ignore``, which reports a flip from the next trading day as a resolution.

TRADING_DAY is the sessions reference-table row itself -- ``(open_ns, close_ns]`` of the trading
day the dataset defines -- so censoring and the session-day clustering agree on what a day is.
It is a censoring session only (never a population gate) and exists only on a calendar dataset.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000


@pytest.fixture(scope="module")
def sessions_df():
    from research_workflow.dataset_v2 import session_table
    return session_table(pd.Timestamp("2023-12-20", tz="UTC").value, pd.Timestamp("2024-02-10", tz="UTC").value)


@pytest.fixture(scope="module")
def golden():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    from research_workflow.host.interfaces import BarView
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    return bars, expected


@pytest.fixture
def calendar_datasets(tmp_path):
    """The golden datasets with SYN_A declaring a `sessions` reference table (a calendar dataset at
    compile time; the runtime session table is injected, exactly as the golden tests do)."""
    d = tmp_path / "datasets"; d.mkdir()
    for p in (GOLDEN / "datasets").glob("*.yaml"):
        shutil.copy2(p, d / p.name)
    body = yaml.safe_load((d / "SYN_A.yaml").read_text(encoding="utf-8"))
    body["reference_tables"] = ["sessions"]
    (d / "SYN_A.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return d


# --------------------------------------------------------------------------- session tables
def test_trading_day_window_is_the_sessions_row_itself(sessions_df):
    from research_workflow.sessions import session_windows
    rows = session_windows(sessions_df, "TRADING_DAY")
    assert len(rows) == len(sessions_df) and len(rows) > 20
    ordered = sessions_df.sort_values("open_ns")
    assert rows == [(int(a), int(b)) for a, b in zip(ordered["open_ns"], ordered["close_ns"])]
    rth = session_windows(sessions_df, "RTH")
    # the trading day contains its RTH window and closes at or after it
    for (o, c), (ro, rc) in zip(rows, rth):
        assert o < ro and rc <= c


def test_trading_day_close_censors_a_whole_tape_population(sessions_df):
    from research_workflow.sessions import CalendarSessionTable, SplitSessionTable, TRADING_DAY, build_session_table, session_windows
    day_rows = session_windows(sessions_df, TRADING_DAY)
    spec = {"kind": "calendar", "session": "ALL", "censor_session": TRADING_DAY, "rows": [], "rows_by_session": {TRADING_DAY: day_rows}}
    table = build_session_table(spec)
    assert isinstance(table, SplitSessionTable) and isinstance(table.censor, CalendarSessionTable) and table.censor.name == TRADING_DAY
    o, c = day_rows[5]
    mid = (o + c) // 2
    assert table.in_session(mid) and table.in_session(o - 1)          # ALL gates nothing
    assert table.session_close(mid) == c                               # censor at THIS trading day's close
    assert table.session_close(c) == c and table.session_close(c + 1) == day_rows[6][1]


def test_trading_day_has_no_close_on_a_legacy_dataset():
    from research_workflow.sessions import LegacySessionTable, SessionCloseUndefinedError, resolve_calendar_session_spec
    with pytest.raises(SessionCloseUndefinedError, match="LEGACY_TRADING_DAY"):
        LegacySessionTable("TRADING_DAY")
    # a legacy spec passes through resolve untouched (no calendar to derive from)
    assert resolve_calendar_session_spec({"kind": "legacy", "session": "RTH"}, ROOT) == {"kind": "legacy", "session": "RTH"}


# --------------------------------------------------------------------------- compiler
def _flip_spec(*, population_session: str, censor, session_end: str = "censor", horizon: str = "86400s") -> dict:
    body = yaml.safe_load((GOLDEN / "study_flip.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = "flip_td"
    body["population"]["session"] = population_session
    body["outcome"]["session_end"] = session_end
    body["outcome"]["horizon"] = horizon
    if censor is not None:
        body["outcome"]["session"] = censor
    return body


def _compile(tmp_path: Path, body: dict, datasets_dir: Path):
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    study = tmp_path / "studies" / body["study"]["id"]; study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return compile_study(load_spec(study), repo_root=ROOT, datasets_dir=datasets_dir, extra_bindings=SYNTHETIC_BINDINGS)


def test_compiler_admits_trading_day_censoring_on_a_calendar_dataset_only(tmp_path, calendar_datasets):
    out = _compile(tmp_path, _flip_spec(population_session="ALL", censor="TRADING_DAY"), calendar_datasets)
    assert out.ok, out.card()
    plan = out.plan.to_dict()
    assert plan["session"]["kind"] == "calendar" and plan["session"]["session"] == "ALL" and plan["session"]["censor_session"] == "TRADING_DAY"
    # the same declaration on the legacy (non-calendar) golden dataset is a typed semantic gap, not a runtime error
    out = _compile(tmp_path, _flip_spec(population_session="ALL", censor="TRADING_DAY"), GOLDEN / "datasets")
    assert not out.ok
    gaps = out.gaps.to_dict()["gaps"]
    assert any(g["where"] == "outcome.session" and g["kind"] == "SEMANTIC_DECISION_REQUIRED" and "TRADING_DAY" in g["message"] for g in gaps), gaps
    # TRADING_DAY is a censoring session, never a population gate
    out = _compile(tmp_path, _flip_spec(population_session="TRADING_DAY", censor="TRADING_DAY"), calendar_datasets)
    assert not out.ok
    gaps = out.gaps.to_dict()["gaps"]
    assert any(g["where"] == "population.session" and g["kind"] == "INVALID_PARAMETERIZATION" and "admitted: RTH, ETH, ALL" in g["message"] for g in gaps), gaps
    # an unknown name still names what IS admitted
    out = _compile(tmp_path, _flip_spec(population_session="ALL", censor="GLOBEX_DAY"), calendar_datasets)
    assert not out.ok
    gaps = out.gaps.to_dict()["gaps"]
    assert any(g["where"] == "outcome.session" and g["kind"] == "INVALID_PARAMETERIZATION" and "TRADING_DAY" in g["message"] for g in gaps), gaps
    # ALL with censoring still has no close: the message now points at TRADING_DAY
    out = _compile(tmp_path, _flip_spec(population_session="ALL", censor=None), calendar_datasets)
    assert not out.ok
    gaps = out.gaps.to_dict()["gaps"]
    assert any(g["where"] == "outcome.session" and g["kind"] == "AMBIGUOUS_TEMPORAL_SEMANTICS" and "TRADING_DAY" in g["message"] for g in gaps), gaps


# --------------------------------------------------------------------------- runtime (the gate)
def _run(tmp_path, golden, calendar_datasets, *, censor: str, session_end: str):
    from research_workflow.host_runner import run_plan_on_bars
    from research_workflow.sessions import TRADING_DAY, build_session_table
    bars, expected = golden
    rth = [(a * NS, b * NS) for a, b in expected["sessions"]]
    day = [(a - 3600 * NS, b + 3600 * NS) for a, b in rth]      # the trading day wraps its RTH window
    out = _compile(tmp_path, _flip_spec(population_session="ALL", censor=censor, session_end=session_end), calendar_datasets)
    assert out.ok, out.card()
    spec = {"kind": "calendar", "session": "ALL", "censor_session": censor, "rows": [],
            "rows_by_session": {"RTH": rth, TRADING_DAY: day}}
    obs = run_plan_on_bars(out.plan.to_dict(), bars, session_table=build_session_table(spec))["observations"]
    return obs, {c for _, c in rth}, {c for _, c in day}


def test_a_regime_open_at_the_trading_day_close_is_censored_not_resolved(tmp_path, golden, calendar_datasets):
    """The packet gate: the atlas declares population ALL + outcome.session TRADING_DAY + session_end censor."""
    from research_workflow.host.outcomes import LEGACY
    CENSORED, POSITIVE = LEGACY["CENSORED"], LEGACY["POSITIVE"]
    key = ["observation_ts", "regime_start_ns", "checkpoint_index"]
    td, rth_closes, day_closes = _run(tmp_path, golden, calendar_datasets, censor="TRADING_DAY", session_end="censor")
    assert len(td) > 0
    # a 24h horizon never fits inside a trading day: every row is CENSORED SESSION_END, stamped at the TRADING-DAY close
    assert set(td["disposition"]) == {CENSORED} and set(td["censor_reason"]) == {"SESSION_END"}
    assert set(td["session_close_ts"].astype("int64")) <= day_closes
    assert not (set(td["session_close_ts"].astype("int64")) & rth_closes)
    # the same census censored at the RTH close instead: a different (earlier) close on every row
    rt, _, _ = _run(tmp_path, golden, calendar_datasets, censor="RTH", session_end="censor")
    joined = td[key + ["session_close_ts"]].merge(rt[key + ["session_close_ts"]], on=key, suffixes=("_day", "_rth"))
    assert len(joined) == len(td) == len(rt)
    assert (joined["session_close_ts_day"] != joined["session_close_ts_rth"]).all()
    # a row inside RTH is censored at its own RTH close under RTH and later, at the day close, under TRADING_DAY;
    # a row after the RTH close (ALL emits it) is censored at the NEXT day's RTH close under RTH -- the wrong day
    in_rth = joined[joined["session_close_ts_rth"] >= joined["observation_ts"]]
    in_rth = in_rth[(in_rth["session_close_ts_day"] > in_rth["session_close_ts_rth"])]
    assert len(in_rth) > 0
    after_rth = joined[joined["session_close_ts_day"] < joined["session_close_ts_rth"]]
    assert len(after_rth) > 0 and (after_rth["session_close_ts_day"] >= after_rth["observation_ts"]).all()
    # `truncate`: a flip before the trading-day close resolves; a regime still open AT the close is censored there
    tt, _, _ = _run(tmp_path, golden, calendar_datasets, censor="TRADING_DAY", session_end="truncate")
    resolved = tt[tt["disposition"] == POSITIVE]; open_at_close = tt[tt["disposition"] == CENSORED]
    assert len(resolved) > 0 and len(open_at_close) > 0
    assert (resolved["flip_ts"] <= resolved["session_close_ts"]).all()
    at_close = open_at_close[open_at_close["censor_reason"] == "SESSION_END"]
    assert len(at_close) > 0 and (at_close["resolved_at_ts"] == at_close["session_close_ts"]).all() and at_close["flip_ts"].isna().all()
    assert set(at_close["session_close_ts"].astype("int64")) <= day_closes
    # nothing is imputed from the next trading day: no resolution lands after its own day close
    assert not ((tt["flip_ts"].notna()) & (tt["flip_ts"] > tt["session_close_ts"])).any()

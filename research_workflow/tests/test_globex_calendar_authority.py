"""Session-calendar authority for CME Globex equity-index futures (NQ/ES).

The Dataset V2 ``sessions`` reference table must be the product's Globex matching window -- the CME Globex
equity-index schedule (12:15 CT holiday-eve closes) -- never the trading-floor close calendar (12:00 CT), and
the builder must reconcile the declared close against the observed tape. Every fixture here is derived from the
calendar or synthetic; the real catalog is never opened. Dates are examples of a class of day (holiday eve,
holiday session, DST Monday, Good Friday, national day of mourning), not special cases in the implementation.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_workflow import dataset_v2 as dv2
from research_workflow.sessions import CalendarSessionTable, session_windows

CT = "America/Chicago"
NS = 1_000_000_000


def _ns(s: str) -> int:
    return int(pd.Timestamp(s, tz=CT).tz_convert("UTC").value)


def _ct(ns: int) -> str:
    return pd.Timestamp(int(ns), tz="UTC").tz_convert(CT).strftime("%Y-%m-%d %H:%M:%S")


def _row(s: pd.DataFrame, day: str) -> pd.Series:
    hit = s[s["session_date"].astype(str) == day]
    assert len(hit) == 1, f"expected exactly one session row for {day}, got {len(hit)}"
    return hit.iloc[0]


@pytest.fixture(scope="module")
def sessions_2024() -> pd.DataFrame:
    return dv2.session_table(_ns("2023-12-20 00:00:00"), _ns("2025-01-31 00:00:00"))


# --------------------------------------------------------------------------- #
# authority selection
# --------------------------------------------------------------------------- #
def test_globex_product_calendar_is_primary_and_floor_calendar_is_refused():
    assert dv2.CALENDAR_NAME == "CME Globex Equity"
    for floor in ("CME_Equity", "CMES"):
        with pytest.raises(dv2.DatasetV2Error, match="FLOOR_CALENDAR_NOT_AUTHORITATIVE_FOR_GLOBEX_FUTURES"):
            dv2.session_table(_ns("2024-07-01 00:00:00"), _ns("2024-07-05 00:00:00"), floor)
        with pytest.raises(dv2.DatasetV2Error, match="FLOOR_CALENDAR_NOT_AUTHORITATIVE_FOR_GLOBEX_FUTURES"):
            dv2.holiday_table(_ns("2024-07-01 00:00:00"), _ns("2024-07-05 00:00:00"), pd.DataFrame({"session_date": []}), floor)


# --------------------------------------------------------------------------- #
# early-close semantics (the defect: floor 12:00 CT vs Globex 12:15 CT)
# --------------------------------------------------------------------------- #
def test_equity_index_holiday_eve_early_close_is_1215_ct(sessions_2024):
    # holiday eves (Independence Day eve, day after Thanksgiving, Christmas Eve): 12:15 CT on Globex
    for day in ("2024-07-03", "2024-11-29", "2024-12-24"):
        r = _row(sessions_2024, day)
        assert bool(r["early_close"]) and _ct(r["close_ns"]) == f"{day} 12:15:00", day
    # holiday sessions (MLK, Presidents, Memorial, Juneteenth, Independence Day, Labor, Thanksgiving): 12:00 CT
    for day in ("2024-01-15", "2024-02-19", "2024-05-27", "2024-06-19", "2024-07-04", "2024-09-02", "2024-11-28"):
        r = _row(sessions_2024, day)
        assert bool(r["early_close"]) and _ct(r["close_ns"]) == f"{day} 12:00:00", day
    # nothing in range carries the floor calendar's 12:00 close on a holiday eve
    eves = sessions_2024[sessions_2024["session_date"].astype(str).isin(["2024-07-03", "2024-11-29", "2024-12-24"])]
    assert not any(_ct(c).endswith("12:00:00") for c in eves["close_ns"])


def test_2024_07_03_last_completed_1s_bar_is_consistent_with_tape(sessions_2024):
    """NQ/ES tape on an equity-index early-close day: last native 1s bar stamped 12:14:59 CT (interval open), which
    completes at 12:15:00 CT == close_ns. The bar completing one second later is outside the session."""
    r = _row(sessions_2024, "2024-07-03")
    close = int(r["close_ns"])
    assert close == _ns("2024-07-03 12:15:00") == pd.Timestamp("2024-07-03 17:15:00", tz="UTC").value   # 12:15 CDT
    last_bar_open = close - NS
    assert _ct(last_bar_open) == "2024-07-03 12:14:59"
    # raw-second expected window [open, close] contains the 12:14:59 stamp
    raw_windows = dv2.session_windows(r)
    assert raw_windows[-1][0] <= last_bar_open < raw_windows[-1][1] == close + NS
    # completed-bar attribution: ts_init of the last completed bar (== close) is in RTH; one second later is not
    rth = CalendarSessionTable(session_windows(sessions_2024, "RTH"), name="RTH")
    assert rth.in_session(last_bar_open + NS) is True
    assert rth.in_session(close + NS) is False
    # session-end censoring on the early-close day censors at 12:15 CT, not 15:15 CT and not 12:00 CT
    assert rth.session_close(_ns("2024-07-03 12:10:00")) == close
    assert rth.session_close(_ns("2024-07-03 12:05:00")) != _ns("2024-07-03 12:00:00")
    assert (_ns("2024-07-03 08:30:00"), close) in session_windows(sessions_2024, "RTH")
    # ETH post-close segment is empty on an early-close day (close precedes 15:15 CT); the pre-open segment exists
    eth = dict(session_windows(sessions_2024, "ETH"))
    assert eth[int(r["open_ns"])] == _ns("2024-07-03 08:30:00")
    assert _ns("2024-07-03 15:15:00") not in eth


def test_tape_reconciliation_rejects_floor_close_and_accepts_globex_close():
    """Synthetic tape dense through 12:14:59 CT on 2024-07-03 (what NQ/ES printed). A sessions table closing the day
    at 12:00 CT (floor calendar) fails the build; the Globex 12:15 CT close reconciles with zero past-close seconds."""
    s = dv2.session_table(_ns("2024-07-01 00:00:00"), _ns("2024-07-06 00:00:00"))
    r = _row(s, "2024-07-03")
    tape = np.arange(int(r["open_ns"]), _ns("2024-07-03 12:15:00"), NS, dtype=np.int64)          # last stamp 12:14:59
    out, summary = dv2.reconcile_sessions(tape, s)
    row = _row(out, "2024-07-03")
    assert int(row["tape_last_ns"]) == _ns("2024-07-03 12:14:59")
    assert int(row["tape_first_ns"]) == int(r["open_ns"])
    assert int(row["tape_past_close_seconds"]) == 0 and int(row["tape_short_of_close_seconds"]) == 1
    assert summary["sessions_with_tape_past_close"] == []
    assert "2024-07-02" in summary["sessions_without_tape"]                                          # no synthetic rows that day

    floor = s.copy()
    floor.loc[floor["session_date"].astype(str) == "2024-07-03", "close_ns"] = _ns("2024-07-03 12:00:00")
    with pytest.raises(dv2.DatasetV2Error, match="TAPE_EXCEEDS_DECLARED_CLOSE"):
        dv2.reconcile_sessions(tape, floor)

    # a single stray print after the close (the raw tape carries a few such seconds) is tolerated but reported
    stray = np.append(tape, _ns("2024-07-03 16:59:59"))
    _, summary2 = dv2.reconcile_sessions(stray, s)
    assert summary2["sessions_with_tape_past_close"] == [{"session_date": "2024-07-03", "declared_close_ct": "2024-07-03 12:15:00",
                                                          "tape_last_ct": "2024-07-03 16:59:59", "native_seconds_past_close": 1}]


# --------------------------------------------------------------------------- #
# normal close, ETH boundary, DST, holiday reopen
# --------------------------------------------------------------------------- #
def test_normal_day_close_and_eth_boundary(sessions_2024):
    r = _row(sessions_2024, "2024-03-11")
    assert _ct(r["open_ns"]) == "2024-03-10 17:00:00" and _ct(r["close_ns"]) == "2024-03-11 16:00:00" and not bool(r["early_close"])
    assert pd.isna(r["halt_start_ns"]) and r["calendar_override"] is None
    eth = session_windows(sessions_2024, "ETH")
    assert (int(r["open_ns"]), _ns("2024-03-11 08:30:00")) in eth                # pre-open segment starts at the Globex open
    assert (_ns("2024-03-11 15:15:00"), int(r["close_ns"])) in eth              # post-close segment ends at the Globex close
    assert (_ns("2024-03-11 08:30:00"), _ns("2024-03-11 15:15:00")) in session_windows(sessions_2024, "RTH")
    maint = dv2.maintenance_table(sessions_2024)
    m = maint[maint["session_date"].astype(str) == "2024-03-11"].iloc[0]
    assert m["kind"] == "daily_close" and _ct(m["start_ns"]) == "2024-03-11 16:00:01" and _ct(m["end_ns"]) == "2024-03-11 17:00:00"
    # the 16:00:00 CT close second is the last valid bar second; 16:00:01 is closure
    assert dv2.session_windows(r) == [(int(r["open_ns"]), int(r["close_ns"]) + NS)]
    eth_table = CalendarSessionTable(eth, name="ETH")
    assert eth_table.in_session(_ns("2024-03-11 16:00:00")) and not eth_table.in_session(_ns("2024-03-11 16:00:01"))
    assert eth_table.in_session(_ns("2024-03-11 17:00:01")) and not eth_table.in_session(_ns("2024-03-11 17:00:00"))


def test_dst_transitions_resolve_in_chicago_wall_clock(sessions_2024):
    # spring forward 2024-03-10: Friday open 17:00 CST == 23:00Z, Sunday open 17:00 CDT == 22:00Z, Monday close 16:00 CDT == 21:00Z
    assert int(_row(sessions_2024, "2024-03-08")["open_ns"]) == pd.Timestamp("2024-03-07 23:00", tz="UTC").value
    mon = _row(sessions_2024, "2024-03-11")
    assert int(mon["open_ns"]) == pd.Timestamp("2024-03-10 22:00", tz="UTC").value
    assert int(mon["close_ns"]) == pd.Timestamp("2024-03-11 21:00", tz="UTC").value
    # fall back 2024-11-03: Sunday open 17:00 CST == 23:00Z, Monday close 16:00 CST == 22:00Z
    mon = _row(sessions_2024, "2024-11-04")
    assert int(mon["open_ns"]) == pd.Timestamp("2024-11-03 23:00", tz="UTC").value
    assert int(mon["close_ns"]) == pd.Timestamp("2024-11-04 22:00", tz="UTC").value
    # early close in CDT and in CST
    assert int(_row(sessions_2024, "2024-07-03")["close_ns"]) == pd.Timestamp("2024-07-03 17:15", tz="UTC").value
    assert int(_row(sessions_2024, "2024-12-24")["close_ns"]) == pd.Timestamp("2024-12-24 18:15", tz="UTC").value
    # every session is exactly one Globex day: open on the prior calendar day at 17:00 CT
    opens_ct = pd.to_datetime(sessions_2024["open_ns"], utc=True).dt.tz_convert(CT)
    assert (opens_ct.dt.strftime("%H:%M:%S") == "17:00:00").all()
    assert ((pd.to_datetime(sessions_2024["session_date"]) - opens_ct.dt.tz_localize(None).dt.normalize()).dt.days == 1).all()


def test_holiday_reopen_and_holiday_table(sessions_2024):
    days = set(sessions_2024["session_date"].astype(str))
    # Good Friday 2024-03-29 (no employment-report session): closed; Thursday is a full session; Monday opens Sunday 17:00 CT
    assert "2024-03-29" not in days
    assert _ct(_row(sessions_2024, "2024-03-28")["close_ns"]) == "2024-03-28 16:00:00"
    assert _ct(_row(sessions_2024, "2024-04-01")["open_ns"]) == "2024-03-31 17:00:00"
    # Thanksgiving: Thursday 12:00 CT holiday session, Friday opens 17:00 CT and closes 12:15 CT, Monday opens Sunday 17:00 CT
    assert _ct(_row(sessions_2024, "2024-11-28")["close_ns"]) == "2024-11-28 12:00:00"
    fri = _row(sessions_2024, "2024-11-29")
    assert _ct(fri["open_ns"]) == "2024-11-28 17:00:00" and _ct(fri["close_ns"]) == "2024-11-29 12:15:00"
    assert _ct(_row(sessions_2024, "2024-12-02")["open_ns"]) == "2024-12-01 17:00:00"
    # Christmas: no 12-25 session; 12-26 opens 12-25 17:00 CT. New Year: no 01-01 session.
    assert "2024-12-25" not in days and "2025-01-01" not in days
    assert _ct(_row(sessions_2024, "2024-12-26")["open_ns"]) == "2024-12-25 17:00:00"
    hol = dv2.holiday_table(_ns("2024-01-01 00:00:00"), _ns("2025-01-31 00:00:00"), sessions_2024)
    assert set(hol["date"].astype(str)) == {"2024-01-01", "2024-03-29", "2024-12-25", "2025-01-01"}
    assert not hol["session_exists"].any()
    # maintenance kinds bracket the closures
    maint = dv2.maintenance_table(sessions_2024)
    kinds = dict(zip(maint["session_date"].astype(str), maint["kind"]))
    assert kinds["2024-03-28"] == "weekend" and kinds["2024-11-29"] == "weekend" and kinds["2024-12-24"] == "early_close_extended"


# --------------------------------------------------------------------------- #
# override table: CME Group published schedule over the pandas_market_calendars encoding
# --------------------------------------------------------------------------- #
def test_mourning_day_override_applies_and_records_tape_evidence(sessions_2024):
    r = _row(sessions_2024, "2025-01-09")
    assert _ct(r["close_ns"]) == "2025-01-09 08:30:00" and bool(r["early_close"])
    assert "Mourning" in str(r["calendar_override"])
    assert _ct(_row(sessions_2024, "2025-01-10")["open_ns"]) == "2025-01-09 17:00:00"
    entry = [e for e in dv2.load_calendar_overrides()["overrides"] if e["session_date"] == "2025-01-09"][0]
    assert {"NQ", "ES"} <= set(entry["tape"])
    # the raw encoding alone (diagnostics) models a full session -- the override is what restores the schedule
    raw = dv2.session_table(_ns("2025-01-05 00:00:00"), _ns("2025-01-12 00:00:00"), overrides_path=None)
    assert _ct(_row(raw, "2025-01-09")["close_ns"]) == "2025-01-09 16:00:00"


def test_override_table_is_well_formed_and_every_entry_is_live():
    doc = dv2.load_calendar_overrides()
    dates = [e["session_date"] for e in doc["overrides"]]
    assert len(dates) == len(set(dates)) and dates == sorted(dates)
    for e in doc["overrides"]:
        assert bool(e.get("closed", False)) != bool(e.get("market_close_ct"))
        assert e["reason"].strip() and {"NQ", "ES"} <= set(e["tape"])
        d = pd.Timestamp(e["session_date"])
        s = dv2.session_table(int((d - pd.Timedelta(days=5)).tz_localize("UTC").value), int((d + pd.Timedelta(days=5)).tz_localize("UTC").value))
        if e.get("closed"):
            assert e["session_date"] not in set(s["session_date"].astype(str))
        else:
            assert _ct(_row(s, e["session_date"])["close_ns"]) == f"{e['session_date']} {e['market_close_ct']}"


def test_redundant_or_malformed_override_fails_closed(tmp_path: Path):
    def write(entries):
        p = tmp_path / "ov.json"
        p.write_text(json.dumps({"overrides": entries}), encoding="utf-8")
        return p
    good_tape = {"NQ": "x", "ES": "x"}
    # redundant: the encoding already closes 2024-07-03 at 12:15 CT
    p = write([{"session_date": "2024-07-03", "market_close_ct": "12:15:00", "reason": "r", "tape": good_tape}])
    with pytest.raises(dv2.DatasetV2Error, match="CALENDAR_OVERRIDE_REDUNDANT"):
        dv2.session_table(_ns("2024-07-01 00:00:00"), _ns("2024-07-06 00:00:00"), overrides_path=p)
    # redundant: closing a day the encoding has no session for (a holiday)
    p = write([{"session_date": "2024-12-25", "closed": True, "reason": "r", "tape": good_tape}])
    with pytest.raises(dv2.DatasetV2Error, match="CALENDAR_OVERRIDE_REDUNDANT"):
        dv2.session_table(_ns("2024-12-20 00:00:00"), _ns("2024-12-28 00:00:00"), overrides_path=p)
    # malformed: both closed and a close time; missing tape evidence; duplicate dates
    for bad in ([{"session_date": "2024-07-03", "closed": True, "market_close_ct": "12:00:00", "reason": "r", "tape": good_tape}],
                [{"session_date": "2024-07-03", "market_close_ct": "12:00:00", "reason": "r"}],
                [{"session_date": "2024-07-03", "market_close_ct": "12:00:00", "reason": "r", "tape": good_tape}] * 2):
        with pytest.raises(dv2.DatasetV2Error, match="CALENDAR_OVERRIDES_MALFORMED"):
            dv2.load_calendar_overrides(write(bad))
    # a live override applies generically by date and is recorded on the row
    p = write([{"session_date": "2024-07-03", "market_close_ct": "12:00:00", "reason": "synthetic test override", "tape": good_tape}])
    s = dv2.session_table(_ns("2024-07-01 00:00:00"), _ns("2024-07-06 00:00:00"), overrides_path=p)
    r = _row(s, "2024-07-03")
    assert _ct(r["close_ns"]) == "2024-07-03 12:00:00" and r["calendar_override"] == "synthetic test override"
    assert _row(s, "2024-07-02")["calendar_override"] is None


# --------------------------------------------------------------------------- #
# pre-2021-06-28 halt: a Globex product rule, not the floor calendar's break columns
# --------------------------------------------------------------------------- #
def test_pre_2021_halt_is_a_product_rule():
    s = dv2.session_table(_ns("2021-02-25 00:00:00"), _ns("2021-07-01 00:00:00"))
    r = _row(s, "2021-03-01")
    assert _ct(r["halt_start_ns"]) == "2021-03-01 15:15:01" and _ct(r["halt_end_ns"]) == "2021-03-01 15:30:00"
    assert dv2.session_windows(r) == [(int(r["open_ns"]), int(r["halt_start_ns"])), (int(r["halt_end_ns"]), int(r["close_ns"]) + NS)]
    assert pd.isna(_row(s, "2021-05-31")["halt_start_ns"])           # 12:00 CT holiday session: no halt
    assert pd.isna(_row(s, "2021-06-28")["halt_start_ns"])           # halt removed from 2021-06-28
    assert not pd.isna(_row(s, "2021-06-25")["halt_start_ns"])       # last halt session
    eth_starts = {o for o, _ in session_windows(s, "ETH")}
    assert _ns("2021-03-01 15:30:00") in eth_starts and _ns("2021-03-01 15:15:00") not in eth_starts
    assert _ns("2021-06-28 15:15:00") in eth_starts

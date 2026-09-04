"""Dataset V2 builder: an immutable, native-only (never forward-filled) 1-second catalog with
calendar, holiday, early-close, maintenance, roll and gap reference tables.

    <catalog_root>/<SYM>_1S_V2/
        data/bar/<INSTRUMENT>-1-SECOND-LAST-EXTERNAL/<year>.parquet   native 1s rows only
        data/bar/<INSTRUMENT>-1-MINUTE-LAST-EXTERNAL/<year>.parquet   build-time aggregation of the SAME native
                                                                     seconds (closed=left, label=left; a minute
                                                                     exists iff >= 1 native second) -- see
                                                                     scripts/prove_bar_equivalence.py
        data/futures_contract/<INSTRUMENT>/...
        reference/{sessions,holidays,maintenance,rolls,gaps,out_of_calendar}.parquet
        build_manifest.json          sources (sha256, rows), rules, counts, reference-table digests
        dataset_manifest.json        research_workflow.roots logical digest over data/ (immutable identity)

5m is NOT materialized: it stays a runtime derivation from completed 1m bars (the equivalence proof
records why). V0 catalogs are never touched: the builder refuses any output path registered in
``backtests.nt_runtime.data_plan.PRODUCT_CATALOGS`` and refuses to write into an existing directory.

Session calendar authority (NQ/ES are Globex products): the ``sessions`` table is the CME Globex
equity-index product schedule (``CALENDAR_NAME``, corrected by ``calendars/cme_globex_equity_index_overrides.json``),
reconciled against the observed tape per session at build time (``reconcile_sessions``). The CME trading-floor
close calendar (``CME_Equity``: 12:00 CT holiday-eve closes while the Globex tape runs to 12:15 CT) is refused.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SECOND_NS = 1_000_000_000
MINUTE_NS = 60 * SECOND_NS
CHICAGO = "America/Chicago"
OLD_BREAK_END = date(2021, 6, 25)          # last session with the 15:15-15:30 CT halt (CME removed it 2021-06-28)
HALT_START_CT = time(15, 15, 0)            # pre-2021-06-28 daily equity-index maintenance halt (Globex product rule):
HALT_END_CT = time(15, 30, 0)              # 15:15:00 CT is the last valid second, matching resumes 15:30:00 CT
# Session authority for CME Globex equity-index futures (NQ/ES/YM/RTY):
#   PRIMARY   the CME Globex product-specific trading/holiday schedule. pandas_market_calendars' "CME Globex Equity"
#             is the machine-readable encoding consumed here (12:15 CT holiday-eve closes, 12:00 CT holiday sessions,
#             08:15 CT employment-report Good Fridays), corrected by the repo override table below where the encoding
#             disagrees with the published schedule (each entry carries its tape evidence).
#   SECONDARY the observed native tape, reconciled per session at build time (``reconcile_sessions``): a tape that
#             continues past a declared close is proof the calendar is wrong and fails the build.
#   NOT AUTHORITATIVE  the CME trading-floor close calendar ("CME_Equity": 12:00 CT holiday-eve closes while the
#             Globex equity-index tape runs to 12:15 CT). Refused for futures datasets.
CALENDAR_NAME = "CME Globex Equity"
FLOOR_CALENDARS = frozenset({"CME_Equity", "CMES", "CME_TradeDate"})
CALENDAR_OVERRIDES_PATH = Path(__file__).resolve().parent / "calendars" / "cme_globex_equity_index_overrides.json"
TAPE_PAST_CLOSE_TOLERANCE_SECONDS = 60     # native seconds strictly after close_ns a session may carry (stray prints) before the build fails
TAPE_SHORT_OF_CLOSE_REPORT_SECONDS = 1800  # sessions whose tape ends this far before close_ns are listed (not fatal: thin tape / raw gaps)
SCHEMA_VERSION = 3
RAW_COLUMNS = ["ts_event", "open", "high", "low", "close", "volume", "instrument_id", "symbol"]


class DatasetV2Error(RuntimeError):
    pass


@dataclass
class RawYear:
    year: str
    path: Path
    sha256: str
    rows: int
    first_ns: int
    last_ns: int
    instrument_ids: List[int] = field(default_factory=list)


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def raw_path(raw_dir: Path, symbol: str, year: str) -> Path:
    cands = [raw_dir / f"{symbol}_v0_1s_{year}.parquet", raw_dir / f"{symbol}_v0_1s_{year}_ytd.parquet"]
    for c in cands:
        if c.is_file():
            return c
    raise DatasetV2Error(f"RAW_YEAR_MISSING: {symbol} {year} (looked for {[c.name for c in cands]})")


def load_raw_year(path: Path, symbol: str) -> pd.DataFrame:
    """Native rows only. Refuses filled products, non-v0 symbols, unordered or duplicate seconds."""
    schema = pq.ParquetFile(path).schema_arrow
    if "is_fill" in schema.names:
        raise DatasetV2Error(f"FILLED_INPUT_REJECTED: {path} carries is_fill -- V2 is built from native raw years only")
    df = pd.read_parquet(path, columns=[c for c in RAW_COLUMNS if c != "ts_event"])
    if df.index.name != "ts_event":
        raise DatasetV2Error(f"RAW_INDEX_NOT_TS_EVENT: {path}")
    bad = sorted(set(df["symbol"].unique()) - {f"{symbol}.v.0"})
    if bad:
        raise DatasetV2Error(f"NON_V0_INPUT_REJECTED: {path} has {bad}")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    ts = df.index.asi8
    if len(ts) and (np.any(np.diff(ts) <= 0)):
        raise DatasetV2Error(f"RAW_NOT_STRICTLY_INCREASING: {path}")
    if len(ts) and np.any(ts % SECOND_NS):
        raise DatasetV2Error(f"RAW_NOT_SECOND_ALIGNED: {path}")
    return df.drop(columns=["symbol"])


# ---------------------------------------------------------------------------
# calendar tables
# ---------------------------------------------------------------------------

def load_calendar_overrides(path: Path = CALENDAR_OVERRIDES_PATH) -> Dict[str, Any]:
    """The repo override table (CME Group published schedule vs. the pandas_market_calendars encoding).
    Validated on load: unique dates, ``closed`` xor ``market_close_ct``, a reason and tape evidence per entry."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DatasetV2Error(f"CALENDAR_OVERRIDES_UNREADABLE: {path}: {exc}")
    entries = doc.get("overrides")
    if not isinstance(entries, list):
        raise DatasetV2Error(f"CALENDAR_OVERRIDES_MALFORMED: {path} has no 'overrides' list")
    seen: set = set()
    for e in entries:
        try:
            day = date.fromisoformat(str(e["session_date"]))
        except (KeyError, ValueError) as exc:
            raise DatasetV2Error(f"CALENDAR_OVERRIDES_MALFORMED: bad session_date in {e!r}: {exc}")
        if day in seen:
            raise DatasetV2Error(f"CALENDAR_OVERRIDES_MALFORMED: duplicate session_date {day}")
        seen.add(day)
        closed = bool(e.get("closed", False))
        if closed == bool(e.get("market_close_ct")):
            raise DatasetV2Error(f"CALENDAR_OVERRIDES_MALFORMED: {day} must declare exactly one of closed / market_close_ct")
        if not str(e.get("reason", "")).strip() or not isinstance(e.get("tape"), dict) or not e["tape"]:
            raise DatasetV2Error(f"CALENDAR_OVERRIDES_MALFORMED: {day} needs a reason and per-product tape evidence")
    return doc


def _ct_instant_ns(day: date, hms: str) -> int:
    h, m, s = (int(x) for x in str(hms).split(":"))
    return int(pd.Timestamp(day.year, day.month, day.day, h, m, s, tz=ZoneInfo(CHICAGO)).tz_convert("UTC").value)


def session_table(first_ns: int, last_ns: int, calendar_name: str = CALENDAR_NAME, *,
                  overrides_path: Optional[Path] = CALENDAR_OVERRIDES_PATH) -> pd.DataFrame:
    """One row per Globex trading session: open second, last valid close second (inclusive), early-close flag,
    the pre-2021-06-28 halt window (product rule), and the override that produced the row when one applied.

    The calendar is the CME Globex equity-index product schedule (``CALENDAR_NAME``); trading-floor calendars are
    refused (``FLOOR_CALENDAR_NOT_AUTHORITATIVE_FOR_GLOBEX_FUTURES``). Overrides from ``overrides_path`` (CME Group
    published schedule, tape-verified) are applied generically by session date; an override the encoding already
    agrees with is an error (``CALENDAR_OVERRIDE_REDUNDANT``) so the table cannot silently rot when the upstream
    package is corrected. Pass ``overrides_path=None`` to build the raw encoding (diagnostics only)."""
    import pandas_market_calendars as mcal
    if calendar_name in FLOOR_CALENDARS:
        raise DatasetV2Error(
            f"FLOOR_CALENDAR_NOT_AUTHORITATIVE_FOR_GLOBEX_FUTURES: {calendar_name!r} is a CME trading-floor / generic "
            f"calendar; NQ/ES session tables derive from the Globex product schedule ({CALENDAR_NAME!r})")
    tz = ZoneInfo(CHICAGO)
    first_ct = pd.Timestamp(first_ns, tz="UTC").tz_convert(tz)
    last_ct = pd.Timestamp(last_ns, tz="UTC").tz_convert(tz)
    cal = mcal.get_calendar(calendar_name)
    sched = cal.schedule(start_date=(first_ct.date() - timedelta(days=2)).isoformat(), end_date=(last_ct.date() + timedelta(days=2)).isoformat(), market_times="all")
    by_day: Dict[date, Dict[str, Any]] = {}
    for session_day, row in sched.iterrows():
        d = session_day.date()
        by_day[d] = {"session_date": d, "open_ns": int(row.market_open.value), "close_ns": int(row.market_close.value), "calendar_override": None}
    overrides = load_calendar_overrides(overrides_path)["overrides"] if overrides_path is not None else []
    lo_day, hi_day = first_ct.date() - timedelta(days=2), last_ct.date() + timedelta(days=2)
    for e in overrides:
        d = date.fromisoformat(str(e["session_date"]))
        if not (lo_day <= d <= hi_day):
            continue
        if e.get("closed"):
            if d not in by_day:
                raise DatasetV2Error(f"CALENDAR_OVERRIDE_REDUNDANT: {d} declared closed but the encoding has no session either")
            del by_day[d]
            continue
        close_ns = _ct_instant_ns(d, e["market_close_ct"])
        if d in by_day:
            if by_day[d]["close_ns"] == close_ns:
                raise DatasetV2Error(f"CALENDAR_OVERRIDE_REDUNDANT: {d} close {e['market_close_ct']} CT already encoded")
            by_day[d]["close_ns"] = close_ns
        else:
            if not e.get("market_open_ct"):
                raise DatasetV2Error(f"CALENDAR_OVERRIDE_MALFORMED: {d} adds a session the encoding lacks but has no market_open_ct")
            by_day[d] = {"session_date": d, "open_ns": _ct_instant_ns(d - timedelta(days=1), e["market_open_ct"]), "close_ns": close_ns}
        by_day[d]["calendar_override"] = str(e["reason"])
    rows = []
    for d in sorted(by_day):
        r = by_day[d]
        open_ns, close_ns = r["open_ns"], r["close_ns"]                    # the declared close second is itself a valid bar second
        if open_ns % SECOND_NS or close_ns % SECOND_NS:
            raise DatasetV2Error("CALENDAR_TIMESTAMP_NOT_SECOND_ALIGNED")
        if close_ns <= open_ns:
            raise DatasetV2Error(f"CALENDAR_SESSION_INVALID: {d} close_ns <= open_ns")
        close_ct = pd.Timestamp(close_ns, tz="UTC").tz_convert(tz)
        early = (close_ct.hour, close_ct.minute, close_ct.second) != (16, 0, 0)
        halt_start = halt_end = None
        if d <= OLD_BREAK_END:
            hs, he = _ct_instant_ns(d, HALT_START_CT.isoformat()), _ct_instant_ns(d, HALT_END_CT.isoformat())
            if open_ns < hs < he < close_ns:                                # an early close (12:xx CT) has no halt
                halt_start, halt_end = hs + SECOND_NS, he                   # 15:15:00 is valid; halt is (15:15:00, 15:30:00)
        rows.append({"session_date": d, "open_ns": open_ns, "close_ns": close_ns, "early_close": bool(early),
                     "halt_start_ns": halt_start, "halt_end_ns": halt_end, "calendar_override": r.get("calendar_override")})
    df = pd.DataFrame(rows, columns=["session_date", "open_ns", "close_ns", "early_close", "halt_start_ns", "halt_end_ns", "calendar_override"])
    df = df[(df["close_ns"] >= first_ns) & (df["open_ns"] <= last_ns)].reset_index(drop=True)
    return df


def reconcile_sessions(ts: np.ndarray, sessions: pd.DataFrame, *, tolerance_seconds: int = TAPE_PAST_CLOSE_TOLERANCE_SECONDS,
                       report_short_seconds: int = TAPE_SHORT_OF_CLOSE_REPORT_SECONDS) -> tuple[pd.DataFrame, Dict[str, Any]]:
    """SECONDARY authority: per-session observed tape boundaries. Every native second is attributed to the session
    whose open it follows (``open_ns <= t < next open_ns``). Adds ``tape_first_ns``, ``tape_last_ns``,
    ``tape_past_close_seconds`` (native seconds strictly after ``close_ns``) and ``tape_short_of_close_seconds``
    (``close_ns - tape_last_ns``). A session carrying more than ``tolerance_seconds`` native seconds after its declared
    close is proof the calendar closes too early (the floor-calendar 12:00 vs Globex 12:15 CT defect shows ~700 such
    seconds per holiday eve) and raises ``TAPE_EXCEEDS_DECLARED_CLOSE``; a tape ending early is only reported."""
    s = sessions.sort_values("open_ns").reset_index(drop=True)
    opens = s["open_ns"].to_numpy(dtype=np.int64)
    closes = s["close_ns"].to_numpy(dtype=np.int64)
    ts = np.asarray(ts, dtype=np.int64)
    idx = np.searchsorted(opens, ts, side="right") - 1
    # integer arithmetic throughout: ns epochs exceed float64's exact range
    first = np.zeros(len(s), dtype=np.int64)
    last = np.zeros(len(s), dtype=np.int64)
    past = np.zeros(len(s), dtype=np.int64)
    has = np.zeros(len(s), dtype=bool)
    valid = idx >= 0
    if valid.any():
        order = np.flatnonzero(valid)                       # ts is sorted, so sessions form contiguous runs
        sess_idx = idx[order]
        bounds = np.flatnonzero(np.diff(sess_idx)) + 1
        starts = np.concatenate(([0], bounds))
        ends = np.concatenate((bounds, [len(order)]))
        for a, b in zip(starts, ends):
            i = int(sess_idx[a])
            seg = ts[order[a]:order[b - 1] + 1]
            first[i], last[i], has[i] = int(seg[0]), int(seg[-1]), True
            past[i] = int(np.count_nonzero(seg > closes[i]))
    short = np.where(has, (closes - last) // SECOND_NS, 0)
    s["tape_first_ns"] = pd.array([int(v) if h else None for v, h in zip(first, has)], dtype="Int64")
    s["tape_last_ns"] = pd.array([int(v) if h else None for v, h in zip(last, has)], dtype="Int64")
    s["tape_past_close_seconds"] = past
    s["tape_short_of_close_seconds"] = pd.array([int(v) if h else None for v, h in zip(short, has)], dtype="Int64")

    def _ct(ns_val: int) -> str:
        return pd.Timestamp(int(ns_val), tz="UTC").tz_convert(CHICAGO).strftime("%Y-%m-%d %H:%M:%S")

    exceeds = [{"session_date": str(s.loc[i, "session_date"]), "declared_close_ct": _ct(closes[i]), "tape_last_ct": _ct(int(last[i])),
                "native_seconds_past_close": int(past[i])} for i in range(len(s)) if past[i] > 0]
    fatal = [e for e in exceeds if e["native_seconds_past_close"] > tolerance_seconds]
    if fatal:
        raise DatasetV2Error(f"TAPE_EXCEEDS_DECLARED_CLOSE: {len(fatal)} session(s) trade past the declared close by more than "
                             f"{tolerance_seconds} native seconds -- the session calendar is not the product's matching window: {fatal[:5]}")
    short_list = [{"session_date": str(s.loc[i, "session_date"]), "declared_close_ct": _ct(closes[i]), "tape_last_ct": _ct(int(last[i])),
                   "seconds_short_of_close": int(short[i])} for i in range(len(s)) if has[i] and short[i] > report_short_seconds]
    no_tape = [str(s.loc[i, "session_date"]) for i in range(len(s)) if not has[i]]
    summary = {"rule": "every native second is attributed to the session whose open precedes it; seconds strictly after close_ns count as past-close",
               "past_close_tolerance_native_seconds": int(tolerance_seconds), "short_of_close_report_seconds": int(report_short_seconds),
               "sessions_with_tape_past_close": exceeds, "sessions_tape_short_of_close": short_list, "sessions_without_tape": no_tape}
    return s, summary


def session_windows(sess: pd.Series) -> List[tuple[int, int]]:
    """Half-open [start, end) second windows in which native bars are expected for one session."""
    end = int(sess["close_ns"]) + SECOND_NS
    if sess["halt_start_ns"] is not None and not pd.isna(sess["halt_start_ns"]):
        return [(int(sess["open_ns"]), int(sess["halt_start_ns"])), (int(sess["halt_end_ns"]), end)]
    return [(int(sess["open_ns"]), end)]


def load_reference_tables(catalog_path: Path, declared: Sequence[str], reference_digest: Optional[str] = None) -> Dict[str, pd.DataFrame]:
    """Loads and fail-closed-verifies the declared reference tables of a V2 catalog against
    ``build_manifest.json``: every declared table must exist under ``<catalog>/reference/<name>.parquet``
    and its bytes must hash to the sha256 recorded in the manifest at build time. When ``reference_digest``
    is given (the DatasetSpec's aggregate digest) and ``declared`` is the full set the manifest built, the
    aggregate over the declared tables' sha256s must also match it. Fails closed: a missing file, a byte
    mismatch, or an aggregate mismatch all raise -- this function never silently returns a partial result."""
    catalog_path = Path(catalog_path)
    manifest_path = catalog_path / "build_manifest.json"
    if not manifest_path.is_file():
        raise DatasetV2Error(f"REFERENCE_TABLE_MISSING: {manifest_path} not found")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DatasetV2Error(f"REFERENCE_TABLE_MISSING: {manifest_path} is not parseable JSON: {exc}")
    if not isinstance(manifest, dict):
        raise DatasetV2Error(f"REFERENCE_TABLE_MISSING: {manifest_path} does not contain a JSON object")
    ref_manifest = manifest.get("reference_tables") or {}
    if not isinstance(ref_manifest, dict):
        raise DatasetV2Error(f"REFERENCE_TABLE_MISSING: {manifest_path} reference_tables is malformed")
    # W-3: declared must be a subset of what the catalog actually built -- a study cannot
    # declare a table the catalog never produced.
    undeclared_missing = sorted(set(declared) - set(ref_manifest))
    if undeclared_missing:
        raise DatasetV2Error(f"REFERENCE_TABLE_MISSING: declared {undeclared_missing} not present in {manifest_path} reference_tables")
    out: Dict[str, pd.DataFrame] = {}
    for name in declared:
        entry = ref_manifest.get(name)
        path = catalog_path / "reference" / f"{name}.parquet"
        if entry is None or not path.is_file():
            raise DatasetV2Error(f"REFERENCE_TABLE_MISSING: {name!r} not found under {catalog_path / 'reference'}")
        actual = _sha256(path)
        if actual != entry.get("sha256"):
            raise DatasetV2Error(f"REFERENCE_TABLE_CORRUPT: {name!r} sha256 {actual} != manifest {entry.get('sha256')}")
        out[name] = pd.read_parquet(path)
    if reference_digest is not None:
        # W-3: the DatasetSpec digest covers the FULL catalog manifest (this is exactly the
        # formula computed at build time -- see `build_reference_catalog`), never a
        # declared-subset aggregate. Declaring a strict subset of the catalog's reference
        # tables must not silently disarm this check: verify unconditionally against every
        # table the catalog build recorded, not only the ones this study reads.
        computed = hashlib.sha256(
            json.dumps({n: (ref_manifest.get(n) or {}).get("sha256") for n in sorted(ref_manifest)}, sort_keys=True).encode()
        ).hexdigest()
        if computed != reference_digest:
            raise DatasetV2Error(f"REFERENCE_DIGEST_MISMATCH: computed {computed} != declared {reference_digest}")
    return out


def holiday_table(first_ns: int, last_ns: int, sessions: pd.DataFrame, calendar_name: str = CALENDAR_NAME, *,
                  overrides_path: Optional[Path] = CALENDAR_OVERRIDES_PATH) -> pd.DataFrame:
    """Full-closure days of the Globex product schedule in range: the encoding's holidays plus override-closed
    sessions (Good Fridays without an employment-report session), with whether a session row exists anyway."""
    import pandas_market_calendars as mcal
    if calendar_name in FLOOR_CALENDARS:
        raise DatasetV2Error(f"FLOOR_CALENDAR_NOT_AUTHORITATIVE_FOR_GLOBEX_FUTURES: {calendar_name!r}")
    cal = mcal.get_calendar(calendar_name)
    hol = {h.date() for h in pd.DatetimeIndex(cal.holidays().holidays)}
    if overrides_path is not None:
        hol |= {date.fromisoformat(str(e["session_date"])) for e in load_calendar_overrides(overrides_path)["overrides"] if e.get("closed")}
    lo, hi = pd.Timestamp(first_ns, tz="UTC").date(), pd.Timestamp(last_ns, tz="UTC").date()
    days = sorted(h for h in hol if lo <= h <= hi)
    have = set(sessions["session_date"])
    return pd.DataFrame({"date": days, "weekday": [h.weekday() for h in days], "session_exists": [h in have for h in days]})


def maintenance_table(sessions: pd.DataFrame) -> pd.DataFrame:
    """Closures between consecutive sessions (daily 16:00-17:00 CT, weekends, holidays) plus in-session halts."""
    rows = []
    s = sessions.sort_values("open_ns").reset_index(drop=True)
    for i in range(len(s)):
        r = s.iloc[i]
        if r["halt_start_ns"] is not None and not pd.isna(r["halt_start_ns"]):
            rows.append({"start_ns": int(r["halt_start_ns"]), "end_ns": int(r["halt_end_ns"]), "kind": "pre_2021_halt", "session_date": r["session_date"]})
        if i + 1 < len(s):
            nxt = s.iloc[i + 1]
            start, end = int(r["close_ns"]) + SECOND_NS, int(nxt["open_ns"])
            hours = (end - start) / SECOND_NS / 3600.0
            kind = "daily_close" if hours <= 1.0 + 1e-9 else ("early_close_extended" if r["early_close"] and hours < 30 else ("weekend" if hours < 80 else "holiday_or_extended"))
            rows.append({"start_ns": start, "end_ns": end, "kind": kind, "session_date": r["session_date"]})
    return pd.DataFrame(rows, columns=["start_ns", "end_ns", "kind", "session_date"])


def roll_table(ts: np.ndarray, instrument_ids: np.ndarray, sessions: pd.DataFrame) -> pd.DataFrame:
    """Contract rolls of the volume-continuous series: every change of the databento instrument_id."""
    if len(ts) == 0:
        return pd.DataFrame(columns=["ts_ns", "prev_instrument_id", "next_instrument_id", "session_date"])
    idx = np.flatnonzero(np.diff(instrument_ids) != 0) + 1
    dates = _session_date_for(ts[idx], sessions)
    return pd.DataFrame({"ts_ns": ts[idx], "prev_instrument_id": instrument_ids[idx - 1], "next_instrument_id": instrument_ids[idx], "session_date": dates})


def _session_date_for(ts: np.ndarray, sessions: pd.DataFrame) -> List[Optional[date]]:
    opens = sessions["open_ns"].to_numpy()
    closes = sessions["close_ns"].to_numpy()
    out: List[Optional[date]] = []
    for t in ts:
        i = int(np.searchsorted(opens, t, side="right")) - 1
        out.append(sessions["session_date"].iloc[i] if i >= 0 and t <= closes[i] else None)
    return out


def gap_tables(ts: np.ndarray, sessions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(gaps, out_of_calendar, per-session coverage). Gaps are run-length encoded missing native seconds
    inside expected windows; out_of_calendar lists native seconds outside every window (kept in the
    catalog -- native rows take precedence over the generic calendar, as the dense product documents)."""
    gaps, cover = [], []
    in_window = np.zeros(len(ts), dtype=bool)
    for _, sess in sessions.iterrows():
        expected = native = 0
        for start, end in session_windows(sess):
            lo, hi = np.searchsorted(ts, start, side="left"), np.searchsorted(ts, end, side="left")
            in_window[lo:hi] = True
            present = ts[lo:hi]
            n_exp = (end - start) // SECOND_NS
            expected += n_exp
            native += len(present)
            # runs of missing seconds: boundaries of the present set inside [start, end)
            edges = np.concatenate(([start - SECOND_NS], present, [end]))
            d = np.diff(edges)
            run_idx = np.flatnonzero(d > SECOND_NS)
            for k in run_idx:
                g0 = int(edges[k]) + SECOND_NS
                g1 = int(edges[k + 1])
                gaps.append({"start_ns": g0, "end_ns": g1, "seconds": (g1 - g0) // SECOND_NS, "session_date": sess["session_date"]})
        cover.append({"session_date": sess["session_date"], "expected_seconds": int(expected), "native_seconds": int(native),
                      "coverage": (native / expected) if expected else None})
    ooc = pd.DataFrame({"ts_ns": ts[~in_window]})
    return (pd.DataFrame(gaps, columns=["start_ns", "end_ns", "seconds", "session_date"]), ooc, pd.DataFrame(cover))


# ---------------------------------------------------------------------------
# aggregation (the ONE build-time derivation; proven against V0 and an independent implementation)
# ---------------------------------------------------------------------------

def aggregate_minutes(df_1s: pd.DataFrame) -> pd.DataFrame:
    """closed=left, label=left, a minute exists iff >= 1 native second (identical to the V0 materializer rule)."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df_1s[list(agg)].resample("1min", label="left", closed="left").agg(agg).dropna()


def aggregate_minutes_independent(df_1s: pd.DataFrame) -> pd.DataFrame:
    """Second implementation via integer bucket keys (no pandas resample) for the equivalence proof."""
    ts = df_1s.index.asi8
    key = ts // MINUTE_NS * MINUTE_NS
    g = df_1s.groupby(key, sort=True)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(), "volume": g["volume"].sum()})
    out.index = pd.to_datetime(out.index, unit="ns", utc=True)
    out.index.name = "ts_event"
    return out


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def _instrument(symbol: str, venue: str, multiplier: str, price_increment: str, years: Sequence[str]):
    from nautilus_trader.model.instruments import FuturesContract
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    t = TestInstrumentProvider.future(symbol=symbol, underlying=symbol, venue=venue, exchange=venue)
    d = t.to_dict(t)
    y0, y1 = min(int(y[:4]) for y in years), max(int(y[:4]) for y in years)
    activation = pd.Timestamp(f"{y0}-01-01", tz="UTC")
    d["activation_ns"] = activation.value
    d["expiration_ns"] = pd.Timestamp(f"{y1 + 1}-01-01 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = activation.value
    d["multiplier"] = multiplier
    d["price_increment"] = price_increment
    d["price_precision"] = len(price_increment.split(".")[1]) if "." in price_increment else 0
    return FuturesContract.from_dict(d)


def _write_table(path: Path, df: pd.DataFrame) -> Dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path, compression="zstd")
    return {"path": path.name, "rows": int(len(df)), "sha256": _sha256(path)}


def product_facts(symbol: str) -> Dict[str, str]:
    from backtests.nt_runtime.data_plan import PRODUCT_CATALOGS
    prod = PRODUCT_CATALOGS.get(symbol.upper())
    if not prod:
        raise DatasetV2Error(f"UNKNOWN_PRODUCT: {symbol}")
    return {"venue": prod["venue"], "instrument_id": prod["instrument_id"], "multiplier": prod["multiplier"], "price_increment": prod["price_increment"],
            "v0_catalog_rel_path": prod["catalog_rel_path"], "v0_dataset_id": prod["dataset_id"]}


def build_dataset_v2(*, symbol: str, years: Sequence[str], raw_dir: Path, catalog_root: Path, repo_root: Path,
                     dataset_id: Optional[str] = None, calendar_name: str = CALENDAR_NAME, write_spec: bool = True,
                     progress: Optional[Any] = None) -> Dict[str, Any]:
    from nautilus_trader.model.data import BarType
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    from nautilus_trader.persistence.wranglers import BarDataWrangler
    from research_workflow.roots import write_dataset_manifest

    symbol = symbol.upper()
    dataset_id = dataset_id or f"{symbol}_1S_V2"
    facts = product_facts(symbol)
    out_dir = (Path(catalog_root) / dataset_id).resolve()
    for guard in (Path(repo_root) / facts["v0_catalog_rel_path"],):
        if out_dir == guard.resolve() or dataset_id == facts["v0_dataset_id"]:
            raise DatasetV2Error(f"V0_OVERWRITE_REFUSED: {out_dir}")
    if out_dir.exists():
        raise DatasetV2Error(f"OUTPUT_EXISTS_IMMUTABLE: {out_dir} (a V2 dataset is never rebuilt in place; choose a new dataset_id)")
    years = [str(y) for y in years]
    sources = [raw_path(Path(raw_dir), symbol, y) for y in years]

    log = progress or (lambda msg: None)
    out_dir.mkdir(parents=True)
    catalog = ParquetDataCatalog(str(out_dir))
    instrument = _instrument(symbol, facts["venue"], facts["multiplier"], facts["price_increment"], years)
    catalog.write_data([instrument])
    bt_1s = BarType.from_str(f"{instrument.id}-1-SECOND-LAST-EXTERNAL")
    bt_1m = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")

    raw_years: List[RawYear] = []
    all_ts: List[np.ndarray] = []
    all_ids: List[np.ndarray] = []
    stream_rows = {"1s": 0, "1m": 0}
    minute_check = {"years_compared": 0, "mismatching_minutes": 0}
    for year, path in zip(years, sources):
        log(f"load {path.name}")
        df = load_raw_year(path, symbol)
        raw_years.append(RawYear(year=year, path=path, sha256=_sha256(path), rows=int(len(df)), first_ns=int(df.index.asi8[0]), last_ns=int(df.index.asi8[-1]),
                                 instrument_ids=[int(v) for v in pd.unique(df["instrument_id"])]))
        all_ts.append(df.index.asi8.copy())
        all_ids.append(df["instrument_id"].to_numpy().copy())
        ohlcv = df[["open", "high", "low", "close", "volume"]]
        log(f"write 1s {year}")
        bars = BarDataWrangler(bar_type=bt_1s, instrument=instrument).process(ohlcv, ts_init_delta=SECOND_NS)
        catalog.write_data(bars)
        stream_rows["1s"] += len(bars)
        del bars
        m = aggregate_minutes(ohlcv)
        m2 = aggregate_minutes_independent(ohlcv)
        if not (len(m) == len(m2) and (m.index.asi8 == m2.index.asi8).all() and np.allclose(m.to_numpy(dtype=float), m2.to_numpy(dtype=float), rtol=0, atol=0)):
            raise DatasetV2Error(f"MINUTE_AGGREGATION_IMPLEMENTATIONS_DISAGREE: {year}")
        minute_check["years_compared"] += 1
        log(f"write 1m {year}")
        bars = BarDataWrangler(bar_type=bt_1m, instrument=instrument).process(m, ts_init_delta=MINUTE_NS)
        catalog.write_data(bars)
        stream_rows["1m"] += len(bars)
        del bars, df, ohlcv, m, m2

    ts = np.concatenate(all_ts)
    ids = np.concatenate(all_ids)
    if np.any(np.diff(ts) <= 0):
        raise DatasetV2Error("CROSS_YEAR_ORDER_VIOLATION")
    log("reference tables")
    sessions = session_table(int(ts[0]), int(ts[-1]), calendar_name)
    sessions, tape_reconciliation = reconcile_sessions(ts, sessions)        # SECONDARY authority: fails on tape past a declared close
    gaps, ooc, cover = gap_tables(ts, sessions)
    sessions = sessions.merge(cover, on="session_date", how="left")
    tables = {"sessions": sessions, "holidays": holiday_table(int(ts[0]), int(ts[-1]), sessions, calendar_name), "maintenance": maintenance_table(sessions),
              "rolls": roll_table(ts, ids, sessions), "gaps": gaps, "out_of_calendar": ooc}
    overrides_doc = load_calendar_overrides()
    applied_overrides = sessions.loc[sessions["calendar_override"].notna(), ["session_date", "calendar_override"]]
    closed_overrides = [e["session_date"] for e in overrides_doc["overrides"] if e.get("closed")
                        and pd.Timestamp(ts[0], tz="UTC").date() <= date.fromisoformat(e["session_date"]) <= pd.Timestamp(ts[-1], tz="UTC").date()]
    ref_dir = out_dir / "reference"
    ref_manifest = {name: _write_table(ref_dir / f"{name}.parquet", df) for name, df in tables.items()}
    reference_digest = hashlib.sha256(json.dumps({k: v["sha256"] for k, v in ref_manifest.items()}, sort_keys=True).encode()).hexdigest()

    builder_sha = _sha256(Path(__file__))
    manifest = {
        "schema_version": SCHEMA_VERSION, "dataset_id": dataset_id, "symbol": symbol, "instrument_id": str(instrument.id), "years": years,
        "rules": {"forward_fill": False, "native_rows_only": True, "out_of_calendar_native_rows": "kept (native precedence), listed in reference/out_of_calendar.parquet",
                  "1m": "build-time aggregation of the native 1s rows: closed=left, label=left, minute exists iff >= 1 native second; verified against an independent integer-bucket implementation per year",
                  "5m": "not materialized -- runtime derivation from completed 1m bars",
                  "calendar": {"name": calendar_name, "timezone": CHICAGO,
                               "authority": {"primary": "CME Globex equity-index product trading/holiday schedule (pandas_market_calendars encoding + repo override table)",
                                             "secondary": "observed native tape boundaries, reconciled per session (see tape_reconciliation)",
                                             "not_authoritative": "CME trading-floor close calendar (CME_Equity) -- refused for Globex futures"},
                               "package_version": importlib.metadata.version("pandas_market_calendars"), "close_second_inclusive": True,
                               "pre_2021_halt": {"last_session": OLD_BREAK_END.isoformat(), "halt_start_ct": HALT_START_CT.isoformat(), "halt_end_ct": HALT_END_CT.isoformat(),
                                                 "rule": "product rule on every full session through last_session; not applied on early-close days"},
                               "overrides": {"path": str(CALENDAR_OVERRIDES_PATH.relative_to(Path(__file__).resolve().parents[1])).replace("\\", "/"),
                                             "sha256": _sha256(CALENDAR_OVERRIDES_PATH),
                                             "applied": [{"session_date": str(r.session_date), "reason": r.calendar_override} for r in applied_overrides.itertuples()],
                                             "closed_sessions_removed": closed_overrides}},
                  "tape_reconciliation": tape_reconciliation},
        "sources": [{"year": r.year, "path": str(r.path), "sha256": r.sha256, "rows": r.rows, "first_ns": r.first_ns, "last_ns": r.last_ns, "instrument_ids": r.instrument_ids} for r in raw_years],
        "streams": {"1s": {"bar_type": str(bt_1s), "rows": stream_rows["1s"], "ts_init_delta_ns": SECOND_NS, "source": "external"},
                    "1m": {"bar_type": str(bt_1m), "rows": stream_rows["1m"], "ts_init_delta_ns": MINUTE_NS, "source": "external", "derivation": "build_time_from_native_1s"}},
        "minute_aggregation_cross_check": minute_check,
        "coverage": {"first_ns": int(ts[0]), "last_ns": int(ts[-1]), "native_rows": int(len(ts)), "sessions": int(len(sessions)),
                     "expected_seconds": int(sessions["expected_seconds"].sum()), "native_in_window_seconds": int(sessions["native_seconds"].sum()),
                     "gap_runs": int(len(gaps)), "gap_seconds": int(gaps["seconds"].sum()) if len(gaps) else 0, "max_gap_seconds": int(gaps["seconds"].max()) if len(gaps) else 0,
                     "out_of_calendar_rows": int(len(ooc)), "rolls": int(len(tables["rolls"])), "early_close_sessions": int(sessions["early_close"].sum()),
                     "holidays_in_range": int(len(tables["holidays"]))},
        "reference_tables": ref_manifest, "reference_digest": reference_digest, "builder": {"module": "research_workflow.dataset_v2", "sha256": builder_sha},
        "built_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    (out_dir / "build_manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    ds_manifest = write_dataset_manifest(out_dir, dataset_id, str(instrument.id))
    manifest["logical_digest"] = ds_manifest["logical_digest"]
    manifest["catalog_path"] = str(out_dir)
    if write_spec:
        manifest["spec_path"] = str(write_dataset_spec(Path(repo_root), manifest, facts))
    return manifest


def write_dataset_spec(repo_root: Path, manifest: Dict[str, Any], facts: Dict[str, str]) -> Path:
    import yaml
    inst = manifest["instrument_id"]
    first = pd.Timestamp(manifest["coverage"]["first_ns"], tz="UTC")
    last = pd.Timestamp(manifest["coverage"]["last_ns"], tz="UTC")
    spec = {
        "dataset_id": manifest["dataset_id"], "instrument_id": inst, "schema_version": SCHEMA_VERSION,
        "catalog_rel_path": None,
        "logical_digest": manifest["logical_digest"], "digest_method": "sha256(sorted(relpath,size,sha256(bytes)) under <catalog>/data)",
        "reference_digest": manifest["reference_digest"],
        "provenance": {"source": "databento *.v.0 raw yearly parquet (native rows, no fill)", "build_manifest": "build_manifest.json",
                       "builder_sha256": manifest["builder"]["sha256"], "sources": [{"year": s["year"], "sha256": s["sha256"], "rows": s["rows"]} for s in manifest["sources"]]},
        "rules": {"forward_fill": False, "native_rows_only": True,
                  "session_calendar": {"name": manifest["rules"]["calendar"]["name"], "authority": manifest["rules"]["calendar"]["authority"]["primary"],
                                       "overrides_sha256": manifest["rules"]["calendar"]["overrides"]["sha256"]}},
        "instrument": {"instrument_id": inst, "venue": facts["venue"], "multiplier": facts["multiplier"], "price_increment": facts["price_increment"]},
        "streams": {
            "1s": {"source": "external", "bar_type": manifest["streams"]["1s"]["bar_type"], "source_timestamp_semantics": "interval_open", "availability_rule": "interval_end", "ts_init_delta_ns": SECOND_NS},
            "1m": {"source": "external", "bar_type": manifest["streams"]["1m"]["bar_type"], "source_timestamp_semantics": "interval_open", "availability_rule": "interval_end", "ts_init_delta_ns": MINUTE_NS,
                   "derivation": "build_time_from_native_1s(closed=left,label=left,minute_exists_iff_native_second)", "equivalence_proof": "artifacts/platform_v2_do_soon/dataset_v2/equivalence_<SYMBOL>.json"},
            "5m": {"source": "derived", "external_catalog_stream": False, "derived_from": "1m", "aggregator": "runtime_complete_calendar_bucket"},
        },
        "reference_tables": sorted(manifest["reference_tables"]),
        "coverage": {"start": first.isoformat(), "end": last.isoformat(), "years": manifest["years"]},
    }
    path = repo_root / "research" / "datasets" / f"{manifest['dataset_id']}.yaml"
    header = ("# DatasetSpec authority for the immutable %s catalog (Dataset V2).\n# Built by research_workflow.dataset_v2 -- native 1s rows only, never forward-filled; 1m is a build-time\n"
              "# aggregation of the same seconds; 5m stays a runtime derivation. Reference tables live under <catalog>/reference/.\n" % manifest["dataset_id"])
    path.write_text(header + yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path

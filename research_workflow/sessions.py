"""Session tables the host gates on (integer intervals; built outside the host).

* :class:`LegacySessionTable` -- the project-canonical CT windows from
  ``utils.session_boundaries`` (weekday rule, no holidays).  This is the session
  semantics every sealed V0 study was collected under.
* :class:`CalendarSessionTable` -- explicit per-day (open_ns, close_ns] intervals from a
  dataset calendar table (V2 datasets: holidays and early closes included).
* :class:`AllSessionTable` -- no gating.
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

# Session vocabulary. RTH / ETH / ALL gate a population and censor an outcome on every dataset.
# TRADING_DAY is the calendar dataset's own session row -- the (open_ns, close_ns] tape of one
# trading day as the dataset's `sessions` reference table defines it (NQ_1S_V2_GLOBEX: the Globex
# trading day, holidays and early closes included). It is admitted as an outcome CENSORING session
# only, and only on a calendar dataset: a legacy weekday-rule dataset has no trading-day table, so
# it has no trading-day close to censor at (SessionCloseUndefinedError, and the compiler refuses it
# before the runtime is reached). Censoring at the trading-day close and clustering on the
# session day then agree on what a day is.
TRADING_DAY = "TRADING_DAY"
SESSION_NAMES = ("RTH", "ETH", "ALL")
CENSOR_SESSION_NAMES = SESSION_NAMES + (TRADING_DAY,)

# FILL_SCOPE is not a session and never gates or censors anything. It is the narrower interval set a
# `closed_window` derived stream may publish a zero-volume bar into: the trading day MINUS the declared
# maintenance halts and MINUS the declared data outages. A trading-day row is the whole session, halt
# included, because that is what censoring at the trading-day close means; filling a halt or a data
# hole with flat bars is a different question and gets a different table.
FILL_SCOPE = "FILL_SCOPE"


class SessionRowInvalidError(ValueError):
    """Raised when a sessions reference-table row is internally inconsistent (e.g.
    ``close_ns <= open_ns``) or overlaps the immediately preceding row."""
    pass


class SessionHaltInvalidError(ValueError):
    """Raised when a declared halt window on a sessions reference-table row is internally
    inconsistent (``halt_end_ns < halt_start_ns``) or ends before the RTH close it interrupts."""
    pass


class FillScopeUndeclaredError(ValueError):
    """Raised when a calendar session spec declares a data-outage threshold but carries no `gaps`
    reference table to identify an outage in.  A spec that declares NO threshold is not an error: it
    gets no fill scope at all, so nothing is filled and nothing is silently assumed."""
    pass


class SessionCloseUndefinedError(ValueError):
    """Raised when a session's close instant has no defined authority (e.g. ETH on a
    non-calendar/legacy dataset, which has no single contiguous daily window)."""
    pass


class AllSessionTable:
    name = "ALL"

    def in_session(self, ts_ns: int) -> bool:
        return True

    def session_close(self, ts_ns: int) -> Optional[int]:
        return None


class LegacySessionTable:
    """Half-open ``(open, close]`` attribution of completed-bar close timestamps."""

    def __init__(self, session: str = "RTH") -> None:
        from utils.session_boundaries import is_in_session, session_close_ns, resolve_session_window
        key = (session or "").strip().upper()
        if key == TRADING_DAY:
            raise SessionCloseUndefinedError(
                "SESSION_CLOSE_UNDEFINED_FOR_LEGACY_TRADING_DAY: TRADING_DAY is a calendar dataset's own session row; "
                "the legacy weekday-rule session table has no trading-day close.")
        if key not in SESSION_NAMES:
            resolve_session_window(key)  # raises UnknownSessionError
        self.name = key
        self._in = is_in_session
        self._close = session_close_ns

    def in_session(self, ts_ns: int) -> bool:
        return self._in(int(ts_ns), self.name)

    def session_close(self, ts_ns: int) -> Optional[int]:
        if self.name == "ALL":
            return None
        if self.name == "ETH":
            # ETH is the complement of RTH -- not a single contiguous daily window on the legacy
            # (weekday-rule) authority, so it has no well-defined close instant. Fail closed rather
            # than silently inheriting the RTH close.
            raise SessionCloseUndefinedError(
                "SESSION_CLOSE_UNDEFINED_FOR_LEGACY_ETH: ETH session-end censoring requires a "
                "calendar dataset (explicit per-day windows); the legacy weekday-rule session table "
                "has no single ETH close instant."
            )
        return int(self._close(int(ts_ns), self.name))


class CalendarSessionTable:
    """Explicit sessions: sorted ``(open_ns, close_ns)`` rows, one per trading day."""

    def __init__(self, rows: Sequence[Tuple[int, int]], name: str = "RTH") -> None:
        rows = sorted((int(a), int(b)) for a, b in rows)
        for (a, b), (c, _d) in zip(rows, rows[1:]):
            if b > c:
                raise ValueError("CALENDAR_SESSIONS_OVERLAP")
        self._opens = [a for a, _ in rows]
        self._closes = [b for _, b in rows]
        self.name = name

    def _row(self, ts_ns: int) -> Optional[int]:
        i = bisect_right(self._opens, int(ts_ns)) - 1
        return i if i >= 0 else None

    def in_session(self, ts_ns: int) -> bool:
        i = self._row(ts_ns)
        return i is not None and self._opens[i] < int(ts_ns) <= self._closes[i]

    def session_close(self, ts_ns: int) -> Optional[int]:
        """Close of the session whose (open, close] window contains ``ts_ns``; for a
        timestamp between sessions, the close of the next session (the one a forward
        window would run into) -- mirrors 'close of the calendar day' for in-session use."""
        i = self._row(ts_ns)
        if i is not None and int(ts_ns) <= self._closes[i]:
            return self._closes[i]
        j = (i + 1) if i is not None else 0
        return self._closes[j] if j < len(self._closes) else None

    def overlaps(self, open_ts: int, close_ts: int) -> bool:
        """True iff the bar window whose members close in ``(open_ts, close_ts]`` shares time with a row."""
        i = bisect_right(self._closes, int(open_ts))
        return i < len(self._opens) and self._opens[i] < int(close_ts)

    def next_row_after(self, ts_ns: int) -> Optional[Tuple[int, int]]:
        """The first row whose close is after ``ts_ns`` (the row a window starting at ``ts_ns`` runs into)."""
        i = bisect_right(self._closes, int(ts_ns))
        return (self._opens[i], self._closes[i]) if i < len(self._opens) else None


class _IntervalSet:
    """Disjoint, sorted half-open ``[start, end)`` intervals in bar-open-second space."""

    def __init__(self, intervals: Sequence[Tuple[int, int]]) -> None:
        rows = sorted((int(a), int(b)) for a, b in intervals if int(b) > int(a))
        for (_a, b), (c, _d) in zip(rows, rows[1:]):
            if b > c:
                raise ValueError("FILL_SCOPE_EXCLUSION_INTERVALS_OVERLAP")
        self._starts = [a for a, _ in rows]
        self._ends = [b for _, b in rows]

    def overlaps(self, open_ts: int, close_ts: int) -> bool:
        """True iff the window ``[open_ts, close_ts)`` shares a second with some interval."""
        i = bisect_right(self._starts, int(close_ts) - 1) - 1
        return i >= 0 and self._ends[i] > int(open_ts)


class FillScopeTable(CalendarSessionTable):
    """Where a ``closed_window`` derived stream may publish a zero-volume bar.

    ``rows`` are the dataset's trading-day rows with the declared maintenance halts and the declared
    data outages cut out; the cut-out intervals are kept alongside so a window that is NOT filled can
    be attributed to a reason (:meth:`skip_reason`) instead of inferred from a total.  A window that
    overlaps a halt or an outage AND still overlaps a surviving row is filled: it contains observable
    in-session time whose emptiness is a real quiet market."""

    def __init__(self, rows: Sequence[Tuple[int, int]], *, halts: Sequence[Tuple[int, int]] = (),
                 outages: Sequence[Tuple[int, int]] = (), name: str = FILL_SCOPE) -> None:
        super().__init__(rows, name=name)
        self._halts = _IntervalSet(halts)
        self._outages = _IntervalSet(outages)

    def skip_reason(self, open_ts: int, close_ts: int) -> str:
        """Why the window ``[open_ts, close_ts)`` is not filled: ``halt`` (a declared maintenance
        interval), ``outage`` (a declared data gap at or above the dataset's outage threshold), or
        ``closed`` (outside every trading day -- a weekend, a holiday, the nightly break).  A window
        overlapping both a halt and an outage is attributed to the halt: the scheduled closure is the
        primary reason, and the gaps table never covers halted seconds in the first place."""
        if self._halts.overlaps(open_ts, close_ts):
            return "halt"
        if self._outages.overlaps(open_ts, close_ts):
            return "outage"
        return "closed"


class SplitSessionTable:
    """Population gating from one session, outcome censoring from another (legacy episode
    studies emitted candidates in every session while censoring on the RTH close)."""

    def __init__(self, gate: object, censor: object) -> None:
        self.gate, self.censor = gate, censor
        self.name = f"{getattr(gate, 'name', '?')}/{getattr(censor, 'name', '?')}"

    def in_session(self, ts_ns: int) -> bool:
        return self.gate.in_session(ts_ns)

    def session_close(self, ts_ns: int) -> Optional[int]:
        return self.censor.session_close(ts_ns)


def build_session_table(spec: dict) -> object:
    """The population gate / outcome censor table.  A materialized calendar spec also carries two
    tables that never gate or censor: ``table.trading_day`` (the dataset's TRADING_DAY rows, halts
    included -- the censoring authority) and ``table.fill_scope`` (those rows minus the declared
    maintenance halts and minus the declared data outages -- what ``research_workflow.host.mux`` is
    allowed to fill with zero-volume bars)."""
    table = _build_gate_table(spec)
    rows = (spec.get("rows_by_session") or {}).get(TRADING_DAY)
    if rows is not None:
        table.trading_day = CalendarSessionTable([(r[0], r[1]) for r in rows], name=TRADING_DAY)
    fs = spec.get("fill_scope")
    if fs is not None:
        table.fill_scope = FillScopeTable([(r[0], r[1]) for r in fs["rows"]],
                                          halts=[(r[0], r[1]) for r in (fs.get("halts") or ())],
                                          outages=[(r[0], r[1]) for r in (fs.get("outages") or ())])
    return table


def _build_gate_table(spec: dict) -> object:
    censor_name = spec.get("censor_session")
    if censor_name and str(censor_name).upper() != str(spec.get("session", "RTH")).upper():
        base = {k: v for k, v in spec.items() if k not in ("censor_session", "rows", "rows_by_session")}
        rows_by_session = spec.get("rows_by_session") or {}
        gate_session = str(spec.get("session", "RTH")).upper()
        censor_session = str(censor_name).upper()
        gate_rows = rows_by_session.get(gate_session, spec.get("rows"))
        censor_rows = rows_by_session.get(censor_session, spec.get("rows"))
        gate = build_session_table({**base, "session": spec.get("session", "RTH"), **({"rows": gate_rows} if gate_rows is not None else {})})
        censor = build_session_table({**base, "session": censor_name, **({"rows": censor_rows} if censor_rows is not None else {})})
        return SplitSessionTable(gate, censor)
    kind = str(spec.get("kind", "legacy"))
    if kind == "legacy":
        return LegacySessionTable(str(spec.get("session", "RTH")))
    if kind == "all" or str(spec.get("session", "")).upper() == "ALL":
        return AllSessionTable()
    if kind == "calendar":
        return CalendarSessionTable([(r[0], r[1]) for r in spec["rows"]], name=str(spec.get("session", "RTH")))
    raise ValueError(f"UNKNOWN_SESSION_TABLE_KIND: {kind!r}")


# ---------------------------------------------------------------------------
# Calendar window derivation (dataset reference-table contract, platform-v2 packet D).
# ---------------------------------------------------------------------------
_CT = "America/Chicago"
_SECOND_NS = 1_000_000_000


def session_windows(sessions_df: Any, session: str, *, holidays_df: Any = None) -> list:
    """Explicit half-open ``(open_ns, close_ns]`` windows per trading day, derived from a
    dataset's ``sessions`` reference table (see ``research_workflow.dataset_v2.session_table``
    for the row schema: ``open_ns``, ``close_ns`` (inclusive close second), ``early_close``,
    ``halt_start_ns``, ``halt_end_ns``).

    RTH on a session day is ``(08:30:00 CT, min(15:15:00 CT, close_ns)]`` -- an early close
    tightens the window, it never widens it. ETH is the contiguous complement within that
    session's tape: the pre-open segment ``(open_ns, 08:30:00 CT]`` and the post-close segment
    ``(15:15:00 CT [or the pre-2021-06-28 halt end, 15:30 CT], close_ns]``. TRADING_DAY is the
    row itself, ``(open_ns, close_ns]`` -- the trading day the dataset defines, used as an outcome
    censoring session. A day the sessions table has no row for (holiday / non-session day)
    contributes no window. All wall-clock
    conversions are DST-safe (``zoneinfo``).
    """
    import pandas as pd
    from zoneinfo import ZoneInfo

    key = str(session).upper()
    if key not in {"RTH", "ETH", TRADING_DAY}:
        raise ValueError(f"UNSUPPORTED_CALENDAR_SESSION: {session!r} (only RTH/ETH/TRADING_DAY derive explicit windows)")
    tz = ZoneInfo(_CT)
    out: list = []
    prev_close_ns: Optional[int] = None
    prev_day = None
    for _, row in sessions_df.sort_values("open_ns").iterrows():
        open_ns, close_ns = int(row["open_ns"]), int(row["close_ns"])
        day = row["session_date"]
        if close_ns <= open_ns:
            raise SessionRowInvalidError(f"SESSION_ROW_INVALID: session_date={day} close_ns={close_ns} <= open_ns={open_ns}")
        if prev_close_ns is not None and open_ns < prev_close_ns:
            raise SessionRowInvalidError(
                f"SESSION_ROW_INVALID: session_date={day} open_ns={open_ns} overlaps prior row "
                f"(session_date={prev_day}) close_ns={prev_close_ns}")
        prev_close_ns, prev_day = close_ns, day
        # Use the row's own session_date label (the trading day), NOT the calendar date the raw
        # tape-open instant falls on -- the overnight tape open (e.g. 17:00 CT the prior evening)
        # belongs to THIS session's date, so deriving the day from open_ns would land RTH open on
        # the wrong calendar day.
        rth_open = int(pd.Timestamp(day.year, day.month, day.day, 8, 30, 0, tz=tz).tz_convert("UTC").value)
        rth_close_wall = int(pd.Timestamp(day.year, day.month, day.day, 15, 15, 0, tz=tz).tz_convert("UTC").value)
        rth_close = min(rth_close_wall, close_ns)
        halt_start = row.get("halt_start_ns")
        halt_end = row.get("halt_end_ns")
        has_halt_start = halt_start is not None and not pd.isna(halt_start)
        has_halt_end = halt_end is not None and not pd.isna(halt_end)
        if has_halt_start or has_halt_end:
            if has_halt_start and has_halt_end and int(halt_end) < int(halt_start):
                raise SessionHaltInvalidError(
                    f"SESSION_HALT_INVALID: session_date={day} halt_end_ns={int(halt_end)} < halt_start_ns={int(halt_start)}")
            if has_halt_end and int(halt_end) < rth_close:
                raise SessionHaltInvalidError(
                    f"SESSION_HALT_INVALID: session_date={day} halt_end_ns={int(halt_end)} < rth_close={rth_close} "
                    "(halt cannot end before the RTH close it interrupts)")
        if key == TRADING_DAY:
            # the trading day IS the row: its whole (open_ns, close_ns] tape, halts included
            out.append((open_ns, close_ns))
            continue
        if key == "RTH":
            if rth_open < rth_close:
                out.append((rth_open, rth_close))
            continue
        # ETH
        pre = (open_ns, rth_open)
        halt_end = row.get("halt_end_ns")
        post_start = int(halt_end) if halt_end is not None and not pd.isna(halt_end) else rth_close_wall
        post = (post_start, close_ns)
        if pre[0] < pre[1]:
            out.append(pre)
        if post[0] < post[1]:
            out.append(post)
    return out


def _subtract_intervals(rows: list, cuts: Sequence[Tuple[int, int]]) -> list:
    """``rows`` (sorted, disjoint ``[open, close)``) minus ``cuts`` (sorted, disjoint). A cut spanning
    several rows is applied to each of them; a cut wholly outside every row changes nothing."""
    cuts = sorted((int(a), int(b)) for a, b in cuts if int(b) > int(a))
    out: list = []
    i = 0
    for a, b in rows:
        start = a
        while i < len(cuts) and cuts[i][1] <= start:
            i += 1
        j = i
        while j < len(cuts) and cuts[j][0] < b:
            cut_start, cut_end = cuts[j]
            if cut_start > start:
                out.append((start, min(cut_start, b)))
            start = max(start, cut_end)
            if start >= b:
                break
            j += 1
        if start < b:
            out.append((start, b))
    return out


def fill_scope_windows(sessions_df: Any, *, gaps_df: Any = None, outage_gap_seconds: Optional[int] = None) -> tuple:
    """``(rows, halts, outages)`` -- the closed-window zero-volume fill scope of a V2 calendar dataset.

    ``rows`` are the TRADING_DAY rows with two things cut out:

    * **declared maintenance halts** (``sessions.halt_start_ns``/``halt_end_ns``; the pre-2021-06-28
      15:15-15:30 CT equity-index halt, 372 of them on NQ).  A TRADING_DAY row is the whole session
      *including* the halt, so without this every halted 15 minutes received a full set of flat bars
      on every derived timeframe, every day, for two years -- suppressing ATR and freezing EMAs.
    * **declared data outages**: runs of the dataset's ``gaps`` reference table at or above
      ``outage_gap_seconds``.  A data hole is not a quiet market; filling it makes an outage
      indistinguishable from a calm session.  The threshold is the dataset's declaration
      (``rules.outage_gap_seconds``), because "how long is too long to be quiet" is a property of the
      tape: on NQ the quiet-market maximum in a clean year is 299 s (2023) and 119 s (2022), while
      every genuine hole is >= 7200 s.  Every empty window is inside *some* gap run by construction
      (native rows only, 19.2 M runs, median 2 s), so an unthresholded subtraction would be
      ``empty_window: none``, not a fix.

    Intervals are half-open ``[start, end)`` in bar-open-second space: ``halt_start_ns`` is the first
    halted second and ``halt_end_ns`` the first second that trades again; a gap run ``[start_ns,
    end_ns)`` likewise ends at the next second the tape actually carries."""
    halts: list = []
    for _, row in sessions_df.sort_values("open_ns").iterrows():
        hs, he = row.get("halt_start_ns"), row.get("halt_end_ns")
        if hs is None or he is None or _isna(hs) or _isna(he):
            continue
        # The cut starts one second BEFORE the declared halt_start_ns. That column marks the first
        # fully halted second under an inclusive-last-valid-second convention, so the second before it
        # (15:15:00 CT) is nominally valid -- but the product halts AT 15:15:00 CT, no bar has ever been
        # observed in it (0 of 372 halted NQ sessions), and this repo's own session authority already
        # excludes it: session_windows(..., "RTH") ends at 15:15:00 exclusive and the ETH post-close
        # segment resumes at halt_end_ns. Cutting from halt_start_ns would leave exactly one straddling
        # window per timeframe fillable -- at 15m, a single flat bar standing for the whole halt.
        halts.append((int(hs) - _SECOND_NS, int(he)))
    outages: list = []
    if outage_gap_seconds is not None and gaps_df is not None and len(gaps_df):
        big = gaps_df[gaps_df["seconds"] >= int(outage_gap_seconds)].sort_values("start_ns")
        outages = [(int(r["start_ns"]), int(r["end_ns"])) for _, r in big.iterrows()]
    rows = [(int(a), int(b)) for a, b in session_windows(sessions_df, TRADING_DAY)]
    return _subtract_intervals(_subtract_intervals(rows, halts), outages), sorted(halts), sorted(outages)


def _isna(v: Any) -> bool:
    import pandas as pd
    return bool(pd.isna(v))


def resolve_calendar_session_spec(session_spec: Mapping[str, Any], repo_root: Any) -> Dict[str, Any]:
    """Materializes the ``CalendarSessionTable`` row(s) for a compiled ``kind: calendar`` session
    spec by resolving the declared dataset, loading its reference tables with fail-closed hash
    verification (``dataset_v2.load_reference_tables``), and deriving RTH/ETH windows from the
    ``sessions`` table. ``legacy``/``all`` specs pass through unchanged."""
    spec: Dict[str, Any] = dict(session_spec)
    if spec.get("kind") != "calendar" or spec.get("rows") is not None:
        return spec  # already materialized (test hook) or not a calendar spec
    from research_workflow import dataset_v2
    from research_workflow.roots import resolve_dataset

    resolved = resolve_dataset(spec["dataset"], repo_root)
    declared = list(spec.get("reference_tables") or [])
    tables = dataset_v2.load_reference_tables(resolved.catalog_path, declared, spec.get("reference_digest"))
    sessions_df = tables["sessions"]
    # TRADING_DAY is always materialized: it is the censoring authority and the base of the fill scope.
    needed = {str(spec.get("session", "RTH")).upper(), str(spec.get("censor_session") or spec.get("session", "RTH")).upper(), TRADING_DAY}
    rows_by_session: Dict[str, list] = {}
    for name in sorted(needed):
        if name in ("RTH", "ETH", TRADING_DAY):
            rows_by_session[name] = session_windows(sessions_df, name, holidays_df=tables.get("holidays"))
    spec["rows_by_session"] = rows_by_session
    spec["rows"] = rows_by_session.get(str(spec.get("session", "RTH")).upper(), [])
    spec["reference_row_counts"] = {name: int(len(df)) for name, df in tables.items()}
    # The zero-volume fill scope: trading days minus declared halts minus declared data outages.
    # No declared outage rule means NO FILL SCOPE, not a wider one: `build_session_table` attaches
    # nothing, and a stream declaring `zero_volume_in_trading_day` is then refused by the mux
    # (TRADING_DAY_CALENDAR_ABSENT) instead of filling data holes with flat bars. The compiler refuses
    # that combination up front; this is the runtime half of the same gate, and it is also what lets a
    # plan sealed before the rule existed (no fill, `complete_bucket`) replay untouched.
    outage_seconds = spec.get("outage_gap_seconds")
    if outage_seconds is None:
        spec["fill_scope"] = None
        return spec
    if "gaps" not in tables:
        raise FillScopeUndeclaredError(
            "FILL_SCOPE_GAPS_TABLE_ABSENT: 'outage_gap_seconds' is declared but the dataset's 'gaps' "
            "reference table is not among reference_tables, so no outage can be identified")
    fill_rows, halts, outages = fill_scope_windows(sessions_df, gaps_df=tables.get("gaps"),
                                                  outage_gap_seconds=outage_seconds)
    spec["fill_scope"] = {"rows": fill_rows, "halts": halts, "outages": outages,
                          "outage_gap_seconds": int(outage_seconds)}
    return spec


__all__ = ["AllSessionTable", "LegacySessionTable", "CalendarSessionTable", "SplitSessionTable", "FillScopeTable",
           "build_session_table", "session_windows", "fill_scope_windows", "resolve_calendar_session_spec",
           "SessionCloseUndefinedError", "TRADING_DAY", "FILL_SCOPE", "SESSION_NAMES", "CENSOR_SESSION_NAMES",
           "SessionRowInvalidError", "SessionHaltInvalidError", "FillScopeUndeclaredError"]

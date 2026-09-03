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


class SessionRowInvalidError(ValueError):
    """Raised when a sessions reference-table row is internally inconsistent (e.g.
    ``close_ns <= open_ns``) or overlaps the immediately preceding row."""
    pass


class SessionHaltInvalidError(ValueError):
    """Raised when a declared halt window on a sessions reference-table row is internally
    inconsistent (``halt_end_ns < halt_start_ns``) or ends before the RTH close it interrupts."""
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
        if key not in {"RTH", "ETH", "ALL"}:
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
    ``(15:15:00 CT [or the pre-2021-06-28 halt end, 15:30 CT], close_ns]``. A day the sessions
    table has no row for (holiday / non-session day) contributes no window. All wall-clock
    conversions are DST-safe (``zoneinfo``).
    """
    import pandas as pd
    from zoneinfo import ZoneInfo

    key = str(session).upper()
    if key not in {"RTH", "ETH"}:
        raise ValueError(f"UNSUPPORTED_CALENDAR_SESSION: {session!r} (only RTH/ETH derive explicit windows)")
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
    needed = {str(spec.get("session", "RTH")).upper(), str(spec.get("censor_session") or spec.get("session", "RTH")).upper()}
    rows_by_session: Dict[str, list] = {}
    for name in sorted(needed):
        if name in ("RTH", "ETH"):
            rows_by_session[name] = session_windows(sessions_df, name, holidays_df=tables.get("holidays"))
    spec["rows_by_session"] = rows_by_session
    spec["rows"] = rows_by_session.get(str(spec.get("session", "RTH")).upper(), [])
    spec["reference_row_counts"] = {name: int(len(df)) for name, df in tables.items()}
    return spec


__all__ = ["AllSessionTable", "LegacySessionTable", "CalendarSessionTable", "SplitSessionTable", "build_session_table",
           "session_windows", "resolve_calendar_session_spec", "SessionCloseUndefinedError",
           "SessionRowInvalidError", "SessionHaltInvalidError"]

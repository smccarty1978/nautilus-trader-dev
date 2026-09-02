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
from typing import Optional, Sequence, Tuple


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
        return int(self._close(int(ts_ns), "RTH"))


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
        gate = build_session_table({k: v for k, v in spec.items() if k != "censor_session"})
        censor = build_session_table({**{k: v for k, v in spec.items() if k != "censor_session"}, "session": censor_name})
        return SplitSessionTable(gate, censor)
    kind = str(spec.get("kind", "legacy"))
    if kind == "legacy":
        return LegacySessionTable(str(spec.get("session", "RTH")))
    if kind == "all" or str(spec.get("session", "")).upper() == "ALL":
        return AllSessionTable()
    if kind == "calendar":
        return CalendarSessionTable([(r[0], r[1]) for r in spec["rows"]], name=str(spec.get("session", "RTH")))
    raise ValueError(f"UNKNOWN_SESSION_TABLE_KIND: {kind!r}")


__all__ = ["AllSessionTable", "LegacySessionTable", "CalendarSessionTable", "SplitSessionTable", "build_session_table"]

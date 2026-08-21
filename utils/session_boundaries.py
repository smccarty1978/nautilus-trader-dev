"""Authoritative Chicago Session Boundary Invariants & Classifier.
================================================================

Timezone: America/Chicago
Session Definitions:
  - RTH (Regular Trading Hours): 08:30:00 CT to 15:15:00 CT
  - ETH (Extended Trading Hours): Outside RTH

Close-Timestamped Bar Attribution Invariant:
--------------------------------------------
For bars labeled at completed CLOSE time $T$:
  - 1-Minute Bar:
    - 08:30:00 CT close represents [08:29:00, 08:30:00) -> ETH (pre-open).
    - 08:31:00 CT close represents [08:30:00, 08:31:00) -> First complete RTH bar.
    - 15:15:00 CT close represents [15:14:00, 15:15:00) -> Final complete RTH bar.
    - 15:16:00 CT close represents [15:15:00, 15:16:00) -> ETH (post-close).

  - 1-Second Bar:
    - 08:30:00 CT close represents [08:29:59, 08:30:00) -> ETH.
    - 08:30:01 CT close represents [08:30:00, 08:30:01) -> First RTH second.
    - 15:15:00 CT close represents [15:14:59, 15:15:00) -> Final RTH second.
    - 15:15:01 CT close represents [15:15:00, 15:15:01) -> ETH.
"""

from __future__ import annotations

import datetime
from typing import List, Sequence, Tuple, Union
import numpy as np
import pandas as pd
import pytz

CT = pytz.timezone("America/Chicago")

# ---------------------------------------------------------------------------
# The single authoritative session window definition.
#
# These constants exist because `strategies/flip_prediction_collector.py` carried
# THREE different inline session boundaries at once: the OHLCV accumulator used
# 08:30-15:15, the candidate emission gate used `510 <= minute_of_day < 900`
# (08:30-15:00), and the `is_rth` context feature used `hour < 15` (08:30-15:00).
# The population contract said only `session: "RTH"`, which cannot arbitrate between
# them. Anything asking "is this RTH?" must import from here rather than re-deriving
# a boundary inline.
#
# 08:30-15:15 CT is the project-canonical RTH window (AGENTS.md, "Session Definitions").
# ---------------------------------------------------------------------------
RTH_START = datetime.time(8, 30, 0)
RTH_END = datetime.time(15, 15, 0)

SESSION_WINDOWS = {
    "RTH": (RTH_START, RTH_END),
    "ETH": None,   # the complement of RTH; not a single contiguous daily window
    "ALL": None,   # no session restriction
}


class SessionBoundaryViolation(AssertionError):
    """Raised when a boundary timestamp is misattributed."""
    pass


class UnknownSessionError(ValueError):
    """Raised when a study declares a session this module cannot resolve."""
    pass


def resolve_session_window(session: str) -> Tuple[datetime.time, datetime.time]:
    """Resolves a declared session name to explicit CT open/close times.

    Fails closed on an unknown name: a session the runtime cannot resolve must never
    silently degrade to "no restriction", which would widen the study population.
    """
    key = (session or "").strip().upper()
    if key not in SESSION_WINDOWS:
        raise UnknownSessionError(
            f"UNKNOWN_SESSION: {session!r} is not a resolvable session. Known: "
            f"{sorted(SESSION_WINDOWS)}"
        )
    window = SESSION_WINDOWS[key]
    if window is None:
        raise UnknownSessionError(
            f"SESSION_NOT_A_CONTIGUOUS_WINDOW: {key!r} has no single daily open/close window. "
            f"Only 'RTH' defines one."
        )
    return window


def _to_ct(ts_ns: int) -> pd.Timestamp:
    return pd.Timestamp(int(ts_ns), tz="UTC").tz_convert(CT)


def is_in_session(ts_ns: int, session: str = "RTH") -> bool:
    """Is a completed-bar close timestamp (ns, UTC) inside the declared session?

    Uses the same half-open ``(start, end]`` attribution as the classifiers above: a bar
    closing exactly at the open belongs to the period *before* the open.
    """
    key = (session or "").strip().upper()
    if key == "ALL":
        return True
    if key == "ETH":
        return not is_in_session(ts_ns, "RTH")
    start, end = resolve_session_window(key)
    ts = _to_ct(ts_ns)
    t = ts.time()
    return (t > start) and (t <= end) and (ts.weekday() < 5)


def session_close_ns(ts_ns: int, session: str = "RTH") -> int:
    """Nanosecond UTC timestamp of the session close on the CT calendar day of ``ts_ns``.

    This is what makes ``session_end_censoring`` computable: a candidate whose forward
    horizon extends past this instant cannot be resolved from in-session data alone.
    """
    _start, end = resolve_session_window(session)
    ts = _to_ct(ts_ns)
    close_ct = ts.normalize() + pd.Timedelta(
        hours=end.hour, minutes=end.minute, seconds=end.second
    )
    return int(close_ct.tz_convert("UTC").value)


def is_rth_completed_bar_1m(ts: Union[pd.Timestamp, datetime.datetime, int]) -> bool:
    """Classifies a completed 1m bar (timestamped at CLOSE) as RTH or ETH.

    RTH 1m bars have completed close timestamps in (08:30:00, 15:15:00] CT.
    """
    if isinstance(ts, (int, np.integer)):
        ts = pd.to_datetime(ts, unit="ns", utc=True).tz_convert(CT)
    elif isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize("America/Chicago")
        else:
            ts = ts.tz_convert(CT)
    elif isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            ts = CT.localize(ts)
        else:
            ts = ts.astimezone(CT)

    # Time of day
    t = ts.time()
    rth_start = datetime.time(8, 30, 0)
    rth_end = datetime.time(15, 15, 0)

    # A 1m bar closing at exactly 08:30:00 was formed during 08:29:00-08:30:00 (ETH).
    # The first 1m RTH bar closes at 08:31:00.
    return (t > rth_start) and (t <= rth_end) and (ts.weekday() < 5)


def is_rth_completed_bar_1s(ts: Union[pd.Timestamp, datetime.datetime, int]) -> bool:
    """Classifies a completed 1s bar (timestamped at CLOSE) as RTH or ETH.

    RTH 1s bars have completed close timestamps in (08:30:00, 15:15:00] CT.
    """
    if isinstance(ts, (int, np.integer)):
        ts = pd.to_datetime(ts, unit="ns", utc=True).tz_convert(CT)
    elif isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize("America/Chicago")
        else:
            ts = ts.tz_convert(CT)
    elif isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            ts = CT.localize(ts)
        else:
            ts = ts.astimezone(CT)

    t = ts.time()
    rth_start = datetime.time(8, 30, 0)
    rth_end = datetime.time(15, 15, 0)

    return (t > rth_start) and (t <= rth_end) and (ts.weekday() < 5)


def verify_session_attribution_invariants(
    classify_fn_1m,
    classify_fn_1s,
) -> Tuple[bool, List[str]]:
    """Verifies that 1m and 1s classification functions strictly obey session boundary invariants."""
    errors = []

    # 1m boundary tests
    # 08:30:00 CT close -> ETH (False)
    ts_0830 = pd.Timestamp("2026-01-05 08:30:00", tz="America/Chicago")
    if classify_fn_1m(ts_0830) is not False:
        errors.append(f"1m bar at 08:30:00 CT close misclassified as RTH (must be ETH)")

    # 08:31:00 CT close -> RTH (True)
    ts_0831 = pd.Timestamp("2026-01-05 08:31:00", tz="America/Chicago")
    if classify_fn_1m(ts_0831) is not True:
        errors.append(f"1m bar at 08:31:00 CT close misclassified as ETH (must be RTH)")

    # 15:15:00 CT close -> RTH (True)
    ts_1515 = pd.Timestamp("2026-01-05 15:15:00", tz="America/Chicago")
    if classify_fn_1m(ts_1515) is not True:
        errors.append(f"1m bar at 15:15:00 CT close misclassified as ETH (must be RTH)")

    # 15:16:00 CT close -> ETH (False)
    ts_1516 = pd.Timestamp("2026-01-05 15:16:00", tz="America/Chicago")
    if classify_fn_1m(ts_1516) is not False:
        errors.append(f"1m bar at 15:16:00 CT close misclassified as RTH (must be ETH)")

    # 1s boundary tests
    ts_1s_083000 = pd.Timestamp("2026-01-05 08:30:00", tz="America/Chicago")
    if classify_fn_1s(ts_1s_083000) is not False:
        errors.append(f"1s bar at 08:30:00 CT close misclassified as RTH (must be ETH)")

    ts_1s_083001 = pd.Timestamp("2026-01-05 08:30:01", tz="America/Chicago")
    if classify_fn_1s(ts_1s_083001) is not True:
        errors.append(f"1s bar at 08:30:01 CT close misclassified as ETH (must be RTH)")

    ts_1s_151500 = pd.Timestamp("2026-01-05 15:15:00", tz="America/Chicago")
    if classify_fn_1s(ts_1s_151500) is not True:
        errors.append(f"1s bar at 15:15:00 CT close misclassified as ETH (must be RTH)")

    ts_1s_151501 = pd.Timestamp("2026-01-05 15:15:01", tz="America/Chicago")
    if classify_fn_1s(ts_1s_151501) is not False:
        errors.append(f"1s bar at 15:15:01 CT close misclassified as RTH (must be ETH)")

    return (len(errors) == 0), errors

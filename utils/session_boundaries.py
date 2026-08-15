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
from typing import Sequence, Tuple, Union
import numpy as np
import pandas as pd
import pytz

CT = pytz.timezone("America/Chicago")


class SessionBoundaryViolation(AssertionError):
    """Raised when a boundary timestamp is misattributed."""
    pass


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

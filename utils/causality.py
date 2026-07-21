"""Causality helpers — preventing higher-timeframe (HTF) lookahead.

The recurring lookahead bug:
  - HTF bar `i` has ts_event = OPEN time, physically closes at
    ts_event + bucket_size_ns
  - At decision_ts T, we want the LATEST HTF bar whose close <= T
  - The wrong pattern is `searchsorted(htf_open_times, T) - 1` which
    returns the bar with OPEN <= T, even if that bar hasn't closed yet
  - That leaks the bar's full H/L/C into a moment when only its open
    was actually known

Use the helpers in this module instead. The single rule:

    Eligible HTF bars at T satisfy htf_close_time <= T.

Never select by `htf_open_time <= T`.

For audit trail, every HTF feature read should also produce a
`FeatureTimestampAudit` entry that proves
`feature_bar_close_ts <= decision_ts`.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
import numpy as np


def latest_completed_bar_index(
    close_times: np.ndarray,
    decision_ts: int,
) -> int:
    """Return index of the latest HTF bar whose CLOSE time <=
    decision_ts, or -1 if none.

    `close_times` MUST be the bars' close times (not open). For a
    1m bar with ts_event = 09:00 and bucket = 60s, close_time =
    09:01. For a 5m bar at 09:00, close_time = 09:05. NT's
    `bar.ts_init` is the canonical close timestamp.

    Use this in place of every `searchsorted(open_times, T) - 1`.
    """
    idx = int(np.searchsorted(close_times, decision_ts,
                                side="right")) - 1
    return idx


def htf_close_times_from_opens(
    open_times: np.ndarray,
    bucket_size_ns: int,
) -> np.ndarray:
    """Convert HTF bar open-time array into close-time array by
    adding the bucket size. Use when you have open times but not
    NT-style ts_init."""
    return open_times + bucket_size_ns


# Convenience constants for common bucket sizes
BUCKET_NS_1S = 1_000_000_000
BUCKET_NS_5S = 5 * BUCKET_NS_1S
BUCKET_NS_30S = 30 * BUCKET_NS_1S
BUCKET_NS_1M = 60 * BUCKET_NS_1S
BUCKET_NS_5M = 5 * BUCKET_NS_1M
BUCKET_NS_15M = 15 * BUCKET_NS_1M


@dataclass
class FeatureTimestampAudit:
    """Per-feature evidence that the source bar had closed by
    decision_ts. Append one of these every time you read a feature
    from an HTF bar. Run `assert_causal()` to fail loudly on
    violation.
    """
    feature_name: str
    feature_source_tf: str            # e.g. "5m", "1s", "5s"
    feature_bar_open_ts: int
    feature_bar_close_ts: int
    decision_ts: int

    @property
    def causal(self) -> bool:
        return self.feature_bar_close_ts <= self.decision_ts

    def assert_causal(self) -> None:
        if not self.causal:
            raise CausalityViolation(
                f"NON-CAUSAL feature read: "
                f"feature={self.feature_name} "
                f"source_tf={self.feature_source_tf} "
                f"bar_open_ts={self.feature_bar_open_ts} "
                f"bar_close_ts={self.feature_bar_close_ts} "
                f"decision_ts={self.decision_ts} "
                f"(close - decision = "
                f"{self.feature_bar_close_ts - self.decision_ts} ns)"
            )


class CausalityViolation(AssertionError):
    """Raised when a feature is read from a bar that hadn't closed
    by decision time."""


def audit_feature_lookups(
    audits: Sequence[FeatureTimestampAudit],
    raise_on_violation: bool = True,
) -> dict:
    """Audit a batch of feature reads. Returns summary dict; if
    raise_on_violation=True (default), raises on the first violation.
    """
    n = len(audits)
    violations = [a for a in audits if not a.causal]
    if violations and raise_on_violation:
        violations[0].assert_causal()
    return {
        "n_total": n,
        "n_violations": len(violations),
        "first_violation": violations[0] if violations else None,
        "violation_max_ns": (
            max(a.feature_bar_close_ts - a.decision_ts
                for a in violations) if violations else 0),
    }

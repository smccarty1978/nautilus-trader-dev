"""CompletedBarRegistry — single source of MTF truth.

Stores the latest *completed* bar state per timeframe. Updated only
when a bar close fires from the corresponding RegimeStateEngine.
Read-only after that until the next close.

Hard invariant on every snapshot:

    state.close_ts <= decision_ts   for all stored timeframes

Violation raises CausalityViolation immediately. No exceptions.

This module is the central air-gap. No feature anywhere else in the
strategy may bypass it to read raw bars.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import sys
from pathlib import Path

# utils path (relative to repo root)
_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from utils.causality import (  # noqa: E402
    CausalityViolation,
    FeatureTimestampAudit,
)

SUPPORTED_TIMEFRAMES = ("30s", "1m", "3m", "5m")


@dataclass(frozen=True)
class CompletedBarState:
    """Snapshot of one timeframe's most recently CLOSED bar.

    All fields are determined at the moment of bar close. Frozen so
    no caller can mutate state after registry stores it.
    """
    timeframe: str
    open_ts: int          # bar OPEN ts (ns since epoch)
    close_ts: int         # bar CLOSE ts (= open_ts + bucket_size_ns)
    open: float
    high: float
    low: float
    close: float
    volume: float
    regime: int           # +1 / -1 / 0 (uninit)
    bars_in_regime: int   # consecutive bars in current regime
    atr: float            # Wilder ATR computed at this bar's close
    # EMAs that gate the regime (for downstream feature use)
    ema3_h: float
    ema9_h: float
    ema3_l: float
    ema9_l: float


class CompletedBarRegistry:
    """Holds latest CompletedBarState per timeframe.

    `update(tf, state)` — called by RegimeStateEngine on bar close.
    `get(tf)` — returns latest state or None.
    `audit_provenance(decision_ts)` — raises CausalityViolation if
        any stored state has close_ts > decision_ts. Called BEFORE
        every snapshot.
    `audit_records(decision_ts)` — returns list of
        FeatureTimestampAudit for downstream provenance dumps.
    """

    def __init__(self, supported_timeframes: tuple = SUPPORTED_TIMEFRAMES):
        # Default preserves legacy behavior (collector_v2 passes nothing →
        # the canonical 4 TFs). A caller may widen the allowed set (e.g. to
        # include "5s") without affecting any other consumer.
        self._supported: tuple = tuple(supported_timeframes)
        self._state: dict[str, CompletedBarState] = {}
        self._n_updates: dict[str, int] = {tf: 0
                                                for tf in self._supported}

    # ---- Mutators ----

    def update(self, timeframe: str, state: CompletedBarState) -> None:
        if timeframe not in self._supported:
            raise ValueError(
                f"Unsupported timeframe: {timeframe!r}; "
                f"supported = {self._supported}")
        if state.timeframe != timeframe:
            raise ValueError(
                f"State.timeframe={state.timeframe!r} does not "
                f"match key {timeframe!r}")
        # Monotonicity: each update must advance close_ts
        prev = self._state.get(timeframe)
        if prev is not None and state.close_ts <= prev.close_ts:
            raise ValueError(
                f"Non-monotonic update for {timeframe!r}: "
                f"prev close_ts={prev.close_ts}, "
                f"new close_ts={state.close_ts}")
        self._state[timeframe] = state
        self._n_updates[timeframe] += 1

    # ---- Readers ----

    def get(self, timeframe: str) -> Optional[CompletedBarState]:
        return self._state.get(timeframe)

    def all_states(self) -> dict[str, CompletedBarState]:
        return dict(self._state)

    def n_updates(self, timeframe: str) -> int:
        return self._n_updates.get(timeframe, 0)

    # ---- Provenance audit (HARD INVARIANT) ----

    def audit_provenance(self, decision_ts: int) -> None:
        """Raise CausalityViolation if any stored state has
        close_ts > decision_ts. Called before every snapshot."""
        for tf, state in self._state.items():
            if state.close_ts > decision_ts:
                raise CausalityViolation(
                    f"PROVENANCE VIOLATION at decision_ts="
                    f"{decision_ts}: timeframe={tf} "
                    f"close_ts={state.close_ts} "
                    f"(close_ts - decision_ts = "
                    f"{state.close_ts - decision_ts} ns). "
                    f"Bar had not closed by decision time.")

    def audit_records(
        self, decision_ts: int,
    ) -> list[FeatureTimestampAudit]:
        """Return per-timeframe FeatureTimestampAudit records.
        Useful for emitting provenance dumps alongside snapshots."""
        out: list[FeatureTimestampAudit] = []
        for tf, state in self._state.items():
            out.append(FeatureTimestampAudit(
                feature_name=f"regime_{tf}",
                feature_source_tf=tf,
                feature_bar_open_ts=state.open_ts,
                feature_bar_close_ts=state.close_ts,
                decision_ts=decision_ts,
            ))
        return out

    # ---- Diagnostics ----

    def __repr__(self) -> str:
        bits = []
        for tf in self._supported:
            s = self._state.get(tf)
            if s is None:
                bits.append(f"{tf}=<empty>")
            else:
                bits.append(
                    f"{tf}=close_ts={s.close_ts} "
                    f"regime={s.regime} bars={s.bars_in_regime}")
        return ("CompletedBarRegistry(" + ", ".join(bits) + ")")

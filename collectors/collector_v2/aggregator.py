"""TimeframeAggregator — 1s bars → 30s/1m/3m/5m bucket completions.

The aggregator owns one bucket per timeframe. On each 1s bar:

  1. Determine the 1s bar's bucket id for each TF
     (bucket_id = floor(ts_event / bucket_size_ns))
  2. If the new 1s bar is in a different bucket than the current
     open one for that TF → CLOSE the previous bucket (which fires
     the engine's on_bar_closed callback, which writes the
     CompletedBarState to the registry)
  3. Add this 1s bar to the new bucket

Crucially: a bucket is closed only by the arrival of a bar in the
NEXT bucket. The bucket's data is final at close — no peeking at
in-progress bars allowed.

Bucket boundaries are aligned to UTC epoch (00:00:00 UTC). For NQ
data this gives clean alignment to clock minutes/hours.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional


# Bucket sizes in nanoseconds
BUCKET_NS_5S = 5 * 1_000_000_000
BUCKET_NS_30S = 30 * 1_000_000_000
BUCKET_NS_1M = 60 * 1_000_000_000
BUCKET_NS_3M = 3 * 60 * 1_000_000_000
BUCKET_NS_5M = 5 * 60 * 1_000_000_000

TIMEFRAME_TO_BUCKET_NS = {
    "5s": BUCKET_NS_5S,
    "30s": BUCKET_NS_30S,
    "1m": BUCKET_NS_1M,
    "3m": BUCKET_NS_3M,
    "5m": BUCKET_NS_5M,
}


@dataclass
class _OpenBucket:
    """Mutable in-progress bucket. Promoted to a CompletedBarState
    by the RegimeStateEngine when the next-bucket bar arrives."""
    bucket_id: int
    open_ts: int           # bar OPEN ts (= bucket_id * bucket_size)
    close_ts: int          # bar CLOSE ts (= open_ts + bucket_size)
    open: float
    high: float
    low: float
    close: float
    volume: float
    expected_count: int
    observed_event_ts: set[int]

    def absorb(self, event_ts: int, bar_h: float, bar_l: float, bar_c: float,
               bar_v: float) -> None:
        """Add a 1s bar's data into this bucket."""
        if bar_h > self.high:
            self.high = bar_h
        if bar_l < self.low:
            self.low = bar_l
        self.close = bar_c
        self.volume += bar_v
        self.observed_event_ts.add(event_ts)

    @property
    def is_complete(self) -> bool:
        """True only when every expected one-second member is present once."""
        if len(self.observed_event_ts) != self.expected_count:
            return False
        return (min(self.observed_event_ts) == self.open_ts
                and max(self.observed_event_ts) == self.close_ts - 1_000_000_000)


@dataclass
class _OpenMinuteBucket:
    """Five-minute bucket whose members are completed one-minute parents."""
    bucket_id: int
    open_ts: int
    close_ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    observed_open_ts: set[int]

    def absorb(self, open_ts: int, high: float, low: float, close: float, volume: float) -> None:
        self.high = max(self.high, high)
        self.low = min(self.low, low)
        self.close = close
        self.volume += volume
        self.observed_open_ts.add(open_ts)

    @property
    def is_complete(self) -> bool:
        return self.observed_open_ts == set(range(self.open_ts, self.close_ts, BUCKET_NS_1M))


# Type for "bucket completed" callback. Receives:
#   timeframe (e.g. "5m"), open_bucket (_OpenBucket about to be closed)
BucketClosedCb = Callable[[str, _OpenBucket], None]


class TimeframeAggregator:
    """Aggregates 1s bars into per-timeframe bucket completions.

    Construct with a callback to fire on each bucket close:

        agg = TimeframeAggregator(on_bucket_closed=cb)
        agg.on_1s_bar(ts_event, open, high, low, close, volume)

    The callback is called with (timeframe, _OpenBucket) at the
    moment the previous bucket closes (i.e., when the FIRST 1s bar
    of the next bucket arrives). The aggregator does NOT close the
    final partial bucket; that data is discarded for safety.
    """

    def __init__(
        self,
        on_bucket_closed: BucketClosedCb,
        timeframes=("30s", "1m", "3m", "5m"),
    ):
        self._cb = on_bucket_closed
        self._tfs = tuple(timeframes)
        self._open_buckets: dict[str, Optional[_OpenBucket]] = {
            tf: None for tf in self._tfs}
        self._incomplete_close_ts: dict[str, list[int]] = {tf: [] for tf in self._tfs}

    def consume_incomplete_close_ts(self, timeframe: str) -> list[int]:
        """Return and clear buckets discarded for incomplete 1s coverage."""
        out = self._incomplete_close_ts[timeframe]
        self._incomplete_close_ts[timeframe] = []
        return out

    def on_1s_bar(
        self, ts_event: int, open_: float, high: float, low: float,
        close: float, volume: float,
    ) -> None:
        completions = []
        for tf in self._tfs:
            completed = self._on_1s_for_tf(tf, ts_event, open_, high, low, close, volume)
            if completed is not None:
                completions.append((tf, completed))
                
        if not completions:
            return
            
        # Sort completions:
        # 1. By completed.close_ts ascending
        # 2. If close_ts is equal, by timeframe size descending (macro first)
        tf_priority = {"5m": 0, "3m": 1, "1m": 2, "30s": 3, "5s": 4}
        completions.sort(key=lambda x: (x[1].close_ts, tf_priority.get(x[0], 99)))
        
        for tf, completed in completions:
            self._cb(tf, completed)

    def finalize_through(self, available_ns: int) -> None:
        """Publish buckets whose close is known by ``available_ns``.

        A completed 1s bar with open/event timestamp ``T-1s`` becomes available
        at ``T``.  Without this explicit availability boundary, a 5m bucket
        ending at ``T`` would be delayed until the next bar arrives, even though
        its final constituent bar is already complete.  This method never opens
        or reads a forming bucket: it only promotes an existing bucket after its
        declared close timestamp is at or before the caller's decision time.
        """
        completions = []
        for tf, current in self._open_buckets.items():
            if current is not None and current.close_ts <= available_ns:
                if current.is_complete:
                    completions.append((tf, current))
                else:
                    self._incomplete_close_ts[tf].append(current.close_ts)
                self._open_buckets[tf] = None
        tf_priority = {"5m": 0, "3m": 1, "1m": 2, "30s": 3, "5s": 4}
        completions.sort(key=lambda x: (x[1].close_ts, tf_priority.get(x[0], 99)))
        for tf, completed in completions:
            self._cb(tf, completed)

    def _on_1s_for_tf(
        self, tf: str, ts_event: int, op: float, h: float, l: float,
        c: float, v: float,
    ) -> Optional[_OpenBucket]:
        bucket_size = TIMEFRAME_TO_BUCKET_NS[tf]
        bucket_id = ts_event // bucket_size
        cur = self._open_buckets[tf]

        if cur is None:
            # First-ever 1s for this TF — start bucket
            self._open_buckets[tf] = _OpenBucket(
                bucket_id=bucket_id,
                open_ts=bucket_id * bucket_size,
                close_ts=(bucket_id + 1) * bucket_size,
                open=op, high=h, low=l, close=c, volume=v,
                expected_count=bucket_size // 1_000_000_000,
                observed_event_ts={ts_event},
            )
            return None

        if bucket_id == cur.bucket_id:
            # Same bucket — absorb
            cur.absorb(ts_event, h, l, c, v)
            return None

        # New bucket arrived → CLOSE previous, fire callback,
        # start new bucket
        if bucket_id < cur.bucket_id:
            # Out-of-order data — should never happen if NT feeds in
            # ts_init order. Raise loudly.
            raise ValueError(
                f"Out-of-order 1s bar for {tf}: cur bucket "
                f"id={cur.bucket_id}, incoming id={bucket_id}, "
                f"ts_event={ts_event}")

        completed = cur if cur.is_complete else None
        if completed is None:
            self._incomplete_close_ts[tf].append(cur.close_ts)
        self._open_buckets[tf] = _OpenBucket(
            bucket_id=bucket_id,
            open_ts=bucket_id * bucket_size,
            close_ts=(bucket_id + 1) * bucket_size,
            open=op, high=h, low=l, close=c, volume=v,
            expected_count=bucket_size // 1_000_000_000,
            observed_event_ts={ts_event},
        )
        return completed

    # Diagnostics
    def current_bucket(self, tf: str) -> Optional[_OpenBucket]:
        """Return the currently OPEN (in-progress) bucket. Strategy
        code MUST NOT use this for features. Provided for tests
        only."""
        return self._open_buckets.get(tf)


class CompletedMinuteFiveMinuteAggregator:
    """Build completed 5m bars from five consecutive completed 1m parents.

    One-second bars are the source for 1s feature families, but an otherwise
    valid completed 1m parent must not be discarded solely because one of its
    constituent seconds had no trade.  This state machine consumes only the
    already-completed 1m stream and publishes a 5m bar only after all five
    aligned parents are present.  It never exposes a forming bucket.
    """

    def __init__(self, on_bucket_closed: BucketClosedCb) -> None:
        self._cb = on_bucket_closed
        self._current: Optional[_OpenMinuteBucket] = None
        self._incomplete_close_ts: list[int] = []

    def consume_incomplete_close_ts(self) -> list[int]:
        out = self._incomplete_close_ts
        self._incomplete_close_ts = []
        return out

    def on_completed_1m(
        self, open_ts: int, open_: float, high: float, low: float,
        close: float, volume: float,
    ) -> None:
        if open_ts % BUCKET_NS_1M != 0:
            raise ValueError(f"completed 1m parent is not minute-aligned: {open_ts}")
        bucket_id = open_ts // BUCKET_NS_5M
        if self._current is None:
            self._current = self._new_bucket(bucket_id, open_ts, open_, high, low, close, volume)
        elif bucket_id < self._current.bucket_id:
            raise ValueError(f"out-of-order completed 1m parent: {open_ts}")
        elif bucket_id == self._current.bucket_id:
            self._current.absorb(open_ts, high, low, close, volume)
        else:
            self._discard_if_incomplete()
            self._current = self._new_bucket(bucket_id, open_ts, open_, high, low, close, volume)

        current = self._current
        if open_ts + BUCKET_NS_1M == current.close_ts:
            if current.is_complete:
                self._cb("5m", current)
            else:
                self._incomplete_close_ts.append(current.close_ts)
            self._current = None

    @staticmethod
    def _new_bucket(
        bucket_id: int, open_ts: int, open_: float, high: float, low: float,
        close: float, volume: float,
    ) -> _OpenMinuteBucket:
        bucket_open = bucket_id * BUCKET_NS_5M
        return _OpenMinuteBucket(
            bucket_id=bucket_id, open_ts=bucket_open,
            close_ts=bucket_open + BUCKET_NS_5M, open=open_, high=high,
            low=low, close=close, volume=volume, observed_open_ts={open_ts},
        )

    def _discard_if_incomplete(self) -> None:
        if self._current is not None and not self._current.is_complete:
            self._incomplete_close_ts.append(self._current.close_ts)

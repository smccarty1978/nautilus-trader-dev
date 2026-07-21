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

    def absorb(self, bar_h: float, bar_l: float, bar_c: float,
                  bar_v: float) -> None:
        """Add a 1s bar's data into this bucket."""
        if bar_h > self.high:
            self.high = bar_h
        if bar_l < self.low:
            self.low = bar_l
        self.close = bar_c
        self.volume += bar_v


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
            )
            return None

        if bucket_id == cur.bucket_id:
            # Same bucket — absorb
            cur.absorb(h, l, c, v)
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

        completed = cur
        self._open_buckets[tf] = _OpenBucket(
            bucket_id=bucket_id,
            open_ts=bucket_id * bucket_size,
            close_ts=(bucket_id + 1) * bucket_size,
            open=op, high=h, low=l, close=c, volume=v,
        )
        return completed

    # Diagnostics
    def current_bucket(self, tf: str) -> Optional[_OpenBucket]:
        """Return the currently OPEN (in-progress) bucket. Strategy
        code MUST NOT use this for features. Provided for tests
        only."""
        return self._open_buckets.get(tf)

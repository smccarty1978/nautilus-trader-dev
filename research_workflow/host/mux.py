"""Stream multiplexer: per-stream ``visible_through_ns``, the same-timestamp rule, and
generic completed-bucket aggregation for derived timeframes.

Causal rule.  A decision epoch belongs to the execution instrument.  At epoch ``T``
(the ``ts_init`` of an execution-stream bar) execution streams may expose their bar at
``T``; a context stream exposes only bars with ``ts_init < T``.  Context bars are
queued on arrival and released just before the first execution bar with a strictly
later ``ts_init`` -- one integer per stream and one assertion at the epoch, nothing
more.  There is no proven same-timestamp policy yet, so ``same_ts: available`` is
refused at compile time.

Derived timeframes.  A bucket of ``bucket_ns`` is keyed by ``ts_event // bucket_ns``;
it publishes when every expected member (``bucket_ns / source_duration``) is present and
the member with ``ts_init == close_ts`` has arrived (``finalize_through``); an
incomplete bucket is discarded when its successor opens.  Publications inside one source
bar are ordered by ``close_ts`` then by larger bucket first.  This is the accepted
``collectors/collector_v2/aggregator.py`` semantics, generic over source and bucket.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from research_workflow.host.interfaces import NS, BarView


class CausalOrderViolation(RuntimeError):
    pass


@dataclass
class StreamInfo:
    key: str
    instrument: str
    timeframe: str
    duration_ns: int
    role: str
    source: str
    derived_from: Optional[str] = None
    aggregation: Optional[str] = None
    bar_type: Optional[str] = None


class _Bucket:
    __slots__ = ("bucket_id", "open_ts", "close_ts", "open", "high", "low", "close", "volume", "count", "min_ts", "max_ts")

    def __init__(self, bucket_id: int, open_ts: int, close_ts: int, bar: BarView) -> None:
        self.bucket_id = bucket_id
        self.open_ts = open_ts
        self.close_ts = close_ts
        self.open, self.high, self.low, self.close, self.volume = bar.open, bar.high, bar.low, bar.close, bar.volume
        self.count = 1
        self.min_ts = bar.ts_event
        self.max_ts = bar.ts_event

    def absorb(self, bar: BarView) -> None:
        if bar.high > self.high:
            self.high = bar.high
        if bar.low < self.low:
            self.low = bar.low
        self.close = bar.close
        self.volume += bar.volume
        self.count += 1
        if bar.ts_event < self.min_ts:
            self.min_ts = bar.ts_event
        if bar.ts_event > self.max_ts:
            self.max_ts = bar.ts_event


class BucketAggregator:
    """Complete-bucket aggregation of one source stream into one derived stream."""

    def __init__(self, derived_key: str, bucket_ns: int, source_duration_ns: int) -> None:
        if bucket_ns % source_duration_ns != 0:
            raise ValueError(f"BUCKET_NOT_MULTIPLE: {bucket_ns} % {source_duration_ns}")
        self.key = derived_key
        self.bucket_ns = int(bucket_ns)
        self.source_duration_ns = int(source_duration_ns)
        self.expected = self.bucket_ns // self.source_duration_ns
        self._cur: Optional[_Bucket] = None
        self.incomplete_close_ts: List[int] = []

    def _complete(self, b: _Bucket) -> bool:
        return (b.count == self.expected and b.min_ts == b.open_ts
                and b.max_ts == b.close_ts - self.source_duration_ns)

    def _publish(self, b: _Bucket) -> BarView:
        return BarView(self.key, b.open_ts, b.close_ts, b.open, b.high, b.low, b.close, b.volume)

    def on_source_bar(self, bar: BarView) -> List[BarView]:
        out: List[BarView] = []
        bucket_id = bar.ts_event // self.bucket_ns
        cur = self._cur
        if cur is None:
            self._cur = _Bucket(bucket_id, bucket_id * self.bucket_ns, (bucket_id + 1) * self.bucket_ns, bar)
        elif bucket_id == cur.bucket_id:
            cur.absorb(bar)
        elif bucket_id < cur.bucket_id:
            raise CausalOrderViolation(f"OUT_OF_ORDER_SOURCE_BAR: {self.key} bucket {bucket_id} < {cur.bucket_id}")
        else:
            if self._complete(cur):
                out.append(self._publish(cur))
            else:
                self.incomplete_close_ts.append(cur.close_ts)
            self._cur = _Bucket(bucket_id, bucket_id * self.bucket_ns, (bucket_id + 1) * self.bucket_ns, bar)
        # finalize_through(available_ns = bar.ts_init)
        cur = self._cur
        if cur is not None and cur.close_ts <= bar.ts_init:
            if self._complete(cur):
                out.append(self._publish(cur))
            else:
                self.incomplete_close_ts.append(cur.close_ts)
            self._cur = None
        return out


class StreamMux:
    """Orders and gates bars; delivers ``BarView``s through ``deliver`` in causal order."""

    def __init__(self, streams: Sequence[dict], deliver: Callable[[BarView], None]) -> None:
        self.streams: Dict[str, StreamInfo] = {}
        for s in streams:
            self.streams[s["key"]] = StreamInfo(
                key=s["key"], instrument=s["instrument"], timeframe=s["timeframe"], duration_ns=int(s["duration_ns"]),
                role=s["role"], source=s["source"], derived_from=s.get("derived_from"), aggregation=s.get("aggregation"),
                bar_type=s.get("bar_type"))
        self._deliver = deliver
        self.visible_through: Dict[str, int] = {k: -1 for k in self.streams}
        self.by_bar_type: Dict[str, str] = {s.bar_type: s.key for s in self.streams.values() if s.bar_type}
        self._aggregators: Dict[str, List[BucketAggregator]] = {}
        for s in self.streams.values():
            if s.source == "derived" and s.aggregation == "complete_bucket":
                src = self.streams[s.derived_from]
                self._aggregators.setdefault(src.key, []).append(BucketAggregator(s.key, s.duration_ns, src.duration_ns))
        for aggs in self._aggregators.values():
            aggs.sort(key=lambda a: -a.bucket_ns)
        self._context_queue: List[BarView] = []
        self.execution_instrument = next((s.instrument for s in self.streams.values() if s.role == "execution"), None)
        self.bars_seen: Dict[str, int] = {k: 0 for k in self.streams}

    # -- ingestion --------------------------------------------------------------
    def ingest(self, bar: BarView) -> None:
        info = self.streams[bar.stream]
        if info.role == "execution":
            self._release_context(before_ts=bar.ts_init)
            self._apply(bar)
        else:
            self._context_queue.append(bar)

    def flush(self) -> None:
        """Run end: release every queued context bar (no execution epoch can follow)."""
        self._release_context(before_ts=None)

    def _release_context(self, before_ts: Optional[int]) -> None:
        if not self._context_queue:
            return
        keep: List[BarView] = []
        for b in sorted(self._context_queue, key=lambda x: (x.ts_init, self.streams[x.stream].duration_ns)):
            if before_ts is None or b.ts_init < before_ts:
                self._apply(b)
            else:
                keep.append(b)
        self._context_queue = keep

    def _apply(self, bar: BarView) -> None:
        last = self.visible_through[bar.stream]
        if bar.ts_init <= last:
            raise CausalOrderViolation(f"NON_MONOTONIC_STREAM: {bar.stream} ts_init {bar.ts_init} <= {last}")
        self.visible_through[bar.stream] = bar.ts_init
        self.bars_seen[bar.stream] += 1
        self._deliver(bar)
        aggs = self._aggregators.get(bar.stream)
        if aggs:
            published: List[Tuple[int, int, BarView]] = []
            for agg in aggs:
                for out in agg.on_source_bar(bar):
                    published.append((out.ts_init, -agg.bucket_ns, out))
            published.sort(key=lambda t: (t[0], t[1]))
            for _, _, out in published:
                self._apply(out)

    # -- the assertion ------------------------------------------------------------
    def assert_epoch_visibility(self, T: int, execution_streams: Sequence[str]) -> None:
        for key, ts in self.visible_through.items():
            if key in execution_streams:
                if ts > T:
                    raise CausalOrderViolation(f"EXECUTION_STREAM_AHEAD_OF_EPOCH: {key} visible_through {ts} > T {T}")
            elif ts >= T:
                raise CausalOrderViolation(f"CONTEXT_STREAM_VISIBLE_AT_EPOCH: {key} visible_through {ts} >= T {T}")


__all__ = ["StreamMux", "StreamInfo", "BucketAggregator", "CausalOrderViolation"]

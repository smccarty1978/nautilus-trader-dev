"""Stream multiplexer: per-stream ``visible_through_ns``, the same-timestamp rule, and
generic aggregation for derived timeframes.

Causal rule.  A decision epoch belongs to the execution instrument.  At epoch ``T``
(the ``ts_init`` of the bar that raises the epoch) a stream whose declared
``visibility`` is ``at_epoch`` may expose its bar at ``T``; a ``strictly_before``
stream exposes only bars with ``ts_init < T``.  Context bars are queued on arrival and
released just before the first execution bar with a strictly later ``ts_init`` -- one
integer per stream and one assertion at the epoch, nothing more.  There is no proven
same-timestamp policy yet, so ``same_ts: available`` is refused at compile time.

``visibility`` is a per-stream plan field, not a synonym for ``role``.  Every execution
stream is ``at_epoch``.  A context stream is ``strictly_before`` EXCEPT when it is the
population's completed-bar cadence stream: that stream's own bar close *is* the epoch,
the finer execution bar closing at the same instant is already visible, and nothing on
any stream is ahead of ``T``, so the epoch is causally sound.  The compiler sets that
field (``_resolve_population``); the mux only enforces what the plan declares.

Derived timeframes.  The plan names the aggregation per derived stream; the mux dispatches
on that name and refuses one it does not know.

* ``closed_window`` (every new compile).  A window of ``bucket_ns`` is keyed by
  ``ts_event // bucket_ns`` and absorbs whatever source bars arrive: ANY member suffices,
  which is the rule the dataset uses to build 1m from 1s and the rule
  ``artifacts/platform_v2_do_soon/dataset_v2/equivalence_NQ.json`` proves reproduces the
  historical 5m stream (``5m_runtime_rule_matching_v0: any_minute``).  It publishes when
  the source bar with ``ts_init >= close_ts`` arrives, or when time has passed the close:
  a bar with ``ts_init > close_ts`` on any external stream, or ``== close_ts`` on a stream
  the mux always applies after the source at the same instant (execution before context,
  finer context before coarser).  A window with no source bar emits a zero-volume bar
  (O=H=L=C = the previous close) -- NautilusTrader 1.230 ``TimeBarAggregator``'s default
  ``build_with_no_updates=True`` -- but only when the plan declares
  ``empty_window: zero_volume_in_trading_day`` and the window overlaps a trading day of the
  dataset calendar, and never before the first member.  NT's timer also fires through
  weekend/holiday/maintenance closures; this does not (owner decision D3b, 2026-09-14).
  ``empty_window: none`` emits nothing for an empty window, which equals NT only with
  ``DataEngineConfig(time_bars_build_with_no_updates=False)``.
* ``complete_bucket`` (sealed plans only; the compiler never emits it again).  Publishes a
  bucket only when every expected member is present; an incomplete bucket is discarded
  when its successor opens (``collectors/collector_v2/aggregator.py`` semantics).  Kept
  dispatchable so ``v2_shape_b_deep_pullback_5s`` replays bit-identically.

Publications inside one applied bar are ordered by ``close_ts`` then by larger bucket
first, and are delivered before that bar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from research_workflow.host.interfaces import NS, BarView

AGGREGATIONS = ("closed_window", "complete_bucket")
EMPTY_WINDOW_RULES = ("zero_volume_in_trading_day", "none")


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
    visibility: str = "at_epoch"
    derived_from: Optional[str] = None
    aggregation: Optional[str] = None
    bar_type: Optional[str] = None
    empty_window: Optional[str] = None


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


class ClosedWindowAggregator:
    """Closed-window aggregation: any member publishes; an empty window inside a trading day
    publishes a zero-volume bar when ``trading_days`` is given (see the module docstring)."""

    def __init__(self, derived_key: str, bucket_ns: int, source_duration_ns: int, *, trading_days: Any = None) -> None:
        if bucket_ns % source_duration_ns != 0:
            raise ValueError(f"BUCKET_NOT_MULTIPLE: {bucket_ns} % {source_duration_ns}")
        self.key = derived_key
        self.bucket_ns = int(bucket_ns)
        self.source_duration_ns = int(source_duration_ns)
        self._days = trading_days
        self._cur: Optional[_Bucket] = None
        self._frontier: Optional[int] = None        # close_ts of the latest window accounted for
        self._last_close: Optional[float] = None
        self.empty_windows_published = 0

    @property
    def due_ns(self) -> Optional[int]:
        """Earliest instant at which a sweep could publish something."""
        if self._cur is not None:
            return self._cur.close_ts
        if self._days is not None and self._frontier is not None:
            return self._frontier + self.bucket_ns
        return None

    def _publish(self, b: _Bucket) -> BarView:
        self._last_close = b.close
        self._frontier = b.close_ts
        return BarView(self.key, b.open_ts, b.close_ts, b.open, b.high, b.low, b.close, b.volume)

    def _fill_empty_through(self, max_close: int, out: List[BarView]) -> None:
        """Zero-volume bars for every empty window with ``close_ts <= max_close`` (aligned) that
        overlaps a trading day; windows inside a closure are skipped, not iterated."""
        if self._days is None or self._frontier is None or self._last_close is None:
            return
        bn = self.bucket_ns
        o = self._frontier
        while o < max_close:
            c = o + bn
            if self._days.overlaps(o, c):
                px = self._last_close
                out.append(BarView(self.key, o, c, px, px, px, px, 0.0))
                self.empty_windows_published += 1
                o = c
                continue
            nxt = self._days.next_row_after(o)
            o = max_close if nxt is None else min(max(c, (nxt[0] // bn) * bn), max_close)
        self._frontier = max(self._frontier, o)

    def on_source_bar(self, bar: BarView) -> List[BarView]:
        out: List[BarView] = []
        bn = self.bucket_ns
        bucket_id = bar.ts_event // bn
        cur = self._cur
        if cur is not None:
            if bucket_id < cur.bucket_id:
                raise CausalOrderViolation(f"OUT_OF_ORDER_SOURCE_BAR: {self.key} bucket {bucket_id} < {cur.bucket_id}")
            if bucket_id > cur.bucket_id:
                out.append(self._publish(cur))
                self._cur = cur = None
        if cur is None:
            open_ts = bucket_id * bn
            if self._frontier is not None and open_ts < self._frontier:
                raise CausalOrderViolation(f"OUT_OF_ORDER_SOURCE_BAR: {self.key} window opening {open_ts} was already closed at {self._frontier}")
            self._fill_empty_through(open_ts, out)
            self._cur = _Bucket(bucket_id, open_ts, open_ts + bn, bar)
        else:
            cur.absorb(bar)
        if self._cur.close_ts <= bar.ts_init:
            out.append(self._publish(self._cur))
            self._cur = None
        return out

    def sweep(self, t: int, inclusive: bool) -> List[BarView]:
        """Time has reached ``t``: every source bar with ``ts_init < t`` (``<= t`` when
        ``inclusive``) has been applied, so windows closing before it are closed."""
        out: List[BarView] = []
        cur = self._cur
        if cur is not None:
            if cur.close_ts < t or (inclusive and cur.close_ts == t):
                out.append(self._publish(cur))
                self._cur = None
            else:
                return out
        if self._days is not None and self._frontier is not None:
            bn = self.bucket_ns
            self._fill_empty_through((t // bn) * bn if inclusive else ((t - 1) // bn) * bn, out)
        return out


class StreamMux:
    """Orders and gates bars; delivers ``BarView``s through ``deliver`` in causal order.

    ``trading_days`` is the dataset calendar's trading-day table (``overlaps``/``next_row_after``);
    a plan whose derived stream declares ``empty_window: zero_volume_in_trading_day`` cannot be
    run without it.  ``require_calendar=False`` is the compiler's dry construction only."""

    def __init__(self, streams: Sequence[dict], deliver: Callable[[BarView], None], *, trading_days: Any = None,
                 require_calendar: bool = True) -> None:
        self.streams: Dict[str, StreamInfo] = {}
        for s in streams:
            self.streams[s["key"]] = StreamInfo(
                key=s["key"], instrument=s["instrument"], timeframe=s["timeframe"], duration_ns=int(s["duration_ns"]),
                role=s["role"], source=s["source"],
                visibility=str(s.get("visibility") or ("at_epoch" if s["role"] == "execution" else "strictly_before")),
                derived_from=s.get("derived_from"), aggregation=s.get("aggregation"),
                bar_type=s.get("bar_type"), empty_window=s.get("empty_window"))
        self._deliver = deliver
        self.visible_through: Dict[str, int] = {k: -1 for k in self.streams}
        self.by_bar_type: Dict[str, str] = {s.bar_type: s.key for s in self.streams.values() if s.bar_type}
        self._aggregators: Dict[str, List[Any]] = {}
        # Same-instant application order of external streams: execution bars are applied on ingest,
        # context bars are released later sorted by (ts_init, duration).  Derived bars have no rank.
        self._rank: Dict[str, Tuple[int, int]] = {
            k: ((0, 0) if s.role == "execution" else (1, s.duration_ns))
            for k, s in self.streams.items() if s.source != "derived"}
        self._sweepers: List[Tuple[ClosedWindowAggregator, str, Optional[Tuple[int, int]]]] = []
        self.at_epoch_streams = {k for k, s in self.streams.items() if s.visibility == "at_epoch"}
        for s in self.streams.values():
            if s.source != "derived":
                continue
            if s.derived_from not in self.streams:
                raise CausalOrderViolation(
                    f"DERIVED_SOURCE_STREAM_ABSENT: {s.key} is derived from {s.derived_from!r}, "
                    f"which is not one of the plan's streams {sorted(self.streams)}")
            src = self.streams[s.derived_from]
            if s.aggregation == "complete_bucket":
                agg: Any = BucketAggregator(s.key, s.duration_ns, src.duration_ns)
            elif s.aggregation == "closed_window":
                if s.empty_window not in EMPTY_WINDOW_RULES:
                    raise CausalOrderViolation(
                        f"EMPTY_WINDOW_RULE_UNDECLARED: {s.key} (closed_window) declares empty_window={s.empty_window!r}; "
                        f"one of {list(EMPTY_WINDOW_RULES)} is required")
                days = None
                if s.empty_window == "zero_volume_in_trading_day":
                    if trading_days is None and require_calendar:
                        raise CausalOrderViolation(
                            f"TRADING_DAY_CALENDAR_ABSENT: {s.key} fills empty windows inside trading days, "
                            f"but the run was given no trading-day calendar")
                    days = trading_days
                agg = ClosedWindowAggregator(s.key, s.duration_ns, src.duration_ns, trading_days=days)
                self._sweepers.append((agg, src.key, self._rank.get(src.key)))
            else:
                raise CausalOrderViolation(
                    f"UNKNOWN_AGGREGATION: {s.key} declares aggregation={s.aggregation!r}; known: {list(AGGREGATIONS)}")
            self._aggregators.setdefault(src.key, []).append(agg)
        for aggs in self._aggregators.values():
            aggs.sort(key=lambda a: -a.bucket_ns)
        self._sweep_due: float = float("inf")
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

    def _recompute_sweep_due(self) -> None:
        due = float("inf")
        for agg, _src, _rank in self._sweepers:
            d = agg.due_ns
            if d is not None and d < due:
                due = d
        self._sweep_due = due

    def _apply(self, bar: BarView) -> None:
        last = self.visible_through[bar.stream]
        if bar.ts_init <= last:
            raise CausalOrderViolation(f"NON_MONOTONIC_STREAM: {bar.stream} ts_init {bar.ts_init} <= {last}")
        self.visible_through[bar.stream] = bar.ts_init
        self.bars_seen[bar.stream] += 1
        # Derived windows closed by this bar are delivered BEFORE the bar itself: a window closing
        # at T is closed at T, and is published as part of that availability instant, ahead of any
        # decision at T.
        published: List[Tuple[int, int, BarView]] = []
        aggs = self._aggregators.get(bar.stream)
        if aggs:
            for agg in aggs:
                for out in agg.on_source_bar(bar):
                    published.append((out.ts_init, -agg.bucket_ns, out))
        if self._sweepers:
            rank = self._rank.get(bar.stream)
            if rank is not None and bar.ts_init >= self._sweep_due:
                for agg, src_key, src_rank in self._sweepers:
                    if src_key == bar.stream:
                        continue
                    inclusive = src_rank is not None and rank > src_rank
                    for out in agg.sweep(bar.ts_init, inclusive):
                        published.append((out.ts_init, -agg.bucket_ns, out))
            if aggs or published:
                self._recompute_sweep_due()
        if published:
            published.sort(key=lambda t: (t[0], t[1]))
            for _, _, out in published:
                self._apply(out)
        self._deliver(bar)

    # -- the assertion ------------------------------------------------------------
    def assert_epoch_visibility(self, T: int) -> None:
        """Nothing on any stream may be ahead of ``T``; a ``strictly_before`` stream may not
        even reach it.  The allowed-at-``T`` set is the plan's ``visibility`` field, so a
        cadence stream that raises its epoch at its own bar close is admitted by the plan
        rather than by an exception carved into this assertion."""
        for key, ts in self.visible_through.items():
            if key in self.at_epoch_streams:
                if ts > T:
                    raise CausalOrderViolation(f"EXECUTION_STREAM_AHEAD_OF_EPOCH: {key} visible_through {ts} > T {T}")
            elif ts >= T:
                raise CausalOrderViolation(f"CONTEXT_STREAM_VISIBLE_AT_EPOCH: {key} visible_through {ts} >= T {T}")


__all__ = ["StreamMux", "StreamInfo", "BucketAggregator", "ClosedWindowAggregator", "CausalOrderViolation",
           "AGGREGATIONS", "EMPTY_WINDOW_RULES"]

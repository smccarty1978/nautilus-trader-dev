"""Telemetry & Performance Tracking for NautilusTrader Execution.
================================================================
Measures wall-time, process RSS memory, bar callbacks by timeframe,
and emits deterministic telemetry cards.
"""

from __future__ import annotations

import os
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import psutil


@dataclass
class TelemetrySnapshot:
    elapsed_seconds: float
    total_bars_processed: int
    candidates_count: int
    throughput_bars_per_sec: float
    baseline_process_rss_mb: float
    peak_process_rss_mb: float
    rss_delta_mb: float
    python_tracemalloc_peak_mb: float
    bars_loaded_by_tf: Dict[str, int] = field(default_factory=dict)
    callbacks_by_tf: Dict[str, int] = field(default_factory=dict)
    ts_event_ranges_by_tf: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    ts_init_ranges_by_tf: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    # Population funnel (Packet E). None unless the strategy exposes
    # get_population_funnel() -- most strategies predate this instrumentation.
    population_total_checkpoints: Optional[int] = None
    population_declared_contract_exclusions_in_run: Optional[int] = None
    population_implementation_only_exclusions: Optional[int] = None
    population_candidates_emitted_raw: Optional[int] = None


class CausalTelemetry:
    """Tracks execution performance and process resource utilization."""

    def __init__(self, trace_allocations: Optional[bool] = None) -> None:
        self.process = psutil.Process(os.getpid())
        # Python allocation tracing (tracemalloc) instruments every allocation in
        # the process and captures a traceback for each one.  Left always-on it
        # cost this collector ~6-7x replay wall time (measured 2026-08-24: full
        # surface 5.73s -> 35.24s on the 213,431-event smoke day), which is the
        # dominant term in every historical throughput number for this runtime.
        # It is a memory *diagnostic*, so it is opt-in; process RSS telemetry
        # below is always collected and is cheap.
        if trace_allocations is None:
            trace_allocations = os.environ.get("NT_TELEMETRY_TRACEMALLOC", "") == "1"
        self.trace_allocations = bool(trace_allocations)
        self._tracing_started = False
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.baseline_rss_mb: float = 0.0
        self.peak_rss_mb: float = 0.0
        self.bars_loaded_by_tf: Dict[str, int] = {}
        self.callbacks_by_tf: Dict[str, int] = {}
        self.first_ts_event: Dict[str, Optional[int]] = {}
        self.last_ts_event: Dict[str, Optional[int]] = {}
        self.first_ts_init: Dict[str, Optional[int]] = {}
        self.last_ts_init: Dict[str, Optional[int]] = {}
        self.candidates_count: int = 0
        # Population funnel (Packet E) -- set via record_population_funnel(), left None
        # (not persisted / not reconciled) when the strategy does not expose one.
        self.population_total_checkpoints: Optional[int] = None
        self.population_declared_contract_exclusions_in_run: Optional[int] = None
        self.population_implementation_only_exclusions: Optional[int] = None
        self.population_candidates_emitted_raw: Optional[int] = None

    def start(self) -> None:
        if self.trace_allocations and not tracemalloc.is_tracing():
            tracemalloc.start()
            self._tracing_started = True
        self.baseline_rss_mb = self.process.memory_info().rss / (1024 * 1024)
        self.peak_rss_mb = self.baseline_rss_mb
        self.start_time = time.perf_counter()

    def record_loaded_bars(self, timeframe: str, count: int) -> None:
        self.bars_loaded_by_tf[timeframe] = count

    def record_bar_callback(self, timeframe: str, ts_event: int, ts_init: int) -> None:
        self.callbacks_by_tf[timeframe] = self.callbacks_by_tf.get(timeframe, 0) + 1

        if timeframe not in self.first_ts_event or self.first_ts_event[timeframe] is None:
            self.first_ts_event[timeframe] = ts_event
            self.first_ts_init[timeframe] = ts_init
        self.last_ts_event[timeframe] = ts_event
        self.last_ts_init[timeframe] = ts_init

        # Sample memory periodically
        current_rss = self.process.memory_info().rss / (1024 * 1024)
        if current_rss > self.peak_rss_mb:
            self.peak_rss_mb = current_rss

    def update_candidates(self, count: int) -> None:
        self.candidates_count = count

    def update(self, bars_increment: int = 0, candidates_increment: int = 0) -> None:
        self.candidates_count += candidates_increment

    def record_population_funnel(
        self,
        *,
        total_checkpoints: int,
        declared_contract_exclusions: int,
        implementation_only_exclusions: int,
        candidates_emitted_raw: int,
    ) -> None:
        """Records the raw, whole-run population-funnel counters from a collector
        that implements get_population_funnel() (Packet E). Left unset for any
        strategy that does not expose one; the persistence path treats that as
        "no funnel to reconcile", not a defect.
        """
        self.population_total_checkpoints = total_checkpoints
        self.population_declared_contract_exclusions_in_run = declared_contract_exclusions
        self.population_implementation_only_exclusions = implementation_only_exclusions
        self.population_candidates_emitted_raw = candidates_emitted_raw

    def stop(self) -> TelemetrySnapshot:
        self.end_time = time.perf_counter()
        # 0.0 is the defined "allocation tracing was not run" value; the field
        # stays in the telemetry card so the persisted schema is unchanged.
        tm_peak = 0.0
        if self._tracing_started:
            _current_mem, tm_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            self._tracing_started = False

        final_rss = self.process.memory_info().rss / (1024 * 1024)
        if final_rss > self.peak_rss_mb:
            self.peak_rss_mb = final_rss

        elapsed = max(self.end_time - self.start_time, 0.0001)
        total_callbacks = sum(self.callbacks_by_tf.values())
        throughput = total_callbacks / elapsed
        rss_delta = max(0.0, self.peak_rss_mb - self.baseline_rss_mb)

        ts_event_ranges = {
            tf: {"first": self.first_ts_event.get(tf), "last": self.last_ts_event.get(tf)}
            for tf in self.callbacks_by_tf
        }
        ts_init_ranges = {
            tf: {"first": self.first_ts_init.get(tf), "last": self.last_ts_init.get(tf)}
            for tf in self.callbacks_by_tf
        }

        return TelemetrySnapshot(
            elapsed_seconds=elapsed,
            total_bars_processed=total_callbacks,
            candidates_count=self.candidates_count,
            throughput_bars_per_sec=throughput,
            baseline_process_rss_mb=round(self.baseline_rss_mb, 2),
            peak_process_rss_mb=round(self.peak_rss_mb, 2),
            rss_delta_mb=round(rss_delta, 2),
            python_tracemalloc_peak_mb=round(tm_peak / (1024 * 1024), 2),
            bars_loaded_by_tf=self.bars_loaded_by_tf,
            callbacks_by_tf=self.callbacks_by_tf,
            ts_event_ranges_by_tf=ts_event_ranges,
            ts_init_ranges_by_tf=ts_init_ranges,
            population_total_checkpoints=self.population_total_checkpoints,
            population_declared_contract_exclusions_in_run=self.population_declared_contract_exclusions_in_run,
            population_implementation_only_exclusions=self.population_implementation_only_exclusions,
            population_candidates_emitted_raw=self.population_candidates_emitted_raw,
        )

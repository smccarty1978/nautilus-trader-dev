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


class CausalTelemetry:
    """Tracks execution performance and process resource utilization."""

    def __init__(self) -> None:
        self.process = psutil.Process(os.getpid())
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

    def start(self) -> None:
        tracemalloc.start()
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

    def stop(self) -> TelemetrySnapshot:
        self.end_time = time.perf_counter()
        current_mem, tm_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

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
        )

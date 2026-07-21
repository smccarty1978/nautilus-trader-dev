import time
from typing import Optional


class CausalProgressTracker:
    """Tracks and reports throughput, elapsed time, and ETA for backtests."""

    def __init__(self, report_interval_sec: float = 60.0):
        self.report_interval_sec = report_interval_sec
        self.start_time: Optional[float] = None
        self.last_report_time: float = 0.0
        
        self.total_bars = 0
        self.total_candidates = 0
        self.total_triggers = 0
        self.total_trades = 0

    def start(self) -> None:
        """Starts the tracking timer."""
        self.start_time = time.time()
        self.last_report_time = self.start_time

    def update(
        self,
        current_day: str,
        bars_increment: int = 0,
        candidates_increment: int = 0,
        triggers_increment: int = 0,
        trades_increment: int = 0,
        force_report: bool = False,
    ) -> None:
        """Updates counts and periodically prints progress metrics."""
        self.total_bars += bars_increment
        self.total_candidates += candidates_increment
        self.total_triggers += triggers_increment
        self.total_trades += trades_increment

        now = time.time()
        if self.start_time is None:
            self.start_time = now

        elapsed = now - self.start_time

        if force_report or (now - self.last_report_time >= self.report_interval_sec):
            self.last_report_time = now
            throughput_bars = self.total_bars / elapsed if elapsed > 0 else 0.0
            
            print(
                f"[PROGRESS] Day: {current_day} | "
                f"Elapsed: {elapsed:.1f}s | "
                f"Throughput: {throughput_bars:.1f} bars/sec | "
                f"Bars: {self.total_bars:,} | "
                f"Candidates: {self.total_candidates} | "
                f"Triggers: {self.total_triggers} | "
                f"Trades: {self.total_trades}",
                flush=True
            )

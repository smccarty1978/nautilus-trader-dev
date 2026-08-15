"""Minimal Checkpoint Collector Strategy.
========================================
Test collector B for Framework Genericity Proof:
  - Timeframes: 1s and 1m bars
  - Cadence: 15-second exact grid checkpoints
  - Feature count: 3 features ('arrival_vel_5s', 'arrival_vel_10s', 'arrival_vel_20s')
  - Minimal metadata: ('observation_ts', 'checkpoint_index', 'close', 'triggering_1s_ts_init')
  - No maturity buckets, no A/B/C arms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy
from features.trackers.velocity import ArrivalVelocityTracker


class MinimalCheckpointCollectorConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    cadence_seconds: int = 15
    feature_list: List[str] = ("arrival_vel_5s", "arrival_vel_10s", "arrival_vel_20s")


class MinimalCheckpointCollector(Strategy):
    def __init__(self, config: MinimalCheckpointCollectorConfig) -> None:
        super().__init__(config)
        self.bar_type_1s = BarType.from_str(config.bar_type_1s)
        self.bar_type_1m = BarType.from_str(config.bar_type_1m)
        self.cadence_ns = config.cadence_seconds * 1_000_000_000

        self.vel_tracker = ArrivalVelocityTracker(maxlen=60)
        self.last_1s_close: float = 0.0

        self.checkpoint_index: int = 0
        self.next_checkpoint_ts: Optional[int] = None

        self._candidates: List[Dict[str, Any]] = []
        self._observations: List[Dict[str, Any]] = []

    def on_start(self) -> None:
        self.subscribe_bars(self.bar_type_1s)
        self.subscribe_bars(self.bar_type_1m)

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type == self.bar_type_1s:
            self._handle_1s_bar(bar)

    def _handle_1s_bar(self, bar: Bar) -> None:
        ts = int(bar.ts_init)
        self.last_1s_close = float(bar.close)
        self.vel_tracker.update(self.last_1s_close)

        if self.next_checkpoint_ts is None:
            self.next_checkpoint_ts = ((ts // self.cadence_ns) + 1) * self.cadence_ns

        while self.next_checkpoint_ts <= ts:
            if self.next_checkpoint_ts == ts and self.last_1s_close > 0.0:
                self._evaluate_checkpoint(ts)
            self.next_checkpoint_ts += self.cadence_ns
            self.checkpoint_index += 1

    def _evaluate_checkpoint(self, obs_ts: int) -> None:
        vels = self.vel_tracker.calculate(atr=10.0)

        row = {
            "observation_ts": obs_ts,
            "checkpoint_index": self.checkpoint_index,
            "close": self.last_1s_close,
            "triggering_1s_ts_init": obs_ts,
            # 3 features
            "arrival_vel_5s": vels.get("arrival_vel_5s", 0.0),
            "arrival_vel_10s": vels.get("arrival_vel_10s", 0.0),
            "arrival_vel_20s": vels.get("arrival_vel_20s", 0.0),
        }
        self._candidates.append(row)
        self._observations.append(row)

    def get_candidates_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self._candidates) if self._candidates else pd.DataFrame(columns=[
            "observation_ts", "checkpoint_index", "close", "triggering_1s_ts_init",
            "arrival_vel_5s", "arrival_vel_10s", "arrival_vel_20s"
        ])

    def get_candidates_df(self) -> pd.DataFrame:
        return self.get_candidates_dataframe()

    def get_observations_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self._observations) if self._observations else pd.DataFrame(columns=[
            "observation_ts", "checkpoint_index", "close", "triggering_1s_ts_init",
            "arrival_vel_5s", "arrival_vel_10s", "arrival_vel_20s"
        ])

    def get_observations_df(self) -> pd.DataFrame:
        return self.get_observations_dataframe()

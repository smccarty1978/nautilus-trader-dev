"""Level Break Test Collector Strategy.
=====================================
Test collector C for Framework Genericity Proof:
  - Streams: 1s and 1m completed bars
  - Observation policy: 1m bar close event-driven observation
  - Feature count: 7 features ('arrival_vel_5s', 'arrival_vel_10s', 'arrival_vel_20s', 'arrival_vel_30s', 'arrival_accel_5s', 'arrival_accel_10s', 'arrival_jerk')
  - Uses ArrivalVelocityTracker
  - Different metadata layout
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy
from features.trackers.velocity import ArrivalVelocityTracker


class LevelBreakTestCollectorConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    feature_list: List[str] = (
        "arrival_vel_5s",
        "arrival_vel_10s",
        "arrival_vel_20s",
        "arrival_vel_30s",
        "arrival_accel_5s",
        "arrival_accel_10s",
        "arrival_jerk",
    )


class LevelBreakTestCollector(Strategy):
    def __init__(self, config: LevelBreakTestCollectorConfig) -> None:
        super().__init__(config)
        self.bar_type_1s = BarType.from_str(config.bar_type_1s)
        self.bar_type_1m = BarType.from_str(config.bar_type_1m)

        self.vel_tracker = ArrivalVelocityTracker(maxlen=60)
        self.last_1s_close: float = 0.0
        self.last_1s_ts: int = 0

        self.event_index: int = 0
        self._candidates: List[Dict[str, Any]] = []
        self._observations: List[Dict[str, Any]] = []

    def on_start(self) -> None:
        self.subscribe_bars(self.bar_type_1s)
        self.subscribe_bars(self.bar_type_1m)

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type == self.bar_type_1s:
            self.last_1s_close = float(bar.close)
            self.last_1s_ts = int(bar.ts_init)
            self.vel_tracker.update(self.last_1s_close)
        elif bar.bar_type == self.bar_type_1m:
            self._handle_1m_bar(bar)

    def _handle_1m_bar(self, bar: Bar) -> None:
        obs_ts = int(bar.ts_init)
        if self.last_1s_ts == 0:
            return

        vels = self.vel_tracker.calculate(atr=10.0)
        self.event_index += 1

        row = {
            "observation_ts": obs_ts,
            "event_index": self.event_index,
            "bar_close_1m": float(bar.close),
            "bar_volume_1m": float(bar.volume),
            "triggering_1s_ts_init": self.last_1s_ts,
            # 7 features
            "arrival_vel_5s": vels.get("arrival_vel_5s", 0.0),
            "arrival_vel_10s": vels.get("arrival_vel_10s", 0.0),
            "arrival_vel_20s": vels.get("arrival_vel_20s", 0.0),
            "arrival_vel_30s": vels.get("arrival_vel_30s", 0.0),
            "arrival_accel_5s": vels.get("arrival_accel_5s", 0.0),
            "arrival_accel_10s": vels.get("arrival_accel_10s", 0.0),
            "arrival_jerk": vels.get("arrival_jerk", 0.0),
        }
        self._candidates.append(row)
        self._observations.append(row)

    def get_candidates_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self._candidates) if self._candidates else pd.DataFrame(columns=[
            "observation_ts", "event_index", "bar_close_1m", "bar_volume_1m", "triggering_1s_ts_init",
            "arrival_vel_5s", "arrival_vel_10s", "arrival_vel_20s", "arrival_vel_30s",
            "arrival_accel_5s", "arrival_accel_10s", "arrival_jerk",
        ])

    def get_observations_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self._observations) if self._observations else pd.DataFrame(columns=[
            "observation_ts", "event_index", "bar_close_1m", "bar_volume_1m", "triggering_1s_ts_init",
            "arrival_vel_5s", "arrival_vel_10s", "arrival_vel_20s", "arrival_vel_30s",
            "arrival_accel_5s", "arrival_accel_10s", "arrival_jerk",
        ])

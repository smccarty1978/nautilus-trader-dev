from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar
from nautilus_trader.trading.strategy import Strategy

from utils.runner.checkpoint import DailyStateCheckpointer
from utils.runner.fanning import ThresholdEvaluator
from utils.runner.progress import CausalProgressTracker
from utils.runner.registry import CompletedBarRegistry


class ScoreFanningConfig(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type_1s: str
    bar_type_1m: str
    checkpoint_dir: str = "backtests/results/checkpoints"
    
    # Policies to evaluate concurrently (name, threshold, sl_atr_mult, pt_atr_mult)
    policies: List[Dict[str, Any]] = [
        {"name": "R5", "threshold": 0.62, "sl_atr_mult": 1.5, "pt_atr_mult": 2.0},
        {"name": "R2.5", "threshold": 0.50, "sl_atr_mult": 1.5, "pt_atr_mult": 2.0}
    ]


class ScoreFanningStrategy(Strategy):
    """A research strategy evaluating multiple policy/threshold variants concurrently."""

    def __init__(self, config: ScoreFanningConfig):
        super().__init__(config)
        self.cfg = config
        
        self.inst_id = self.cache.instrument(config.instrument_id).id
        self.bt_1s = self.cache.bar_type(config.bar_type_1s)
        self.bt_1m = self.cache.bar_type(config.bar_type_1m)

        # Composition-based components
        self.bar_registry = CompletedBarRegistry()
        self.progress_tracker = CausalProgressTracker(report_interval_sec=60.0)
        self.checkpointer = DailyStateCheckpointer(Path(config.checkpoint_dir))
        
        # Instantiate evaluators
        self.evaluators: List[ThresholdEvaluator] = []
        for p in config.policies:
            self.evaluators.append(
                ThresholdEvaluator(
                    name=p["name"],
                    threshold=p["threshold"],
                    sl_atr_mult=p["sl_atr_mult"],
                    pt_atr_mult=p["pt_atr_mult"]
                )
            )

        self.last_day_str: Optional[str] = None
        self.progress_tracker.start()

    def on_start(self):
        super().on_start()
        # Request data subscriptions
        self.request_data_subscription(self.bt_1s)
        self.request_data_subscription(self.bt_1m)

    def on_bar(self, bar: Bar):
        # Enforce CompletedBarRegistry close checks (A1 rule)
        if not self.bar_registry.register_completed_bar(str(bar.bar_type), bar.ts_init):
            return

        ts_event = bar.ts_event
        dt = pd.to_datetime(ts_event, unit="ns", utc=True)
        current_day_str = dt.strftime("%Y-%m-%d")

        # 1-second bar loop
        if bar.bar_type == self.bt_1s:
            open_px = float(bar.open)
            high = float(bar.high)
            low = float(bar.low)
            close = float(bar.close)

            # Dispatch 1s bar updates to all policy evaluators
            for evalr in self.evaluators:
                evalr.on_bar_1s(ts_event, open_px, high, low, close)

            # Track throughput
            self.progress_tracker.update(current_day_str, bars_increment=1)

        # 1-minute bar loop
        elif bar.bar_type == self.bt_1m:
            close_px = float(bar.close)
            # Simulated regime/score computation
            # For demonstration, we simulate scoring signals on 1m closes.
            # Upstream components (regime, model runtime) would be evaluated here once.
            dummy_score = 0.55  # Exceeds R2.5 but not R5
            dummy_atr = 15.0
            dummy_direction = -1  # Short

            # Fan the single score out to all policies
            for evalr in self.evaluators:
                evalr.on_candidate(
                    ts_event=ts_event,
                    price=close_px,
                    atr=dummy_atr,
                    score=dummy_score,
                    direction=dummy_direction
                )

            # Progress check / Checkpoint check
            if self.last_day_str is not None and current_day_str != self.last_day_str:
                self.save_daily_checkpoint(self.last_day_str)
            self.last_day_str = current_day_str

    def save_daily_checkpoint(self, day_str: str) -> None:
        """Saves current state for all evaluators and registers it in resume manifest."""
        state = {
            "evaluators": {
                evalr.name: evalr.get_serialized_state()
                for evalr in self.evaluators
            }
        }
        self.checkpointer.save_checkpoint(day_str, state)
        
        # Write manifest
        self.checkpointer.write_manifest(
            current_date_str=day_str,
            strategy_config=self.cfg.dict(),
            model_paths={}  # Fill in if joblib models are used
        )

    def load_daily_checkpoint(self, day_str: str) -> None:
        """Restores state for all evaluators from a saved checkpoint."""
        state = self.checkpointer.load_checkpoint(day_str)
        for evalr in self.evaluators:
            if evalr.name in state["evaluators"]:
                evalr.load_serialized_state(state["evaluators"][evalr.name])
        self.last_day_str = day_str

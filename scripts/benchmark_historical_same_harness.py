"""Historical collector controls using the canonical data-plan/engine builder."""
from __future__ import annotations

import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtests.nt_runtime.compiled_study_loader import load_compiled_study
from backtests.nt_runtime.run_plan import resolve_run_plan
from backtests.nt_runtime.data_plan import resolve_data_plan
from backtests.nt_runtime.engine_builder import build_engine
from strategies.minimal_checkpoint_collector import MinimalCheckpointCollector, MinimalCheckpointCollectorConfig
from strategies.w4_exit_strategy import W4ExitStrategy, W4ExitConfig


def run(name: str) -> dict:
    study = load_compiled_study(ROOT / "studies/clean_maturity_flip_model_rolling_productivity")
    plan = resolve_run_plan(study, stage="day", reference_date="2023-10-02")
    data = resolve_data_plan(study, start_date=plan.start_date, end_date=plan.end_date)
    started = time.perf_counter()
    engine, _ = build_engine(data, log_level="ERROR")
    setup = time.perf_counter() - started
    if name == "minimal":
        strategy = MinimalCheckpointCollector(MinimalCheckpointCollectorConfig(
            instrument_id=data.instrument_id, bar_type_1s=data.bar_type_1s,
            bar_type_1m=data.bar_type_1m))
    else:
        strategy = W4ExitStrategy(W4ExitConfig(
            instrument_id=data.instrument_id, bar_type_1s=data.bar_type_1s,
            bar_type_1m=data.bar_type_1m, year=2023, policy="B0"))
    engine.add_strategy(strategy)
    replay_started = time.perf_counter()
    engine.run()
    replay = time.perf_counter() - replay_started
    engine.dispose()
    return {"collector": name, "setup_seconds": setup, "replay_seconds": replay,
            "bars": 207911 + 5520, "bars_per_second": (207911 + 5520) / replay}


if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else "minimal"))

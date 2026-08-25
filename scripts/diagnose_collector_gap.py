"""Diagnostic: locate the replay-time gap between the generic collector and the
historical Python collectors, using one shared data plan and engine builder.

Benchmark-only. Constructs collectors directly (no seal/governance path) so the
measurement isolates engine.run() and nothing else.
"""
from __future__ import annotations

import argparse
import cProfile
import io
import os
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtests.nt_runtime.compiled_study_loader import load_compiled_study
from backtests.nt_runtime.run_plan import resolve_run_plan
from backtests.nt_runtime.data_plan import resolve_data_plan
from backtests.nt_runtime.engine_builder import build_engine
from backtests.nt_runtime.modes.collect import build_collector_config_kwargs
from backtests.nt_runtime.strategy_binding import resolve_strategy_binding

STUDY = ROOT / "studies/clean_maturity_flip_model_rolling_productivity"
DATE = "2023-10-02"
TOTAL_EVENTS = 213431


def _plan():
    study_data = load_compiled_study(STUDY)
    run_plan = resolve_run_plan(study_data, stage="day", reference_date=DATE)
    data_plan = resolve_data_plan(study_data, start_date=run_plan.start_date, end_date=run_plan.end_date)
    return study_data, run_plan, data_plan


def _make_strategy(name, study_data, run_plan, data_plan):
    if name == "minimal":
        from strategies.minimal_checkpoint_collector import (
            MinimalCheckpointCollector, MinimalCheckpointCollectorConfig)
        return MinimalCheckpointCollector(MinimalCheckpointCollectorConfig(
            instrument_id=data_plan.instrument_id, bar_type_1s=data_plan.bar_type_1s,
            bar_type_1m=data_plan.bar_type_1m))
    if name == "w4":
        from strategies.w4_exit_strategy import W4ExitStrategy, W4ExitConfig
        return W4ExitStrategy(W4ExitConfig(
            instrument_id=data_plan.instrument_id, bar_type_1s=data_plan.bar_type_1s,
            bar_type_1m=data_plan.bar_type_1m, year=2023, policy="B0"))
    binding = resolve_strategy_binding(
        study_data.spec.execution.strategy_class or "flip_prediction_collector",
        study_type=study_data.spec.study.type, mode="collect")
    kwargs = build_collector_config_kwargs(binding, study_data.spec, study_data, data_plan)
    return binding.strategy_cls(binding.config_cls(**kwargs))


def run_variant(name, ablation, study_data, run_plan, data_plan, profile=False):
    prev = os.environ.get("NT_COLLECTOR_ABLATION")
    if ablation is None:
        os.environ.pop("NT_COLLECTOR_ABLATION", None)
    else:
        os.environ["NT_COLLECTOR_ABLATION"] = ablation
    try:
        engine, _ = build_engine(data_plan, log_level="ERROR")
        engine.add_strategy(_make_strategy(name, study_data, run_plan, data_plan))
        prof = cProfile.Profile() if profile else None
        t = time.perf_counter()
        if prof:
            prof.enable()
        engine.run()
        if prof:
            prof.disable()
        replay = time.perf_counter() - t
        engine.dispose()
        return replay, prof
    finally:
        if prev is None:
            os.environ.pop("NT_COLLECTOR_ABLATION", None)
        else:
            os.environ["NT_COLLECTOR_ABLATION"] = prev


VARIANTS = {
    "empty_generic": ("generic", "empty_generic"),
    "regime_state": ("generic", "regime_state"),
    "full": ("generic", "full"),
    "w4": ("w4", None),
    "minimal": ("minimal", None),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="empty_generic,w4,minimal")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--profile-out", default="")
    ap.add_argument("--top", type=int, default=35)
    args = ap.parse_args()

    study_data, run_plan, data_plan = _plan()
    for label in args.variants.split(","):
        label = label.strip()
        name, ablation = VARIANTS[label]
        times = []
        prof = None
        for _ in range(args.repeats):
            replay, prof = run_variant(name, ablation, study_data, run_plan, data_plan, args.profile)
            times.append(replay)
        best = min(times)
        med = sorted(times)[len(times) // 2]
        print(f"{label:16s} best={best:7.2f}s median={med:7.2f}s "
              f"bars/sec={TOTAL_EVENTS/med:9,.0f}  runs={times}")
        if prof is not None:
            s = io.StringIO()
            pstats.Stats(prof, stream=s).sort_stats("tottime").print_stats(args.top)
            print(s.getvalue())
            if args.profile_out:
                prof.dump_stats(args.profile_out.replace("{v}", label))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

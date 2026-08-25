"""Run the benchmark-only collector ablation matrix on one NT replay day."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtests.nt_runtime.modes import collect
import scripts.resolve_execution_manifest as execution_manifest
from research_workflow import output_manager


STUDY = ROOT / "studies/clean_maturity_flip_model_rolling_productivity"
TOTAL_EVENTS = 213431
CONTROLS = ("checkpoint_only", "baseline", "structural", "rolling", "full_no_target", "full")


def run_one(name: str, root: Path) -> dict:
    old_mode = os.environ.get("NT_COLLECTOR_ABLATION")
    os.environ["NT_COLLECTOR_ABLATION"] = name
    old_seal = collect.verify_preexec_audit_seal
    old_identity = execution_manifest.verify_frozen_execution_identity
    old_persist = output_manager.OutputManager.persist_collection
    old_build_engine = collect.build_engine
    timing = {}
    engines: list = []
    collect.verify_preexec_audit_seal = lambda *a, **k: True
    execution_manifest.verify_frozen_execution_identity = lambda *a, **k: None
    # Every ablation, including the full workload control, uses the same
    # benchmark-only no-persistence policy.  Accepted-output parity is checked
    # separately against the persisted full run.
    output_manager.OutputManager.persist_collection = (
        lambda self, candidates, observations, snapshot: {"status": "BENCHMARK_ONLY"}
    )
    def timed_build_engine(*args, **kwargs):
        engine, instrument = old_build_engine(*args, **kwargs)
        class EngineProxy:
            def __init__(self, wrapped):
                self._wrapped = wrapped
            def run(self, *r_args, **r_kwargs):
                started = time.perf_counter()
                try:
                    return self._wrapped.run(*r_args, **r_kwargs)
                finally:
                    timing["replay_seconds"] = time.perf_counter() - started
                    engines.append(self._wrapped)
            def __getattr__(self, attr):
                return getattr(self._wrapped, attr)
        return EngineProxy(engine), instrument
    collect.build_engine = timed_build_engine
    try:
        started = time.perf_counter()
        result = collect.run_collect_mode(
            study_path=STUDY, stage="day", date_override="2023-10-02",
            output_dir=root / name, log_level="ERROR",
        )
        elapsed = time.perf_counter() - started
        candidates = 0
        artifacts = result.get("output_artifacts", {})
        if artifacts.get("candidates_parquet"):
            import pandas as pd
            candidates = len(pd.read_parquet(artifacts["candidates_parquet"]))
        replay = timing.get("replay_seconds")
        return {"configuration": name, "wall_seconds": elapsed,
                "replay_seconds": replay,
                "setup_seconds": (elapsed - (replay if replay else elapsed)),
                # Throughput is reported over replay time and total NT events
                # (1s + 1m), matching scripts/benchmark_historical_same_harness.py.
                "bars_per_second": (TOTAL_EVENTS / replay) if replay else None,
                "candidates": candidates}
    finally:
        for built in engines:
            try:
                built.dispose()
            except Exception:
                pass
        collect.verify_preexec_audit_seal = old_seal
        execution_manifest.verify_frozen_execution_identity = old_identity
        output_manager.OutputManager.persist_collection = old_persist
        collect.build_engine = old_build_engine
        if old_mode is None:
            os.environ.pop("NT_COLLECTOR_ABLATION", None)
        else:
            os.environ["NT_COLLECTOR_ABLATION"] = old_mode


def main() -> int:
    """Drive the matrix with one child process per control.

    NautilusTrader initializes its Rust logger once per process and engines are
    not re-initializable after dispose, so building several engines in a single
    interpreter both panics the logger and leaves every previously-built engine
    resident during the next variant's replay.  One process per control removes
    both confounds and is what makes the variants comparable to each other and
    to scripts/benchmark_historical_same_harness.py.
    """
    root = ROOT / "runs/collector_ablations_matrix"
    root.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 2 and sys.argv[1] == "--one":
        name = sys.argv[2]
        (root / f"{name}.json").write_text(
            json.dumps(run_one(name, root), indent=2), encoding="utf-8")
        return 0

    report = {}
    for name in CONTROLS:
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--one", name],
                       check=True, cwd=str(ROOT))
        report[name] = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

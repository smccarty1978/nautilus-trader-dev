"""Record the current-runtime performance baseline (Phase 0E) as bench/baseline_v0.json.

Measurements only -- nothing here is a gate. Every run executes in its own child
process (NautilusTrader's Rust logger initializes once per process), and the parent
samples the child's RSS so peak/growth are measured from outside the replay.

Configurations (all on the same real replay day so throughput is comparable):

  floor        NT_COLLECTOR_ABLATION=empty_generic  -- engine + dispatch, callback returns immediately
  full         NT_COLLECTOR_ABLATION=full           -- representative full-surface governed collector
  smoke        real run_collect_mode with seal verification + persistence (one bounded smoke day)
  decomposition: one run each of the ablation controls, as the provider-dispatch proxy

Usage:
  python scripts/bench_baseline.py                 # writes bench/baseline_v0.json
  python scripts/bench_baseline.py --child <cfg>   # internal
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ABLATION_STUDY = ROOT / "studies/clean_maturity_flip_model_rolling_productivity"
SMOKE_STUDY = ROOT / "studies/regime_transition_target_before_stop_v1"
REPLAY_DATE = "2023-10-02"
REPEATS = 3
DECOMPOSITION = ("checkpoint_only", "baseline", "structural", "rolling", "full_no_target", "full")
OUT = ROOT / "bench" / "baseline_v0.json"
WORK = ROOT / "bench" / "_work"


def _child(cfg: str, out_path: Path) -> None:
    """Run one configuration in this process and write its measurement JSON."""
    import psutil
    from backtests.nt_runtime import telemetry as telemetry_mod
    from backtests.nt_runtime.modes import collect

    captured: dict = {}
    real_stop = telemetry_mod.CausalTelemetry.stop

    def capturing_stop(self):
        snap = real_stop(self)
        captured["snapshot"] = snap.__dict__ if hasattr(snap, "__dict__") else dict(snap)
        return snap

    telemetry_mod.CausalTelemetry.stop = capturing_stop
    collect.CausalTelemetry = telemetry_mod.CausalTelemetry

    proc = psutil.Process()
    rss_start = proc.memory_info().rss
    timing: dict = {}
    old_build = collect.build_engine
    rss_after_load: dict = {}

    def timed_build_engine(*a, **k):
        engine, instrument = old_build(*a, **k)
        rss_after_load["rss"] = proc.memory_info().rss

        class Proxy:
            def __init__(self, w): self._w = w
            def run(self, *ra, **rk):
                t0 = time.perf_counter()
                try:
                    return self._w.run(*ra, **rk)
                finally:
                    timing["replay_seconds"] = time.perf_counter() - t0
                    timing["rss_after_replay"] = proc.memory_info().rss
            def __getattr__(self, n): return getattr(self._w, n)
        return Proxy(engine), instrument

    collect.build_engine = timed_build_engine

    started = time.perf_counter()
    if cfg == "smoke":
        result = collect.run_collect_mode(
            study_path=SMOKE_STUDY, stage="day", date_override=REPLAY_DATE,
            output_dir=WORK / "smoke_runs", log_level="ERROR",
        )
    else:
        import scripts.resolve_execution_manifest as execution_manifest
        from research_workflow import output_manager
        os.environ["NT_COLLECTOR_ABLATION"] = cfg
        collect.verify_preexec_audit_seal = lambda *a, **k: True
        execution_manifest.verify_frozen_execution_identity = lambda *a, **k: None
        output_manager.OutputManager.persist_collection = (
            lambda self, candidates, observations, snapshot: {"status": "BENCHMARK_ONLY"})
        result = collect.run_collect_mode(
            study_path=ABLATION_STUDY, stage="day", date_override=REPLAY_DATE,
            output_dir=WORK / "ablation" / cfg, log_level="ERROR",
        )
    wall = time.perf_counter() - started
    snap = captured.get("snapshot", {})
    events = int(snap.get("total_bars_processed") or sum((snap.get("bars_loaded_by_tf") or {}).values()) or 0)
    replay = timing.get("replay_seconds")
    out = {
        "configuration": cfg,
        "study": str((SMOKE_STUDY if cfg == "smoke" else ABLATION_STUDY).relative_to(ROOT)).replace("\\", "/"),
        "replay_date": REPLAY_DATE,
        "wall_seconds": wall,
        "replay_seconds": replay,
        "setup_seconds": wall - (replay or 0.0),
        "events": events,
        "bars_loaded_by_tf": snap.get("bars_loaded_by_tf"),
        "callbacks_by_tf": snap.get("callbacks_by_tf"),
        "events_per_second": (events / replay) if (replay and events) else None,
        "candidates": snap.get("candidates_count"),
        "rss_mb": {
            "process_start": rss_start / 2**20,
            "after_data_load": (rss_after_load.get("rss") or 0) / 2**20,
            "after_replay": (timing.get("rss_after_replay") or 0) / 2**20,
            "telemetry_peak": snap.get("peak_process_rss_mb"),
            "growth_during_replay": ((timing.get("rss_after_replay") or 0) - (rss_after_load.get("rss") or 0)) / 2**20,
        },
        "result_status": result.get("status") if isinstance(result, dict) else None,
    }
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")


def _run_child(cfg: str, tag: str) -> dict:
    import psutil
    WORK.mkdir(parents=True, exist_ok=True)
    out_path = WORK / f"{tag}.json"
    if out_path.exists():
        out_path.unlink()
    p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", cfg, "--out", str(out_path)],
                         cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    ps = psutil.Process(p.pid)
    peak = 0
    while p.poll() is None:
        try:
            peak = max(peak, ps.memory_info().rss)
        except psutil.Error:
            break
        time.sleep(0.05)
    err = p.stderr.read() if p.stderr else ""
    if p.returncode != 0 or not out_path.exists():
        return {"configuration": cfg, "tag": tag, "failed": True, "returncode": p.returncode, "stderr_tail": err[-1500:]}
    rec = json.loads(out_path.read_text(encoding="utf-8"))
    rec["tag"] = tag
    rec["rss_mb"]["parent_sampled_peak"] = peak / 2**20
    return rec


def _agg(runs: list[dict], key: str) -> dict | None:
    vals = [r.get(key) for r in runs if isinstance(r.get(key), (int, float))]
    if not vals:
        return None
    return {"n": len(vals), "mean": statistics.fmean(vals), "min": min(vals), "max": max(vals),
            "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child"); ap.add_argument("--out"); ap.add_argument("--repeats", type=int, default=REPEATS)
    ap.add_argument("--skip-smoke", action="store_true"); ap.add_argument("--skip-decomposition", action="store_true")
    a = ap.parse_args()
    if a.child:
        _child(a.child, Path(a.out)); return 0

    import nautilus_trader
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    report: dict = {
        "schema_version": 1, "kind": "performance_baseline", "status": "MEASUREMENT_ONLY_NOT_A_GATE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "git_head": head,
        "environment": {"python": platform.python_version(), "nautilus_trader": nautilus_trader.__version__,
                        "platform": platform.platform(), "cpu_count": os.cpu_count()},
        "method": __doc__.strip().splitlines()[0],
        "repeats": a.repeats, "series": {}, "decomposition": {},
    }
    for cfg in ("floor:empty_generic", "full:full", "smoke:smoke"):
        label, mode = cfg.split(":")
        if mode == "smoke" and a.skip_smoke:
            continue
        runs = [_run_child(mode, f"{label}_{i+1}") for i in range(a.repeats)]
        report["series"][label] = {
            "mode": mode, "runs": runs,
            "events_per_second": _agg(runs, "events_per_second"),
            "replay_seconds": _agg(runs, "replay_seconds"),
            "wall_seconds": _agg(runs, "wall_seconds"),
            "peak_rss_mb": _agg([{"v": (r.get("rss_mb") or {}).get("parent_sampled_peak")} for r in runs], "v"),
            "rss_growth_during_replay_mb": _agg([{"v": (r.get("rss_mb") or {}).get("growth_during_replay")} for r in runs], "v"),
        }
        print(label, json.dumps(report["series"][label]["events_per_second"]))
    if not a.skip_decomposition:
        for mode in DECOMPOSITION:
            rec = _run_child(mode, f"decomp_{mode}")
            report["decomposition"][mode] = {k: rec.get(k) for k in ("replay_seconds", "events_per_second", "candidates", "failed", "stderr_tail")}
            print("decomp", mode, rec.get("events_per_second"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

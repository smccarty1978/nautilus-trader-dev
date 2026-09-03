#!/usr/bin/env python3
"""Measure the platform-v2 host on the same replay day as ``bench/baseline_v0.json``.

Each run executes in its own child process (the NT logger is process-global); the parent
samples the child's RSS.  Series:

  host_c    the Shape C composition (13 features + 3 barrier arms) -- the baseline's "full" workload
  host_a    the Shape A composition (flip label)
  golden    the golden fixture (engine run) as the synthetic floor

Results are measurements, not gates: ``bench/baseline_v1_host.json`` records mean/min/max/
stdev over the repeats next to the v0 numbers and the per-tracker dispatch profile from one
instrumented run (``bench/providers.json``).

    python scripts/bench_host.py [--repeats 3] [--series host_c,host_a,golden]
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
MAIN_REPO = ROOT.parent / "Nautilus Trader"
REPLAY_DATE = "2023-10-02"
OUT = ROOT / "bench" / "baseline_v1_host.json"
WORK = ROOT / "bench" / "_work"
SPECS = {"host_c": ROOT / "fixtures/parity/shape_c/study.yaml", "host_a": ROOT / "fixtures/parity/shape_a/study.yaml"}


def _child(cfg: str, out_path: Path, profile: bool) -> None:
    import psutil
    from research_workflow.grammar import compile_study, load_spec
    proc = psutil.Process()
    rss_start = proc.memory_info().rss
    if cfg == "golden":
        from research_workflow.host.interfaces import BarView
        from research_workflow.host_runner import run_plan_with_engine
        from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
        G = ROOT / "fixtures" / "golden"
        bars = [BarView(**b) for b in json.loads((G / "bars.json").read_text(encoding="utf-8"))]
        exp = json.loads((G / "expected.json").read_text(encoding="utf-8"))
        NS = 10 ** 9
        spec = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in exp["sessions"]]}
        plan = compile_study(load_spec(G / "study_barrier.yaml"), repo_root=ROOT, datasets_dir=G / "datasets", extra_bindings=SYNTHETIC_BINDINGS).plan.to_dict()
        rss_load = proc.memory_info().rss
        run = run_plan_with_engine(plan, bars, session_table_spec=spec)
        replay = run["elapsed_s"]; stats = run["stats"]
    else:
        from research_workflow.host_runner import run_plan_on_catalog
        plan = compile_study(load_spec(SPECS[cfg]), repo_root=ROOT).plan.to_dict()
        if profile:
            os.environ["NT_HOST_PROFILE"] = "1"
        rss_load = proc.memory_info().rss
        run = run_plan_on_catalog(plan, start_date=REPLAY_DATE, end_date=REPLAY_DATE, repo_root=MAIN_REPO, studies_root=MAIN_REPO / "studies")
        replay = run["elapsed_s"]; stats = run["stats"]
    rss_end = proc.memory_info().rss
    events = int(stats["bars"])
    out = {"configuration": cfg, "replay_date": REPLAY_DATE, "replay_seconds": replay, "events": events,
           "events_per_second": events / replay if replay else None, "candidates": stats.get("candidates"),
           "bars_by_stream": stats.get("bars_by_stream"), "profile": stats.get("profile"),
           "rss_mb": {"process_start": rss_start / 2 ** 20, "after_data_load": rss_load / 2 ** 20, "after_replay": rss_end / 2 ** 20,
                      "growth_during_replay": (rss_end - rss_load) / 2 ** 20}}
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")


def _run_child(cfg: str, tag: str, profile: bool = False) -> dict:
    import psutil
    WORK.mkdir(parents=True, exist_ok=True)
    out_path = WORK / f"{tag}.json"
    if out_path.exists():
        out_path.unlink()
    args = [sys.executable, str(Path(__file__).resolve()), "--child", cfg, "--out", str(out_path)] + (["--profile"] if profile else [])
    p = subprocess.Popen(args, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
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
    rec["rss_mb"]["parent_sampled_peak"] = peak / 2 ** 20
    return rec


def _agg(runs, key):
    vals = [r.get(key) for r in runs if isinstance(r.get(key), (int, float))]
    if not vals:
        return None
    return {"n": len(vals), "mean": statistics.fmean(vals), "min": min(vals), "max": max(vals), "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child"); ap.add_argument("--out"); ap.add_argument("--profile", action="store_true")
    ap.add_argument("--repeats", type=int, default=3); ap.add_argument("--series", default="host_c,host_a,golden")
    a = ap.parse_args()
    if a.child:
        _child(a.child, Path(a.out), a.profile); return 0
    import nautilus_trader
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    baseline = json.loads((ROOT / "bench" / "baseline_v0.json").read_text(encoding="utf-8"))
    report = {"schema_version": 1, "kind": "performance_measurement_v1_host", "status": "MEASUREMENT_ONLY_NOT_A_GATE",
              "generated_at_utc": datetime.now(timezone.utc).isoformat(), "git_head": head,
              "environment": {"python": platform.python_version(), "nautilus_trader": nautilus_trader.__version__, "platform": platform.platform(), "cpu_count": os.cpu_count()},
              "baseline_v0": {"full_events_per_second": baseline["series"]["full"]["events_per_second"], "full_replay_seconds": baseline["series"]["full"]["replay_seconds"],
                              "full_peak_rss_mb": baseline["series"]["full"]["peak_rss_mb"], "full_rss_growth_mb": baseline["series"]["full"]["rss_growth_during_replay_mb"],
                              "floor_events_per_second": baseline["series"]["floor"]["events_per_second"], "decomposition": baseline.get("decomposition"),
                              "target_runtime_share_before": "~92% of replay (32.9k -> 2.7k events/s)"},
              "repeats": a.repeats, "series": {}}
    for label in [s.strip() for s in a.series.split(",") if s.strip()]:
        runs = [_run_child(label, f"{label}_{i + 1}") for i in range(a.repeats)]
        report["series"][label] = {"runs": runs, "events_per_second": _agg(runs, "events_per_second"), "replay_seconds": _agg(runs, "replay_seconds"),
                                   "peak_rss_mb": _agg([{"v": (r.get("rss_mb") or {}).get("parent_sampled_peak")} for r in runs], "v"),
                                   "rss_growth_during_replay_mb": _agg([{"v": (r.get("rss_mb") or {}).get("growth_during_replay")} for r in runs], "v")}
        print(label, json.dumps(report["series"][label]["events_per_second"]))
    if "host_c" in report["series"]:
        prof = _run_child("host_c", "host_c_profile", profile=True)
        report["profile"] = prof.get("profile")
        (ROOT / "bench" / "providers.json").write_text(json.dumps({"generated_at_utc": report["generated_at_utc"], "git_head": head, "replay_date": REPLAY_DATE,
                                                                   "configuration": "host_c", "profile": prof.get("profile")}, indent=2, default=str), encoding="utf-8")
        full = report["baseline_v0"]["full_events_per_second"]["mean"]
        new = (report["series"]["host_c"]["events_per_second"] or {}).get("mean")
        report["delta"] = {"host_c_vs_baseline_full_events_per_second": (new / full if new and full else None),
                           "target_runtime_share_after": (prof.get("profile") or {}).get("share", {}).get("outcome_kernel")}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

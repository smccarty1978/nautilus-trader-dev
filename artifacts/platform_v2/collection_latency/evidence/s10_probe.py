"""S1.0 throughput probe: one full-year partition (same harness), sampling progress.json every 10 s."""
import sys, json, time, threading, os
from pathlib import Path
ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader"); sys.path.insert(0, str(ROOT))
PLAN = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-supv1_shape_a_flip_180s_r2\studies\supv1_shape_a_flip_180s_r2\compiled_plan.json")
OUT = Path(sys.argv[1]); PROG = OUT.with_suffix(".progress.json"); SAMPLES = OUT.with_suffix(".samples.jsonl")
import pandas as pd, psutil
from research_workflow.host_runner import run_plan_on_catalog
plan = json.loads(PLAN.read_text(encoding="utf-8"))
start, end = "2021-01-01", "2021-12-31"
s = int(pd.Timestamp(start, tz="UTC").value); e = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)).value)
stop = threading.Event(); proc = psutil.Process()
def sampler():
    last = None
    with open(SAMPLES, "a", encoding="utf-8") as f:
        while not stop.is_set():
            try:
                d = json.loads(PROG.read_text(encoding="utf-8"))
                if d != last:
                    d = {**d, "wall": time.time(), "rss_mb": proc.memory_info().rss / 1e6}
                    f.write(json.dumps(d) + "\n"); f.flush(); last = {k: v for k, v in d.items() if k not in ("wall", "rss_mb")}
            except Exception:
                pass
            stop.wait(10)
t = threading.Thread(target=sampler, daemon=True); t.start()
t0 = time.time()
r = run_plan_on_catalog(plan, start_date=start, end_date=end, repo_root=ROOT, primary_interval=(s, e), warmup_days=5,
                        progress_path=PROG, progress_every_bars=100_000)
stop.set(); t.join(timeout=15)
OUT.write_text(json.dumps({"wall_total_s": time.time() - t0, "engine_run_s": r["elapsed_s"], "stats": r["stats"],
                           "rows": {"candidates": int(len(r["candidates"]))}, "peak_rss_mb": proc.memory_info().peak_wset / 1e6 if hasattr(proc.memory_info(), "peak_wset") else None,
                           "plan_sha256": plan["plan_sha256"]}, indent=1, default=str), encoding="utf-8")

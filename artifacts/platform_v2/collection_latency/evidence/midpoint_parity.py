"""Parity gate for the bounded midpoint buffer: replay the sealed supv1_shape_a_flip_180s_r2 TRAIN 2021 partition
through the same harness (host_runner.run_plan_on_catalog, the compiled plan read-only) under the chore branch,
persist candidates/observations exactly as _persist does (to_parquet(index=False)) and compare sha256 against the
sealed partition manifest. Throughput is sampled every 10 s as a secondary observation."""
import sys, json, time, threading, hashlib
from pathlib import Path
ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-collection_latency"); sys.path.insert(0, str(ROOT))
SEALED = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-supv1_shape_a_flip_180s_r2\studies\supv1_shape_a_flip_180s_r2")
OUT = Path(sys.argv[1]); PROG = OUT.with_suffix(".progress.json"); SAMPLES = OUT.with_suffix(".samples.jsonl"); WORK = OUT.parent / "midpoint_parity_out"
import pandas as pd, psutil
from research_workflow.host_runner import run_plan_on_catalog
import research_workflow.provider_host as ph

plan = json.loads((SEALED / "compiled_plan.json").read_text(encoding="utf-8"))
sealed = json.loads((SEALED / "_work/controller/partitions/train/2021/manifest.json").read_text(encoding="utf-8"))
start, end = "2021-01-01", "2021-12-31"   # whole-year partition: run_end == primary_end because 2022 is not a train/dev year
s = int(pd.Timestamp(start, tz="UTC").value); e = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)).value)
stop = threading.Event(); proc = psutil.Process()
def sampler():
    last = None
    with open(SAMPLES, "w", encoding="utf-8") as f:
        while not stop.is_set():
            try:
                d = json.loads(PROG.read_text(encoding="utf-8"))
                key = {k: v for k, v in d.items()}
                if key != last:
                    f.write(json.dumps({**d, "wall": time.time(), "rss_mb": proc.memory_info().rss / 1e6}) + "\n"); f.flush(); last = key
            except Exception:
                pass
            stop.wait(10)
t = threading.Thread(target=sampler, daemon=True); t.start()
t0 = time.perf_counter()
r = run_plan_on_catalog(plan, start_date=start, end_date=end, repo_root=ROOT, primary_interval=(s, e), warmup_days=5,
                        progress_path=PROG, progress_every_bars=100_000)
wall = time.perf_counter() - t0
stop.set(); t.join(timeout=15)
WORK.mkdir(parents=True, exist_ok=True)
c, o = WORK / "candidates.parquet", WORK / "observations.parquet"
r["candidates"].to_parquet(c, index=False); r["observations"].to_parquet(o, index=False)
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
res = {"midpoint_history": ph.ContextAdapter.MIDPOINT_HISTORY,
       "wall_total_s": wall, "engine_run_s": r["elapsed_s"], "stats": r["stats"], "rows": {"candidates": int(len(r["candidates"])), "observations": int(len(r["observations"]))},
       "sealed": {"candidates_sha256": sealed["candidates_sha256"], "observations_sha256": sealed["observations_sha256"], "rows": sealed["rows"], "elapsed_s": sealed.get("elapsed_s"), "plan_sha256": sealed["plan_sha256"]},
       "replayed": {"candidates_sha256": sha(c), "observations_sha256": sha(o)}}
res["byte_identical"] = res["replayed"]["candidates_sha256"] == sealed["candidates_sha256"] and res["replayed"]["observations_sha256"] == sealed["observations_sha256"]
OUT.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: res[k] for k in ("byte_identical", "wall_total_s", "engine_run_s", "rows")}))

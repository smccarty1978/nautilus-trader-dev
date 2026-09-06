"""W0.4 same-harness throughput: host_runner.run_plan_on_catalog (the exact code path a V2 partition uses)
on one representative RTH month, using a closed study's compiled plan read-only. Output to scratchpad only."""
import sys, json, time, cProfile, pstats, io, os
from pathlib import Path
ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader"); sys.path.insert(0, str(ROOT))
PLAN = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-supv1_shape_a_flip_180s_r2\studies\supv1_shape_a_flip_180s_r2\compiled_plan.json")
OUT = Path(sys.argv[1])
import pandas as pd
from research_workflow.host_runner import run_plan_on_catalog
plan = json.loads(PLAN.read_text(encoding="utf-8"))
start, end = "2021-03-01", "2021-03-31"
s = int(pd.Timestamp(start, tz="UTC").value); e = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)).value)
def once(profile):
    pr = cProfile.Profile() if profile else None
    t0 = time.perf_counter()
    if pr: pr.enable()
    r = run_plan_on_catalog(plan, start_date=start, end_date=end, repo_root=ROOT, primary_interval=(s, e), warmup_days=5)
    if pr: pr.disable()
    wall = time.perf_counter() - t0
    out = {"profile": profile, "wall_total_s": wall, "engine_run_s": r["elapsed_s"], "stats": r["stats"],
           "rows": {"candidates": int(len(r["candidates"])), "observations": int(len(r["observations"]))},
           "bars_per_s": r["stats"]["bars"] / r["elapsed_s"], "epochs_per_s": r["stats"]["epochs"] / r["elapsed_s"], "dataset": r["dataset"]}
    if pr:
        sio = io.StringIO(); ps = pstats.Stats(pr, stream=sio); ps.sort_stats("cumulative").print_stats(60); out["cumulative_top60"] = sio.getvalue()
        sio = io.StringIO(); ps = pstats.Stats(pr, stream=sio); ps.sort_stats("tottime").print_stats(60); out["tottime_top60"] = sio.getvalue()
    return out
res = {"plan_sha256": plan["plan_sha256"], "study": "supv1_shape_a_flip_180s_r2 (read-only plan)", "window": [start, end],
       "note": "host contended: one V2 partition child + one broad pytest run active during measurement", "runs": []}
res["runs"].append(once(False)); OUT.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")

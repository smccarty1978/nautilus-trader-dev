"""chunked_sink_flush harness orchestrator: launches collect.py then verify.py, each in its own
fresh subprocess (so each phase's peak RSS is measured independently and the NT engine's
Rust logger, which can only initialize once per process, never collides across variants),
each under its own 8 GiB watchdog (default; override with --watchdog-gib). Enforces the
2022-only causal data scope from the REPLAYED bar range collect.py actually recorded (not the
requested window) -- fails loudly, does not silently truncate or retry.

Usage:
  python run_watched.py --repo-root <worktree> --start 2022-01-10 --end 2022-02-09 \
      --out-dir <dir> --batch-bytes 268435456 --result <combined.json>
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent

ap = argparse.ArgumentParser()
ap.add_argument("--repo-root", required=True)
ap.add_argument("--start", required=True)
ap.add_argument("--end", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--batch-bytes", type=int, default=256 * 1024 * 1024)
ap.add_argument("--batch-rows", type=int, default=100_000)
ap.add_argument("--profile", action="store_true", default=True)
ap.add_argument("--no-profile", dest="profile", action="store_false")
ap.add_argument("--watchdog-gib", type=float, default=8.0)
ap.add_argument("--result", required=True, help="combined result JSON path")
a = ap.parse_args()

LIMIT = int(a.watchdog_gib * 2**30)
out_dir = Path(a.out_dir)
out_dir.mkdir(parents=True, exist_ok=True)


def run_watched(cmd, log_path):
    log = open(log_path, "w")
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=a.repo_root, stdout=log, stderr=subprocess.STDOUT)
    pp = psutil.Process(p.pid)
    peak = 0
    killed = False
    while p.poll() is None:
        try:
            r = pp.memory_info().rss + sum(c.memory_info().rss for c in pp.children(recursive=True))
        except psutil.Error:
            r = 0
        peak = max(peak, r)
        if r > LIMIT:
            for c in pp.children(recursive=True):
                c.kill()
            p.kill()
            killed = True
            break
        time.sleep(0.1)
    p.wait()
    return {"cmd": cmd, "returncode": p.returncode, "watchdog_killed": killed,
            "watchdog_peak_rss_bytes": peak, "wall_s": time.time() - t0}


def main():
    collect_out = out_dir / "collect_result.json"
    collect_log = out_dir / "collect.log"
    wd_collect = run_watched(
        [sys.executable, str(HERE / "collect.py"), "--repo-root", a.repo_root, "--start", a.start,
         "--end", a.end, "--out", str(collect_out), "--out-dir", str(out_dir / "partition"),
         "--batch-bytes", str(a.batch_bytes), "--batch-rows", str(a.batch_rows)]
        + ([] if a.profile else ["--no-profile"]),
        collect_log)

    combined = {"collect_watchdog": wd_collect, "window_requested": [a.start, a.end],
                "batch_bytes": a.batch_bytes, "batch_rows": a.batch_rows, "profile": a.profile}

    if wd_collect["watchdog_killed"] or wd_collect["returncode"] != 0 or not collect_out.exists():
        combined["STATUS"] = "COLLECT_FAILED"
        json.dump(combined, open(a.result, "w"), indent=1, default=str)
        print(json.dumps({"STATUS": "COLLECT_FAILED", "watchdog": wd_collect}))
        return 1

    collected = json.load(open(collect_out))
    combined["collect"] = collected

    # Causal data scope (hard): the REPLAYED range must stay inside 2022, regardless of the
    # requested --start/--end (run_plan_on_catalog's default 5-day warmup can silently extend
    # replay backward past a requested start date).
    rng = collected["replayed_bar_range"]
    first_iso = rng["first_bar_iso"]
    last_iso = rng["last_bar_iso"]
    lo = datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc)
    hi = datetime.datetime(2022, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
    first_dt = datetime.datetime.fromisoformat(first_iso) if first_iso else None
    last_dt = datetime.datetime.fromisoformat(last_iso) if last_iso else None
    scope_ok = bool(first_dt and last_dt and lo <= first_dt and last_dt <= hi)
    combined["causal_data_scope"] = {"first_bar_iso": first_iso, "last_bar_iso": last_iso,
                                      "PASS": scope_ok}
    if not scope_ok:
        combined["STATUS"] = "CAUSAL_DATA_SCOPE_VIOLATION"
        json.dump(combined, open(a.result, "w"), indent=1, default=str)
        print(json.dumps({"STATUS": "CAUSAL_DATA_SCOPE_VIOLATION", "replayed_bar_range": rng}))
        return 1

    verify_out = out_dir / "verify_result.json"
    verify_log = out_dir / "verify.log"
    wd_verify = run_watched(
        [sys.executable, str(HERE / "verify.py"), "--repo-root", a.repo_root,
         "--collect-result", str(collect_out), "--parquet", str(out_dir / "partition" / "candidates.parquet"),
         "--out", str(verify_out)],
        verify_log)
    combined["verify_watchdog"] = wd_verify
    if verify_out.exists():
        combined["verify"] = json.load(open(verify_out))
    combined["STATUS"] = "OK" if not wd_verify["watchdog_killed"] and wd_verify["returncode"] == 0 else "VERIFY_FAILED"
    json.dump(combined, open(a.result, "w"), indent=1, default=str)
    print(json.dumps({
        "STATUS": combined["STATUS"],
        "collect_peak_gib": collected["peak_rss_bytes"] / 2**30,
        "collect_phase_peaks_gib": {k: round(v["rss"] / 2**30, 3) for k, v in collected["phase_peaks"].items()},
        "verify_peak_gib": (combined.get("verify", {}).get("peak_rss_bytes", 0) or 0) / 2**30,
        "verify_matches_manifest": combined.get("verify", {}).get("matches_manifest"),
        "rows": collected["rows"], "flushes": collected["flushes"],
        "row_groups": collected["footer"]["num_row_groups"],
        "replayed_bar_range": rng,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

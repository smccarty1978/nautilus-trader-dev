"""chunked_sink_flush harness -- VERIFICATION phase, in its OWN process, separate from collect.py.

Calls ``recompute_logical_content_sha256`` (the Task A bytes-bounded streaming fix) against a
finalized partition's ``candidates.parquet`` and compares it to the ``logical_content_sha256``
recorded in ``collect.py``'s result JSON. Measures THIS process's own peak RSS -- a process
that does nothing but import, open the file, and recompute -- so the recompute's own memory
footprint can never be attributed to (or hidden inside) the collection/replay measurement.
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import threading
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--repo-root", required=True)
ap.add_argument("--collect-result", required=True, help="collect.py's --out JSON path")
ap.add_argument("--parquet", required=True, help="candidates.parquet path to verify")
ap.add_argument("--out", required=True)
a = ap.parse_args()

repo_root = Path(a.repo_root)
sys.path.insert(0, str(repo_root))

import psutil  # noqa: E402

from research_workflow.host.chunked_writer import recompute_logical_content_sha256  # noqa: E402

proc = psutil.Process()
trace = []
stop = {"flag": False}


def rss() -> int:
    return proc.memory_info().rss


def sampler():
    while not stop["flag"]:
        trace.append({"t": time.perf_counter(), "rss": rss(), "phase": "verification"})
        time.sleep(0.05)


def main():
    collected = json.load(open(a.collect_result))
    manifest = collected["candidates_manifest"]
    columns = manifest["columns"]
    expected = manifest["logical_content_sha256"]

    gc.collect()
    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    t0 = time.perf_counter()
    rss_before = rss()
    got = recompute_logical_content_sha256(Path(a.parquet), columns)
    elapsed = time.perf_counter() - t0
    rss_after = rss()
    stop["flag"] = True
    th.join(timeout=2)
    peak = max((s["rss"] for s in trace), default=max(rss_before, rss_after))

    result = {
        "parquet": a.parquet,
        "matches_manifest": got == expected,
        "recomputed_sha256": got,
        "manifest_sha256": expected,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "peak_rss_bytes": peak,
        "elapsed_s": elapsed,
        "rows": manifest["rows"],
    }
    json.dump(result, open(a.out, "w"), indent=1, default=str)
    print(json.dumps({"matches_manifest": result["matches_manifest"], "peak_gib": peak / 2**30,
                      "elapsed_s": elapsed, "rows": manifest["rows"]}))


if __name__ == "__main__":
    main()

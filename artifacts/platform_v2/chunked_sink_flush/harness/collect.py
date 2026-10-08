"""chunked_sink_flush harness -- REPLAY/FINALIZE phase, no verification in this process.

Session-3 diagnosis (diag2/DIAGNOSIS.md) found that an EARLIER version of this harness called
``recompute_logical_content_sha256`` right after ``finalize()``, INSIDE the sampled RSS window,
and that whole-file read-back (not collection) produced the 2.6/4.4/12.8 GiB "collection" peaks
previously recorded in ``rss_curve.json``. This script never calls recompute at all -- that is
``verify.py``'s job, run as its own separate process by ``run_watched.py`` -- so a collection-only
peak RSS measured here cannot be contaminated by the read-back step by construction, not by
discipline.

Adapted from the diag2 scratch harness (``probe.py``/``launch.py``), trimmed to the one
production-shaped variant this chore's packet asks for: nine real
``tracker.volume_profile.rolling`` instances ({range_uniform, full_per_tick, close} x
{120, 360, 1440} open minutes), ``emit_profile: true`` on every instance, descriptive
(``outcome: none``), ``completed_1m`` cadence, through the real ``compile_study`` ->
``run_plan_on_catalog`` -> chunked-writer path -- no bespoke collector.

Records, per the packet's causal-scope requirement: the ACTUAL first/last replayed bar
timestamp (from ``HostCore._epoch``'s own ``T`` argument -- nanoseconds since the Unix epoch,
UTC -- not the requested --start/--end), so a caller can assert the replay never touched 2021
tape even though ``run_plan_on_catalog``'s default 5-day warmup can silently extend a window's
replay backward past a requested start date.
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
ap.add_argument("--start", required=True)
ap.add_argument("--end", required=True)
ap.add_argument("--out", required=True, help="result JSON path")
ap.add_argument("--out-dir", required=True, help="where candidates.parquet/observations.parquet land")
ap.add_argument("--batch-bytes", type=int, default=256 * 1024 * 1024, help="module default unless overridden")
ap.add_argument("--batch-rows", type=int, default=100_000)
ap.add_argument("--profile", action="store_true", default=True)
ap.add_argument("--no-profile", dest="profile", action="store_false")
ap.add_argument("--flush-sample-every", type=int, default=1, help="record RSS at every Nth post_emit flush")
a = ap.parse_args()

repo_root = Path(a.repo_root)
sys.path.insert(0, str(repo_root))

import psutil  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from research_workflow.grammar.compiler import compile_study  # noqa: E402
from research_workflow.host_runner import run_plan_on_catalog  # noqa: E402
from research_workflow.host.chunked_writer import ChunkedParquetWriter  # noqa: E402
from research_workflow.host import strategy as host_strategy  # noqa: E402
from research_workflow.host.strategy import plan_output_columns, declared_metadata_types  # noqa: E402

DS = "NQ_1S_V2_GLOBEX"


def build_spec() -> dict:
    allocs = ["range_uniform", "full_per_tick", "close"]
    horizons = [120, 360, 1440]
    combos = [(h, al) for h in horizons for al in allocs]
    context, metadata = {}, {}
    for i, (h, al) in enumerate(combos):
        name = f"vp{i}"
        context[name] = {"tracker": "volume_profile.rolling", "bars": "1s", "dataset": DS,
                         "horizon_open_minutes": h, "allocation": al, "emit_profile": a.profile}
        if a.profile:
            metadata[f"profile_{i}"] = f"{name}.profile"
        metadata[f"poc_{i}"] = f"{name}.poc"
    return {
        "study": {"id": "chunked_sink_flush_harness", "tier": 2, "question": "collection-side bounded memory"},
        "streams": [{"dataset": DS, "timeframes": ["1s", "1m"]}],
        "context": context,
        "population": {"session": "RTH", "cadence": "completed_1m"},
        "triggers": "every_candidate",
        "features": {"metadata": metadata},
        "outcome": "none",
        "chronology": {"train": [2022], "dev": [], "prohibited": [2025, 2026]},
        "model": "none",
    }


proc = psutil.Process()
trace = []
stop = {"flag": False}
state = {"phase": "init", "epochs": 0, "min_T": None, "max_T": None}


def rss() -> int:
    return proc.memory_info().rss


def mark(event, extra=None):
    trace.append({"t": time.perf_counter(), "rss": rss(), "event": event, "phase": state["phase"],
                  "epochs": state["epochs"], "extra": extra or {}})


def sampler():
    while not stop["flag"]:
        try:
            trace.append({"t": time.perf_counter(), "rss": rss(), "event": "poll", "phase": state["phase"],
                          "epochs": state["epochs"]})
        except Exception:
            pass
        time.sleep(0.05)


_orig_epoch = host_strategy.HostCore._epoch
flush_marks = {"n": 0}


def _epoch_wrapper(self, bar, T, grid_index):
    state["epochs"] += 1
    Ti = int(T)
    if state["min_T"] is None or Ti < state["min_T"]:
        state["min_T"] = Ti
    if state["max_T"] is None or Ti > state["max_T"]:
        state["max_T"] = Ti
    return _orig_epoch(self, bar, T, grid_index)


host_strategy.HostCore._epoch = _epoch_wrapper


def phase_peaks():
    out = {}
    for s in trace:
        p = s["phase"]
        if p not in out or s["rss"] > out[p]["rss"]:
            out[p] = {"rss": s["rss"], "epochs": s["epochs"], "event": s["event"]}
    return out


def ns_to_iso(ns):
    if ns is None:
        return None
    import datetime
    return datetime.datetime.fromtimestamp(ns / 1e9, tz=datetime.timezone.utc).isoformat()


def main():
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = compile_study(build_spec(), repo_root=repo_root)
    if not res.ok:
        json.dump({"STATUS": "COMPILE_FAILED", "gaps": res.gaps.to_dict()}, open(a.out, "w"), default=str)
        return
    plan = res.plan.to_dict()
    cand_cols, obs_cols = plan_output_columns(plan)
    identity_cols = set(plan["columns"]["identity"])
    declared_meta = declared_metadata_types(plan)
    declared_cand = ({c: pa.int64() for c in identity_cols} | declared_meta
                     | {c: pa.float64() for c in (plan["columns"].get("features") or []) if c not in declared_meta})
    declared_obs = {c: pa.int64() for c in identity_cols if c in obs_cols}

    def on_flush(event, info):
        if event == "post_emit":
            flush_marks["n"] += 1
            if flush_marks["n"] % a.flush_sample_every == 0:
                mark("flush_post_emit", info)

    cand_w = ChunkedParquetWriter(out_dir / "candidates.parquet", cand_cols, declared_types=declared_cand,
                                  batch_rows=a.batch_rows, batch_bytes=a.batch_bytes, on_flush=on_flush)
    obs_w = ChunkedParquetWriter(out_dir / "observations.parquet", obs_cols, declared_types=declared_obs,
                                 batch_rows=a.batch_rows, batch_bytes=a.batch_bytes)

    gc.collect()
    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    state["phase"] = "setup"
    mark("start")
    state["phase"] = "replay"
    mark("replay_start")
    t0 = time.perf_counter()
    run = run_plan_on_catalog(plan, start_date=a.start, end_date=a.end, repo_root=repo_root,
                              chunked_writers=(cand_w, obs_w), chunked_flush_every=a.batch_rows,
                              chunked_flush_bytes=a.batch_bytes)
    replay_s = time.perf_counter() - t0
    state["phase"] = "post_replay"
    mark("run_return")
    state["phase"] = "finalize"
    mark("finalize_start")
    cand_m = cand_w.finalize()
    obs_m = obs_w.finalize()
    mark("finalize_end")
    state["phase"] = "post_finalize"
    mark("post_finalize")
    md = pq.ParquetFile(str(out_dir / "candidates.parquet")).metadata
    footer = {"num_row_groups": md.num_row_groups, "num_leaf_columns": md.num_columns,
              "footer_serialized_bytes": md.serialized_size,
              "file_bytes": (out_dir / "candidates.parquet").stat().st_size,
              "mean_row_group_bytes": (sum(md.row_group(i).total_byte_size for i in range(md.num_row_groups))
                                        / max(1, md.num_row_groups)),
              "mean_rows_per_row_group": md.num_rows / max(1, md.num_row_groups)}
    state["phase"] = "end"
    mark("end")
    stop["flag"] = True
    th.join(timeout=2)
    peak = max(trace, key=lambda s: s["rss"])
    pp = phase_peaks()
    rep = [s for s in trace if s["phase"] == "replay"]
    step = max(1, len(rep) // 400)
    curve = [max(rep[i:i + step], key=lambda s: s["rss"]) for i in range(0, len(rep), step)]
    result = {
        "requested_window": [a.start, a.end],
        "batch_rows": a.batch_rows, "batch_bytes": a.batch_bytes, "profile": a.profile,
        "rows": {"candidates": cand_m["rows"], "observations": obs_m["rows"]},
        "flushes": cand_m["batches"],
        "epochs": state["epochs"],
        "replayed_bar_range": {
            "first_bar_ns": state["min_T"], "last_bar_ns": state["max_T"],
            "first_bar_iso": ns_to_iso(state["min_T"]), "last_bar_iso": ns_to_iso(state["max_T"]),
        },
        "stats": run.get("stats"),
        "replay_s": replay_s,
        "peak_rss_bytes": peak["rss"], "peak_at": {k: peak[k] for k in ("phase", "event", "epochs")},
        "phase_peaks": pp,
        "footer": footer,
        "candidates_manifest": cand_m,
        "observations_manifest": obs_m,
        "flush_cycle_rss_series": [{"epochs": s["epochs"], "rss_bytes": s["rss"], "batches_written": s["extra"].get("batches_written")}
                                    for s in trace if s["event"] == "flush_post_emit"],
        "replay_curve": [{"t": s["t"], "rss_bytes": s["rss"], "epochs": s["epochs"]} for s in curve],
    }
    json.dump(result, open(a.out, "w"), indent=1, default=str)
    print(json.dumps({
        "peak_gib": peak["rss"] / 2**30, "peak_phase": peak["phase"],
        "phase_peaks_gib": {k: round(v["rss"] / 2**30, 3) for k, v in pp.items()},
        "rows": result["rows"], "flushes": result["flushes"],
        "replayed_bar_range": result["replayed_bar_range"],
        "row_groups": footer["num_row_groups"],
    }))


if __name__ == "__main__":
    main()

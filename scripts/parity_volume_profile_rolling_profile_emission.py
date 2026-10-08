"""Real-tape parity + size/memory measurement for tracker.volume_profile.rolling's typed
``profile`` emission (G2, D1/D2 repair).

Runs the live kernel over real 1s bars (two 4-day windows: a baseline and a high-activity CPI
week, both picked by raw bar volume, never by outcomes), flushes every snapshot through the REAL
host sink (``research_workflow.host.sink.ColumnarBuffer``) to a parquet file, reads it back, and
reconstructs every scalar output from the typed struct alone. Also measures peak RSS of a
9-kernel (3 allocations x {120, 360, 1440}) collection-style run and the consecutive-snapshot
redundancy of the raw weight vector.

Only 2022 / 2023dev tape may ever be opened here (never 2021 or after 2023-10-17).

    python scripts/parity_volume_profile_rolling_profile_emission.py --out artifacts/parity/volume_profile_rolling_profile_emission.json
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import parity_volume_profile_rolling as P  # noqa: E402
from features.trackers.volume_profile_rolling import MIN_NS, VolumeProfileKernel, VolumeProfileSnapshot, open_minute_ends  # noqa: E402
from research_workflow.host.sink import ColumnarBuffer  # noqa: E402

ALLOCATIONS = ("range_uniform", "full_per_tick", "close")
HORIZONS = (120, 360, 1440)
WINDOWS = {
    "2022-02-01_04_baseline": ("2022-02-01", "2022-02-04"),
    # picked by raw bar volume (2022-10-13 is the 3rd highest single-day volume of 2022 -- the
    # September CPI print release day), never by any trade/outcome measure.
    "2022-10-11_14_cpi_high_activity": ("2022-10-11", "2022-10-14"),
}


def _calendar():
    ref = P.dataset_v2.load_reference_tables(P.CATALOG, ["sessions", "rolls"])
    s = ref["sessions"].copy()
    s["session_date"] = s.session_date.astype(str)
    s = s[s.close_ns <= P.DEV_END].sort_values("open_ns").reset_index(drop=True)
    om = open_minute_ends(s.open_ns.to_numpy(), s.close_ns.to_numpy())
    rolls = np.sort(ref["rolls"].ts_ns.to_numpy().astype(np.int64))
    return s, om, rolls


def _window_tape(s, om, d0: str, d1: str):
    b = s[(s.session_date >= d0) & (s.session_date <= d1)]
    t0, t1 = int(b.open_ns.min()), int(b.close_ns.max())
    d = P.tape(int(om[np.searchsorted(om, t0, side="right")]) - MIN_NS, t1)
    return d, t0, t1


def _run_kernel(om, rolls, alloc: str, h: int, d: pd.DataFrame, t0: int, t1: int):
    k = VolumeProfileKernel(om, rolls, h, alloc, origin_ns=t0)
    live_snaps, structs, hashes, tss = [], [], [], []

    def oc(p, k=k):
        snap = k.snapshot()
        if snap is None or snap.get("poc") is None:
            return
        ps = k.profile_snapshot(snap)
        if ps is None:
            return
        live_snaps.append(snap)
        structs.append(ps.to_struct())
        hashes.append(ps.content_hash)
        tss.append(ps.snapshot_ts)

    k.on_close = oc
    for row in d[["ts", "h", "l", "c", "v"]].itertuples(index=False):
        k.push(int(row.ts), float(row.h), float(row.l), float(row.c), float(row.v))
    k.close_through(t1)
    return live_snaps, structs, hashes, tss


def _roundtrip_check(tmp_dir: Path, name: str, live_snaps, structs, hashes, tss) -> dict:
    n = len(structs)
    buf = ColumnarBuffer(["observation_ts", "profile", "profile_hash"])
    for ts_, st, hs in zip(tss, structs, hashes):
        buf.append({"observation_ts": ts_, "profile": st, "profile_hash": hs})
    df = buf.to_frame()
    p = tmp_dir / f"{name}.parquet"
    df.to_parquet(p, index=False)
    on_disk_bytes = p.stat().st_size
    df2 = pd.read_parquet(p)
    p.unlink()
    mism, n_exact_tie = [], 0
    for i in range(n):
        snap = live_snaps[i]
        if structs[i].get("triplet_tick") is not None:
            n_exact_tie += 1
        got = VolumeProfileSnapshot.from_struct(df2["profile"].iloc[i])
        if got.content_hash != hashes[i]:
            mism.append((int(snap["snapshot_ts"]), "content_hash_after_parquet"))
            continue
        rec = got.reconstruct_poc_va_nodes()
        for f in ("poc", "vah", "val", "raw_poc", "raw_vah", "raw_val", "n_hvn", "n_lvn", "hvns_json", "lvns_json"):
            if rec.get(f) != snap.get(f):
                mism.append((int(snap["snapshot_ts"]), f, rec.get(f), snap.get(f)))
        if got.weights_fp != tuple(int(x) for x in structs[i]["weights_fp"]):
            mism.append((int(snap["snapshot_ts"]), "weights_fp_mismatch"))
        if got.contributions != tuple(int(x) for x in structs[i]["contributions"]):
            mism.append((int(snap["snapshot_ts"]), "contributions_mismatch"))
    return dict(n_checked=n, n_mismatch=len(mism), n_exact_tie_replay=n_exact_tie, on_disk_bytes_total=on_disk_bytes,
                on_disk_bytes_mean=on_disk_bytes / n if n else 0, sample_mismatch=mism[:5])


def _redundancy(profiles) -> dict:
    n = len(profiles)
    if n < 2:
        return {}
    unchanged_frac, delta_bytes, full_bytes = [], [], []
    for i in range(1, n):
        lo0, w0 = profiles[i - 1]
        lo1, w1 = profiles[i]
        a, b_ = min(lo0, lo1), max(lo0 + len(w0) - 1, lo1 + len(w1) - 1)
        n_ = b_ - a + 1
        A = np.zeros(n_, np.int64); B = np.zeros(n_, np.int64)
        A[lo0 - a:lo0 - a + len(w0)] = w0
        B[lo1 - a:lo1 - a + len(w1)] = w1
        same = A == B
        unchanged_frac.append(float(same.sum()) / n_)
        delta_bytes.append(int((~same).sum()) * 16)   # (index int64, value int64) per changed bin
        full_bytes.append(len(w1) * 8)
    return dict(mean_unchanged_frac=float(np.mean(unchanged_frac)), mean_delta_bytes=float(np.mean(delta_bytes)),
                mean_full_bytes=float(np.mean(full_bytes)), delta_vs_full_ratio=float(np.mean(delta_bytes) / np.mean(full_bytes)))


def _rss_run(om, rolls, d: pd.DataFrame, t0: int, t1: int) -> dict:
    """Peak RSS of a 9-kernel (3 allocations x 3 horizons) collection-style run, fed the same
    tape, accumulated into 9 ColumnarBuffers (the pre-flush in-memory state a real collection
    partition holds -- no incremental flush exists in lifecycle_v2.run_partition today)."""
    proc = psutil.Process()
    rows = list(d[["ts", "h", "l", "c", "v"]].itertuples(index=False))
    gc.collect()
    rss0 = proc.memory_info().rss
    kernels, bufs = [], []
    for alloc in ALLOCATIONS:
        for h in HORIZONS:
            k = VolumeProfileKernel(om, rolls, h, alloc, origin_ns=t0)
            buf = ColumnarBuffer(["observation_ts", "profile", "profile_hash"])

            def oc(p, k=k, buf=buf):
                snap = k.snapshot()
                if snap is None or snap.get("poc") is None:
                    return
                ps = k.profile_snapshot(snap)
                if ps is None:
                    return
                buf.append({"observation_ts": ps.snapshot_ts, "profile": ps.to_struct(), "profile_hash": ps.content_hash})

            k.on_close = oc
            kernels.append(k); bufs.append(buf)
    rss_after_init = proc.memory_info().rss
    for row in rows:
        a_, b_, c_, dd_, e_ = int(row.ts), float(row.h), float(row.l), float(row.c), float(row.v)
        for k in kernels:
            k.push(a_, b_, c_, dd_, e_)
    for k in kernels:
        k.close_through(t1)
    gc.collect()
    rss_after_accumulate = proc.memory_info().rss
    total_rows = sum(len(b) for b in bufs)
    frames = [b.to_frame() for b in bufs]
    total_parquet_bytes = 0
    for i, df in enumerate(frames):
        p = Path(f"_rss_tmp_{i}.parquet")
        df.to_parquet(p, index=False)
        total_parquet_bytes += p.stat().st_size
        p.unlink()
    return dict(total_rows=total_rows, delta_accumulate_bytes=rss_after_accumulate - rss_after_init,
                bytes_per_row_rss_accumulate=(rss_after_accumulate - rss_after_init) / total_rows if total_rows else 0,
                total_parquet_bytes=total_parquet_bytes, bytes_per_row_parquet=total_parquet_bytes / total_rows if total_rows else 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tmp", default=None)
    a = ap.parse_args()
    tmp_dir = Path(a.tmp) if a.tmp else Path(a.out).parent / "_tmp_vp_profile_emission"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    s, om, rolls = _calendar()
    t_start = time.time()
    report: dict = {"windows": {}}
    for win_name, (d0, d1) in WINDOWS.items():
        d, t0, t1 = _window_tape(s, om, d0, d1)
        report["windows"][win_name] = {}
        for alloc in ALLOCATIONS:
            for h in HORIZONS:
                live_snaps, structs, hashes, tss = _run_kernel(om, rolls, alloc, h, d, t0, t1)
                rt = _roundtrip_check(tmp_dir, f"{win_name}_{alloc}_{h}", live_snaps, structs, hashes, tss)
                if win_name == "2022-02-01_04_baseline":
                    profiles = [(st["lo_tick"], np.asarray(st["weights_fp"], np.int64)) for st in structs]
                    rt["redundancy"] = _redundancy(profiles)
                report["windows"][win_name][f"{alloc}/{h}"] = rt
                print(win_name, alloc, h, "checked", rt["n_checked"], "mismatches", rt["n_mismatch"], flush=True)
    # peak RSS / full-year extrapolation on the baseline window (all 9 kernels simultaneously)
    d, t0, t1 = _window_tape(s, om, *WINDOWS["2022-02-01_04_baseline"])
    rss = _rss_run(om, rolls, d, t0, t1)
    b2022 = s[(s.session_date >= "2022-01-03") & (s.session_date <= "2022-12-30")]
    open_minutes_2022 = len(open_minute_ends(b2022.open_ns.to_numpy(), b2022.close_ns.to_numpy()))
    rows_per_year_9_kernels = open_minutes_2022 * 9
    report["rss_measurement"] = rss
    report["full_year_extrapolation"] = dict(
        open_minutes_2022=open_minutes_2022, n_kernels=9, rows_per_year_9_kernels=rows_per_year_9_kernels,
        projected_peak_in_memory_bytes=rows_per_year_9_kernels * rss["bytes_per_row_rss_accumulate"],
        projected_peak_in_memory_gib=rows_per_year_9_kernels * rss["bytes_per_row_rss_accumulate"] / 2 ** 30,
        projected_on_disk_bytes=rows_per_year_9_kernels * rss["bytes_per_row_parquet"],
        projected_on_disk_gib=rows_per_year_9_kernels * rss["bytes_per_row_parquet"] / 2 ** 30,
        infeasible_in_memory_budget_gib=8,
        note=("lifecycle_v2.run_partition holds the WHOLE partition's candidate/observation rows as "
              "plain Python objects (ColumnarBuffer lists of dicts, no numpy/arrow backing) until a "
              "SINGLE to_parquet() flush at partition end -- no incremental/chunked flush exists today. "
              "The on-disk (parquet, typed Arrow) footprint is comfortably within the 8 GiB budget; the "
              "in-memory PRE-FLUSH Python-object footprint is not, because of CPython per-object overhead "
              "on the profile struct's weights_fp/contributions int lists, not because of the serialized "
              "representation itself."))
    report["passed"] = all(v["n_mismatch"] == 0 for win in report["windows"].values() for v in win.values())
    report["seconds"] = round(time.time() - t_start, 1)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != "windows"}, default=str))


if __name__ == "__main__":
    main()

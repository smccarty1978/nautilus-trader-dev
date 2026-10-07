"""One-week performance probe + incremental-vs-scratch check of tracker.volume_profile.rolling on real 1s bars.

Kernels: horizons 120 / 360 / 1440 open minutes x allocations range_uniform / full_per_tick / close, fed the
same bars (the first 7 days of the 2022 block, from the oracle tape cache = CausalDataLoader output). At every
97th closed minute each kernel's int64 window profile is compared with a scratch rebuild from the window's
bars (same per-bar quantisation): must be bit-identical. Reports seconds per kernel and the full-study
extrapolation. Outcome-free: prices are only binned, nothing forward is read.

    python scripts/probe_volume_profile_rolling.py --out artifacts/parity/volume_profile_rolling_probe.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

import parity_volume_profile_rolling as P
from features.trackers.volume_profile_rolling import FP, MIN_NS, VolumeProfileKernel, open_minute_ends

EVERY = 97


def scratch(k, d, p):
    start = max(p - k.h_min + 1, k.reset_pos(p))
    w = d[(d.ts > int(k.om[start]) - MIN_NS) & (d.ts <= int(k.om[p]))]
    lt = np.round(w.l.to_numpy() / k.tick).astype(np.int64)
    ht = np.round(w.h.to_numpy() / k.tick).astype(np.int64)
    ct = np.round(w.c.to_numpy() / k.tick).astype(np.int64)
    v = w.v.to_numpy()
    if k.alloc == "close":
        tk, wt = ct, np.round(v * FP).astype(np.int64)
    else:
        n = ht - lt + 1
        tk = np.repeat(lt, n) + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
        wt = np.repeat(np.round((v / n if k.alloc == "range_uniform" else v) * FP).astype(np.int64), n)
    u, inv = np.unique(tk, return_inverse=True)
    out = np.zeros(len(u), np.int64)
    np.add.at(out, inv, wt)
    nz = out != 0
    return u[nz], out[nz]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ref = P.dataset_v2.load_reference_tables(P.CATALOG, ["sessions", "rolls"])
    s = ref["sessions"].copy()
    s["session_date"] = s.session_date.astype(str)
    s = s[s.close_ns <= P.DEV_END].sort_values("open_ns").reset_index(drop=True)
    blk = s[(s.session_date >= P.BLOCKS["2022"][0]) & (s.session_date <= P.BLOCKS["2022"][1])]
    ef = int(blk.open_ns.min())
    et = ef + a.days * 86400 * 10**9
    t0 = int(s[s.close_ns <= ef].tail(2).open_ns.min())
    om = open_minute_ends(s.open_ns.to_numpy(), s.close_ns.to_numpy())
    rolls = np.sort(ref["rolls"].ts_ns.to_numpy().astype(np.int64))
    d = P.tape(int(om[np.searchsorted(om, t0, side="right")]) - MIN_NS, et)
    cols = [d[c].to_numpy() for c in ("ts", "h", "l", "c", "v")]
    res = {}
    for h in (120, 360, 1440):
        for alloc in ("range_uniform", "full_per_tick", "close"):
            k = VolumeProfileKernel(om, rolls, h, alloc, origin_ns=t0)
            n_snap, checks, bad = [0], [0], [0]

            def cb(p, k=k):
                if ef < k.om[p] <= et:
                    k.snapshot()
                    n_snap[0] += 1
                    if n_snap[0] % EVERY == 0:
                        u, w = scratch(k, d, p)
                        nz = np.flatnonzero(k.X)
                        checks[0] += 1
                        bad[0] += int(not (np.array_equal(nz + k.base, u) and np.array_equal(k.X[nz], w)))

            k.on_close = cb
            t = time.time()
            for ts, hh, ll, cc, vv in zip(*cols):
                k.push(int(ts), float(hh), float(ll), float(cc), float(vv))
            k.close_through(et)
            res[f"{h}/{alloc}"] = dict(seconds=round(time.time() - t, 2), snapshots=n_snap[0], scratch_checks=checks[0],
                                       scratch_mismatch=bad[0], exact_resolutions=k.n_exact)
    week_s = sum(r["seconds"] for r in res.values())
    snaps = max(r["snapshots"] for r in res.values())
    full_minutes = 353_630 + 281_793                                         # 2022 + 2023dev VP120 oracle population (order of magnitude)
    out = dict(days=a.days, bars=int(len(d)), kernels=res, week_seconds_all_kernels=round(week_s, 1),
               est_full_study_minutes=round(week_s * full_minutes / max(snaps, 1) / 60, 1),
               passed=all(r["scratch_mismatch"] == 0 and r["scratch_checks"] > 0 for r in res.values()))
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(json.dumps(out))


if __name__ == "__main__":
    main()

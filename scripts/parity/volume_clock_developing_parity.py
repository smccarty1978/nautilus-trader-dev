"""Historical parity for tracker.volume_clock.developing against the frozen vc_v1 Stage C engine.

Three separate steps (replay market data ONCE, compare many times without it):

  replay  -- one pass over NQ_1S_V2_GLOBEX 1s bars (canonical CausalDataLoader, one month at a time, Globex session
             2023-11-01 .. 2025-12-31; no 2026 row is requested) through three kernels (scale_k 1 / 5 / 15). Persists
             deterministic parquet outputs to --dir:
               tracker_bars.parquet         every bar_completed event, all scales
               tracker_sessions.parquet     session_opened + session_closed records, all scales
               tracker_checkpoints.parquet  every V1 checkpoint event
               tracker_states.parquet       V1 developing state at every 97th RTH row of every calibrated session
               reference_states.parquet     independent vectorised reference at the same rows (same catalog rows +
                                            the frozen Stage C V1 bars; no tracker code)
               reference_checkpoints.parquet  independent crossing rows from the frozen bars and the session rows
               replay_manifest.json         sources, tracker sha, row counts, schemas, durations, memory samples
  compare -- reads only the persisted outputs and the frozen, sha256-pinned Stage C ledgers. Keyed hash joins
             (linear); detects missing / extra / duplicate keys and every field mismatch, exact equality (no
             tolerance; NaN equals NaN; nanosecond timestamps compared as int64). Writes checkpoint_comparison.json,
             comparison_provenance.json and the promotion parity artifact.
  probe   -- feed-only memory / throughput probe (nothing retained outside the kernel).

Usage:
  python scripts/parity/volume_clock_developing_parity.py replay  --dir <dir> [--months N]
  python scripts/parity/volume_clock_developing_parity.py compare --dir <dir> --out <artifact.json> [--smoke]
  python scripts/parity/volume_clock_developing_parity.py probe   --out <json> [--months N]
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from features.trackers.volume_clock_developing import (  # noqa: E402
    DIR_WINDOW_S, MIN_NS, NS, VolumeClockKernel, load_calendar)

ORACLE_DIR = Path("C:/Users/Scott McCarty/Projects/Nautilus Trader-nq_adaptive_volume_clock/research/nq_adaptive_volume_clock/out/full")
ORACLE_PINS = {
    "volume_bars_v1.parquet": "1913951903cced6f7ba0a574c391cd2c78719338e6d19fb36a8743a70aac691c",
    "volume_bars_v5.parquet": "dff5b307aef76df866d050a54d503bd40abe15259acef02e8e82981f418fb64c",
    "volume_bars_v15.parquet": "4c36614aa78092a411f4209978f01eea2b484efa6fd35f89e82017fa6ff87e8b",
    "daily_calibration.parquet": "5e958a44e5a116f0d8e73eadc658442c076187f810519a212a0f914ed4a053b2",
    "session_build_audit.parquet": "905f4a20c0f37decc06c833526004d70b36c9b1ef66ab037f05077fd0e2bf066",
}
ORACLE_CONTRACT = {"version": "vc_v1", "stage": "C", "branch": "research/nq_adaptive_volume_clock",
                   "contract": "VOLUME_CLOCK_CONTRACT_FROZEN.md", "contract_sha256": "3535f09dab33057cdbe76a86c7711285b450572fd8f0cf5070f4cb3caafb69d5"}
DATASET = "NQ_1S_V2_GLOBEX"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
ORIGIN = pd.Timestamp("2023-10-31 22:00:00", tz="UTC")       # open of Globex session 2023-11-01 (17:00 CT) = Stage C origin
END = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")          # last Stage C session 2025-12-31; never 2026
SCALES = {"V1": 1, "V5": 5, "V15": 15}
SAMPLE_EVERY = 97
RV_W, RATE_W, CPS = (15, 30, 60, 120, 300), (10, 15, 30), (0.25, 0.50, 0.75)
STATE_FIELDS = ("n_completed", "consumed", "frac", "elapsed_s", "bar_open_price", "bar_high", "bar_low", "carry_contracts",
                "internal_contracts", "rate_since_open", *[f"rate_last_{w}s" for w in RATE_W], "r_exp",
                *[f"vol_{w}s" for w in RV_W], *[f"rv_{w}s" for w in RV_W], "d60_points", "dir_d60")
INT_STATE = {"n_completed", "consumed", "elapsed_s", "carry_contracts", "internal_contracts", "dir_d60", *[f"vol_{w}s" for w in RV_W]}
TS_COLS = ("start_ts", "end_ts", "avail_ts", "rth_start_ns", "rth_end_ns", "ts", "t")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def rss_mb() -> float:
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / 2**20
    except Exception:       # pragma: no cover
        return float("nan")


def kernel_state(k: VolumeClockKernel) -> Dict[str, Any]:
    """Tracker-owned state sizes (rows retained and an approximate byte count)."""
    lists = [k._px.ts, k._px.val, k._cum.ts, k._cum.val, k.elig_vol, k.elig_dates]
    b = sum(sys.getsizeof(x) + 32 * len(x) for x in lists) + sum(a.nbytes for a in k.elig_prof)
    if k.sess is not None:
        b += k.sess["minute_vol"].nbytes + (k.sess["r_exp"].nbytes if k.sess["r_exp"] is not None else 0)
    return {"price_buf_rows": len(k._px.ts), "price_live_rows": len(k._px), "cum_buf_rows": len(k._cum.ts),
            "cum_live_rows": len(k._cum), "elig_vol": len(k.elig_vol), "elig_prof": len(k.elig_prof), "approx_bytes": int(b)}


def months():
    m = ORIGIN.tz_localize(None).to_period("M")
    while m.start_time <= END.tz_localize(None):
        a = max(m.start_time.tz_localize("UTC"), ORIGIN)
        b = min((m + 1).start_time.tz_localize("UTC") - pd.Timedelta(seconds=1), END)
        yield a, b
        m += 1


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()


# ============================================================================================ independent reference
def ref_session(rows: np.ndarray, start_ns: int, T: int, frozen: pd.DataFrame, r_exp: np.ndarray, pre: np.ndarray,
                sample_every: int = SAMPLE_EVERY):
    """Independent vectorised developing state at every sample_every-th RTH row, and every checkpoint crossing.
    rows: (n, 6) ts_event, o, h, l, c, v of the session's RTH rows; frozen: the session's frozen Stage C bars
    (bar_seq order; avail_ts, end_ts, close); pre: (m, 2) ts_init, close of rows before the session.
    Returns (states: list of dict with key t, crossings: list of (bar_seq, level, ts))."""
    ts = rows[:, 0].astype(np.int64)
    o, h, l, c, v = rows[:, 1], rows[:, 2], rows[:, 3], rows[:, 4], rows[:, 5].astype(np.int64)
    ti = ts + NS
    C = np.cumsum(v)
    avail = frozen.avail_ts.to_numpy(np.int64)
    bclose = frozen.close.to_numpy(float)
    nb = len(avail)
    first = int(np.searchsorted(C, 1, side="left"))
    all_ti = np.concatenate([pre[:, 0].astype(np.int64), ti])
    all_c = np.concatenate([pre[:, 1], c])
    out = []
    for i in range(0, len(ts), sample_every):
        t = int(ti[i])
        n = int(np.searchsorted(avail, t, side="right"))
        cum = int(C[i])
        origin = int(avail[n - 1]) if n else start_ns
        s = int(np.searchsorted(C, n * T + 1, side="left"))
        if n == 0:
            bo = float(o[first]) if first <= i else None
        else:
            bo = float(bclose[n - 1]) if not math.isnan(bclose[n - 1]) else float(c[np.searchsorted(ts, int(frozen.end_ts.iloc[n - 1]))])
        if s <= i and bo is not None:
            hi, lo = max(float(h[s:i + 1].max()), bo), min(float(l[s:i + 1].min()), bo)
        else:
            hi = lo = bo
        cum_origin = int(C[np.searchsorted(ti, origin, side="right") - 1]) if n else 0
        elapsed = (t - origin) // NS
        d: Dict[str, Any] = {"t": t, "n_completed": n, "consumed": cum - n * T, "frac": (cum - n * T) / T, "elapsed_s": elapsed,
                             "bar_open_price": bo, "bar_high": hi, "bar_low": lo,
                             "carry_contracts": (cum_origin - n * T) if n else 0, "internal_contracts": cum - cum_origin}
        if elapsed > 0:
            d["rate_since_open"] = (cum - cum_origin) / elapsed
            for w in RATE_W:
                ww = min(w, elapsed)
                j = int(np.searchsorted(ti, t - ww * NS, side="right")) - 1
                d[f"rate_last_{w}s"] = (cum - (int(C[j]) if j >= 0 else 0)) / ww
        m = (t - NS - start_ns) // MIN_NS
        r = float(r_exp[m])
        d["r_exp"] = r
        for w in RV_W:
            if t - w * NS >= start_ns:
                j = int(np.searchsorted(ti, t - w * NS, side="right")) - 1
                vw = cum - (int(C[j]) if j >= 0 else 0)
                d[f"vol_{w}s"] = vw
                d[f"rv_{w}s"] = vw / (w * r) if r > 0 else None
        j = int(np.searchsorted(all_ti, t - DIR_WINDOW_S * NS, side="right")) - 1
        if j >= 0:
            dd = float(c[i]) - float(all_c[j])
            d["d60_points"] = dd
            d["dir_d60"] = int(np.sign(dd))
        out.append(d)
    cps = []
    for n in range(1, nb + 2):                     # every frozen bar and the final incomplete (residual) bar
        for q in CPS:
            k = int(np.searchsorted(C - (n - 1) * T, q * T, side="left"))
            if k < len(C):
                cps.append((n, q, int(ti[k])))
    return out, cps


# ============================================================================================ keyed comparison
def _norm(s: pd.Series, f: str) -> pd.Series:
    if f in TS_COLS or s.dtype.kind in "iub" or str(s.dtype) in ("Int64", "boolean"):
        try:
            return s.astype("Int64")
        except (TypeError, ValueError):
            return s
    return s


def compare_keyed(ref: pd.DataFrame, trk: pd.DataFrame, keys: Sequence[str], values: Sequence[str], name: str,
                  max_examples: int = 10) -> Dict[str, Any]:
    """Exact keyed comparison by one hash join (linear in rows). NaN/None equal NaN/None; nothing else is tolerated."""
    t0 = time.perf_counter()
    keys, values = list(keys), list(values)
    res: Dict[str, Any] = {"name": name, "keys": keys, "values": values, "ref_rows": int(len(ref)), "trk_rows": int(len(trk))}
    res["dup_ref"] = int(ref.duplicated(keys, keep=False).sum()) if len(ref) else 0
    res["dup_trk"] = int(trk.duplicated(keys, keep=False).sum()) if len(trk) else 0
    r = ref[keys + values].drop_duplicates(keys)
    t = trk[keys + values].drop_duplicates(keys)
    m = r.merge(t, on=keys, how="outer", suffixes=("_r", "_t"), indicator=True)
    only_r, only_t = m["_merge"] == "left_only", m["_merge"] == "right_only"
    both = m["_merge"] == "both"
    res["only_ref"], res["only_trk"], res["matched"] = int(only_r.sum()), int(only_t.sum()), int(both.sum())
    bad = only_r | only_t
    fm = {}
    for f in values:
        a, b = _norm(m[f + "_r"], f), _norm(m[f + "_t"], f)
        na, nb_ = a.isna(), b.isna()
        eq = (a == b).fillna(False).astype(bool) | (na & nb_)
        neq = both & ~eq
        fm[f] = int(neq.sum())
        bad = bad | neq
    res["field_mismatches"] = fm
    if bad.any():
        bm = m[bad].sort_values(keys)
        first = bm.iloc[0]
        res["first_divergence"] = {k_: (first[k_].item() if hasattr(first[k_], "item") else first[k_]) for k_ in keys}
        res["examples"] = json.loads(bm.head(max_examples).to_json(orient="records", default_handler=str))
    else:
        res["first_divergence"], res["examples"] = None, []
    res["pass"] = bool(res["dup_ref"] == 0 and res["dup_trk"] == 0 and not bad.any())
    res["seconds"] = round(time.perf_counter() - t0, 4)
    return res


# ============================================================================================ replay
def replay(a) -> int:
    t_all = time.time()
    out = Path(a.dir)
    out.mkdir(parents=True, exist_ok=True)
    pins = {k: sha256(ORACLE_DIR / k) for k in ORACLE_PINS}
    if pins != ORACLE_PINS:
        raise SystemExit(f"ORACLE_HASH_MISMATCH {pins}")
    fb1 = pd.read_parquet(ORACLE_DIR / "volume_bars_v1.parquet", columns=["date", "bar_seq", "avail_ts", "end_ts", "close"])
    fb_by = {d: g.sort_values("bar_seq").reset_index(drop=True) for d, g in fb1.groupby("date")}
    dc = pd.read_parquet(ORACLE_DIR / "daily_calibration.parquet", columns=["date", "calibrated", "T_V1", "cal_source_dates"])
    dc_by = {r.date: r for r in dc.itertuples(index=False)}
    del fb1, dc

    from research_workflow.roots import resolve_dataset
    from utils.runner.data import CausalDataLoader
    cat = resolve_dataset(DATASET, REPO).catalog_path
    cal = load_calendar(DATASET)
    kernels = {nm: VolumeClockKernel(cal, scale_k=k, rv_windows=RV_W, rate_windows=RATE_W, checkpoints=CPS) for nm, k in SCALES.items()}
    k1 = kernels["V1"]

    bars: List[dict] = []
    sessions: List[dict] = []
    trk_cps: List[tuple] = []
    trk_states: List[dict] = []
    ref_states: List[dict] = []
    ref_cps: List[tuple] = []
    minute_prof: Dict[str, np.ndarray] = {}
    mem: List[dict] = []
    n_rows, feed_s, ref_s = 0, 0.0, 0.0
    sess_rows: list = []
    sess_samples: Dict[int, dict] = {}
    pre_buf: list = []
    pre_snapshot: list = []
    cur_rs = None
    loader = CausalDataLoader(cat)

    def finish_session(rs) -> None:
        nonlocal ref_s
        if rs is None or not sess_rows:
            return
        tr = time.time()
        arr = np.asarray(sess_rows, dtype=np.float64)
        minute_prof[rs.date] = np.bincount((arr[:, 0].astype(np.int64) - rs.start_ns) // MIN_NS, weights=arr[:, 5], minlength=405)[:405]
        row = dc_by.get(rs.date)
        if row is not None and bool(row.calibrated) and rs.date in fb_by:
            srcs = str(row.cal_source_dates).split(",")
            if all(sd in minute_prof for sd in srcs):
                r_exp = np.mean(np.vstack([minute_prof[sd] for sd in srcs]), axis=0) / 60.0
                pre = np.asarray(pre_snapshot, dtype=np.float64).reshape(-1, 2)
                st, cp = ref_session(arr, rs.start_ns, int(row.T_V1), fb_by[rs.date], r_exp, pre)
                for d in st:
                    d["date"] = rs.date
                ref_states.extend(st)
                ref_cps.extend((rs.date, n, q, t) for n, q, t in cp)
        for d in list(minute_prof):                 # bounded: keep the profiles a later calibration can use
            if len(minute_prof) > 40:
                minute_prof.pop(d)
        for t, st in sess_samples.items():
            trk_states.append({"date": rs.date, "t": t, **{f: st.get(f) for f in STATE_FIELDS}})
        ref_s += time.time() - tr

    def take(nm: str, k: VolumeClockKernel) -> None:
        for name, p in k.drain():
            if name == "bar_completed":
                bars.append({"scale": nm, **{f: p[f] for f in ("session_date", "bar_seq", "T", "start_ts", "end_ts", "avail_ts",
                                                                 "dur_raw", "duration_s", "cum_session_contracts", "collapsed",
                                                                 "open", "high", "low", "close")}})
            elif name == "checkpoint" and nm == "V1":
                trk_cps.append((p["session_date"], p["bar_seq"], p["level"], p["ts"], bool(p["completed_in_row"]),
                                bool(p["collapsed"]), bool(p["multi_cross"])))
            elif name == "session_opened":
                sessions.append({"scale": nm, "event": "opened", **p})
        for rec in k.closed_sessions:
            sessions.append({"scale": nm, "event": "closed", **rec})
        k.closed_sessions.clear()

    for mi, (lo, hi) in enumerate(months()):
        if a.months and mi >= a.months:
            break
        tl = time.time()
        src = loader.load_bars(BAR_TYPE, lo, hi)
        CausalDataLoader.clear_cache()
        load_s = time.time() - tl
        tf = time.time()
        for b in src:
            te, ti = int(b.ts_event), int(b.ts_init)
            o, h, l, c, v = b.open.as_double(), b.high.as_double(), b.low.as_double(), b.close.as_double(), b.volume.as_double()
            for nm, k in kernels.items():
                k.push(te, ti, o, h, l, c, v)
            n_rows += 1
            rs = k1.sess["rs"] if k1.sess is not None else None
            if rs is not cur_rs:
                finish_session(cur_rs)
                pre_snapshot = list(pre_buf)
                sess_rows, sess_samples = [], {}
                cur_rs = rs
            if rs is not None:
                sess_rows.append((te, o, h, l, c, v))
                if k1.state["calibrated"] and (len(sess_rows) - 1) % SAMPLE_EVERY == 0:
                    sess_samples[ti] = dict(k1.state)
            else:
                pre_buf.append((ti, c))
                if len(pre_buf) > 400:
                    del pre_buf[:200]
            for nm, k in kernels.items():
                take(nm, k)
        feed_s += time.time() - tf
        del src
        gc.collect()
        mem.append({"month": str(lo.date())[:7], "rows_total": n_rows, "load_seconds": round(load_s, 1),
                    "rss_mb": round(rss_mb(), 1), "harness_rows_held": {"bars": len(bars), "checkpoints": len(trk_cps),
                                                                         "tracker_states": len(trk_states), "reference_states": len(ref_states)},
                    "kernel_V1": kernel_state(k1)})
        print(json.dumps(mem[-1]), flush=True)
    # end of stream: the next row would close the open session; close it explicitly for every scale
    for nm, k in kernels.items():
        k._close_session()
        take(nm, k)
    finish_session(cur_rs)

    # ------------------------------------------------------------------------------------------ persist
    def frame(rows, cols=None):
        df = pd.DataFrame(rows, columns=cols)
        for col in df.columns:
            if col in TS_COLS or col in INT_STATE or col in ("bar_seq", "T", "dur_raw", "duration_s", "cum_session_contracts",
                                                              "n_bars", "residual_contracts", "rth_volume", "native_rows"):
                df[col] = pd.array(df[col].astype(object).where(df[col].notna(), None), dtype="Int64")
        return df

    files = {
        "tracker_bars.parquet": frame(bars),
        "tracker_sessions.parquet": frame(sessions).astype({"roll_ratio_med20": "float64"}, errors="ignore"),
        "tracker_checkpoints.parquet": frame(trk_cps, ["date", "bar_seq", "level", "ts", "completed_in_row", "collapsed", "multi_cross"]),
        "tracker_states.parquet": frame(trk_states, ["date", "t", *STATE_FIELDS]),
        "reference_states.parquet": frame(ref_states, ["date", "t", *STATE_FIELDS]),
        "reference_checkpoints.parquet": frame(ref_cps, ["date", "bar_seq", "level", "ts"]),
    }
    outputs = {}
    for fn, df in files.items():
        df = df.sort_values([c for c in ("scale", "date", "session_date", "event", "bar_seq", "level", "t") if c in df.columns]).reset_index(drop=True)
        df.to_parquet(out / fn, index=False, compression="zstd")
        outputs[fn] = {"rows": int(len(df)), "sha256": sha256(out / fn), "schema": {c: str(t) for c, t in df.dtypes.items()}}
    mod = REPO / "features/trackers/volume_clock_developing.py"
    manifest = {
        "capability": "tracker.volume_clock.developing", "step": "replay", "dataset": DATASET, "bar_type": BAR_TYPE,
        "catalog_logical_digest": json.loads((Path(cat) / "dataset_manifest.json").read_text(encoding="utf-8")).get("logical_digest"),
        "window_utc": [str(ORIGIN), str(END)], "months_limit": a.months or None, "rows_fed": n_rows, "scales": SCALES,
        "tracker_commit": git_head(), "tracker_module_sha256": sha256(mod), "harness_sha256": sha256(Path(__file__)),
        "oracle": {**ORACLE_CONTRACT, "dir": str(ORACLE_DIR), "sha256": pins},
        "timestamp_convention": "int64 UTC ns; ts_event = second open, ts_init = second close = availability; avail_ts = end_ts + 1 s",
        "sampling": f"every {SAMPLE_EVERY}th RTH row (0-based row index within the session) of every calibrated V1 session",
        "outputs": outputs,
        "durations_seconds": {"source_load": round(sum(x["load_seconds"] for x in mem), 1), "tracker_feed_incl_harness": round(feed_s, 1),
                              "reference_build": round(ref_s, 1), "wall": round(time.time() - t_all, 1)},
        "memory_by_month": mem,
    }
    (out / "replay_manifest.json").write_text(json.dumps(manifest, indent=1, default=str) + chr(10), encoding="utf-8")
    print(json.dumps({"rows_fed": n_rows, "outputs": {k_: v_["rows"] for k_, v_ in outputs.items()}, "wall": manifest["durations_seconds"]["wall"]}))
    return 0


# ============================================================================================ compare
def _derived_flags(b: pd.DataFrame) -> pd.DataFrame:
    """vc_v1 quality flags from bar timestamps only (per scale, date): start_partial = the bar starts in the previous
    bar's completion second (bar 1: never); end_partial(n) = start_partial(n+1) (the last bar is not derivable from
    events and is excluded); shared_second_completions = completions of the scale in the same second."""
    b = b.sort_values(["scale", "date", "bar_seq"]).copy()
    g = b.groupby(["scale", "date"], sort=False)
    prev_end = g["end_ts"].shift(1)
    b["start_partial"] = (b["start_ts"] == prev_end).fillna(False).astype(bool)
    nxt = g["start_partial"].shift(-1)
    b["end_partial_cmp"] = nxt.astype("boolean")
    b["shared_second_completions"] = b.groupby(["scale", "date", "end_ts"])["bar_seq"].transform("size").astype("Int64")
    b["completion_speed"] = 60.0 * b["scale"].map(SCALES).astype(float) / b["duration_s"].astype(float)
    return b


def compare(a) -> int:
    t0 = time.time()
    d = Path(a.dir)
    man = json.loads((d / "replay_manifest.json").read_text(encoding="utf-8"))
    hashes = {fn: sha256(d / fn) for fn in man["outputs"]}
    if any(hashes[fn] != man["outputs"][fn]["sha256"] for fn in hashes):
        raise SystemExit(f"REPLAY_OUTPUT_HASH_MISMATCH {hashes}")
    pins = {k: sha256(ORACLE_DIR / k) for k in ORACLE_PINS}
    if pins != ORACLE_PINS:
        raise SystemExit(f"ORACLE_HASH_MISMATCH {pins}")
    tb = pd.read_parquet(d / "tracker_bars.parquet").rename(columns={"session_date": "date"})
    ts_ = pd.read_parquet(d / "tracker_sessions.parquet")
    last_date = str(ts_.loc[ts_.event == "closed", "session_date"].max())
    res: Dict[str, Any] = {"capability": "tracker.volume_clock.developing", "replay_manifest_sha256": sha256(d / "replay_manifest.json"),
                           "tracker_commit_at_replay": man["tracker_commit"], "tracker_module_sha256_at_replay": man["tracker_module_sha256"],
                           "rows_fed": man["rows_fed"], "last_session": last_date, "smoke": bool(a.smoke)}

    # ---- population reconciliation (counts straight from the frozen manifests)
    sba = pd.read_parquet(ORACLE_DIR / "session_build_audit.parquet")
    dc = pd.read_parquet(ORACLE_DIR / "daily_calibration.parquet")
    pop = {}
    fbs = {}
    for nm in SCALES:
        fb = pd.read_parquet(ORACLE_DIR / f"volume_bars_{nm.lower()}.parquet")
        fb = fb[fb.date <= last_date].copy()
        fb["scale"] = nm
        fbs[nm] = fb
        pop[nm] = {"oracle_all": int(len(fb)), "oracle_reported_2024_2025": int(fb.reported.sum()),
                   "oracle_primary": int((fb.reported & fb.primary).sum()),
                   "oracle_primary_sessions": int(fb[fb.reported & fb.primary].date.nunique()),
                   "oracle_by_class": {k_: int(v_) for k_, v_ in fb.groupby("rth_class").size().items()},
                   "tracker_all": int((tb.scale == nm).sum())}
    res["population"] = pop

    # ---- sessions: identity, boundaries, classes, calibration, conservation, residual (per scale)
    op = ts_[ts_.event == "opened"]
    cl = ts_[ts_.event == "closed"]
    sess_res = {}
    dcw = dc[(dc.date <= last_date)]
    for nm, k in SCALES.items():
        o_ = op[op.scale == nm][["session_date", "rth_start_ns", "rth_end_ns"]]
        c_ = cl[cl.scale == nm].drop(columns=["rth_start_ns", "rth_end_ns"], errors="ignore").merge(o_, on="session_date", how="left")
        c_ = c_.rename(columns={"session_date": "date"})
        c_["target_exact"] = c_["target_exact"].astype(float)
        c_["T"] = c_["T"].astype("Int64")
        c_["conserved"] = (c_["n_bars"] * c_["T"] + c_["residual_contracts"] == c_["rth_volume"])
        ref = dcw[~dcw.rth_class.isin(["NO_RTH", "MISSING_DATA"])].merge(
            sba[["date", f"n_bars_{nm}", f"residual_{nm}", f"conserved_{nm}"]], on="date", how="left")
        ref = ref.assign(T=ref[f"T_{nm}"].where(ref.calibrated).astype("Int64"),
                         target_exact=ref[f"{nm}_exact"].where(ref.calibrated).astype(float),
                         cal_source_dates=ref.cal_source_dates.where(ref.calibrated),
                         n_bars=ref[f"n_bars_{nm}"].fillna(0).astype("Int64"),
                         residual_contracts=ref[f"residual_{nm}"].astype("Int64"),
                         conserved=ref[f"conserved_{nm}"].where(ref.calibrated))
        trk = c_.assign(cal_source_dates=c_.cal_source_dates.where(c_.calibrated.astype(bool)),
                        residual_contracts=c_.residual_contracts.astype("Int64"),
                        conserved=c_.conserved.where(c_.calibrated.astype(bool)))
        vals = ["rth_class", "calibrated", "T", "target_exact", "cal_source_dates", "rth_volume", "rth_start_ns", "rth_end_ns",
                "n_bars", "residual_contracts", "conserved"]
        ref = ref.assign(rth_volume=ref.rth_volume.astype("Int64"))
        sess_res[nm] = compare_keyed(ref, trk, ["date"], vals, f"sessions_{nm}")
    res["sessions"] = sess_res

    # ---- completed bars, every scale, every field the reference exposes (+ derived flags)
    bars_res = {}
    allb = pd.concat(fbs.values(), ignore_index=True)
    fo = _derived_flags(allb.drop(columns=["start_partial", "shared_second_completions", "completion_speed"], errors="ignore")
                        .assign(start_partial_o=allb.start_partial, end_partial_o=allb.end_partial,
                                shared_o=allb.shared_second_completions, speed_o=allb.completion_speed))
    ft = _derived_flags(tb[tb.date <= last_date])
    for nm in SCALES:
        r = fo[fo.scale == nm].copy()
        t = ft[ft.scale == nm].copy()
        # the reference's own flags vs the same derivation on the reference (validates the derivation itself)
        r["end_partial_cmp"] = r["end_partial_cmp"]
        deriv_ok = {"start_partial": int((r.start_partial != r.start_partial_o).sum()),
                    "end_partial_non_last": int(((r.end_partial_cmp.notna()) & (r.end_partial_cmp.astype("boolean") != r.end_partial_o)).sum()),
                    "shared_second_completions": int((r.shared_second_completions != r.shared_o).sum()),
                    "completion_speed": int((r.completion_speed != r.speed_o).sum())}
        vals = ["start_ts", "end_ts", "avail_ts", "dur_raw", "duration_s", "cum_session_contracts", "T", "collapsed",
                "open", "high", "low", "close", "start_partial", "end_partial_cmp", "shared_second_completions", "completion_speed"]
        for col in ("open", "high", "low", "close"):
            r[col], t[col] = r[col].astype(float), t[col].astype(float)
        r["collapsed"], t["collapsed"] = r["collapsed"].astype(bool), t["collapsed"].astype(bool)
        c = compare_keyed(r, t, ["date", "bar_seq"], vals, f"bars_{nm}")
        prim = r[r.reported & r.primary][["date", "bar_seq"]].merge(t[["date", "bar_seq"]], on=["date", "bar_seq"])
        c["primary_matched"] = int(len(prim))
        c["primary_oracle"] = int((r.reported & r.primary).sum())
        c["flag_derivation_on_reference_mismatches"] = deriv_ok
        c["pass"] = bool(c["pass"] and all(v == 0 for v in deriv_ok.values()) and c["primary_matched"] == c["primary_oracle"])
        bars_res[nm] = c
    res["bars"] = bars_res

    # ---- developing state and checkpoints (V1)
    rs_ = pd.read_parquet(d / "reference_states.parquet")
    ts2 = pd.read_parquet(d / "tracker_states.parquet")
    ts2 = ts2[ts2.date.isin(set(rs_.date))]
    res["developing_states"] = compare_keyed(rs_, ts2, ["date", "t"], list(STATE_FIELDS), "developing_states_V1")
    rc = pd.read_parquet(d / "reference_checkpoints.parquet")
    tc = pd.read_parquet(d / "tracker_checkpoints.parquet")
    tc = tc[tc.date.isin(set(rc.date))]
    res["checkpoints"] = compare_keyed(rc, tc, ["date", "bar_seq", "level"], ["ts"], "checkpoints_V1")
    res["checkpoints"]["tracker_multi_cross"] = int(tc.multi_cross.sum())
    res["checkpoints"]["tracker_collapsed"] = int(tc.collapsed.sum())
    res["checkpoints"]["tracker_completed_in_row"] = int(tc.completed_in_row.sum())

    # ---- source identity
    ds_yaml = (REPO / "research/datasets/NQ_1S_V2_GLOBEX.yaml").read_text(encoding="utf-8")
    prov = json.loads((ORACLE_DIR / "provenance_manifest.json").read_text(encoding="utf-8"))
    raw = {k_: v_["sha256"] for k_, v_ in prov["sources"].items()}
    res["source_identity"] = {"oracle_raw_sha256": raw, "all_in_dataset_provenance": all(h in ds_yaml for h in raw.values()),
                              "catalog_logical_digest_at_replay": man["catalog_logical_digest"],
                              "note": "the catalog stream carries no instrument_id; identity = the same v.0 raw files (sha256) "
                                      "the dataset was built from; Stage C gate G02 (one instrument per RTH session) holds"}
    res["source_identity"]["pass"] = bool(res["source_identity"]["all_in_dataset_provenance"])

    gates = [v_["pass"] for v_ in sess_res.values()] + [v_["pass"] for v_ in bars_res.values()] + \
            [res["developing_states"]["pass"], res["checkpoints"]["pass"], res["source_identity"]["pass"]]
    nonempty = res["developing_states"]["matched"] > 0 and res["checkpoints"]["matched"] > 0 and all(v_["matched"] > 0 for v_ in bars_res.values())
    res["comparison_seconds"] = round(time.time() - t0, 2)
    res["passed"] = bool(all(gates) and nonempty and not a.smoke)
    res["all_comparisons_pass"] = bool(all(gates) and nonempty)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + chr(10), encoding="utf-8")
    prov_out = {"replay_dir": str(d), "replay_manifest": man | {"memory_by_month": f"{len(man['memory_by_month'])} samples (see replay_manifest.json)"},
                "replay_output_sha256": hashes, "oracle_sha256": pins, "oracle_contract": ORACLE_CONTRACT,
                "comparison_key_definitions": {"sessions": ["date"], "bars": ["scale", "date", "bar_seq"],
                                               "developing_states": ["date", "t (ts_init ns of the sampled row)"],
                                               "checkpoints": ["date", "bar_seq", "level"]},
                "equality": "exact; NaN/None equal NaN/None; int64 ns timestamps; no tolerance",
                "comparison_harness_sha256": sha256(Path(__file__)), "artifact": str(a.out), "artifact_sha256": sha256(Path(a.out))}
    (d / "comparison_provenance.json").write_text(json.dumps(prov_out, indent=1, default=str) + chr(10), encoding="utf-8")
    summary = {"sessions": {k_: v_["pass"] for k_, v_ in sess_res.items()}, "bars": {k_: v_["pass"] for k_, v_ in bars_res.items()},
               "developing_states": res["developing_states"]["pass"], "checkpoints": res["checkpoints"]["pass"],
               "source_identity": res["source_identity"]["pass"], "all_comparisons_pass": res["all_comparisons_pass"],
               "passed": res["passed"], "comparison_seconds": res["comparison_seconds"]}
    print(json.dumps(summary))
    return 0


# ============================================================================================ probe
def probe(a) -> int:
    """Feed-only run: nothing is retained outside the kernel, so RSS growth would be the kernel's own."""
    from research_workflow.roots import resolve_dataset
    from utils.runner.data import CausalDataLoader
    k = VolumeClockKernel(load_calendar(DATASET), rv_windows=RV_W, rate_windows=RATE_W, checkpoints=CPS)
    loader = CausalDataLoader(resolve_dataset(DATASET, REPO).catalog_path)
    mem, n, feed, ev = [], 0, 0.0, 0
    t0 = time.time()
    for mi, (lo, hi) in enumerate(months()):
        if a.months and mi >= a.months:
            break
        bars = loader.load_bars(BAR_TYPE, lo, hi)
        CausalDataLoader.clear_cache()
        tf = time.time()
        for b in bars:
            k.push(int(b.ts_event), int(b.ts_init), b.open.as_double(), b.high.as_double(), b.low.as_double(),
                   b.close.as_double(), b.volume.as_double())
            ev += len(k.drain())
            k.closed_sessions.clear()
            n += 1
        feed += time.time() - tf
        del bars
        gc.collect()
        mem.append({"month": str(lo.date())[:7], "rows_total": n, "rss_mb_after_release": round(rss_mb(), 1),
                    "kernel_price_buf": len(k._px.ts), "kernel_cum_buf": len(k._cum.ts), "kernel_elig_vol": len(k.elig_vol),
                    "kernel_elig_prof": len(k.elig_prof)})
        print(json.dumps(mem[-1]), flush=True)
    r = [x["rss_mb_after_release"] for x in mem[2:]] or [0.0]
    out = {"capability": "tracker.volume_clock.developing", "mode": "feed-only memory/throughput probe", "rows": n,
           "events": ev, "feed_seconds": round(feed, 1), "rows_per_second": round(n / feed) if feed else None,
           "wall_seconds": round(time.time() - t0, 1), "memory_by_month": mem,
           "rss_range_after_warmup_mb": [min(r), max(r)], "passed": True}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1) + chr(10), encoding="utf-8")
    print(json.dumps({k_: out[k_] for k_ in ("rows", "rows_per_second", "rss_range_after_warmup_mb")}))
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("replay"); r.add_argument("--dir", required=True); r.add_argument("--months", type=int, default=0)
    c = sub.add_parser("compare"); c.add_argument("--dir", required=True); c.add_argument("--out", required=True)
    c.add_argument("--smoke", action="store_true", help="bounded replay: comparisons run, passed stays false")
    p = sub.add_parser("probe"); p.add_argument("--out", required=True); p.add_argument("--months", type=int, default=0)
    a = ap.parse_args(list(argv) if argv is not None else None)
    return {"replay": replay, "compare": compare, "probe": probe}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())

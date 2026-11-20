"""Historical parity replay for tracker.volume_clock.developing against the frozen vc_v1 Stage C engine.

Streams NQ_1S_V2_GLOBEX 1s bars (canonical CausalDataLoader, one calendar month at a time, 2023-11 .. 2025-12;
no 2026 row is requested) through VolumeClockKernel from the Stage C origin (Globex session 2023-11-01) and compares:

  C1 session classes, calibration flags, cal_source_dates, target_exact, T            vs daily_calibration.parquet
  C2 every completed bar: (date, bar_seq, start_ts, end_ts, avail_ts, dur_raw, duration_s, cum contracts, collapsed,
     open/high/low/close)                                                             vs volume_bars_v1.parquet
  C3 per-session bar counts and volume conservation (n_bars * T + residual == RTH volume)
  D1 sampled developing states (every 97th RTH row of every built session) vs an independent vectorised
     reference from the same rows + the frozen Stage C bars (consumed, frac, n_completed, elapsed, bar open/high/low,
     carry, rates, r_exp, vol_w / rv_w, dir_d60)
  D2 every checkpoint crossing (bar_seq, level, ts) vs the reference crossing row from the frozen bars

The oracle files are read-only and sha256-pinned. Memory (RSS, kernel buffer sizes) is sampled every month.
Usage: python scripts/parity/volume_clock_developing_parity.py --out artifacts/parity/volume_clock_developing.json [--months N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from features.trackers.volume_clock_developing import (  # noqa: E402
    DIR_WINDOW_S, MIN_NS, NS, VolumeClockKernel, load_calendar)

ORACLE_DIR = Path("C:/Users/Scott McCarty/Projects/Nautilus Trader-nq_adaptive_volume_clock/research/nq_adaptive_volume_clock/out/full")
ORACLE_PINS = {"volume_bars_v1.parquet": "1913951903cced6f7ba0a574c391cd2c78719338e6d19fb36a8743a70aac691c",
               "daily_calibration.parquet": "5e958a44e5a116f0d8e73eadc658442c076187f810519a212a0f914ed4a053b2"}
DATASET = "NQ_1S_V2_GLOBEX"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
ORIGIN = pd.Timestamp("2023-10-31 22:00:00", tz="UTC")       # open of Globex session 2023-11-01 (17:00 CT)
END = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")          # last Stage C session 2025-12-31; never 2026
SAMPLE_EVERY = 97
RV_W, RATE_W, CPS = (15, 30, 60, 120, 300), (10, 15, 30), (0.25, 0.50, 0.75)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def rss_mb() -> float:
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / 2**20
    except Exception:       # pragma: no cover
        return float("nan")


def months():
    m = ORIGIN.tz_localize(None).to_period("M")
    while m.start_time <= END.tz_localize(None):
        a = max(m.start_time.tz_localize("UTC"), ORIGIN)
        b = min((m + 1).start_time.tz_localize("UTC") - pd.Timedelta(seconds=1), END)
        yield a, b
        m += 1


# ----------------------------------------------------------------------------------------------- reference
def ref_session(rows: np.ndarray, rs, T: int, frozen: pd.DataFrame, r_exp: np.ndarray, pre: np.ndarray):
    """Independent vectorised developing state at sampled rows. rows: (n, 6) ts_event, o, h, l, c, v (RTH rows).
    pre: (m, 2) ts_init, close of the rows before the session (for dir_d60 near the open). Returns {ts_init: dict}."""
    ts = rows[:, 0].astype(np.int64)
    o, h, l, c, v = rows[:, 1], rows[:, 2], rows[:, 3], rows[:, 4], rows[:, 5].astype(np.int64)
    ti = ts + NS
    C = np.cumsum(v)
    avail = frozen.avail_ts.to_numpy(np.int64)
    bclose = frozen.close.to_numpy(float)
    nb = len(avail)
    # first row with volume -> bar-1 open (Stage C: o[searchsorted(C, 1)])
    first = int(np.searchsorted(C, 1, side="left"))
    all_ti = np.concatenate([pre[:, 0].astype(np.int64), ti])
    all_c = np.concatenate([pre[:, 1], c])
    out = {}
    for i in range(0, len(ts), SAMPLE_EVERY):
        t = int(ti[i])
        n = int(np.searchsorted(avail, t, side="right"))          # bars available by t
        cum = int(C[i])
        consumed = cum - n * T
        origin = int(avail[n - 1]) if n else rs.start_ns
        # developing bar rows: from the row holding contract n*T+1 up to i
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
        d = {"n_completed": n, "consumed": consumed, "frac": consumed / T, "elapsed_s": elapsed, "bar_open_price": bo,
             "bar_high": hi, "bar_low": lo, "carry_contracts": (cum_origin - n * T) if n else 0,
             "internal_contracts": cum - cum_origin}
        if elapsed > 0:
            d["rate_since_open"] = (cum - cum_origin) / elapsed
            for w in RATE_W:
                ww = min(w, elapsed)
                j = int(np.searchsorted(ti, t - ww * NS, side="right")) - 1
                d[f"rate_last_{w}s"] = (cum - (int(C[j]) if j >= 0 else 0)) / ww
        m = (t - NS - rs.start_ns) // MIN_NS
        r = float(r_exp[m])
        d["r_exp"] = r
        for w in RV_W:
            if t - w * NS >= rs.start_ns:
                j = int(np.searchsorted(ti, t - w * NS, side="right")) - 1
                vw = cum - (int(C[j]) if j >= 0 else 0)
                d[f"vol_{w}s"] = vw
                d[f"rv_{w}s"] = vw / (w * r) if r > 0 else None
        j = int(np.searchsorted(all_ti, t - DIR_WINDOW_S * NS, side="right")) - 1
        if j >= 0:
            dd = float(c[i]) - float(all_c[j])
            d["d60_points"] = dd
            d["dir_d60"] = int(np.sign(dd))
        out[t] = d
    # checkpoint crossings: first row where cum - (n-1)T >= q*T, for every frozen bar n and the session's final
    # incomplete (residual) bar nb+1 when its residual reaches q
    cps = set()
    for n in range(1, nb + 2):
        for q in CPS:
            k = int(np.searchsorted(C - (n - 1) * T, q * T, side="left"))
            if k < len(C):
                cps.add((n, q, int(ti[k])))
    return out, cps


def same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        return (math.isnan(a) and math.isnan(b)) or abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


# ----------------------------------------------------------------------------------------------- probe
def probe(a) -> int:
    """Feed-only run: nothing is retained outside the kernel, so RSS growth would be the kernel's own."""
    import gc
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


# ----------------------------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--months", type=int, default=0, help="limit (smoke); 0 = full 2023-11..2025-12")
    ap.add_argument("--probe", action="store_true", help="memory/throughput probe: feed the kernel only, keep nothing")
    a = ap.parse_args()
    if a.probe:
        return probe(a)
    t0 = time.time()
    pins = {k: sha256(ORACLE_DIR / k) for k in ORACLE_PINS}
    if pins != ORACLE_PINS:
        raise SystemExit(f"ORACLE_HASH_MISMATCH {pins}")
    fb = pd.read_parquet(ORACLE_DIR / "volume_bars_v1.parquet")
    dc = pd.read_parquet(ORACLE_DIR / "daily_calibration.parquet")
    fb_by = {d: g.sort_values("bar_seq").reset_index(drop=True) for d, g in fb.groupby("date")}
    dc_by = {r.date: r for r in dc.itertuples(index=False)}

    from research_workflow.roots import resolve_dataset
    from utils.runner.data import CausalDataLoader
    cat = resolve_dataset(DATASET, REPO).catalog_path
    cal = load_calendar(DATASET)
    k = VolumeClockKernel(cal, rv_windows=RV_W, rate_windows=RATE_W, checkpoints=CPS)

    completed, closed, cps_k = [], [], set()
    dev_mismatch, dev_checked, dev_fields = [], 0, {}
    cps_ref_all = set()
    minute_prof: dict = {}
    mem, n_rows, feed_s = [], 0, 0.0
    sess_rows: list = []
    sess_states: dict = {}
    pre_buf: list = []           # (ts_init, close) of rows outside the open RTH session, last 120 s
    cur_rs = None
    loader = CausalDataLoader(cat)

    def finish_session(rs):
        nonlocal dev_checked
        if rs is None or not sess_rows:
            return
        arr = np.asarray(sess_rows, dtype=np.float64)
        mv = np.bincount(((arr[:, 0].astype(np.int64) - rs.start_ns) // MIN_NS), weights=arr[:, 5], minlength=405)[:405]
        minute_prof[rs.date] = mv
        row = dc_by.get(rs.date)
        if row is None or not bool(row.calibrated) or rs.date not in fb_by:
            return
        srcs = str(row.cal_source_dates).split(",")
        if not all(sd in minute_prof for sd in srcs):
            return
        r_exp = np.mean(np.vstack([minute_prof[sd] for sd in srcs]), axis=0) / 60.0
        pre = np.asarray(pre_snapshot, dtype=np.float64).reshape(-1, 2)
        ref, cps = ref_session(arr, rs, int(row.T_V1), fb_by[rs.date], r_exp, pre)
        cps_ref_all.update((rs.date,) + x for x in cps)
        for t, d in ref.items():
            st = sess_states.get(t)
            if st is None:
                dev_mismatch.append({"date": rs.date, "t": t, "field": "<missing tracker state>"})
                continue
            dev_checked += 1
            for f, val in d.items():
                dev_fields[f] = dev_fields.get(f, 0) + 1
                if not same(st.get(f), val):
                    if len(dev_mismatch) < 50:
                        dev_mismatch.append({"date": rs.date, "t": t, "field": f, "tracker": st.get(f), "reference": val})
                    else:
                        dev_mismatch.append(None)

    pre_snapshot: list = []
    for mi, (lo, hi) in enumerate(months()):
        if a.months and mi >= a.months:
            break
        bars = loader.load_bars(BAR_TYPE, lo, hi)
        CausalDataLoader.clear_cache()
        tf = time.time()
        for b in bars:
            te, ti = int(b.ts_event), int(b.ts_init)
            o, h, l, c, v = b.open.as_double(), b.high.as_double(), b.low.as_double(), b.close.as_double(), b.volume.as_double()
            k.push(te, ti, o, h, l, c, v)
            n_rows += 1
            st = k.state
            rs = k.sess["rs"] if k.sess is not None else None
            if rs is not cur_rs:
                finish_session(cur_rs)
                pre_snapshot = list(pre_buf)
                sess_rows, sess_states = [], {}
                cur_rs = rs
            if rs is not None:
                sess_rows.append((te, o, h, l, c, v))
                if st["calibrated"] and (len(sess_rows) - 1) % SAMPLE_EVERY == 0:
                    sess_states[ti] = dict(st)
            else:
                pre_buf.append((ti, c))
                if len(pre_buf) > 400:
                    del pre_buf[:200]
            for name, p in k.drain():
                if name == "bar_completed":
                    completed.append(p)
                elif name == "checkpoint":
                    cps_k.add((p["session_date"], p["bar_seq"], p["level"], p["ts"]))
            if k.closed_sessions:
                closed.extend(k.closed_sessions)
                k.closed_sessions.clear()
        feed_s += time.time() - tf
        del bars
        mem.append({"month": str(lo.date())[:7], "rows_total": n_rows, "rss_mb": round(rss_mb(), 1),
                    "kernel_price_buf": len(k._px.ts), "kernel_cum_buf": len(k._cum.ts), "kernel_elig_vol": len(k.elig_vol),
                    "kernel_elig_prof": len(k.elig_prof)})
        print(json.dumps(mem[-1]), flush=True)
    # flush the last session (a row past its end would close it in a live stream)
    k._close_session()
    closed.extend(k.closed_sessions)
    for name, p in k.drain():
        if name == "bar_completed":
            completed.append(p)
    finish_session(cur_rs)

    # ------------------------------------------------------------------------------------------- comparisons
    res: dict = {"capability": "tracker.volume_clock.developing", "dataset": DATASET, "oracle_dir": str(ORACLE_DIR),
                 "oracle_sha256": pins, "window": [str(ORIGIN), str(END)], "rows_fed": n_rows}
    kc = pd.DataFrame(closed)
    last_date = kc.session_date.max() if len(kc) else ""
    dcw = dc[dc.date <= last_date]
    m = dcw.merge(kc, left_on="date", right_on="session_date", how="left", suffixes=("_o", "_k"))
    built_o = dcw[dcw.calibrated & dcw.rth_class.isin(["FULL", "ROLL_TRANSITION", "SHORT_RTH"])]
    c1 = {"oracle_sessions": int(len(dcw)), "tracker_sessions_closed": int(len(kc)),
          "class_mismatch": [], "calibration_mismatch": []}
    for r in m.itertuples(index=False):
        if r.rth_class_o in ("NO_RTH", "MISSING_DATA"):
            if isinstance(r.session_date, str):
                c1["class_mismatch"].append({"date": r.date, "oracle": r.rth_class_o, "tracker": r.rth_class_k})
            continue
        if r.rth_class_o != r.rth_class_k:
            c1["class_mismatch"].append({"date": r.date, "oracle": r.rth_class_o, "tracker": r.rth_class_k})
        if bool(r.calibrated_o) != bool(r.calibrated_k):
            c1["calibration_mismatch"].append({"date": r.date, "what": "calibrated", "oracle": bool(r.calibrated_o)})
        elif bool(r.calibrated_o):
            if not (int(r.T_V1) == int(r.T) and r.V1_exact == r.target_exact and r.cal_source_dates_o == r.cal_source_dates_k
                    and int(r.rth_volume_o) == int(r.rth_volume_k)):
                c1["calibration_mismatch"].append({"date": r.date, "T_o": int(r.T_V1), "T_k": r.T, "ex_o": r.V1_exact,
                                                   "ex_k": r.target_exact, "vol_o": int(r.rth_volume_o), "vol_k": r.rth_volume_k})
    c1["built_sessions"] = int(len(built_o))
    c1["pass"] = not c1["class_mismatch"] and not c1["calibration_mismatch"]
    res["C1_sessions_and_calibration"] = c1

    kb = pd.DataFrame(completed)
    kb = kb.rename(columns={"session_date": "date"})
    fbw = fb[fb.date <= last_date]
    key = ["date", "bar_seq"]
    j = fbw.merge(kb, on=key, how="outer", suffixes=("_o", "_k"), indicator=True)
    only_o, only_k = j[j._merge == "left_only"], j[j._merge == "right_only"]
    both = j[j._merge == "both"]
    cmp = {}
    for f in ("start_ts", "end_ts", "avail_ts", "dur_raw", "duration_s", "cum_session_contracts", "T", "collapsed"):
        cmp[f] = int((both[f + "_o"].astype("int64") != both[f + "_k"].astype("int64")).sum())
    for f in ("open", "high", "low", "close"):
        o_, k_ = both[f + "_o"].to_numpy(float), pd.to_numeric(both[f + "_k"], errors="coerce").to_numpy(float)
        cmp[f] = int((~((o_ == k_) | (np.isnan(o_) & np.isnan(k_)))).sum())
    rep = fbw[fbw.reported & fbw.primary] if "primary" in fbw else fbw
    kb_rep = both[both.reported & both.primary]
    c2 = {"oracle_bars_all": int(len(fbw)), "tracker_bars_all": int(len(kb)), "only_oracle": int(len(only_o)),
          "only_tracker": int(len(only_k)), "field_mismatches": cmp, "oracle_primary_2024_2025": int(len(rep)),
          "matched_primary_2024_2025": int(len(kb_rep)),
          "primary_exact": int(len(kb_rep)) == int(len(rep)) and all(v == 0 for v in cmp.values()),
          "only_oracle_examples": only_o[key].head(5).to_dict("records"), "only_tracker_examples": only_k[key].head(5).to_dict("records")}
    c2["pass"] = c2["only_oracle"] == 0 and c2["only_tracker"] == 0 and all(v == 0 for v in cmp.values())
    res["C2_completed_bars"] = c2

    cons = kc[kc.calibrated == True]                                              # noqa: E712
    bad = cons[cons.n_bars * cons["T"] + cons.residual_contracts != cons.rth_volume]
    per = fbw.groupby("date").size()
    kcnt = cons.set_index("session_date").n_bars
    cnt_bad = [d for d in per.index if int(kcnt.get(d, -1)) != int(per[d])]
    res["C3_counts_and_conservation"] = {"sessions": int(len(cons)), "conservation_violations": int(len(bad)),
                                         "count_mismatch_sessions": cnt_bad[:20], "pass": len(bad) == 0 and not cnt_bad}

    nm = [x for x in dev_mismatch if x is not None]
    res["D1_developing_reference"] = {"epochs_checked": dev_checked, "field_checks": dev_fields,
                                      "mismatches": len(dev_mismatch), "examples": nm[:20], "pass": dev_checked > 0 and not dev_mismatch}
    cps_ref = {x for x in cps_ref_all}
    res["D2_checkpoints"] = {"reference_crossings": len(cps_ref), "tracker_crossings_in_reference_sessions":
                             len({x for x in cps_k if x[0] in {y[0] for y in cps_ref}}),
                             "only_reference": len(cps_ref - cps_k), "only_tracker":
                             len({x for x in cps_k if x[0] in {y[0] for y in cps_ref}} - cps_ref),
                             "examples_only_reference": sorted(cps_ref - cps_k)[:5]}
    res["D2_checkpoints"]["pass"] = res["D2_checkpoints"]["only_reference"] == 0 and res["D2_checkpoints"]["only_tracker"] == 0
    rss = [x["rss_mb"] for x in mem]
    res["performance"] = {"feed_seconds": round(feed_s, 1), "rows_per_second": round(n_rows / feed_s) if feed_s else None,
                          "wall_seconds": round(time.time() - t0, 1), "memory_by_month": mem,
                          "kernel_buffers_bounded": max(x["kernel_price_buf"] for x in mem) < 8192 and max(x["kernel_cum_buf"] for x in mem) < 8192
                          and max(x["kernel_elig_vol"] for x in mem) <= 20 and max(x["kernel_elig_prof"] for x in mem) <= 5}
    res["passed"] = bool(c1["pass"] and c2["pass"] and res["C3_counts_and_conservation"]["pass"]
                         and res["D1_developing_reference"]["pass"] and res["D2_checkpoints"]["pass"]
                         and res["performance"]["kernel_buffers_bounded"] and not a.months)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k_: (v_["pass"] if isinstance(v_, dict) and "pass" in v_ else None) for k_, v_ in res.items()} | {"passed": res["passed"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

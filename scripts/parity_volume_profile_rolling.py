"""R0 parity of tracker.volume_profile.rolling against the stored study-local ledgers (read-only oracle).

Input = the oracle's own 1s tape cache (CausalDataLoader output of NQ_1S_V2_GLOBEX, ts = ts_init); calendar
and rolls = the catalog's hash-verified reference tables. The kernel starts at the oracle's origin
(poc_node.prepare_block: the open of the second session before the block) so A's cumulative sums see the
same history. Every closed minute in (emit_from, emit_to] is snapshotted and joined by ts to:
  120  -> nq_vp120_edge_fade/_work/PROFILE_<block>.parquet
  360  -> nq_poc_node_edge_rejection/_work/MP_VP6H_<block>.parquet
  1380 -> nq_poc_node_edge_rejection/_work/MP_VP24H_<block>.parquet   (legacy "24H" = one 23 h Globex session)
Only 2022 / 2023dev are ever opened.

    python scripts/parity_volume_profile_rolling.py --block 2022 [--days 7] --out artifacts/parity/x.json
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from features.trackers.volume_profile_rolling import MIN_NS, VolumeProfileKernel, open_minute_ends  # noqa: E402
from research_workflow import dataset_v2  # noqa: E402

MAIN = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
CATALOG = MAIN / "data" / "catalog" / "NQ_1S_V2_GLOBEX"
TAPE = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-nq_auction_map_1s\studies\nq_auction_map_1s\_work\tape")
VPW = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-nq_auction_map_1s-nq_poc_node_edge_rejection-nq_vp120_edge_fade\studies\nq_vp120_edge_fade\_work")
NODEW = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-nq_auction_map_1s-nq_poc_node_edge_rejection\studies\nq_poc_node_edge_rejection\_work")
BLOCKS = {"2022": ("2022-01-03", "2022-12-30"), "2023dev": ("2023-01-03", "2023-10-17")}
DEV_END = pd.Timestamp("2023-10-17 21:00", tz="UTC").value
ORACLE = {120: lambda b: VPW / f"PROFILE_{b}.parquet", 360: lambda b: NODEW / f"MP_VP6H_{b}.parquet", 1380: lambda b: NODEW / f"MP_VP24H_{b}.parquet"}
COLS = ["poc", "vah", "val", "A", "win_lo", "win_hi", "va_frac_o", "n_hvn", "n_lvn", "hvns", "win_volume"]


def tape(t0: int, t1: int) -> pd.DataFrame:
    months = pd.period_range(pd.Timestamp(t0, tz="UTC").tz_localize(None), pd.Timestamp(t1, tz="UTC").tz_localize(None), freq="M")
    d = pd.concat([pd.read_parquet(TAPE / f"{p.year}-{p.month:02d}.parquet") for p in months], ignore_index=True)
    return d[(d.ts > t0) & (d.ts <= t1)].reset_index(drop=True)


def oracle(h: int, block: str, ef: int, et: int) -> pd.DataFrame:
    o = pd.read_parquet(ORACLE[h](block))
    o = o[(o.ts > ef) & (o.ts <= et)]
    o = o.rename(columns={"va_frac": "va_frac_o", "value_area_volume_fraction": "va_frac_o"})
    keep = [c for c in ["ts"] + COLS if c in o.columns]
    return o[keep].set_index("ts")


def exact_va(d: pd.DataFrame, om, start: int, p: int, a_t: int, b_t: int, ip_t: int, frac: float = 0.70):
    """Value-area walk on the EXACT rational range_uniform profile of the window (oracle semantics)."""
    w = d[(d.ts > int(om[start]) - MIN_NS) & (d.ts <= int(om[p]))]
    X = [Fraction(0)] * (b_t - a_t + 1)
    for h, l, v in zip(w.h.to_numpy(), w.l.to_numpy(), w.v.to_numpy()):
        lt, ht = int(round(l / 0.25)), int(round(h / 0.25))
        q = Fraction(int(v), ht - lt + 1)
        for k in range(lt, ht + 1):
            X[k - a_t] += q
    tot, ip, n = sum(X), ip_t - a_t, len(X)
    lo = hi = ip
    acc, steps, stop = X[ip], [], []
    while True:
        stop.append(abs(acc - Fraction(frac) * tot) / tot)
        if not (acc < Fraction(frac) * tot and (lo > 0 or hi < n - 1)):
            break
        up = sum(X[hi + 1:min(hi + 3, n)]) if hi < n - 1 else Fraction(-1)
        dn = sum(X[max(lo - 2, 0):lo]) if lo > 0 else Fraction(-1)
        steps.append(up - dn)
        if up > dn:
            acc += up; hi = min(hi + 2, n - 1)
        elif dn > up:
            acc += dn; lo = max(lo - 2, 0)
        else:
            acc += up + dn; hi = min(hi + 2, n - 1); lo = max(lo - 2, 0)
    return (lo + a_t) * 0.25, (hi + a_t) * 0.25, sum(1 for s in steps if s == 0), float(min(stop))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", required=True, choices=sorted(BLOCKS))
    ap.add_argument("--days", type=int, default=0, help="probe: only the first N calendar days of emission")
    ap.add_argument("--horizons", default="120,360,1380")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t_start = time.time()
    ref = dataset_v2.load_reference_tables(CATALOG, ["sessions", "rolls"])
    s = ref["sessions"].copy()
    s["session_date"] = s.session_date.astype(str)
    s = s[s.close_ns <= DEV_END].sort_values("open_ns").reset_index(drop=True)
    s0, s1 = BLOCKS[a.block]
    blk = s[(s.session_date >= s0) & (s.session_date <= s1)]
    ef, et = int(blk.open_ns.min()), int(blk.close_ns.max())
    if a.days:
        et = min(et, ef + a.days * 86400 * 10**9)
    t0 = int(s[s.close_ns <= ef].tail(2).open_ns.min())
    om = open_minute_ends(s.open_ns.to_numpy(), s.close_ns.to_numpy())
    rolls = np.sort(ref["rolls"].ts_ns.to_numpy().astype(np.int64))
    H = [int(x) for x in a.horizons.split(",")]
    K = {h: VolumeProfileKernel(om, rolls, h, "range_uniform", origin_ns=t0) for h in H}
    m0 = int(om[np.searchsorted(om, t0, side="right")])
    d = tape(m0 - MIN_NS, et)
    t_load = time.time() - t_start
    rows = {h: [] for h in H}
    for h, k in K.items():
        k.on_close = (lambda kk, rr: (lambda p: rr.append(kk.snapshot()) if ef < kk.om[p] <= et else None))(k, rows[h])
    ts_, hh, ll, cc, vv = (d[k].to_numpy() for k in ("ts", "h", "l", "c", "v"))
    t_feed = time.time()
    kl = list(K.values())
    for i in range(len(ts_)):
        a_, b_, c_, d_, e_ = int(ts_[i]), float(hh[i]), float(ll[i]), float(cc[i]), float(vv[i])
        for k in kl:
            k.push(a_, b_, c_, d_, e_)
    for k in kl:                                                            # trailing minutes of the range
        k.close_through(et)
    t_feed = time.time() - t_feed
    report = dict(block=a.block, emit_from=ef, emit_to=et, origin=t0, bars=int(len(d)), probe_days=a.days, seconds=dict(load=round(t_load, 1), feed_and_snapshot=round(t_feed, 1)), horizons={})
    for h in H:
        C = pd.DataFrame([r for r in rows[h] if r is not None]).set_index("snapshot_ts")
        O = oracle(h, a.block, ef, et)
        J = C.join(O, how="inner", rsuffix="_o")
        poc_eq = (J.poc == J.poc_o)
        res = dict(capability_minutes=int(len(C)), oracle_rows=int(len(O)), joined=int(len(J)),
                   oracle_missing_in_capability=int((~O.index.isin(C.index)).sum()),
                   oracle_rows_capability_null=int(J.poc.isna().sum()),
                   poc_mismatch=int((~poc_eq & J.poc.notna()).sum()), vah_mismatch=int((J.vah != J.vah_o).sum()), val_mismatch=int((J.val != J.val_o).sum()),
                   A_max_rel_diff=float(np.nanmax(np.abs(J.A / J.A_o - 1))) if len(J) else None,
                   win_lo_mismatch=int((J.win_lo != J.win_lo_o).sum()), win_hi_mismatch=int((J.win_hi != J.win_hi_o).sum()),
                   va_frac_max_abs_diff=float(np.nanmax(np.abs(J.va_weight_fraction - J.va_frac_o))) if len(J) else None,
                   dropped_bars=int(K[h].dropped))
        if "win_volume" in J:
            res["total_weight_max_abs_diff"] = float(np.nanmax(np.abs(J.total_weight - J.win_volume)))
        if "n_hvn" in J.columns and "n_hvn_o" in J.columns:
            res["n_hvn_mismatch"] = int((J.n_hvn != J.n_hvn_o).sum()); res["n_lvn_mismatch"] = int((J.n_lvn != J.n_lvn_o).sum())
            cen = lambda js: tuple(x["center"] for x in json.loads(js))  # noqa: E731
            res["hvn_centers_mismatch"] = int(sum(cen(x) != cen(y) for x, y in zip(J.hvns_json, J.hvns)))
        res["eligible_without_oracle"] = int((C.window_complete & C.poc.notna() & ~C.index.isin(O.index)).sum()) if h == 120 else \
            int((C.poc.notna() & ~C.index.isin(O.index)).sum())
        mm = J[(J.poc != J.poc_o) | (J.vah != J.vah_o) | (J.val != J.val_o)]
        cls = []
        for t_, r in mm.iterrows():
            start = int(r.minute_idx) - int(r.window_minutes) + 1
            pad = int(np.ceil(4 * r.sigma_ticks)) + 2
            a_t, b_t = int(round(r.win_lo / 0.25)) - pad, int(round(r.win_hi / 0.25)) + pad
            ev, eh, nties, stop_rel = exact_va(d, om, start, int(r.minute_idx), a_t, b_t, int(round(r.poc / 0.25)))
            cls.append(dict(ts=int(t_), poc=r.poc, vah=(r.vah, r.vah_o, eh), val=(r.val, r.val_o, ev), exact_ties_in_walk=nties, min_stop_rel=stop_rel, stop_tie=bool(stop_rel <= 1e-15),
                            capability_equals_exact=bool(r.vah == eh and r.val == ev), oracle_equals_exact=bool(r.vah_o == eh and r.val_o == ev)))
        res["mismatches"] = cls
        res["mismatch_capability_equals_exact"] = sum(c["capability_equals_exact"] for c in cls)
        res["mismatch_oracle_equals_exact"] = sum(c["oracle_equals_exact"] for c in cls)
        res["mismatch_with_exact_tie"] = sum(c["exact_ties_in_walk"] > 0 or c["stop_tie"] for c in cls)
        res["mismatch_pair_tie"] = sum(c["exact_ties_in_walk"] > 0 for c in cls)
        res["mismatch_stop_tie_only"] = sum(c["exact_ties_in_walk"] == 0 and c["stop_tie"] for c in cls)
        report["horizons"][str(h)] = res
    # PASS = every oracle row reproduced; POC exact; every VAH / VAL difference is a minute whose EXACT rational
    # walk contains an exact tie -- a pair tie (up == dn) or a stop tie (accumulated == va_frac x total to <= 1e-15
    # relative) -- that the oracle's float arithmetic broke, and the capability equals the exact rational walk.
    report["passed"] = all(v["poc_mismatch"] == v["oracle_missing_in_capability"] == v["oracle_rows_capability_null"] == 0
                           and v["mismatch_capability_equals_exact"] == len(v["mismatches"]) == v["mismatch_with_exact_tie"]
                           for v in report["horizons"].values())
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != "horizons"} | {h: {k: v for k, v in r.items() if k != "mismatches"} for h, r in report["horizons"].items()}, default=str))


if __name__ == "__main__":
    main()

"""Compression x VWAP 2x2 study on raw flips, 7 years, A and B entries.

Universe: all raw 1m regime flips (v2 collector), 2020-2026.
Compression filter (from the 7-year gate): bucket low / mid / high on
`total_excursion_slow` (mfe+mae over the 30m backward window), tertile
cuts fixed from IS years 2020-2022.

VWAP context, layered on top of compression:
  - session VWAP anchored at 17:00 CT, vol-weighted typical = (h+l+c)/3
  - sigma = sqrt(E[p^2] - VWAP^2), volume-weighted
  - vwap_z      = (close - VWAP) / sigma  (signed, +ve = above VWAP)
  - vwap_z_dir  = vwap_z * direction       (+ve = AWAY from VWAP in
                                            the flip's intended dir)
2x2 cells:
  near       |z|  < 1.0
  stretched  |z| >= 1.0
  away       z_dir  > 0
  toward     z_dir <= 0

Entries (two separate tests):
  A  flip-bar entry      anchor = close at signal_time
  B  bar1-confirm entry  anchor = close at signal_time + 60s,
                         restricted to flips where bar1 confirms
                         (long: bar1.high > flip.high AND bar1.close
                          > bar1.open; short: mirror)

Bracket: +1.0 ATR / -1.0 ATR, unbounded 1s first-touch (matches the
gate scan).  No commission, no NT.  Directional / robustness screen.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
from numba import njit

NS = 1_000_000_000
ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2026)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"
SNAP = "studies/1m_regime_collector_v2/results/v2_feature_snapshots_{}.parquet"
GATE = Path("studies/v_a_excursion_regime/results_v0/"
            "flips_excursion_7yr.parquet")
OUT = Path("studies/v_a_excursion_regime/results_v0")


def session_id_array(ts_ns):
    """CME globex session date: hour < 17 CT -> today, else tomorrow.

    Returned as int64 = days-since-epoch in CT.  Stable across DST.
    """
    ct = (pd.to_datetime(ts_ns, utc=True)
          .tz_convert("America/Chicago"))
    day = ct.normalize()
    add = np.where(ct.hour.values >= 17, 1, 0)
    sid = (day.view("int64") // (24 * 3600 * NS)) + add
    return sid.astype(np.int64)


def compute_session_vwap(bars):
    """Per-1s-bar session-anchored VWAP and vol-weighted sigma.

    Resets at each 17:00 CT session boundary.  Returns vwap, sigma
    arrays aligned with `bars.index`.
    """
    h = bars["high"].to_numpy(np.float64)
    l = bars["low"].to_numpy(np.float64)
    c = bars["close"].to_numpy(np.float64)
    v = bars["volume"].to_numpy(np.float64)
    p = (h + l + c) / 3.0
    pv = p * v
    p2v = p * p * v
    sid = session_id_array(bars.index.values.astype(np.int64))
    f = pd.DataFrame({"sid": sid, "pv": pv, "p2v": p2v, "v": v})
    cum_pv = f.groupby("sid")["pv"].cumsum().to_numpy()
    cum_p2v = f.groupby("sid")["p2v"].cumsum().to_numpy()
    cum_v = f.groupby("sid")["v"].cumsum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = np.where(cum_v > 0, cum_pv / cum_v, np.nan)
        var = np.where(cum_v > 0, cum_p2v / cum_v - vwap * vwap, 0.0)
        sigma = np.sqrt(np.maximum(var, 0.0))
    return vwap, sigma


def build_1m(bars):
    """Epoch-floored 1m bars from 1s."""
    ts = bars.index.values.astype(np.int64)
    bucket = (ts // (60 * NS)) * (60 * NS)
    g = pd.DataFrame({
        "b": bucket, "o": bars["open"].values,
        "h": bars["high"].values, "l": bars["low"].values,
        "c": bars["close"].values})
    agg = g.groupby("b").agg(o=("o", "first"), h=("h", "max"),
                              l=("l", "min"), c=("c", "last"))
    return agg


@njit
def race_from_anchor(anchor_ts, anchor_px, direction, atr,
                     ts, hi, lo):
    """Unbounded 1s forward race from anchor_ts at +1 ATR / -1 ATR."""
    if not np.isfinite(anchor_px) or atr <= 0:
        return -1
    j = np.searchsorted(ts, anchor_ts, side="left")
    if direction == 1:
        tgt, stp = anchor_px + atr, anchor_px - atr
    else:
        tgt, stp = anchor_px - atr, anchor_px + atr
    while j < len(ts):
        h, l = hi[j], lo[j]
        if direction == 1:
            ht, hs = h >= tgt, l <= stp
        else:
            ht, hs = l <= tgt, h >= stp
        if ht and hs:
            return 0
        if ht:
            return 1
        if hs:
            return 0
        j += 1
    return -1


def process_year(year, fl):
    """fl = flips for `year` (subset of gate parquet).  Returns df with
    vwap/confirm/B-outcome appended.  A outcome already in `fl['hit']`.
    """
    parts = []
    for y in (year - 1, year, year + 1):
        p = ONE_S.get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["open", "high", "low", "close", "volume"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    ts = bars.index.values.astype(np.int64)
    cl = bars["close"].to_numpy(np.float64)
    hi = bars["high"].to_numpy(np.float64)
    lo = bars["low"].to_numpy(np.float64)
    vwap, sigma = compute_session_vwap(bars)

    bars1m = build_1m(bars)
    m_ts = bars1m.index.values.astype(np.int64)
    mh, ml = bars1m["h"].to_numpy(), bars1m["l"].to_numpy()
    mo, mc = bars1m["o"].to_numpy(), bars1m["c"].to_numpy()
    midx = {int(t): i for i, t in enumerate(m_ts)}

    n = len(fl)
    vw = np.full(n, np.nan)
    sg = np.full(n, np.nan)
    cT = np.full(n, np.nan)
    confirm = np.zeros(n, dtype=bool)
    bar1_close_px = np.full(n, np.nan)
    hit_B = np.full(n, -1, dtype=np.int64)

    sig = fl["signal_time"].to_numpy(np.int64)
    dr = fl["signal_direction"].to_numpy(np.int64)
    at = fl["atr_at_signal"].to_numpy(np.float64)
    for k in range(n):
        T = int(sig[k])
        d = int(dr[k])
        # VWAP / close at signal_time (last 1s bar with ts < T+1s, i.e.
        # bar that closes at T or just before)
        i = np.searchsorted(ts, T, side="left") - 1
        if i < 0:
            continue
        vw[k] = vwap[i]; sg[k] = sigma[i]; cT[k] = cl[i]
        # bar1 confirm: flip bar opens at T-60s, bar1 opens at T
        fb = midx.get(T - 60 * NS, -1)
        b1 = midx.get(T, -1)
        if fb >= 0 and b1 >= 0:
            if d == 1:
                confirm[k] = mh[b1] > mh[fb] and mc[b1] > mo[b1]
            else:
                confirm[k] = ml[b1] < ml[fb] and mc[b1] < mo[b1]
        # B anchor = close at signal_time + 60s (= bar1 close)
        T_b = T + 60 * NS
        j = np.searchsorted(ts, T_b, side="left") - 1
        if j >= 0:
            bar1_close_px[k] = cl[j]
            hit_B[k] = race_from_anchor(T_b, cl[j], d, at[k],
                                         ts, hi, lo)
    out = fl.copy()
    out["vwap"] = vw; out["vwap_sigma"] = sg
    out["close_at_T"] = cT
    out["bar1_confirm"] = confirm
    out["bar1_close_px"] = bar1_close_px
    out["hit_B"] = hit_B
    return out


def main():
    t0 = time.time()
    gate = pd.read_parquet(GATE)
    print(f"Gate parquet: {len(gate):,} flips 2020-2026")
    parts = []
    for y in range(2020, 2027):
        fl = gate[gate["year"] == y].copy()
        if len(fl) == 0:
            continue
        d = process_year(y, fl)
        parts.append(d)
        print(f"  {y}: {len(d):,}  vwap_ok {d['vwap'].notna().mean():.1%}"
              f"  confirm_rate {d['bar1_confirm'].mean():.1%}"
              f"  B resolved {(d['hit_B']!=-1).mean():.1%}")
    df = pd.concat(parts, ignore_index=True)

    # VWAP cells
    df["vwap_z"] = (df["close_at_T"] - df["vwap"]) / df["vwap_sigma"]
    df["vwap_z_dir"] = df["vwap_z"] * df["signal_direction"]
    df["vwap_near"] = df["vwap_z"].abs() < 1.0
    df["vwap_away"] = df["vwap_z_dir"] > 0
    df["cell"] = np.where(
        df["vwap_near"],
        np.where(df["vwap_away"], "near-away", "near-toward"),
        np.where(df["vwap_away"], "stretched-away", "stretched-toward"))

    out_p = OUT / "compression_vwap_study.parquet"
    df.to_parquet(out_p, index=False)
    print(f"\nsaved {out_p}  ({len(df):,} rows)")

    # --- report A and B win rates on the LOW tot_slow subset ---
    df["A_resolved"] = df["hit"] != -1
    df["B_resolved"] = df["hit_B"] != -1
    df["A_win"] = df["hit"] == 1
    df["B_win"] = (df["bar1_confirm"]) & (df["hit_B"] == 1)
    df["B_eligible"] = df["bar1_confirm"] & df["B_resolved"]

    low = df[(df["tot_slow_bkt"] == "low") & df["vwap"].notna()].copy()
    print(f"\n{'='*78}")
    print(f"COMPRESSION (low tot_slow) x VWAP 2x2  --  n={len(low):,}")
    print(f"  cells: near|stretched (|z| vs 1.0)  x  away|toward "
          f"(z_dir sign)")
    print(f"{'='*78}")

    cells = ["near-away", "near-toward", "stretched-away",
             "stretched-toward"]

    for entry, n_col, win_col, elig_col in (
            ("A flip-bar", "A_resolved", "A_win", "A_resolved"),
            ("B bar1-conf", "B_eligible", "B_win", "B_eligible")):
        print(f"\n--- entry: {entry} ---")
        # overall low (no VWAP filter) for reference
        s = low[low[elig_col]]
        w = s[win_col].sum() / len(s) if len(s) else float("nan")
        print(f"  low all (no VWAP filter)   n={len(s):>6,}  "
              f"win {w:.1%}")
        for c in cells:
            s = low[(low["cell"] == c) & low[elig_col]]
            w = s[win_col].sum() / len(s) if len(s) else float("nan")
            print(f"  {c:<24}     n={len(s):>6,}  win {w:.1%}")
        # per-year breakdown for each cell
        print(f"\n  {'cell':<22}{'2020':>9}{'2021':>9}{'2022':>9}"
              f"{'2023':>9}{'2024':>9}{'2025':>9}{'2026':>9}")
        for c in cells:
            sub = low[(low["cell"] == c) & low[elig_col]]
            row = f"  {c:<22}"
            for y in range(2020, 2027):
                g = sub[sub["year"] == y]
                if len(g) < 30:
                    row += f"{'-':>9}"
                else:
                    row += f"{g[win_col].mean():>8.1%}"
                    row += "*" if len(g) >= 200 else "."
            print(row)
        # also show overall low base by year (for delta)
        row = f"  {'(low base)':<22}"
        for y in range(2020, 2027):
            g = low[(low["year"] == y) & low[elig_col]]
            if len(g) < 30:
                row += f"{'-':>9}"
            else:
                row += f"{g[win_col].mean():>8.1%} "
        print(row)

    print(f"\n[done] {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

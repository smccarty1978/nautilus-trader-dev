"""2nd-aligned-flip study — the first pullback-and-realignment inside a proving
1m trend. Restricts to `1m_ordinal == 2` and conditions on path-dependent parent
state (time-in-regime, 1m MFE so far, 1m EMA slope), the variables the Truth
Collector flagged as the only ones with early signal.

For each cell: n, win-rate and $/trade for the symmetric 0.5/0.5 and 1.0/1.0
ATR_5s brackets (bracket-only, 300s hold, exits on PT/SL/parent-1m-flip).
GROSS metrics measure signal merit; NET (after $5 RT + 0.5-tick) measures
tradeability. yrs+ = of the 4 IS years (robustness).

    python studies/regime_5s_scalps/second_flip_study.py --instrument NQ
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import analyze_5s_scalps as A  # noqa: E402

CFG05 = "sym050_5s_bo_300"   # 0.5 ATR_5s : 0.5 ATR_5s
CFG10 = "sym100_5s_bo_300"   # 1.0 ATR_5s : 1.0 ATR_5s
TIME_BINS = [-np.inf, 30, 60, 90, 180, np.inf]
TIME_LABELS = ["0-30s", "30-60s", "60-90s", "90-180s", "180s+"]
MFE_BINS = [-np.inf, 0.25, 0.50, 1.00, np.inf]
MFE_LABELS = ["<0.25", "0.25-0.5", "0.5-1.0", "1.0+"]


def cfg_metrics(sub, cfg):
    pnl = sub[f"pnl_{cfg}"].astype(float); reason = sub[f"reason_{cfg}"].astype(int)
    gross = A.calc_net_pnl(pnl, reason, "gross"); net = A.calc_net_pnl(pnl, reason, "primary")
    if len(sub) == 0:
        return dict(wr=np.nan, gross=np.nan, net=np.nan, pf=np.nan, yrs=0, nyr=0)
    pos = net[net > 0].sum(); neg = -net[net < 0].sum()
    pf = pos / neg if neg > 0 else np.inf
    yp = net.groupby(sub["year"]).sum()
    return dict(wr=(gross > 0).mean() * 100, gross=gross.mean(), net=net.mean(),
                pf=pf, yrs=int((yp > 0).sum()), nyr=int(yp.shape[0]))


def cell(sub):
    m5 = cfg_metrics(sub, CFG05); m10 = cfg_metrics(sub, CFG10)
    return m5, m10


def fmt(n, m5, m10):
    pf = f"{m10['pf']:.2f}" if np.isfinite(m10['pf']) else "inf"
    def w(x): return f"{x:.1f}%" if x == x else "—"
    def d(x): return f"${x:+.2f}" if x == x else "—"
    return (f"| {n:,} | {w(m5['wr'])} | {d(m5['gross'])} | {d(m5['net'])} | "
            f"{w(m10['wr'])} | {d(m10['gross'])} | {d(m10['net'])} | {pf} | "
            f"{m10['yrs']}/{m10['nyr']} |")


HDR = ("| n | WR 0.5 | gross 0.5 | net 0.5 | WR 1.0 | gross 1.0 | net 1.0 | PF 1.0 | yrs+ |")
SEP = "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="NQ", choices=sorted(A.INSTRUMENTS))
    ap.add_argument("--years", default="2021,2022,2023,2024")
    args = ap.parse_args()
    ci = A.INSTRUMENTS[args.instrument]
    A.MULT = ci["mult"]; A.TICK_VAL = ci["tick_val"]; A.PREFIX = ci["prefix"]
    instr = args.instrument
    years = [int(y) for y in args.years.split(",")]

    df = A.load_years(years, "")
    d2 = df[df["1m_ordinal"] == 2].copy()
    base5, base10 = cell(d2)
    slip = 0.5 * A.TICK_VAL

    L = [f"# {instr} — 2nd Aligned 5s Flip Study (first pullback-and-realignment)",
         "",
         f"Restricted to `1m_ordinal == 2` (the 2nd time the 5s flips into alignment with the "
         f"active 1m regime). IS {years[0]}–{years[-1]}, **n = {len(d2):,}**. Brackets are "
         f"symmetric **ATR_5s** (bracket-only, 300s hold, also exits on parent-1m flip). "
         f"`WR` = gross win rate (PnL>0 before costs) = signal merit. `gross`/`net` $/trade "
         f"(net = after $5 RT + 0.5-tick=${slip:.2f}). `yrs+` of 4 = robustness. "
         f"${A.MULT:.0f}/pt.",
         "",
         f"**Baseline (all 2nd-flips):** WR(0.5)={base5['wr']:.1f}%, gross(0.5)=${base5['gross']:+.2f}, "
         f"net(0.5)=${base5['net']:+.2f}; WR(1.0)={base10['wr']:.1f}%, gross(1.0)=${base10['gross']:+.2f}, "
         f"net(1.0)=${base10['net']:+.2f}, PF(1.0)={base10['pf']:.2f}, yrs+ {base10['yrs']}/{base10['nyr']}.",
         ""]

    # ---------- 1. time_since_1m x 1m MFE ----------
    d2["tb"] = pd.cut(d2["time_since_1m"], TIME_BINS, labels=TIME_LABELS)
    d2["mb"] = pd.cut(d2["1m_mfe_atr"], MFE_BINS, labels=MFE_LABELS)
    L += ["## 1. time-since-1m-flip  ×  1m MFE-so-far", "",
          "| Time \\\\ 1m-MFE | MFE bucket | " + HDR[2:]]
    L.append("| --- | --- | " + SEP[6:])
    for tb in TIME_LABELS:
        for mb in MFE_LABELS:
            sub = d2[(d2["tb"] == tb) & (d2["mb"] == mb)]
            if len(sub) == 0:
                continue
            m5, m10 = cell(sub)
            L.append(f"| {tb} | {mb} " + fmt(len(sub), m5, m10))
    # 2-D scan grids (gross $ at 1.0 and WR at 1.0)
    def grid(metric_fn, title, pct=False):
        L.append(""); L.append(f"**{title}** (rows=time, cols=1m-MFE):"); L.append("")
        L.append("| time \\\\ MFE | " + " | ".join(MFE_LABELS) + " |")
        L.append("| --- | " + " | ".join(["---"] * len(MFE_LABELS)) + " |")
        for tb in TIME_LABELS:
            cells = []
            for mb in MFE_LABELS:
                sub = d2[(d2["tb"] == tb) & (d2["mb"] == mb)]
                if len(sub) < 50:
                    cells.append("·")
                else:
                    v = metric_fn(cell(sub)[1])
                    cells.append(f"{v:.1f}%" if pct else f"${v:+.2f}")
            L.append(f"| {tb} | " + " | ".join(cells) + " |")
    grid(lambda m: m["wr"], "WR(1.0:1.0) gross — grid", pct=True)
    grid(lambda m: m["gross"], "GROSS $/trade (1.0:1.0) — grid")
    grid(lambda m: m["net"], "NET $/trade (1.0:1.0) — grid")

    # ---------- 2. EMA slope quintiles ----------
    def quintile_table(col, title):
        L.append(""); L.append(f"## {title}"); L.append("")
        sub_all = d2[d2[col].notna()].copy()
        try:
            sub_all["q"] = pd.qcut(sub_all[col], 5, labels=["Q1 (low)", "Q2", "Q3", "Q4", "Q5 (high)"])
        except Exception:
            L.append("(insufficient spread for quintiles)"); return
        edges = pd.qcut(sub_all[col], 5, retbins=True)[1]
        L.append(f"Quintile edges (favorable-signed, ATR/bar): "
                 f"{', '.join(f'{e:+.3f}' for e in edges)}")
        L.append(""); L.append("| Quintile | " + HDR[2:]); L.append("| --- | " + SEP[6:])
        for q in ["Q1 (low)", "Q2", "Q3", "Q4", "Q5 (high)"]:
            s = sub_all[sub_all["q"] == q]
            m5, m10 = cell(s)
            L.append(f"| {q} " + fmt(len(s), m5, m10))
    quintile_table("ema9_1m_slope", "2. 1m EMA9 slope quintile")
    quintile_table("ema13_1m_slope", "3. 1m EMA13 slope quintile")

    # ---------- 3. bonus: milestones, slope-accel, distance ----------
    L += ["", "## 4. Bonus — Tier-1/2 single splits", ""]
    L.append("| Split | " + HDR[2:]); L.append("| --- | " + SEP[6:])
    for col, lbls in [("1m_reached_025", ("not reached +0.25", "reached +0.25")),
                      ("1m_reached_050", ("not reached +0.50", "reached +0.50")),
                      ("1m_reached_100", ("not reached +1.00", "reached +1.00")),
                      ("1m_net_positive", ("1m net-negative", "1m net-positive"))]:
        for v, lab in [(0, lbls[0]), (1, lbls[1])]:
            s = d2[d2[col] == v]
            if len(s) < 50:
                continue
            m5, m10 = cell(s)
            L.append(f"| {lab} " + fmt(len(s), m5, m10))
    for col, name in [("ema9_1m_slope_accel", "EMA9 slope-accel"),
                      ("ema9_1m_dist_atr", "dist to 1m EMA9")]:
        s_all = d2[d2[col].notna()].copy()
        if len(s_all) < 250:
            continue
        try:
            s_all["t"] = pd.qcut(s_all[col], 3, labels=[f"{name} low", f"{name} mid", f"{name} high"])
        except Exception:
            continue
        for t in s_all["t"].cat.categories:
            s = s_all[s_all["t"] == t]
            m5, m10 = cell(s)
            L.append(f"| {t} " + fmt(len(s), m5, m10))

    out = A.OUT / f"{A.PREFIX}second_flip_study.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"Wrote {out}")
    # console highlights: best gross cells in the time×MFE grid
    print(f"\n{instr} 2nd-flip baseline: WR1.0={base10['wr']:.1f}% gross1.0=${base10['gross']:+.2f} "
          f"net1.0=${base10['net']:+.2f}")
    rows = []
    for tb in TIME_LABELS:
        for mb in MFE_LABELS:
            sub = d2[(d2["tb"] == tb) & (d2["mb"] == mb)]
            if len(sub) >= 200:
                m5, m10 = cell(sub)
                rows.append((tb, mb, len(sub), m10["wr"], m10["gross"], m10["net"], m10["yrs"]))
    rows.sort(key=lambda r: r[4], reverse=True)
    print("Top time×MFE cells by GROSS$/tr (1.0:1.0, n>=200):")
    for tb, mb, n, wr, g, nt, y in rows[:6]:
        print(f"  {tb:>8} | MFE {mb:>8} | n={n:5,} | WR={wr:4.1f}% | gross=${g:+.2f} | net=${nt:+.2f} | yrs+{y}/4")


if __name__ == "__main__":
    main()

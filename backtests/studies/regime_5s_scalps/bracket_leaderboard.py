"""Bracket leaderboard + symmetric-1:1 win-rate analysis from the completed
5s scalp study (IS 2021-2024). Reuses the audited analyzer's cost model and
bucketing so numbers match the main report exactly.

    python studies/regime_5s_scalps/bracket_leaderboard.py --instrument NQ
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import analyze_5s_scalps as A  # noqa: E402

BR_MAP = {
    "sym025": (0.25, 0.25), "sym050": (0.50, 0.50), "sym075": (0.75, 0.75),
    "sym100": (1.00, 1.00), "pos050_025": (0.50, 0.25), "pos100_050": (1.00, 0.50),
    "pos150_075": (1.50, 0.75), "pos200_100": (2.00, 1.00), "nobr": (None, None),
}
SYM = ["sym025", "sym050", "sym075", "sym100"]


def parse_cfg(cfg):
    """cfg = '<br>_<atr>_<flavor>_<hold>' where <br> may contain underscores."""
    for atr in ("5s", "1m"):
        tok = f"_{atr}_"
        if tok in cfg:
            br, rest = cfg.split(tok, 1)
            flavor, hold = rest.split("_", 1)
            return br, atr, flavor, int(hold)
    raise ValueError(cfg)


def win_rates(df, cfg):
    pnl = df[f"pnl_{cfg}"].astype(float)
    reason = df[f"reason_{cfg}"].astype(int)
    gross = A.calc_net_pnl(pnl, reason, "gross")
    net = A.calc_net_pnl(pnl, reason, "primary")
    return float((gross > 0).mean()) * 100, float((net > 0).mean()) * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="NQ", choices=sorted(A.INSTRUMENTS))
    ap.add_argument("--years", default="2021,2022,2023,2024")
    args = ap.parse_args()
    ci = A.INSTRUMENTS[args.instrument]
    A.MULT = ci["mult"]; A.TICK_VAL = ci["tick_val"]; A.PREFIX = ci["prefix"]
    years = [int(y) for y in args.years.split(",")]
    instr = args.instrument

    df = A.load_years(years, "")
    if df is None:
        print("No data"); return
    configs = [c[4:] for c in df.columns if c.startswith("pnl_")]
    n = len(df)
    print(f"{instr}: {n:,} IS scalps, {len(configs)} configs, "
          f"MULT=${A.MULT}/pt slip0.5tick=${0.5*A.TICK_VAL}")

    # ---------- full leaderboard ----------
    rows = []
    for cfg in configs:
        br, atr, flavor, hold = parse_cfg(cfg)
        pt, sl = BR_MAP[br]
        mp = A.compute_metrics(df, cfg, "primary")
        mg = A.compute_metrics(df, cfg, "gross")
        rows.append(dict(
            ptsl=(f"{pt:.2f}/{sl:.2f}" if pt is not None else "none (nobr)"),
            norm=atr, flavor=flavor, hold=hold,
            trades=mp["trades"], win=mp["win_pct"], be=mp["be_win_pct"],
            edge=mp["edge"], gross=mg["gross_pnl_trade"], net=mp["net_pnl_trade"],
            pf=mp["net_pf"], yrs=f"{mp['years_positive']}/{mp['n_years']}"))
    lb = pd.DataFrame(rows).sort_values("net", ascending=False).reset_index(drop=True)

    L = [f"# {instr} 5s Scalp — Bracket Leaderboard (IS {years[0]}–{years[-1]}, {n:,} scalps)",
         "",
         f"Costs: $5 RT commission + 0.5-tick (${0.5*A.TICK_VAL:.2f}) slippage on every non-PT exit; "
         "PT is a limit (0 slip). `win %` = net win rate (net PnL > 0). Sorted by net $/trade.",
         "",
         "| # | PT/SL | ATR norm | Exit flavor | Max hold (s) | Trades | Win % | BE Win % | "
         "Edge % | Gross $/tr | Net $/tr | Net PF | Yrs+ |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for i, r in lb.iterrows():
        pf = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "inf"
        L.append(f"| {i+1} | {r['ptsl']} | {r['norm']} | {r['flavor']} | {r['hold']} | "
                 f"{r['trades']:,} | {r['win']:.1f}% | {r['be']:.1f}% | {r['edge']:.1f}% | "
                 f"${r['gross']:.2f} | ${r['net']:.2f} | {pf} | {r['yrs']} |")
    out = A.OUT / f"{A.PREFIX}bracket_leaderboard.md"

    # ---------- symmetric 1:1 global win rates ----------
    L += ["", "## Symmetric 1:1 brackets — global win rates", "",
          "| PT/SL | ATR norm | Flavor | Hold | Trades | Gross Win % | Net Win % | Net $/tr |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    sym_rows = []
    for cfg in configs:
        br, atr, flavor, hold = parse_cfg(cfg)
        if br not in SYM:
            continue
        gw, nw = win_rates(df, cfg)
        mp = A.compute_metrics(df, cfg, "primary")
        sym_rows.append((BR_MAP[br], atr, flavor, hold, mp["trades"], gw, nw, mp["net_pnl_trade"], cfg))
    sym_rows.sort(key=lambda x: x[5], reverse=True)  # by gross win
    for (pt, sl), atr, flavor, hold, tr, gw, nw, net, cfg in sym_rows:
        L.append(f"| {pt:.2f}/{sl:.2f} | {atr} | {flavor} | {hold} | {tr:,} | "
                 f"{gw:.1f}% | {nw:.1f}% | ${net:.2f} |")
    best_global_gw = max(sym_rows, key=lambda x: x[5])
    best_global_nw = max(sym_rows, key=lambda x: x[6])

    # ---------- best win rate across ANY segmentation bucket (symmetric 1:1) ----------
    edges = {}
    dfb = A.build_buckets(df, edges, fit=True)
    seg_cols = [c for c in dfb.columns if c.startswith("bucket_")]
    sym_cfgs = [c for c in configs if parse_cfg(c)[0] in SYM]
    MIN_TR = 200
    best = {"gross": (0.0, None), "net": (0.0, None)}
    scan_rows = []
    for cfg in sym_cfgs:
        pnl = dfb[f"pnl_{cfg}"].astype(float); reason = dfb[f"reason_{cfg}"].astype(int)
        gwin = (A.calc_net_pnl(pnl, reason, "gross") > 0).astype(float)
        nwin = (A.calc_net_pnl(pnl, reason, "primary") > 0).astype(float)
        tmp = pd.DataFrame({"g": gwin.values, "nt": nwin.values})
        for col in seg_cols:
            tmp["k"] = dfb[col].astype(str).values
            grp = tmp.groupby("k", observed=True).agg(tr=("g", "size"),
                                                       gw=("g", "mean"), nw=("nt", "mean"))
            grp = grp[grp["tr"] >= MIN_TR]
            if grp.empty:
                continue
            gmax = grp["gw"].idxmax()
            if grp.loc[gmax, "gw"] * 100 > best["gross"][0]:
                best["gross"] = (grp.loc[gmax, "gw"] * 100,
                                 (cfg, col.replace("bucket_", ""), gmax, int(grp.loc[gmax, "tr"])))
            nmax = grp["nw"].idxmax()
            if grp.loc[nmax, "nw"] * 100 > best["net"][0]:
                best["net"] = (grp.loc[nmax, "nw"] * 100,
                               (cfg, col.replace("bucket_", ""), nmax, int(grp.loc[nmax, "tr"])))

    L += ["", "## Best win rate for symmetric 1:1 — across ANY segmentation bucket",
          f"(min {MIN_TR} trades per cell; bucket cells across all {len(seg_cols)} "
          f"segmentation features × all {len(sym_cfgs)} symmetric configs)", ""]
    bg, bgi = best["gross"]; bn, bni = best["net"]
    L.append(f"- **Best GROSS win rate:** {bg:.1f}%  ({bgi[1]}={bgi[2]}, config `{bgi[0]}`, n={bgi[3]:,})")
    L.append(f"- **Best NET win rate:** {bn:.1f}%  ({bni[1]}={bni[2]}, config `{bni[0]}`, n={bni[3]:,})")
    L += ["", "### Threshold check (symmetric 1:1)", "",
          "| Threshold | Any global config? | Any segmentation bucket? |",
          "| --- | --- | --- |"]
    for thr in (50.0, 52.5, 55.0):
        gglob = "YES" if best_global_gw[5] > thr else "no"
        gbuck = "YES" if bg > thr else "no"
        L.append(f"| Win rate > {thr:.1f}% (gross) | {gglob} | {gbuck} |")

    out.write_text("\n".join(L), encoding="utf-8")
    print(f"\nWrote {out}\n")
    # console summary
    print("TOP 12 (net $/tr):")
    print(lb.head(12).to_string(index=False))
    print("\nBOTTOM 5 (net $/tr):")
    print(lb.tail(5).to_string(index=False))
    print(f"\nSymmetric 1:1 best GLOBAL gross win = {best_global_gw[5]:.1f}% "
          f"(cfg {best_global_gw[8]}); best global NET win = {best_global_nw[6]:.1f}%")
    print(f"Symmetric 1:1 best gross win across ANY bucket = {bg:.1f}% "
          f"[{bgi[1]}={bgi[2]} cfg {bgi[0]} n={bgi[3]:,}]")
    print(f"Symmetric 1:1 best NET win across ANY bucket = {bn:.1f}% "
          f"[{bni[1]}={bni[2]} cfg {bni[0]} n={bni[3]:,}]")
    print("\nThreshold (symmetric 1:1, GROSS win rate):")
    for thr in (50.0, 52.5, 55.0):
        print(f"  > {thr:>5.1f}% : global={'YES' if best_global_gw[5]>thr else 'no':>3} | "
              f"any-bucket={'YES' if bg>thr else 'no':>3}")


if __name__ == "__main__":
    main()

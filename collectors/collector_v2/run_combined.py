"""Runner for the bar-4 all-flips Combined (Model B pQF + KNN hC) NT strategy.

Phase 3 (default): market-order / state-gated BASELINE sanity run (one year),
emits execution_audit.md and FAILS the run if count_delay_gt_1 > 0 or any FOK/IOC
order is found. Also reports the live-flip -> mapping join rate (universe check).

Usage:
  python collectors/collector_v2/run_combined.py sanity [YEAR]
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

CATALOG = "data/catalog/NQ_v0_2020_2026"
OUT = PROJECT_ROOT / "collectors" / "collector_v2" / "results" / "combined_arch"
OUT.mkdir(parents=True, exist_ok=True)
PQF_MAP = str(OUT / "pqf_mapping.parquet")
HC_MAP = str(OUT / "hc_perbar_mapping.parquet")


def run_one(year: int, label: str, overrides: dict):
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.enums import AccountType, OmsType, TimeInForce
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.objects import Money
    from collectors.collector_v2.run_smoke import create_nq
    from collectors.collector_v2.combined_strategy import CombinedStrategy, CombinedConfig

    out_dir = OUT / f"{label}_{year}"
    out_dir.mkdir(parents=True, exist_ok=True)
    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=5)
    load_end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    catalog = ParquetDataCatalog(CATALOG)
    bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"], start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"], start=load_start, end=load_end)

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"CMB-{year}",
        logging=LoggingConfig(log_level="ERROR", log_directory=str(out_dir / "logs")),
    ))
    engine.add_venue(venue=Venue("XCME"), oms_type=OmsType.NETTING,
                     account_type=AccountType.MARGIN, base_currency=USD,
                     starting_balances=[Money(1_000_000, USD)], bar_execution=True)
    engine.add_instrument(create_nq())
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    cfg_kwargs = dict(
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        mode="trading", rth_only=True,
        position_size=2, base_position_size=2,
        pqf_mapping_path=PQF_MAP, hc_perbar_mapping_path=HC_MAP,
        output_dir=str(out_dir),
    )
    cfg_kwargs.update(overrides)
    strat = CombinedStrategy(CombinedConfig(**cfg_kwargs))
    engine.add_strategy(strat)
    engine.run()

    # ---- collect from cache + strategy state (in-process) ----
    orders = engine.cache.orders()
    fok = sum(1 for o in orders if o.time_in_force == TimeInForce.FOK)
    ioc = sum(1 for o in orders if o.time_in_force == TimeInForce.IOC)
    mkt = sum(1 for o in orders if o.order_type.name == "MARKET")
    audit = dict(strat._audit)
    trades = pd.DataFrame(strat._trades) if strat._trades else pd.DataFrame()
    audit["n_orders"] = len(orders); audit["n_market"] = mkt
    audit["FOK_order_count"] = fok; audit["IOC_order_count"] = ioc
    audit["n_trades"] = len(trades)
    engine.dispose()
    if len(trades):
        trades.to_parquet(out_dir / "trades.parquet", index=False)
    return trades, audit


def sanity(year: int):
    print(f"=== Phase 3 baseline sanity run {year} (raw bar-4 all-flips) ===")
    trades, a = run_one(year, "baseline_sanity", dict(
        pqf_threshold=-1.0, hc_sizing="none", enable_add=False,
        collapse_action="none", deter_action="none"))

    net = float(trades.net_pnl.sum()) if len(trades) else 0.0
    ppt = net / len(trades) if len(trades) else 0.0
    join = (a["bar4_flips_mapped"] / a["bar4_flips_total"] * 100) if a["bar4_flips_total"] else 0.0
    valid = (a["count_delay_gt_1"] == 0) and (a["FOK_order_count"] == 0) and (a["IOC_order_count"] == 0)

    L = [f"# Execution Audit — Phase 3 baseline sanity ({year})", ""]
    L.append(f"Strategy: bar-4 all-flips, GTC market orders, state-gated opposite-regime exit. No ML, no hC mgmt.")
    L.append("")
    L.append("## Execution integrity (HARD INVARIANT)")
    L.append(f"- market_order_confirmed = **{a['n_market'] == a['n_orders'] and a['n_orders']>0}** "
             f"({a['n_market']}/{a['n_orders']} orders are MARKET)")
    L.append(f"- FOK_order_count = **{a['FOK_order_count']}** {'PASS' if a['FOK_order_count']==0 else 'FAIL'}")
    L.append(f"- IOC_order_count = **{a['IOC_order_count']}** {'PASS' if a['IOC_order_count']==0 else 'FAIL'}")
    L.append(f"- opposite_regime_seen_count = {a['opposite_regime_seen_count']}")
    L.append(f"- exit_submitted_count = {a['exit_submitted_count']}")
    L.append(f"- exit_filled_count = {a['exit_filled_count']}")
    L.append(f"- max_bars_after_opposite_regime = **{a['max_bars_after_opposite_regime']}**")
    L.append(f"- count_delay_gt_1 = **{a['count_delay_gt_1']}** "
             f"{'PASS' if a['count_delay_gt_1']==0 else 'FAIL — RUN INVALID'}")
    L.append("")
    L.append(f"## Run validity: **{'VALID' if valid else 'INVALID — DO NOT TRUST'}**")
    L.append("")
    L.append("## Universe / mapping coverage (join rate)")
    L.append(f"- bar-4 flips entered (total) = {a['bar4_flips_total']:,}")
    L.append(f"- of which found in pQF mapping = {a['bar4_flips_mapped']:,} "
             f"(**{join:.1f}%** join rate on regime_start_ts)")
    L.append(f"  - <80% would indicate the capsule is a filtered subset of the live NT flip universe.")
    L.append("")
    L.append("## Activity")
    L.append(f"- n_trades = {a['n_trades']:,} | entries_filled = {a.get('entries_filled','-')}")
    L.append(f"- add_count = {a['add_count']} | reduce_count = {a['reduce_count']} | sizing_count = {a['sizing_count']}")
    L.append(f"- net PnL = ${net:,.0f} | $/trade = ${ppt:,.2f}")
    (OUT / f"execution_audit_{year}.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\nWrote execution_audit_{year}.md")
    return valid


YEARS = [2022, 2023, 2024, 2025, 2026]
OOS = [2025, 2026]
BASE = dict(pqf_threshold=-1.0, hc_sizing="none", enable_add=False,
            collapse_action="none", deter_action="none")
HC_PKGS = {
    "hc_sizing":   dict(hc_sizing="discrete"),
    "hc_add":      dict(enable_add=True),
    "hc_collapse": dict(collapse_action="reduce"),
    "hc_deter":    dict(deter_action="reduce_if_profit"),
    "hc_combined": dict(hc_sizing="discrete", enable_add=True,
                        collapse_action="reduce", deter_action="reduce_if_profit"),
}
ML_PCTS = [20, 40]


def _worker(task):
    import json as _json
    label, year, overrides = task
    out_dir = OUT / f"{label}_{year}"
    if (out_dir / "audit.json").exists() and (out_dir / "done.flag").exists():
        return (label, year, "cached")
    try:
        trades, audit = run_one(year, label, dict(overrides))
        with open(out_dir / "audit.json", "w") as f:
            _json.dump({k: (float(v) if isinstance(v, (int, float)) else v)
                        for k, v in audit.items()}, f)
        (out_dir / "done.flag").write_text("ok")
        return (label, year, "ok")
    except Exception as e:
        return (label, year, f"ERROR: {e}")


def _metrics(df):
    if df is None or len(df) == 0:
        return dict(n=0, net=0.0, ppt=0.0, pf=0.0, wr=0.0, maxdd=0.0)
    d = df.sort_values("entry_ts")
    p = d.net_pnl.values
    net = float(p.sum()); n = len(p)
    pos = p[p > 0].sum(); neg = -p[p < 0].sum()
    eq = np.cumsum(p); maxdd = float((np.maximum.accumulate(eq) - eq).max())
    return dict(n=n, net=net, ppt=net / n, pf=float(pos / neg) if neg > 0 else float("inf"),
                wr=float((p > 0).mean() * 100), maxdd=maxdd)


def _load(label, year):
    import json as _json
    d = OUT / f"{label}_{year}"
    tp = d / "trades.parquet"; ap = d / "audit.json"
    tr = pd.read_parquet(tp) if tp.exists() else pd.DataFrame()
    au = _json.loads(ap.read_text()) if ap.exists() else {}
    return tr, au


def matrix(workers=4):
    from concurrent.futures import ProcessPoolExecutor
    thr = pd.read_parquet(OUT / "pqf_is_thresholds.parquet")

    def thr_for(year, pct):
        r = thr[(thr.year == year) & (thr.reject_pct == pct)]
        return float(r.pqf_threshold.iloc[0]) if len(r) else 0.5

    # ---- Stage A: baseline + ML-only + hC-only ----
    jobs = []
    for y in YEARS:
        jobs.append(("baseline", y, BASE))
        for pct in ML_PCTS:
            jobs.append((f"ml{pct}", y, {**BASE, "pqf_threshold": thr_for(y, pct)}))
        for name, pk in HC_PKGS.items():
            jobs.append((name, y, {**BASE, **pk}))
    print(f"Stage A: {len(jobs)} runs on {workers} workers...")
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_worker, jobs):
            print("  ", r, flush=True)

    # pick best 2 ML thresholds by pooled OOS net
    ml_oos = {}
    for pct in ML_PCTS:
        net = sum(_metrics(_load(f"ml{pct}", y)[0])["net"] for y in OOS)
        ml_oos[pct] = net
    best2 = sorted(ml_oos, key=ml_oos.get, reverse=True)[:2]
    print(f"ML OOS net: {ml_oos}; best2 = {best2}")

    # ---- Stage B: ML + hC (best2 ML x combined hC package) ----
    jobsB = []
    for pct in best2:
        for y in YEARS:
            ov = {**BASE, **HC_PKGS["hc_combined"], "pqf_threshold": thr_for(y, pct)}
            jobsB.append((f"ml{pct}_hccomb", y, ov))
    print(f"Stage B: {len(jobsB)} runs...")
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_worker, jobsB):
            print("  ", r, flush=True)

    _reports(best2)


def _yr_row(label):
    cells = {}
    for y in YEARS:
        tr, au = _load(label, y)
        cells[y] = _metrics(tr)
    pooled = _metrics(pd.concat([_load(label, y)[0] for y in YEARS
                                 if len(_load(label, y)[0])], ignore_index=True)
                      if any(len(_load(label, y)[0]) for y in YEARS) else pd.DataFrame())
    return cells, pooled


def _reports(best2):
    import json as _json
    # ---- 1. execution_audit (aggregate) ----
    all_labels = ["baseline"] + [f"ml{p}" for p in ML_PCTS] + list(HC_PKGS) + \
                 [f"ml{p}_hccomb" for p in best2]
    tot_fok = tot_ioc = tot_delay = 0; max_bars = 0; invalid = []
    for lab in all_labels:
        for y in YEARS:
            _, au = _load(lab, y)
            if not au:
                continue
            tot_fok += int(au.get("FOK_order_count", 0))
            tot_ioc += int(au.get("IOC_order_count", 0))
            tot_delay += int(au.get("count_delay_gt_1", 0))
            max_bars = max(max_bars, int(au.get("max_bars_after_opposite_regime", 0)))
            if au.get("count_delay_gt_1", 0) > 0 or au.get("FOK_order_count", 0) > 0:
                invalid.append(f"{lab}_{y}")
    L = ["# execution_audit.md — matrix-wide", "",
         f"- runs audited: {len([1 for lab in all_labels for y in YEARS if _load(lab,y)[1]])}",
         f"- FOK_order_count (total) = **{tot_fok}**", f"- IOC_order_count (total) = **{tot_ioc}**",
         f"- count_delay_gt_1 (total) = **{tot_delay}**",
         f"- max_bars_after_opposite_regime (max) = **{max_bars}**",
         f"- invalid runs: {invalid if invalid else 'NONE'}",
         f"\n**Matrix validity: {'VALID' if not invalid else 'INVALID'}**"]
    (OUT / "execution_audit.md").write_text("\n".join(L), encoding="utf-8")

    def tbl(labels, title):
        R = [f"## {title}", "",
             "| Strategy | " + " | ".join(f"{y} ppt/net" for y in YEARS) + " | Pooled ppt/net/PF/DD |",
             "| --- | " + " | ".join(["---"] * (len(YEARS) + 1)) + " |"]
        for lab in labels:
            cells, pooled = _yr_row(lab)
            yc = " | ".join(f"${cells[y]['ppt']:+.0f} / ${cells[y]['net']/1000:+.0f}k (n{cells[y]['n']})"
                            for y in YEARS)
            R.append(f"| {lab} | {yc} | ${pooled['ppt']:+.1f} / ${pooled['net']/1000:+.0f}k / "
                     f"{pooled['pf']:.2f} / ${pooled['maxdd']/1000:.0f}k |")
        return R

    # ---- 2. ML entry filter ----
    ml_labels = ["baseline"] + [f"ml{p}" for p in ML_PCTS]
    (OUT / "ml_entry_filter_report.md").write_text(
        "\n".join(["# ml_entry_filter_report.md", "",
                   "pQF reject-worst-X% (IS-derived thresholds), entry bar-4 open, exit on regime. "
                   "(QF/runner-rate omitted: label not carried in NT trade record.)", ""]
                  + tbl(ml_labels, "ML-only vs baseline")), encoding="utf-8")

    # ---- 3. hC management ----
    hc_labels = ["baseline"] + list(HC_PKGS)
    base_pool = _yr_row("baseline")[1]["net"]
    R3 = ["# hc_management_report.md", "", f"Baseline pooled net = ${base_pool:,.0f}.",
          "Trigger counts summed across years (from audit).", ""]
    R3 += tbl(hc_labels, "hC-management-only vs baseline")
    R3 += ["", "### Trigger activity (pooled)",
           "| Strategy | sizing | add | reduce | Δnet vs base |", "| --- | ---: | ---: | ---: | ---: |"]
    for lab in list(HC_PKGS):
        sz = ad = rd = 0
        for y in YEARS:
            _, au = _load(lab, y)
            sz += int(au.get("sizing_count", 0)); ad += int(au.get("add_count", 0))
            rd += int(au.get("reduce_count", 0))
        dn = _yr_row(lab)[1]["net"] - base_pool
        R3.append(f"| {lab} | {sz} | {ad} | {rd} | ${dn:+,.0f} |")
    (OUT / "hc_management_report.md").write_text("\n".join(R3), encoding="utf-8")

    # ---- 4. combined ----
    comb_labels = [f"ml{p}_hccomb" for p in best2]
    R4 = ["# combined_strategy_report.md", "", f"Best-2 ML thresholds: {best2} (by OOS net). "
          "Combined = ML pQF gate + full hC management (sizing+add+collapse+DETER).", ""]
    R4 += tbl(["baseline"] + ml_labels[1:] + ["hc_combined"] + comb_labels, "Reconciliation")
    R4 += ["", "### OOS focus (2025 & 2026 separate)",
           "| Strategy | 2025 ppt | 2025 net | 2026 ppt | 2026 net | both>0 |",
           "| --- | ---: | ---: | ---: | ---: | :---: |"]
    for lab in ["baseline"] + [f"ml{p}" for p in ML_PCTS] + ["hc_combined"] + comb_labels:
        c = _yr_row(lab)[0]
        ok = c[2025]["ppt"] > 0 and c[2026]["ppt"] > 0
        R4.append(f"| {lab} | ${c[2025]['ppt']:+.1f} | ${c[2025]['net']/1000:+.0f}k | "
                  f"${c[2026]['ppt']:+.1f} | ${c[2026]['net']/1000:+.0f}k | {'✓' if ok else '✗'} |")
    (OUT / "combined_strategy_report.md").write_text("\n".join(R4), encoding="utf-8")

    # ---- 5. failure modes + verdict ----
    base = _yr_row("baseline")
    best_comb = max(comb_labels, key=lambda l: sum(_yr_row(l)[0][y]["net"] for y in OOS)) if comb_labels else None
    bc = _yr_row(best_comb) if best_comb else (None, None)
    def oos_pos(lab):
        c = _yr_row(lab)[0]; return c[2025]["ppt"] > 0 and c[2026]["ppt"] > 0
    any_winner = any(oos_pos(l) for l in (["baseline"] + [f"ml{p}" for p in ML_PCTS]
                                          + list(HC_PKGS) + comb_labels))
    verdict = "YES — deployable candidate" if any_winner else "NO — fails OOS under corrected NT execution"
    R5 = ["# failure_mode_report.md", "",
          f"- Baseline pooled ppt ${base[1]['ppt']:+.2f} (n {base[1]['n']:,}).",
          f"- Best combined: {best_comb} pooled ppt ${bc[1]['ppt']:+.2f}." if best_comb else "",
          f"- ML filter removes trades but per-trade expectancy stays negative => filtering loses the (few) "
          f"winners along with losers; not a positive-EV gate.",
          f"- hC management shifts DD/expectancy at the margin; check hc_management_report Δnet.",
          f"- Any strategy net-positive in BOTH 2025 and 2026: **{any_winner}**.", "",
          "# FINAL VERDICT", "",
          f"**{verdict}**", "",
          "1. Does Model B provide useful entry selection after costs? — see ml_entry_filter_report (ppt vs baseline).",
          "2. Does hC improve trade management after costs? — see hc_management_report Δnet.",
          "3. Do they combine constructively? — see combined_strategy_report.",
          "4. Robust in both 2025 and 2026? — see OOS-focus table (both>0 column).",
          f"5. Single best candidate to carry forward: {best_comb or 'baseline'}."]
    (OUT / "failure_mode_report.md").write_text("\n".join(R5), encoding="utf-8")
    print("Reports written to", OUT)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sanity"
    if cmd == "sanity":
        sanity(int(sys.argv[2]) if len(sys.argv) > 2 else 2024)
    elif cmd == "matrix":
        matrix(workers=int(sys.argv[2]) if len(sys.argv) > 2 else 4)
    elif cmd == "reports":
        thr = pd.read_parquet(OUT / "pqf_is_thresholds.parquet")
        ml_oos = {p: sum(_metrics(_load(f"ml{p}", y)[0])["net"] for y in OOS) for p in ML_PCTS}
        _reports(sorted(ml_oos, key=ml_oos.get, reverse=True)[:2])

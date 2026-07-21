"""Branch 5 — strict policy gate (real bracket backtest) + decile 9/10 diagnostic.

Each scored bar is a candidate bracket trade: enter at next executable open, the
bracket resolves to PT/SL/regime_flip/timeout (from the label), gross from the
label. Walk-forward score thresholds. Entry modes: first-entry-only (official)
and re-entry. Cost regimes: primary(entry0/exit0.5), stress(0.5/0.5),
severe(1.0/1.0), all +$5 RT; exit slip applies only to non-PT (market) exits.

Strict gate (PRIMARY cost, first-entry-only): OOS net>0 AND 2025>0 AND 2026>0
AND PF>1.05 AND max DD materially better than the always-enter benchmark.

    python studies/regime_dna_knn/policy_dna_gate.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
BRACKETS = ["pt050_sl025", "pt075_sl050", "pt100_sl050", "pt150_sl075", "pt200_sl100"]
TICK = 5.0; COMM = 5.0
COSTS = {"primary": (0.0, 0.5), "stress": (0.5, 0.5), "severe": (1.0, 1.0)}
PCTS = [90, 95, 98, 99]


def net_series(sub, b, regime):
    gross = sub[f"gross_{b}_actual"].values
    reason = sub[f"reason_{b}_actual"].values
    en, ex = COSTS[regime]
    cost = COMM + en * TICK + np.where(reason == 1, 0.0, ex * TICK)  # PT (1) = limit, no exit slip
    return gross - cost


def dd(net, ts):
    s = pd.Series(net, index=ts).sort_index().values
    eq = np.cumsum(s); pk = np.maximum.accumulate(eq)
    return float((pk - eq).max()) if len(eq) else 0.0


def evaluate(sel, b, regime, ts):
    net = net_series(sel, b, regime)
    n = len(net)
    if n == 0:
        return None
    y = sel.year.values
    n25 = net[y == 2025].sum(); n26 = net[y == 2026].sum()
    pf = net[net > 0].sum() / (-net[net < 0].sum()) if (net < 0).any() else (np.inf if (net > 0).any() else 0.0)
    reason = sel[f"reason_{b}_actual"].values; bars = sel[f"bars_{b}_actual"].values
    return dict(trades=n, win=100 * (net > 0).mean(), net=net.sum(), net25=n25, net26=n26,
                pf=pf, avg=net.mean(), maxdd=dd(net, ts),
                med_pt=np.median(bars[reason == 1]) if (reason == 1).any() else np.nan,
                med_sl=np.median(bars[reason == 2]) if (reason == 2).any() else np.nan,
                med_flip=np.median(sel["bars_to_flip_actual"].values))


def main():
    sc = pd.read_parquet(OUT / "dna_knn_scores.parquet")
    oos = sc[sc.is_oos == 1].copy()
    print(f"{len(sc):,} scored, OOS {len(oos):,}")
    rows = []
    for b in BRACKETS:
        scol = f"score_{b}"
        # walk-forward thresholds per OOS year from prior-year scores
        thr = {}
        for Y in (2025, 2026):
            tr = sc[sc.year < Y][scol].values
            thr[Y] = {p: np.percentile(tr, p) for p in PCTS} if len(tr) else {p: 1e9 for p in PCTS}
        for pct in PCTS:
            qual = oos[oos.apply(lambda r: r[scol] >= thr[r.year][pct], axis=1)]
            for mode in ("first-entry", "re-entry"):
                sel = qual.sort_values("bar_ts").groupby("regime_id").first().reset_index() if mode == "first-entry" else qual
                if len(sel) == 0:
                    continue
                ts = sel.bar_ts.values
                for regime in COSTS:
                    m = evaluate(sel, b, regime, ts)
                    if m:
                        m.update(bracket=b, pct=pct, mode=mode, cost=regime)
                        rows.append(m)
        # benchmark (always-enter, first per regime) primary cost, for DD
    res = pd.DataFrame(rows)

    # benchmark DD per bracket (all OOS bars, first per regime, primary)
    bench = {}
    for b in BRACKETS:
        allsel = oos.sort_values("bar_ts").groupby("regime_id").first().reset_index()
        bm = evaluate(allsel, b, "primary", allsel.bar_ts.values)
        bench[b] = bm

    def gate(r, b):
        bm = bench[b]
        return (r["cost"] == "primary" and r["mode"] == "first-entry" and r["net"] > 0
                and r["net25"] > 0 and r["net26"] > 0 and r["pf"] > 1.05
                and bm and r["maxdd"] < bm["maxdd"])

    L = ["# DNA Policy Gate — OOS (2025 & 2026)", "",
         "Real bracket backtest, walk-forward thresholds, next-open fills. Official gate = "
         "PRIMARY cost + first-entry-only: net>0 AND 2025>0 AND 2026>0 AND PF>1.05 AND DD<benchmark.", "",
         "## Primary cost, first-entry-only",
         "| Bracket | Top% | Trades | Win% | Net | Net25 | Net26 | PF | Avg/tr | MaxDD | med b→PT | med b→flip | PASS |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    prim = res[(res.cost == "primary") & (res["mode"] == "first-entry")].sort_values("net", ascending=False)
    n_pass = 0
    for _, r in prim.iterrows():
        p = gate(r, r.bracket); n_pass += int(p)
        L.append(f"| {r.bracket} | {100-r.pct}% | {r.trades:,} | {r.win:.0f}% | ${r.net:,.0f} | "
                 f"${r.net25:,.0f} | ${r.net26:,.0f} | {r.pf:.2f} | ${r.avg:.2f} | ${r.maxdd:,.0f} | "
                 f"{r.med_pt:.0f} | {r.med_flip:.0f} | {'✅' if p else '❌'} |")
    L += ["", "## Benchmark (always-enter, first per regime, primary cost)",
          "| Bracket | Trades | Net | Net25 | Net26 | PF | MaxDD |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for b in BRACKETS:
        bm = bench[b]
        if bm:
            L.append(f"| {b} | {bm['trades']:,} | ${bm['net']:,.0f} | ${bm['net25']:,.0f} | "
                     f"${bm['net26']:,.0f} | {bm['pf']:.2f} | ${bm['maxdd']:,.0f} |")
    # cost robustness of the least-bad first-entry config
    L += ["", "## Cost robustness (best first-entry bracket/threshold by net, all regimes)"]
    if len(prim):
        bestrow = prim.iloc[0]
        L.append(f"Best = {bestrow.bracket} Top {100-bestrow.pct}%:")
        L.append("| Cost regime | Net | Net25 | Net26 | PF | Avg/tr |")
        L.append("| --- | --- | --- | --- | --- | --- |")
        for regime in COSTS:
            rr = res[(res.bracket == bestrow.bracket) & (res.pct == bestrow.pct) &
                     (res["mode"] == "first-entry") & (res.cost == regime)]
            if len(rr):
                r = rr.iloc[0]
                L.append(f"| {regime} | ${r.net:,.0f} | ${r.net25:,.0f} | ${r.net26:,.0f} | {r.pf:.2f} | ${r.avg:.2f} |")
    L += ["", "## Verdict",
          (f"> [!TIP]\n> **{n_pass} configuration(s) PASS** the strict gate. Investigate / NT-validate."
           if n_pass else
           "> [!WARNING]\n> **0 configurations pass** the strict gate (PRIMARY cost, first-entry-only, "
           "net+both-years-PF>1.05-DD<benchmark). DNA + live state does not produce monetizable "
           "forward payoff on this OHLCV regime-memory framework. Per the SPEC, close this branch and "
           "preserve the framework for future orderflow/microstructure features.")]
    (OUT / "dna_policy_gate.md").write_text("\n".join(L), encoding="utf-8")
    print(f"Wrote dna_policy_gate.md; passes={n_pass}")

    # ---- decile 9/10 diagnostic ----
    if len(oos):
        oos = oos.copy()
        oos["dec"] = pd.qcut(oos["score_expected_net"], 10, labels=False, duplicates="drop") + 1
        D = ["# Decile 9 vs 10 Diagnostic (DNA-aware score_expected_net, OOS)", ""]
        for dec in (9, 10):
            s = oos[oos.dec == dec]
            if not len(s):
                continue
            net = net_series(s, "pt100_sl050", "primary")
            arch = s.cluster_id.value_counts(normalize=True).head(3)
            D += [f"## Decile {dec}  (n={len(s):,})",
                  f"- net $/tr (pt100_sl050, primary): ${net.mean():+.2f}",
                  f"- mean bar_index: {s.bar_index.mean():.1f} | med bars→flip: {s['bars_to_flip_actual'].median():.0f}",
                  f"- pre_30 lr_slope: {s['dna_pre_30_lr_slope_atr'].mean():+.3f} | pre_15 compression: "
                  f"{s['dna_pre_15_compression_score'].mean():.3f} | pre_5 vol_z: {s['dna_pre_5_volume_zscore'].mean():+.2f}",
                  "- top archetypes: " + ", ".join(f"c{int(c)} {v*100:.0f}%" for c, v in arch.items()), ""]
        (OUT / "decile_9_10_diagnostic.md").write_text("\n".join(D), encoding="utf-8")
        print("Wrote decile_9_10_diagnostic.md")


if __name__ == "__main__":
    main()

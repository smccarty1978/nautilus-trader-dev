"""Coverage Bias Audit — is KNN hC coverage MCAR / MAR / systematic (MNAR)?

Population = the BASELINE bar-4 all-flips runs (full live NT flip universe entered at
bar 4; uniform size 2, no ML filter, no hC management -> no selection distortion).
Split each trade by whether its regime_start_ts is present in the per-bar hC mapping
(= the universe the hC studies could actually measure).

Compare mapped vs unmapped on:
  - trade quality (net $/tr, win rate, median $)
  - duration (hold_s)  - volatility (atr_at_signal)  - direction balance
Then test whether the OUTCOME gap persists after conditioning on volatility & duration
terciles (the MAR vs MNAR discriminator).

Reports: 2022-2026 pooled, plus each year, plus 2025 and 2026 called out.
Writes results/combined_arch/coverage_bias_audit.md
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "collectors/collector_v2/results/combined_arch"
YEARS = [2022, 2023, 2024, 2025, 2026]


def ztest_prop(p1, n1, p2, n2):
    if n1 == 0 or n2 == 0:
        return float("nan")
    p = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return (p1 - p2) / se if se > 0 else float("nan")


def welch_t(a, b):
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    return (a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))


def main():
    mapped_rsts = set(pd.read_parquet(OUT / "hc_perbar_mapping.parquet")
                      .regime_start_ts.astype("int64").unique())
    frames = []
    for y in YEARS:
        p = OUT / f"baseline_{y}" / "trades.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        d["year"] = y
        d["mapped"] = d.regime_start_ts.astype("int64").isin(mapped_rsts)
        frames.append(d)
    allt = pd.concat(frames, ignore_index=True)

    def stats(df):
        if len(df) == 0:
            return None
        p = df.net_pnl.values
        return dict(n=len(df), cov=df.mapped.mean(),
                    ppt=p.mean(), win=(p > 0).mean() * 100, med=np.median(p),
                    hold=df.hold_s.median(), atr=df.atr_at_signal.median(),
                    longpct=(df.direction == 1).mean() * 100)

    def block(df, title):
        m = df[df.mapped]; u = df[~df.mapped]
        sm, su = stats(m), stats(u)
        L = [f"### {title}", ""]
        if sm is None or su is None or len(u) == 0:
            L += [f"(n={len(df)}, mapped={len(m)}, unmapped={len(u)} — insufficient unmapped)", ""]
            return L, None
        L += ["| Cohort | n | $/tr | win% | median $ | median hold_s | median ATR | %long |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for nm, s in [("MAPPED (hC studies saw)", sm), ("UNMAPPED (missed)", su)]:
            L.append(f"| {nm} | {s['n']:,} | ${s['ppt']:+.2f} | {s['win']:.1f}% | "
                     f"${s['med']:+.0f} | {s['hold']:.0f} | {s['atr']:.2f} | {s['longpct']:.0f}% |")
        win_gap = sm['win'] - su['win']; ppt_gap = sm['ppt'] - su['ppt']
        z = ztest_prop(sm['win']/100, sm['n'], su['win']/100, su['n'])
        tt = welch_t(m.net_pnl.values, u.net_pnl.values)
        L += ["",
              f"- coverage = **{df.mapped.mean()*100:.1f}%** mapped",
              f"- **win-rate gap (mapped − unmapped) = {win_gap:+.1f} pp** (z={z:.1f})",
              f"- **$/tr gap = ${ppt_gap:+.2f}** (Welch t={tt:.1f})",
              f"- duration gap (median hold_s) = {sm['hold']-su['hold']:+.0f}s | "
              f"volatility gap (median ATR) = {sm['atr']-su['atr']:+.2f}", ""]
        return L, dict(win_gap=win_gap, ppt_gap=ppt_gap, z=z)

    # conditional check (MAR vs MNAR): does the $/tr & win gap persist within
    # volatility & duration terciles computed on the pooled population?
    def conditional(df):
        df = df.copy()
        df["atr_t"] = pd.qcut(df.atr_at_signal, 3, labels=["loVol", "midVol", "hiVol"], duplicates="drop")
        df["hold_t"] = pd.qcut(df.hold_s, 3, labels=["short", "mid", "long"], duplicates="drop")
        rows = ["| Stratum | mapped n | unmapped n | mapped win% | unmapped win% | win gap | $/tr gap |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        persist = []
        for dim, col in [("ATR", "atr_t"), ("Hold", "hold_t")]:
            for lvl in df[col].cat.categories:
                s = df[df[col] == lvl]
                m = s[s.mapped]; u = s[~s.mapped]
                if len(m) < 50 or len(u) < 50:
                    continue
                wg = (m.net_pnl > 0).mean()*100 - (u.net_pnl > 0).mean()*100
                pg = m.net_pnl.mean() - u.net_pnl.mean()
                persist.append(wg)
                rows.append(f"| {dim}={lvl} | {len(m):,} | {len(u):,} | "
                            f"{(m.net_pnl>0).mean()*100:.1f}% | {(u.net_pnl>0).mean()*100:.1f}% | "
                            f"{wg:+.1f}pp | ${pg:+.0f} |")
        return rows, persist

    R = ["# Coverage Bias Audit — KNN hC mapped vs unmapped (NT bar-4 all-flips)", "",
         "Population: `baseline_<year>` runs (full live NT flip universe entered at bar 4, "
         "uniform size, no ML/hC selection). 'mapped' = regime_start_ts present in the per-bar "
         "hC mapping = the subset the hC studies could measure.", ""]

    pooled_block, pooled_g = block(allt, "POOLED 2022–2026")
    R += pooled_block
    for y in YEARS:
        b, _ = block(allt[allt.year == y], f"Year {y}")
        R += b

    R += ["---", "## Conditional check (MAR vs MNAR): does the gap survive volatility/duration strata?",
          "If the win/$ gap collapses to ~0 within strata → MAR (explained by observables). "
          "If it persists → MNAR (coverage tied to outcome itself).", ""]
    crows, persist = conditional(allt)
    R += crows
    R += [""]

    # verdict
    wg = abs(pooled_g["win_gap"]); pg = abs(pooled_g["ppt_gap"])
    strat_med = np.median([abs(x) for x in persist]) if persist else 0
    if wg < 2 and pg < 5:
        verdict = "MCAR-like — coverage ≈ random; mapped and unmapped look the same. hC findings trustworthy on the full population."
    elif strat_med < 2:
        verdict = ("MAR — the outcome gap is largely explained by observable volatility/duration "
                   "(gap collapses within strata). hC findings are conditionally valid but the raw "
                   "base rates are skewed by composition; re-weight before quoting population rates.")
    else:
        verdict = ("MNAR / SYSTEMATIC — unmapped flips differ in OUTCOME and the gap PERSISTS within "
                   "volatility/duration strata. The hC studies measured the easier-to-model subset. "
                   "Put an asterisk on hC base-rate conclusions until the mapping is rebuilt on the "
                   "full NT flip universe. (The negative backtest is unaffected — it used the full "
                   "baseline population.)")
    R += ["---", "## VERDICT", "",
          f"Pooled win-rate gap {pooled_g['win_gap']:+.1f}pp, $/tr gap ${pooled_g['ppt_gap']:+.2f}; "
          f"median |win gap| within strata = {strat_med:.1f}pp.", "",
          f"**{verdict}**"]
    (OUT / "coverage_bias_audit.md").write_text("\n".join(R), encoding="utf-8")
    print("\n".join(R))
    print("\nWrote coverage_bias_audit.md")


if __name__ == "__main__":
    main()

"""Bar1-Confirmed Stair-Step Validation Study.

Population substitution: SAME audited replay engine, SAME 13 exit versions, SAME
costs — but ONLY the Bar1-confirmed (Population B) entries. Isolates: can
stair-step protection improve monetization of the best-confirmed regime-flip
population? Answered on its own terms (NOT compared to raw flips).

Reads the already-replayed outcomes (B rows). No re-run.
    python studies/stairstep_exits/bar1_study.py
"""
from __future__ import annotations
import os, sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root)); os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np, pandas as pd

RES = Path("studies/stairstep_exits/results")
YEARS = (2021, 2022, 2023, 2024)
MULT = 20.0; TICK = 0.25; TICK_VAL = TICK * MULT; COMMISSION = 5.0
SLIP_PRIMARY = {"stop": 0.5, "regime": 0.5, "gate30": 0.5, "gate60": 0.5,
                "pt": 0.0, "end_of_data": 0.5}
SLIP_STRESS = {k: (0.0 if k == "pt" else 1.0) for k in SLIP_PRIMARY}
VERSION_ORDER = ["V0_regime", "BR10", "BR15", "V1_ladder", "V2_gate_ladder",
                 "V3_struct_1m", "V3_struct_5s", "V4D1_ma_1m", "V4D1_ma_5s",
                 "V4D2_ma_1m", "V4D2_ma_5s", "V5_hybrid_1m", "V5_hybrid_5s"]
OUT = []
def P(s=""): OUT.append(str(s)); print(s)


def load_B():
    parts = [pd.read_parquet(RES / f"exit_outcomes_{y}.parquet") for y in YEARS]
    df = pd.concat(parts, ignore_index=True)
    df = df[(df.population == "B") & (df.warmed_up)].copy()
    df["gross_pts"] = df.direction * (df.exit_px_ideal - df.entry_px)
    df["gross_atr"] = df.gross_pts / df.atr_at_entry
    df["gross_dol"] = df.gross_pts * MULT
    df["mfe_atr"] = df.max_mfe_pts / df.atr_at_entry
    df["giveback_atr"] = (df.max_mfe_pts - df.gross_pts) / df.atr_at_entry
    df["net"] = df.gross_dol - df.exit_reason.map(SLIP_PRIMARY).fillna(0.5) * TICK_VAL - COMMISSION
    df["net_stress"] = df.gross_dol - df.exit_reason.map(SLIP_STRESS).fillna(1.0) * TICK_VAL - COMMISSION
    return df


def pf(x):
    w = x[x > 0].sum(); ls = -x[x < 0].sum()
    return (w / ls) if ls > 0 else np.inf


def max_dd(s):
    eq = np.cumsum(s); peak = np.maximum.accumulate(eq)
    return float((eq - peak).min()) if len(eq) else 0.0


def metrics(g):
    g = g.sort_values("entry_ts")
    atr = g.gross_atr
    mp = g[g.max_mfe_pts > 0]
    return dict(
        n=len(g), gross_tr=g.gross_dol.mean(), net_tr=g.net.mean(),
        stress_tr=g.net_stress.mean(), pf_gross=pf(g.gross_dol), pf_net=pf(g.net),
        max_dd=max_dd(g.net.to_numpy()),
        win=(g.net > 0).mean(), lose=(g.net < 0).mean(),
        giveback=g.giveback_atr.median(),
        mfe_cap=(mp.gross_pts / mp.max_mfe_pts).median(),
        capt2=(atr >= 2).mean(), capt3=(atr >= 3).mean(),
        loser_bot10=atr[atr <= atr.quantile(.10)].mean(),
        runner_top10=atr[atr >= atr.quantile(.90)].mean(),
    )


def full_table(df, title):
    P(f"\n### {title}\n")
    cols = ["n", "gross_tr", "net_tr", "stress_tr", "pf_gross", "pf_net",
            "max_dd", "win", "lose", "giveback", "mfe_cap", "capt2", "capt3"]
    P("| version | " + " | ".join(cols) + " |")
    P("| " + " | ".join("---" for _ in range(len(cols) + 1)) + " |")
    rows = {}
    for v in VERSION_ORDER:
        g = df[df.version == v]
        if not len(g): continue
        m = metrics(g); rows[v] = m
        def f(k):
            x = m[k]
            if k == "n": return f"{int(x):,}"
            if k in ("gross_tr", "net_tr", "stress_tr"): return f"{x:+.1f}"
            if k == "max_dd": return f"{x:+,.0f}"
            if k in ("pf_gross", "pf_net", "mfe_cap"): return f"{x:.2f}"
            if k in ("win", "lose", "capt2", "capt3"): return f"{x:.0%}"
            if k == "giveback": return f"{x:+.2f}"
            return f"{x:.2f}"
        P(f"| {v} | " + " | ".join(f(k) for k in cols) + " |")
    return rows


def decision_table(df, title):
    P(f"\n### Decision table — {title}\n")
    P("| Version | loser bot 10% | giveback | runner top 10% | +3 ATR capture | net $/trade |")
    P("| --- | --- | --- | --- | --- | --- |")
    for v in VERSION_ORDER:
        g = df[df.version == v]
        if not len(g): continue
        m = metrics(g)
        P(f"| {v} | {m['loser_bot10']:+.2f} | {m['giveback']:+.2f} | "
          f"{m['runner_top10']:+.2f} | {m['capt3']:.0%} | {m['net_tr']:+.1f} |")


def main():
    df = load_B()
    P("# Bar1-Confirmed Stair-Step Validation Study\n")
    P(f"Population: Bar1-confirmed regime flips ONLY (Population B), NQ `NQ.v.0` "
      f"2021-2024, warmed. n entries = {df.drop_duplicates('entry_id').shape[0]:,}. "
      f"Same audited replay engine, same 13 versions, same costs (PRIMARY: entry 0 "
      f"/ exit 0.5 tick / PT 0 / $5 RT; STRESS: exit 1.0 tick). 0 phantom fills.\n")
    P("> Interpretation rule honored: this study asks only whether exits improve "
      "monetization of the BEST-confirmed population, on its own terms.\n")

    P("## 1. Full metrics")
    full_table(df, "All Bar1 (both sides) — pooled 2021-2024")
    full_table(df[df.direction == 1], "Bar1 LONG-only — pooled")
    full_table(df[df.direction == -1], "Bar1 SHORT-only — pooled")

    P("\n## 2. Critical comparison (decision tables)")
    decision_table(df, "All Bar1")
    decision_table(df[df.direction == 1], "Bar1 LONG-only")
    decision_table(df[df.direction == -1], "Bar1 SHORT-only")

    P("\n## 3. Per-year net $/trade (All Bar1, primary cost)\n")
    piv = df.groupby(["version", "year"])["net"].mean().unstack()
    piv = piv.reindex([v for v in VERSION_ORDER if v in piv.index])
    P("| version | " + " | ".join(str(y) for y in piv.columns) + " | yrs+ |")
    P("| " + " | ".join("---" for _ in range(len(piv.columns) + 2)) + " |")
    for v, r in piv.iterrows():
        P(f"| {v} | " + " | ".join(f"{x:+.1f}" for x in r) + f" | {int((r>0).sum())}/4 |")

    # ---- explicit validation questions ----
    P("\n## 4. Validation questions\n")
    base = metrics(df[df.version == "V0_regime"])
    allm = {v: metrics(df[df.version == v]) for v in VERSION_ORDER}
    longm = {v: metrics(df[(df.version == v) & (df.direction == 1)]) for v in VERSION_ORDER}
    shortm = {v: metrics(df[(df.version == v) & (df.direction == -1)]) for v in VERSION_ORDER}

    # Q1
    best = max(VERSION_ORDER, key=lambda v: allm[v]["net_tr"])
    n_improve = sum(1 for v in VERSION_ORDER if v != "V0_regime" and allm[v]["net_tr"] > base["net_tr"])
    n_pos = sum(1 for v in VERSION_ORDER if allm[v]["net_tr"] > 0)
    P(f"**Q1 — Does any stair-step improve expectancy vs Bar1 regime exit (V0)?**")
    P(f"V0 net = {base['net_tr']:+.1f} $/tr. Best version = {best} "
      f"({allm[best]['net_tr']:+.1f} $/tr). {n_improve}/12 beat V0; "
      f"{n_pos}/13 are net-positive. "
      f"{'YES (some beat V0)' if n_improve>0 else 'NO'} — but "
      f"{'a positive expectancy exists' if n_pos>0 else 'NONE reach positive expectancy'}.\n")

    # Q2
    q2 = [v for v in VERSION_ORDER if v != "V0_regime"
          and allm[v]["loser_bot10"] > base["loser_bot10"] + 0.05
          and allm[v]["runner_top10"] >= base["runner_top10"] - 0.10]
    P(f"**Q2 — Any architecture that cuts the loser tail while PRESERVING the runner tail?**")
    P(f"V0: loser_bot10={base['loser_bot10']:+.2f}, runner_top10={base['runner_top10']:+.2f}. "
      f"Versions cutting loser tail (>+0.05) AND preserving runner (within 0.10): "
      f"{q2 if q2 else 'NONE'}. "
      f"{'YES' if q2 else 'NO — every loser-tail cut comes with a runner-tail cut.'}\n")

    # Q3
    v4s = ["V4D1_ma_1m", "V4D1_ma_5s", "V4D2_ma_1m", "V4D2_ma_5s"]
    P(f"**Q3 — Is stall/MA-protection lift reproducible on Bar1?**")
    for v in v4s:
        P(f"- {v}: net {allm[v]['net_tr']:+.1f} vs V0 {base['net_tr']:+.1f} "
          f"(lift {allm[v]['net_tr']-base['net_tr']:+.1f}/tr)")
    lift = any(allm[v]["net_tr"] > base["net_tr"] for v in v4s)
    P(f"  => {'Some MA lift' if lift else 'NO MA lift'} on Bar1.\n")

    # Q4
    P(f"**Q4 — Is the prove-it gate additive on Bar1 (V1 ladder -> V2 gate+ladder)?**")
    for label, mm in [("all", allm), ("long", longm), ("short", shortm)]:
        d = mm["V2_gate_ladder"]["net_tr"] - mm["V1_ladder"]["net_tr"]
        P(f"- {label}: V1={mm['V1_ladder']['net_tr']:+.1f} -> V2={mm['V2_gate_ladder']['net_tr']:+.1f} "
          f"(gate {d:+.1f}/tr)")
    P("")

    # Q5
    P(f"**Q5 — If Bar1 also fails, is the remaining problem ENTRY quality, not exit quality?**")
    gross_all = {v: allm[v]["gross_tr"] for v in VERSION_ORDER}
    best_gross_v = max(gross_all, key=gross_all.get)
    P(f"Best-confirmed population + best exit still gross = "
      f"{gross_all[best_gross_v]:+.1f} $/tr ({best_gross_v}); all {len(VERSION_ORDER)} "
      f"versions gross-{'negative' if max(gross_all.values())<0 else 'mixed'}. "
      f"If gross is negative under the strongest entry filter AND every exit "
      f"architecture, the deficit is in the ENTRY edge, not the stop. (See verdict.)\n")

    out = RES / "bar1_study_results.md"
    out.write_text("\n".join(OUT), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()

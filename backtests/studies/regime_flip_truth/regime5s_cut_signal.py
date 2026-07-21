"""5s/30s regime in the first 90s — is there a quicker / additional CUT signal?

Descriptive feasibility only (no optimization, no ML, no tuning). Uses the
collector-recorded, 1s-causal 5s/30s regime path:
  - event-level: t_first_5s_opposed_s, t_first_30s_opposed_s, n_5s_flips_first90s
  - checkpoint-level: align_5s, align_30s (+1 aligned / -1 opposed / 0 neutral)

Cohorts: winners = +2ATR reachers; non-reachers; Elite; Fakeout (never +1 ATR
MFE); cut-set = net-negative (cur_pnl_atr<0) at +60s.

    python studies/regime_flip_truth/regime5s_cut_signal.py
"""
from __future__ import annotations
import os, sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root)); os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np, pandas as pd

RES = Path("studies/regime_flip_truth/results")
YEARS = (2021, 2022, 2023, 2024)
OUT = []
def P(s=""): OUT.append(str(s)); print(s)


def load():
    ev, ck = [], []
    for y in YEARS:
        e = pd.read_parquet(RES / f"flip_truth_dataset_{y}.parquet"); e["year"] = y
        e["uid"] = e.year * 10_000_000 + e.event_id; ev.append(e)
        c = pd.read_parquet(RES / f"flip_checkpoint_dataset_{y}.parquet"); c["year"] = y
        c["uid"] = c.year * 10_000_000 + c.event_id; ck.append(c)
    EV = pd.concat(ev, ignore_index=True); CK = pd.concat(ck, ignore_index=True)
    EV = EV[EV.warmed_up].copy(); CK = CK[CK.uid.isin(set(EV.uid))].copy()
    EV["fakeout"] = ~EV["reached_1_0_atr"]
    # net PnL & 5s align at +60s / +30s (only checkpoints actually reached)
    for cp, tag in [("+30s", "30"), ("+60s", "60"), ("+90s", "90")]:
        sl = CK[(CK.checkpoint == cp) & (CK.reached == True)][
            ["uid", "cur_pnl_atr", "align_5s", "align_30s"]]
        sl = sl.rename(columns={"cur_pnl_atr": f"pnl_{tag}",
                                "align_5s": f"a5_{tag}", "align_30s": f"a30_{tag}"})
        EV = EV.merge(sl, on="uid", how="left")
    return EV, CK


def pct(x):
    return f"{x:.1%}" if pd.notna(x) else "—"


def study_q1(EV):
    P("\n## Q1 — Do eventual winners flip 5s-OPPOSED in the first 90s?\n")
    P("Share of each cohort whose 5s regime turns opposed to the trade by +T, "
      "median time of first 5s-opposed, and median 5s churn (flips) in 90s.\n")
    for pop in ("A", "B"):
        sub = EV[EV.population == pop]
        cohorts = {
            "winners (+2ATR)": sub[sub.reached_2_0_atr],
            "non-reachers": sub[~sub.reached_2_0_atr],
            "cut-set (net<0 @60s)": sub[sub.pnl_60 < 0],
            "Elite": sub[sub.elite_trend],
            "Fakeout": sub[sub.fakeout],
        }
        P(f"### Population {pop}")
        P("| cohort | n | 5s-opp ≤30s | ≤60s | ≤90s | med t_first_5s | med 5s-flips/90s |")
        P("| --- | --- | --- | --- | --- | --- | --- |")
        for name, c in cohorts.items():
            t = c["t_first_5s_opposed_s"]
            P(f"| {name} | {len(c):,} | {pct((t<=30).mean())} | {pct((t<=60).mean())} | "
              f"{pct((t<=90).mean())} | {t.median():.0f}s | {c['n_5s_flips_first90s'].median():.0f} |")
        P("")
        # same for 30s regime (steadier)
        P(f"30s regime (Population {pop}), opposed by +60s / +90s:")
        for name, c in cohorts.items():
            t = c["t_first_30s_opposed_s"]
            P(f"- {name}: ≤60s {pct((t<=60).mean())}, ≤90s {pct((t<=90).mean())}, "
              f"med {t.median():.0f}s")
        P("")


def cut_rule(EV, pop, tcol, tmax_list):
    """5s-opposed-by-T as a CUT rule. Report trigger rate, P(reach2|trig vs not),
    winners killed, E[term|trig vs not]."""
    sub = EV[EV.population == pop]
    W = sub.reached_2_0_atr
    rows = []
    for T in tmax_list:
        trig = sub[tcol] <= T
        n_w = W.sum()
        rows.append({
            "cut@T": f"≤{T}s",
            "trig%": trig.mean(),
            "P(reach2|trig)": sub.loc[trig, "reached_2_0_atr"].mean(),
            "P(reach2|keep)": sub.loc[~trig, "reached_2_0_atr"].mean(),
            "winners_killed%": (trig & W).sum() / n_w if n_w else np.nan,
            "E_term|trig": sub.loc[trig, "terminal_pnl_atr"].mean(),
            "E_term|keep": sub.loc[~trig, "terminal_pnl_atr"].mean(),
        })
    return pd.DataFrame(rows)


def study_q2(EV):
    P("\n## Q2 — 5s-opposed as a stand-alone CUT signal\n")
    P("Rule: cut the trade the first time the 5s regime is opposed, if that "
      "happens by +T. A good cut has LOW P(reach2|trig), HIGH P(reach2|keep), "
      "and kills few winners.\n")
    for pop in ("A", "B"):
        P(f"### Population {pop}")
        t = cut_rule(EV, pop, "t_first_5s_opposed_s", [15, 30, 45, 60, 90])
        P("| cut@T | trig% | P(reach2\\|trig) | P(reach2\\|keep) | winners killed% | E[term\\|trig] | E[term\\|keep] |")
        P("| --- | --- | --- | --- | --- | --- | --- |")
        for _, r in t.iterrows():
            P(f"| {r['cut@T']} | {pct(r['trig%'])} | {pct(r['P(reach2|trig)'])} | "
              f"{pct(r['P(reach2|keep)'])} | {pct(r['winners_killed%'])} | "
              f"{r['E_term|trig']:+.2f} | {r['E_term|keep']:+.2f} |")
        P("")


def study_q3(EV):
    P("\n## Q3 — Does 5s ADD to the +60s net-PnL gate? (orthogonality)\n")
    P("At +60s, cross net-PnL sign with 5s alignment. If 5s-opposed sharpens the "
      "cut WITHIN a PnL bucket, it adds information; if reach2 is flat across 5s "
      "within each PnL bucket, it is redundant with PnL.\n")
    for pop in ("A", "B"):
        sub = EV[(EV.population == pop) & EV.pnl_60.notna() & EV.a5_60.notna()].copy()
        sub["pnl_sign"] = np.where(sub.pnl_60 >= 0, "net≥0", "net<0")
        sub["a5"] = sub.a5_60.map({1: "5s aligned", 0: "5s neutral", -1: "5s opposed"})
        P(f"### Population {pop} (n={len(sub):,})")
        P("| @+60s state | n | P(reach2) | E[term] |")
        P("| --- | --- | --- | --- |")
        for ps in ("net≥0", "net<0"):
            for a in ("5s aligned", "5s neutral", "5s opposed"):
                g = sub[(sub.pnl_sign == ps) & (sub.a5 == a)]
                if len(g) < 100: continue
                P(f"| {ps} & {a} | {len(g):,} | {pct(g.reached_2_0_atr.mean())} | "
                  f"{g.terminal_pnl_atr.mean():+.2f} |")
        P("")


def study_q4(EV):
    P("\n## Q4 — Quicker? 5s at +30s vs the +60s gate\n")
    P("Can a +30s read (30s earlier) act as the cut? Cross +30s net-PnL sign with "
      "+30s 5s alignment.\n")
    for pop in ("A", "B"):
        sub = EV[(EV.population == pop) & EV.pnl_30.notna() & EV.a5_30.notna()].copy()
        sub["pnl_sign"] = np.where(sub.pnl_30 >= 0, "net≥0", "net<0")
        sub["a5"] = sub.a5_30.map({1: "aligned", 0: "neutral", -1: "opposed"})
        P(f"### Population {pop} @+30s (n={len(sub):,})")
        P("| @+30s state | n | P(reach2) | E[term] | winners-killed share |")
        P("| --- | --- | --- | --- | --- |")
        W = sub.reached_2_0_atr.sum()
        for ps in ("net≥0", "net<0"):
            for a in ("aligned", "neutral", "opposed"):
                g = sub[(sub.pnl_sign == ps) & (sub.a5 == a)]
                if len(g) < 100: continue
                wk = (g.reached_2_0_atr.sum() / W) if W else np.nan
                P(f"| {ps} & 5s {a} | {len(g):,} | {pct(g.reached_2_0_atr.mean())} | "
                  f"{g.terminal_pnl_atr.mean():+.2f} | {pct(wk)} |")
        P("")


def study_q5(EV):
    P("\n## Q5 — 5s CHURN (chop) in first 90s\n")
    P("Number of 5s regime flips in the first 90s vs outcomes. High churn = chop.\n")
    for pop in ("A", "B"):
        sub = EV[EV.population == pop]
        P(f"### Population {pop}")
        P("| 5s flips /90s | n | P(reach2) | fakeout% | elite% | E[term] |")
        P("| --- | --- | --- | --- | --- | --- |")
        for k in range(0, 6):
            g = sub[sub.n_5s_flips_first90s == k] if k < 5 else sub[sub.n_5s_flips_first90s >= 5]
            lab = str(k) if k < 5 else "5+"
            if len(g) < 100: continue
            P(f"| {lab} | {len(g):,} | {pct(g.reached_2_0_atr.mean())} | "
              f"{pct(g.fakeout.mean())} | {pct(g.elite_trend.mean())} | "
              f"{g.terminal_pnl_atr.mean():+.2f} |")
        P("")


def main():
    EV, CK = load()
    P("# 5s/30s Regime in the First 90s — Quicker Cut Signal?\n")
    P(f"NQ `NQ.v.0` 2021-2024, warmed. A n={(EV.population=='A').sum():,}, "
      f"B n={(EV.population=='B').sum():,}. 1s-causal 5s/30s regime path.\n")
    study_q1(EV); study_q2(EV); study_q3(EV); study_q4(EV); study_q5(EV)
    out = RES / "regime5s_cut_signal.md"
    out.write_text("\n".join(OUT), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()

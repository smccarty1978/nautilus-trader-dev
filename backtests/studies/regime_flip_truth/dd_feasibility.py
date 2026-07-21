"""Drawdown Timing & Adaptive Exit Feasibility Study.

Descriptive feasibility only. NO strategy optimization, NO ML, NO threshold
tuning. Answers: when does DD occur vs MFE, is DD worse after big extension
bars, and which early path states causally justify holding for +2 ATR vs cutting.

Studies 1-4 per brief. Population A (raw flips) and B (bar1-confirmed) reported
SEPARATELY throughout.

Definitions (stated up-front, not tuned):
  - +2ATR reacher: reached_2_0_atr == True
  - non-reacher:   reached_2_0_atr == False
  - Elite:         elite_trend (persistent >=15 bars AND MFE>=2 AND MAE<=0.75)
  - Fakeout:       NOT reached_1_0_atr  (the flip never achieved even +1 ATR of
                   favorable excursion before the regime ended)
  - "hit -X ATR before +2": adverse threshold time < +2 MFE time (with +2 never
                   reached treated as +inf). 1s-precise (collector-recorded).

    python studies/regime_flip_truth/dd_feasibility.py
"""
from __future__ import annotations
import os, sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root)); os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

RES = Path("studies/regime_flip_truth/results")
YEARS = (2021, 2022, 2023, 2024)
INF = np.inf
OUT = []
def P(s=""): OUT.append(str(s)); print(s)


def load():
    ev, ck = [], []
    for y in YEARS:
        e = pd.read_parquet(RES / f"flip_truth_dataset_{y}.parquet"); e["year"] = y
        e["uid"] = e["year"] * 10_000_000 + e["event_id"]; ev.append(e)
        c = pd.read_parquet(RES / f"flip_checkpoint_dataset_{y}.parquet"); c["year"] = y
        c["uid"] = c["year"] * 10_000_000 + c["event_id"]; ck.append(c)
    EV = pd.concat(ev, ignore_index=True)
    CK = pd.concat(ck, ignore_index=True)
    EV = EV[EV.warmed_up].copy()
    CK = CK[CK.uid.isin(set(EV.uid))].copy()
    # derived
    EV["fakeout"] = ~EV["reached_1_0_atr"]
    t2 = EV["t_reach_2_0_atr_s"].fillna(INF)
    for thr, col in [("0_75", "t_mae_0_75_atr_s"), ("1_0", "t_mae_1_0_atr_s"),
                     ("0_5", "t_mae_0_5_atr_s")]:
        ta = EV[col].fillna(INF)
        EV[f"adv_{thr}_before_2"] = (EV[col].notna()) & (ta < t2)
    return EV, CK


def med(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return s.median() if len(s) else np.nan


def p90(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return s.quantile(0.9) if len(s) else np.nan


def fmt_s(x):
    return f"{x:.0f}s" if pd.notna(x) else "—"


# ----------------------------------------------------------------------
def study1(EV):
    P("\n# STUDY 1 — Drawdown Timing\n")
    P("Median time (s from entry) to each excursion threshold, by cohort. "
      "NaN = threshold never reached (excluded from median); reach-rate shown "
      "in parentheses.\n")
    tmetrics = [
        ("0.5ATR MAE", "t_mae_0_5_atr_s"),
        ("1.0ATR MAE", "t_mae_1_0_atr_s"),
        ("max MAE",    "t_max_mae_s"),
        ("0.5ATR MFE", "t_reach_0_5_atr_s"),
        ("1.0ATR MFE", "t_reach_1_0_atr_s"),
        ("2.0ATR MFE", "t_reach_2_0_atr_s"),
    ]
    for pop in ("A", "B"):
        sub = EV[EV.population == pop]
        cohorts = {
            "all": sub,
            "+2ATR reach": sub[sub.reached_2_0_atr],
            "non-reach": sub[~sub.reached_2_0_atr],
            "Elite": sub[sub.elite_trend],
            "Fakeout": sub[sub.fakeout],
        }
        P(f"### Population {pop}")
        hdr = ["cohort", "n"] + [m[0] for m in tmetrics]
        P("| " + " | ".join(hdr) + " |")
        P("| " + " | ".join("---" for _ in hdr) + " |")
        for cname, c in cohorts.items():
            cells = [cname, f"{len(c):,}"]
            for _, col in tmetrics:
                m = med(c[col]); rate = c[col].notna().mean()
                cells.append(f"{fmt_s(m)} ({rate:.0%})" if pd.notna(m) else "—")
            P("| " + " | ".join(cells) + " |")
        P("")
        # MAE-before-MFE ordering
        P(f"**Adverse-before-favorable ordering (Population {pop}, all events):**")
        for thr, mfe_col, lab in [("t_mae_0_5_atr_s", "t_reach_0_5_atr_s", "0.5 MAE before 0.5 MFE"),
                                  ("t_mae_1_0_atr_s", "t_reach_1_0_atr_s", "1.0 MAE before 1.0 MFE")]:
            ta = sub[thr].fillna(INF); tm = sub[mfe_col].fillna(INF)
            frac = ((sub[thr].notna()) & (ta < tm)).mean()
            P(f"- {lab}: {frac:.1%}")
        P("")


def study2(EV):
    P("\n# STUDY 2 — Drawdown Location (where does the heat sit for +2ATR reachers)\n")
    P("For events that reach +2 ATR: WHEN does the worst pre-+2 adverse excursion "
      "(`t_max_mae_before_2atr_s`) occur relative to the +0.5 / +1.0 ATR MFE "
      "milestones, and how big is that DD (`mae_before_2_0_atr`)?\n")
    for pop in ("A", "B"):
        r = EV[(EV.population == pop) & (EV.reached_2_0_atr)].copy()
        tdd = r["t_max_mae_before_2atr_s"]
        t05 = r["t_reach_0_5_atr_s"].fillna(INF)
        t10 = r["t_reach_1_0_atr_s"].fillna(INF)
        before_05 = tdd < t05
        before_10 = tdd < t10
        after_10 = ~before_10
        P(f"### Population {pop}  (n reachers = {len(r):,})")
        P("| DD location | share | median DD (ATR) | p90 DD (ATR) |")
        P("| --- | --- | --- | --- |")
        for lab, mask in [("before +0.5 ATR MFE", before_05),
                          ("before +1.0 ATR MFE", before_10),
                          ("after +1.0 ATR MFE", after_10)]:
            s = r[mask]
            P(f"| {lab} | {mask.mean():.1%} | "
              f"{med(s['mae_before_2_0_atr']):.2f} | {p90(s['mae_before_2_0_atr']):.2f} |")
        P(f"\nOverall: median worst-pre-2ATR DD = {med(r['mae_before_2_0_atr']):.2f} ATR, "
          f"occurring at median {fmt_s(med(tdd))} after entry "
          f"(vs +2 ATR reached at median {fmt_s(med(r['t_reach_2_0_atr_s']))}).\n")


def decile_table(df, feat, n=10):
    sub = df[[feat, "reached_2_0_atr", "mae_before_2_0_atr",
              "t_reach_2_0_atr_s", "fakeout", "elite_trend"]].dropna(subset=[feat]).copy()
    if len(sub) < 500 or sub[feat].nunique() < n:
        return None
    try:
        sub["d"] = pd.qcut(sub[feat], n, labels=False, duplicates="drop")
    except Exception:
        return None
    rows = []
    for d, g in sub.groupby("d"):
        rows.append({
            "decile": int(d) + 1,
            "feat_lo": g[feat].min(), "feat_hi": g[feat].max(),
            "n": len(g),
            "reach2": g["reached_2_0_atr"].mean(),
            "med_DD": med(g.loc[g.reached_2_0_atr, "mae_before_2_0_atr"]),
            "p90_DD": p90(g.loc[g.reached_2_0_atr, "mae_before_2_0_atr"]),
            "med_t2": med(g.loc[g.reached_2_0_atr, "t_reach_2_0_atr_s"]),
            "fakeout": g["fakeout"].mean(),
            "elite": g["elite_trend"].mean(),
        })
    return pd.DataFrame(rows)


def study3(EV):
    P("\n# STUDY 3 — Extension-Bar Conditioning\n")
    P("Decile each entry/confirm-bar feature; report forward path outcomes. "
      "Shows whether bigger/stronger entry bars precede better follow-through "
      "or just bigger drawdown.\n")
    feats = [
        ("confirm_bar_range_atr", "confirm_bar_range_ATR"),
        ("confirm_bar_body_atr", "confirm_bar_body_ATR"),
        ("close_loc_in_confirm_bar", "close_location_in_confirm_bar"),
        ("feat_ema13_dist_atr", "extension_from_EMA13_ATR"),
        ("feat_dist_from_vwap_atr", "extension_from_VWAP_ATR"),
        ("gap_flip_to_entry_atr", "gap_flip_to_entry_ATR"),
    ]
    for pop in ("A", "B"):
        sub = EV[EV.population == pop]
        P(f"## Population {pop}")
        for col, name in feats:
            if col == "gap_flip_to_entry_atr" and pop == "A":
                continue  # gap is 0 by construction for raw flips
            dt = decile_table(sub, col)
            if dt is None:
                P(f"### {name}: (insufficient spread)\n"); continue
            # show deciles 1,5,10 for compactness + spread
            P(f"### {name}  (Population {pop})")
            P("| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |")
            P("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
            for _, r in dt.iterrows():
                P(f"| {int(r['decile'])} | {r['feat_lo']:.2f}..{r['feat_hi']:.2f} | "
                  f"{int(r['n']):,} | {r['reach2']:.1%} | {r['med_DD']:.2f} | "
                  f"{r['p90_DD']:.2f} | {fmt_s(r['med_t2'])} | {r['fakeout']:.1%} | "
                  f"{r['elite']:.1%} |")
            d1, d10 = dt.iloc[0], dt.iloc[-1]
            P(f"_D10−D1: reach2 {d10['reach2']-d1['reach2']:+.1%}, "
              f"p90_DD {d10['p90_DD']-d1['p90_DD']:+.2f} ATR, "
              f"elite {d10['elite']-d1['elite']:+.1%}, "
              f"fakeout {d10['fakeout']-d1['fakeout']:+.1%}_\n")


def study4(EV, CK):
    P("\n# STUDY 4 — Checkpoint Feasibility\n")
    P("At each checkpoint, bucket OPEN trades by their state THEN (quartiles), "
      "and report forward whole-trade outcomes. `P(reach+2)`, the adverse races, "
      "and `E[term PnL]` are eventual outcomes conditioned on the checkpoint "
      "state — the feasibility signal for a hold/cut decision at that moment.\n")
    # join eventual outcomes onto checkpoints
    keep = ["uid", "reached_2_0_atr", "terminal_pnl_atr", "adv_0_75_before_2",
            "adv_1_0_before_2", "population"]
    lab = EV[keep].set_index("uid")
    ck = CK.join(lab, on="uid", rsuffix="_ev")
    ck = ck[ck["reached_2_0_atr"].notna()].copy()
    ck["hh_minus_ll"] = ck["hh_count"] - ck["ll_count"]
    # only checkpoints that were genuinely reached while open (not frozen-terminal)
    ck = ck[ck["reached"] == True].copy()

    metrics = [("cur_mfe_atr", "cur MFE"), ("cur_mae_atr", "cur MAE"),
               ("cur_pnl_atr", "net PnL"), ("path_efficiency", "path eff"),
               ("stall_s", "stall_s"), ("hh_minus_ll", "HH−LL")]
    cps_full = ["+30s", "+60s", "+90s", "+120s", "Bar2", "Bar3", "Bar5"]

    def bucket_report(sub, metric):
        s = sub[[metric, "reached_2_0_atr", "terminal_pnl_atr",
                 "adv_0_75_before_2", "adv_1_0_before_2"]].dropna(subset=[metric])
        if len(s) < 400 or s[metric].nunique() < 4:
            return None
        try:
            s = s.copy(); s["q"] = pd.qcut(s[metric], 4, labels=False, duplicates="drop")
        except Exception:
            return None
        rows = []
        for q, g in s.groupby("q"):
            rows.append({
                "q": int(q) + 1, "range": f"{g[metric].min():.2f}..{g[metric].max():.2f}",
                "n": len(g), "P_reach2": g["reached_2_0_atr"].mean(),
                "P_-0.75_b4_2": g["adv_0_75_before_2"].mean(),
                "P_-1.0_b4_2": g["adv_1_0_before_2"].mean(),
                "E_term_pnl": g["terminal_pnl_atr"].mean(),
            })
        return pd.DataFrame(rows)

    # 4a/4b: evolution of separation (bottom vs top quartile) over checkpoints
    for metric, mlab in [("path_efficiency", "path efficiency"),
                         ("cur_pnl_atr", "net PnL (ATR)")]:
        P(f"## 4a. Forward outcomes by checkpoint — bucketed on {mlab} "
          f"(bottom Q1 vs top Q4)")
        for pop in ("A", "B"):
            P(f"### Population {pop}")
            P("| checkpoint | Q1 P(reach+2) | Q4 P(reach+2) | Q1 E[term] | Q4 E[term] | "
              "Q4 P(-0.75 b/f +2) | n/qtile |")
            P("| --- | --- | --- | --- | --- | --- | --- |")
            for cp in cps_full:
                sub = ck[(ck.checkpoint == cp) & (ck.population == pop)]
                t = bucket_report(sub, metric)
                if t is None:
                    continue
                q1, q4 = t.iloc[0], t.iloc[-1]
                P(f"| {cp} | {q1['P_reach2']:.1%} | {q4['P_reach2']:.1%} | "
                  f"{q1['E_term_pnl']:+.2f} | {q4['E_term_pnl']:+.2f} | "
                  f"{q4['P_-0.75_b4_2']:.1%} | {int(q4['n']):,} |")
            P("")

    # 4c: full quartile breakdown at two representative checkpoints, all 6 metrics
    for cp in ("+60s", "Bar3"):
        P(f"## 4b. Full quartile breakdown at {cp} (Population A)")
        sub = ck[(ck.checkpoint == cp) & (ck.population == "A")]
        for metric, mlab in metrics:
            t = bucket_report(sub, metric)
            if t is None:
                continue
            P(f"### {mlab} @ {cp}")
            P("| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |")
            P("| --- | --- | --- | --- | --- | --- | --- |")
            for _, r in t.iterrows():
                P(f"| Q{int(r['q'])} | {r['range']} | {int(r['n']):,} | {r['P_reach2']:.1%} | "
                  f"{r['P_-0.75_b4_2']:.1%} | {r['P_-1.0_b4_2']:.1%} | {r['E_term_pnl']:+.2f} |")
            P("")


def main():
    EV, CK = load()
    P("# Drawdown Timing & Adaptive Exit Feasibility Study\n")
    P(f"NQ `NQ.v.0` 2021-2024, 24h, warmed events. "
      f"A (raw flip) n={ (EV.population=='A').sum():,}, "
      f"B (bar1-confirmed) n={ (EV.population=='B').sum():,}. "
      f"Catalog `NQ_v0_2020_2026`. 1s-precise excursion timing (collector-recorded).\n")
    P("**Definitions:** +2ATR reacher = reached_2_0_atr; Elite = persistent≥15bars "
      "& MFE≥2 & MAE≤0.75; Fakeout = never reached +1.0 ATR MFE; "
      "'-X before +2' = adverse threshold crossed before the +2 MFE touch (1s).\n")
    study1(EV)
    study2(EV)
    study3(EV)
    study4(EV, CK)
    out = RES / "dd_feasibility_report.md"
    out.write_text("\n".join(OUT), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()

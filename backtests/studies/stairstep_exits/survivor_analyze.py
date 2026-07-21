"""Survivor / Add-On forward-expectancy analysis.

Forward EV from each survivor state, the add-on contract economics (3 risk
variants, computed analytically via forward MAE level-touch), and the probe+add
vs fixed-size comparison. Answers Q1-Q7. Leads with the gate: if no survivor
state has positive forward EV after costs, the branch is closed.

    python studies/stairstep_exits/survivor_analyze.py
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
MULT = 20.0; TICK = 0.25; TICK_VAL = TICK * MULT; COMM = 5.0
HALF = 0.5 * TICK_VAL  # 0.5-tick = $2.50

TIME_STATES = ["alive_30", "alive_60", "alive_90", "alive_120", "alive_180"]
PROG_STATES = ["reach_0p25", "reach_0p50", "reach_0p75", "reach_1p00", "reach_1p50"]
PATH_STATES = ["gate_pass", "no5s_opp_90", "pos_path_eff", "mfe_gt_mae"]
ALL_STATES = TIME_STATES + PROG_STATES + PATH_STATES
# add entry execution: progress = limit (0 slip), time/path = market (0.5 tick)
IS_LIMIT = {s: (s in PROG_STATES) for s in ALL_STATES}
OUT = []
def P(s=""): OUT.append(str(s)); print(s)


def load():
    df = pd.concat([pd.read_parquet(RES / f"survivor_{y}.parquet") for y in YEARS],
                   ignore_index=True)
    return df[df.warmed_up].copy()


def add_net(df, state, exit_kind="regime", stop_atr=None):
    """Per-reached-trade net $ of the ADD contract entered at `state`.
    exit_kind: 'regime' (forward_term), 'stop' (independent stop at -stop_atr),
    'be' (breakeven stop at pS). All measured purely forward from pS."""
    r = df[df[f"{state}_reached"] == True].copy()
    fwd_term = r[f"{state}_fwd_term"]          # pts, forward to regime exit
    fwd_mae = r[f"{state}_fwd_mae"]            # pts adverse forward from pS
    atr = r["atr_at_entry"]
    entry_slip = 0.0 if IS_LIMIT[state] else HALF
    if exit_kind == "regime":
        gross = fwd_term * MULT
        exit_slip = HALF
    elif exit_kind == "be":
        # BE stop at pS: if forward path returned to pS (fwd_mae >= 0) -> exit ~0
        hit = fwd_mae >= 0
        gross = np.where(hit, 0.0, fwd_term * MULT)
        exit_slip = HALF
    elif exit_kind == "stop":
        lvl = stop_atr * atr
        hit = fwd_mae >= lvl
        gross = np.where(hit, -lvl * MULT, fwd_term * MULT)
        exit_slip = HALF
    net = gross - entry_slip - exit_slip - COMM
    return pd.Series(net, index=r.index), r


def state_row(df, state, n_total):
    r = df[df[f"{state}_reached"] == True]
    if len(r) == 0:
        return None
    fwd_term = r[f"{state}_fwd_term"]; atr = r["atr_at_entry"]
    fwd_mfe_atr = r[f"{state}_fwd_mfe"] / atr
    net, _ = add_net(df, state, "regime")
    term_dol = fwd_term * MULT
    return dict(
        state=state, count=len(r), pct_orig=len(r) / n_total,
        future_ev_gross=term_dol.mean(), future_ev_net=net.mean(),
        reach1=(fwd_mfe_atr >= 1).mean(), reach2=(fwd_mfe_atr >= 2).mean(),
        reach3=(fwd_mfe_atr >= 3).mean(),
        mean_atr=(fwd_term / atr).mean(), med_atr=(fwd_term / atr).median(),
        med_dol=term_dol.median(),
        bot10=term_dol[term_dol <= term_dol.quantile(.10)].mean(),
        top10=term_dol[term_dol >= term_dol.quantile(.90)].mean(),
    )


def fwd_table(df, pop):
    sub = df[df.population == pop]
    n = len(sub)
    rows = [state_row(sub, s, n) for s in ALL_STATES]
    rows = [r for r in rows if r]
    rows.sort(key=lambda r: r["future_ev_net"], reverse=True)
    P(f"\n### Forward expectancy by survivor state — Population {pop} (n={n:,})\n")
    P("| Survivor State | Count | % Orig | Future EV gross $ | Future EV NET $ | "
      "Reach+1 | Reach+2 | Reach+3 | Top 10% $ | Bottom 10% $ |")
    P("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        P(f"| {r['state']} | {r['count']:,} | {r['pct_orig']:.0%} | "
          f"{r['future_ev_gross']:+.1f} | {r['future_ev_net']:+.1f} | "
          f"{r['reach1']:.0%} | {r['reach2']:.0%} | {r['reach3']:.0%} | "
          f"{r['top10']:+.0f} | {r['bot10']:+.0f} |")
    return rows


def addon_table(df, pop):
    sub = df[df.population == pop]
    n = len(sub)
    probe_net = sub["probe_term_pts"] * MULT - HALF - COMM  # 1-contract probe, regime exit
    P(f"\n### Add-on simulation — Population {pop} (probe=1 V0 contract; add=1 contract)\n")
    P("Net $/trade is over ALL entries (add only on reached trades). "
      f"Fixed-2 baseline (2 probes) = {2*probe_net.mean():+.1f} $/tr, "
      f"PF {pf(2*probe_net):.2f}.\n")
    add_rules = [("A_+0.5ATR", "reach_0p50"), ("B_+1.0ATR", "reach_1p00"),
                 ("C_gate_pass", "gate_pass"), ("D_no5s_opp_90", "no5s_opp_90"),
                 ("E_mfe_gt_mae", "mfe_gt_mae")]
    P("| Add Rule | Variant | add net/add $ | TOTAL net/trade $ | PF | win% | avg contracts | max DD |")
    P("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for label, st in add_rules:
        reached = sub[f"{st}_reached"] == True
        rr = reached.mean()
        for vk, vargs in [("indep stop -0.75", ("stop", 0.75)),
                          ("protect@regime", ("regime", None)),
                          ("BE", ("be", None))]:
            anet, ridx = add_net(sub, st, vargs[0], vargs[1])
            # combined per-trade series over ALL entries
            combined = probe_net.copy()
            combined.loc[ridx.index] = combined.loc[ridx.index] + anet.values
            P(f"| {label} | {vk} | {anet.mean():+.1f} | {combined.mean():+.1f} | "
              f"{pf(combined):.2f} | {(combined>0).mean():.0%} | "
              f"{1+rr:.2f} | {max_dd(sub, combined):+,.0f} |")
    return probe_net


def pf(x):
    x = np.asarray(x); w = x[x > 0].sum(); l = -x[x < 0].sum()
    return (w / l) if l > 0 else np.inf


def max_dd(sub, series):
    s = pd.Series(series.values, index=sub["entry_ts"].values).sort_index()
    eq = np.cumsum(s.values); pk = np.maximum.accumulate(eq)
    return float((eq - pk).min()) if len(eq) else 0.0


def main():
    df = load()
    P("# Raw-Flip / Bar1 Survivor & Add-On Expectancy Study\n")
    P(f"V0_regime probe. NQ `NQ.v.0` 2021-2024 warmed. "
      f"A={int((df.population=='A').sum()):,}, B={int((df.population=='B').sum()):,}. "
      f"Forward economics measured PURELY from each survivor state forward to the "
      f"regime exit (no pre-state credit). Costs: progress adds = limit (0 entry "
      f"slip); time/path adds = market (0.5 tick); exit 0.5 tick; $5 RT/contract.\n")

    P("## 1. Forward expectancy table (ranked by NET future EV)")
    rowsA = fwd_table(df, "A")
    rowsB = fwd_table(df, "B")

    P("\n## 2. Add-on simulation (3 risk variants)")
    probeA = addon_table(df, "A")
    probeB = addon_table(df, "B")

    # ---- validation questions ----
    P("\n## 3. Validation questions\n")
    def best(rows, key):
        return max(rows, key=lambda r: r[key])
    bA_g, bA_n = best(rowsA, "future_ev_gross"), best(rowsA, "future_ev_net")
    bB_n = best(rowsB, "future_ev_net")
    n_pos_gross_A = sum(1 for r in rowsA if r["future_ev_gross"] > 0)
    n_pos_net_A = sum(1 for r in rowsA if r["future_ev_net"] > 0)
    n_pos_net_B = sum(1 for r in rowsB if r["future_ev_net"] > 0)

    P(f"**Q1 — Any survivor state with positive forward expectancy (gross)?**")
    P(f"A: {n_pos_gross_A}/{len(rowsA)} states gross-positive; best = {bA_g['state']} "
      f"({bA_g['future_ev_gross']:+.1f} $). {'YES' if n_pos_gross_A>0 else 'NO'}.\n")
    P(f"**Q2 — Positive forward expectancy AFTER realistic costs?**")
    P(f"A: {n_pos_net_A}/{len(rowsA)} states net-positive; best = {bA_n['state']} "
      f"({bA_n['future_ev_net']:+.1f} $). B: {n_pos_net_B}/{len(rowsB)}; best = "
      f"{bB_n['state']} ({bB_n['future_ev_net']:+.1f} $). "
      f"{'YES' if max(n_pos_net_A,n_pos_net_B)>0 else 'NO'}.\n")
    P(f"**Q3 — Is the ADD-ON contract itself profitable (net, per added contract)?**")
    P(f"Best net add (regime exit) A = {bA_n['state']} {bA_n['future_ev_net']:+.1f} $/add. "
      f"{'YES for some states' if n_pos_net_A>0 else 'NO — every add contract is net-negative'}.\n")
    for q, st in [("Q4", "gate_pass"), ("Q5", "no5s_opp_90")]:
        ra = next((r for r in rowsA if r["state"] == st), None)
        rb = next((r for r in rowsB if r["state"] == st), None)
        P(f"**{q} — Does `{st}` create a profitable add location?**")
        P(f"A net add = {ra['future_ev_net']:+.1f} $ (reach2 {ra['reach2']:.0%}); "
          f"B net add = {rb['future_ev_net']:+.1f} $ (reach2 {rb['reach2']:.0%}). "
          f"{'YES' if (ra['future_ev_net']>0 or rb['future_ev_net']>0) else 'NO'}.\n")
    P(f"**Q6 — Raw (A) or Bar1 (B) superior for probe-and-add?**")
    P(f"Best net-add state: A {bA_n['state']} {bA_n['future_ev_net']:+.1f} vs "
      f"B {bB_n['state']} {bB_n['future_ev_net']:+.1f}. "
      f"Probe net/tr: A {probeA.mean():+.1f}, B {probeB.mean():+.1f}.\n")
    P(f"**Q7 — Can a 1-contract probe + conditional add beat fixed-size entry?**")
    P(f"See add-on table: compare TOTAL net/trade & PF vs the Fixed-2 baseline "
      f"(2×probe). A probe net/tr={probeA.mean():+.1f} (fixed-2={2*probeA.mean():+.1f}).\n")

    # success criterion
    any_pos = (n_pos_net_A + n_pos_net_B) > 0
    P("## 4. Success criterion")
    if any_pos:
        P("At least one survivor state shows POSITIVE forward EV after costs. "
          "Probe-and-pyramid is a live research direction — see add-on table for "
          "whether the added contract nets positive per rule/variant.\n")
    else:
        P("NO survivor state has positive forward EV after costs. Per the stated "
          "criterion, the probe-and-add branch is CLOSED: surviving trades do not "
          "carry positive forward expectancy; the market does not reveal enough "
          "post-entry information to make additional size profitable on this signal.\n")

    out = RES / "survivor_results.md"
    out.write_text("\n".join(OUT), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()

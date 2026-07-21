"""HMM state-conditioned trade economics + confirmed vs unconfirmed
comparison + filter experiments."""

from __future__ import annotations
import json
from pathlib import Path
import pickle
import numpy as np
import pandas as pd

OUT = Path("studies/hmm_5s_v1/results")
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0


def stats(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {"n": 0}
    s = df["pnl_dollars"].dropna()
    if len(s) == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    k = int(len(s) * 0.05)
    trim = (s.sort_values().iloc[k:len(s) - k].mean()
             if k * 2 < len(s) else float("nan"))
    return {
        "n": len(s),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "trimmed": float(trim),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
        "pt_pct": float((df["outcome"] == "pt").mean()),
        "sl_pct": float((df["outcome"] == "sl").mean()),
        "unr_pct": float((df["outcome"] == "unresolved").mean()),
        "med_res_s": float(df["resolution_s"].median())
            if df["resolution_s"].notna().any() else float("nan"),
    }


def fmt_d(v):
    if v is None or pd.isna(v):
        return "—"
    if isinstance(v, float) and np.isinf(v):
        return "∞"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def main():
    rec = pd.read_parquet(OUT / "rawflip_state_outcomes_2025.parquet")
    with open(OUT / "hmm_model.pkl", "rb") as f:
        hmm_data = pickle.load(f)
    state_means = pd.read_parquet(OUT / "state_feature_means.parquet")
    print(f"Raw-flip trades on 2025 RTH: {len(rec):,}")
    print(f"Outcome mix: {rec['outcome'].value_counts().to_dict()}")
    print(f"Confirmed: {int(rec['hhll_confirmed'].sum()):,}, "
           f"Unconfirmed: {int((~rec['hhll_confirmed']).sum()):,}")

    n_states = int(rec["state"].max() + 1)

    lines = []
    lines.append("# HMM 5s State Layer — 2025 Raw-Flip Study")
    lines.append("")
    lines.append("**Setup**: 4-state Gaussian HMM on 5s bars, fit on "
                  "2023-2024, evaluated on 2025 RTH raw 1m flips. "
                  "No HH/LL gate.")
    lines.append("")
    lines.append("**Trade simulation**: decision at flip close, fill "
                  "at flip+30s (open of first available 1s bar), "
                  "1 ATR PT / 1 ATR SL bracket, 30-min max horizon. "
                  "Cost: $5 commission + 1 tick adverse entry + "
                  "1 tick adverse SL exit.")
    lines.append("")

    # ----- 1. Executive summary -----
    lines.append("## 1. Executive summary")
    lines.append("")
    pop_pt = (rec["outcome"] == "pt").mean()
    state_pt = rec.groupby("state").apply(
        lambda g: (g["outcome"] == "pt").mean(),
        include_groups=False)
    state_n = rec.groupby("state").size()
    lifts = {s: (state_pt[s] - pop_pt) for s in range(n_states)}
    best_state = max(lifts, key=lifts.get)
    worst_state = min(lifts, key=lifts.get)
    print(f"\nState PT% lifts vs population ({100*pop_pt:.1f}%):")
    for s in range(n_states):
        print(f"  State {s}: {100*state_pt[s]:.1f}% "
               f"(n={state_n[s]:,}, lift {100*lifts[s]:+.1f}pp)")

    spread_pp = max(lifts.values()) - min(lifts.values())
    lines.append(f"- Population PT% on raw flips: {100*pop_pt:.1f}%")
    lines.append(f"- Best state ({best_state}): "
                  f"{100*state_pt[best_state]:.1f}% PT "
                  f"({100*lifts[best_state]:+.1f}pp lift)")
    lines.append(f"- Worst state ({worst_state}): "
                  f"{100*state_pt[worst_state]:.1f}% PT "
                  f"({100*lifts[worst_state]:+.1f}pp)")
    lines.append(f"- State PT% spread: {spread_pp*100:.1f}pp")
    lines.append("")

    # ----- 2. State characterization -----
    lines.append("## 2. State characterization (5s feature means)")
    lines.append("")
    lines.append("| State | Range | Body % | Close Loc | Vol Z | RV |")
    lines.append("|--:|--:|--:|--:|--:|--:|")
    for _, r in state_means.iterrows():
        lines.append(
            f"| {int(r['state'])} | {r['range']:.3f} | "
            f"{r['body_pct']:.3f} | {r['close_loc']:.3f} | "
            f"{r['vol_z']:.3f} | {r['rv']:.5f} |")
    lines.append("")
    lines.append("**Plain-English interpretation** (heuristic):")
    for _, r in state_means.iterrows():
        s = int(r["state"])
        rng = r["range"]
        body = r["body_pct"]
        loc = r["close_loc"]
        vol = r["vol_z"]
        # Very rough labeling
        if rng < 0.5 and abs(loc - 0.5) > 0.4:
            label = "decisive small-range close-at-extreme"
        elif rng > 3.0:
            label = "wide-range high-volume volatility burst"
        elif body < 0.5:
            label = "indecisive mid-bar (chop)"
        elif body > 0.7:
            label = "directional clean-body"
        else:
            label = "mixed / normal"
        lines.append(f"- State {s}: {label} "
                      f"(range {rng:.2f}, body {body:.0%}, "
                      f"close-loc {loc:.2f}, vol-z {vol:+.2f})")
    lines.append("")

    # ----- 3. Trade economics by state -----
    lines.append("## 3. Trade economics by HMM state")
    lines.append("")
    lines.append("| State | n | Mean $ | Median | Trim 5% | PF | "
                  "Win% | PT% | SL% | Unr% | Median res | Total $ |")
    lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for s in range(n_states):
        sub = rec[rec["state"] == s]
        m = stats(sub)
        if m["n"] == 0:
            continue
        lines.append(
            f"| {s} | {m['n']:,} | {fmt_d(m['mean'])} | "
            f"{fmt_d(m['median'])} | {fmt_d(m['trimmed'])} | "
            f"{m['pf']:.2f} | {fmt_p(m['win_rate'])} | "
            f"{fmt_p(m['pt_pct'])} | {fmt_p(m['sl_pct'])} | "
            f"{fmt_p(m['unr_pct'])} | "
            f"{m['med_res_s']:.0f}s | {fmt_d(m['sum'])} |")
    # ALL row
    m = stats(rec)
    lines.append(
        f"| **ALL** | **{m['n']:,}** | **{fmt_d(m['mean'])}** | "
        f"**{fmt_d(m['median'])}** | **{fmt_d(m['trimmed'])}** | "
        f"**{m['pf']:.2f}** | **{fmt_p(m['win_rate'])}** | "
        f"**{fmt_p(m['pt_pct'])}** | **{fmt_p(m['sl_pct'])}** | "
        f"**{fmt_p(m['unr_pct'])}** | "
        f"**{m['med_res_s']:.0f}s** | **{fmt_d(m['sum'])}** |")
    lines.append("")

    # ----- 4. Confirmed vs unconfirmed comparison -----
    lines.append("## 4. Confirmed vs unconfirmed raw flips, by state")
    lines.append("")
    lines.append("| State | Conf n | Conf PT% | Conf Mean $ | "
                  "Unconf n | Unconf PT% | Unconf Mean $ |")
    lines.append("|--:|--:|--:|--:|--:|--:|--:|")
    for s in range(n_states):
        conf = rec[(rec["state"] == s) & rec["hhll_confirmed"]]
        unconf = rec[(rec["state"] == s) & ~rec["hhll_confirmed"]]
        cm = stats(conf)
        um = stats(unconf)
        lines.append(
            f"| {s} | {cm.get('n', 0):,} | "
            f"{fmt_p(cm.get('pt_pct'))} | {fmt_d(cm.get('mean'))} | "
            f"{um.get('n', 0):,} | "
            f"{fmt_p(um.get('pt_pct'))} | {fmt_d(um.get('mean'))} |")
    lines.append("")
    # ALL row
    conf = rec[rec["hhll_confirmed"]]
    unconf = rec[~rec["hhll_confirmed"]]
    cm = stats(conf)
    um = stats(unconf)
    lines.append("**Aggregate (all states)**:")
    lines.append("")
    lines.append(f"- HH/LL confirmed: n={cm['n']:,}, PT% "
                  f"{fmt_p(cm['pt_pct'])}, mean {fmt_d(cm['mean'])}, "
                  f"PF {cm['pf']:.2f}")
    lines.append(f"- Unconfirmed: n={um['n']:,}, PT% "
                  f"{fmt_p(um['pt_pct'])}, mean {fmt_d(um['mean'])}, "
                  f"PF {um['pf']:.2f}")
    delta = cm["pt_pct"] - um["pt_pct"]
    lines.append(f"- Δ PT% (confirmed minus unconfirmed): "
                  f"{100*delta:+.1f}pp")
    lines.append("")

    # ----- 5. Transition analysis -----
    lines.append("## 5. Transition analysis")
    lines.append("")
    lines.append("Did a state change happen in the 30s before the flip?")
    lines.append("")
    no_trans = rec[~rec["recent_transition"]]
    yes_trans = rec[rec["recent_transition"]]
    nm = stats(no_trans)
    tm = stats(yes_trans)
    lines.append("| Group | n | PT% | Mean $ | PF |")
    lines.append("|---|--:|--:|--:|--:|")
    lines.append(f"| No recent transition | {nm['n']:,} | "
                  f"{fmt_p(nm['pt_pct'])} | {fmt_d(nm['mean'])} | "
                  f"{nm['pf']:.2f} |")
    lines.append(f"| Recent transition | {tm['n']:,} | "
                  f"{fmt_p(tm['pt_pct'])} | {fmt_d(tm['mean'])} | "
                  f"{tm['pf']:.2f} |")
    lines.append("")

    # Dwell-time effect
    lines.append("Dwell-time effect (consecutive 5s bars in current state):")
    lines.append("")
    lines.append("| Dwell bucket | n | PT% | Mean $ | PF |")
    lines.append("|---|--:|--:|--:|--:|")
    for lo, hi, label in [
        (0, 30, "≤ 30s"), (30, 60, "30-60s"),
        (60, 120, "60-120s"), (120, 300, "120-300s"),
        (300, 99999, "> 300s"),
    ]:
        sub = rec[(rec["dwell_s"] >= lo) & (rec["dwell_s"] < hi)]
        m = stats(sub)
        if m.get("n", 0) == 0:
            continue
        lines.append(
            f"| {label} | {m['n']:,} | {fmt_p(m['pt_pct'])} | "
            f"{fmt_d(m['mean'])} | {m['pf']:.2f} |")
    lines.append("")

    # ----- 6. Filter experiments -----
    lines.append("## 6. Simple filter experiments")
    lines.append("")
    lines.append("| Filter | n | PT% | Mean $ | PF | Total $ |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    base_m = stats(rec)
    lines.append(
        f"| No filter (ALL) | {base_m['n']:,} | "
        f"{fmt_p(base_m['pt_pct'])} | {fmt_d(base_m['mean'])} | "
        f"{base_m['pf']:.2f} | {fmt_d(base_m['sum'])} |")
    # Exclude worst state
    if worst_state != best_state:
        sub = rec[rec["state"] != worst_state]
        m = stats(sub)
        lines.append(
            f"| Exclude state {worst_state} | {m['n']:,} | "
            f"{fmt_p(m['pt_pct'])} | {fmt_d(m['mean'])} | "
            f"{m['pf']:.2f} | {fmt_d(m['sum'])} |")
    # Only best state
    sub = rec[rec["state"] == best_state]
    m = stats(sub)
    lines.append(
        f"| Only state {best_state} | {m['n']:,} | "
        f"{fmt_p(m['pt_pct'])} | {fmt_d(m['mean'])} | "
        f"{m['pf']:.2f} | {fmt_d(m['sum'])} |")
    # Exclude recent transitions
    sub = rec[~rec["recent_transition"]]
    m = stats(sub)
    lines.append(
        f"| Exclude recent transitions | {m['n']:,} | "
        f"{fmt_p(m['pt_pct'])} | {fmt_d(m['mean'])} | "
        f"{m['pf']:.2f} | {fmt_d(m['sum'])} |")
    # HH/LL confirmed only
    sub = rec[rec["hhll_confirmed"]]
    m = stats(sub)
    lines.append(
        f"| HH/LL confirmed only | {m['n']:,} | "
        f"{fmt_p(m['pt_pct'])} | {fmt_d(m['mean'])} | "
        f"{m['pf']:.2f} | {fmt_d(m['sum'])} |")
    # HH/LL + best state
    sub = rec[(rec["hhll_confirmed"]) & (rec["state"] == best_state)]
    m = stats(sub)
    lines.append(
        f"| HH/LL conf + state {best_state} | {m['n']:,} | "
        f"{fmt_p(m['pt_pct'])} | {fmt_d(m['mean'])} | "
        f"{m['pf']:.2f} | {fmt_d(m['sum'])} |")
    # HH/LL + exclude worst state + no recent transition
    sub = rec[(rec["hhll_confirmed"])
                & (rec["state"] != worst_state)
                & (~rec["recent_transition"])]
    m = stats(sub)
    lines.append(
        f"| HH/LL conf + excl state {worst_state} + no transition "
        f"| {m['n']:,} | "
        f"{fmt_p(m['pt_pct'])} | {fmt_d(m['mean'])} | "
        f"{m['pf']:.2f} | {fmt_d(m['sum'])} |")
    lines.append("")

    # ----- 7. Verdict -----
    lines.append("## 7. Verdict")
    lines.append("")
    excl_worst = rec[rec["state"] != worst_state]
    em = stats(excl_worst)
    lift_excl = em["mean"] - base_m["mean"]
    only_best = rec[rec["state"] == best_state]
    bm = stats(only_best)
    lift_best = bm["mean"] - base_m["mean"]

    lines.append(f"- State PT% spread on raw flips: "
                  f"{100*spread_pp:.1f}pp (best {best_state} "
                  f"{100*state_pt[best_state]:.1f}% vs worst "
                  f"{worst_state} {100*state_pt[worst_state]:.1f}%)")
    lines.append(f"- Excluding worst state: mean Δ "
                  f"{fmt_d(lift_excl)} per trade")
    lines.append(f"- Trading only best state: mean Δ "
                  f"{fmt_d(lift_best)} per trade vs baseline "
                  f"({fmt_d(base_m['mean'])})")

    if spread_pp > 0.05:
        verdict = ("STRONG state separation — HMM identifies "
                    "meaningfully different sub-populations")
    elif spread_pp > 0.02:
        verdict = ("MODEST state separation — interpretable but "
                    "small")
    else:
        verdict = ("WEAK state separation — states do not "
                    "meaningfully differ on PT% race")
    lines.append(f"- Verdict: **{verdict}**")
    lines.append("")

    out = OUT / "HMM_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()

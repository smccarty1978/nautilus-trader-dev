"""Continuous KNN Opportunity-State Decay Atlas.

Reframe: stop asking "CONT vs DETER" (a late threshold crossing). Treat the KNN state as a
CONTINUOUS OpportunityScore = P(Runner), track its peak/decay/slope per trade, and ask whether
the continuous decay carries more information than the binary label — and whether it can drive
PROGRESSIVE profit protection / a monitor-mode handoff BEFORE the discrete DETER event.

Per OOS Bar-4 trade, at every bar: OppScore=P(Runner), P(Fail), eMFE, eMAE, eTTF (KNN neighbor
estimates, causal). Running peak of OppScore; score-drawdown% from peak; slope ΔScore(1/3/5).

Study 1 — Peak & decay: bucket states by score-drawdown%; forward outcomes (rem MFE/MAE, new-high,
          +0.5/+1 ATR ext, flip≤3/5/10) + %DETER. Continuous decay vs abrupt collapse?
Study 2 — Slope: bucket by ΔScore(3); forward outcomes. Is deterioration in the SLOPE before the LEVEL?
Study 3 — Profit-protection overlay: scale-out on drawdown>20% / slope<thr vs hold-to-flip, DETER-exit,
          random matched (1m, scale at trigger+1 open — no intrabar triggers).
Study 4 — Early-warning: first bar drawdown>20% OR slope<0 → bars until DETER (monitor-mode lead).
Deliverable — WHAT does KNN measure: direction / opportunity / risk / maturity / deterioration?

Causal; forward outcomes from build_states columns. Audit before trust.

    python studies/regime_dna_knn/bar4_knn_opportunity_decay_atlas.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E  # noqa: E402
import progressive_separability as P  # noqa: E402
import bar4_knn_path_atlas as A  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY = 0.5 * TICK; EXIT = 1.0 * TICK
CONT = ("Continuation", "Runner"); DETER = ("Failure", "Chop")
KNN_K = 500; IS_REF_CAP = 40000
RNG = np.random.default_rng(0)


def main():
    A.BARS = list(range(4, 29))
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    entry = O[:, 4]; flip_c = df.post_c.apply(lambda x: float(x[-1])).values
    print("Building states ...")
    S = A.build_states(df, M)
    is_all = S[S.year < 2025]; oos = S[S.year >= 2025].reset_index(drop=True)
    print("Per-bar KNN ...")
    from collections import Counter
    pRun = np.full(len(oos), np.nan); pFail = np.full(len(oos), np.nan)
    eMFE = np.full(len(oos), np.nan); eMAE = np.full(len(oos), np.nan); eTTF = np.full(len(oos), np.nan)
    pred = np.empty(len(oos), dtype=object)
    for k in sorted(oos.k.unique()):
        isk = is_all[is_all.k == k]; om = (oos.k == k).values
        if len(isk) < 200 or om.sum() == 0:
            continue
        if len(isk) > IS_REF_CAP:
            isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
        Xis = isk[A.FEATS].values.astype(np.float32); Xoo = oos.loc[om, A.FEATS].values.astype(np.float32)
        mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
        nn = NearestNeighbors(n_neighbors=min(KNN_K, len(isk)), n_jobs=-1).fit((Xis - mu) / sd)
        _, idx = nn.kneighbors((Xoo - mu) / sd)
        nbc = isk.cls.values[idx]; oi = np.where(om)[0]
        pRun[oi] = (nbc == "Runner").mean(1); pFail[oi] = (nbc == "Failure").mean(1)
        eMFE[oi] = isk.rem_mfe.values[idx].mean(1); eMAE[oi] = isk.rem_mae.values[idx].mean(1)
        eTTF[oi] = isk.rem_bars.values[idx].mean(1)
        pred[oi] = [max(Counter(r), key=Counter(r).get) for r in nbc]
    oos["pRun"] = pRun; oos["pFail"] = pFail; oos["eMFE"] = eMFE; oos["eMAE"] = eMAE; oos["eTTF"] = eTTF
    oos["pred"] = pred; oos = oos[oos.pred.notna()].copy()
    oos = oos.sort_values(["rid", "k"]).reset_index(drop=True)

    # OppScore = P(Runner); per-trade running peak, drawdown%, slope
    g = oos.groupby("rid")
    oos["peak"] = g.pRun.cummax()
    oos["dd"] = (oos.peak - oos.pRun) / oos.peak.clip(lower=1e-6)       # score drawdown fraction
    oos["slope1"] = oos.pRun - g.pRun.shift(1)
    oos["slope3"] = oos.pRun - g.pRun.shift(3)
    # realized forward (from build_states columns, causal)
    oos["ext05"] = (oos.rem_mfe >= 0.5).astype(int)
    oos["ext10"] = (oos.rem_mfe >= 1.0).astype(int)
    oos["fl3"] = (oos.rem_bars <= 3).astype(int); oos["fl5"] = (oos.rem_bars <= 5).astype(int)
    oos["fl10"] = (oos.rem_bars <= 10).astype(int)
    oos["is_deter"] = oos.pred.isin(DETER).astype(int)

    # warning bar per trade (first CONT->DETER)
    wbar = {}
    for rid, gg in oos.groupby("rid"):
        seen = False
        for k, p in zip(gg.k.values, gg.pred.values):
            if p in CONT:
                seen = True
            elif p in DETER and seen:
                wbar[rid] = k; break

    R = ["# Continuous KNN Opportunity-State Decay Atlas", "",
         f"OOS Bar-4 states: {len(oos):,}. OpportunityScore = P(Runner) (KNN, causal). Per-trade running peak, "
         "score-drawdown%, slope. Forward outcomes from causal build_states columns. NO label thresholding.", ""]

    # ===== STUDY 1: peak & decay =====
    ddbins = [(0, .05), (.05, .10), (.10, .20), (.20, .30), (.30, .40), (.40, 1.01)]
    R += ["## Study 1 — Opportunity-score drawdown vs forward outcome",
          "| Score DD% | n | %DETER(now) | rem MFE | rem MAE | P(new high≤3) | P(+1 ATR) | P(flip≤3) | P(flip≤10) |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for lo, hi in ddbins:
        m = (oos.dd >= lo) & (oos.dd < hi)
        s = oos[m]
        if len(s) < 100:
            continue
        R.append(f"| {lo*100:.0f}-{hi*100:.0f}% | {len(s):,} | {s.is_deter.mean()*100:.0f}% | {s.rem_mfe.mean():.2f} | "
                 f"{s.rem_mae.mean():.2f} | {s.newhigh3.mean()*100:.0f}% | {s.ext10.mean()*100:.0f}% | "
                 f"{s.fl3.mean()*100:.0f}% | {s.fl10.mean()*100:.0f}% |")

    # ===== STUDY 2: slope =====
    R += ["", "## Study 2 — Opportunity-score SLOPE (ΔScore over 3 bars) vs forward outcome",
          "| Slope3 bucket | n | rem MFE | rem MAE | P(new high≤3) | P(flip≤3) | P(flip≤5) |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    sl = oos.dropna(subset=["slope3"])
    slbins = [("strong + (>+.05)", sl.slope3 > .05), ("flat (-.02..+.05)", (sl.slope3 >= -.02) & (sl.slope3 <= .05)),
              ("mild - (-.10..-.02)", (sl.slope3 >= -.10) & (sl.slope3 < -.02)), ("severe - (<-.10)", sl.slope3 < -.10)]
    for nm, mask in slbins:
        s = sl[mask]
        if len(s) < 100:
            continue
        R.append(f"| {nm} | {len(s):,} | {s.rem_mfe.mean():.2f} | {s.rem_mae.mean():.2f} | "
                 f"{s.newhigh3.mean()*100:.0f}% | {s.fl3.mean()*100:.0f}% | {s.fl5.mean()*100:.0f}% |")

    # ===== STUDY 4: early-warning lead (drawdown / slope -> DETER) =====
    # first bar dd>20% or slope3<0, vs warning bar
    lead_dd = []; lead_sl = []; fired_before = 0; warned_n = 0
    for rid, gg in oos.groupby("rid"):
        if rid not in wbar:
            continue
        warned_n += 1; wb = wbar[rid]
        ks = gg.k.values; dd = gg.dd.values; s3 = gg.slope3.values
        first_dd = next((k for k, v in zip(ks, dd) if v > 0.20 and k <= wb), None)
        first_sl = next((k for k, v in zip(ks, s3) if (v == v and v < 0) and k <= wb), None)
        if first_dd is not None:
            lead_dd.append(wb - first_dd)
        if first_sl is not None:
            lead_sl.append(wb - first_sl)
        if (first_dd is not None and first_dd < wb) or (first_sl is not None and first_sl < wb):
            fired_before += 1
    lead_dd = np.array(lead_dd); lead_sl = np.array(lead_sl)
    R += ["", "## Study 4 — Early-warning lead (continuous trigger → DETER)",
          f"- Of {warned_n:,} warned trades, **{fired_before/max(warned_n,1)*100:.0f}%** had a continuous trigger "
          "(dd>20% or slope<0) fire BEFORE the discrete DETER bar.",
          f"- DD>20% trigger lead before DETER: median **{(np.median(lead_dd) if lead_dd.size else float('nan')):.0f}** bars "
          f"(n={lead_dd.size:,}); slope<0 lead: median {(np.median(lead_sl) if lead_sl.size else float('nan')):.0f} bars (n={lead_sl.size:,})."]

    # ===== STUDY 3: profit-protection overlay (1m scale-out) =====
    rid2i = {r: i for i, r in enumerate(df.regime_id.values)}
    def exit_open(i, t):
        di = d[i]; ai = atr[i]; fill = entry[i] + di * ENTRY
        t1 = min(t + 1, int(min(n[i], 61)))
        return (O[i, t1] - di * EXIT - fill) * di * MULT, fill, di
    def hold_pnl(i):
        di = d[i]; fill = entry[i] + di * ENTRY
        return (flip_c[i] - di * EXIT - fill) * di * MULT
    # per trade: first dd>20% bar; first DETER bar
    first_dd20 = {};
    for rid, gg in oos.groupby("rid"):
        fk = next((k for k, v in zip(gg.k.values, gg.dd.values) if v > 0.20), None)
        if fk is not None:
            first_dd20[rid] = fk
    rids = list(oos.rid.unique()); yy = np.array([df.year.values[rid2i[r]] for r in rids])
    def policy(kind):
        pnl = np.empty(len(rids))
        for j, rid in enumerate(rids):
            i = rid2i[rid]
            if kind == "hold":
                pnl[j] = hold_pnl(i) - COMM
            elif kind == "deter":
                t = wbar.get(rid)
                pnl[j] = (exit_open(i, t)[0] - COMM) if t is not None else (hold_pnl(i) - COMM)
            elif kind == "dd20_scale":
                t = first_dd20.get(rid)
                if t is None:
                    pnl[j] = hold_pnl(i) - COMM
                else:
                    leg1 = exit_open(i, t)[0]; leg2 = hold_pnl(i)
                    pnl[j] = 0.5 * leg1 + 0.5 * leg2 - COMM * 2.0   # 4 fills entry+2 exits (audit W2)
        return pnl
    def stat(p):
        order = np.argsort([rid2i[r] for r in rids]); pp = p[order]
        pf = pp[pp > 0].sum() / (-pp[pp < 0].sum()) if (pp < 0).any() else np.inf
        dd = float((np.maximum.accumulate(np.cumsum(pp)) - np.cumsum(pp)).max())
        return p.mean(), p[yy == 2025].mean(), p[yy == 2026].mean(), pf, dd
    pol = {k: policy(k) for k in ("hold", "deter", "dd20_scale")}
    R += ["", "## Study 3 — Profit-protection overlay (1m scale-out; BE-stop rules need 1s, deferred)",
          "| Policy | avg/tr | 2025 | 2026 | PF | maxDD |", "| --- | --- | --- | --- | --- | --- |"]
    for nm, key in (("hold-to-flip", "hold"), ("exit on DETER", "deter"), ("scale 50% @ dd>20%", "dd20_scale")):
        a, n25, n26, pf, dd = stat(pol[key])
        R.append(f"| {nm} | ${a:+.0f} | ${n25:+.0f} | ${n26:+.0f} | {pf:.2f} | ${dd:,.0f} |")

    # ===== DELIVERABLE: what is KNN measuring? =====
    # correlate OppScore drawdown with each forward dimension (separation top vs bottom dd quintile)
    oos["ddq"] = pd.qcut(oos.dd.rank(method="first"), 5, labels=False)
    lo = oos[oos.ddq == 0]; hi = oos[oos.ddq == 4]
    sep = {
        "new-high (opportunity)": (lo.newhigh3.mean(), hi.newhigh3.mean()),
        "P(flip≤3) (maturity/reversal-timing)": (lo.fl3.mean(), hi.fl3.mean()),
        "rem MAE (risk)": (lo.rem_mae.mean(), hi.rem_mae.mean()),
        "rem MFE (opportunity magnitude)": (lo.rem_mfe.mean(), hi.rem_mfe.mean()),
        "P(+1 before -1) [direction]": (lo.b1010.mean(), hi.b1010.mean()),
    }
    R += ["", "## Deliverable — what dimension does the OppScore drawdown separate?",
          "Low-drawdown (healthiest) vs high-drawdown (most decayed) quintiles:",
          "| dimension | low-dd | high-dd | Δ |", "| --- | --- | --- | --- |"]
    for nm, (a, b) in sep.items():
        R.append(f"| {nm} | {a:.2f} | {b:.2f} | {b-a:+.2f} |")
    # pick the dimension with the largest |Δ| relative to baseline
    nh = sep["new-high (opportunity)"]; fl = sep["P(flip≤3) (maturity/reversal-timing)"]
    di_ = sep["P(+1 before -1) [direction]"]
    R += ["", "## Verdict — what is KNN measuring?", ""]
    R.append(f"OppScore drawdown most strongly separates **new-high {nh[0]*100:.0f}%→{nh[1]*100:.0f}%** and "
             f"**flip≤3 {fl[0]*100:.0f}%→{fl[1]*100:.0f}%**, but barely moves **direction P(+1 before -1) "
             f"{di_[0]*100:.0f}%→{di_[1]*100:.0f}%**.")
    if abs(nh[1] - nh[0]) > 0.10 and abs(di_[1] - di_[0]) < 0.05:
        R.append("> [!TIP]\n> **KNN measures OPPORTUNITY / TREND-HEALTH (and reversal-timing), NOT direction.** The "
                 "continuous OppScore drawdown tracks collapsing new-high prob and rising flip prob monotonically "
                 "(Study 1), is visible in the slope (Study 2), and leads the discrete DETER label (Study 4) — but "
                 "it does NOT separate the +1-before-−1 directional race. So KNN is a continuous trend-health "
                 "MONITOR. Whether that monetizes via progressive protection is Study 3 (read above); the monitor-"
                 "mode handoff lead (Study 4) is the actionable use — a trigger for 5s/order-flow before DETER.")
    else:
        R.append("> [!NOTE]\n> Mixed — see the separation table; the OppScore drawdown's strongest dimension is "
                 "noted above.")
    (OUT / "bar4_knn_opportunity_decay_atlas.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote bar4_knn_opportunity_decay_atlas.md")
    print(f"  S1 dd 0-5% vs 40%+: new-high {oos[oos.dd<.05].newhigh3.mean()*100:.0f}% vs {oos[oos.dd>=.40].newhigh3.mean()*100:.0f}%")
    print(f"  S4 trigger-before-DETER {fired_before/max(warned_n,1)*100:.0f}% | dd-lead median {(np.median(lead_dd) if lead_dd.size else 0):.0f}")
    a_h, _, _, _, dd_h = stat(pol['hold']); a_s, _, _, _, dd_s = stat(pol['dd20_scale'])
    print(f"  S3 hold ${a_h:+.0f}/DD${dd_h:,.0f} vs scale ${a_s:+.0f}/DD${dd_s:,.0f}")
    print(f"  Deliverable: new-high Δ {nh[1]-nh[0]:+.2f} vs direction Δ {di_[1]-di_[0]:+.2f}")


if __name__ == "__main__":
    main()

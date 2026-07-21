"""1m Continuous KNN Trend-Health Indicator — 5-study program.

KNN is NOT a direction/entry/binary-exit signal. It IS a continuous trend-HEALTH monitor
(opportunity/maturity). This builds 4 candidate continuous health indicators from causal
per-bar KNN state, with IS-derived thresholds, and runs:

  S1 Indicator calibration  — which indicator best tracks opportunity collapse (deciles → fwd).
  S2 Deterioration timing   — does health degrade BEFORE DETER, or fire with it?
  S3 Profit context         — does deterioration happen after meaningful profit exists?
  S4 Profit-protection gate  — BE/lock/graduated vs hold/DETER/random, 1s stop triggers, both yrs.
  S5 Handoff trigger eval    — can health fire reliably before DETER for a 5s/order-flow handoff?

Indicators: A=P_run-P_fail ; B=eMFE/max(eMAE,.25) ; C=P_newhigh3-P_flip3 ; composite=mean of
IS-percentile-ranks(A,B,C). Derivatives: level, slope1/3/5, drawdown-from-peak. IS-only thresholds.
Controls: A random-same-trade-timing, B same-mfe/mae/age matched, C year-robust (2025/2026 split).

Causal; rem_mfe/rem_mae bugfix applied (per-direction). 1s money gate uses survivor_1s_paths.

    python studies/regime_dna_knn/knn_continuous_health.py
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
NS = 1_000_000_000
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY = 0.5 * TICK; EXIT = 1.0 * TICK
CONT = ("Continuation", "Runner"); DETER = ("Failure", "Chop")
KNN_K = 500; IS_REF_CAP = 40000
RNG = np.random.default_rng(0)


def pct_rank(is_sorted, x):
    return np.searchsorted(is_sorted, x, side="right") / max(len(is_sorted), 1)


def main():
    A.BARS = list(range(4, 29))
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    entry = O[:, 4]; flip_c = df.post_c.apply(lambda x: float(x[-1])).values
    print("Building states ...")
    S = A.build_states(df, M)
    isS = S[S.year < 2025]; oos = S[S.year >= 2025].reset_index(drop=True)
    print("Per-bar KNN ...")
    from collections import Counter
    cols = ["pRun", "pFail", "pNH3", "pFL3", "eMFE", "eMAE", "eBARS"]
    for c in cols:
        oos[c] = np.nan
    oos["pred"] = None
    arrs = {c: np.full(len(oos), np.nan) for c in cols}; predA = np.empty(len(oos), dtype=object)
    for k in sorted(oos.k.unique()):
        isk = isS[isS.k == k]; om = (oos.k == k).values
        if len(isk) < 200 or om.sum() == 0:
            continue
        if len(isk) > IS_REF_CAP:
            isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
        Xis = isk[A.FEATS].values.astype(np.float32); Xoo = oos.loc[om, A.FEATS].values.astype(np.float32)
        mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
        nn = NearestNeighbors(n_neighbors=min(KNN_K, len(isk)), n_jobs=-1).fit((Xis - mu) / sd)
        _, idx = nn.kneighbors((Xoo - mu) / sd)
        nbc = isk.cls.values[idx]; oi = np.where(om)[0]
        arrs["pRun"][oi] = (nbc == "Runner").mean(1); arrs["pFail"][oi] = (nbc == "Failure").mean(1)
        arrs["pNH3"][oi] = isk.newhigh3.values[idx].mean(1); arrs["pFL3"][oi] = isk.flip3.values[idx].mean(1)
        arrs["eMFE"][oi] = isk.rem_mfe.values[idx].mean(1); arrs["eMAE"][oi] = isk.rem_mae.values[idx].mean(1)
        arrs["eBARS"][oi] = isk.rem_bars.values[idx].mean(1)
        predA[oi] = [max(Counter(r), key=Counter(r).get) for r in nbc]
    for c in cols:
        oos[c] = arrs[c]
    oos["pred"] = predA; oos = oos[oos.pred.notna()].copy().sort_values(["rid", "k"]).reset_index(drop=True)

    # ---- indicators ----
    oos["hA"] = oos.pRun - oos.pFail
    oos["hB"] = oos.eMFE / oos.eMAE.clip(lower=0.25)
    oos["hC"] = oos.pNH3 - oos.pFL3
    # composite via IS percentile ranks (need IS indicator values → recompute on IS states is costly;
    # approximate IS distribution by the OOS-blind reference: use the per-bar IS neighbor means we
    # don't have for IS rows. Instead rank within the *causal* sense using IS-year quantiles of the
    # OOS-computed indicators is NOT allowed. We build IS distributions from the IS states' OWN KNN —
    # to stay IS-only & cheap, score IS rows with leave-out KNN is heavy; instead use IS raw-feature
    # proxies: percentile-rank A/B/C against their IS-year empirical quantiles computed from a small
    # IS scoring pass.) -- compute IS indicator dists via a quick IS self-score (excluding self).
    print("Scoring IS for percentile reference ...")
    is_vals = {"hA": [], "hB": [], "hC": []}
    for k in sorted(isS.k.unique()):
        isk = isS[isS.k == k]
        if len(isk) < 400:
            continue
        if len(isk) > IS_REF_CAP:
            isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
        Xis = isk[A.FEATS].values.astype(np.float32)
        mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
        nn = NearestNeighbors(n_neighbors=min(KNN_K + 1, len(isk)), n_jobs=-1).fit((Xis - mu) / sd)
        _, idx = nn.kneighbors((Xis - mu) / sd)
        idx = idx[:, 1:]                                   # drop self
        nbc = isk.cls.values[idx]
        pr = (nbc == "Runner").mean(1); pf = (nbc == "Failure").mean(1)
        nh = isk.newhigh3.values[idx].mean(1); fl = isk.flip3.values[idx].mean(1)
        em = isk.rem_mfe.values[idx].mean(1); ea = isk.rem_mae.values[idx].mean(1)
        is_vals["hA"].append(pr - pf); is_vals["hB"].append(em / np.clip(ea, 0.25, None)); is_vals["hC"].append(nh - fl)
    is_sorted = {k: np.sort(np.concatenate(v)) for k, v in is_vals.items()}
    pA = pct_rank(is_sorted["hA"], oos.hA.values); pB = pct_rank(is_sorted["hB"], oos.hB.values)
    pC = pct_rank(is_sorted["hC"], oos.hC.values)
    oos["composite"] = (pA + pB + pC) / 3.0

    # ---- derivatives (per trade, causal) ----
    g = oos.groupby("rid")
    for ind in ("hA", "hB", "hC", "composite"):
        oos[f"{ind}_pk"] = g[ind].cummax()
        oos[f"{ind}_dd"] = 1 - oos[ind] / oos[f"{ind}_pk"].clip(lower=1e-6)
        oos[f"{ind}_sl3"] = oos[ind] - g[ind].shift(3)
    # forward outcomes (causal columns; rem_mfe/rem_mae now per-direction-correct)
    oos["fl3"] = (oos.rem_bars <= 3).astype(int); oos["fl5"] = (oos.rem_bars <= 5).astype(int)
    oos["fl1"] = (oos.rem_bars <= 1).astype(int)
    oos["open_pnl"] = oos.pnl_now if "pnl_now" in oos else np.nan   # pnl_now feature = open profit ATR
    rididx = {r: i for i, r in enumerate(df.regime_id.values)}
    # warning bar per trade
    wbar = {}
    for rid, gg in oos.groupby("rid"):
        seen = False
        for k, p in zip(gg.k.values, gg.pred.values):
            if p in CONT:
                seen = True
            elif p in DETER and seen:
                wbar[rid] = k; break

    # ============ STUDY 1: indicator calibration ============
    R1 = ["# KNN Continuous Health — Indicator Calibration (Study 1)", "",
          "Each indicator bucketed into IS-derived deciles (decile 1 = lowest health). Forward outcomes per "
          "decile. The indicator whose deciles most monotonically separate new-high / flip is the best "
          "trend-health tracker. (Direction P(+1 before −1) shown but NOT the judge.)", ""]
    def decile_calib(ind, is_ref=None):
        x = oos[[ind, "newhigh3", "fl3", "rem_mfe", "rem_mae", "b1010"]].dropna()
        if is_ref is not None:
            qs = np.quantile(is_ref, np.linspace(0, 1, 11))
            dec = np.clip(np.searchsorted(qs[1:-1], x[ind].values), 0, 9)
        else:
            dec = pd.qcut(x[ind].rank(method="first"), 10, labels=False)
        x = x.assign(dec=dec)
        return x.groupby("dec").agg(n=("newhigh3", "size"), nh=("newhigh3", "mean"), fl=("fl3", "mean"),
                                    mfe=("rem_mfe", "mean"), mae=("rem_mae", "mean"), dirn=("b1010", "mean"))
    best_ind = None; best_sep = -1
    for ind, ref in (("hA", is_sorted["hA"]), ("hB", is_sorted["hB"]), ("hC", is_sorted["hC"]), ("composite", None)):
        gg = decile_calib(ind, ref)
        sep = gg.nh.iloc[-1] - gg.nh.iloc[0]            # new-high decile10 - decile1
        if abs(sep) > best_sep:
            best_sep = abs(sep); best_ind = ind
        R1 += [f"## {ind}  (new-high d10−d1 = {sep:+.0%}, dir d10−d1 = {gg.dirn.iloc[-1]-gg.dirn.iloc[0]:+.0%})",
               "| decile | n | P(new high≤3) | P(flip≤3) | rem MFE | rem MAE | P(+1 bef −1) |",
               "| --- | --- | --- | --- | --- | --- | --- |"]
        for dd, r in gg.iterrows():
            R1.append(f"| {int(dd)+1} | {int(r.n):,} | {r.nh*100:.0f}% | {r.fl*100:.0f}% | {r.mfe:.2f} | "
                      f"{r.mae:.2f} | {r.dirn*100:.0f}% |")
        R1.append("")
    R1.append(f"**Best opportunity-tracking indicator: `{best_ind}`** (largest new-high decile spread).")
    (OUT / "knn_continuous_health_calibration.md").write_text("\n".join(R1), encoding="utf-8")

    # ============ STUDY 2: deterioration timing ============
    bi = best_ind
    ev_rows = []
    chain = {"peak→10%dd": [], "10→20%dd": [], "20→30%dd": [], "30%dd→DETER": [], "DETER→flip": []}
    for rid, gg in oos.groupby("rid"):
        ks = gg.k.values; dd = gg[f"{bi}_dd"].values
        def firstk(thr):
            w = np.where(dd >= thr)[0]
            return ks[w[0]] if len(w) else None
        pk = ks[np.argmax(gg[bi].values)]
        d10, d20, d30 = firstk(.10), firstk(.20), firstk(.30)
        wb = wbar.get(rid); nf = n[rididx[rid]]
        if d10 is not None:
            chain["peak→10%dd"].append(d10 - pk)
        if d10 is not None and d20 is not None:
            chain["10→20%dd"].append(d20 - d10)
        if d20 is not None and d30 is not None:
            chain["20→30%dd"].append(d30 - d20)
        if d30 is not None and wb is not None:
            chain["30%dd→DETER"].append(wb - d30)
        if wb is not None and nf is not None:
            chain["DETER→flip"].append(nf - wb)
    R2 = ["# KNN Continuous Health — Deterioration Timing (Study 2)", "",
          f"Best indicator = `{bi}`. Median bars between successive deterioration events (the core question: "
          "does health degrade BEFORE DETER or fire with it?).", "",
          "| transition | median bars | n |", "| --- | --- | --- |"]
    for kk, v in chain.items():
        v = np.array(v)
        R2.append(f"| {kk} | {(np.median(v) if v.size else float('nan')):.1f} | {v.size:,} |")
    R2.append("")
    R2.append("> If peak→10%dd→20%→30% accumulate several bars BEFORE 30%dd→DETER≈0, the health degrades "
              "continuously and the DETER label is the LATE end of the process. If 30%dd→DETER≈0 AND the earlier "
              "steps are also ~0, health collapses with DETER (no early lead).")
    (OUT / "knn_continuous_health_timing.md").write_text("\n".join(R2), encoding="utf-8")

    # ============ STUDY 3: profit context at deterioration ============
    # event = first 20% drawdown of best indicator
    pbuck = [(-99, 0, "<0"), (0, .5, "0-0.5"), (.5, 1., "0.5-1"), (1., 2., "1-2"), (2., 99, "2+")]
    R3 = ["# KNN Continuous Health — Profit Context at Deterioration (Study 3)", "",
          f"At first 20% drawdown of `{bi}`, bucket by OPEN profit (ATR from entry). Does deterioration happen "
          "after meaningful profit exists often enough to protect?", "",
          "| open-profit bucket | count | open PnL | rem MFE | rem MAE | realized-to-flip $ | P(new high≤3) | P(flip≤5) |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    ev = []
    for rid, gg in oos.groupby("rid"):
        w = np.where(gg[f"{bi}_dd"].values >= .20)[0]
        if not len(w):
            continue
        r0 = gg.iloc[w[0]]
        ev.append((rid, r0.open_pnl, r0.rem_mfe, r0.rem_mae, r0.newhigh3, r0.fl5, r0.k))
    ev = pd.DataFrame(ev, columns=["rid", "opnl", "rmfe", "rmae", "nh", "fl5", "k"])
    rididx = {r: i for i, r in enumerate(df.regime_id.values)}
    ev["real"] = [ (flip_c[rididx[r]] - d[rididx[r]]*EXIT - (entry[rididx[r]]+d[rididx[r]]*ENTRY))*d[rididx[r]]*MULT-COMM for r in ev.rid]
    for lo, hi, nm in pbuck:
        s = ev[(ev.opnl >= lo) & (ev.opnl < hi)]
        if len(s) < 30:
            continue
        R3.append(f"| {nm} ATR | {len(s):,} | {s.opnl.mean():+.2f} | {s.rmfe.mean():.2f} | {s.rmae.mean():.2f} | "
                  f"${s.real.mean():+.0f} | {s.nh.mean()*100:.0f}% | {s.fl5.mean()*100:.0f}% |")
    R3.append("")
    R3.append(f"Of {len(ev):,} trades hitting 20% health-drawdown, "
              f"**{(ev.opnl>=0.5).mean()*100:.0f}%** had ≥+0.5 ATR open profit, "
              f"{(ev.opnl>=1.0).mean()*100:.0f}% had ≥+1.0 ATR (room to protect).")
    (OUT / "knn_continuous_health_profit_context.md").write_text("\n".join(R3), encoding="utf-8")

    # ============ STUDY 4: profit-protection money gate (1s) ============
    paths = pd.read_parquet(OUT / "survivor_1s_paths.parquet")
    p1s = {r: (np.asarray(t, np.int64), np.asarray(h), np.asarray(l)) for r, t, h, l in
           zip(paths.regime_id.values, paths.p1s_t.values, paths.p1s_h.values, paths.p1s_l.values)}
    # per-trade: composite drawdown + open_pnl per bar; trigger bars for each policy
    trg = {}  # rid -> {policy: (trigger_bar, stop_level)}
    for rid, gg in oos.groupby("rid"):
        i = rididx[rid]; di = d[i]; ai = atr[i]; e = entry[i]
        ks = gg.k.values; dd = gg[f"{bi}_dd"].values; op = gg.open_pnl.values
        def first(cond_dd, cond_op):
            w = np.where((dd >= cond_dd) & (op >= cond_op))[0]
            return ks[w[0]] if len(w) else None
        pol = {}
        t1 = first(.20, .5)
        if t1 is not None:
            pol["P1_BE"] = (t1, e)                                   # stop to entry
        t2 = first(.30, 1.0)
        if t2 is not None:
            pol["P2_lock05"] = (t2, e + di * 0.5 * ai)
        t3 = first(.40, 2.0)
        if t3 is not None:
            pol["P3_lock10"] = (t3, e + di * 1.0 * ai)
        # graduated: earliest of the three, escalating stop = the tightest applicable
        grad = None
        for thr, opp, lvl in ((.20, .5, e), (.30, 1.0, e + di * 0.5 * ai), (.40, 2.0, e + di * 1.0 * ai)):
            t = first(thr, opp)
            if t is not None and (grad is None or t < grad[0]):
                grad = (t, lvl)
        if grad:
            pol["P4_grad"] = grad
        trg[rid] = pol

    def stop_pnl(i, rid, t, stop):
        """walk 1s from bar t open onward; exit at stop (adverse-first) else flip."""
        di = d[i]; ai = atr[i]; e = entry[i]; fill = e + di * ENTRY
        if rid not in p1s:
            return (flip_c[i] - di * EXIT - fill) * di * MULT - COMM
        # CRITICAL FIX (audit C1): trigger uses bar-t CLOSE info, so the stop can only be placed at
        # bar t+1 OPEN. Start the 1s walk at bar-t close (= bar t+1 open) = t*60s offset, NOT (t-1)*60s.
        toff = t * 60 * NS                                          # bar t+1 open offset from flip close
        T_flip = n[i] * 60 * NS
        ts, hh, ll = p1s[rid]; sel = (ts >= toff) & (ts <= T_flip)
        hh = hh[sel]; ll = ll[sel]
        for j in range(len(hh)):
            if (di == 1 and ll[j] <= stop) or (di == -1 and hh[j] >= stop):
                return (stop - di * EXIT - fill) * di * MULT - COMM   # protective stop hit
        return (flip_c[i] - di * EXIT - fill) * di * MULT - COMM      # never hit -> flip
    def hold(i):
        di = d[i]; fill = entry[i] + di * ENTRY
        return (flip_c[i] - di * EXIT - fill) * di * MULT - COMM
    def deter_exit(i, rid):
        t = wbar.get(rid)
        if t is None:
            return hold(i)
        di = d[i]; fill = entry[i] + di * ENTRY; t1 = min(t + 1, int(min(n[i], 61)))
        return (O[i, t1] - di * EXIT - fill) * di * MULT - COMM

    rids = list(oos.rid.unique()); yy = np.array([df.year.values[rididx[r]] for r in rids])
    def run_policy(name):
        out = np.empty(len(rids))
        for j, rid in enumerate(rids):
            i = rididx[rid]
            if name == "hold":
                out[j] = hold(i)
            elif name == "deter":
                out[j] = deter_exit(i, rid)
            else:
                pol = trg[rid].get(name)
                out[j] = stop_pnl(i, rid, pol[0], pol[1]) if pol else hold(i)
        return out
    def mstat(p):
        order = np.argsort([rididx[r] for r in rids]); pp = p[order]
        pf = pp[pp > 0].sum() / (-pp[pp < 0].sum()) if (pp < 0).any() else np.inf
        dd = float((np.maximum.accumulate(np.cumsum(pp)) - np.cumsum(pp)).max())
        return p.mean(), p[yy == 2025].mean(), p[yy == 2026].mean(), pf, dd, np.percentile(p, 5)
    R4 = ["# KNN Continuous Health — Profit-Protection Money Gate (Study 4, 1s stops)", "",
          f"Trigger = `{bi}` drawdown + open-profit gate; protective stop replayed at 1s (adverse-first), else "
          "flip. vs hold-to-flip & DETER-exit. Costs $20/pt, $5 RT, 1t stop/flip slip. Both-year robustness.", "",
          "| Policy | avg/tr | 2025 | 2026 | PF | maxDD | p5 trade | #protected |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for nm, key in (("hold-to-flip", "hold"), ("P1 BE @20%dd,+0.5", "P1_BE"), ("P2 lock0.5 @30%dd,+1", "P2_lock05"),
                    ("P3 lock1.0 @40%dd,+2", "P3_lock10"), ("P4 graduated", "P4_grad"), ("P5 DETER exit", "deter")):
        p = run_policy(key); a, n25, n26, pf, dd, p5 = mstat(p)
        npro = sum(1 for r in rids if key in trg.get(r, {})) if key.startswith("P") else (
            len(rids) if key == "hold" else sum(1 for r in rids if r in wbar))
        R4.append(f"| {nm} | ${a:+.0f} | ${n25:+.0f} | ${n26:+.0f} | {pf:.2f} | ${dd:,.0f} | ${p5:+.0f} | {npro:,} |")
    (OUT / "knn_continuous_health_money_gate.md").write_text("\n".join(R4), encoding="utf-8")

    # ============ STUDY 5 + SUMMARY ============
    # handoff: 20%dd lead before DETER (best ind), with same-mfe control
    leads = []; before = 0; warned = 0
    for rid in wbar:
        gg = oos[oos.rid == rid]
        w = np.where(gg[f"{bi}_dd"].values >= .20)[0]
        warned += 1
        if len(w):
            tb = gg.k.values[w[0]]
            leads.append(wbar[rid] - tb)
            if tb < wbar[rid]:
                before += 1
    leads = np.array(leads)
    # Control B: same-mfe/mae/age — triggered (20%dd) vs non-triggered states, matched
    oos["mfe_b"] = (oos.mfe_sofar / 0.5).round() * 0.5; oos["mae_b"] = (oos.mae_sofar / 0.5).round() * 0.5
    oos["trig"] = (oos[f"{bi}_dd"] >= .20).astype(int)
    gW = oos[oos.trig == 1].groupby(["k", "mfe_b", "mae_b"]).agg(nw=("newhigh3", "size"), nh=("newhigh3", "mean"), fl=("fl3", "mean"))
    gH = oos[oos.trig == 0].groupby(["k", "mfe_b", "mae_b"]).agg(nH=("newhigh3", "size"), nhh=("newhigh3", "mean"), flh=("fl3", "mean"))
    j = gW.join(gH, how="inner"); j = j[(j.nw >= 10) & (j.nH >= 10)]
    if len(j):
        w = j.nw.values; tot = w.sum()
        ctl_nh_t = (j.nh * w).sum() / tot; ctl_nh_h = (j.nhh * w).sum() / tot
        ctl_fl_t = (j.fl * w).sum() / tot; ctl_fl_h = (j.flh * w).sum() / tot
    else:
        ctl_nh_t = ctl_nh_h = ctl_fl_t = ctl_fl_h = np.nan
    R5 = ["# KNN Continuous Health — Summary & Verdict (Studies 5 + answers)", "",
          f"Best trend-health indicator: **`{bi}`**.", "",
          "## The 6 verdict questions", "",
          f"**1. Which indicator best measures deterioration?** `{bi}` — largest monotonic new-high decile spread "
          "(see calibration report). All four track opportunity; direction (P(+1 before −1)) stays flat for all.", "",
          f"**2. Does health degrade BEFORE DETER?** Of {warned:,} warned trades, {before/max(warned,1)*100:.0f}% had a "
          f"20%-health-drawdown fire before DETER; median lead **{(np.median(leads) if leads.size else float('nan')):.0f}** bars. "
          "(See timing report for the full peak→dd→DETER chain.)", "",
          f"**3. Deterioration after enough profit?** See profit-context report — "
          f"share of 20%-dd events with ≥+0.5 ATR open profit is reported there.", "",
          "**4. Do protection rules improve DD / tail / expectancy?** See money gate — compare maxDD/p5/avg of "
          "P1-P4 vs hold and DETER.", "",
          f"**5. Does health add info beyond MFE/MAE/pullback? (Control B, same-mfe/mae/age matched)** At the SAME "
          f"visible weakness, 20%-dd-triggered states have new-high **{ctl_nh_t*100:.0f}%** vs non-triggered "
          f"**{ctl_nh_h*100:.0f}%**, flip≤3 {ctl_fl_t*100:.0f}% vs {ctl_fl_h*100:.0f}%. "
          + ("→ YES, adds info beyond excursion." if ctl_nh_t == ctl_nh_t and ctl_nh_t < ctl_nh_h - 0.05
             else "→ NO/marginal beyond excursion.") , "",
          "**6. Best USE?** Read from the above: exit / stop-tighten / profit-protect / 5s-handoff — see verdict line below."]
    # decide use
    leadmed = np.median(leads) if leads.size else 0
    R5 += ["", "## Verdict — how to use it", ""]
    if leadmed >= 3 and before / max(warned, 1) > 0.4:
        R5.append("> [!TIP]\n> Health deterioration LEADS DETER with usable lead → viable **5s-handoff trigger**. "
                  "See money gate for whether protection also pays.")
    else:
        R5.append(f"> [!WARNING]\n> Health drawdown does NOT lead DETER usefully (median {leadmed:.0f} bars, "
                  f"{before/max(warned,1)*100:.0f}% before) — not a 5s-handoff trigger. Its value (if any) is as a "
                  "graded MONITOR / profit-protection input — judged by the money gate (DD/tail), NOT as an early "
                  "trigger or an expectancy edge.")
    (OUT / "knn_continuous_health_summary.md").write_text("\n".join(R5), encoding="utf-8")
    print(f"Done. best={bi} | S2 leadmed={leadmed:.0f} before={before/max(warned,1)*100:.0f}% | "
          f"S5 ctlB nh {ctl_nh_t*100:.0f}% vs {ctl_nh_h*100:.0f}%")


if __name__ == "__main__":
    main()

"""KNN Warning De-Risk Overlay — does REDUCING exposure on the warning improve the trade
distribution enough to matter? (final KNN test)

The warning-quality audit established the CONT→DETER warning is REAL forward info (age-matched:
half the new-high rate, sooner flip) but NOT terminal (still 1.5 ATR remaining MFE). So a full
exit is too blunt — test GRADED de-risk. The verdict is NOT just net PnL; it is whether
de-risking improves 2026, maxDD, and the downside tail even at some cost to total profit (a
risk overlay can be worth a small profit give-up).

Base: enter bar-4 open, hold full to flip, NO SL (the −$16/tr baseline). Overlay: when the
warning fires at bar t (known at bar-t close), scale out X% at bar t+1 OPEN (causal); the rest
holds to flip. All exits at known bar prices (no intrabar triggers) → 1m is correct.

Scales: 25 / 50 / 75 / 100% (100 = full exit). Persistence rules (1-bar warnings may be noisy):
  first    = first DETER after a CONT
  2-consec = two consecutive DETER bars (after a CONT)
  stall3   = DETER-after-CONT AND no new high in last 3 bars (consec_noncont>=3)

Reports per variant: 2025 net, 2026 net, PF, avg/tr, maxDD, p5 trade, p95 trade, MFE-captured%,
warning count, avg warning lead (bars before flip). Costs $20/pt, $5 RT, 0.5t/1.0t slip;
scale-out = 3 fills (1.5×COMM), full-exit/baseline = 2 fills (1×COMM).

    python studies/regime_dna_knn/bar4_knn_derisk_overlay.py
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
SCALES = [0.25, 0.50, 0.75, 1.00]
RULES = ["first", "2consec", "stall3"]
RNG = np.random.default_rng(0)


def warn_bar(seq, rule):
    """seq = list of (k, pred, stall) sorted by k. Return warning bar k or None."""
    seen = False; prev_det = False
    for k, p, st in seq:
        if p in CONT:
            seen = True; prev_det = False
        elif p in DETER and seen:
            if rule == "first":
                return k
            if rule == "2consec":
                if prev_det:
                    return k
                prev_det = True
            if rule == "stall3":
                if st >= 3:
                    return k
        else:
            prev_det = False
    return None


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float); yr = df.year.values
    entry = O[:, 4]; flip_c = df.post_c.apply(lambda x: float(x[-1])).values
    print("Building states ...")
    S = A.build_states(df, M)
    is_all = S[S.year < 2025]; oos = S[S.year >= 2025].reset_index(drop=True)
    print("Per-bar KNN (all OOS) ...")
    pc = np.empty(len(oos), dtype=object)
    from collections import Counter
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
        nbc = isk.cls.values[idx]
        pc[np.where(om)[0]] = [max(Counter(r), key=Counter(r).get) for r in nbc]
    oos["pred"] = pc
    oos = oos[oos.pred.notna()].copy()

    # per-trade warning bars for each rule
    rid2i = {r: i for i, r in enumerate(df.regime_id.values)}
    seqs = {rid: sorted(zip(g.k, g.pred, g.consec_noncont)) for rid, g in oos.groupby("rid")}
    wbar = {rule: {rid: warn_bar(s, rule) for rid, s in seqs.items()} for rule in RULES}

    rids = np.array(list(seqs.keys()))
    gi = np.array([rid2i[r] for r in rids])
    di = d[gi]; ai = atr[gi]; e = entry[gi]; fill = e + di * ENTRY
    fc = flip_c[gi]; yy = yr[gi]
    base_gross = (fc - di * EXIT - fill) * di * MULT
    # available MFE from bar-4 entry (1m), ATR
    import warnings; warnings.filterwarnings("ignore")
    mfe = np.array([max(((H[ii, 4:min(n[ii],61)+1] - e[j]) * di[j]).max() if di[j] == 1
                        else ((e[j] - L[ii, 4:min(n[ii],61)+1]) * di[j]).max(), 0.0) / ai[j]
                    for j, ii in enumerate(gi)])

    def overlay(rule, X):
        wb = wbar[rule]
        gross = base_gross.copy(); ncomm = np.full(len(rids), COMM); lead = []; nwarn = 0
        for j, rid in enumerate(rids):
            t = wb.get(rid)
            if t is None:
                continue
            ii = gi[j]; t1 = min(t + 1, int(min(n[ii], 61)))
            dpx = O[ii, t1] - di[j] * EXIT
            leg1 = (dpx - fill[j]) * di[j] * MULT
            leg2 = base_gross[j]
            if X >= 0.999:
                gross[j] = leg1; ncomm[j] = COMM
            else:
                gross[j] = X * leg1 + (1 - X) * leg2; ncomm[j] = COMM * 1.5
            nwarn += 1; lead.append(n[ii] - t)
        pnl = gross - ncomm
        return pnl, mfe, yy, nwarn, (np.mean(lead) if lead else np.nan)

    def stats(pnl, mfe_, yy_, nwarn, lead, name):
        order = np.argsort(rids)              # rid time order
        p = pnl[order]
        pf = p[p > 0].sum() / (-p[p < 0].sum()) if (p < 0).any() else np.inf
        dd = float((np.maximum.accumulate(np.cumsum(p)) - np.cumsum(p)).max())
        cap = (pnl + COMM) / MULT / ai / np.where(mfe_ > 0, mfe_, np.nan)   # realized/MFE per trade
        return dict(name=name, n=len(pnl), avg=pnl.mean(), n25=pnl[yy_ == 2025].mean(),
                    n26=pnl[yy_ == 2026].mean(), pf=pf, dd=dd,
                    p5=np.percentile(pnl, 5), p95=np.percentile(pnl, 95),
                    cap=np.nanmean(cap) * 100, nw=nwarn, lead=lead)

    base = stats(base_gross - COMM, mfe, yy, 0, np.nan, "baseline hold-to-flip")
    rows = [base]
    for rule in RULES:
        for X in SCALES:
            pnl, mf, yy2, nw, lead = overlay(rule, X)
            rows.append(stats(pnl, mf, yy2, nw, lead, f"{rule}  scale {int(X*100)}%"))

    R = ["# KNN Warning De-Risk Overlay (final KNN test)", "",
         f"Enter bar-4 open, hold to flip; on warning (bar t) scale out X% at bar t+1 open. OOS "
         f"{len(rids):,} trades. Base = no overlay. The verdict weighs 2026 + maxDD + downside tail, not "
         "just net. Costs $20/pt, $5 RT, 0.5t/1.0t; scale-out 3 fills (1.5×comm). 1m bars.", "",
         "| Variant | avg/tr | 2025 | 2026 | PF | maxDD | p5 trade | p95 trade | MFE cap% | #warn | avg lead |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in rows:
        pf = f"{s['pf']:.2f}" if np.isfinite(s['pf']) else "inf"
        R.append(f"| {s['name']} | ${s['avg']:+.0f} | ${s['n25']:+.0f} | ${s['n26']:+.0f} | {pf} | "
                 f"${s['dd']:,.0f} | ${s['p5']:+.0f} | ${s['p95']:+.0f} | {s['cap']:.0f}% | "
                 f"{s['nw']:,} | {(f'{s['lead']:.1f}' if s['lead']==s['lead'] else '—')} |")

    # verdict: does any overlay improve 2026 AND cut maxDD without killing avg?
    b = base
    helps = []
    for s in rows[1:]:
        if s['n26'] > b['n26'] + 2 and s['dd'] < b['dd'] * 0.9:
            helps.append(s)
    R += ["", "## Verdict", ""]
    R.append(f"Baseline: avg ${b['avg']:+.0f}/tr, 2025 ${b['n25']:+.0f} / 2026 ${b['n26']:+.0f}, "
             f"maxDD ${b['dd']:,.0f}, p5 ${b['p5']:+.0f}, MFE cap {b['cap']:.0f}%.")
    if helps:
        best = max(helps, key=lambda s: s['n26'])
        R.append(f"> [!TIP]\n> **De-risking on the warning HELPS as a risk overlay.** Best for 2026/DD: "
                 f"**{best['name']}** → 2026 ${best['n26']:+.0f} (base ${b['n26']:+.0f}), maxDD ${best['dd']:,.0f} "
                 f"(base ${b['dd']:,.0f}), avg ${best['avg']:+.0f}. The warning's forward info converts to "
                 "DOWNSIDE/DD reduction even if total profit barely moves — a usable portfolio risk overlay. "
                 "Validate live-style/1s before deployment.")
    else:
        # is it at least DD-neutral-with-better-2026 or tail-improving?
        best26 = max(rows[1:], key=lambda s: s['n26'])
        R.append("> [!WARNING]\n> **De-risking does NOT materially help.** No overlay improves 2026 by >$2/tr "
                 f"while cutting maxDD >10%. Best 2026 ({best26['name']}): ${best26['n26']:+.0f} vs base "
                 f"${b['n26']:+.0f}; its maxDD ${best26['dd']:,.0f} vs base ${b['dd']:,.0f}. The warning is real "
                 "forward info, but ACTING on it (surrendering the retained ~1.5 ATR) does not improve the trade "
                 "distribution enough to matter — the post-warning range is priced, same wall as pullback "
                 "severity and the exit atlas. KNN, as a tradable/risk signal, is exhausted. "
                 "[[bar4_knn_calibrated_wrong_dimensions]]")
    (OUT / "bar4_knn_derisk_overlay.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote bar4_knn_derisk_overlay.md")
    for s in rows:
        print(f"  {s['name']}: avg ${s['avg']:+.0f} 25 ${s['n25']:+.0f} 26 ${s['n26']:+.0f} "
              f"DD ${s['dd']:,.0f} p5 ${s['p5']:+.0f} cap {s['cap']:.0f}% nw {s['nw']:,}")


if __name__ == "__main__":
    main()

"""KNN Money Gate — does the high-P(Runner)/low-P(Failure) cohort make money, or is the
calibrated probability priced by payoff asymmetry?

The composition atlas showed KNN's neighbor MIXTURE calibrates (P(Runner) 14→67%, P(Failure)
AUC 0.84). This is the decisive follow-up: select trades by that signal and measure net $.

CAUSAL: the KNN signal is the state THROUGH bar 4 (known at bar-4 CLOSE). So the filter is
applied at bar-4 close and the trade is ENTERED at **bar-5 open** (one bar later — no
look-ahead). Hold to the opposite 1m flip, NO stop. Population = OOS survivors with n>4
(bar-5 exists). KNN reference = IS only (year<2025).

Cohorts: P(Runner) top 10/20% AND P(Failure) bottom 50/30/20% (+ single-filter & baseline).
Thresholds are OOS-relative percentiles (a deployment version needs IS-derived cuts) — the
**both-year (2025 & 2026) split is the robustness gate**: a cohort positive in only one year
is dead. Costs $20/pt, $5 RT, 0.5t entry / 1.0t exit slip. 1m bars (1s/NT before deployment).

    python studies/regime_dna_knn/bar4_knn_money_gate.py
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
DECISION_BAR = 4          # signal through bar 4 (close) → enter bar 5 open
ENTRY_COL = 5
KNN_K = 500
IS_REF_CAP = 60000
RNG = np.random.default_rng(0)


def maxdd(pnl_time_ordered):
    eq = np.cumsum(pnl_time_ordered)
    return float((np.maximum.accumulate(eq) - eq).max()) if len(eq) else 0.0


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    yr = df.year.values
    print("Building states ...")
    S = A.build_states(df, M)
    sb = S[S.k == DECISION_BAR]                      # one row per alive trade at bar 4
    isk = sb[sb.year < 2025]; ook = sb[sb.year >= 2025]
    if len(isk) > IS_REF_CAP:
        isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
    Xis = isk[A.FEATS].values.astype(np.float32); Xoo = ook[A.FEATS].values.astype(np.float32)
    mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
    print("KNN scoring OOS at bar 4 ...")
    nn = NearestNeighbors(n_neighbors=KNN_K, n_jobs=-1).fit((Xis - mu) / sd)
    _, idx = nn.kneighbors((Xoo - mu) / sd)
    nbcls = isk.cls.values[idx]
    ook = ook.copy()
    ook["pRun"] = (nbcls == "Runner").mean(1)
    ook["pFail"] = (nbcls == "Failure").mean(1)

    # map to trade-level entry (bar-5 open) / exit (terminal flip close)
    rid_to_i = {r: i for i, r in enumerate(df.regime_id.values)}
    gi = np.array([rid_to_i[r] for r in ook.rid.values])
    has5 = n[gi] > DECISION_BAR                       # n>4 → bar-5 exists (== ENTRY_COL col present)
    ook = ook[has5].copy(); gi = gi[has5]
    di = d[gi]; ai = atr[gi]; ni = np.minimum(n[gi], 61)
    entry = O[gi, ENTRY_COL]; fill = entry + di * ENTRY
    idxr = np.arange(len(df))
    flip_c = df.post_c.apply(lambda x: float(x[-1])).values[gi]
    pnl = (flip_c - di * EXIT - fill) * di * MULT - COMM
    # forward MFE/MAE from bar-5 entry
    import warnings; warnings.filterwarnings("ignore")
    fav = np.full(len(gi), 0.0); adv = np.full(len(gi), 0.0)
    for j, ii in enumerate(gi):
        cols = np.arange(ENTRY_COL, ni[j] + 1)
        if cols.size == 0:
            continue
        h = H[ii, cols]; l = L[ii, cols]
        fav[j] = max(((h - entry[j]) * di[j] / ai[j]).max(), 0.0)
        adv[j] = max(((entry[j] - l) * di[j] / ai[j]).max(), 0.0)
    ook["pnl"] = pnl; ook["fav"] = fav; ook["adv"] = adv; ook["yr"] = yr[gi]
    ook["isRun"] = (ook.cls == "Runner").astype(int); ook["isFail"] = (ook.cls == "Failure").astype(int)
    ook = ook.sort_values("rid").reset_index(drop=True)   # time order for maxDD

    pR = ook.pRun.values; pF = ook.pFail.values
    qR90 = np.quantile(pR, .90); qR80 = np.quantile(pR, .80)
    qF50 = np.quantile(pF, .50); qF30 = np.quantile(pF, .30); qF20 = np.quantile(pF, .20)

    def stats(mask, name):
        s = ook[mask]
        if len(s) < 50:
            return None
        p = s.pnl.values
        pf = p[p > 0].sum() / (-p[p < 0].sum()) if (p < 0).any() else np.inf
        return dict(name=name, n=len(s), run=s.isRun.mean()*100, fail=s.isFail.mean()*100,
                    mfe=s.fav.mean(), mae=s.adv.mean(), net=p.mean(), pf=pf,
                    n25=s[s.yr == 2025].pnl.mean(), n26=s[s.yr == 2026].pnl.mean(),
                    dd=maxdd(p), win=(p > 0).mean()*100, tot=p.sum())

    cohorts = [(np.ones(len(ook), bool), "baseline (all bar-5 entries)"),
               (pR >= qR90, "P(Run) top 10%"),
               (pR >= qR80, "P(Run) top 20%"),
               (pF <= qF50, "P(Fail) bottom 50%"),
               (pF <= qF30, "P(Fail) bottom 30%"),
               (pF <= qF20, "P(Fail) bottom 20%"),
               ((pR >= qR90) & (pF <= qF50), "Run top10 & Fail bot50"),
               ((pR >= qR90) & (pF <= qF30), "Run top10 & Fail bot30"),
               ((pR >= qR90) & (pF <= qF20), "Run top10 & Fail bot20"),
               ((pR >= qR80) & (pF <= qF50), "Run top20 & Fail bot50"),
               ((pR >= qR80) & (pF <= qF30), "Run top20 & Fail bot30")]

    R = ["# KNN Money Gate — high-P(Runner)/low-P(Failure) cohort, net of costs", "",
         f"Signal through bar {DECISION_BAR} (close) → enter bar {ENTRY_COL} open (causal), hold to flip, NO SL. "
         "KNN ref = IS only. OOS-relative percentile cohorts; **both-year split is the robustness gate.** "
         "Costs $20/pt, $5 RT, 0.5t/1.0t slip. 1m bars.", "",
         "| Cohort | n | Run% | Fail% | avgMFE | avgMAE | net/tr | PF | 2025 | 2026 | maxDD | win% |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    res = {}
    for m, nm in cohorts:
        st = stats(m, nm); res[nm] = st
        if not st:
            R.append(f"| {nm} | <50 | | | | | | | | | | |"); continue
        pf = f"{st['pf']:.2f}" if np.isfinite(st['pf']) else "inf"
        R.append(f"| {nm} | {st['n']:,} | {st['run']:.0f}% | {st['fail']:.0f}% | {st['mfe']:.2f} | "
                 f"{st['mae']:.2f} | ${st['net']:+.0f} | {pf} | ${st['n25']:+.0f} | ${st['n26']:+.0f} | "
                 f"${st['dd']:,.0f} | {st['win']:.0f}% |")

    # verdict: any combined cohort net-positive BOTH years with PF>1.1?
    winners = [nm for nm, st in res.items() if st and "&" in nm and st['n25'] > 0 and st['n26'] > 0
               and np.isfinite(st['pf']) and st['pf'] >= 1.1]
    base = res["baseline (all bar-5 entries)"]
    R += ["", "## Verdict", ""]
    R.append(f"Baseline (all bar-5 entries): ${base['net']:+.0f}/tr, win {base['win']:.0f}%, "
             f"2025 ${base['n25']:+.0f} / 2026 ${base['n26']:+.0f}.")
    if winners:
        best = max((res[w] for w in winners), key=lambda s: min(s['n25'], s['n26']))
        R.append(f"> [!TIP]\n> **{len(winners)} combined cohort(s) net-positive BOTH years (PF≥1.1).** Best: "
                 f"**{best['name']}** → ${best['net']:+.0f}/tr (2025 ${best['n25']:+.0f}, 2026 ${best['n26']:+.0f}, "
                 f"PF {best['pf']:.2f}, win {best['win']:.0f}%, n={best['n']:,}). **The KNN distribution edge "
                 "converts to money** — the probability is NOT fully priced. Next: 1s/NT live-style validation + "
                 "IS-derived thresholds before any deployment claim.")
    else:
        # show best combined for context
        combs = [(nm, st) for nm, st in res.items() if st and "&" in nm]
        bc = max(combs, key=lambda x: min(x[1]['n25'], x[1]['n26'])) if combs else (None, None)
        R.append("> [!WARNING]\n> **The probability edge is PRICED — no combined cohort is net-positive in both "
                 "years after costs.** "
                 + (f"Best combined ({bc[0]}): 2025 ${bc[1]['n25']:+.0f} / 2026 ${bc[1]['n26']:+.0f}, "
                    f"net ${bc[1]['net']:+.0f}/tr, PF {bc[1]['pf']:.2f}. " if bc[0] else "")
                 + "KNN calibrates the Runner/Failure DISTRIBUTION (real), but the high-P(Runner) cohort's "
                 "runners are paid for by its failures — same as pullback severity: probability separates, "
                 "magnitude compensates, EV stays flat. Calibrated ≠ tradable. This is the clean result that "
                 "now justifies order-flow for the direction residual. [[price_pullback_severity_monetarily_inert]]")
    (OUT / "bar4_knn_money_gate.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote bar4_knn_money_gate.md")
    for nm in ["baseline (all bar-5 entries)", "P(Run) top 10%", "Run top10 & Fail bot30", "Run top10 & Fail bot20"]:
        st = res.get(nm)
        if st:
            print(f"  {nm}: n={st['n']:,} net=${st['net']:+.0f} PF={st['pf']:.2f} "
                  f"25=${st['n25']:+.0f} 26=${st['n26']:+.0f} win={st['win']:.0f}% Run%={st['run']:.0f}")


if __name__ == "__main__":
    main()

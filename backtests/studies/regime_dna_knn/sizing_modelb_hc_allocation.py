"""Capital-allocation study: Model B (early failure risk) x hC (trend quality).

NOT entry selection (already shown dead) and NOT a "better model" (KNN/Model B kept
as-is). The question: do pQ and hC combine into a 2D state where SOME causal cohort is
net-positive in BOTH 2025 and 2026 -> i.e. is there anything for a sizing/management
layer to over/under-weight?

STAGE 1 (this script) — pure allocation, hold-to-flip (no intra-trade triggers):
  - Signals decided at bar-4 CLOSE (both known then): pQ = Model B P(QuickFail) thru bar 3;
    hC4 = KNN health at bar 4 (pNH3-pFL3). Causal ENTRY = bar 5 open.
  - Exit = hold to flip, catastrophic stop at flip-bar extreme (a bar-open regime exit,
    the exit class memory marks safe; NO BE/trailing here -> those are trigger exits that
    need 1s/NT and are Stage 2, only worth building if a positive cohort exists).
  - Population = all flips alive at bar 5 (delayed entry => NOT survivor-biased).
  - Thresholds fixed from IS (portable). 2025 and 2026 reported separately.

A 2D cohort EV table is the arbiter. Then the user's size map is applied and booked.
Writes results/sizing_modelb_hc_allocation.md
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors

sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E
import progressive_separability as P
import bar4_knn_path_atlas as A
from rejection_power import MODEL_B, gbm

OUT = Path("studies/regime_dna_knn/results")
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY_SLIP_T = 0.5; EXIT_SLIP_T = 1.0
KNN_K = 500; IS_REF_CAP = 40000
RNG = np.random.default_rng(0)


def main():
    print("Loading...")
    A.BARS = list(range(4, 29))
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    lab = df.label.values
    yr = df.year.values
    npost = df.n_post.values.astype(int)

    # ---------- Model B pQ (causal, features thru bar 3) ----------
    print("Model B P(QuickFail)...")
    XB = P.feats_through(df, M, 3)[MODEL_B].values
    yQ = (lab == "QuickFailure").astype(int)
    alive4 = npost >= 4                      # bar 4 exists (Model B's own population)
    is_m = (yr < 2025) & alive4
    oos_m = (yr >= 2025) & alive4
    pQ = np.full(len(df), np.nan)
    pQ[oos_m] = gbm(XB[is_m], yQ[is_m], XB[oos_m])
    pQ[is_m] = gbm(XB[is_m], yQ[is_m], XB[is_m])      # in-sample, ONLY to set thresholds
    # portable thresholds from IS pQ distribution (terciles)
    q_lo, q_hi = np.nanpercentile(pQ[is_m], [33.3, 66.7])

    # ---------- hC4 (KNN walk-forward, same as prior re-runs) ----------
    print("States + walk-forward KNN for hC4...")
    S = A.build_states(df, M)
    pNH3 = np.full(len(S), np.nan); pFL3 = np.full(len(S), np.nan)
    for year in [2022, 2023, 2024, 2025, 2026]:
        db = S[S.year < year] if year < 2025 else S[S.year < 2025]
        q = S[S.year == year]
        if len(q) == 0 or len(db) < 200:
            continue
        for k in sorted(q.k.unique()):
            isk = db[db.k == k]; om = (S.year == year) & (S.k == k)
            if len(isk) < 100 or om.sum() == 0:
                continue
            if len(isk) > IS_REF_CAP:
                isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
            Xis = isk[A.FEATS].values.astype(np.float32)
            Xoo = S.loc[om, A.FEATS].values.astype(np.float32)
            mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
            nn = NearestNeighbors(n_neighbors=min(KNN_K, len(isk)), n_jobs=-1).fit((Xis - mu) / sd)
            _, idx = nn.kneighbors((Xoo - mu) / sd)
            oi = np.where(om)[0]
            pNH3[oi] = isk.newhigh3.values[idx].mean(1)
            pFL3[oi] = isk.flip3.values[idx].mean(1)
    S["hC"] = pNH3 - pFL3
    hC4 = {r: float(g.hC.values[0]) for r, g in S[(S.k == 4)].groupby("rid")
           if len(g) and not np.isnan(g.hC.values[0])}
    rid = df.regime_id.values
    hc4_arr = np.array([hC4.get(r, np.nan) for r in rid])

    # ---------- per-trade 1-lot PnL: causal bar-5 entry, cat stop, hold-to-flip ----------
    def sim(i, entry_col):
        d_val = df.direction.values[i]; npv = npost[i]
        if npv < entry_col:
            return None
        po = df.post_o.values[i]; pc = df.post_c.values[i]
        ph = df.post_h.values[i]; pl = df.post_l.values[i]
        entry = po[entry_col - 1]                       # bar k = post_o[k-1]
        ef = entry + d_val * ENTRY_SLIP_T * TICK
        stop = (df.flip_l.values[i] - TICK) if d_val == 1 else (df.flip_h.values[i] + TICK)
        ex = None
        for j in range(entry_col, npv + 1):
            bh, bl = ph[j - 1], pl[j - 1]
            if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                ex = stop - d_val * EXIT_SLIP_T * TICK; break
        if ex is None:
            ex = pc[npv - 1] - d_val * EXIT_SLIP_T * TICK
        return (ex - ef) * d_val * MULT - COMM

    pnl5 = np.array([sim(i, 5) if (npost[i] >= 5 and yr[i] >= 2025) else np.nan
                     for i in range(len(df))])
    use = (~np.isnan(pnl5)) & (~np.isnan(hc4_arr)) & (~np.isnan(pQ))

    # buckets
    def pq_bucket(p):
        return "pQ-Low(safe)" if p <= q_lo else ("pQ-High(risk)" if p >= q_hi else "pQ-Mid")
    def hc_bucket(h):
        return "hC-High(>=.5)" if h >= 0.5 else ("hC-Low(<.1)" if h < 0.1 else "hC-Med(.1-.5)")

    rows = []
    for i in np.where(use)[0]:
        rows.append((yr[i], pq_bucket(pQ[i]), hc_bucket(hc4_arr[i]), pnl5[i]))
    A2 = pd.DataFrame(rows, columns=["year", "pq", "hc", "pnl"])

    pq_order = ["pQ-Low(safe)", "pQ-Mid", "pQ-High(risk)"]
    hc_order = ["hC-Low(<.1)", "hC-Med(.1-.5)", "hC-High(>=.5)"]

    def cell(sub):
        s = sub.pnl
        n25 = sub[sub.year == 2025].pnl; n26 = sub[sub.year == 2026].pnl
        return (len(s), s.mean() if len(s) else 0,
                n25.mean() if len(n25) else 0, n26.mean() if len(n26) else 0,
                (len(n25) and len(n26) and n25.mean() > 0 and n26.mean() > 0))

    Lr = ["# Stage 1 — Model B x hC capital-allocation screen (causal, full-universe, bar-5 entry)", ""]
    Lr.append(f"Population alive at bar 5 (OOS): **{use.sum():,}** trades. "
              f"Exit = hold-to-flip + cat-stop (no triggers). pQ thresholds from IS terciles "
              f"(lo={q_lo:.3f}, hi={q_hi:.3f}). hC buckets fixed (<.1 / .1-.5 / >=.5).")
    Lr.append("")
    Lr.append("## 2D cohort EV — net $/tr (the arbiter). ✓ = net-positive in BOTH 2025 and 2026")
    Lr.append("")
    Lr.append("| hC \\ pQ | " + " | ".join(pq_order) + " |")
    Lr.append("| --- | " + " | ".join(["---"] * len(pq_order)) + " |")
    for hb in hc_order:
        cells = []
        for pb in pq_order:
            sub = A2[(A2.pq == pb) & (A2.hc == hb)]
            nN, mAll, m25, m26, ok = cell(sub)
            mark = " ✓" if ok else ""
            cells.append(f"${mAll:+.0f} (n{nN:,}; 25:${m25:+.0f} 26:${m26:+.0f}){mark}")
        Lr.append(f"| **{hb}** | " + " | ".join(cells) + " |")
    Lr.append("")

    # ---------- apply user's size map + book it ----------
    def size_of(pb, hb, zero_high):
        if pb == "pQ-High(risk)":
            return 0.0 if zero_high else 0.5
        if hb == "hC-High(>=.5)" and pb == "pQ-Low(safe)":
            return 1.5
        return 1.0

    Lr.append("## Booked P&L under the size map vs flat size=1")
    Lr.append("")
    Lr.append("| Policy | Year | trades | units cap | net $ | $/unit-cap | flat-1 net $ |")
    Lr.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for zero_high in [False, True]:
        tag = "pQ-High->0.5" if not zero_high else "pQ-High->0"
        sizes = np.array([size_of(p, h, zero_high) for p, h in zip(A2.pq, A2.hc)])
        for y in [2025, 2026]:
            ym = (A2.year == y).values
            booked = (sizes[ym] * A2.pnl.values[ym]).sum()
            units = sizes[ym].sum()
            flat = A2.pnl.values[ym].sum()
            Lr.append(f"| {tag}; hC-High&safe->1.5 | {y} | {ym.sum():,} | {units:,.0f} | "
                      f"${booked:+,.0f} | ${booked/units if units else 0:+.2f} | ${flat:+,.0f} |")
    Lr.append("")

    # best cohort summary
    best = None
    for hb in hc_order:
        for pb in pq_order:
            sub = A2[(A2.pq == pb) & (A2.hc == hb)]
            nN, mAll, m25, m26, ok = cell(sub)
            if nN >= 200 and (best is None or mAll > best[1]):
                best = (f"{hb} x {pb}", mAll, m25, m26, nN, ok)
    Lr.append("## Verdict")
    Lr.append("")
    if best:
        Lr.append(f"- Best cohort (n>=200): **{best[0]}** = ${best[1]:+.0f}/tr "
                  f"(2025 ${best[2]:+.0f}, 2026 ${best[3]:+.0f}, n={best[4]:,}), "
                  f"both-year-positive: **{best[5]}**.")
    any_ok = any(cell(A2[(A2.pq == pb) & (A2.hc == hb)])[4]
                 and len(A2[(A2.pq == pb) & (A2.hc == hb)]) >= 200
                 for pb in pq_order for hb in hc_order)
    Lr.append(f"- Any cohort (n>=200) net-positive in BOTH years: **{any_ok}**.")
    Lr.append("- If False: no allocation/management layer can rescue this — sizing only "
              "scales an across-the-board-negative book; Stage 2 (1s/NT BE+add management) is NOT warranted.")
    (OUT / "sizing_modelb_hc_allocation.md").write_text("\n".join(Lr), encoding="utf-8")
    print("\n".join(Lr))
    print("\nWrote sizing_modelb_hc_allocation.md")


if __name__ == "__main__":
    main()

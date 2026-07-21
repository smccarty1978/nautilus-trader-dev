"""KNN Runner Cohort Exit Atlas — can a better exit convert the runner-rich cohort to PnL?

Money gate found the high-P(Runner)/low-P(Failure) cohort is 61% runners, avg MFE 2.53 ATR,
yet hold-to-flip nets only +$3/tr (PF 1.01, 2025 +15 / 2026 −44). That contradiction (huge
MFE, ~zero PnL) says the EXIT gives back the edge. This tests fixed-PT and scale-out exits
that harvest the runner MFE instead of riding to the flip.

Cohort: P(Runner) top 10% AND P(Failure) bottom 20% (signal thru bar-4 close → enter bar-5
open, causal). PT exits are trigger-based → **1s precision** (memory: 1m PT/BE sign-flips).
PT = limit fill at the level (no favorable slip); no-PT → ride to flip (no SL). Scale-out =
50% at the level, 50% to flip. Costs $20/pt, $5 RT, 0.5t entry / 1.0t exit slip.

Reports per exit: win%, avg $/tr, PF, 2025, 2026, captured-MFE %. Plus the REMAINING-MFE
DISTRIBUTION (p10..p90) of the selected cohort from the bar-5 entry — the "is there meat
left" metric the mean hides.

    python studies/regime_dna_knn/bar4_knn_exit_atlas.py
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
DECISION_BAR = 4; ENTRY_COL = 5
ENTRY_T = ENTRY_COL * 60 * NS - 60 * NS    # bar-5 open = +240s from flip close ((5-1)*60)
KNN_K = 500; IS_REF_CAP = 60000
PTS = [1.0, 1.5, 2.0, 2.5, 3.0]
SCALES = [1.0, 1.5, 2.0]
RNG = np.random.default_rng(0)


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float); yr = df.year.values
    print("Building states + KNN at bar 4 ...")
    S = A.build_states(df, M); sb = S[S.k == DECISION_BAR]
    isk = sb[sb.year < 2025]; ook = sb[sb.year >= 2025]
    if len(isk) > IS_REF_CAP:
        isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
    Xis = isk[A.FEATS].values.astype(np.float32); Xoo = ook[A.FEATS].values.astype(np.float32)
    mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
    nn = NearestNeighbors(n_neighbors=KNN_K, n_jobs=-1).fit((Xis - mu) / sd)
    _, idx = nn.kneighbors((Xoo - mu) / sd)
    nbcls = isk.cls.values[idx]
    ook = ook.copy(); ook["pRun"] = (nbcls == "Runner").mean(1); ook["pFail"] = (nbcls == "Failure").mean(1)
    qR90 = np.quantile(ook.pRun, .90); qF20 = np.quantile(ook.pFail, .20)
    coh = ook[(ook.pRun >= qR90) & (ook.pFail <= qF20)]
    print(f"Cohort (Run top10 & Fail bot20): {len(coh):,}")

    # join 1s paths
    paths = pd.read_parquet(OUT / "survivor_1s_paths.parquet")
    rid2i = {r: i for i, r in enumerate(df.regime_id.values)}
    m = coh.merge(paths[["regime_id", "p1s_t", "p1s_h", "p1s_l", "p1s_c"]],
                  left_on="rid", right_on="regime_id", how="inner")
    m = m[m.rid.map(lambda r: n[rid2i[r]]) > DECISION_BAR]   # bar-5 exists
    print(f"Cohort with 1s path & bar-5: {len(m):,}")

    recs = []
    for r in m.itertuples(index=False):
        ii = rid2i[r.rid]; di = d[ii]; ai = atr[ii]; e = O[ii, ENTRY_COL]
        if not np.isfinite(e):
            continue
        fill = e + di * ENTRY
        t = np.asarray(r.p1s_t, np.int64); sel = t >= ENTRY_T
        T_flip = n[ii] * 60 * NS
        sel &= (t <= T_flip)
        if sel.sum() < 2:
            continue
        h = np.asarray(r.p1s_h)[sel]; l = np.asarray(r.p1s_l)[sel]
        fav_ext = (h - e) * di / ai if di == 1 else (e - l) * di / ai     # favorable each 1s
        mfe = max(fav_ext.max(), 0.0)
        flip_c = float(df.post_c.values[ii][-1])                          # exact terminal close
        rec = dict(rid=r.rid, yr=yr[ii], mfe=mfe, run=int(r.cls == "Runner"))
        # hold-to-flip
        rec["hold"] = (flip_c - di * EXIT - fill) * di * MULT - COMM
        rec["hold_gain"] = (flip_c - di * EXIT - fill) * di / ai          # realized ATR (capture)
        # fixed PT (PT-or-flip, no SL)
        for X in PTS:
            ptpx = fill + di * X * ai
            hit = np.where(h >= ptpx if di == 1 else l <= ptpx)[0]
            if hit.size:
                ex = ptpx; g = X                                          # PT limit, no slip
                rec[f"pt{X}"] = (ex - fill) * di * MULT - COMM
                rec[f"pt{X}_gain"] = X
            else:
                rec[f"pt{X}"] = (flip_c - di * EXIT - fill) * di * MULT - COMM
                rec[f"pt{X}_gain"] = (flip_c - di * EXIT - fill) * di / ai
        # scale-out: 50% @ Y, 50% flip
        for Y in SCALES:
            ptpx = fill + di * Y * ai
            hit = np.where(h >= ptpx if di == 1 else l <= ptpx)[0]
            leg1 = (ptpx - fill) * di * MULT if hit.size else (flip_c - di * EXIT - fill) * di * MULT
            leg2 = (flip_c - di * EXIT - fill) * di * MULT
            rec[f"so{Y}"] = 0.5 * leg1 + 0.5 * leg2 - COMM * 1.5          # 3 fills (entry+2 exits) (audit W2)
            rec[f"so{Y}_gain"] = (0.5 * (Y * ai if hit.size else (flip_c - di * EXIT - fill))
                                  + 0.5 * (flip_c - di * EXIT - fill)) / ai
        recs.append(rec)
    A2 = pd.DataFrame(recs)
    print(f"Simulated: {len(A2):,}")

    def row(col, gaincol, label):
        p = A2[col].values; y = A2.yr.values
        pf = p[p > 0].sum() / (-p[p < 0].sum()) if (p < 0).any() else np.inf
        cap_pct = A2[gaincol].mean() / A2.mfe.mean() * 100 if A2.mfe.mean() > 0 else 0
        return (label, len(p), (p > 0).mean()*100, p.mean(),
                f"{pf:.2f}" if np.isfinite(pf) else "inf",
                p[y == 2025].mean(), p[y == 2026].mean(), cap_pct)

    R = ["# KNN Runner Cohort Exit Atlas (P(Run) top10 & P(Fail) bot20)", "",
         f"Cohort {len(A2):,} trades, entered bar-5 open (causal after bar-4 signal). 1s PT triggers. "
         "PT = limit (no fav slip); no PT → flip; no SL. Costs $20/pt, $5 RT, 0.5t/1.0t slip. "
         f"Cohort avg MFE = **{A2.mfe.mean():.2f} ATR**.", "",
         "## Remaining-MFE distribution from bar-5 entry (the meat left, not the mean)",
         "| p10 | p25 | p50 | p75 | p90 | mean |", "| --- | --- | --- | --- | --- | --- |"]
    q = A2.mfe.quantile([.1, .25, .5, .75, .9]).values
    R.append(f"| {q[0]:.2f} | {q[1]:.2f} | {q[2]:.2f} | {q[3]:.2f} | {q[4]:.2f} | {A2.mfe.mean():.2f} | (ATR)")
    R += ["", "## Exit comparison",
          "| Exit | n | win% | avg $/tr | PF | 2025 | 2026 | captured MFE % |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    rows = [row("hold", "hold_gain", "hold-to-flip")]
    for X in PTS:
        rows.append(row(f"pt{X}", f"pt{X}_gain", f"PT @ {X} ATR"))
    for Y in SCALES:
        rows.append(row(f"so{Y}", f"so{Y}_gain", f"scale 50% @ {Y} + flip"))
    for lab, nn_, w, av, pf, n25, n26, capp in rows:
        R.append(f"| {lab} | {nn_:,} | {w:.0f}% | ${av:+.0f} | {pf} | ${n25:+.0f} | ${n26:+.0f} | {capp:.0f}% |")

    # verdict
    best = None
    for lab, nn_, w, av, pf, n25, n26, capp in rows:
        if n25 > 0 and n26 > 0 and (best is None or av > best[3]):
            best = (lab, nn_, w, av, pf, n25, n26, capp)
    R += ["", "## Verdict", ""]
    if best:
        R.append(f"> [!TIP]\n> **{best[0]} makes the cohort net-positive in BOTH years** — ${best[3]:+.0f}/tr "
                 f"(2025 ${best[5]:+.0f}, 2026 ${best[6]:+.0f}, PF {best[4]}, win {best[2]:.0f}%, captured "
                 f"{best[7]:.0f}% of MFE). The exit, not the signal, was the bottleneck — a better exit converts "
                 "the runner-rich cohort. Next: 1s/NT live-style validation + IS-derived thresholds. KNN is ALIVE.")
    else:
        R.append("> [!WARNING]\n> **No exit makes the cohort net-positive in BOTH years.** Even harvesting the "
                 f"2.53-ATR MFE with fixed PTs, 2026 stays negative — the runner IDENTIFICATION does not hold "
                 "across regimes (2025 vs 2026), so it is not the exit, it is the signal failing out-of-period. "
                 "The cohort's MFE is real but the WHICH-trades-run is a 2025 phenomenon. KNN cohort = dead on "
                 "year-robustness. [[bar4_knn_calibrated_wrong_dimensions]]")
    (OUT / "bar4_knn_exit_atlas.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote bar4_knn_exit_atlas.md")
    for lab, nn_, w, av, pf, n25, n26, capp in rows:
        print(f"  {lab}: win {w:.0f}% avg ${av:+.0f} PF {pf} 25 ${n25:+.0f} 26 ${n26:+.0f} cap {capp:.0f}%")


if __name__ == "__main__":
    main()

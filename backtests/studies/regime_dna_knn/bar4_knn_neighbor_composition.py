"""KNN Neighbor Composition Atlas — is KNN a path-DISTRIBUTION estimator, not just an
average-path estimator?

The path-atlas critique ("rem-MFE point-skill only +5% vs naive") measured POINT accuracy
of the MEAN — blind to dispersion. A neighbor set 50% Runner / 50% Failure has the SAME
mean MFE as a tight cluster at 2.5 ATR, but the bimodality is the whole signal. So instead
of "expected MFE = 2.4", report the neighbor CLASS MIXTURE and test whether it calibrates:

    When KNN says P(Runner)=40%, do 40% actually run?

Uses the SHARED 4-class label from bar4_knn_path_atlas.build_states (cls):
    Failure (mfe<0.5 & (mae>=0.5 or flip<=3)) / Chop (else) / Continuation (mfe>=1.0) /
    Runner (mfe>=2.5 ATR) — total MFE from the Bar-4 entry.

Per OOS Bar-4 (and 5/6/8) state: 500-neighbor class proportions = predicted P(class).
Reports: RELIABILITY of P(Runner)/P(Failure) (predicted bin → actual rate + top-decile
lift), DISPERSION of P(Runner) (does it span above base, or stay pinned?), and BIFURCATION
(states with high P(Runner) AND high P(Failure) — does KNN flag two-sided states?).

Causal (features through bar k; class is a forward LABEL; KNN ref = IS only). 1m diagnostic.

    python studies/regime_dna_knn/bar4_knn_neighbor_composition.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import roc_auc_score
sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E  # noqa: E402
import progressive_separability as P  # noqa: E402
import bar4_knn_path_atlas as A  # noqa: E402  (build_states, FEATS, CLASSES — shared 4-class)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")

BARS_C = [4, 5, 6, 8]
KNN_K = 500
IS_REF_CAP = 50000
OOS_CAP = 25000
CLS4 = A.CLASSES                       # ["Failure","Chop","Continuation","Runner"]
RNG = np.random.default_rng(0)


def reliability(d, pcol, ycol, bins):
    rows = []
    for lo, hi in bins:
        m = (d[pcol] >= lo) & (d[pcol] < hi)
        if m.sum() < 30:
            rows.append((lo, hi, int(m.sum()), np.nan, np.nan)); continue
        rows.append((lo, hi, int(m.sum()), d.loc[m, pcol].mean(), d.loc[m, ycol].mean()))
    return rows


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df)
    print("Building states (shared audited build_states, 4-class) ...")
    S = A.build_states(df, M)
    # per-TRADE base rates (dedupe rid so long trades don't over-weight)
    base = S.drop_duplicates("rid").cls.value_counts(normalize=True)
    print("Per-trade base: " + ", ".join(f"{c} {base.get(c,0)*100:.0f}%" for c in CLS4))

    R = ["# KNN Neighbor Composition Atlas — path-DISTRIBUTION estimation", "",
         "Per OOS state: 500-neighbor class mixture = predicted P(class). Shared 4-class by total MFE "
         "from Bar-4 entry (Runner ≥2.5 / Continuation ≥1.0 / Chop / Failure). The test is RELIABILITY: "
         "when KNN predicts P(Runner)=X, is the actual Runner rate X? And does P(Runner) ever rise "
         "meaningfully above base — i.e., can KNN LOCATE runners, not just average them?", "",
         "Per-trade base rates: " + ", ".join(f"**{c} {base.get(c,0)*100:.0f}%**" for c in CLS4), ""]

    is_all = S[S.year < 2025]; oos_all = S[S.year >= 2025]
    runbins = [(0, .05), (.05, .10), (.10, .15), (.15, .20), (.20, .30), (.30, .50), (.50, 1.01)]
    failbins = [(0, .10), (.10, .20), (.20, .30), (.30, .40), (.40, .50), (.50, .70), (.70, 1.01)]
    summary = {}
    for k in BARS_C:
        isk = is_all[is_all.k == k]; ook = oos_all[oos_all.k == k]
        if len(isk) < 500 or len(ook) < 200:
            continue
        if len(isk) > IS_REF_CAP:
            isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
        if len(ook) > OOS_CAP:
            ook = ook.iloc[RNG.choice(len(ook), OOS_CAP, replace=False)]
        Xis = isk[A.FEATS].values.astype(np.float32); Xoo = ook[A.FEATS].values.astype(np.float32)
        mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
        nn = NearestNeighbors(n_neighbors=KNN_K, n_jobs=-1).fit((Xis - mu) / sd)
        _, idx = nn.kneighbors((Xoo - mu) / sd)
        nbcls = isk.cls.values[idx]; nb_mfe = isk.tot_mfe.values[idx]
        out = ook.copy()
        for c in CLS4:
            out[f"p_{c}"] = (nbcls == c).mean(1)
        out["nb_mfe_std"] = nb_mfe.std(1)
        for c in CLS4:
            out[f"y_{c}"] = (out.cls == c).astype(int)

        def auc(c):
            y = out[f"y_{c}"]
            return roc_auc_score(y, out[f"p_{c}"]) if y.nunique() == 2 else np.nan
        def topdec(c):
            s = out[f"p_{c}"].values; y = out[f"y_{c}"].values
            top = np.argsort(-s)[:max(1, int(len(s) * .1))]
            return y[top].mean(), y.mean()
        summary[k] = dict(aucR=auc("Runner"), aucF=auc("Failure"),
                          tR=topdec("Runner"), tF=topdec("Failure"),
                          pRmax=out.p_Runner.quantile(.99), pRmed=out.p_Runner.median())

        if k == 4:
            R += [f"## Bar 4 — RELIABILITY of P(Runner)  [base {base.get('Runner',0)*100:.0f}%]",
                  "| predicted P(Runner) bin | n | mean predicted | **actual Runner %** |",
                  "| --- | --- | --- | --- |"]
            for lo, hi, nn_, pp, aa in reliability(out, "p_Runner", "y_Runner", runbins):
                R.append(f"| {lo*100:.0f}–{hi*100:.0f}% | {nn_:,} | "
                         f"{(f'{pp*100:.0f}%' if pp==pp else '—')} | "
                         f"{(f'**{aa*100:.0f}%**' if aa==aa else '—')} |")
            R += ["", f"## Bar 4 — RELIABILITY of P(Failure)  [base {base.get('Failure',0)*100:.0f}%]",
                  "| predicted P(Failure) bin | n | mean predicted | **actual Failure %** |",
                  "| --- | --- | --- | --- |"]
            for lo, hi, nn_, pp, aa in reliability(out, "p_Failure", "y_Failure", failbins):
                R.append(f"| {lo*100:.0f}–{hi*100:.0f}% | {nn_:,} | "
                         f"{(f'{pp*100:.0f}%' if pp==pp else '—')} | "
                         f"{(f'**{aa*100:.0f}%**' if aa==aa else '—')} |")
            q = out.p_Runner.quantile([.5, .9, .99, 1.0]).values
            R += ["", "## Bar 4 — DISPERSION of predicted P(Runner)",
                  f"- base {base.get('Runner',0)*100:.0f}%; predicted P(Runner) median {q[0]*100:.0f}%, "
                  f"p90 {q[1]*100:.0f}%, p99 {q[2]*100:.0f}%, max {q[3]*100:.0f}%",
                  f"- → KNN {'DOES' if q[2] > base.get('Runner',0)*2 else 'does NOT'} locate runner-rich "
                  "pockets (p99 vs base)."]
            bif = out[(out.p_Runner >= 0.20) & (out.p_Failure >= 0.30)]
            R += ["", "## Bar 4 — BIFURCATION (P(Runner)≥20% AND P(Failure)≥30%)",
                  f"- {len(bif):,} states ({len(bif)/len(out)*100:.1f}% of Bar-4 OOS)"]
            if len(bif) > 30:
                R.append(f"- actual outcome: Runner {bif.y_Runner.mean()*100:.0f}%, "
                         f"Failure {bif.y_Failure.mean()*100:.0f}%, Chop {(bif.cls=='Chop').mean()*100:.0f}%, "
                         f"Continuation {(bif.cls=='Continuation').mean()*100:.0f}% "
                         f"(base Runner {base.get('Runner',0)*100:.0f}% / Failure {base.get('Failure',0)*100:.0f}%)")
                R.append("- → KNN flags genuinely two-sided states (BOTH tails elevated vs base)."
                         if bif.y_Runner.mean() > base.get('Runner', 0) * 1.5 and bif.y_Failure.mean() > base.get('Failure', 0)
                         else "- → the bifurcation flag does NOT elevate both tails vs base — not a real bimodal detector.")

    R += ["", "## Runner / Failure discrimination by bar (AUC + top-decile lift)",
          "| Bar | AUC Runner | top-10% P(Runner) → actual (base) | AUC Failure | top-10% P(Fail) → actual (base) | P(Runner) p99 |",
          "| --- | --- | --- | --- | --- | --- |"]
    for k in BARS_C:
        s = summary.get(k)
        if s:
            R.append(f"| {k} | {s['aucR']:.2f} | {s['tR'][0]*100:.0f}% ({s['tR'][1]*100:.0f}%) | "
                     f"{s['aucF']:.2f} | {s['tF'][0]*100:.0f}% ({s['tF'][1]*100:.0f}%) | {s['pRmax']*100:.0f}% |")

    s4 = summary.get(4, {})
    tR = s4.get("tR", (0, 1)); run_lift = (tR[0] / tR[1]) if tR[1] else 0
    R += ["", "## Verdict — distribution estimator or not?", ""]
    R.append(f"At Bar 4: AUC Runner {s4.get('aucR', float('nan')):.2f}; top-10%-P(Runner) states actually run "
             f"{tR[0]*100:.0f}% vs base {tR[1]*100:.0f}% (**{run_lift:.1f}× lift**); P(Runner) p99 "
             f"{s4.get('pRmax',0)*100:.0f}%.")
    if run_lift >= 1.8 and s4.get("aucR", 0) >= 0.62:
        R.append("> [!TIP]\n> **KNN IS a path-DISTRIBUTION estimator at the entry bar** — it locates runner-rich "
                 "pockets (top-decile lift + P(Runner) spanning well above base) and the mixture calibrates. The "
                 "earlier 'low rem-MFE point-skill' verdict undersold this: the mean is uninformative, the MIXTURE "
                 "is not. Next: confirm reliability monotonicity, then a size-up / scale-out money gate on the "
                 "high-P(Runner) cohort (1s/NT validated). This reopens KNN.")
    else:
        R.append("> [!WARNING]\n> **Not a usable distribution estimator at the entry bar.** P(Runner) barely "
                 f"separates (AUC {s4.get('aucR', float('nan')):.2f}, top-decile {run_lift:.1f}× lift, p99 "
                 f"{s4.get('pRmax',0)*100:.0f}% vs base {base.get('Runner',0)*100:.0f}%). KNN cannot locate "
                 "runner-rich states from the Bar-4 OHLCV state — the runner-vs-failure bifurcation is not visible "
                 "at the decision point. (Separation sharpens as bars pass = observation.) The mixture confirms "
                 "the same wall as the mean.")
    (OUT / "bar4_knn_neighbor_composition.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote bar4_knn_neighbor_composition.md")
    for k in BARS_C:
        s = summary.get(k)
        if s:
            print(f"  Bar {k}: AUC Runner {s['aucR']:.2f} topR {s['tR'][0]*100:.0f}%({s['tR'][1]*100:.0f}%) | "
                  f"AUC Fail {s['aucF']:.2f} topF {s['tF'][0]*100:.0f}%({s['tF'][1]*100:.0f}%) | pR_p99 {s['pRmax']*100:.0f}%")


if __name__ == "__main__":
    main()

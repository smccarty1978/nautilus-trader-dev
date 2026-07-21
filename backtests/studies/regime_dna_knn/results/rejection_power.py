"""Rejection Power of Pre-Flip (A) and Early-Health (B) models.

NOT "can the model predict launches" — instead: used as a GATEKEEPER, does the
model remove Quick Failures disproportionately faster than it removes Pure Orderly
Launches? Weak AUC is fine; the test is the QF-removed / Launch-removed ratio and
whether the retained universe gets cleaner.

Score per model = goodness S = P(Launch) - P(QuickFail), two walk-forward LightGBM
heads (IS 2021-24 -> OOS 2025-26, no OOS tuning). High S = keep; bottom S = reject.
Uses the LEAK-CORRECTED feats_through (k=Nbar). Model A = pre5 runway only (no
post-flip info). Model B = features through Bar 3.

    python studies/regime_dna_knn/rejection_power.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E  # noqa: E402
import progressive_separability as P  # noqa: E402  (feats_through, build, PRE5)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")

# Model B feature set, exactly per spec ("Use only:")
MODEL_B = ["mfe", "mae", "health", "pullback", "progress_count",
           "close_prog_ratio", "flip_open_viol"] + P.PRE5


def gbm(Xtr, ytr, Xte):
    m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=31,
                           class_weight="balanced", random_state=0, verbose=-1)
    m.fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1]


def goodness(X, is_m, oos_m, yL, yQ):
    """S = P(Launch) - P(QuickFail), trained IS, scored OOS."""
    pL = gbm(X[is_m].values, yL[is_m], X[oos_m].values)
    pQ = gbm(X[is_m].values, yQ[is_m], X[oos_m].values)
    return pL - pQ


def composition_deciles(S, lab):
    dec = pd.qcut(S, 10, labels=False, duplicates="drop") + 1
    rows = []
    for dd in range(1, 11):
        m = dec == dd
        if m.sum() == 0:
            continue
        rows.append((dd, int(m.sum()), (lab[m] == "TradableLaunch").mean() * 100,
                     (lab[m] == "QuickFailure").mean() * 100, (lab[m] == "ChaoticChop").mean() * 100))
    return rows


def rejection_table(S, lab):
    order = np.argsort(S)                    # ascending: worst (lowest S) first
    L = (lab == "TradableLaunch").values; Q = (lab == "QuickFailure").values
    totL = L.sum(); totQ = Q.sum(); N = len(S)
    rows = []
    for q in (0.10, 0.20, 0.30, 0.40):
        k = int(N * q); rem = order[:k]
        qrem = Q[rem].sum() / totQ * 100; lrem = L[rem].sum() / totL * 100
        ratio = qrem / lrem if lrem > 0 else np.inf
        rows.append((q, qrem, lrem, ratio))
    return rows


def retained_table(S, lab):
    order = np.argsort(S); N = len(S)
    rows = []
    base_l = (lab == "TradableLaunch").mean() * 100; base_q = (lab == "QuickFailure").mean() * 100
    rows.append(("baseline (none)", N, base_l, base_q))
    for q in (0.10, 0.20, 0.30, 0.40):
        keep = order[int(N * q):]
        kl = lab.values[keep]
        rows.append((f"drop bottom {int(q*100)}%", len(keep),
                     (kl == "TradableLaunch").mean() * 100, (kl == "QuickFailure").mean() * 100))
    return rows


def preservation_curve(S, lab):
    order = np.argsort(S); N = len(S)
    L = (lab == "TradableLaunch").values; Q = (lab == "QuickFailure").values
    totL = L.sum(); totQ = Q.sum()
    rows = []
    for q in np.arange(0.10, 0.91, 0.10):
        k = int(N * q); rem = order[:k]
        lret = (1 - L[rem].sum() / totL) * 100; qret = (1 - Q[rem].sum() / totQ) * 100
        rows.append((q, lret, qret, lret - qret))
    return rows


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df)
    is_m = (df.year.values < 2025); oos_m = (df.year.values >= 2025)
    yL = df.label.eq("TradableLaunch").values.astype(int)
    yQ = df.label.eq("QuickFailure").values.astype(int)

    XA = P.feats_through(df, M, 0)[P.PRE5]            # Model A: pre5 runway only
    XB = P.feats_through(df, M, 3)[MODEL_B]           # Model B: through bar 3
    SA = goodness(XA, is_m, oos_m, yL, yQ)
    SB = goodness(XB, is_m, oos_m, yL, yQ)
    lab = df.label[oos_m].reset_index(drop=True)
    baseL = (lab == "TradableLaunch").mean() * 100
    baseQ = (lab == "QuickFailure").mean() * 100
    baseC = (lab == "ChaoticChop").mean() * 100

    R = ["# Rejection Power — Pre-Flip (A) & Early-Health (B) models", "",
         f"OOS 2025-26: {len(lab):,} regimes. Base composition: Launch {baseL:.1f}% / "
         f"QuickFail {baseQ:.1f}% / Chop {baseC:.1f}%. Score S = P(Launch) − P(QuickFail), walk-forward "
         "(IS 2021-24 → OOS), leak-corrected features (k=Nbar). High S = keep, bottom S = reject.", "",
         "> [!NOTE]\n> Model A is a PRE-COMMITMENT filter (flip-bar close only, no post-flip info — the true "
         "predictive test). Model B is an EARLY-EXIT filter (you have watched 3 bars); its QuickFail rejection "
         "partly reflects regimes that have ALREADY flipped by bar 3 (observed, not predicted). Read accordingly."]

    for name, S in (("A — Pre-Flip Runway", SA), ("B — Early Health (thru Bar 3)", SB)):
        R += ["", f"## Model {name}", "", "### D1 — Decile composition (decile 1 = lowest S = worst)",
              "| Decile | Count | Launch % | QuickFail % | Chop % |", "| --- | --- | --- | --- | --- |"]
        for dd, c, l, q, ch in composition_deciles(S, lab):
            R.append(f"| {dd} | {c:,} | {l:.1f}% | {q:.1f}% | {ch:.1f}% |")
        R += ["", "### D2 — Rejection power (remove bottom X% by S)",
              "| Removed | % QuickFail removed | % Launch removed | Ratio |", "| --- | --- | --- | --- |"]
        for q, qr, lr, ratio in rejection_table(S, lab):
            tag = " ✅" if ratio >= 1.5 else (" ·" if ratio > 1.0 else " ❌")
            R.append(f"| bottom {int(q*100)}% | {qr:.1f}% | {lr:.1f}% | **{ratio:.2f}**{tag} |")
        R += ["", "### D3 — Retained population quality",
              "| Filter | Trades left | Launch % | QuickFail % |", "| --- | --- | --- | --- |"]
        for f, nl, l, q in retained_table(S, lab):
            R.append(f"| {f} | {nl:,} | {l:.1f}% | {q:.1f}% |")
        R += ["", "### D4 — Launch vs QuickFail retention curve",
              "| % removed | Launch retained % | QuickFail retained % | separation (L−Q) |",
              "| --- | --- | --- | --- |"]
        for q, lret, qret, sep in preservation_curve(S, lab):
            R.append(f"| {int(q*100)}% | {lret:.1f}% | {qret:.1f}% | {sep:+.1f} |")

    # D5 — combined filter (keep high on BOTH)
    R += ["", "## D5 — Combined filter (keep high A AND high B)",
          "| Filter | Trades | Launch % | QuickFail % | Chop % |", "| --- | --- | --- | --- | --- |"]
    R.append(f"| baseline | {len(lab):,} | {baseL:.1f}% | {baseQ:.1f}% | {baseC:.1f}% |")
    for pct in (50, 60, 70):
        ta = np.percentile(SA, pct); tb = np.percentile(SB, pct)
        keep = (SA >= ta) & (SB >= tb)
        kl = lab[keep]
        if len(kl) == 0:
            continue
        R.append(f"| A≥p{pct} & B≥p{pct} | {len(kl):,} | {(kl=='TradableLaunch').mean()*100:.1f}% | "
                 f"{(kl=='QuickFailure').mean()*100:.1f}% | {(kl=='ChaoticChop').mean()*100:.1f}% |")

    # Final verdict
    rejA = rejection_table(SA, lab); rejB = rejection_table(SB, lab)
    a20 = next(r for r in rejA if r[0] == 0.20); b20 = next(r for r in rejB if r[0] == 0.20)
    bestA = max(r[3] for r in rejA); bestB = max(r[3] for r in rejB)
    R += ["", "## Final answer",
          "> **If I reject the bottom X% of regimes by model score, do I eliminate Quick Failures "
          "substantially faster than Pure Orderly Launches?**", ""]
    def verdict(nm, rej, best):
        a = next(r for r in rej if r[0] == 0.20)
        msg = (f"**Model {nm}** — bottom-20% cut removes {a[1]:.0f}% of QuickFails vs {a[2]:.0f}% of Launches "
               f"(ratio {a[3]:.2f}); best ratio across cuts = {best:.2f}. ")
        if best >= 1.5:
            msg += "→ **MEANINGFUL rejection power.**"
        elif best > 1.1:
            msg += "→ weak-but-positive rejection tilt."
        else:
            msg += "→ **NO useful rejection power** (removes losers no faster than winners)."
        return msg
    R.append("> " + verdict("A (pre-flip)", rejA, bestA))
    R.append(">")
    R.append("> " + verdict("B (thru bar 3)", rejB, bestB))
    (OUT / "rejection_power.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote rejection_power.md")
    print(f"Model A best rejection ratio: {bestA:.2f} | bottom-20%: QF {a20[1]:.0f}% / L {a20[2]:.0f}% = {a20[3]:.2f}")
    print(f"Model B best rejection ratio: {bestB:.2f} | bottom-20%: QF {b20[1]:.0f}% / L {b20[2]:.0f}% = {b20[3]:.2f}")


if __name__ == "__main__":
    main()

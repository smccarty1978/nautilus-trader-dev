"""Regime-flip (hold-to-flip) exit: win rate + MFE capture / give-back.

Question: entering early and HOLDING TO THE OPPOSITE REGIME FLIP — do these trades
win, and what % reach >=1 ATR favorable excursion before the flip exits them? The
key diagnostic is GIVE-BACK: of trades that DO reach >=1 ATR MFE, how many still net
lose because the flip exit catches them after the peak.

Two entry interpretations of "enter on bar 3":
  (a) Bar 3 open  — literal; no Model B filter possible (it needs Bar-3 info → leak).
  (b) Bar 4 open  — causal entry AFTER observing Bar 3; the study's entry. Model B
                    QuickFailure-rejection filter is causal here.

Hold-to-flip = exit at the close of the terminal opposite-flip bar (column n), adverse
slip. Costs: $20/pt, $5 RT, 0.5t entry / 1.0t exit slip. OOS 2025-26.

NOTE: MFE/MAE here are 1m-bar excursions (intrabar path unknown) — a trade flagged
">=1 ATR MFE" reached that HIGH at some bar; on 1s/tick the same path may differ. This
is a diagnostic of give-back, not a deployable exit rule.

    python studies/regime_dna_knn/regime_flip_mfe_capture.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E      # noqa: E402
import progressive_separability as P  # noqa: E402
from rejection_power import MODEL_B, gbm  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY = 0.5 * TICK; EXIT = 1.0 * TICK; BMAX = 61
MFE_LEVELS = [0.5, 1.0, 1.5, 2.0]


def flip_pnl(entry_raw, d, C, n):
    idx = np.arange(len(entry_raw)); last = np.minimum(n, BMAX)
    fill = entry_raw + d * ENTRY
    ex = C[idx, last] - d * EXIT
    return (ex - fill) * d * MULT - COMM


def rem_excursion(entry_raw, d, atr, H, L, e):
    """MFE/MAE (ATR) from entry bar e through end of regime (forward only)."""
    import warnings; warnings.filterwarnings("ignore", message="All-NaN slice encountered")
    fav = np.where(d[:, None] == 1, H[:, e:] - entry_raw[:, None], entry_raw[:, None] - L[:, e:])
    adv = np.where(d[:, None] == 1, entry_raw[:, None] - L[:, e:], H[:, e:] - entry_raw[:, None])
    return np.maximum(np.nanmax(fav, axis=1) / atr, 0.0), np.maximum(np.nanmax(adv, axis=1) / atr, 0.0)


def stats(name, pnl, mfe, realized_atr, yy):
    n = len(pnl); win = (pnl > 0).mean() * 100
    hit = {x: (mfe >= x).mean() * 100 for x in MFE_LEVELS}
    # give-back: of trades that reached >=1 ATR MFE, % that still net-lose
    ge1 = mfe >= 1.0
    giveback = (pnl[ge1] <= 0).mean() * 100 if ge1.any() else float("nan")
    n25 = pnl[yy == 2025].mean(); n26 = pnl[yy == 2026].mean()
    return dict(name=name, n=n, win=win, hit=hit, giveback=giveback,
                avg_mfe=mfe.mean(), avg_real=realized_atr.mean(), net=pnl.mean(), n25=n25, n26=n26)


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    yr = df.year.values; lab = df.label.values
    oos = yr >= 2025

    rows = []

    # (a) Bar 3 open entry, unfiltered (n>=3)
    for e, lbl in ((3, "Bar 3 open"), (4, "Bar 4 open")):
        pop = oos & (n >= e)
        gi = np.where(pop)[0]
        er = O[gi, e]
        pnl = flip_pnl(er, d[gi], C[gi], n[gi])
        mfe, mae = rem_excursion(er, d[gi], atr[gi], H[gi], L[gi], e)
        realized_atr = (pnl + COMM) / MULT / atr[gi]  # net pts/atr incl slip (approx realized excursion)
        rows.append(stats(f"{lbl} · hold-to-flip · NO filter", pnl, mfe, realized_atr, yr[gi]))

    # (b) Bar 4 open entry + Model B QuickFail-rejection filter (causal)
    XB = P.feats_through(df, M, 3)[MODEL_B].values
    alive = n >= 4
    is_m = alive & (yr < 2025); oos_m = alive & (yr >= 2025)
    yQ = (lab == "QuickFailure").astype(int)
    pQ = gbm(XB[is_m], yQ[is_m], XB[oos_m])
    gi = np.where(oos_m)[0]
    er = O[gi, 4]; dd = d[gi]; aa = atr[gi]
    pnl_all = flip_pnl(er, dd, C[gi], n[gi])
    mfe_all, _ = rem_excursion(er, dd, aa, H[gi], L[gi], 4)
    real_all = (pnl_all + COMM) / MULT / aa
    order = np.argsort(-pQ); Nt = len(pQ)
    for q in (0.20, 0.40):
        keep = np.sort(order[int(Nt * q):])
        rows.append(stats(f"Bar 4 open · hold-to-flip · reject worst {int(q*100)}% (Model B)",
                          pnl_all[keep], mfe_all[keep], real_all[keep], yr[gi][keep]))

    R = ["# Regime-Flip (Hold-to-Flip) Exit — Win Rate & MFE Capture", "",
         "OOS 2025-26. Exit = close of terminal opposite-flip bar. Costs: $20/pt, $5 RT, 0.5t/1.0t slip.",
         "**Give-back** = of trades reaching ≥1 ATR MFE, the % that STILL net-lose (flip caught them after "
         "the peak). 1m-bar excursions — diagnostic of give-back, not a deployable exit.", "",
         "| Policy | n | Win% | ≥0.5 ATR | ≥1.0 ATR | ≥1.5 ATR | ≥2.0 ATR | give-back@1ATR | avg MFE | avg realized | net/tr | 2025 | 2026 |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in rows:
        h = s["hit"]
        R.append(f"| {s['name']} | {s['n']:,} | {s['win']:.1f}% | {h[0.5]:.1f}% | {h[1.0]:.1f}% | "
                 f"{h[1.5]:.1f}% | {h[2.0]:.1f}% | {s['giveback']:.1f}% | {s['avg_mfe']:.2f} | "
                 f"{s['avg_real']:+.2f} | ${s['net']:+.2f} | ${s['n25']:+.2f} | ${s['n26']:+.2f} |")
    R += ["", "## Read",
          "- **Win%** = does the regime-flip exit win. **≥1.0 ATR** = % that reached ≥1 ATR favorable "
          "before the flip. **give-back@1ATR** = the leak: trades that touched +1 ATR and still lost.",
          "- avg MFE (best excursion reached) vs avg realized (what the flip exit actually banked, ATR) "
          "quantifies how much of the favorable move the flip hands back."]
    (OUT / "regime_flip_mfe_capture.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote regime_flip_mfe_capture.md\n")
    for s in rows:
        print(f"{s['name']}\n  n={s['n']:,} win={s['win']:.1f}%  ≥1ATR MFE={s['hit'][1.0]:.1f}%  "
              f"give-back@1ATR={s['giveback']:.1f}%  net=${s['net']:+.2f}/tr "
              f"(avg MFE {s['avg_mfe']:.2f} vs realized {s['avg_real']:+.2f} ATR)")


if __name__ == "__main__":
    main()

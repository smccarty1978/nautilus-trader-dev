"""KNN Warning-Quality Audit — does the Healthy→Deteriorating warning predict a CHANGE in
the forward path, or merely describe a regime that already looks weak?

The one finding still potentially alive: KNN's predicted class transition CONT→DETER fires
a median ~6 bars before the opposite flip. But lead time alone doesn't prove the warning is
INFORMATIVE — a born-weak regime "warns" early and trivially. The decisive test (per the
critique): compare WARNING states to NON-WARNING states AT THE SAME REGIME AGE.

A warning at bar t is informative ONLY if, vs same-age still-healthy states, it shows:
  - much LOWER P(new high soon), LOWER remaining MFE, SHORTER time to flip.
If warning states still have P(new high)~70% and remaining MFE ~1.8 ATR, the warning is
garbage. If P(new high)~20%, remaining MFE ~0.3, time-to-flip ~5, it found something.

Classes (shared 4-class): healthy = Continuation+Runner ; deteriorating = Failure+Chop.
Warning = first bar predicted DETER after having been predicted CONT (a genuine state
change, not born-weak). Forward outcomes are the ACTUAL values from build_states (causal).
Per-bar KNN, ALL OOS queried (no subsample — need complete per-trade sequences).

    python studies/regime_dna_knn/bar4_knn_warning_quality.py
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
CONT = ("Continuation", "Runner"); DETER = ("Failure", "Chop")
KNN_K = 500; IS_REF_CAP = 40000
RNG = np.random.default_rng(0)


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df)
    print("Building states ...")
    S = A.build_states(df, M)
    is_all = S[S.year < 2025]; oos = S[S.year >= 2025].copy()
    # per-bar KNN: pred_cls for ALL OOS (complete sequences)
    print("Per-bar KNN (all OOS) ...")
    pc = np.empty(len(oos), dtype=object); oos = oos.reset_index(drop=True)
    for k in sorted(oos.k.unique()):
        isk = is_all[is_all.k == k]; om = oos.k == k
        if len(isk) < 200 or om.sum() == 0:
            continue
        if len(isk) > IS_REF_CAP:
            isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
        Xis = isk[A.FEATS].values.astype(np.float32); Xoo = oos.loc[om, A.FEATS].values.astype(np.float32)
        mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
        nn = NearestNeighbors(n_neighbors=min(KNN_K, len(isk)), n_jobs=-1).fit((Xis - mu) / sd)
        _, idx = nn.kneighbors((Xoo - mu) / sd)
        nbc = isk.cls.values[idx]
        from collections import Counter
        pred = []
        for row in nbc:
            c = Counter(row); pred.append(max(c, key=c.get))
        pc[np.where(om.values)[0]] = pred
    oos["pred"] = pc
    oos = oos[oos.pred.notna()].copy()
    oos["is_cont"] = oos.pred.isin(CONT); oos["is_deter"] = oos.pred.isin(DETER)

    # warning bar per trade = first DETER after an earlier CONT
    warn_bar = {}
    for rid, g in oos.sort_values("k").groupby("rid"):
        seen_cont = False; wb = None
        for k, p in zip(g.k.values, g.pred.values):
            if p in CONT:
                seen_cont = True
            elif p in DETER and seen_cont:
                wb = k; break
        if wb is not None:
            warn_bar[rid] = wb
    oos["is_warn"] = [warn_bar.get(r) == k for r, k in zip(oos.rid.values, oos.k.values)]
    n_warn_trades = len(warn_bar)
    print(f"Warning trades (CONT→DETER): {n_warn_trades:,} ({n_warn_trades/oos.rid.nunique()*100:.1f}% of OOS trades)")

    # forward-outcome columns already in S (actual): rem_mfe, rem_mae, rem_bars, newhigh3
    oos["p_half"] = (oos.rem_mfe >= 0.5).astype(int)
    oos["p_one"] = (oos.rem_mfe >= 1.0).astype(int)

    # control = PURE never-warned, still-healthy states: predicted CONT AND the trade never
    # has a CONT→DETER warning anywhere (audit W1 — excludes post-warning CONT flips of
    # warned trades, which would dirty the control and UNDERSTATE warning discrimination).
    warned_rids = set(warn_bar.keys())
    oos["is_ctrl"] = [(p in CONT) and (r not in warned_rids)
                      for r, p in zip(oos.rid.values, oos.pred.values)]

    R = ["# KNN Warning-Quality Audit — does CONT→DETER predict a forward CHANGE?", "",
         f"OOS warning trades (predicted Continuation→then Failure/Chop): **{n_warn_trades:,}** "
         f"({n_warn_trades/oos.rid.nunique()*100:.0f}% of OOS). Forward outcomes are ACTUAL (from "
         "build_states). The test: WARNING states vs same-age still-healthy (predicted-CONT) states. "
         "A useful warning is forward-DEAD relative to its age-matched healthy control.", "",
         "## Warning vs same-age healthy control, by regime age (bar k)",
         "| Bar k | n warn | n healthy | P(new high≤3) warn / healthy | rem MFE warn / healthy | "
         "P(+1 ATR) warn / healthy | time-to-flip warn / healthy |",
         "| --- | --- | --- | --- | --- | --- | --- |"]
    # pooled accumulators (age-weighted by warn n)
    acc = {m: [0.0, 0.0] for m in ("nh", "mfe", "p1", "ttf", "mae", "phalf")}; wtot = 0
    for k in sorted(oos.k.unique()):
        w = oos[(oos.k == k) & oos.is_warn]; h = oos[(oos.k == k) & oos.is_ctrl]
        if len(w) < 30 or len(h) < 30:
            continue
        R.append(f"| {k} | {len(w):,} | {len(h):,} | "
                 f"{w.newhigh3.mean()*100:.0f}% / {h.newhigh3.mean()*100:.0f}% | "
                 f"{w.rem_mfe.mean():.2f} / {h.rem_mfe.mean():.2f} | "
                 f"{w.p_one.mean()*100:.0f}% / {h.p_one.mean()*100:.0f}% | "
                 f"{w.rem_bars.mean():.1f} / {h.rem_bars.mean():.1f} |")
        nw = len(w); wtot += nw
        acc["nh"][0] += w.newhigh3.mean()*nw; acc["nh"][1] += h.newhigh3.mean()*nw
        acc["mfe"][0] += w.rem_mfe.mean()*nw; acc["mfe"][1] += h.rem_mfe.mean()*nw
        acc["p1"][0] += w.p_one.mean()*nw; acc["p1"][1] += h.p_one.mean()*nw
        acc["ttf"][0] += w.rem_bars.mean()*nw; acc["ttf"][1] += h.rem_bars.mean()*nw
        acc["mae"][0] += w.rem_mae.mean()*nw; acc["mae"][1] += h.rem_mae.mean()*nw
        acc["phalf"][0] += w.p_half.mean()*nw; acc["phalf"][1] += h.p_half.mean()*nw

    def ag(m):
        return acc[m][0]/wtot, acc[m][1]/wtot
    nhW, nhH = ag("nh"); mfW, mfH = ag("mfe"); p1W, p1H = ag("p1")
    ttW, ttH = ag("ttf"); maW, maH = ag("mae"); phW, phH = ag("phalf")
    R += ["", "## Pooled (age-matched, weighted by warning count)", "",
          "| metric | WARNING | same-age HEALTHY | warning/healthy |", "| --- | --- | --- | --- |",
          f"| P(new high ≤3 bars) | {nhW*100:.0f}% | {nhH*100:.0f}% | {nhW/max(nhH,1e-9):.2f} |",
          f"| P(+0.5 ATR after) | {phW*100:.0f}% | {phH*100:.0f}% | {phW/max(phH,1e-9):.2f} |",
          f"| P(+1.0 ATR after) | {p1W*100:.0f}% | {p1H*100:.0f}% | {p1W/max(p1H,1e-9):.2f} |",
          f"| remaining MFE (ATR) | {mfW:.2f} | {mfH:.2f} | {mfW/max(mfH,1e-9):.2f} |",
          f"| remaining MAE (ATR) | {maW:.2f} | {maH:.2f} | {maW/max(maH,1e-9):.2f} |",
          f"| time to flip (bars) | {ttW:.1f} | {ttH:.1f} | {ttW/max(ttH,1e-9):.2f} |"]

    # verdict
    nh_ratio = nhW / max(nhH, 1e-9); mfe_ratio = mfW / max(mfH, 1e-9)
    R += ["", "## Verdict", ""]
    R.append(f"Age-matched: warning states make a new high (≤3 bars) {nhW*100:.0f}% vs healthy {nhH*100:.0f}% "
             f"(ratio {nh_ratio:.2f}); remaining MFE {mfW:.2f} vs {mfH:.2f} ATR (ratio {mfe_ratio:.2f}); "
             f"time-to-flip {ttW:.1f} vs {ttH:.1f} bars.")
    if nh_ratio <= 0.6 and mfe_ratio <= 0.6:
        R.append("> [!TIP]\n> **The warning is REAL — it predicts a forward CHANGE.** Age-matched, warning states "
                 "are forward-dead vs still-healthy: far fewer new highs, much less remaining MFE, shorter time "
                 "to flip. This is the one KNN signal that survives a hard attack — it identifies deterioration, "
                 "not just a weak-looking regime. Worth a management overlay (de-risk on warning) gated on 1s/NT.")
    elif nh_ratio <= 0.8 or mfe_ratio <= 0.75:
        R.append("> [!NOTE]\n> **Partial signal.** Warning states are somewhat worse forward than same-age healthy "
                 "(new highs and/or remaining MFE reduced), but not dramatically — and many still run. The warning "
                 "carries SOME forward information but with high reversion. Attack further (reversion rate, money "
                 "overlay) before trusting; not clearly garbage, not clearly actionable.")
    else:
        R.append("> [!WARNING]\n> **The warning is GARBAGE — it describes a weak-looking regime, NOT a forward "
                 f"change.** Age-matched, warning states still make new highs {nhW*100:.0f}% of the time (healthy "
                 f"{nhH*100:.0f}%) with {mfW:.2f} ATR remaining MFE (healthy {mfH:.2f}) — essentially the same "
                 "forward path as same-age still-healthy states. The CONT→DETER transition is the model re-reading "
                 "the same weakness, not predicting deterioration. The 6-bar 'lead' is observation of an already-"
                 "soft regime, not foresight. KNN deterioration signal does not survive the age-matched control.")
    (OUT / "bar4_knn_warning_quality.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote bar4_knn_warning_quality.md")
    print(f"  P(new high) warn {nhW*100:.0f}% vs healthy {nhH*100:.0f}% (ratio {nh_ratio:.2f})")
    print(f"  rem MFE warn {mfW:.2f} vs healthy {mfH:.2f} (ratio {mfe_ratio:.2f}) | ttf {ttW:.1f} vs {ttH:.1f}")


if __name__ == "__main__":
    main()

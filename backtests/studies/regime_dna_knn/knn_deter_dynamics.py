"""DETER Dynamics — is DETER a terminal 'about-to-flip' signal or a recurring low-opportunity
state that recovers? + flip-precursor frequency.

Resolves the tension: DETER showed P(reignite)=72%, rem MFE 1.92 ATR, yet realized htf −$120.
That is "lots of future highs + terrible realized" — needs the transition matrix and a MEANINGFUL
reignite threshold (not 0.05 ATR).

States (priority): DETER (pred=Failure/Chop) > HardStall(hC dd≥.20) > SoftStall(.10-.20) > Healthy.
Adds an absorbing FLIP (regime ends at bar n).

Reports:
  1. Reignite by state at thresholds 0.05 / 0.25 / 0.50 ATR (new high beyond prior MFE peak).
  2. FULL state-transition matrix (4 states → 4 states + Flip), row-normalized.
  3. DETER event analysis: P(flip≤1/3/5/10 from DETER); P(recover to non-DETER before flip);
     DETER episodes per regime; terminal vs recurring; realized $ from DETER bar → flip.
  4. Flip precursor: % of flips with a DETER in the preceding 1/3/5 bars; DETER frequency per regime.
  Verdict: Scenario A (Healthy→DETER→Flip) vs B (recurring Healthy↔DETER→…→Flip).

Causal/descriptive. NO trading logic.

    python studies/regime_dna_knn/knn_deter_dynamics.py
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
STATES = ["Healthy", "SoftStall", "HardStall", "DETER"]
RNG = np.random.default_rng(0)


def main():
    A.BARS = list(range(4, 29))
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    entry4 = O[:, 4]; flip_c = df.post_c.apply(lambda x: float(x[-1])).values
    rididx = {r: i for i, r in enumerate(df.regime_id.values)}
    print("Building states ...")
    S = A.build_states(df, M)
    isS = S[S.year < 2025]; oos = S[S.year >= 2025].reset_index(drop=True)
    print("Per-bar KNN ...")
    from collections import Counter
    pNH3 = np.full(len(oos), np.nan); pFL3 = np.full(len(oos), np.nan); predA = np.empty(len(oos), dtype=object)
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
        pNH3[oi] = isk.newhigh3.values[idx].mean(1); pFL3[oi] = isk.flip3.values[idx].mean(1)
        predA[oi] = [max(Counter(r), key=Counter(r).get) for r in nbc]
    oos["pNH3"] = pNH3; oos["pFL3"] = pFL3; oos["pred"] = predA
    oos = oos[oos.pred.notna()].copy().sort_values(["rid", "k"]).reset_index(drop=True)
    oos["hC"] = oos.pNH3 - oos.pFL3
    g = oos.groupby("rid"); oos["dd"] = 1 - oos.hC / g.hC.cummax().clip(lower=1e-6)
    def cls(row):
        if row.pred in DETER:
            return "DETER"
        if row.dd >= .20:
            return "HardStall"
        if row.dd >= .10:
            return "SoftStall"
        return "Healthy"
    oos["state"] = oos.apply(cls, axis=1)
    oos["nf"] = oos.rid.map(lambda r: n[rididx[r]])
    oos["fl1"] = (oos.rem_bars <= 1).astype(int); oos["fl3"] = (oos.rem_bars <= 3).astype(int)
    oos["fl5"] = (oos.rem_bars <= 5).astype(int); oos["fl10"] = (oos.rem_bars <= 10).astype(int)

    R = ["# DETER Dynamics — terminal flip signal or recurring low-opportunity state?", "",
         f"OOS states: {len(oos):,}. The question: is DETER Scenario A (Healthy→DETER→Flip) or B "
         "(recurring Healthy↔DETER→…→Flip)?", ""]

    # ---- 1. reignite by threshold ----
    R += ["## 1. Reignite by state at MEANINGFUL thresholds (new high ≥X ATR beyond prior MFE peak)",
          "| State | n | reignite ≥0.05 | ≥0.25 | ≥0.50 ATR |", "| --- | --- | --- | --- | --- |"]
    for st in STATES:
        s = oos[oos.state == st]
        if len(s) < 100:
            continue
        r05 = (s.tot_mfe > s.mfe_sofar + 0.05).mean()
        r25 = (s.tot_mfe > s.mfe_sofar + 0.25).mean()
        r50 = (s.tot_mfe > s.mfe_sofar + 0.50).mean()
        R.append(f"| {st} | {len(s):,} | {r05*100:.0f}% | {r25*100:.0f}% | {r50*100:.0f}% |")

    # ---- 2. transition matrix (incl Flip) ----
    nxt = {}  # build next-state per (rid,k)
    seqs = {r: gg for r, gg in oos.groupby("rid")}
    trans = {s: {t: 0 for t in STATES + ["Flip"]} for s in STATES}
    for r, gg in seqs.items():
        ks = gg.k.values; sts = gg.state.values; nf = n[rididx[r]]
        kset = set(ks)
        for j, (k, st) in enumerate(zip(ks, sts)):
            if (k + 1) in kset:
                nx = sts[j + 1] if (j + 1 < len(sts) and ks[j + 1] == k + 1) else None
                if nx is None:
                    # find k+1 in gg
                    w = np.where(ks == k + 1)[0]
                    nx = sts[w[0]] if len(w) else None
            elif k + 1 == nf:                              # next bar = the opposite-flip bar
                nx = "Flip"
            else:
                nx = None                                  # truncated (>28 cap)
            if nx is not None:
                trans[st][nx] += 1
    R += ["", "## 2. State-transition matrix (row → next bar, row-normalized %)",
          "| from \\ to | " + " | ".join(STATES + ["Flip"]) + " | n |",
          "|" + " --- |" * (len(STATES) + 3)]
    for s in STATES:
        tot = sum(trans[s].values())
        if tot == 0:
            continue
        R.append(f"| {s} | " + " | ".join(f"{trans[s][t]/tot*100:.0f}%" for t in STATES + ["Flip"]) + f" | {tot:,} |")

    # ---- 3. DETER event analysis ----
    flip1 = flip3 = flip5 = flip10 = 0; ndet_bars = 0
    recovered = 0; entered_deter = 0; episodes = []; terminal = 0
    realized_to_flip = []
    for r, gg in seqs.items():
        i = rididx[r]; sts = gg.state.values; ks = gg.k.values
        det_mask = sts == "DETER"
        ndet_bars += det_mask.sum()
        # episodes (contiguous DETER runs)
        ep = 0; inep = False
        for j in range(len(sts)):
            if sts[j] == "DETER" and not inep:
                ep += 1; inep = True
            elif sts[j] != "DETER":
                inep = False
        if det_mask.any():
            entered_deter += 1; episodes.append(ep)
            # recover = any non-DETER state AFTER the first DETER bar
            fd = np.where(det_mask)[0][0]
            after = sts[fd + 1:]
            if np.any(np.isin(after, STATES[:-1])):        # any Healthy/Soft/Hard after first DETER
                recovered += 1
            else:
                terminal += 1
            # realized from first DETER bar -> flip
            kb = ks[fd]; di = d[i]
            realized_to_flip.append((flip_c[i] - di * EXIT - (C[i, kb] + di * ENTRY)) * di * MULT - COMM)
        # per-DETER-bar flip timing
        for j in np.where(det_mask)[0]:
            rb = n[i] - ks[j]
            flip1 += rb <= 1; flip3 += rb <= 3; flip5 += rb <= 5; flip10 += rb <= 10
    rt = np.array(realized_to_flip)
    R += ["", "## 3. DETER event analysis",
          f"- DETER bars total: {ndet_bars:,}. Regimes that EVER enter DETER: {entered_deter:,}.",
          f"- **From a DETER bar, P(flip within 1/3/5/10 bars) = {flip1/ndet_bars*100:.0f}% / "
          f"{flip3/ndet_bars*100:.0f}% / {flip5/ndet_bars*100:.0f}% / {flip10/ndet_bars*100:.0f}%.**",
          f"- Of regimes entering DETER: **{recovered/entered_deter*100:.0f}% RECOVER** to a non-DETER state "
          f"before flipping; {terminal/entered_deter*100:.0f}% go terminal (DETER→…→flip, no recovery).",
          f"- DETER EPISODES per regime (among enterers): mean **{np.mean(episodes):.1f}**, median "
          f"{np.median(episodes):.0f}, max {max(episodes)}. → DETER is "
          f"{'RECURRING' if np.mean(episodes) > 1.3 else 'mostly one-time'}.",
          f"- Realized $ from first DETER bar → flip: mean ${rt.mean():+.0f}, median ${np.median(rt):+.0f}, "
          f"win {100*(rt>0).mean():.0f}%."]

    # ---- 4. flip precursor + frequency ----
    flips_with_deter = {1: 0, 3: 0, 5: 0}; nflips = 0; det_per_regime = []; bars_per_regime = []
    for r, gg in seqs.items():
        i = rididx[r]; sts = gg.state.values; ks = gg.k.values; nf = n[i]
        # does the regime's flip have DETER in preceding K bars (bars nf-K .. nf-1)?
        if (nf - 1) in set(ks):                            # we observe the bar before flip
            nflips += 1
            for Kp in (1, 3, 5):
                pre = sts[(ks >= nf - Kp) & (ks <= nf - 1)]
                if np.any(pre == "DETER"):
                    flips_with_deter[Kp] += 1
        det_per_regime.append((sts == "DETER").sum()); bars_per_regime.append(len(sts))
    dpr = np.array(det_per_regime); bpr = np.array(bars_per_regime)
    rate = dpr.sum() / bpr.sum()
    R += ["", "## 4. Flip precursor & DETER frequency",
          f"- Of {nflips:,} flips where we observe the pre-flip bar: preceded by a DETER state within "
          f"1/3/5 bars = **{flips_with_deter[1]/max(nflips,1)*100:.0f}% / {flips_with_deter[3]/max(nflips,1)*100:.0f}% / "
          f"{flips_with_deter[5]/max(nflips,1)*100:.0f}%.**",
          f"- DETER frequency: {rate*100:.0f}% of all active bars are DETER → roughly **1 DETER bar every "
          f"{1/max(rate,1e-9):.1f} bars**. Mean DETER bars per regime {dpr.mean():.1f} over {bpr.mean():.1f} "
          "active bars."]

    # ---- verdict ----
    detr = trans["DETER"]; dtot = sum(detr.values())
    p_flip = detr["Flip"] / dtot if dtot else 0; p_recover = (detr["Healthy"] + detr["SoftStall"] + detr["HardStall"]) / dtot if dtot else 0
    R += ["", "## Verdict — Scenario A (terminal) vs B (recurring)", ""]
    R.append(f"From a DETER bar: next bar → Flip {p_flip*100:.0f}%, → recover/persist non-flip {p_recover*100:.0f}%. "
             f"Of regimes entering DETER, {recovered/entered_deter*100:.0f}% recover before flipping; "
             f"{np.mean(episodes):.1f} DETER episodes/regime.")
    if recovered / entered_deter > 0.5 and np.mean(episodes) > 1.3:
        R.append("> [!TIP]\n> **SCENARIO B — DETER is a RECURRING low-opportunity state, NOT a terminal flip "
                 "signal.** Most DETER-entering regimes recover to a productive state and re-enter DETER multiple "
                 "times before the actual flip. DETER ≈ 'trend is in a low-productivity PHASE right now', not "
                 "'about to die'. This confirms it should be read as LIFECYCLE PHASE information, not an exit "
                 "signal — and explains why exiting on DETER cut the recoveries. The flip is NOT reliably "
                 "DETER-preceded as a discrete event; DETER is too frequent/recurring to be a flip timer.")
    else:
        R.append("> [!NOTE]\n> **Leans Scenario A** — DETER tends to lead directly to flip; it is more terminal "
                 "than recurring. (See numbers above.)")
    (OUT / "knn_deter_dynamics.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote knn_deter_dynamics.md")
    print(f"  reignite DETER: 0.05={ (oos[oos.state=='DETER'].tot_mfe>oos[oos.state=='DETER'].mfe_sofar+0.05).mean()*100:.0f}% "
          f"0.5={ (oos[oos.state=='DETER'].tot_mfe>oos[oos.state=='DETER'].mfe_sofar+0.5).mean()*100:.0f}%")
    print(f"  DETER->Flip next-bar {p_flip*100:.0f}% | recover {recovered/entered_deter*100:.0f}% | episodes/regime {np.mean(episodes):.1f}")
    print(f"  flips preceded by DETER (<=3 bars) {flips_with_deter[3]/max(nflips,1)*100:.0f}% | DETER every {1/max(rate,1e-9):.1f} bars")


if __name__ == "__main__":
    main()

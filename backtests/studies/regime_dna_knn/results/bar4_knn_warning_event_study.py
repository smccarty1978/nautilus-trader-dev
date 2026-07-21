"""Continuous Opportunity-State Trajectory Around KNN Deterioration Warnings (event study).

Control 1 showed the warning is a poor EXECUTION trigger (exiting at it underperforms random
timing). Hypothesis: the warning is not the information itself but a THRESHOLD CROSSING of a
longer opportunity-decay process. This warning-aligned event study (t=0 at the first CONT→DETER
bar; rel bars −10..+10) tests:

  World A (sudden):  opportunity stable until the warning, no precursor.
  World B (gradual): opportunity degrades several bars BEFORE the warning fires.

Metrics per relative bar (aggregated over all warning events), vs a matched CONT control that
never warns within the next 5 bars:
  STATE (KNN):  P(Runner), P(Failure), expected remaining MFE/MAE (neighbor estimates).
  REALIZED:     P(new high ≤1/3/5), remaining realized MFE/MAE, P(flip ≤1/3/5/10).

NO trading / PnL / exit logic — state evolution only. All state metrics use info through that
bar; event alignment is retrospective (does not leak into the causal per-bar metrics); matched
controls are matched on causal features (k, mfe_so_far, mae_so_far) with the forward "no-warning"
condition used ONLY for control membership (by design, not a prediction).

    python studies/regime_dna_knn/bar4_knn_warning_event_study.py
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
RELS = list(range(-10, 11))
RNG = np.random.default_rng(0)


def main():
    A.BARS = list(range(4, 29))          # widen window (catches late-firing warnings w/ deep pre-history)
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    print("Building states (bars 4-28) ...")
    S = A.build_states(df, M)
    is_all = S[S.year < 2025]; oos = S[S.year >= 2025].reset_index(drop=True)
    print("Per-bar KNN (all OOS) ...")
    from collections import Counter
    pred = np.empty(len(oos), dtype=object)
    pRun = np.full(len(oos), np.nan); pFail = np.full(len(oos), np.nan)
    eMFE = np.full(len(oos), np.nan); eMAE = np.full(len(oos), np.nan)
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
        oi = np.where(om)[0]
        pRun[oi] = (nbc == "Runner").mean(1); pFail[oi] = (nbc == "Failure").mean(1)
        eMFE[oi] = isk.rem_mfe.values[idx].mean(1); eMAE[oi] = isk.rem_mae.values[idx].mean(1)
        pred[oi] = [max(Counter(r), key=Counter(r).get) for r in nbc]
    oos["pred"] = pred; oos["pRun"] = pRun; oos["pFail"] = pFail; oos["eMFE"] = eMFE; oos["eMAE"] = eMAE
    oos = oos[oos.pred.notna()].copy()
    rid2i = {r: i for i, r in enumerate(df.regime_id.values)}

    # per-trade: ordered bars, pred; warning bar; DETER bars (for control "no-warn-next-5")
    seqs = {}; wbar = {}; deter_bars = {}
    for rid, g in oos.groupby("rid"):
        g = g.sort_values("k")
        ks = g.k.values; ps = g.pred.values
        seqs[rid] = g
        deter_bars[rid] = set(ks[np.isin(ps, DETER)])
        seen = False
        for k, p in zip(ks, ps):
            if p in CONT:
                seen = True
            elif p in DETER and seen:
                wbar[rid] = k; break
    warned = set(wbar)
    # state lookup: (rid,k) -> row
    oos_ix = {(r, k): i for i, (r, k) in enumerate(zip(oos.rid.values, oos.k.values))}

    def realized(i, k):
        ni = int(min(n[i], 61)); di = d[i]; ai = atr[i]; cnow = C[i, k]
        peak_k = (np.max(H[i, 4:k + 1]) if di == 1 else np.min(L[i, 4:k + 1]))
        out = {}
        for h in (1, 3, 5):
            hi = min(k + h, ni)
            if hi > k:
                fh = H[i, k + 1:hi + 1]; fl = L[i, k + 1:hi + 1]
                out[f"nh{h}"] = int((fh.max() > peak_k) if di == 1 else (fl.min() < peak_k))
            else:
                out[f"nh{h}"] = 0
        for h in (1, 3, 5, 10):
            out[f"fl{h}"] = int((ni - k) <= h)
        hi = ni
        if hi > k:
            fh = H[i, k + 1:hi + 1]; fl = L[i, k + 1:hi + 1]
            if di == 1:
                out["rmfe"] = max(((fh - cnow) / ai).max(), 0.0); out["rmae"] = max(((cnow - fl) / ai).max(), 0.0)
            else:
                out["rmfe"] = max(((cnow - fl) / ai).max(), 0.0); out["rmae"] = max(((fh - cnow) / ai).max(), 0.0)
        else:
            out["rmfe"] = out["rmae"] = 0.0
        return out

    SCOLS = ["pRun", "pFail", "eMFE", "eMAE"]
    RCOLS = ["nh1", "nh3", "nh5", "fl1", "fl3", "fl5", "fl10", "rmfe", "rmae"]

    def build_traj(events):
        """events: list of (rid, k0). Returns dict rel -> dict(metric->mean), and rel->n."""
        acc = {rel: {c: 0.0 for c in SCOLS + RCOLS} for rel in RELS}
        cnt = {rel: 0 for rel in RELS}
        for rid, k0 in events:
            i = rid2i[rid]
            for rel in RELS:
                k = k0 + rel
                ix = oos_ix.get((rid, k))
                if ix is None:
                    continue
                row = oos.iloc[ix]
                rz = realized(i, k)
                for c in SCOLS:
                    acc[rel][c] += row[c]
                for c in RCOLS:
                    acc[rel][c] += rz[c]
                cnt[rel] += 1
        means = {rel: ({c: acc[rel][c] / cnt[rel] for c in SCOLS + RCOLS} if cnt[rel] else {}) for rel in RELS}
        return means, cnt

    warn_events = [(r, wbar[r]) for r in wbar]

    # matched control events: locally-healthy CONT states matched to the warning (k0, mfe_so_far)
    # distribution. (audit W1) Do NOT exclude whole warned-trade histories — that selects
    # tautologically clean-forever trajectories and inflates World B. Instead include a warned
    # trade's EARLY states (>5 bars before its own warning); stable() excludes any state within 5
    # bars of a DETER prediction. So the control = "locally healthy NOW, not about to warn".
    oos["mfe_b"] = (oos.mfe_sofar / 0.5).round() * 0.5
    warn_state_rows = oos[[(r in wbar and wbar[r] == k) for r, k in zip(oos.rid, oos.k)]]
    warn_bins = warn_state_rows.groupby(["k", "mfe_b"]).size()
    def stable(rid, k):
        db = deter_bars.get(rid, set())
        return not any((k + 1) <= b <= (k + 5) for b in db)
    def ctrl_ok(rid, k):
        if not stable(rid, k):
            return False
        if rid in warned and k >= wbar[rid] - 5:     # exclude near/after a warned trade's warning
            return False
        return True
    cand = oos[oos.pred.isin(CONT)].copy()
    cand = cand[[ctrl_ok(r, k) for r, k in zip(cand.rid, cand.k)]]
    ctrl_events = []
    for (k0, mb), need in warn_bins.items():
        pool = cand[(cand.k == k0) & (cand.mfe_b == mb)]
        if len(pool) == 0:
            continue
        take = min(len(pool), int(need))
        pick = pool.iloc[RNG.choice(len(pool), take, replace=False)]
        ctrl_events += list(zip(pick.rid.values, pick.k.values))

    print(f"Warning events {len(warn_events):,} | matched control events {len(ctrl_events):,}")
    wM, wC = build_traj(warn_events)
    cM, cC = build_traj(ctrl_events)

    def fmt(means, cnt, cols, pct=()):
        rows = []
        for rel in RELS:
            if cnt[rel] < 30:
                continue
            cells = []
            for c in cols:
                v = means[rel][c]
                cells.append(f"{v*100:.0f}%" if c in pct else f"{v:.2f}")
            rows.append((rel, cnt[rel], cells))
        return rows

    R = ["# Continuous Opportunity-State Trajectory Around KNN Warnings (event study)", "",
         f"Warning events: {len(warn_events):,}; matched controls: {len(ctrl_events):,}. t=0 is the first "
         "CONT→DETER bar. Relative bars with n<30 omitted. State metrics are KNN neighbor estimates "
         "(causal); realized metrics are forward outcomes. NO trading logic.", "",
         "## Output 1 — Warning-aligned STATE trajectory (KNN)",
         "| Rel | n | P(Runner) | P(Fail) | Exp rem MFE | Exp rem MAE |", "| --- | --- | --- | --- | --- | --- |"]
    for rel, c, cells in fmt(wM, wC, ["pRun", "pFail", "eMFE", "eMAE"], pct=("pRun", "pFail")):
        R.append(f"| {rel:+d} | {c:,} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |")

    R += ["", "## Output 2 — Warning-aligned REALIZED opportunity trajectory",
          "| Rel | n | P(new high ≤1) | ≤3 | ≤5 | rem MFE | P(flip ≤3) |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for rel, c, cells in fmt(wM, wC, ["nh1", "nh3", "nh5", "rmfe", "fl3"], pct=("nh1", "nh3", "nh5", "fl3")):
        R.append(f"| {rel:+d} | {c:,} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {cells[4]} |")

    R += ["", "## Output 3 — Warning vs matched-control trajectory",
          "| Rel | P(Fail) W/C | P(new high ≤3) W/C | rem MFE W/C | P(flip ≤3) W/C |",
          "| --- | --- | --- | --- | --- |"]
    for rel in RELS:
        if wC[rel] < 30 or cC[rel] < 30:
            continue
        w = wM[rel]; cc = cM[rel]
        R.append(f"| {rel:+d} | {w['pFail']*100:.0f}% / {cc['pFail']*100:.0f}% | "
                 f"{w['nh3']*100:.0f}% / {cc['nh3']*100:.0f}% | {w['rmfe']:.2f} / {cc['rmfe']:.2f} | "
                 f"{w['fl3']*100:.0f}% / {cc['fl3']*100:.0f}% |")

    # World A vs B: is opportunity already degrading at t=-1..-3 vs t=-5 (and vs control)?
    def g(rel, c):
        return wM[rel][c] if wC[rel] >= 30 else np.nan
    nh3_m5 = g(-5, "nh3"); nh3_m1 = g(-1, "nh3"); nh3_0 = g(0, "nh3")
    pf_m5 = g(-5, "pFail"); pf_m1 = g(-1, "pFail"); pf_0 = g(0, "pFail")
    # lead time: first rel<0 where warning P(new high ≤3) drops materially below control
    lead = None
    for rel in range(-1, -11, -1):
        if wC[rel] >= 30 and cC[rel] >= 30 and wM[rel]["nh3"] < cM[rel]["nh3"] - 0.10:
            lead = -rel
        else:
            if lead is not None:
                break
    R += ["", "## Decision — World A (sudden) vs World B (continuous decay)", ""]
    R.append(f"P(new high ≤3): t=-5 **{(nh3_m5*100 if nh3_m5==nh3_m5 else float('nan')):.0f}%** → "
             f"t=-1 **{(nh3_m1*100 if nh3_m1==nh3_m1 else float('nan')):.0f}%** → t=0 **{nh3_0*100:.0f}%**. "
             f"P(Fail): t=-5 {(pf_m5*100 if pf_m5==pf_m5 else float('nan')):.0f}% → t=-1 "
             f"{(pf_m1*100 if pf_m1==pf_m1 else float('nan')):.0f}% → t=0 {pf_0*100:.0f}%.")
    gradual = (nh3_m1 == nh3_m1 and nh3_m5 == nh3_m5 and nh3_m1 < nh3_m5 - 0.05) or \
              (pf_m1 == pf_m1 and pf_m5 == pf_m5 and pf_m1 > pf_m5 + 0.05)
    if gradual:
        R.append(f"> [!TIP]\n> **WORLD B — continuous opportunity decay.** Opportunity is already degrading "
                 f"BEFORE the warning fires (new-high prob and/or P(Fail) drift across t=-5→-1). The warning is a "
                 f"THRESHOLD CROSSING of a longer process, which explains why exiting AT it is late. "
                 + (f"Median precursor lead ≈ **{lead} bars** before the warning." if lead else "") +
                 " KNN is an opportunity-state MONITOR, not a discrete exit signal — the actionable variable is "
                 "the continuous decay rate, not the threshold event.")
    else:
        R.append("> [!NOTE]\n> **WORLD A — sudden.** Opportunity is roughly stable until the warning bar, with no "
                 "clear multi-bar precursor in the pre-window. The warning is a discrete state transition.")
    (OUT / "bar4_knn_warning_event_study.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote bar4_knn_warning_event_study.md")
    print(f"  nh3: t-5 {nh3_m5} t-1 {nh3_m1} t0 {nh3_0} | pFail: t-5 {pf_m5} t-1 {pf_m1} t0 {pf_0} | lead {lead}")


if __name__ == "__main__":
    main()

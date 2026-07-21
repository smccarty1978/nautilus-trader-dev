"""Fixed-Cohort Warning Event Study — clean World A vs B (no composition shift).

The prior event study was confounded: each relative bar was a different trade subset
(composition shift), inflating the apparent lead time, and Output-1 P(Fail) was circular
(t=-1 is by definition the last CONT bar, t=0 the first DETER bar). This fixes both:

  COHORT = trades that warned at bar >= K+4 (K=5 → bar>=9), so EVERY member has a full
  t=-5..0 pre-window. Track the SAME set across rel bars → pre-window N is CONSTANT.

  Read World A/B from the REALIZED metrics (new-high, remaining MFE) and KNN's CONTINUOUS
  expected-remaining-MFE (eMFE) — all clean of the CONT/DETER argmax artifact. P(Fail) is
  shown but flagged (still artifact-tied to the argmax at t=-1/0).

  World A (sudden): realized opportunity flat until t=-1, then drops (collapse concentrated
                    in the final 1-2 bars).
  World B (gradual): realized opportunity declines smoothly across t=-5..-1.

Matched control = locally-healthy CONT states (audit-fixed pool) at the cohort's (k0, mfe_b)
distribution, tracked the same way. NO trading logic.

    python studies/regime_dna_knn/bar4_knn_warning_fixed_cohort.py
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
K = 5; MIN_WARN_BAR = 4 + K          # >=9 → full t=-5..0 pre-window
RELS = list(range(-K, 11))
RNG = np.random.default_rng(0)


def main():
    A.BARS = list(range(4, 29))
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
    eMFE = np.full(len(oos), np.nan)
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
        nbc = isk.cls.values[idx]; oi = np.where(om)[0]
        pRun[oi] = (nbc == "Runner").mean(1); pFail[oi] = (nbc == "Failure").mean(1)
        eMFE[oi] = isk.rem_mfe.values[idx].mean(1)
        pred[oi] = [max(Counter(r), key=Counter(r).get) for r in nbc]
    oos["pred"] = pred; oos["pRun"] = pRun; oos["pFail"] = pFail; oos["eMFE"] = eMFE
    oos = oos[oos.pred.notna()].copy()
    rid2i = {r: i for i, r in enumerate(df.regime_id.values)}

    wbar = {}; deter_bars = {}
    for rid, g in oos.groupby("rid"):
        g = g.sort_values("k"); ks = g.k.values; ps = g.pred.values
        deter_bars[rid] = set(ks[np.isin(ps, DETER)])
        seen = False
        for k, p in zip(ks, ps):
            if p in CONT:
                seen = True
            elif p in DETER and seen:
                wbar[rid] = k; break
    warned = set(wbar)
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
        out["fl3"] = int((ni - k) <= 3)
        hi = ni
        if hi > k:
            fh = H[i, k + 1:hi + 1]; fl = L[i, k + 1:hi + 1]
            out["rmfe"] = (max(((fh - cnow) / ai).max(), 0.0) if di == 1 else max(((cnow - fl) / ai).max(), 0.0))
        else:
            out["rmfe"] = 0.0
        return out

    SC = ["pRun", "pFail", "eMFE"]; RC = ["nh1", "nh3", "nh5", "fl3", "rmfe"]

    def traj(events):
        acc = {rel: {c: 0.0 for c in SC + RC} for rel in RELS}; cnt = {rel: 0 for rel in RELS}
        for rid, k0 in events:
            i = rid2i[rid]
            for rel in RELS:
                ix = oos_ix.get((rid, k0 + rel))
                if ix is None:
                    continue
                row = oos.iloc[ix]; rz = realized(i, k0 + rel)
                for c in SC:
                    acc[rel][c] += row[c]
                for c in RC:
                    acc[rel][c] += rz[c]
                cnt[rel] += 1
        return ({rel: ({c: acc[rel][c] / cnt[rel] for c in SC + RC} if cnt[rel] else {}) for rel in RELS}, cnt)

    # COHORT: warnings at bar >= MIN_WARN_BAR (full pre-window)
    warn_events = [(r, wbar[r]) for r in wbar if wbar[r] >= MIN_WARN_BAR]
    # matched controls (audit-fixed pool): locally-healthy, not about to warn, include warned
    # trades' early states; matched to cohort (k0, mfe_b) distribution
    oos["mfe_b"] = (oos.mfe_sofar / 0.5).round() * 0.5
    wsr = oos[[(r in wbar and wbar[r] == k and k >= MIN_WARN_BAR) for r, k in zip(oos.rid, oos.k)]]
    wbins = wsr.groupby(["k", "mfe_b"]).size()
    def stable(rid, k):
        db = deter_bars.get(rid, set()); return not any((k + 1) <= b <= (k + 5) for b in db)
    def ctrl_ok(rid, k):
        if not stable(rid, k):
            return False
        if rid in warned and k >= wbar[rid] - 5:
            return False
        return True
    cand = oos[oos.pred.isin(CONT) & (oos.k >= MIN_WARN_BAR)].copy()
    cand = cand[[ctrl_ok(r, k) for r, k in zip(cand.rid, cand.k)]]
    ctrl_events = []
    for (k0, mb), need in wbins.items():
        pool = cand[(cand.k == k0) & (cand.mfe_b == mb)]
        if len(pool) == 0:
            continue
        pick = pool.iloc[RNG.choice(len(pool), min(len(pool), int(need)), replace=False)]
        ctrl_events += list(zip(pick.rid.values, pick.k.values))

    print(f"Cohort warnings (bar>={MIN_WARN_BAR}): {len(warn_events):,} | matched controls: {len(ctrl_events):,}")
    wM, wC = traj(warn_events); cM, cC = traj(ctrl_events)

    R = ["# Fixed-Cohort Warning Event Study — clean World A vs B", "",
         f"Cohort = warnings at bar ≥{MIN_WARN_BAR} (full t=-{K}..0 pre-window, CONSTANT N): "
         f"**{len(warn_events):,}** trades; matched controls {len(ctrl_events):,}. Same set tracked across rel "
         "bars → no composition shift. Read World A/B from REALIZED metrics + KNN eMFE (clean); P(Fail) flagged "
         "(argmax-tied artifact at t=-1/0). NO trading logic.", "",
         "## Fixed-cohort trajectory (warning) — n constant in the pre-window",
         "| Rel | n | P(new high ≤1) | ≤3 | ≤5 | rem MFE | KNN eMFE | P(Runner) | P(Fail)* |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for rel in RELS:
        if wC[rel] == 0:
            continue
        m = wM[rel]
        R.append(f"| {rel:+d} | {wC[rel]:,} | {m['nh1']*100:.0f}% | {m['nh3']*100:.0f}% | {m['nh5']*100:.0f}% | "
                 f"{m['rmfe']:.2f} | {m['eMFE']:.2f} | {m['pRun']*100:.0f}% | {m['pFail']*100:.0f}% |")
    R.append("")
    R.append("\\* P(Fail) is argmax-tied (t=-1 is the last CONT bar, t=0 the first DETER bar) — not a clean trajectory.")

    R += ["", "## Warning vs matched-control (realized new-high ≤3 & KNN eMFE)",
          "| Rel | new-high≤3 W / C | KNN eMFE W / C | rem MFE W / C |", "| --- | --- | --- | --- |"]
    for rel in RELS:
        if wC[rel] < 20 or cC[rel] < 20:
            continue
        w = wM[rel]; c = cM[rel]
        R.append(f"| {rel:+d} | {w['nh3']*100:.0f}% / {c['nh3']*100:.0f}% | {w['eMFE']:.2f} / {c['eMFE']:.2f} | "
                 f"{w['rmfe']:.2f} / {c['rmfe']:.2f} |")

    # World A/B from the FIXED cohort realized new-high≤3 shape
    nh = {rel: (wM[rel]['nh3'] if wC[rel] else np.nan) for rel in RELS}
    emf = {rel: (wM[rel]['eMFE'] if wC[rel] else np.nan) for rel in RELS}
    total_drop = nh[-K] - nh[0]
    final2_drop = nh[-2] - nh[0] if -2 in nh else np.nan
    frac_final2 = (final2_drop / total_drop) if (total_drop and total_drop > 0.02) else np.nan
    emf_drop = emf[-K] - emf[0]
    R += ["", "## Decision — World A vs World B (fixed cohort, no composition shift)", ""]
    R.append(f"Realized new-high≤3 across the FIXED cohort: " +
             " → ".join(f"t{rel:+d} {nh[rel]*100:.0f}%" for rel in range(-K, 1)) + ".")
    R.append(f"KNN eMFE (continuous): " + " → ".join(f"t{rel:+d} {emf[rel]:.2f}" for rel in range(-K, 1)) +
             f" (drop {emf_drop:+.2f}).")
    R.append(f"Total new-high drop t-{K}→0 = {total_drop*100:+.0f}pp; share in final 2 bars = "
             f"{(frac_final2*100 if frac_final2==frac_final2 else float('nan')):.0f}%.")
    if total_drop < 0.03:
        R.append("> [!NOTE]\n> **Inconclusive / WORLD A-ish** — realized opportunity is roughly flat across the "
                 "fixed-cohort pre-window; the collapse is at the warning bar itself. No clear multi-bar gradual decay.")
    elif frac_final2 == frac_final2 and frac_final2 >= 0.70:
        R.append(f"> [!NOTE]\n> **Mostly WORLD A (concentrated).** {frac_final2*100:.0f}% of the pre-warning "
                 "opportunity drop happens in the final 2 bars — the decay is real but SHORT (1-2 bar precursor), "
                 "not a long gradual process. The 'continuous decay' is mostly a final-bars event.")
    else:
        R.append(f"> [!TIP]\n> **WORLD B (gradual) confirmed clean.** In the FIXED cohort (no composition shift), "
                 f"realized opportunity declines across t=-{K}..0 with only {(frac_final2*100 if frac_final2==frac_final2 else 0):.0f}% "
                 "in the final 2 bars, and KNN eMFE drifts down in parallel. The warning is a genuine threshold "
                 "crossing of a multi-bar opportunity-decay → KNN is an opportunity-state MONITOR; the decay rate "
                 "(not the threshold) is the actionable variable, and it begins measurably before the warning.")
    (OUT / "bar4_knn_warning_fixed_cohort.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote bar4_knn_warning_fixed_cohort.md")
    print(f"  cohort n={len(warn_events):,} | new-high3 " +
          " ".join(f"t{rel:+d}={nh[rel]*100:.0f}%" for rel in range(-K, 1)))
    print(f"  total drop {total_drop*100:+.0f}pp, final-2 share {(frac_final2*100 if frac_final2==frac_final2 else float('nan')):.0f}% | eMFE drop {emf_drop:+.2f}")


if __name__ == "__main__":
    main()

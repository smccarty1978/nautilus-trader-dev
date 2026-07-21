"""KNN Warning — two hard controls + continuation atlas.

The warning survived age-matching + a fair blind-SELECTION control. Three more attacks:

CONTROL 1 — SAME-TRADES, RANDOM-BAR (timing vs selection). Exit the EXACT warned trades, but
at a random bar (matched to the warning-bar distribution) instead of the warning bar. If the
warning-bar exit still beats the random-bar exit on the SAME trades → TIMING skill. If equal →
selection only ("these trades are bad, exit anytime").

CONTROL 2 — SAME-MFE-SO-FAR (beyond pullback severity). Match warning vs not-warning states on
(bars_alive k, mfe_so_far, mae_so_far). If, AT THE SAME visible weakness, warning states still
have lower new-high rate / faster flip / less remaining MFE → the warning sees something BEYOND
the obvious pullback severity. This is the direct test of the mfe-so-far tautology.

ATLAS — WARNING CONTINUATION (opportunity vs direction). Per warning, horizon 1/2/3/5/10:
remaining MFE/MAE, new-high%, flip%. Hypothesis: OPPORTUNITY collapses BEFORE DIRECTION reverses
(new-high dies at h=1 while flip% is still low) — a genuinely different thing from prior studies.

Causal, 1m, reuses audited build_states.

    python studies/regime_dna_knn/bar4_knn_warning_controls.py
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
KNN_K = 500; IS_REF_CAP = 40000; HORIZONS = [1, 2, 3, 5, 10]
RNG = np.random.default_rng(0)


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float); yr = df.year.values
    entry = O[:, 4]; flip_c = df.post_c.apply(lambda x: float(x[-1])).values
    print("Building states ...")
    S = A.build_states(df, M)
    is_all = S[S.year < 2025]; oos = S[S.year >= 2025].reset_index(drop=True)
    print("Per-bar KNN (all OOS) ...")
    from collections import Counter
    pc = np.empty(len(oos), dtype=object)
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
        pc[np.where(om)[0]] = [max(Counter(r), key=Counter(r).get) for r in nbc]
    oos["pred"] = pc; oos = oos[oos.pred.notna()].copy()
    oos["is_cont"] = oos.pred.isin(CONT)

    rid2i = {r: i for i, r in enumerate(df.regime_id.values)}
    seqs = {rid: sorted(zip(g.k, g.pred)) for rid, g in oos.groupby("rid")}
    wbar = {}
    for rid, s in seqs.items():
        seen = False
        for k, p in s:
            if p in CONT:
                seen = True
            elif p in DETER and seen:
                wbar[rid] = k; break
    warned = set(wbar); warn_k = np.array(list(wbar.values()))

    def exit_pnl(i, t):
        di = d[i]; ai = atr[i]; fill = entry[i] + di * ENTRY
        t1 = min(t + 1, int(min(n[i], 61)))
        return (O[i, t1] - di * EXIT - fill) * di * MULT - COMM

    # ===== CONTROL 1: same-trades random-bar (timing) =====
    warn_idx = np.array([rid2i[r] for r in wbar]); warn_t = np.array([wbar[r] for r in wbar])
    wyy = yr[warn_idx]
    pnl_warn = np.array([exit_pnl(i, t) for i, t in zip(warn_idx, warn_t)])
    rand_means = []
    for seed in range(8):
        rg = np.random.default_rng(200 + seed)
        pnl_rand = np.empty(len(warn_idx))
        for j, i in enumerate(warn_idx):
            ni = int(min(n[i], 61))
            choices = warn_k[warn_k < ni]                # matched-distribution bars that exist
            t = rg.choice(choices) if len(choices) else (ni - 1)
            pnl_rand[j] = exit_pnl(i, int(t))
        rand_means.append([pnl_rand.mean(), pnl_rand[wyy == 2025].mean(), pnl_rand[wyy == 2026].mean()])
    rand_m = np.array(rand_means).mean(0)

    R = ["# KNN Warning — Timing & Same-MFE Controls + Continuation Atlas", "",
         f"Warned trades: {len(wbar):,}. Three hard attacks on the deterioration warning.", "",
         "## Control 1 — Same-trades, random-bar (timing vs selection)",
         "Exit the EXACT warned trades at the warning bar vs a random bar drawn from the warning-bar "
         "distribution truncated to each trade's own life (per-trade feasible). Warned-trades-only PnL.", "",
         "| Exit timing | avg/tr (warned trades) | 2025 | 2026 |", "| --- | --- | --- | --- |",
         f"| at WARNING bar | ${pnl_warn.mean():+.0f} | ${pnl_warn[wyy==2025].mean():+.0f} | ${pnl_warn[wyy==2026].mean():+.0f} |",
         f"| at RANDOM bar (8-seed) | ${rand_m[0]:+.0f} | ${rand_m[1]:+.0f} | ${rand_m[2]:+.0f} |",
         "",
         f"→ Warning-bar exit {'BEATS' if pnl_warn.mean() > rand_m[0] + 1 else '≈ / does not beat'} random-bar exit "
         f"on the same trades by ${pnl_warn.mean()-rand_m[0]:+.0f}/tr → "
         f"{'**TIMING skill** (the specific bar matters).' if pnl_warn.mean() > rand_m[0] + 1 else '**SELECTION only** (these trades are bad, exit anytime).'}"]

    # ===== CONTROL 2: same-mfe_sofar matched (beyond pullback severity) =====
    oos["mfe_b"] = (oos.mfe_sofar / 0.5).round() * 0.5
    oos["mae_b"] = (oos.mae_sofar / 0.5).round() * 0.5
    warn_state = oos[[wbar.get(r) == k for r, k in zip(oos.rid, oos.k)]].copy()
    # healthy arm = ALL predicted-CONT bar-states (audit C2-LEAK-1: do NOT exclude entire
    # warned-trade histories — that tautologically picks the cleanest trajectories. A warned
    # trade's PRE-warning CONT bars belong in the healthy arm. The test is predicted-DETER
    # (warning) vs predicted-CONT bar-states at the SAME (k, mfe_so_far, mae_so_far).)
    heal_state = oos[oos.is_cont].copy()
    # match on (k, mfe_b, mae_b); aggregate weighted by warning n per bin
    gW = warn_state.groupby(["k", "mfe_b", "mae_b"]).agg(
        nw=("newhigh3", "size"), nh=("newhigh3", "mean"), fl=("flip3", "mean"), rm=("rem_mfe", "mean"))
    gH = heal_state.groupby(["k", "mfe_b", "mae_b"]).agg(
        nhh=("newhigh3", "mean"), flh=("flip3", "mean"), rmh=("rem_mfe", "mean"), nH=("newhigh3", "size"))
    j = gW.join(gH, how="inner")
    j = j[(j.nw >= 10) & (j.nH >= 10)]
    if len(j):
        w = j.nw.values; tot = w.sum()
        nhW = (j.nh * w).sum() / tot; nhH = (j.nhh * w).sum() / tot
        flW = (j.fl * w).sum() / tot; flH = (j.flh * w).sum() / tot
        rmW = (j.rm * w).sum() / tot; rmH = (j.rmh * w).sum() / tot
        matched_n = int(tot)
    else:
        nhW = nhH = flW = flH = rmW = rmH = np.nan; matched_n = 0
    R += ["", "## Control 2 — Same-MFE-so-far matched (beyond pullback severity)",
          f"Match warning vs healthy states on (bars_alive, mfe_so_far ±0.25, mae_so_far ±0.25). Matched warning "
          f"states: {matched_n:,} (bins with ≥10 each). If warning STILL predicts worse forward at the SAME visible "
          "weakness, it sees beyond pullback severity.", "",
          "| metric (matched) | WARNING | HEALTHY | warn/healthy |", "| --- | --- | --- | --- |",
          f"| P(new high ≤3) | {nhW*100:.0f}% | {nhH*100:.0f}% | {nhW/max(nhH,1e-9):.2f} |",
          f"| P(flip ≤3) | {flW*100:.0f}% | {flH*100:.0f}% | {flW/max(flH,1e-9):.2f} |",
          f"| remaining MFE (ATR) | {rmW:.2f} | {rmH:.2f} | {rmW/max(rmH,1e-9):.2f} |",
          "",
          f"→ At the SAME mfe/mae/age, warning P(new high) is {nhW/max(nhH,1e-9):.2f}× healthy → "
          f"{'**KNN sees BEYOND pullback severity** (the warning adds info the visible weakness does not).' if nhW < nhH*0.85 else 'the warning adds LITTLE beyond visible weakness (mostly re-reads mfe_so_far).'}"]

    # ===== ATLAS: warning continuation, opportunity vs direction =====
    def hmetrics(i, k):
        ni = int(min(n[i], 61)); di = d[i]; ai = atr[i]; cnow = C[i, k]
        peak_k = (np.max(H[i, 4:k + 1]) if di == 1 else np.min(L[i, 4:k + 1]))
        out = {}
        for h in HORIZONS:
            hi = min(k + h, ni)
            if hi <= k:
                out[h] = (0.0, 0.0, 0, 1); continue
            cols = np.arange(k + 1, hi + 1); fh = H[i, cols]; fl = L[i, cols]
            if di == 1:
                fav = fh - cnow; adv = cnow - fl
            else:
                fav = cnow - fl; adv = fh - cnow
            mfe = max((fav / ai).max(), 0.0); mae = max((adv / ai).max(), 0.0)
            nh = int((fh.max() > peak_k) if di == 1 else (fl.min() < peak_k))
            flip = int((ni - k) <= h)
            out[h] = (mfe, mae, nh, flip)
        return out

    wstates = [(rid2i[r], wbar[r]) for r in wbar]
    accW = {h: np.zeros(4) for h in HORIZONS}
    for i, k in wstates:
        m = hmetrics(i, k)
        for h in HORIZONS:
            accW[h] += np.array(m[h])
    cW = len(wstates)
    R += ["", "## Warning Continuation Atlas — opportunity vs direction (warning states)",
          "| horizon | remaining MFE | remaining MAE | new-high % | flip % |", "| --- | --- | --- | --- | --- |"]
    for h in HORIZONS:
        a = accW[h] / cW
        R.append(f"| {h} bar | {a[0]:.2f} | {a[1]:.2f} | {a[2]*100:.0f}% | {a[3]*100:.0f}% |")
    nh1 = accW[1][2] / cW * 100; fl1 = accW[1][3] / cW * 100
    R += ["", f"**Opportunity-vs-direction read:** at h=1, new-high% = **{nh1:.0f}%** (opportunity) while flip% = "
          f"**{fl1:.0f}%** (direction). "
          + ("Opportunity collapses BEFORE direction reverses — the warning marks an OPPORTUNITY-STATE change, "
             "not a reversal. This is a genuinely different signal from prior direction-focused studies."
             if nh1 < 30 and fl1 < 40 else
             "Opportunity and direction move together here — less distinct than hoped.")]

    # verdict
    timing = pnl_warn.mean() > rand_m[0] + 1
    beyond = (nhW == nhW) and nhW < nhH * 0.85
    R += ["", "## Verdict", ""]
    R.append(f"Timing skill: {'YES' if timing else 'NO (selection only)'} (warn-bar ${pnl_warn.mean():+.0f} vs "
             f"random-bar ${rand_m[0]:+.0f}). Beyond-pullback-severity: {'YES' if beyond else 'NO'} "
             f"(same-mfe warning new-high {nhW/max(nhH,1e-9):.2f}× healthy).")
    if beyond:
        R.append("> [!TIP]\n> **The warning carries information BEYOND visible pullback severity** — matched on "
                 "mfe/mae/age, warning states still die faster (fewer new highs, sooner flip). KNN is functioning "
                 "as an **opportunity-state detector**, and opportunity collapses before direction reverses. This "
                 "is the distinct thing the project has been chasing. Now scope order-flow ONLY as the exit/ignore "
                 "arbiter on confirmed-warning states.")
    else:
        R.append("> [!NOTE]\n> **The warning is largely a re-read of visible weakness (mfe_so_far).** Matched on "
                 "the same mfe/mae/age, warning vs healthy forward outcomes converge — the signal is real "
                 "(selection works) but it is mostly the pullback severity we already characterized, not new "
                 "information. Selection skill stands; 'beyond-severity' does not.")
    (OUT / "bar4_knn_warning_controls.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote bar4_knn_warning_controls.md")
    print(f"  C1 timing: warn-bar ${pnl_warn.mean():+.0f} vs random-bar ${rand_m[0]:+.0f} -> {'TIMING' if timing else 'selection-only'}")
    print(f"  C2 same-mfe: warn new-high {nhW*100:.0f}% vs healthy {nhH*100:.0f}% ({nhW/max(nhH,1e-9):.2f}x), "
          f"flip {flW*100:.0f}% vs {flH*100:.0f}%, remMFE {rmW:.2f} vs {rmH:.2f} (matched n={matched_n:,})")
    print(f"  Atlas h=1: new-high {nh1:.0f}% flip {fl1:.0f}%")


if __name__ == "__main__":
    main()

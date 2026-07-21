"""KNN Warning Path Atlas (by horizon) + Blind-Exit Control.

Two questions the de-risk study left open:

PART A — WHAT does the warning mean, by HORIZON? The "1.50 ATR remaining MFE" was LIFETIME
— it hides path shape. Is that 1.50 available IMMEDIATELY (next 1-3 bars) or spread over 12
bars? For each horizon h ∈ {1,2,3,5} bars after the warning, compare WARNING vs same-age
HEALTHY states on: P(new high ≤h), MFE within h, MAE within h, giveback-from-peak within h,
P(flip ≤h). If warning's near-horizon MFE is small + flip prob high + new-high low, the
immediate post-warning path is DEAD (exit/mode-switch is well-timed); if near-horizon MFE is
still large, the warning means "dead eventually," not "dead now".

PART B — BLIND-EXIT CONTROL. Does the warning's DD/avg improvement beat a RANDOM exit of the
same fraction of trades at a matched bar? If random gets the same, the warning is just reduced
exposure (dies). If the warning's avg-improvement beats random, it is SKILL (survives).

Causal: warning = CONT→DETER (KNN pred through bar t); forward metrics are ACTUAL (cols t+1..).
1m bars. Reuses audited build_states.

    python studies/regime_dna_knn/bar4_knn_warning_path_atlas.py
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
KNN_K = 500; IS_REF_CAP = 40000; HORIZONS = [1, 2, 3, 5]
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

    rid2i = {r: i for i, r in enumerate(df.regime_id.values)}
    # warning bar (first DETER after CONT) + never-warned set
    seqs = {rid: sorted(zip(g.k, g.pred)) for rid, g in oos.groupby("rid")}
    wbar = {}
    for rid, s in seqs.items():
        seen = False
        for k, p in s:
            if p in CONT:
                seen = True
            elif p in DETER and seen:
                wbar[rid] = k; break
    warned = set(wbar)

    # ---- PART A: horizon metrics for warning states and healthy (CONT, never-warned) states ----
    def horizon_metrics(i, k):
        ni = int(min(n[i], 61)); di = d[i]; ai = atr[i]; cnow = C[i, k]
        peak_k = (np.max(H[i, 4:k + 1]) if di == 1 else np.min(L[i, 4:k + 1]))
        out = {}
        for h in HORIZONS:
            hi = min(k + h, ni)
            if hi <= k:
                out[h] = (0.0, 0.0, 0.0, 0.0, 1)  # already at end → flip
                continue
            cols = np.arange(k + 1, hi + 1)
            fh = H[i, cols]; fl = L[i, cols]
            if di == 1:                                   # per-direction (audit W1)
                fav = fh - cnow; adv = cnow - fl; gbv = peak_k - fl
            else:
                fav = cnow - fl; adv = fh - cnow; gbv = fh - peak_k
            mfe = max((fav / ai).max(), 0.0)
            mae = max((adv / ai).max(), 0.0)
            nh = int((fh.max() > peak_k) if di == 1 else (fl.min() < peak_k))
            gb = max((gbv / ai).max(), 0.0)
            flip = int((ni - k) <= h)
            out[h] = (nh, mfe, mae, gb, flip)
        return out

    warn_states = [(rid2i[r], wbar[r], yr[rid2i[r]]) for r in wbar]
    heal_states = []
    for rid, s in seqs.items():
        if rid in warned:
            continue
        for k, p in s:
            if p in CONT:
                heal_states.append((rid2i[rid], k, yr[rid2i[rid]]))
    # sample healthy for speed, preserve bar mix roughly
    if len(heal_states) > 60000:
        sel = RNG.choice(len(heal_states), 60000, replace=False)
        heal_states = [heal_states[j] for j in sel]
    print(f"Warning states {len(warn_states):,} | healthy states {len(heal_states):,}")

    def agg_horizon(states):
        # age-weighted by warning bar mix: simple mean here (states already age-distributed)
        acc = {h: np.zeros(5) for h in HORIZONS}; cnt = 0
        byk = {}
        for i, k, y in states:
            m = horizon_metrics(i, k)
            for h in HORIZONS:
                acc[h] += np.array(m[h])
            cnt += 1
        return {h: acc[h] / max(cnt, 1) for h in HORIZONS}, cnt

    # age-match: weight healthy by the warning bar-k distribution
    warn_k = np.array([k for _, k, _ in warn_states])
    kdist = pd.Series(warn_k).value_counts(normalize=True)
    heal_by_k = {}
    for i, k, y in heal_states:
        heal_by_k.setdefault(k, []).append((i, k, y))
    # build age-matched healthy sample matching warn_k distribution
    matched_heal = []
    target = len(warn_states)
    for k, frac in kdist.items():
        pool = heal_by_k.get(k, [])
        if not pool:
            continue
        take = min(len(pool), max(1, int(round(frac * target))))
        idxs = RNG.choice(len(pool), take, replace=False)
        matched_heal += [pool[j] for j in idxs]

    wA, _ = agg_horizon(warn_states)
    hA, _ = agg_horizon(matched_heal)
    R = ["# KNN Warning Path Atlas (by horizon) + Blind-Exit Control", "",
         f"Warning states {len(warn_states):,} vs age-matched healthy {len(matched_heal):,}. Forward metrics "
         "by HORIZON h bars after the (warning / current) bar — reveals if the warning's remaining MFE is "
         "front-loaded or spread out. ACTUAL outcomes, causal.", "",
         "## Part A — Warning vs healthy, by horizon (warn / healthy)",
         "| h bars | P(new high) | MFE within h | MAE within h | giveback-from-peak | P(flip ≤h) |",
         "| --- | --- | --- | --- | --- | --- |"]
    for h in HORIZONS:
        w = wA[h]; hh = hA[h]
        R.append(f"| {h} | {w[0]*100:.0f}% / {hh[0]*100:.0f}% | {w[1]:.2f} / {hh[1]:.2f} | "
                 f"{w[2]:.2f} / {hh[2]:.2f} | {w[3]:.2f} / {hh[3]:.2f} | {w[4]*100:.0f}% / {hh[4]*100:.0f}% |")
    # front-loading read: warning MFE at h=3 vs lifetime ~1.5
    R += ["", f"**Path-shape read:** warning MFE within 3 bars = **{wA[3][1]:.2f} ATR** (healthy {hA[3][1]:.2f}); "
          f"within 5 bars = {wA[5][1]:.2f} (healthy {hA[5][1]:.2f}). Lifetime warning remaining-MFE ≈ 1.50. "
          f"→ the warning's remaining MFE is {'FRONT-LOADED (still pops immediately — exit gives up upside)' if wA[3][1] >= 0.9 else 'SPREAD OUT / near-horizon is quiet (immediate post-warning path is dead — exit/mode-switch well-timed)'}."]

    # ---- PART B: blind-exit control ----
    def fullexit_pnl(exit_bar_map):
        """exit_bar_map: dict rid->t (full exit at t+1 open); others hold to flip."""
        pnl = np.empty(len(seqs)); rids = list(seqs.keys()); yy = np.empty(len(rids))
        for j, rid in enumerate(rids):
            ii = rid2i[rid]; di = d[ii]; ai = atr[ii]; e = entry[ii]; fill = e + di * ENTRY
            yy[j] = yr[ii]
            t = exit_bar_map.get(rid)
            if t is None:
                ex = flip_c[ii] - di * EXIT
            else:
                t1 = min(t + 1, int(min(n[ii], 61)))
                ex = O[ii, t1] - di * EXIT
            pnl[j] = (ex - fill) * di * MULT - COMM
        return pnl, yy, np.array(rids)

    def metrics(pnl, yy, rids):
        order = np.argsort(rids); p = pnl[order]
        dd = float((np.maximum.accumulate(np.cumsum(p)) - np.cumsum(p)).max())
        return p.mean(), p[yy == 2025].mean(), p[yy == 2026].mean(), dd, np.percentile(p, 5)

    base_pnl, byy, brids = fullexit_pnl({})
    warn_pnl, wyy, wrids = fullexit_pnl(wbar)
    bm = metrics(base_pnl, byy, brids); wm = metrics(warn_pnl, wyy, wrids)
    # blind: random trades (= warning count) exited at a bar drawn from warn-k distribution
    # FAIR blind control (audit C1+W2): pool = trades that were CONT at some point but never
    # warned (matches the warning's eligibility — healthy trades); each blind exit at a bar
    # sampled from the warning bar-k distribution, guaranteed to EXIST (n>t), one exit per trade.
    was_cont = {rid for rid, s in seqs.items() if any(p in CONT for _, p in s)}
    blind_pool = np.array(sorted(was_cont - warned))
    pool_n = np.array([n[rid2i[r]] for r in blind_pool])
    kvals, kcounts = np.unique(warn_k, return_counts=True)
    blind_res = []
    for seed in range(5):
        rg = np.random.default_rng(100 + seed)
        bmap = {}; used = set()
        for t, cnt in zip(kvals, kcounts):
            valid = [j for j in np.where(pool_n > t)[0] if blind_pool[j] not in used]
            if not valid:
                continue
            pick = rg.choice(valid, min(cnt, len(valid)), replace=False)
            for j in pick:
                bmap[blind_pool[j]] = int(t); used.add(blind_pool[j])
        bp, byy2, brid2 = fullexit_pnl(bmap)
        blind_res.append(metrics(bp, byy2, brid2))
    blind = np.array(blind_res).mean(0)

    R += ["", "## Part B — Blind-exit control (full exit, warning-count trades, matched bars)",
          "| Strategy | avg/tr | 2025 | 2026 | maxDD | p5 trade |", "| --- | --- | --- | --- | --- | --- |",
          f"| baseline (no exit) | ${bm[0]:+.0f} | ${bm[1]:+.0f} | ${bm[2]:+.0f} | ${bm[3]:,.0f} | ${bm[4]:+.0f} |",
          f"| WARNING full-exit | ${wm[0]:+.0f} | ${wm[1]:+.0f} | ${wm[2]:+.0f} | ${wm[3]:,.0f} | ${wm[4]:+.0f} |",
          f"| BLIND full-exit (5-seed avg) | ${blind[0]:+.0f} | ${blind[1]:+.0f} | ${blind[2]:+.0f} | ${blind[3]:,.0f} | ${blind[4]:+.0f} |"]
    # verdict
    warn_avg_lift = wm[0] - bm[0]; blind_avg_lift = blind[0] - bm[0]
    warn_dd_cut = 1 - wm[3] / bm[3]; blind_dd_cut = 1 - blind[3] / bm[3]
    R += ["", "## Verdict", ""]
    R.append(f"Warning full-exit: avg lift {warn_avg_lift:+.1f}/tr, DD cut {warn_dd_cut*100:.0f}%. "
             f"Blind: avg lift {blind_avg_lift:+.1f}/tr, DD cut {blind_dd_cut*100:.0f}%.")
    if warn_avg_lift > blind_avg_lift + 1.0 and wm[2] > blind[2] + 1.0:
        R.append("> [!TIP]\n> **The warning is SKILL, not just reduced exposure.** It beats a blind exit of the "
                 "same trades/bars on avg AND 2026 — random exits cut DD too (less exposure), but only the "
                 "warning IMPROVES expectancy while doing so. The deterioration signal genuinely selects "
                 "bad-to-hold trades. Combined with Part A's path-shape, KNN survives again. Next: warning as a "
                 "mode-switch gate (Part A tells which mode), and order-flow only as the exit/ignore arbiter.")
    else:
        R.append("> [!WARNING]\n> **The DD reduction is mostly REDUCED EXPOSURE, not skill.** Blind exits match "
                 f"the warning's DD cut (warn {warn_dd_cut*100:.0f}% vs blind {blind_dd_cut*100:.0f}%) and avg "
                 f"(warn {warn_avg_lift:+.1f} vs blind {blind_avg_lift:+.1f}). The warning's apparent benefit is "
                 "largely cutting position, not selecting bad trades. KNN warning, as a risk overlay, does not "
                 "beat random de-risking. [[bar4_knn_calibrated_wrong_dimensions]]")
    (OUT / "bar4_knn_warning_path_atlas.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote bar4_knn_warning_path_atlas.md")
    print(f"  Part A: warn MFE@3 {wA[3][1]:.2f} vs healthy {hA[3][1]:.2f} | warn flip@3 {wA[3][4]*100:.0f}% vs {hA[3][4]*100:.0f}%")
    print(f"  Part B: warn avg lift {warn_avg_lift:+.1f} (DD -{warn_dd_cut*100:.0f}%) | blind {blind_avg_lift:+.1f} (DD -{blind_dd_cut*100:.0f}%)")


if __name__ == "__main__":
    main()

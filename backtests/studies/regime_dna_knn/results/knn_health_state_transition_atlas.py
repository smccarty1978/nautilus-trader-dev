"""Continuous Health State-Transition Atlas — is deterioration a death signal or a pause?

Reframe: KNN as a trade-lifecycle MONITOR (not a winner predictor). Classify each active 1m
bar into a health STATE from hC = P(new_high3) - P(flip3) (best indicator) and its per-trade
drawdown, then study transitions and the decisive question:

  Soft stall / Hard stall / DETER → does it REIGNITE (trend resumes, new high) or TERMINAL-decay
  (straight to the opposite flip)?

States (priority): DETER (pred=Failure/Chop) > HardStall (hC dd≥20%) > SoftStall (10-20%) > Healthy (<10%).
REIGNITE at bar k := the trade makes a NEW favorable high AFTER k (tot_mfe > mfe_so_far[k]) — clean,
per-direction-correct (tot_mfe/mfe_so_far from the bugfixed build_states).

Reports:
  1. State frequency by bar index (flip..Bar4..).
  2. Per state: P(reignite), P(flip≤3/5/10), remaining MFE/MAE, realized hold-to-flip $, median bars-to-resolve.
  3. P(reignite | soft stall) vs P(reignite | hard stall) — the death-vs-pause headline.
  4. State transition counts.
  5. Early-entry sim: enter flip-close / Bar1 / Bar2 / Bar4, NO tight stop, protect to BE only AFTER
     (+0.5 ATR profit AND HardStall/DETER); 1s protective-stop replay (starts bar t+1 open). DD/avg/yr.

Causal; rem_mfe/rem_mae per-direction-fixed. Audit before trust.

    python studies/regime_dna_knn/knn_health_state_transition_atlas.py
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
CONT = ("Continuation", "Runner"); DETER = ("Failure", "Chop")
KNN_K = 500; IS_REF_CAP = 40000
RNG = np.random.default_rng(0)
STATES = ["Healthy", "SoftStall", "HardStall", "DETER"]


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
    g = oos.groupby("rid")
    oos["hC_pk"] = g.hC.cummax()
    oos["dd"] = 1 - oos.hC / oos.hC_pk.clip(lower=1e-6)
    # state (priority): DETER > HardStall(dd>=.20) > SoftStall(.10-.20) > Healthy
    def classify(row):
        if row.pred in DETER:
            return "DETER"
        if row.dd >= 0.20:
            return "HardStall"
        if row.dd >= 0.10:
            return "SoftStall"
        return "Healthy"
    oos["state"] = oos.apply(classify, axis=1)
    # reignite: new favorable high after this bar (tot_mfe > mfe_so_far + eps)
    oos["reignite"] = (oos.tot_mfe > oos.mfe_sofar + 0.05).astype(int)
    oos["fl3"] = (oos.rem_bars <= 3).astype(int); oos["fl5"] = (oos.rem_bars <= 5).astype(int)
    oos["fl10"] = (oos.rem_bars <= 10).astype(int)
    # realized hold-to-flip from Bar-4 entry, per trade (forward outcome by current state)
    htf = {r: (flip_c[i] - d[i]*EXIT - (entry4[i]+d[i]*ENTRY))*d[i]*MULT - COMM for r, i in
           [(r, rididx[r]) for r in oos.rid.unique()]}
    oos["htf"] = oos.rid.map(htf)

    # ---- Report 1+2+3: state atlas ----
    R = ["# Continuous Health State-Transition Atlas", "",
         f"OOS states: {len(oos):,}. State from hC=P(new_high3)-P(flip3) + per-trade drawdown. "
         "REIGNITE = trade makes a new favorable high after this bar. The question: is each stall state a "
         "PAUSE (reignites) or DEATH (terminal flip)?", "",
         "## 1. State frequency by bar index (k = bars since flip; entry=Bar4)",
         "| bar k | " + " | ".join(STATES) + " | n |", "|" + " --- |" * (len(STATES) + 2)]
    for k in range(4, 16):
        s = oos[oos.k == k]
        if len(s) < 100:
            continue
        fr = s.state.value_counts(normalize=True)
        R.append(f"| {k} | " + " | ".join(f"{fr.get(st,0)*100:.0f}%" for st in STATES) + f" | {len(s):,} |")

    R += ["", "## 2+3. Per-state forward outcomes — PAUSE vs DEATH",
          "| State | n | **P(reignite)** | P(flip≤3) | P(flip≤5) | P(flip≤10) | rem MFE | rem MAE | realized htf $ | med bars→flip |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for st in STATES:
        s = oos[oos.state == st]
        if len(s) < 100:
            continue
        R.append(f"| {st} | {len(s):,} | **{s.reignite.mean()*100:.0f}%** | {s.fl3.mean()*100:.0f}% | "
                 f"{s.fl5.mean()*100:.0f}% | {s.fl10.mean()*100:.0f}% | {s.rem_mfe.mean():.2f} | "
                 f"{s.rem_mae.mean():.2f} | ${s.htf.mean():+.0f} | {s.rem_bars.median():.0f} |")
    R.append("")
    rs = {st: oos[oos.state == st].reignite.mean() for st in STATES}
    R.append(f"**Death-vs-pause headline:** P(reignite) — Healthy {rs['Healthy']*100:.0f}% · "
             f"SoftStall {rs['SoftStall']*100:.0f}% · HardStall {rs['HardStall']*100:.0f}% · DETER {rs['DETER']*100:.0f}%.")

    # ---- Report 4: transitions (consecutive states per trade) ----
    trans = {}
    for rid, gg in oos.groupby("rid"):
        st = gg.state.values
        for a, b in zip(st, st[1:]):
            trans[(a, b)] = trans.get((a, b), 0) + 1
    R += ["", "## 4. State transitions (consecutive bars, counts)", "| from → to | count |", "| --- | --- |"]
    for (a, b), c in sorted(trans.items(), key=lambda x: -x[1])[:14]:
        R.append(f"| {a} → {b} | {c:,} |")
    (OUT / "knn_health_state_atlas.md").write_text("\n".join(R), encoding="utf-8")

    # ---- Report 5: early-entry simulation ----
    paths = pd.read_parquet(OUT / "survivor_1s_paths.parquet")
    p1s = {r: (np.asarray(t, np.int64), np.asarray(h), np.asarray(l)) for r, t, h, l in
           zip(paths.regime_id.values, paths.p1s_t.values, paths.p1s_h.values, paths.p1s_l.values)}
    # per-trade: first bar (k>=4) where open_profit(from given entry)>=0.5 AND state in (HardStall,DETER)
    state_by = {(r, k): st for r, k, st in zip(oos.rid.values, oos.k.values, oos.state.values)}
    bars_by = {r: gg.k.values for r, gg in oos.groupby("rid")}
    ENTRIES = {"flip-close": ("flip", 0), "Bar1": ("col", 1), "Bar2": ("col", 2), "Bar4": ("col", 4)}

    def entry_px(i, kind, col):
        if kind == "flip":
            return float(df.flip_c.values[i])
        return O[i, col]

    def sim(entry_name, protect):
        kind, col = ENTRIES[entry_name]
        rids = []; pnls = []; yrs = []
        for r in oos.rid.unique():
            i = rididx[r]; di = d[i]; ai = atr[i]; ni = int(min(n[i], 61))
            if col > ni:
                continue
            e = entry_px(i, kind, col); fill = e + di * ENTRY
            held_flip = (flip_c[i] - di * EXIT - fill) * di * MULT - COMM
            if not protect:
                pnls.append(held_flip); rids.append(r); yrs.append(df.year.values[i]); continue
            # find protection trigger: first k>=4 with open_profit>=0.5 ATR AND state Hard/DETER
            tb = None
            for k in bars_by.get(r, []):
                if k < 4 or k > ni:
                    continue
                op = (C[i, k] - e) * di / ai
                stt = state_by.get((r, k))
                if op >= 0.5 and stt in ("HardStall", "DETER"):
                    tb = k; break
            if tb is None:
                pnls.append(held_flip); rids.append(r); yrs.append(df.year.values[i]); continue
            # protective stop to BE (=entry e); 1s replay from bar tb+1 open (=tb*60s offset)
            stop = e
            if r in p1s:
                toff = tb * 60 * NS; T_flip = n[i] * 60 * NS
                ts, hh, ll = p1s[r]; sel = (ts >= toff) & (ts <= T_flip)
                hit = False
                for hv, lv in zip(hh[sel], ll[sel]):
                    if (di == 1 and lv <= stop) or (di == -1 and hv >= stop):
                        pnls.append((stop - di * EXIT - fill) * di * MULT - COMM); hit = True; break
                if not hit:
                    pnls.append(held_flip)
            else:
                pnls.append(held_flip)
            rids.append(r); yrs.append(df.year.values[i])
        p = np.array(pnls); y = np.array(yrs)
        order = np.argsort([rididx[r] for r in rids]); pp = p[order]
        dd = float((np.maximum.accumulate(np.cumsum(pp)) - np.cumsum(pp)).max())
        return p.mean(), p[y == 2025].mean(), p[y == 2026].mean(), dd, np.percentile(p, 5), len(p)

    R5 = ["# Early-Entry Simulation with KNN Health Monitor", "",
         "Enter at flip-close / Bar1 / Bar2 / Bar4, NO tight stop. 'Protected' = move stop to BE only after "
         "(+0.5 ATR open profit AND HardStall/DETER state), 1s replay (starts bar t+1 open). The question: can "
         "the monitor keep you out of chop while letting runners develop, vs naive hold-to-flip?", "",
         "| Entry | mode | avg/tr | 2025 | 2026 | maxDD | p5 trade | n |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for en in ENTRIES:
        for mode, pr in (("hold-to-flip", False), ("protect@profit+stall", True)):
            a, n25, n26, dd, p5, nn_ = sim(en, pr)
            R5.append(f"| {en} | {mode} | ${a:+.0f} | ${n25:+.0f} | ${n26:+.0f} | ${dd:,.0f} | ${p5:+.0f} | {nn_:,} |")
    (OUT / "knn_health_early_entry.md").write_text("\n".join(R5), encoding="utf-8")

    print("Done.")
    print(f"  P(reignite): " + " ".join(f"{st} {rs[st]*100:.0f}%" for st in STATES))
    for en in ("flip-close", "Bar4"):
        a0, _, _, dd0, _, _ = sim(en, False); a1, _, _, dd1, _, _ = sim(en, True)
        print(f"  {en}: hold ${a0:+.0f}/DD${dd0:,.0f} | protect ${a1:+.0f}/DD${dd1:,.0f}")


if __name__ == "__main__":
    main()

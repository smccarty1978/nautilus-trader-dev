"""Does a CAUSAL delayed-entry filter make money?

User question: if we filter at ~bar 3 and only enter survivors at bar 4, is it profitable?

Delayed entry removes the n_post<4 survivor bias (trades that die before entry are
simply never taken). The remaining questions are (a) temporal consistency and (b)
whether the hC filter adds edge over just-delaying-entry.

We test the fully CAUSAL version:
  - filter signal = hC at bar 4 close (earliest hC available)
  - ENTRY = bar 5 open  (so the filter uses only info known before entry; no 1-bar leak)
  - exit  = hold to flip (terminal post close), catastrophic stop at flip-bar extreme
  - population = all flips with n_post >= 5 (i.e. alive at the entry bar) -> NOT survivor-biased

Reported: unfiltered delayed entry, then hC>=t sweep, IS (2022-24) vs OOS (2025-26).
Also an OPTIMISTIC reference: enter bar 4 open using hC4 (1-bar look-ahead) to bound the gap.
Writes results/revalidate_delayed_entry_filter.md
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors

sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E
import progressive_separability as P
import bar4_knn_path_atlas as A

OUT = Path("studies/regime_dna_knn/results")
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY_SLIP_T = 0.5; EXIT_SLIP_T = 1.0
KNN_K = 500; IS_REF_CAP = 40000
RNG = np.random.default_rng(0)


def main():
    print("Loading...")
    A.BARS = list(range(4, 29))
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    rididx = {r: i for i, r in enumerate(df.regime_id.values)}

    print("States + walk-forward KNN...")
    S = A.build_states(df, M)
    pNH3 = np.full(len(S), np.nan); pFL3 = np.full(len(S), np.nan)
    for year in [2022, 2023, 2024, 2025, 2026]:
        db = S[S.year < year] if year < 2025 else S[S.year < 2025]
        q = S[S.year == year]
        if len(q) == 0 or len(db) < 200:
            continue
        for k in sorted(q.k.unique()):
            isk = db[db.k == k]; om = (S.year == year) & (S.k == k)
            if len(isk) < 100 or om.sum() == 0:
                continue
            if len(isk) > IS_REF_CAP:
                isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
            Xis = isk[A.FEATS].values.astype(np.float32)
            Xoo = S.loc[om, A.FEATS].values.astype(np.float32)
            mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
            nn = NearestNeighbors(n_neighbors=min(KNN_K, len(isk)), n_jobs=-1).fit((Xis - mu) / sd)
            _, idx = nn.kneighbors((Xoo - mu) / sd)
            oi = np.where(om)[0]
            pNH3[oi] = isk.newhigh3.values[idx].mean(1)
            pFL3[oi] = isk.flip3.values[idx].mean(1)
    S["hC"] = pNH3 - pFL3
    hC4 = {}
    for r, gg in S[S.k == 4].groupby("rid"):
        v = gg.hC.values
        if len(v) and not np.isnan(v[0]):
            hC4[r] = float(v[0])

    def sim(row, entry_col):
        d_val = row["direction"]; n_post_val = int(row["n_post"])
        post_o = list(row["post_o"]); post_c = list(row["post_c"])
        if n_post_val < entry_col:        # entry bar must exist
            return None
        entry = post_o[entry_col - 1]      # post_o[0]=bar1 -> bar k = index k-1
        entry_fill = entry + d_val * ENTRY_SLIP_T * TICK
        stop = (row["flip_l"] - TICK) if d_val == 1 else (row["flip_h"] + TICK)
        post_h = list(row["post_h"]); post_l = list(row["post_l"])
        exit_px = None
        for j in range(entry_col, n_post_val + 1):
            bh, bl = post_h[j - 1], post_l[j - 1]
            if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                exit_px = stop - d_val * EXIT_SLIP_T * TICK; break
        if exit_px is None:
            exit_px = post_c[n_post_val - 1] - d_val * EXIT_SLIP_T * TICK
        return (exit_px - entry_fill) * d_val * MULT - COMM

    rows = df.to_dict("records")
    yrs = df.year.values

    def run(entry_col, label):
        recs = []
        for r in rows:
            rid = r["regime_id"]
            pnl = sim(r, entry_col)
            if pnl is None:
                continue
            recs.append((rid, r["year"], pnl, hC4.get(rid, np.nan)))
        a = pd.DataFrame(recs, columns=["rid", "year", "pnl", "hc4"])
        out = []
        thresholds = [("ALL (no filter)", None)] + [(f"hC4>={t}", t) for t in
                                                    [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]]
        for name, t in thresholds:
            sub = a if t is None else a[a.hc4 >= t]
            row_out = {"rule": name}
            for tag, mask in [("IS", sub.year < 2025), ("OOS", sub.year >= 2025)]:
                sp = sub.pnl[mask].values
                if len(sp) == 0:
                    row_out[tag] = (0, 0.0, 0.0); continue
                row_out[tag] = (len(sp), sp.mean(), sp.sum())
            out.append(row_out)
        return label, out

    blocks = [run(5, "CAUSAL: filter hC4 (bar-4 close), ENTER bar 5 open"),
              run(4, "OPTIMISTIC ref: filter hC4, ENTER bar 4 open (1-bar look-ahead)")]

    Lr = ["# Delayed-entry hC filter — causal re-validation", ""]
    Lr.append(f"Universe: all flips alive at the entry bar (delayed entry => NOT survivor-biased). "
              f"Friction: entry +0.5t, exit -1.0t, $5 comm, cat-stop at flip extreme, hold-to-flip.")
    Lr.append("")
    for label, out in blocks:
        Lr.append(f"## {label}")
        Lr.append("")
        Lr.append("| Rule | IS n | IS $/tr | IS net | OOS n | OOS $/tr | OOS net |")
        Lr.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for ro in out:
            isn, ise, isnet = ro["IS"]; on, oe, onet = ro["OOS"]
            Lr.append(f"| {ro['rule']} | {isn:,} | ${ise:+.2f} | ${isnet:+,.0f} | "
                      f"{on:,} | ${oe:+.2f} | ${onet:+,.0f} |")
        Lr.append("")
    (OUT / "revalidate_delayed_entry_filter.md").write_text("\n".join(Lr), encoding="utf-8")
    print("\n".join(Lr))
    print("\nWrote revalidate_delayed_entry_filter.md")


if __name__ == "__main__":
    main()

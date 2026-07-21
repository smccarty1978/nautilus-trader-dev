"""Step 2 re-validation: re-run the headline hC Peak-Decay Exit on the FULL flip
universe (no n_post<4 survivor filter), side by side with the published survivor
subset. Reproduces decision_hc_sprint.py Study 2 logic EXACTLY (same KNN walk-forward,
same sim_decay_study), then reports baseline + Decay 20% under two populations:

  (A) SURVIVOR subset  : n_post >= 4   (as published -> the +$475K / +$15.73/tr base)
  (B) FULL universe    : all flips     (includes the ~22% quick-failures excluded above)

Writes results/revalidate_peak_decay_full_universe.md
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
NS = 1_000_000_000
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY_SLIP_T = 0.5; EXIT_SLIP_T = 1.0
ENTRY = ENTRY_SLIP_T * TICK; EXIT = EXIT_SLIP_T * TICK
DETER_STATES = ("Failure", "Chop")
KNN_K = 500; IS_REF_CAP = 40000
RNG = np.random.default_rng(0)


def main():
    print("Loading data...")
    A.BARS = list(range(4, 29))
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    rididx = {r: i for i, r in enumerate(df.regime_id.values)}

    print(f"Total flips in capsule: {len(df):,}")
    print(f"  n_post >= 4 (survivor subset): {(df.n_post >= 4).sum():,}")
    print(f"  n_post <  4 (quick-failures) : {(df.n_post < 4).sum():,}  "
          f"({(df.n_post < 4).mean()*100:.1f}% excluded by the published filter)")

    print("Building states...")
    S = A.build_states(df, M)

    print("Running walk-forward KNN (same as decision_hc_sprint)...")
    pNH3 = np.full(len(S), np.nan); pFL3 = np.full(len(S), np.nan)
    for year in [2022, 2023, 2024, 2025, 2026]:
        db = S[S.year < year] if year < 2025 else S[S.year < 2025]
        q = S[S.year == year]
        if len(q) == 0 or len(db) < 200:
            continue
        for k in sorted(q.k.unique()):
            isk = db[db.k == k]
            om = (S.year == year) & (S.k == k)
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

    S["pNH3"] = pNH3; S["pFL3"] = pFL3
    S = S[S.pNH3.notna()].copy().sort_values(["rid", "k"]).reset_index(drop=True)
    S["hC"] = S.pNH3 - S.pFL3
    S["hC_pk"] = S.groupby("rid").hC.cummax()
    S["dd"] = 1 - S.hC / S.hC_pk.clip(lower=1e-6)

    rid_to_k_feats = {}
    for r, gg in S.groupby("rid"):
        rid_to_k_feats[r] = {row.k: {"hC": row.hC, "dd": row.dd} for _, row in gg.iterrows()}

    # ---- EXACT copy of decision_hc_sprint.sim_decay_study ----
    def sim_decay_study(row, thresh):
        d_val = row["direction"]; atr_val = row["atr_base"]; n_post_val = int(row["n_post"])
        rid = row["regime_id"]
        post_o = list(row["post_o"]); post_h = list(row["post_h"])
        post_l = list(row["post_l"]); post_c = list(row["post_c"])
        entry = post_o[0]
        entry_fill = entry + d_val * ENTRY_SLIP_T * TICK
        stop = (row["flip_l"] - TICK) if d_val == 1 else (row["flip_h"] + TICK)
        hs_info = rid_to_k_feats.get(rid, {})
        exit_px = None
        for j in range(1, n_post_val + 1):
            bh, bl, bc = post_h[j - 1], post_l[j - 1], post_c[j - 1]
            if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
                exit_px = stop - d_val * EXIT_SLIP_T * TICK; break
            if j >= 4:
                feat = hs_info.get(j)
                if feat and feat["dd"] >= thresh:
                    exit_px = bc - d_val * EXIT_SLIP_T * TICK; break
        if exit_px is None:
            exit_px = post_c[n_post_val - 1] - d_val * EXIT_SLIP_T * TICK
        return (exit_px - entry_fill) * d_val * MULT - COMM

    def metrics(p, y):
        p = np.asarray(p); y = np.asarray(y)
        out = {}
        for tag, mask in [("IS", y < 2025), ("OOS", y >= 2025)]:
            sp = p[mask]
            if len(sp) == 0:
                out[tag] = dict(n=0, exp=0, net=0, dd=0, pf=0); continue
            eq = np.cumsum(sp); dd = (np.maximum.accumulate(eq) - eq).max()
            pf = sp[sp > 0].sum() / (-sp[sp < 0].sum()) if (sp < 0).any() else np.inf
            out[tag] = dict(n=len(sp), exp=sp.mean(), net=sp.sum(), dd=dd, pf=pf)
        return out

    rows = df.to_dict("records")
    yrs = df.year.values
    results = {}
    for thresh, name in [(1.0, "Baseline (hold-to-flip)"), (0.20, "Decay 20% (HEADLINE)")]:
        pnl_all = np.array([sim_decay_study(r, thresh) for r in rows])
        surv = df.n_post.values >= 4
        results[name] = {
            "A_survivor": metrics(pnl_all[surv], yrs[surv]),
            "B_full":     metrics(pnl_all,       yrs),
        }

    # ---- report ----
    Lr = ["# Step 2 — Peak-Decay Exit re-validated on FULL flip universe", ""]
    Lr.append(f"Capsule flips: **{len(df):,}** total | survivors (n_post>=4): **{surv.sum():,}** "
              f"| quick-failures dropped by published filter: **{(~surv).sum():,}** "
              f"({(~surv).mean()*100:.1f}%)")
    Lr.append("")
    Lr.append("Friction identical to decision_hc_sprint (entry+0.5t, exit-1.0t, $5 comm). "
              "Cat-stop at flip-bar extreme. Decay arms at bar 4.")
    Lr.append("")
    for name in results:
        Lr.append(f"## {name}")
        Lr.append("")
        Lr.append("| Population | Split | n | Expectancy $/tr | Net PnL | Max DD | PF |")
        Lr.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
        for pop, lbl in [("A_survivor", "A: survivor (n_post>=4, AS PUBLISHED)"),
                          ("B_full", "B: FULL universe (all flips)")]:
            for split in ["IS", "OOS"]:
                m = results[name][pop][split]
                Lr.append(f"| {lbl} | {split} | {m['n']:,} | ${m['exp']:+.2f} | "
                          f"${m['net']:+,.0f} | ${m['dd']:,.0f} | {m['pf']:.2f} |")
        Lr.append("")

    # headline delta
    base_oos_full = results["Baseline (hold-to-flip)"]["B_full"]["OOS"]
    decay_oos_full = results["Decay 20% (HEADLINE)"]["B_full"]["OOS"]
    decay_oos_surv = results["Decay 20% (HEADLINE)"]["A_survivor"]["OOS"]
    Lr.append("## Verdict")
    Lr.append("")
    Lr.append(f"- Published headline (survivor subset, Decay 20%, OOS): "
              f"**${decay_oos_surv['exp']:+.2f}/tr, net ${decay_oos_surv['net']:+,.0f}**")
    Lr.append(f"- Same rule on FULL universe (Decay 20%, OOS): "
              f"**${decay_oos_full['exp']:+.2f}/tr, net ${decay_oos_full['net']:+,.0f}**")
    Lr.append(f"- Full-universe baseline hold-to-flip (OOS): "
              f"**${base_oos_full['exp']:+.2f}/tr, net ${base_oos_full['net']:+,.0f}**")
    (OUT / "revalidate_peak_decay_full_universe.md").write_text("\n".join(Lr), encoding="utf-8")
    print("\n".join(Lr))
    print("\nWrote revalidate_peak_decay_full_universe.md")


if __name__ == "__main__":
    main()

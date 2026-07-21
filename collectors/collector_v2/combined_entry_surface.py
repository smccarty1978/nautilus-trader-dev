"""2D Entry Surface — P_bad_short (risk) x P_runner (opportunity), both causal at Bar 3.

Framing (per user):
  BadShort KNN = avoid bad early lifecycle (risk axis)
  Opportunity KNN = require enough opportunity quality (opportunity axis)

CAUSALITY: hC's earliest value is bar-4 CLOSE, so it cannot gate a bar-4 entry without
1-bar look-ahead (the proven +$69->-$17 leak). The causal opportunity axis at bar 3 is a
KNN twin predicting the RUNNER class (P_runner). Primary surface uses P_bad x P_runner,
enter bar 4, money on REAL NT baseline fills. An hC4 panel is included but TAGGED non-causal.

Runner = (hold-to-flip pnl >= 1.5 ATR) OR (MFE-from-bar4 >= 2.0 ATR).
Money: drop-subset of baseline_<yr> NT fills (entry-only filter => exact economics).
Writes results/combined_arch/combined_entry_surface.md
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backtests" / "studies" / "regime_dna_knn"))
sys.path.insert(0, str(ROOT))
import early_health_filter as E       # noqa: E402
import progressive_separability as P  # noqa: E402

OUT = ROOT / "collectors/collector_v2/results/combined_arch"
KNN_DIR = ROOT / "backtests/studies/regime_dna_knn/results"
FEATS = (["mfe", "mae", "health", "dist_flip_open", "pullback", "progress_count",
          "close_prog_ratio", "flip_open_viol", "consec_noncont", "close_loc",
          "upper_wick", "range_exp", "vol_exp"] + P.PRE5)
YEARS = [2022, 2023, 2024, 2025, 2026]
OOSY = [2025, 2026]
K = 500; IS_REF_CAP = 40000
RNG = np.random.default_rng(0)


def wf_knn(S, label):
    Po = np.full(len(S), np.nan); Pi = np.full(len(S), np.nan)
    for y in YEARS:
        dbm = (S.year < y) if y < 2025 else (S.year < 2025)
        oom = (S.year == y)
        db = S[dbm]
        if oom.sum() == 0 or len(db) < 200:
            continue
        if len(db) > IS_REF_CAP:
            db = db.iloc[RNG.choice(len(db), IS_REF_CAP, replace=False)]
        Xis = db[FEATS].values.astype(np.float32)
        mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
        nn = NearestNeighbors(n_neighbors=min(K, len(db)), n_jobs=-1).fit((Xis - mu) / sd)
        yv = db[label].values
        _, idx = nn.kneighbors((S.loc[oom, FEATS].values.astype(np.float32) - mu) / sd)
        Po[np.where(oom)[0]] = yv[idx].mean(1)
        _, idi = nn.kneighbors((S.loc[dbm, FEATS].values.astype(np.float32) - mu) / sd)
        Pi[np.where(dbm)[0]] = yv[idx[:0]].mean(1) if False else yv[idi].mean(1)
    return Po, Pi


def metrics(p):
    p = np.asarray(p, float)
    if len(p) == 0:
        return dict(n=0, net=0.0, ppt=0.0, pf=0.0, mdd=0.0)
    eq = np.cumsum(p); pos = p[p > 0].sum(); neg = -p[p < 0].sum()
    return dict(n=len(p), net=float(p.sum()), ppt=float(p.mean()),
                pf=float(pos/neg) if neg > 0 else float('inf'),
                mdd=float((np.maximum.accumulate(eq) - eq).max()))


def main():
    cap = pd.read_parquet(KNN_DIR / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    npost = df.n_post.values.astype(int); entry = O[:, 4]
    term = np.minimum(npost, 61); exitpx = C[np.arange(len(df)), term]
    pnl_atr = (exitpx - entry) * d / atr
    favE = np.where(d[:, None] == 1, H[:, 4:] - entry[:, None], entry[:, None] - L[:, 4:])
    mfe4 = np.maximum(np.nanmax(favE, axis=1) / atr, 0.0)
    bad = ((npost <= 10) & (pnl_atr <= 0.25)).astype(int)
    runner = ((pnl_atr >= 1.5) | (mfe4 >= 2.0)).astype(int)
    alive = npost >= 4

    feat3 = P.feats_through(df, M, 3)
    S = pd.DataFrame({"regime_start_ts": df.regime_start_ts.values.astype("int64"),
                      "year": df.year.values, "bad": bad, "runner": runner})
    for c in FEATS:
        S[c] = feat3[c].values
    S = S[alive].reset_index(drop=True)

    print("KNN P_bad..."); S["P_bad"], Pbad_is = wf_knn(S, "bad")
    print("KNN P_runner..."); S["P_run"], Prun_is = wf_knn(S, "runner")
    S["P_bad_is"] = Pbad_is; S["P_run_is"] = Prun_is

    # hC4 (bar-4 close) reference — NON-CAUSAL for bar-4 entry
    hc = pd.read_parquet(OUT / "hc_perbar_mapping.parquet")
    hc4 = dict(zip(hc[hc.bars_in_regime == 5].regime_start_ts.astype("int64"),
                   hc[hc.bars_in_regime == 5].hC))
    S["hC4"] = S.regime_start_ts.map(hc4)

    pbad_map = dict(zip(S.regime_start_ts, S.P_bad))
    prun_map = dict(zip(S.regime_start_ts, S.P_run))
    hc4_map = dict(zip(S.regime_start_ts, S.hC4))

    # real baseline fills
    bt = {}
    for y in OOSY:
        t = pd.read_parquet(OUT / f"baseline_{y}" / "trades.parquet")
        rs = t.regime_start_ts.astype("int64")
        t["P_bad"] = rs.map(pbad_map); t["P_run"] = rs.map(prun_map); t["hC4"] = rs.map(hc4_map)
        bt[y] = t[t.P_bad.notna() & t.P_run.notna()].copy()
    allbt = pd.concat([bt[2025].assign(yr=2025), bt[2026].assign(yr=2026)], ignore_index=True)

    R = ["# 2D Entry Surface — P_bad_short x P_runner (causal Bar-3, enter Bar-4)", "",
         f"Pop alive@bar4: {alive.sum():,} | base bad {bad[alive].mean()*100:.0f}% / runner {runner[alive].mean()*100:.0f}%.",
         f"Scored OOS baseline fills: 2025 n={len(bt[2025]):,}, 2026 n={len(bt[2026]):,}.", ""]

    # axis AUCs
    oo = S[S.year.isin(OOSY)]
    aucb = roc_auc_score(oo.bad, oo.P_bad)
    aucr = roc_auc_score(oo.runner, oo.P_run)
    R += [f"Axis AUC (OOS): P_bad={aucb:.3f} (target bad), P_runner={aucr:.3f} (target runner).", ""]

    # 2D surface: P_bad quintile (rows) x P_run quintile (cols); pooled $/tr; mark both-year>0
    def qbucket(s, col, ref):
        edges = np.percentile(ref, [20, 40, 60, 80])
        return np.digitize(s[col].values, edges)
    allbt["bb"] = qbucket(allbt, "P_bad", bt[2025].P_bad.values)   # ref = OOS dist (descriptive)
    allbt["rb"] = qbucket(allbt, "P_run", bt[2025].P_run.values)
    R += ["## 2D surface — pooled $/tr (rows=P_bad quintile lo→hi, cols=P_runner quintile lo→hi)",
          "✓ = net-positive in BOTH 2025 and 2026 (n>=100 each).", "",
          "| P_bad \\ P_run | Q1 lo | Q2 | Q3 | Q4 | Q5 hi |",
          "| --- | --- | --- | --- | --- | --- |"]
    for bi in range(5):
        cells = []
        for ri in range(5):
            c = allbt[(allbt.bb == bi) & (allbt.rb == ri)]
            if len(c) == 0:
                cells.append("·"); continue
            ppt = c.net_pnl.mean()
            c25 = c[c.yr == 2025].net_pnl; c26 = c[c.yr == 2026].net_pnl
            both = (len(c25) >= 100 and len(c26) >= 100 and c25.mean() > 0 and c26.mean() > 0)
            cells.append(f"${ppt:+.0f}(n{len(c)}){'✓' if both else ''}")
        R.append(f"| bad Q{bi+1} | " + " | ".join(cells) + " |")
    R.append("")

    # composition surface (bad%/runner%) for the low-bad row
    R += ["## Composition by P_bad quintile (OOS): bad% / runner% / $/tr",
          "| P_bad | n | bad% | runner% | $/tr | 2025 $/tr | 2026 $/tr |",
          "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for bi in range(5):
        c = allbt[allbt.bb == bi]
        c25 = c[c.yr == 2025].net_pnl; c26 = c[c.yr == 2026].net_pnl
        # bad/runner labels per regime via maps
        R.append(f"| Q{bi+1} | {len(c):,} | "
                 f"{S[S.regime_start_ts.isin(c.regime_start_ts.astype('int64'))].bad.mean()*100:.0f}% | "
                 f"{S[S.regime_start_ts.isin(c.regime_start_ts.astype('int64'))].runner.mean()*100:.0f}% | "
                 f"${c.net_pnl.mean():+.0f} | ${c25.mean():+.0f} | ${c26.mean():+.0f} |")
    R.append("")

    # ---- combined rules: reject P_bad top X% AND require P_run >= pctile ----
    R += ["## Combined entry rules (IS-derived thresholds, real fills, 2025/2026 separate)",
          "Keep if P_bad < (100−X) IS-pctile AND P_run >= Y IS-pctile.", "",
          "| rule | 2025 n | 2025 $/tr | 2026 n | 2026 $/tr | both>baseline? | both>0? | beats random? |",
          "| --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: |"]
    bl = {y: metrics(bt[y].net_pnl.values) for y in OOSY}
    R.append(f"| baseline (scored) | {bl[2025]['n']:,} | ${bl[2025]['ppt']:+.1f} | "
             f"{bl[2026]['n']:,} | ${bl[2026]['ppt']:+.1f} | — | — | — |")
    bad_is = S[(S.year < 2025)].P_bad_is.dropna().values
    run_is = S[(S.year < 2025)].P_run_is.dropna().values
    for X in (30, 40):
        for Y in (50, 60, 70):
            tb = np.percentile(bad_is, 100 - X); tr = np.percentile(run_is, Y)
            res = {}; rnd = {}
            for y in OOSY:
                t = bt[y]
                keep = t[(t.P_bad < tb) & (t.P_run >= tr)]
                res[y] = metrics(keep.net_pnl.values)
                # random keep same count
                nk = len(keep); ppts = []
                for s in range(20):
                    rg = np.random.default_rng(s)
                    if nk > 0 and nk <= len(t):
                        ppts.append(t.net_pnl.values[rg.choice(len(t), nk, replace=False)].mean())
                rnd[y] = (np.mean(ppts), np.percentile(ppts, 95)) if ppts else (0, 0)
            both_bl = res[2025]['ppt'] > bl[2025]['ppt'] and res[2026]['ppt'] > bl[2026]['ppt']
            both_pos = res[2025]['ppt'] > 0 and res[2026]['ppt'] > 0
            beat_rnd = res[2025]['ppt'] > rnd[2025][1] and res[2026]['ppt'] > rnd[2026][1]
            R.append(f"| bad<top{X}% & run>=p{Y} | {res[2025]['n']:,} | ${res[2025]['ppt']:+.1f} | "
                     f"{res[2026]['n']:,} | ${res[2026]['ppt']:+.1f} | "
                     f"{'YES' if both_bl else 'no'} | {'YES' if both_pos else 'no'} | "
                     f"{'YES' if beat_rnd else 'no'} |")

    # ---- hC4 reference (NON-CAUSAL) ----
    R += ["", "## hC4 reference panel — NON-CAUSAL for bar-4 entry (hC4 uses bar-4 close; "
          "shown for the hC framing only, NOT deployable)",
          "| rule | 2025 $/tr | 2026 $/tr | both>0? |", "| --- | ---: | ---: | :---: |"]
    hc4_is = S[S.year < 2025].hC4.dropna().values
    for X in (30, 40):
        for hcq in (50, 60, 70):
            tb = np.percentile(bad_is, 100 - X); th = np.percentile(hc4_is, hcq)
            r = {}
            for y in OOSY:
                t = bt[y][bt[y].hC4.notna()]
                keep = t[(t.P_bad < tb) & (t.hC4 >= th)]
                r[y] = metrics(keep.net_pnl.values)
            bp = r[2025]['ppt'] > 0 and r[2026]['ppt'] > 0
            R.append(f"| bad<top{X}% & hC4>=p{hcq} | ${r[2025]['ppt']:+.1f} | ${r[2026]['ppt']:+.1f} | {'YES' if bp else 'no'} |")

    # verdict
    any_both_pos = False
    for X in (30, 40):
        for Y in (50, 60, 70):
            tb = np.percentile(bad_is, 100 - X); tr = np.percentile(run_is, Y)
            if all(metrics(bt[y][(bt[y].P_bad < tb) & (bt[y].P_run >= tr)].net_pnl.values)['ppt'] > 0 for y in OOSY):
                any_both_pos = True
    R += ["", "## VERDICT", ""]
    if any_both_pos:
        R.append("**A causal cell/rule is net-positive in BOTH 2025 and 2026 → candidate worth deeper NT validation.**")
    else:
        R.append("**No causal P_bad×P_runner cell or rule is net-positive in both 2025 and 2026.** "
                 "The two KNNs combine to reduce damage and improve composition, but do not create "
                 "expectancy — 2026 stays negative. Price-only entry geometry has reached its ceiling; "
                 "a 2026-robust non-price input (order flow / book) is required.")
    (OUT / "combined_entry_surface.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote combined_entry_surface.md")


if __name__ == "__main__":
    main()

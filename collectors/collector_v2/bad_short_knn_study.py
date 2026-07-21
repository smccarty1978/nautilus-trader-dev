"""KNN Bad-Short-Regime Detector — focused study.

Target (the ONLY target):
  BadShortRegime = (n_post <= 10) AND (hold_to_flip_pnl_atr <= +0.25)
  measured from planned Bar-4 entry (O[:,4]) to opposite-regime-flip exit (terminal post close).
Population: regimes alive at Bar 4 (n_post >= 4) — the enterable set.

Decision: score at Bar 3 close (feature window through bar 3), enter/reject Bar 4 open.
Model: KNN ONLY (no LightGBM). Walk-forward (IS years < test; OOS 2025/2026 capped IS<2025).
Features: progressive_separability.feats_through(df,M,Nbar) — strictly causal, direction-normalized.

Money gate uses the REAL NT baseline fills (backtests/combined_arch/baseline_<yr>/trades.parquet,
GTC market, state-gated). Rejecting an entry-only filter = dropping those rows (single-position,
non-overlapping regimes) => exact filtered economics, no NT re-run.

Writes results/combined_arch/bad_short_knn_study.md
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
IS_REF_CAP = 40000
FEATS = (["mfe", "mae", "health", "dist_flip_open", "pullback", "progress_count",
          "close_prog_ratio", "flip_open_viol", "consec_noncont", "close_loc",
          "upper_wick", "range_exp", "vol_exp"] + P.PRE5)
YEARS = [2022, 2023, 2024, 2025, 2026]
OOSY = [2025, 2026]
RNG = np.random.default_rng(0)


def build_labels(df, M):
    H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    npost = df.n_post.values.astype(int)
    entry = O[:, 4]
    term_idx = np.minimum(npost, 61)
    exitpx = C[np.arange(len(df)), term_idx]
    pnl_atr = (exitpx - entry) * d / atr
    favE = np.where(d[:, None] == 1, H[:, 4:] - entry[:, None], entry[:, None] - L[:, 4:])
    mfe_bar4 = np.maximum(np.nanmax(favE, axis=1) / atr, 0.0)
    bad = ((npost <= 10) & (pnl_atr <= 0.25)).astype(int)
    runner = ((pnl_atr >= 1.5) | (mfe_bar4 >= 2.0)).astype(int)
    return pnl_atr, mfe_bar4, bad, runner


def walkforward_knn(S, feat_cols, K, label_col="bad"):
    """Return P (neighbor bad fraction) for every row, plus in-sample IS P for thresholds,
    plus neighbor-mean n_post and pnl_atr."""
    P_oos = np.full(len(S), np.nan)
    P_is = np.full(len(S), np.nan)
    nn_npost = np.full(len(S), np.nan)
    nn_pnl = np.full(len(S), np.nan)
    for year in YEARS:
        dbm = (S.year < year) if year < 2025 else (S.year < 2025)
        oom = (S.year == year)
        db = S[dbm];
        if oom.sum() == 0 or len(db) < 200:
            continue
        if len(db) > IS_REF_CAP:
            db = db.iloc[RNG.choice(len(db), IS_REF_CAP, replace=False)]
        Xis = db[feat_cols].values.astype(np.float32)
        mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
        nn = NearestNeighbors(n_neighbors=min(K, len(db)), n_jobs=-1).fit((Xis - mu) / sd)
        ybad = db[label_col].values
        ynp = db["n_post"].values; ypn = db["pnl_atr"].values
        # OOS
        Xo = S.loc[oom, feat_cols].values.astype(np.float32)
        _, idx = nn.kneighbors((Xo - mu) / sd)
        oi = np.where(oom)[0]
        P_oos[oi] = ybad[idx].mean(1)
        nn_npost[oi] = ynp[idx].mean(1); nn_pnl[oi] = ypn[idx].mean(1)
        # IS in-sample (thresholds only)
        Xi = S.loc[dbm, feat_cols].values.astype(np.float32)
        _, idxi = nn.kneighbors((Xi - mu) / sd)
        P_is[np.where(dbm)[0]] = ybad[idxi].mean(1)
    return P_oos, P_is, nn_npost, nn_pnl


def metrics(p):
    p = np.asarray(p)
    if len(p) == 0:
        return dict(n=0, net=0, ppt=0, pf=0, win=0, maxdd=0)
    net = p.sum(); pos = p[p > 0].sum(); neg = -p[p < 0].sum()
    eq = np.cumsum(p); mdd = float((np.maximum.accumulate(eq) - eq).max())
    return dict(n=len(p), net=float(net), ppt=float(net/len(p)),
                pf=float(pos/neg) if neg > 0 else float('inf'),
                win=float((p > 0).mean()*100), maxdd=mdd)


def main():
    print("Loading capsule...")
    cap = pd.read_parquet(KNN_DIR / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df)
    pnl_atr, mfe_bar4, bad, runner = build_labels(df, M)

    alive = df.n_post.values >= 4
    base = pd.DataFrame({
        "regime_start_ts": df.regime_start_ts.values.astype("int64"),
        "year": df.year.values, "n_post": df.n_post.values.astype(int),
        "pnl_atr": pnl_atr, "mfe_bar4": mfe_bar4, "bad": bad, "runner": runner,
    })[alive].reset_index(drop=True)

    R = ["# KNN Bad-Short-Regime Detector — study", "",
         f"Target: BadShort = n_post<=10 AND hold-to-flip pnl<=+0.25 ATR (from Bar-4 entry). "
         f"Population alive@bar4: **{len(base):,}** regimes. "
         f"Base BadShort rate: **{base.bad.mean()*100:.1f}%** | runner rate: {base.runner.mean()*100:.1f}%.", ""]

    # ---- 1. Separability per feature window (K=500) ----
    R += ["## 1. Separability (AUC of P_bad_short vs actual, OOS 2025+26 pooled, K=500)", "",
          "| Window | OOS base bad% | AUC | prec@5% | @10% | @20% | @30% |",
          "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    sep_store = {}
    for Nbar, wname in [(0, "flip"), (1, "bar1"), (2, "bar2"), (3, "bar3")]:
        feat = P.feats_through(df, M, Nbar)[FEATS]
        S = base.copy()
        for c in FEATS:
            S[c] = feat[c].values[alive]
        Poos, Pis, _, _ = walkforward_knn(S, FEATS, 500)
        S["P"] = Poos
        oos = S[S.year.isin(OOSY) & S.P.notna()]
        y = oos.bad.values; pp = oos.P.values
        auc = roc_auc_score(y, pp) if len(np.unique(y)) > 1 else float("nan")
        order = np.argsort(-pp)
        precs = []
        for x in (0.05, 0.10, 0.20, 0.30):
            k = max(1, int(len(order) * x)); precs.append(y[order[:k]].mean()*100)
        R.append(f"| {wname} | {y.mean()*100:.1f}% | {auc:.3f} | {precs[0]:.0f}% | "
                 f"{precs[1]:.0f}% | {precs[2]:.0f}% | {precs[3]:.0f}% |")
        if Nbar == 3:
            sep_store["bar3_feat"] = (S, feat)

    # ---- K sweep at bar3 ----
    R += ["", "## 1b. K sweep at Bar 3 (OOS AUC)", "", "| K | AUC | prec@10% |", "| --- | ---: | ---: |"]
    S3 = sep_store["bar3_feat"][0][["regime_start_ts", "year", "n_post", "pnl_atr", "bad", "runner"]].copy()
    for c in FEATS:
        S3[c] = sep_store["bar3_feat"][1][c].values[alive]
    Pby = {}
    for K in (100, 250, 500, 1000):
        Poos, Pis, nnp, nnpnl = walkforward_knn(S3, FEATS, K)
        Pby[K] = (Poos, Pis)
        oos = S3[S3.year.isin(OOSY)].copy(); oos["P"] = Poos[S3.year.isin(OOSY).values]
        oos = oos[oos.P.notna()]
        auc = roc_auc_score(oos.bad, oos.P) if oos.bad.nunique() > 1 else float("nan")
        order = np.argsort(-oos.P.values); k = max(1, int(len(order)*0.1))
        R.append(f"| {K} | {auc:.3f} | {oos.bad.values[order[:k]].mean()*100:.0f}% |")

    # use K=500 for rejection + money gate
    Poos500, Pis500 = Pby[500]
    S3["P"] = Poos500; S3["P_is"] = Pis500

    # ---- 2. Rejection power (Bar3, K=500) ----
    R += ["", "## 2. Rejection power (Bar 3, K=500; thresholds from IS P distribution)", "",
          "| reject top X% | bad removed% | all removed% | runner removed% | retained n | retained bad% | retained runner% |",
          "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    oos = S3[S3.year.isin(OOSY) & S3.P.notna()].copy()
    is_dist = S3[(S3.year < 2025) & S3.P_is.notna()].P_is.values
    for X in (10, 20, 30, 40, 50):
        thr = np.percentile(is_dist, 100 - X)
        rej = oos.P >= thr
        nbad = oos.bad.sum(); nrun = oos.runner.sum(); ntot = len(oos)
        R.append(f"| {X}% | {oos.bad[rej].sum()/nbad*100:.0f}% | {rej.sum()/ntot*100:.0f}% | "
                 f"{oos.runner[rej].sum()/nrun*100:.0f}% | {(~rej).sum():,} | "
                 f"{oos.bad[~rej].mean()*100:.1f}% | {oos.runner[~rej].mean()*100:.1f}% |")

    # ---- 3. Money gate on REAL NT baseline trades ----
    # map regime_start_ts -> P_bad (OOS) and -> IS threshold
    pmap = dict(zip(S3.regime_start_ts.values, S3.P.values))
    pqf = pd.read_parquet(OUT / "pqf_mapping.parquet")
    pqfmap = dict(zip(pqf.regime_start_ts.astype("int64"), pqf.pQF))
    bt = {}
    for y in OOSY:
        t = pd.read_parquet(OUT / f"baseline_{y}" / "trades.parquet")
        t["P_bad"] = t.regime_start_ts.astype("int64").map(pmap)
        t["pQF"] = t.regime_start_ts.astype("int64").map(pqfmap)
        bt[y] = t

    def gate_report(title, scorecol, is_dist_vals):
        R2 = [f"### {title}", "",
              "| reject top X% | 2025 n | 2025 $/tr | 2025 net | 2026 n | 2026 $/tr | 2026 net | both improve? |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |"]
        # baseline (scored only, for apples-to-apples)
        bl = {}
        for y in OOSY:
            sc = bt[y][bt[y][scorecol].notna()]
            bl[y] = metrics(sc.net_pnl.values)
        R2.append(f"| (baseline, scored) | {bl[2025]['n']:,} | ${bl[2025]['ppt']:+.1f} | "
                  f"${bl[2025]['net']/1000:+.0f}k | {bl[2026]['n']:,} | ${bl[2026]['ppt']:+.1f} | "
                  f"${bl[2026]['net']/1000:+.0f}k | — |")
        for X in (10, 20, 30, 40, 50):
            thr = np.percentile(is_dist_vals, 100 - X)
            row = {}
            for y in OOSY:
                sc = bt[y][bt[y][scorecol].notna()]
                keep = sc[sc[scorecol] < thr]
                row[y] = metrics(keep.net_pnl.values)
            imp = (row[2025]['ppt'] > bl[2025]['ppt']) and (row[2026]['ppt'] > bl[2026]['ppt'])
            R2.append(f"| {X}% | {row[2025]['n']:,} | ${row[2025]['ppt']:+.1f} | ${row[2025]['net']/1000:+.0f}k | "
                      f"{row[2026]['n']:,} | ${row[2026]['ppt']:+.1f} | ${row[2026]['net']/1000:+.0f}k | "
                      f"{'YES' if imp else 'no'} |")
        return R2, bl

    R += ["", "## 3. Money gate (real NT baseline fills; reject top X% by P_bad_short, K=500)"]
    g, bl = gate_report("KNN BadShort rejection", "P_bad", is_dist)
    R += g

    # ---- Control A: random rejection (20 seeds) ----
    R += ["", "## Control A — random rejection (20 seeds, mean [5th,95th] $/tr)", "",
          "| reject X% | 2025 KNN $/tr | 2025 random $/tr | 2026 KNN $/tr | 2026 random $/tr |",
          "| --- | ---: | ---: | ---: | ---: |"]
    for X in (10, 20, 30, 40, 50):
        thr = np.percentile(is_dist, 100 - X)
        cells = []
        knn_ppt = {}
        for y in OOSY:
            sc = bt[y][bt[y].P_bad.notna()]
            knn_ppt[y] = metrics(sc[sc.P_bad < thr].net_pnl.values)["ppt"]
            rs = []
            nkeep = int(round(len(sc) * (1 - X/100)))
            for s in range(20):
                rng = np.random.default_rng(s)
                idx = rng.choice(len(sc), nkeep, replace=False)
                rs.append(metrics(sc.net_pnl.values[idx])["ppt"])
            cells.append((y, knn_ppt[y], np.mean(rs), np.percentile(rs, 5), np.percentile(rs, 95)))
        R.append(f"| {X}% | ${cells[0][1]:+.1f} | ${cells[0][2]:+.1f} [{cells[0][3]:+.0f},{cells[0][4]:+.0f}] | "
                 f"${cells[1][1]:+.1f} | ${cells[1][2]:+.1f} [{cells[1][3]:+.0f},{cells[1][4]:+.0f}] |")

    # ---- Control B: duration leakage ----
    R += ["", "## Control B — duration leakage (|corr(feature, n_post)|, flag>0.5)", "",
          "| feature | corr |", "| --- | ---: |"]
    fb = P.feats_through(df, M, 3)[FEATS]
    npv = df.n_post.values[alive]
    corrs = []
    for c in FEATS:
        cc = np.corrcoef(fb[c].values[alive], npv)[0, 1]
        corrs.append((c, cc))
    for c, cc in sorted(corrs, key=lambda x: -abs(x[1]))[:8]:
        flag = " **FLAG**" if abs(cc) > 0.5 else ""
        R.append(f"| {c} | {cc:+.2f}{flag} |")
    R.append("\n(Features use only bars 0..3; correlation is association, not future leakage. "
             "Flagged only if |corr|>0.5 warranting inspection.)")

    # ---- 5. Model B comparison ----
    R += ["", "## Model B comparison (same money gate, reject top X% by P(QuickFail))"]
    pqf_is = pd.read_parquet(OUT / "pqf_is_thresholds.parquet")
    # build IS pQF distribution proxy from the per-year thresholds is awkward; reuse pQF OOS dist of IS years:
    # use IS-derived thresholds already computed in pqf_is_thresholds (per year, reject_pct)
    R2 = ["", "| reject X% | 2025 $/tr | 2025 net | 2026 $/tr | 2026 net | both improve? |",
          "| --- | ---: | ---: | ---: | ---: | :---: |"]
    blq = {y: metrics(bt[y][bt[y].pQF.notna()].net_pnl.values) for y in OOSY}
    R2.append(f"| (baseline, scored) | ${blq[2025]['ppt']:+.1f} | ${blq[2025]['net']/1000:+.0f}k | "
              f"${blq[2026]['ppt']:+.1f} | ${blq[2026]['net']/1000:+.0f}k | — |")
    for X in (10, 20, 30, 40, 50):
        row = {}
        for y in OOSY:
            thr = float(pqf_is[(pqf_is.year == y) & (pqf_is.reject_pct == X)].pqf_threshold.iloc[0])
            sc = bt[y][bt[y].pQF.notna()]
            row[y] = metrics(sc[sc.pQF < thr].net_pnl.values)
        imp = (row[2025]['ppt'] > blq[2025]['ppt']) and (row[2026]['ppt'] > blq[2026]['ppt'])
        R2.append(f"| {X}% | ${row[2025]['ppt']:+.1f} | ${row[2025]['net']/1000:+.0f}k | "
                  f"${row[2026]['ppt']:+.1f} | ${row[2026]['net']/1000:+.0f}k | {'YES' if imp else 'no'} |")
    R += R2

    (OUT / "bad_short_knn_study.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote bad_short_knn_study.md")
    print("\n".join(R[:60]))


if __name__ == "__main__":
    main()

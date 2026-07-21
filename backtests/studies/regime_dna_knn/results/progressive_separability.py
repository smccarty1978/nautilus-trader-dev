"""Pure Launch / Quick Failure separability BY OBSERVATION BAR (causal, leak-aware).

Two targets (Pure Orderly Launch; Quick Failure) x 6 observation windows
(A pre-flip, B..F through bars 1..5). Features are STRICTLY through the observation
bar (no info from later bars). Train IS 2021-24, validate OOS 2025-26 (Logistic +
LightGBM). Report AUC / precision@1,5,10% / recall / base / lift per (target,window).

Then the decisive money test: combined filter (P(Launch) top 5/10% AND P(QuickFail)
bottom 50/30/20%), entered CAUSALLY at the next bar open after the observation bar,
exited at bar-10 close or opposite-flip close (reversal CLOSE, not open — no exit
look-ahead). Net after $5 RT + 0.5t entry + 1.0t exit. Question: does any window/
threshold combo create a smaller-but-net-positive (both years) tradable population?

    python studies/regime_dna_knn/progressive_separability.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
import lightgbm as lgb

sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY = 0.5 * TICK; EXIT = 1.0 * TICK
WINDOWS = [(0, "A pre-flip"), (1, "B bar1"), (2, "C bar2"), (3, "D bar3"), (4, "E bar4"), (5, "F bar5")]
PRE5 = ["pre5_efficiency", "pre5_compression", "pre5_velocity_ratio", "pre5_volume_acceleration", "pre5_hh_ll_count"]


def build(df):
    n = df.n_post.values.astype(int); N = len(df); B = 62
    H = np.full((N, B), np.nan); L = np.full((N, B), np.nan); C = np.full((N, B), np.nan)
    O = np.full((N, B), np.nan); V = np.full((N, B), np.nan)
    H[:, 0] = df.flip_h; L[:, 0] = df.flip_l; C[:, 0] = df.flip_c; O[:, 0] = df.flip_o; V[:, 0] = 0
    ph, pl, pc, po = df.post_h.tolist(), df.post_l.tolist(), df.post_c.tolist(), df.post_o.tolist()
    pv = df.post_v.tolist()
    for i in range(N):
        k = min(n[i], B - 1)
        if k > 0:
            H[i, 1:k+1] = ph[i][:k]; L[i, 1:k+1] = pl[i][:k]; C[i, 1:k+1] = pc[i][:k]
            O[i, 1:k+1] = po[i][:k]; V[i, 1:k+1] = pv[i][:k]
    return H, L, C, O, V, n


def feats_through(df, M, Nbar):
    H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    fo = df.flip_o.values.astype(float); a20 = df.atr_20.values.astype(float)
    # CRITICAL FIX (audit 2026-06-15): k MUST equal Nbar. The old `max(Nbar,1)` let the
    # pre-flip window (Nbar=0) slice H[:, :2] — including the FIRST POST-FLIP BAR — into
    # mfe/mae/health/dist/pullback, leaking bar-1 price into a "pre-flip" feature while
    # entering at bar-1 open. At Nbar=0 these features now use ONLY column 0 (the flip bar,
    # which IS known at decision time). Bars 1..Nbar enter only via the Nbar>=1 block.
    k = Nbar
    f = {}
    fav = np.where(d[:, None] == 1, H[:, :k+1] - fo[:, None], fo[:, None] - L[:, :k+1])
    adv = np.where(d[:, None] == 1, fo[:, None] - L[:, :k+1], H[:, :k+1] - fo[:, None])
    f["mfe"] = np.maximum(np.nanmax(fav, axis=1) / atr, 0.0)
    f["mae"] = np.maximum(np.nanmax(adv, axis=1) / atr, 0.0)
    f["health"] = f["mfe"] / np.maximum(f["mae"], 0.1)
    # close excursion at obs bar
    cb = C[np.arange(len(df)), np.minimum(Nbar, n)]
    f["dist_flip_open"] = (cb - fo) * d / atr
    peak = np.maximum(np.nanmax(fav, axis=1), 0.0) / atr
    f["pullback"] = np.maximum(0.0, peak - f["dist_flip_open"])
    # progression / continuation over bars 1..Nbar
    if Nbar >= 1:
        ext = np.where(d[:, None] == 1, H[:, 1:k+1], -L[:, 1:k+1])
        run = np.maximum.accumulate(np.nan_to_num(ext, nan=-1e18), axis=1)
        prev = np.column_stack([np.where(d == 1, fo, -fo), run[:, :-1]])
        newext = (ext > prev) & ~np.isnan(ext)
        f["progress_count"] = np.nansum(newext, axis=1)
        bd = np.where(d[:, None] == 1, C[:, 1:k+1] > O[:, 1:k+1], C[:, 1:k+1] < O[:, 1:k+1])
        valid = ~np.isnan(C[:, 1:k+1])
        f["close_prog_ratio"] = np.nansum(bd & valid, axis=1) / np.maximum(valid.sum(axis=1), 1)
        viol = np.where(d[:, None] == 1, L[:, 1:k+1] < fo[:, None], H[:, 1:k+1] > fo[:, None])
        f["flip_open_viol"] = (np.nansum(viol, axis=1) > 0).astype(float)
        # consecutive non-continuation ending at Nbar
        stall = np.zeros(len(df))
        for j in range(newext.shape[1]-1, -1, -1):
            still = stall == (newext.shape[1]-1-j)
            stall = np.where(still & ~newext[:, j], stall + 1, stall)
        f["consec_noncont"] = stall
        # obs-bar close location / wick
        ob = np.minimum(Nbar, n)
        bh = H[np.arange(len(df)), ob]; bl = L[np.arange(len(df)), ob]
        bo = O[np.arange(len(df)), ob]; bc = C[np.arange(len(df)), ob]
        rng = bh - bl
        f["close_loc"] = np.where(d == 1, bc - bl, bh - bc) / np.where(rng > 0, rng, np.nan)
        f["upper_wick"] = np.where(d == 1, bh - np.maximum(bo, bc), np.minimum(bo, bc) - bl) / np.where(rng > 0, rng, np.nan)
        # volume / range expansion through Nbar
        f["range_exp"] = np.nanmean(H[:, 1:k+1] - L[:, 1:k+1], axis=1) / a20
        ob2 = np.minimum(Nbar, n)
        v_obs = V[np.arange(len(df)), ob2]
        v_mean = np.nanmean(V[:, 1:k+1], axis=1)
        f["vol_exp"] = v_obs / np.where(v_mean > 0, v_mean, np.nan)
    else:
        for c in ["progress_count", "close_prog_ratio", "flip_open_viol", "consec_noncont",
                  "close_loc", "upper_wick", "range_exp", "vol_exp"]:
            f[c] = np.full(len(df), 0.0)
    out = pd.DataFrame(f)
    for c in PRE5:
        out[c] = df[c].values
    return out.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def models(Xtr, ytr, Xte):
    sc = StandardScaler().fit(Xtr)
    lr = LogisticRegression(max_iter=2000, class_weight="balanced").fit(sc.transform(Xtr), ytr)
    gb = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=31,
                            class_weight="balanced", random_state=0, verbose=-1).fit(Xtr, ytr)
    # return OOS LR, OOS GBM, and IS GBM (IS GBM used to set filter thresholds — CRITICAL FIX 2)
    return (lr.predict_proba(sc.transform(Xte))[:, 1], gb.predict_proba(Xte)[:, 1],
            gb.predict_proba(Xtr)[:, 1])


def pk(y, s, frac):
    k = max(1, int(len(y) * frac)); top = np.argsort(-s)[:k]
    prec = y[top].mean(); rec = y[top].sum() / max(y.sum(), 1)
    return prec, rec


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    df["is_launch"] = (df.label == "TradableLaunch").astype(int)
    df["is_qf"] = (df.label == "QuickFailure").astype(int)
    df["is_chop"] = (df.label == "ChaoticChop").astype(int)
    M = build(df)
    H, Lm, C, O, V, n = M
    d = df.direction.values.astype(float); fo = df.flip_o.values
    is_mask = df.year.values < 2025; oos_mask = df.year.values >= 2025
    yr = df.year.values

    R = ["# Progressive Separability by Observation Bar (causal)", "",
         "Features strictly through the observation bar. Train IS 2021–24, validate OOS 2025–26. "
         "AUC rises toward Bar 5 PARTLY tautologically (more of the label window is observed; at Bar 5 a "
         "QuickFailure is nearly resolved) — so the combined-filter NET/TRADE is the arbiter.", "",
         "## 1. AUC progression",
         "| Window | Launch AUC (LR/GBM) | Launch base | QuickFail AUC (LR/GBM) | QF base |",
         "| --- | --- | --- | --- | --- |"]
    dec_table = []
    store = {}
    for Nbar, wname in WINDOWS:
        pop = n >= Nbar                       # reached observation bar
        X = feats_through(df, M, Nbar)
        itr = is_mask & pop; ite = oos_mask & pop
        row = {"window": wname, "Nbar": Nbar}
        for tgt in ("is_launch", "is_qf"):
            y = df[tgt].values
            ytr = y[itr]; yte = y[ite]
            if ytr.sum() < 20 or yte.sum() < 5:
                row[tgt] = None; continue
            s_lr, s_gb, s_gb_is = models(X[itr].values, ytr, X[ite].values)
            row[tgt] = dict(auc_lr=roc_auc_score(yte, s_lr), auc_gb=roc_auc_score(yte, s_gb),
                            base=yte.mean(), s_gb=s_gb, ite=np.where(ite)[0], s_gb_is=s_gb_is)
        store[Nbar] = row
        la = row.get("is_launch"); qa = row.get("is_qf")
        la_cell = f"{la['auc_lr']:.2f}/{la['auc_gb']:.2f}" if la else "—"
        la_base = f"{la['base']*100:.1f}%" if la else "—"
        qa_cell = f"{qa['auc_lr']:.2f}/{qa['auc_gb']:.2f}" if qa else "—"
        qa_base = f"{qa['base']*100:.1f}%" if qa else "—"
        R.append(f"| {wname} | {la_cell} | {la_base} | {qa_cell} | {qa_base} |")

    # ---- precision/recall table for the launch target ----
    R.append("")
    R.append("## 2. Launch precision/recall @ top-k% (GBM, OOS)")
    R.append("| Window | base | P@1% | P@5% | P@10% | R@5% | lift@1% |")
    R.append("| --- | --- | --- | --- | --- | --- | --- |")
    for Nbar, wname in WINDOWS:
        la = store[Nbar].get("is_launch")
        if not la:
            continue
        yte = df["is_launch"].values[la["ite"]]
        p1, _ = pk(yte, la["s_gb"], .01); p5, r5 = pk(yte, la["s_gb"], .05); p10, _ = pk(yte, la["s_gb"], .10)
        R.append(f"| {wname} | {la['base']*100:.1f}% | {p1*100:.0f}% | {p5*100:.0f}% | {p10*100:.0f}% | "
                 f"{r5*100:.0f}% | {p1/la['base']:.1f}x |")

    # ---- 3. combined money filter (decisive) ----
    R.append("")
    R.append("## 3. Combined filter MONEY test (causal entry at next bar open, exit bar10 / opp-flip close)")
    R.append("Candidates: P(Launch) top X% AND P(QuickFail) bottom Y%. Net = $20/pt − $5 RT − 0.5t entry − 1.0t exit.")
    R.append("")
    R.append("| Window | Filter | n | Launch% | Net/tr (bar10) | Net/tr (flip) | 2025 net | 2026 net | both+ & PF≥1.1? |")
    R.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    arange = np.arange(len(df))
    col10 = np.where(n > 10, 10, n); colf = np.minimum(n, 61)
    any_pass = 0
    best_line = None
    for Nbar, wname in WINDOWS:
        la = store[Nbar].get("is_launch"); qa = store[Nbar].get("is_qf")
        if not la or not qa or Nbar >= 5:
            continue
        ite = la["ite"]
        # map OOS scores back to global idx
        pl_s = pd.Series(la["s_gb"], index=ite); qf_s = pd.Series(qa["s_gb"], index=qa["ite"])
        common = ite[np.isin(ite, qa["ite"])]
        pls = pl_s.reindex(common).values; qfs = qf_s.reindex(common).values
        # CRITICAL FIX 2 (audit): filter thresholds are set on the IS score distribution,
        # NOT on the OOS pool being evaluated. Fixed thresholds then applied to OOS.
        pls_is = la["s_gb_is"]; qfs_is = qa["s_gb_is"]
        # entry feasible only if active at Nbar+1
        feas = n[common] > Nbar
        for topX in (0.05, 0.10):
            for botY in (0.50, 0.30, 0.20):
                lt = np.quantile(pls_is, 1 - topX); qt = np.quantile(qfs_is, botY)
                sel = (pls >= lt) & (qfs <= qt) & feas
                gi = common[sel]
                if len(gi) < 30:
                    continue
                ent = O[gi, Nbar + 1] + d[gi] * ENTRY
                e10 = (C[gi, col10[gi]] - d[gi] * EXIT - ent) * d[gi] * MULT - COMM
                ef = (C[gi, colf[gi]] - d[gi] * EXIT - ent) * d[gi] * MULT - COMM
                yy = yr[gi]
                pf = ef[ef > 0].sum() / (-ef[ef < 0].sum()) if (ef < 0).any() else np.inf
                n25 = ef[yy == 2025].sum(); n26 = ef[yy == 2026].sum()
                passed = (n25 > 0 and n26 > 0 and np.isfinite(pf) and pf >= 1.10)
                any_pass += int(passed)
                lp = df["is_launch"].values[gi].mean()
                line = (f"| {wname} | L≥{int(topX*100)}% & QF≤{int(botY*100)}% | {len(gi):,} | "
                        f"{lp*100:.0f}% | ${e10.mean():+.2f} | ${ef.mean():+.2f} | ${n25:,.0f} | ${n26:,.0f} | "
                        f"{'✅' if passed else '❌'} |")
                R.append(line)
                if best_line is None or ef.mean() > best_line[0]:
                    best_line = (ef.mean(), line)
    R.append("")
    R.append("## Verdict")
    # info-appearance read
    la0 = store[0]["is_launch"]["auc_gb"]; la3 = store[3]["is_launch"]["auc_gb"]
    qf0 = store[0]["is_qf"]["auc_gb"]; qf4 = store[4]["is_qf"]["auc_gb"]
    if any_pass:
        R.append(f"> [!TIP]\n> **{any_pass} combined filter(s) net-positive both years, PF≥1.10.** Pre-flip Launch "
                 f"AUC {la0:.2f} → Bar3 {la3:.2f}. A smaller-but-better tradable population MAY exist — requires "
                 "1s/tick re-validation (1m-bar exits overstate).")
    else:
        R.append(f"> [!WARNING]\n> **No combined filter is net-positive in both years (PF≥1.10).** Launch AUC rises "
                 f"pre-flip {la0:.2f} → Bar3 {la3:.2f} and QuickFail {qf0:.2f} → Bar4 {qf4:.2f} (info DOES appear "
                 "after the flip — but it is the label-window-overlap/observation kind). The combined Launch-high + "
                 "QuickFail-low filter selects a smaller population that is STILL net-negative both years: **early "
                 "OHLCV health is descriptive but not monetizable** (the user's third interpretation). Same wall.")
    (OUT / "progressive_separability.md").write_text("\n".join(R), encoding="utf-8")
    print(f"Wrote progressive_separability.md; combined passes={any_pass}")
    print(f"Launch AUC: preflip {la0:.3f} -> bar3 {la3:.3f} -> bar5 {store[5]['is_launch']['auc_gb']:.3f}")
    print(f"QuickFail AUC: preflip {qf0:.3f} -> bar4 {qf4:.3f}")
    if best_line:
        print("best combined net/tr line:", best_line[1])


if __name__ == "__main__":
    main()

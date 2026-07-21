"""Pure Orderly Launch — Early Separability (Bar-3 info only).

The decisive question: using ONLY information available through Bar 3 (early MFE/MAE,
health ratio, pullback, progression, bar-3 close location, flip-open violation, and
the pre-flip runway), can we distinguish the 1,228 OOS orderly launches from the
fakeouts? No KNN, no clustering, no lifecycle labels — just univariate decile
separation + a multivariate model (Logistic + LightGBM), trained on IS (2021-24),
evaluated OOS (2025-26). Report AUC and precision @ top 1/5/10%.

    python studies/regime_dna_knn/pure_launch_separability.py
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

FEATS = ["early_mfe_expansion", "early_mae_peak", "early_health_ratio",
         "current_pullback_from_peak", "progress_count_3", "close_progression_ratio",
         "bar3_close_location", "flip_open_violation_b",
         "pre5_efficiency", "pre5_compression", "pre5_velocity_ratio",
         "pre5_volume_acceleration", "pre5_hh_ll_count"]


def add_bar3_close_loc(df):
    d = df["direction"].values.astype(float)
    h = np.array([x[2] if len(x) >= 3 else np.nan for x in df["post_h"]])
    l = np.array([x[2] if len(x) >= 3 else np.nan for x in df["post_l"]])
    c = np.array([x[2] if len(x) >= 3 else np.nan for x in df["post_c"]])
    rng = h - l
    loc = np.where(d == 1, (c - l), (h - c)) / np.where(rng > 0, rng, np.nan)
    df["bar3_close_location"] = loc
    return df


def prec_at(y, score, frac):
    n = max(1, int(len(y) * frac))
    top = np.argsort(-score)[:n]
    return y[top].mean(), n


def evaluate(name, Xtr, ytr, Xte, yte, L):
    L.append(f"### Negatives = {name}  (OOS positives {int(yte.sum())}, negatives {int((1-yte).sum())}, "
             f"base rate {yte.mean()*100:.1f}%)")
    L.append("| Model | AUC | Prec@1% | Prec@5% | Prec@10% | Lift@1% |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    base = yte.mean()
    # logistic
    sc = StandardScaler().fit(Xtr)
    lr = LogisticRegression(max_iter=2000, class_weight="balanced").fit(sc.transform(Xtr), ytr)
    s_lr = lr.predict_proba(sc.transform(Xte))[:, 1]
    # lightgbm
    gbm = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=31,
                             class_weight="balanced", random_state=0, verbose=-1).fit(Xtr, ytr)
    s_gb = gbm.predict_proba(Xte)[:, 1]
    out = {}
    for mname, s in [("Logistic", s_lr), ("LightGBM", s_gb)]:
        auc = roc_auc_score(yte, s)
        p1, _ = prec_at(yte, s, 0.01); p5, _ = prec_at(yte, s, 0.05); p10, _ = prec_at(yte, s, 0.10)
        L.append(f"| {mname} | **{auc:.3f}** | {p1*100:.1f}% | {p5*100:.1f}% | {p10*100:.1f}% | "
                 f"{p1/base:.1f}x |")
        out[mname] = auc
    L.append("")
    return out


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap)
    df = add_bar3_close_loc(df)
    for f in FEATS:
        df[f] = df[f].replace([np.inf, -np.inf], np.nan)
    df["is_launch"] = (df["label"] == "TradableLaunch").astype(int)
    df["is_quickfail"] = (df["label"] == "QuickFailure").astype(int)
    is_df = df[df.year < 2025]; oos = df[df.year >= 2025]

    L = ["# Pure Orderly Launch — Early Separability (Bar-3 info only)", "",
         f"Positives = Pure Orderly Launch (IS {int(is_df.is_launch.sum()):,} / OOS {int(oos.is_launch.sum()):,}). "
         "Features: Bar-1–3 health + pre-flip runway ONLY. Train IS 2021–24, evaluate OOS 2025–26. "
         "No KNN, no clustering. The question: AUC ~0.52 (unpredictable) vs ~0.70 (the conclusion changes).", ""]

    # ---- Univariate decile P(launch) — launch vs all-non-launch, IS ----
    L.append("## Univariate — P(Pure Launch | decile), IS, launch vs all non-launch")
    base_is = is_df.is_launch.mean()
    L.append(f"Base rate P(launch) = {base_is*100:.1f}%. A feature separates if top/bottom deciles "
             "deviate strongly from base.\n")
    L.append("| Feature | D1 | D2 | D5 | D9 | D10 | span(max−min) |")
    L.append("| --- | --- | --- | --- | --- | --- | --- |")
    for f in FEATS:
        s = is_df[[f, "is_launch"]].dropna()
        if s[f].nunique() < 10:
            continue
        try:
            s["dec"] = pd.qcut(s[f], 10, labels=False, duplicates="drop") + 1
        except Exception:
            continue
        g = s.groupby("dec")["is_launch"].mean() * 100
        span = g.max() - g.min()
        def gv(k):
            return f"{g.get(k, float('nan')):.1f}%" if k in g.index else "—"
        L.append(f"| {f} | {gv(1)} | {gv(2)} | {gv(5)} | {gv(9)} | {gv(10)} | {span:.1f}pp |")
    L.append("")

    # ---- Multivariate AUC + precision ----
    L.append("## Multivariate — AUC + precision @ top k% (OOS 2025–26)")
    Xtr_all = is_df[FEATS].fillna(0.0).values
    ytr = is_df["is_launch"].values
    Xte_all = oos[FEATS].fillna(0.0).values
    yte = oos["is_launch"].values
    aucs = {}
    aucs["all"] = evaluate("ALL non-launch (deployment haystack)", Xtr_all, ytr, Xte_all, yte, L)
    # launch vs quickfail only
    is_qf = is_df[(is_df.is_launch == 1) | (is_df.is_quickfail == 1)]
    oo_qf = oos[(oos.is_launch == 1) | (oos.is_quickfail == 1)]
    aucs["qf"] = evaluate("QuickFailure fakeouts only (easiest)", is_qf[FEATS].fillna(0.0).values,
                          is_qf["is_launch"].values, oo_qf[FEATS].fillna(0.0).values,
                          oo_qf["is_launch"].values, L)

    best = max(max(aucs["all"].values()), max(aucs["qf"].values()))
    L.append("## Verdict")
    if best < 0.58:
        L.append(f"> [!WARNING]\n> **CONCLUSION HOLDS — orderly launches are NOT early-separable.** Best OOS AUC "
                 f"= {best:.3f} (≈ coin flip). Bar-3 + pre-flip information cannot distinguish the 1,228 orderly "
                 "launches from fakeouts. The 'barely-pulls-back-and-runs' pattern is not foreshadowed by its "
                 "first 3 bars — it is decided by what happens at bars 4–10, which are unobservable at decision "
                 "time. Consistent with every prior result.")
    elif best < 0.65:
        L.append(f"> [!NOTE]\n> **Weak separability.** Best OOS AUC = {best:.3f} — some signal, but below the "
                 "0.65–0.72 threshold that would change the conclusion. Worth a costed entry-filter test, but "
                 "expect the edge to be marginal after friction.")
    else:
        L.append(f"> [!TIP]\n> **CONCLUSION CHANGES — orderly launches ARE early-separable.** Best OOS AUC = "
                 f"{best:.3f}. Bar-3 + pre-flip information meaningfully identifies the orderly launches. This "
                 "reopens the price-action branch as an ENTRY filter — proceed to a costed, walk-forward, "
                 "both-years money gate on the top-decile selections.")
    (OUT / "pure_launch_separability.md").write_text("\n".join(L), encoding="utf-8")
    print(f"Best OOS AUC = {best:.3f}")
    for neg, dd in aucs.items():
        print(f"  vs {neg}: " + ", ".join(f"{m} {a:.3f}" for m, a in dd.items()))
    print("Wrote pure_launch_separability.md")


if __name__ == "__main__":
    main()

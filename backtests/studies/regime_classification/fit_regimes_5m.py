"""Phase 2 (5m) — fit unsupervised regime models on 5m features.

Trains HMM, GMM, and KMeans models for K ∈ {3, 4, 5, 6} on 5-minute features
using In-Sample (IS: 2020-2022) data for scaling and fitting, then predicts
states across all years (2020-2026) and saves the results.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import MiniBatchKMeans
from sklearn.mixture import GaussianMixture

try:
    from hmmlearn.hmm import GaussianHMM
    HAS_HMM = True
except ImportError:
    HAS_HMM = False
    print("WARN: hmmlearn not installed; skipping HMM")

PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
OUT = Path("studies/regime_classification/results")
IS_YEARS = (2020, 2021, 2022)
STATE_COUNTS = (3, 4, 5, 6)
SEED = 42

FEATURE_COLS = [
    "ret_25s", "ret_150s", "ret_300s", "ret_1500s", "cum_abs_300s",
    "rv_150s", "rv_1500s",
    "range_atr_300s", "range_atr_1500s", "range_atr_9000s",
    "vol_expansion",
    "efficiency_1500s", "chop_ratio_1500s", "n_dir_changes_300s",
    "body_ratio", "upper_wick", "lower_wick", "close_location",
    "vwap_z_signed", "vwap_z_abs", "vwap_slope_25m_atr", "session_pos",
    "range_pct_300s_vs_5h", "compress_drift",
]


def compute_causal_states(hmm, X) -> np.ndarray:
    """Compute strictly causal forward filtering states."""
    from scipy.stats import multivariate_normal
    N, D = X.shape
    K = hmm.n_components
    B = np.zeros((N, K))
    for k in range(K):
        if hmm.covariance_type == "full":
            cov = hmm.covars_[k]
        elif hmm.covariance_type == "diag":
            cov = np.diag(hmm.covars_[k])
        else:
            cov = hmm.covars_[k]
        B[:, k] = multivariate_normal(mean=hmm.means_[k], cov=cov, allow_singular=True).pdf(X)

    alpha = np.zeros((N, K))
    alpha[0] = hmm.startprob_ * B[0]
    sum_alpha = alpha[0].sum()
    if sum_alpha > 0:
        alpha[0] /= sum_alpha
    else:
        alpha[0] = np.ones(K) / K

    transmat = hmm.transmat_
    for t in range(1, N):
        pred = alpha[t-1] @ transmat
        alpha[t] = pred * B[t]
        sum_alpha = alpha[t].sum()
        if sum_alpha > 0:
            alpha[t] /= sum_alpha
        else:
            alpha[t] = pred
    return alpha.argmax(axis=1)


def main():
    t0 = time.time()
    in_p = OUT / f"features_{PRODUCT.lower()}_5m.parquet"
    df = pd.read_parquet(in_p)
    print(f"Loaded {len(df):,} rows from {in_p.name}")

    # Drop rows with any NaN in features
    mask = df[FEATURE_COLS].notna().all(axis=1)
    print(f"  rows with full feature vector: {mask.sum():,} "
          f"({mask.mean():.1%})")

    # Train scaler on IS only
    is_mask = mask & df["year"].isin(IS_YEARS)
    print(f"  IS (2020-2022) rows for fitting: {is_mask.sum():,}")

    scaler = StandardScaler()
    X_is = scaler.fit_transform(df.loc[is_mask, FEATURE_COLS].values)
    print(f"  scaler fit on IS (mean: {scaler.mean_[:3].round(3)}... "
          f"std: {scaler.scale_[:3].round(3)}...)")

    # Apply scaler to the FULL rolled-up feature set (all years, valid rows)
    X_all = np.full((len(df), len(FEATURE_COLS)), np.nan)
    X_all[mask.values] = scaler.transform(
        df.loc[mask, FEATURE_COLS].values)

    # Fit each model on IS rows
    for k in STATE_COUNTS:
        print(f"\n── n_states={k} (5m) ──")

        # KMeans
        t1 = time.time()
        km = MiniBatchKMeans(n_clusters=k, random_state=SEED,
                              n_init=10, batch_size=4096)
        km.fit(X_is)
        labels_km = np.full(len(df), -1, dtype=np.int64)
        labels_km[mask.values] = km.predict(X_all[mask.values])
        df[f"kmeans_{k}"] = labels_km
        print(f"  kmeans  fit+predict in {time.time()-t1:.0f}s  "
              f"inertia={km.inertia_:.0f}")

        # GMM
        t1 = time.time()
        try:
            gmm = GaussianMixture(n_components=k, covariance_type="full",
                                    random_state=SEED, max_iter=300, n_init=2,
                                    reg_covar=1e-4)
            gmm.fit(X_is)
            labels_g = np.full(len(df), -1, dtype=np.int64)
            labels_g[mask.values] = gmm.predict(X_all[mask.values])
            df[f"gmm_{k}"] = labels_g
            print(f"  gmm     fit+predict in {time.time()-t1:.0f}s  "
                  f"conv={gmm.converged_}  ll={gmm.score(X_is):.3f}")
        except Exception as e:
            print(f"  gmm FAILED: {e}")
            df[f"gmm_{k}"] = -1

        # HMM
        if HAS_HMM:
            t1 = time.time()
            try:
                hmm = GaussianHMM(n_components=k, covariance_type="full",
                                    random_state=SEED, n_iter=100,
                                    tol=1e-3)
                hmm.fit(X_is)
                labels_h = np.full(len(df), -1, dtype=np.int64)
                labels_h[mask.values] = compute_causal_states(hmm, X_all[mask.values])
                df[f"hmm_{k}"] = labels_h
                print(f"  hmm     fit+predict (causal) in {time.time()-t1:.0f}s  "
                      f"converged after {hmm.monitor_.iter} iter  "
                      f"ll={hmm.score(X_is):.3f}")
            except Exception as e:
                print(f"  hmm FAILED: {e}")
                df[f"hmm_{k}"] = -1

    out_p = OUT / f"states_{PRODUCT.lower()}_5m.parquet"
    df.to_parquet(out_p)
    print(f"\nsaved {out_p}")
    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()

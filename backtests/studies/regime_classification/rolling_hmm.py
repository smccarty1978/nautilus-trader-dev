"""Rolling HMM refit experiment: A. static / B. annual / C. quarterly / D. monthly.

Same 24 features as static (fit_regimes.py FEATURE_COLS), same GaussianHMM(4),
same StandardScaler discipline. Only change: training window slides.

Each refit:
  1. Define training window = trailing 24 months before deploy_start.
  2. Fit StandardScaler on training rows (full feature vectors).
  3. Fit GaussianHMM(4, covariance='full') on scaled training.
  4. Predict states on training; identify "expansion" state by signature:
         score = z(rv_300s) + z(range_atr_60s) + z(efficiency_300s) - z(chop_ratio_300s)
     where z is computed against the TRAINING distribution.
  5. Remap: target state → label 3 (matches static convention).
     Other states → labels 0/1/2 by ascending score (deterministic).
  6. Causal forward filter on deploy-window features (using training scaler);
     write remapped labels into the rolling state series.

Output:
  studies/regime_classification/results/states_nq_1m_rolling_<schedule>.parquet
    indexed by ts_1m_open, column `hmm_4_rolling`.
  studies/regime_classification/results/rolling_<schedule>_metadata.parquet
    one row per refit checkpoint with target_state, scores, remap, occupancy.

Notes:
  - State labels in deploy windows have a target-state-by-signature meaning.
    Downstream (NT strategy) uses target_state=3 against `hmm_4_rolling`.
  - Cold-start: forward filter on each deploy window starts from stationary;
    transient (~30 bars) is negligible against 3-month windows.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

try:
    from hmmlearn.hmm import GaussianHMM
except ImportError:
    raise SystemExit("hmmlearn not installed; cannot proceed")

from scipy.stats import multivariate_normal

PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
OUT = Path("studies/regime_classification/results")
FEATURES_PATH = OUT / f"features_{PRODUCT.lower()}_1m.parquet"
SEED = 42
# Subsample training rows per refit (HMM EM scales linearly per iter)
TRAIN_SAMPLE_MAX = 150_000
# Regularization for covariance (heavier than hmmlearn default 1e-3 for stability)
MIN_COVAR = 1e-2
HMM_N_ITER = 50
HMM_TOL = 1e-3

# Identical to fit_regimes.py FEATURE_COLS
FEATURE_COLS = [
    "ret_5s", "ret_30s", "ret_60s", "ret_300s", "cum_abs_60s",
    "rv_30s", "rv_300s",
    "range_atr_60s", "range_atr_300s", "range_atr_1800s",
    "vol_expansion",
    "efficiency_300s", "chop_ratio_300s", "n_dir_changes_60s",
    "body_ratio", "upper_wick", "lower_wick", "close_location",
    "vwap_z_signed", "vwap_z_abs", "vwap_slope_5m_atr", "session_pos",
    "range_pct_60s_vs_1h", "compress_drift",
]

# Signature features for state ranking
SIG_FEATURES = ["rv_300s", "range_atr_60s", "efficiency_300s", "chop_ratio_300s"]
SIG_SIGNS    = [+1.0,       +1.0,             +1.0,              -1.0]


def causal_forward_filter(hmm, X):
    """Causal forward-filter using emission * prior, uniform startprob.

    Returns most-likely-state per bar from filtered alpha.
    """
    N, D = X.shape
    K = hmm.n_components
    # Emission probabilities at each step
    B = np.zeros((N, K))
    for k in range(K):
        cov = hmm.covars_[k]
        if cov.ndim == 1:
            cov = np.diag(cov)
        B[:, k] = multivariate_normal(mean=hmm.means_[k], cov=cov,
                                       allow_singular=True).pdf(X)
    alpha = np.zeros((N, K))
    # Start from HMM start distribution
    alpha[0] = hmm.startprob_ * B[0]
    s = alpha[0].sum()
    alpha[0] = alpha[0] / s if s > 0 else np.ones(K) / K
    A = hmm.transmat_
    for t in range(1, N):
        pred = alpha[t-1] @ A
        alpha[t] = pred * B[t]
        s = alpha[t].sum()
        if s > 0:
            alpha[t] /= s
        else:
            alpha[t] = pred  # graceful degenerate
    return alpha.argmax(axis=1)


def quarter_starts(start, end):
    """Quarter-start dates UTC, from `start` to `end` (inclusive of last)."""
    return pd.date_range(start=start, end=end, freq="QS-JAN", tz="UTC")


def month_starts(start, end):
    return pd.date_range(start=start, end=end, freq="MS", tz="UTC")


def week_starts(start, end):
    """Monday-start weeks UTC."""
    return pd.date_range(start=start, end=end, freq="W-MON", tz="UTC")


def year_starts(start, end):
    return pd.date_range(start=start, end=end, freq="YS-JAN", tz="UTC")


def schedule_starts(schedule, start, end):
    if schedule == "weekly":
        return week_starts(start, end)
    if schedule == "quarterly":
        return quarter_starts(start, end)
    if schedule == "monthly":
        return month_starts(start, end)
    if schedule == "annual":
        return year_starts(start, end)
    raise ValueError(f"unknown schedule {schedule}")


def fit_and_label(df, train_idx, deploy_idx, cov_type="full"):
    """Fit scaler+HMM on train rows, score states, label deploy rows.

    Returns: (deploy_labels [int array], scores [k-array], target_state [int],
              remap [dict], train_state_occupancy [k-array], cov_type_used [str]).
    """
    X_train_raw = df.loc[train_idx, FEATURE_COLS].values
    # Subsample training to keep HMM EM tractable (per-iter cost linear in N)
    if len(X_train_raw) > TRAIN_SAMPLE_MAX:
        rng = np.random.default_rng(SEED)
        sample_idx = rng.choice(len(X_train_raw), size=TRAIN_SAMPLE_MAX, replace=False)
        sample_idx.sort()
        X_train_raw = X_train_raw[sample_idx]
        sig_vals_raw = df.loc[train_idx, SIG_FEATURES].values[sample_idx]
    else:
        sig_vals_raw = df.loc[train_idx, SIG_FEATURES].values

    scaler = StandardScaler().fit(X_train_raw)
    X_train = scaler.transform(X_train_raw)

    # Try full cov first; on failure or instability, fall back to diag
    for ct in [cov_type, "diag"]:
        try:
            hmm = GaussianHMM(n_components=4, covariance_type=ct,
                               random_state=SEED, n_iter=HMM_N_ITER,
                               tol=HMM_TOL, min_covar=MIN_COVAR)
            hmm.fit(X_train)
            # Quick sanity: did it produce valid params?
            if np.any(~np.isfinite(hmm.means_)) or np.any(~np.isfinite(hmm.transmat_)):
                raise ValueError(f"non-finite params with cov={ct}")
            cov_used = ct
            break
        except Exception as e:
            print(f"    HMM fit failed with cov={ct}: {e}; trying diag", flush=True)
            cov_used = None
    if cov_used is None:
        raise RuntimeError("HMM fit failed with both full and diag covariance")

    train_states = hmm.predict(X_train)
    occ = np.bincount(train_states, minlength=4) / len(train_states)

    # Signature scoring: z-score each signature feature on TRAIN raw values
    # (use the sampled subset so the state assignments align row-by-row)
    sig_vals = sig_vals_raw
    sig_mu = sig_vals.mean(axis=0)
    sig_sd = sig_vals.std(axis=0) + 1e-9
    sig_z = (sig_vals - sig_mu) / sig_sd

    scores = np.full(4, -np.inf)
    for k in range(4):
        in_state = train_states == k
        if in_state.sum() == 0:
            continue
        state_z = sig_z[in_state].mean(axis=0)  # 4-vector
        scores[k] = sum(s * z for s, z in zip(SIG_SIGNS, state_z))
    target = int(np.argmax(scores))

    # Remap: target → 3. Other 3 states → 0/1/2 by ascending score.
    ranked = np.argsort(scores)
    remap = {}
    others = [int(s) for s in ranked if int(s) != target]
    for new_lbl, old in enumerate(others):
        remap[old] = new_lbl
    remap[target] = 3

    # Forward-filter on deploy
    X_deploy_raw = df.loc[deploy_idx, FEATURE_COLS].values
    X_deploy = scaler.transform(X_deploy_raw)
    deploy_states = causal_forward_filter(hmm, X_deploy)
    deploy_labels = np.array([remap[int(s)] for s in deploy_states], dtype=np.int64)

    return deploy_labels, scores, target, remap, occ, cov_used


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule", choices=["annual", "quarterly", "monthly", "weekly"],
                    default="quarterly")
    ap.add_argument("--train-months", type=int, default=24)
    ap.add_argument("--deploy-start", default="2022-01-01",
                    help="first deploy-window start (need train-months prior)")
    ap.add_argument("--deploy-end", default="2026-12-31",
                    help="cutoff for last deploy window")
    args = ap.parse_args()

    t0 = time.time()
    df = pd.read_parquet(FEATURES_PATH)
    df = df.sort_index()
    print(f"Loaded {len(df):,} 1m bars from {FEATURES_PATH.name}")
    print(f"  index range: {df.index.min()} .. {df.index.max()}")

    # Valid-row mask (full feature vector)
    mask_full = df[FEATURE_COLS].notna().all(axis=1)
    print(f"  valid feature rows: {mask_full.sum():,} ({mask_full.mean():.1%})")

    deploy_start = pd.Timestamp(args.deploy_start, tz="UTC")
    deploy_end = pd.Timestamp(args.deploy_end, tz="UTC")
    starts = schedule_starts(args.schedule, deploy_start, deploy_end)
    print(f"\nSchedule: {args.schedule}, train-months={args.train_months}")
    print(f"  refit checkpoints: {len(starts)} ({starts[0].date()} .. {starts[-1].date()})")

    rolling_labels = np.full(len(df), -1, dtype=np.int64)
    metadata = []

    for i, deploy_t0 in enumerate(starts):
        deploy_t1 = (starts[i+1] if i + 1 < len(starts)
                      else min(deploy_end, df.index.max() + pd.Timedelta(seconds=1)))
        train_t0 = deploy_t0 - pd.DateOffset(months=args.train_months)
        train_t1 = deploy_t0

        train_mask = mask_full & (df.index >= train_t0) & (df.index < train_t1)
        deploy_mask = mask_full & (df.index >= deploy_t0) & (df.index < deploy_t1)

        n_train = train_mask.sum()
        n_deploy = deploy_mask.sum()
        if n_train < 10000:
            print(f"  {deploy_t0.date()}: train rows={n_train:,} < 10k, SKIP")
            continue
        if n_deploy == 0:
            print(f"  {deploy_t0.date()}: no deploy rows, SKIP")
            continue

        t1 = time.time()
        try:
            labels, scores, target, remap, occ, cov_used = fit_and_label(
                df, train_mask, deploy_mask)
        except Exception as e:
            print(f"  {deploy_t0.date()}: FIT FAILED ({e}); fall back to -1", flush=True)
            continue

        # Write into rolling_labels
        deploy_idx = np.where(deploy_mask.values)[0]
        rolling_labels[deploy_idx] = labels

        # Score-rank of target in occupancy
        target_occ = occ[target]
        scores_str = "[" + ",".join(f"{s:+.2f}" for s in scores) + "]"
        print(f"  {deploy_t0.date()} -> {deploy_t1.date()}: "
              f"train {n_train:,} / deploy {n_deploy:,}; "
              f"cov={cov_used}, target=s{target} score={scores[target]:+.2f}, "
              f"occ={target_occ:.2%}, scores={scores_str}; "
              f"fit {time.time()-t1:.0f}s", flush=True)

        metadata.append({
            "deploy_start": deploy_t0,
            "deploy_end":   deploy_t1,
            "train_start":  train_t0,
            "train_end":    train_t1,
            "train_rows":   int(n_train),
            "deploy_rows":  int(n_deploy),
            "cov_type":     cov_used,
            "target_state": target,
            "target_score": float(scores[target]),
            "target_train_occupancy": float(target_occ),
            "scores":       scores.tolist(),
            "train_occupancy": occ.tolist(),
            "remap":        {str(int(k)): int(v) for k, v in remap.items()},
        })

    # Save labels
    out = df[["year"]].copy()
    out["hmm_4_rolling"] = rolling_labels
    out_p = OUT / f"states_{PRODUCT.lower()}_1m_rolling_{args.schedule}.parquet"
    out.to_parquet(out_p)
    print(f"\nSaved labels → {out_p}")
    print(f"  bars with rolling label assigned: {(rolling_labels >= 0).sum():,}")
    print(f"  per-year coverage:")
    for y in sorted(out["year"].dropna().unique()):
        yr = out[out["year"] == y]
        cov = (yr["hmm_4_rolling"] >= 0).mean()
        s3 = (yr["hmm_4_rolling"] == 3).mean()
        print(f"    {int(y)}: {cov:.1%} labeled, state-3 share = {s3:.2%}")

    md_p = OUT / f"rolling_{args.schedule}_metadata.parquet"
    pd.DataFrame(metadata).to_parquet(md_p)
    print(f"Saved metadata → {md_p}")
    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()

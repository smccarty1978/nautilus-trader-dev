"""Temporal-OOS training and bucket evaluation. No random split exists in this file.

Fold membership is a calendar function of the observation timestamp, and gate V5
asserts `max(train ts) < min(eval ts)` in integer nanoseconds for every fit that
is performed. Headline numbers are the POOLED OOS predictions of folds 1+2;
training metrics are computed and stored but never headlined.
"""
from __future__ import annotations

import numpy as np
import polars as pl
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

from .common import BUCKETS, CT, FOLDS, GBT_PARAMS, N_BOOT, SEED


def fold_edges() -> list[tuple[str, int, int, int, int]]:
    out = []
    for name, (ts0, ts1), (es0, es1) in FOLDS:
        f = lambda s: int(  # noqa: E731
            pl.Series([s]).str.to_datetime("%Y-%m-%d").dt.replace_time_zone(CT)
            .dt.convert_time_zone("UTC").dt.epoch(time_unit="ns")[0])
        out.append((name, f(ts0), f(ts1), f(es0), f(es1)))
    return out


def _matrix(df: pl.DataFrame, cols: list[str]) -> np.ndarray:
    X = np.full((df.height, len(cols)), np.nan, dtype=float)
    for j, c in enumerate(cols):
        if c not in df.columns:
            continue
        s = df[c]
        if s.dtype == pl.Boolean:
            s = s.cast(pl.Int8)
        elif s.dtype == pl.String:
            continue
        try:
            X[:, j] = s.cast(pl.Float64).to_numpy()
        except Exception:
            pass
    return X


def usable_columns(df: pl.DataFrame, cols: list[str]) -> list[str]:
    """Drop columns that are constant or entirely null -- they cannot inform, and a
    constant column silently inflates a permutation-importance table."""
    keep = []
    for c in cols:
        if c not in df.columns:
            continue
        s = df[c]
        if s.dtype == pl.String:
            continue
        v = s.cast(pl.Float64, strict=False).drop_nulls()
        if v.len() == 0 or v.n_unique() <= 1:
            continue
        keep.append(c)
    return keep


def temporal_oos(df: pl.DataFrame, ts_col: str, y: np.ndarray, cols: list[str],
                 group_col: str | None = None) -> dict:
    """Fit each fold on its own past, predict its own future. Returns pooled OOS."""
    ts = df[ts_col].to_numpy()
    X = _matrix(df, cols)
    pooled = np.full(df.height, np.nan)
    pooled_fold = np.array([""] * df.height, dtype=object)
    per_fold, checks = {}, []

    for name, t0, t1, e0, e1 in fold_edges():
        tr = (ts >= t0) & (ts < t1)
        ev = (ts >= e0) & (ts < e1)
        if tr.sum() < 50 or ev.sum() < 20:
            per_fold[name] = {"n_train": int(tr.sum()), "n_eval": int(ev.sum()),
                              "skipped": "insufficient sample"}
            continue
        if y[tr].min() == y[tr].max():
            per_fold[name] = {"n_train": int(tr.sum()), "n_eval": int(ev.sum()),
                              "skipped": "single-class training fold"}
            continue
        checks.append({
            "fold": name, "max_train_ns": int(ts[tr].max()),
            "min_eval_ns": int(ts[ev].min()),
            "causal": bool(ts[tr].max() < ts[ev].min()),
            "group_overlap": (
                len(set(df[group_col].to_numpy()[tr]) & set(df[group_col].to_numpy()[ev]))
                if group_col else 0),
        })
        m = HistGradientBoostingClassifier(**GBT_PARAMS)
        m.fit(X[tr], y[tr])
        p = m.predict_proba(X[ev])[:, 1]
        pooled[ev] = p
        pooled_fold[ev] = name

        lg = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                           LogisticRegression(max_iter=2000))
        try:
            lg.fit(X[tr], y[tr])
            p_lg = lg.predict_proba(X[ev])[:, 1]
            auc_lg = float(roc_auc_score(y[ev], p_lg)) if y[ev].min() != y[ev].max() else None
        except Exception:
            auc_lg = None

        per_fold[name] = {
            "n_train": int(tr.sum()), "n_eval": int(ev.sum()),
            "base_rate_train": float(y[tr].mean()), "base_rate_eval": float(y[ev].mean()),
            "auc_oos": float(roc_auc_score(y[ev], p)) if y[ev].min() != y[ev].max() else None,
            "auc_in_sample_NOT_HEADLINE": float(
                roc_auc_score(y[tr], m.predict_proba(X[tr])[:, 1])),
            "auc_oos_logistic": auc_lg,
        }

    has = ~np.isnan(pooled)
    auc = (float(roc_auc_score(y[has], pooled[has]))
           if has.sum() > 20 and y[has].min() != y[has].max() else None)
    return {"pooled": pooled, "pooled_fold": pooled_fold, "mask": has,
            "auc_pooled_oos": auc, "per_fold": per_fold, "fold_checks": checks,
            "n_features": len(cols)}


def bucket_table(p: np.ndarray, mask: np.ndarray, frame: pl.DataFrame,
                 metrics: dict, group_col: str | None = None) -> pl.DataFrame:
    """Concentration by predicted-probability bucket. `metrics` maps name -> callable
    taking a boolean selector over the OOS rows and returning a scalar."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return pl.DataFrame()
    order = idx[np.argsort(-p[idx], kind="stable")]
    rows = []
    for name, q in BUCKETS:
        k = max(1, int(round(q * order.size)))
        sel = np.zeros(p.size, dtype=bool)
        sel[order[:k]] = True
        row = {"bucket": name, "n": int(k),
               "pct_population": float(100.0 * k / order.size),
               "min_prob": float(p[order[:k]].min()),
               "mean_prob": float(p[order[:k]].mean())}
        if group_col:
            row["n_unique_trades"] = int(pl.Series(
                frame[group_col].to_numpy()[sel]).n_unique())
        for mname, fn in metrics.items():
            try:
                row[mname] = fn(sel)
            except Exception:
                row[mname] = None
        rows.append(row)
    return pl.DataFrame(rows)


def monotonicity(tbl: pl.DataFrame, col: str) -> dict:
    """Spearman of bucket index vs `col`, plus adjacent inversions. Bucket 0 is
    `all`, which is not a tail, so the trend is measured over the tail buckets."""
    if tbl.is_empty() or col not in tbl.columns:
        return {"spearman": None, "inversions": None}
    v = tbl.filter(pl.col("bucket") != "all")[col].cast(pl.Float64, strict=False).to_numpy()
    v = v.astype(float)
    if np.isnan(v).any() or v.size < 3:
        return {"spearman": None, "inversions": None}
    # Buckets arrive LOOSEST -> TIGHTEST, so tightness is the position index.
    # See analysis/gates._spearman for why the orientation is pinned by a test.
    tight = np.arange(v.size, dtype=float)
    rx = np.argsort(np.argsort(tight)).astype(float)
    ry = np.argsort(np.argsort(v)).astype(float)
    sp = float(np.corrcoef(rx, ry)[0, 1])
    inv = int(np.sum(np.diff(v) < 0))
    return {"spearman": sp, "inversions": inv}


def boot_ci(values: np.ndarray, groups: np.ndarray | None = None,
            n: int = N_BOOT, seed: int = SEED) -> tuple[float, float]:
    """Trade-clustered bootstrap when `groups` is given, i.i.d. otherwise."""
    rng = np.random.default_rng(seed)
    if values.size == 0:
        return (float("nan"), float("nan"))
    if groups is None:
        draws = rng.choice(values, size=(n, values.size), replace=True).mean(axis=1)
    else:
        uniq, inv = np.unique(groups, return_inverse=True)
        buckets = [values[inv == i] for i in range(uniq.size)]
        draws = np.empty(n)
        for b in range(n):
            pick = rng.integers(0, uniq.size, uniq.size)
            draws[b] = np.concatenate([buckets[i] for i in pick]).mean()
    return (float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975)))

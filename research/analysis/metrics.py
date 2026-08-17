"""Canonical metrics with safe empty / one-class / NaN behaviour (A0 §7).

Every metric returns a `MetricResult`, never a bare float. At the sample sizes these
collections produce, a slice can easily be empty or single-class, and an AUC printed
as `0.5` or `nan` in that situation is worse than an explicit refusal — it looks like
a measurement. `not_computable` carries the reason so a report can say why.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

METRIC_DEFINITIONS: Dict[str, str] = {
    "sample_count": "Number of rows in the slice after all declared filters.",
    "positive_rate": "Mean of the binary target; the slice's base rate.",
    "roc_auc": "Area under the ROC curve. Undefined unless both classes are present.",
    "pr_auc": "Average precision (area under the precision-recall curve). Undefined unless both classes are present.",
    "brier": "Mean squared error between predicted probability and the binary outcome. Lower is better.",
    "win_rate": "Fraction of resolved trades with a positive return.",
    "expected_value": "Mean return per row, in the units of the supplied return column.",
    "mfe": "Maximum favourable excursion; reported as mean and the declared quantiles.",
    "mae": "Maximum adverse excursion; reported as mean and the declared quantiles.",
    "drawdown": "Maximum peak-to-trough decline of the cumulative return series.",
    "quantiles": "Empirical quantiles of a numeric series, NaNs excluded and counted.",
}

NOT_COMPUTABLE = "not_computable"


def _non_finite_reason(value: Any, extra: Optional[Dict[str, Any]] = None) -> str:
    """Names the first non-finite number in a result, or '' if everything is finite."""

    def scan(v: Any, path: str) -> str:
        if isinstance(v, (np.floating, np.integer)):
            v = v.item()
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            kind = "NaN" if math.isnan(v) else "infinite"
            return f"{kind} value{'' if not path else f' in {path}'}"
        if isinstance(v, dict):
            for k, x in v.items():
                hit = scan(x, f"{path}.{k}" if path else str(k))
                if hit:
                    return hit
        if isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                hit = scan(x, f"{path}[{i}]" if path else f"[{i}]")
                if hit:
                    return hit
        return ""

    return scan(value, "") or scan(extra or {}, "")


@dataclass
class MetricResult:
    name: str
    value: Optional[float] = None
    computable: bool = True
    reason: str = ""
    n: int = 0
    n_missing: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """A non-finite result is not a measurement (M6).

        `_jsonable` used to turn inf/NaN into a bare `null` while `status` stayed
        `"ok"`, so on the wire a computed-but-undefined metric was byte-identical to
        an *absent* metric — collapsing exactly the distinction this layer exists to
        make. Downgrade at construction so `.computable` is honest everywhere, not
        only in `to_dict()`.
        """
        if not self.computable:
            return
        reason = _non_finite_reason(self.value, self.extra)
        if reason:
            self.computable = False
            self.reason = reason
            self.value = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.name,
            "value": None if not self.computable else _jsonable(self.value),
            "status": "ok" if self.computable else NOT_COMPUTABLE,
            "reason": self.reason,
            "n": self.n,
            "n_missing": self.n_missing,
            "definition": METRIC_DEFINITIONS.get(self.name, ""),
            **({"extra": {k: _jsonable(v) for k, v in self.extra.items()}} if self.extra else {}),
        }


def _jsonable(v: Any) -> Any:
    if isinstance(v, (np.floating, np.integer)):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def _clean(y: Sequence, *, name: str) -> "tuple[np.ndarray, int]":
    arr = pd.Series(list(y), dtype="float64") if not isinstance(y, pd.Series) else y.astype("float64")
    missing = int(arr.isna().sum())
    return arr.dropna().to_numpy(), missing


def _not_computable(name: str, reason: str, n: int = 0, n_missing: int = 0) -> MetricResult:
    return MetricResult(name=name, value=None, computable=False, reason=reason, n=n, n_missing=n_missing)


# ---------------------------------------------------------------------------
# Classification metrics
# ---------------------------------------------------------------------------


def sample_count(y: Sequence) -> MetricResult:
    n = len(y)
    return MetricResult("sample_count", float(n), n=n)


def positive_rate(y: Sequence) -> MetricResult:
    arr, missing = _clean(y, name="positive_rate")
    if arr.size == 0:
        return _not_computable("positive_rate", "empty slice", 0, missing)
    return MetricResult("positive_rate", float(arr.mean()), n=int(arr.size), n_missing=missing)


def _both_classes(arr: np.ndarray) -> bool:
    return np.unique(arr).size >= 2


def roc_auc(y_true: Sequence, y_score: Sequence) -> MetricResult:
    return _auc_like("roc_auc", y_true, y_score)


def pr_auc(y_true: Sequence, y_score: Sequence) -> MetricResult:
    return _auc_like("pr_auc", y_true, y_score)


def _auc_like(name: str, y_true: Sequence, y_score: Sequence) -> MetricResult:
    yt = pd.Series(list(y_true), dtype="float64")
    ys = pd.Series(list(y_score), dtype="float64")
    if len(yt) != len(ys):
        return _not_computable(name, f"length mismatch: {len(yt)} labels vs {len(ys)} scores")
    keep = ~(yt.isna() | ys.isna())
    missing = int((~keep).sum())
    yt_c, ys_c = yt[keep].to_numpy(), ys[keep].to_numpy()

    if yt_c.size == 0:
        return _not_computable(name, "empty slice", 0, missing)
    if not _both_classes(yt_c):
        only = float(np.unique(yt_c)[0])
        return _not_computable(
            name, f"single-class slice (all y={only:g}); {name} is undefined", int(yt_c.size), missing
        )
    # sklearn raises on +/-inf. One infinite score must not abort a whole table build,
    # so refuse the metric explicitly instead of letting the exception escape (M6).
    if not np.isfinite(ys_c).all() or not np.isfinite(yt_c).all():
        n_bad = int((~np.isfinite(ys_c)).sum() + (~np.isfinite(yt_c)).sum())
        return _not_computable(
            name, f"{n_bad} non-finite value(s) in labels or scores; {name} is undefined",
            int(yt_c.size), missing,
        )
    try:
        from sklearn.metrics import average_precision_score, roc_auc_score

        fn = roc_auc_score if name == "roc_auc" else average_precision_score
        return MetricResult(name, float(fn(yt_c, ys_c)), n=int(yt_c.size), n_missing=missing)
    except ImportError:
        return _not_computable(name, "scikit-learn is not installed", int(yt_c.size), missing)
    except ValueError as err:
        return _not_computable(name, f"scikit-learn refused the input: {err}",
                               int(yt_c.size), missing)


def brier(y_true: Sequence, y_prob: Sequence) -> MetricResult:
    yt = pd.Series(list(y_true), dtype="float64")
    yp = pd.Series(list(y_prob), dtype="float64")
    if len(yt) != len(yp):
        return _not_computable("brier", f"length mismatch: {len(yt)} vs {len(yp)}")
    keep = ~(yt.isna() | yp.isna())
    missing = int((~keep).sum())
    yt_c, yp_c = yt[keep].to_numpy(), yp[keep].to_numpy()
    if yt_c.size == 0:
        return _not_computable("brier", "empty slice", 0, missing)
    return MetricResult("brier", float(np.mean((yp_c - yt_c) ** 2)), n=int(yt_c.size), n_missing=missing)


# ---------------------------------------------------------------------------
# Economic metrics
# ---------------------------------------------------------------------------


def win_rate(returns: Sequence) -> MetricResult:
    arr, missing = _clean(returns, name="win_rate")
    if arr.size == 0:
        return _not_computable("win_rate", "empty slice", 0, missing)
    return MetricResult("win_rate", float((arr > 0).mean()), n=int(arr.size), n_missing=missing)


def expected_value(returns: Sequence) -> MetricResult:
    arr, missing = _clean(returns, name="expected_value")
    if arr.size == 0:
        return _not_computable("expected_value", "empty slice", 0, missing)
    return MetricResult("expected_value", float(arr.mean()), n=int(arr.size), n_missing=missing,
                        extra={"std": float(arr.std(ddof=1)) if arr.size > 1 else None})


def excursion(values: Sequence, *, kind: str, quantiles: Sequence[float] = (0.5, 0.9)) -> MetricResult:
    """MFE / MAE summary: mean plus declared quantiles."""
    name = "mfe" if kind == "mfe" else "mae"
    arr, missing = _clean(values, name=name)
    if arr.size == 0:
        return _not_computable(name, "empty slice", 0, missing)
    qs = {f"q{int(q * 100)}": float(np.quantile(arr, q)) for q in quantiles}
    return MetricResult(name, float(arr.mean()), n=int(arr.size), n_missing=missing, extra=qs)


def drawdown(returns: Sequence) -> MetricResult:
    arr, missing = _clean(returns, name="drawdown")
    if arr.size == 0:
        return _not_computable("drawdown", "empty slice", 0, missing)
    equity = np.cumsum(arr)
    peak = np.maximum.accumulate(equity)
    dd = float(np.min(equity - peak))
    return MetricResult("drawdown", dd, n=int(arr.size), n_missing=missing,
                        extra={"final_equity": float(equity[-1])})


def quantiles(values: Sequence, qs: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9)) -> MetricResult:
    arr, missing = _clean(values, name="quantiles")
    if arr.size == 0:
        return _not_computable("quantiles", "empty slice", 0, missing)
    out = {f"q{int(q * 100)}": float(np.quantile(arr, q)) for q in qs}
    return MetricResult("quantiles", None, n=int(arr.size), n_missing=missing, extra=out)


# ---------------------------------------------------------------------------
# Bundles
# ---------------------------------------------------------------------------


def classification_bundle(y_true: Sequence, y_score: Optional[Sequence] = None) -> Dict[str, Dict[str, Any]]:
    """Metrics computable from labels alone, plus score-based ones when scores exist."""
    out = {
        "sample_count": sample_count(y_true).to_dict(),
        "positive_rate": positive_rate(y_true).to_dict(),
    }
    if y_score is not None:
        out["roc_auc"] = roc_auc(y_true, y_score).to_dict()
        out["pr_auc"] = pr_auc(y_true, y_score).to_dict()
        out["brier"] = brier(y_true, y_score).to_dict()
    return out


def economic_bundle(
    returns: Optional[Sequence] = None,
    mfe: Optional[Sequence] = None,
    mae: Optional[Sequence] = None,
) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if returns is not None:
        out["win_rate"] = win_rate(returns).to_dict()
        out["expected_value"] = expected_value(returns).to_dict()
        out["drawdown"] = drawdown(returns).to_dict()
    if mfe is not None:
        out["mfe"] = excursion(mfe, kind="mfe").to_dict()
    if mae is not None:
        out["mae"] = excursion(mae, kind="mae").to_dict()
    return out

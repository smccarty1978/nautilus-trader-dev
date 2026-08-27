"""Descriptive summaries of observed forward paths.

The question this layer serves is "does model confidence rank economic path quality?",
and it is answered descriptively -- never by choosing a rule.

Two methodological commitments are wired in rather than left to the caller:

* **Censored rows are counted, not dropped.** A censored path has a truncated maximum,
  so pooling it into a median understates the tail. Every group therefore reports
  ``n``, ``n_resolved`` and ``censored_fraction``, and path statistics are computed on
  resolved rows only. A group whose censored fraction is large is a group whose
  statistics are about the paths that happened to fit inside the window.
* **Thresholds come from the study.** ``P(MFE >= x ATR)`` needs an ``x``, and the
  framework does not supply one. :class:`OutcomeAnalysisConfig` carries the study's
  declared thresholds so a framework constant can never become an implicit finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from research_workflow.forward_outcomes.contracts import (
    ForwardOutcomeError,
    OutcomeStatus,
    horizon_label,
)

_UNIT_SUFFIX = {"points": "", "atr": "_atr", "ticks": "_ticks"}


@dataclass(frozen=True)
class OutcomeAnalysisConfig:
    """Study-declared analysis parameters. The framework contributes no thresholds."""

    mfe_thresholds: Sequence[float] = ()
    mae_thresholds: Sequence[float] = ()
    quantiles: Sequence[float] = (0.5, 0.75, 0.90)
    horizons_seconds: Sequence[int] = ()
    excursion_unit: str = "atr"
    min_group_size: int = 1

    def __post_init__(self) -> None:
        if self.excursion_unit not in _UNIT_SUFFIX:
            raise ForwardOutcomeError(f"unknown excursion_unit: {self.excursion_unit!r}")
        if any(not (0.0 < float(q) < 1.0) for q in self.quantiles):
            raise ForwardOutcomeError("quantiles must lie strictly between 0 and 1")

    @property
    def suffix(self) -> str:
        return _UNIT_SUFFIX[self.excursion_unit]


def _q_label(q: float) -> str:
    return f"p{int(round(float(q) * 100))}"


def _stats(series: pd.Series, config: OutcomeAnalysisConfig, prefix: str) -> dict[str, Any]:
    clean = series.dropna().astype(float)
    out: dict[str, Any] = {f"{prefix}_n": int(len(clean))}
    if clean.empty:
        for q in config.quantiles:
            out[f"{prefix}_{_q_label(q)}"] = None
        out[f"{prefix}_mean"] = None
        return out
    for q in config.quantiles:
        out[f"{prefix}_{_q_label(q)}"] = float(clean.quantile(float(q)))
    out[f"{prefix}_mean"] = float(clean.mean())
    return out


def _exceedance(series: pd.Series, thresholds: Iterable[float], prefix: str, *, at_least: bool) -> dict[str, Any]:
    clean = series.dropna().astype(float)
    out: dict[str, Any] = {}
    for level in thresholds:
        key = f"{prefix}_{f'{float(level):g}'.replace('.', 'p')}"
        if clean.empty:
            out[key] = None
            continue
        hits = (clean >= float(level)) if at_least else (clean <= float(level))
        out[key] = float(hits.mean())
    return out


def summarize_group(frame: pd.DataFrame, config: OutcomeAnalysisConfig) -> dict[str, Any]:
    """All declared statistics for one already-selected slice."""
    suffix = config.suffix
    row: dict[str, Any] = {"n": int(len(frame))}

    if "outcome_status" in frame.columns:
        resolved_mask = frame["outcome_status"] == OutcomeStatus.RESOLVED.value
        row["n_resolved"] = int(resolved_mask.sum())
        row["n_censored"] = int((~resolved_mask).sum())
        row["censored_fraction"] = float((~resolved_mask).mean()) if len(frame) else None
        resolved = frame.loc[resolved_mask]
    else:
        row["n_resolved"] = int(len(frame))
        row["n_censored"] = 0
        row["censored_fraction"] = 0.0
        resolved = frame

    for disposition_col in sorted(
        c for c in frame.columns
        if c.startswith("ordered_") and c.endswith("_disposition")
    ):
        prefix = disposition_col.removesuffix("_disposition")
        values = frame[disposition_col].dropna().astype(str)
        row[f"{prefix}_n_terminal"] = int(len(values))
        for disposition in (
            "SUCCESS", "FAILURE", "TIMEOUT", "AMBIGUOUS_FIRST_TOUCH", "CENSORED"
        ):
            count = int((values == disposition).sum())
            row[f"{prefix}_n_{disposition.lower()}"] = count
            row[f"{prefix}_fraction_{disposition.lower()}"] = (
                float(count / len(values)) if len(values) else None
            )
        label_col = f"{prefix}_binary_label"
        if label_col in frame.columns:
            labels = frame[label_col].dropna().astype(int)
            row[f"{prefix}_n_binary"] = int(len(labels))
            row[f"{prefix}_positive_rate"] = (
                float(labels.mean()) if len(labels) else None
            )

    if "confirmed" in frame.columns:
        confirmed = frame["confirmed"].dropna()
        row["confirmation_rate"] = float(confirmed.astype(bool).mean()) if len(confirmed) else None
        row["n_confirmation_unknown"] = int(len(frame) - len(confirmed))
        if "seconds_to_confirmation" in frame.columns:
            row.update(_stats(frame["seconds_to_confirmation"], config, "seconds_to_confirmation"))

    max_mfe = f"max_mfe{suffix}"
    max_mae = f"max_mae{suffix}"
    if max_mfe in resolved.columns:
        row.update(_stats(resolved[max_mfe], config, "max_mfe"))
        row.update(_exceedance(resolved[max_mfe], config.mfe_thresholds, "p_mfe_ge", at_least=True))
    if max_mae in resolved.columns:
        row.update(_stats(resolved[max_mae], config, "max_mae"))
        row.update(_exceedance(resolved[max_mae], config.mae_thresholds, "p_mae_le", at_least=False))
    if "time_to_max_mfe" in resolved.columns:
        row.update(_stats(resolved["time_to_max_mfe"], config, "time_to_max_mfe"))
    if "time_to_max_mae" in resolved.columns:
        row.update(_stats(resolved["time_to_max_mae"], config, "time_to_max_mae"))
    if f"final_return{suffix}" in resolved.columns:
        row.update(_stats(resolved[f"final_return{suffix}"], config, "final_return"))
    if "max_mfe_mae_ratio" in resolved.columns:
        row.update(_stats(resolved["max_mfe_mae_ratio"], config, "mfe_mae_ratio"))

    for seconds in config.horizons_seconds:
        lab = horizon_label(seconds)
        # A horizon carries its own status: a row resolved overall can still hold a
        # session-censored horizon, and pooling those would understate the excursion.
        status_col = f"status_{lab}"
        slice_ = resolved
        if status_col in resolved.columns:
            slice_ = resolved.loc[resolved[status_col] == OutcomeStatus.RESOLVED.value]
        row[f"n_resolved_{lab}"] = int(len(slice_))
        for metric in ("mfe", "mae", "return"):
            col = f"{metric}_{lab}{suffix}"
            if col in slice_.columns:
                row.update(_stats(slice_[col], config, f"{metric}_{lab}"))
        if f"mfe_{lab}{suffix}" in slice_.columns:
            row.update(_exceedance(
                slice_[f"mfe_{lab}{suffix}"], config.mfe_thresholds, f"p_mfe_{lab}_ge", at_least=True
            ))
        if f"mae_{lab}{suffix}" in slice_.columns:
            row.update(_exceedance(
                slice_[f"mae_{lab}{suffix}"], config.mae_thresholds, f"p_mae_{lab}_le", at_least=False
            ))

    for prefix in ("pre_confirmation", "post_confirmation"):
        for metric in ("mfe", "mae"):
            col = f"{prefix}_{metric}{suffix}"
            if col in resolved.columns:
                row.update(_stats(resolved[col], config, f"{prefix}_{metric}"))
    return row


def summarize_outcomes(
    frame: pd.DataFrame,
    config: OutcomeAnalysisConfig,
    *,
    group_by: Sequence[str] = (),
) -> pd.DataFrame:
    """Summary table, optionally grouped by any causal descriptor of the entry."""
    if frame.empty:
        return pd.DataFrame()
    keys = list(group_by)
    missing = [k for k in keys if k not in frame.columns]
    if missing:
        raise ForwardOutcomeError(f"grouping columns not present in outcome frame: {missing}")
    if not keys:
        return pd.DataFrame([{"group": "ALL", **summarize_group(frame, config)}])

    rows: list[dict[str, Any]] = []
    for key, group in frame.groupby(keys, dropna=False, sort=True):
        values = key if isinstance(key, tuple) else (key,)
        if len(group) < config.min_group_size:
            continue
        rows.append({**{k: v for k, v in zip(keys, values)}, **summarize_group(group, config)})
    return pd.DataFrame(rows)


def confidence_ranking_report(
    frame: pd.DataFrame,
    config: OutcomeAnalysisConfig,
    *,
    rank_column: str,
    metrics: Sequence[str] = ("max_mfe_p50", "max_mae_p50", "final_return_p50"),
    group_by: Sequence[str] = (),
) -> dict[str, Any]:
    """Does higher model confidence rank better economic paths?

    Reports the Spearman rank correlation between the ordered confidence bucket and each
    summary metric. This measures monotonic ordering only -- it says nothing about
    whether the spread is large enough to trade, and must not be read as if it did.
    """
    if rank_column not in frame.columns:
        raise ForwardOutcomeError(f"rank column {rank_column!r} is not in the outcome frame")
    keys = [*group_by, rank_column]
    table = summarize_outcomes(frame, config, group_by=keys)
    if table.empty:
        return {"rank_column": rank_column, "buckets": 0, "rankings": {}, "table": table}

    rankings: dict[str, Any] = {}
    ordered = table.sort_values(rank_column, kind="mergesort")
    ranks = pd.Series(range(len(ordered)), index=ordered.index, dtype=float)
    for metric in metrics:
        if metric not in ordered.columns:
            rankings[metric] = None
            continue
        values = ordered[metric].astype(float)
        mask = values.notna()
        if mask.sum() < 3:
            rankings[metric] = None
            continue
        rankings[metric] = float(
            np.corrcoef(ranks[mask].rank(), values[mask].rank())[0, 1]
        )
    return {
        "rank_column": rank_column,
        "buckets": int(len(ordered)),
        "rankings": rankings,
        "n_total": int(len(frame)),
        "censored_fraction_overall": (
            float((frame["outcome_status"] != OutcomeStatus.RESOLVED.value).mean())
            if "outcome_status" in frame.columns else None
        ),
        "table": ordered.reset_index(drop=True),
    }

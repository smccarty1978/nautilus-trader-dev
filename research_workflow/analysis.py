"""Structured, provenance-bound experiment analysis."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import numpy as np
import pandas as pd

from research.analysis.metrics import classification_bundle
from research_workflow.experiment import assert_oos_open, load_authorization


def _metric_row(y: pd.Series, score: pd.Series) -> Dict[str, Any]:
    bundle = classification_bundle(y, score)
    return {k: (v.to_dict() if hasattr(v, "to_dict") else v) for k, v in bundle.items()}


def classification_results(
    frame: pd.DataFrame,
    *,
    score_columns: Mapping[str, str],
    target_column: str,
    direction_column: str = "regime_direction",
    maturity_column: str = "maturity_bucket",
) -> Dict[str, Any]:
    """Return model/direction/maturity metrics without pooling away the slices."""
    required = [target_column, *score_columns.values()]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(f"analysis frame missing required columns: {missing}")
    out: Dict[str, Any] = {"overall": {}, "by_direction": {}, "by_maturity": {}, "by_direction_maturity": {}}
    for model, col in score_columns.items():
        sub = frame[[target_column, col]].dropna()
        out["overall"][model] = _metric_row(sub[target_column].astype(int), sub[col].astype(float))
        if direction_column in frame:
            out["by_direction"][model] = {
                str(key): _metric_row(g[target_column].astype(int), g[col].astype(float))
                for key, g in frame.groupby(direction_column, dropna=False)
            }
        if maturity_column in frame:
            out["by_maturity"][model] = {
                str(key): _metric_row(g[target_column].astype(int), g[col].astype(float))
                for key, g in frame.groupby(maturity_column, dropna=False)
            }
            if direction_column in frame:
                out["by_direction_maturity"][model] = {
                    f"{d}|{m}": _metric_row(g[target_column].astype(int), g[col].astype(float))
                    for (d, m), g in frame.groupby([direction_column, maturity_column], dropna=False)
                }
    return out


def incremental_results(results: Mapping[str, Any], *, baseline: str = "A", structural: str = "B", rolling: str = "C") -> Dict[str, Any]:
    """Compare scalar metric values where available; retain caveats for undefined cells."""
    def diff(path: str, left: str, right: str) -> Any:
        try:
            a = results[path][left]["roc_auc"]["value"]
            b = results[path][right]["roc_auc"]["value"]
            return None if a is None or b is None else float(b - a)
        except (KeyError, TypeError):
            return None
    return {"B-A": diff("overall", baseline, structural), "C-B": diff("overall", structural, rolling), "C-A": diff("overall", baseline, rolling)}


def score_deciles(frame: pd.DataFrame, score_column: str, *, n_deciles: int = 10, target_column: str = "target") -> list[dict[str, Any]]:
    """Build deterministic score deciles; ties use stable row order."""
    if score_column not in frame or target_column not in frame:
        raise ValueError("score and target columns are required")
    work = frame[[score_column, target_column]].copy().dropna().reset_index(drop=True)
    if work.empty:
        return []
    work["_rank"] = work[score_column].rank(method="first", ascending=True)
    work["decile"] = np.minimum(n_deciles - 1, ((work["_rank"] - 1) * n_deciles // len(work)).astype(int)) + 1
    return [{"decile": int(k), "n": int(len(g)), "flip_rate": float(g[target_column].mean())} for k, g in work.groupby("decile", sort=True)]


def first_crossings(frame: pd.DataFrame, *, score_column: str, threshold_records: Mapping[str, Mapping[str, Any]], regime_column: str, timestamp_column: str, flip_timestamp_column: str) -> list[dict[str, Any]]:
    """One first threshold crossing per regime/threshold, using frozen TRAIN thresholds."""
    work = frame.sort_values([regime_column, timestamp_column], kind="mergesort")
    rows: list[dict[str, Any]] = []
    for label, rec in threshold_records.items():
        threshold = float(rec["threshold"])
        for regime, group in work.groupby(regime_column, sort=False):
            armed = group[group[score_column] >= threshold]
            if armed.empty:
                continue
            first = armed.iloc[0]
            t = pd.Timestamp(first[timestamp_column])
            flip = pd.Timestamp(first[flip_timestamp_column])
            rows.append({"threshold": label, "regime": regime, "crossing_ts": t.isoformat(), "seconds_to_flip": float((flip - t).total_seconds())})
    return rows


def analyze_results(
    study_path: str | Path,
    frame: pd.DataFrame,
    *,
    score_columns: Mapping[str, str],
    target_column: str,
    output_name: str = "experiment_analysis.json",
    oos_run_id: str | None = None,
    oos_dataset_identity_sha256: str | None = None,
) -> Dict[str, Any]:
    """Persist a structured OOS analysis artifact bound to its full lineage (RT-13).

    Beyond ``study_id`` / ``authorization_sha256``, the artifact binds the exact TRAIN
    freeze file bytes, the frozen model ids, the stage-scoped closures, the OOS
    authorization + run/dataset identity, and this analysis code's own identity, plus a
    self-binding ``identity_sha256``. ``research_workflow.oos_analysis_lineage.
    classify_oos_analysis`` re-resolves all of it and returns FRESH / STALE / INVALID.
    """
    from research.analysis.modeling import frame_content_identity
    from research_workflow.oos_analysis_lineage import build_oos_analysis_identity

    path = Path(study_path).resolve()
    auth = load_authorization(path)
    # Analysis is an OOS operation; this gate also verifies a TRAIN freeze exists and is
    # bound to the current authorization, and returns the freeze payload.
    freeze = assert_oos_open(path)
    result = classification_results(frame, score_columns=score_columns, target_column=target_column)
    if oos_dataset_identity_sha256 is None:
        oos_dataset_identity_sha256 = frame_content_identity(frame.reindex(sorted(frame.columns), axis=1))
    result.update({
        "study_id": auth.study_id,
        "authorization_sha256": auth.authorization_sha256,
        "rows": int(len(frame)),
        "oos_analysis_identity": build_oos_analysis_identity(
            path, freeze=freeze, oos_run_id=oos_run_id,
            oos_dataset_identity_sha256=oos_dataset_identity_sha256,
        ),
    })
    out = path / "artifacts" / output_name
    out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    return result

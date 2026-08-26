"""Derived-score threshold-upcross population derivation.
=========================================================

Generic, reusable derivation of a population defined by: score a checkpoint stream with a
frozen upstream model, then select the first strict below-to-above threshold crossing per
regime. This is the offline counterpart to the generic collector's identity-allowlist
qualification mode (`research_workflow/generic_collector.py`'s
`required_checkpoint_identities_path` -- see `docs/RESEARCH_WORKFLOW.md` §7): this script
BUILDS the frozen `(regime_start_ns, checkpoint_index)` identity table that mode consumes.

Not specific to any one study, model, or threshold. Extracted after being independently
reimplemented twice for `clean_tradable_reversal` (TRAIN 2021-2023, then OOS 2024) with
identical logic -- a third study needing the same population shape should call this instead
of writing a third copy.

Semantics (fixed, not configurable -- a different crossing rule is a different function):
  - Strict upcross: score_t >= threshold AND the immediately preceding eligible checkpoint
    in the same regime has score < threshold. No persistence rule, no cadence resampling.
  - A regime whose first eligible checkpoint is already >= threshold is
    LEFT_CENSORED_ABOVE_THRESHOLD and excluded entirely (its later checkpoints, if any,
    can never produce a real upcross -- the regime never observed the crossing).
  - First upcross per regime only, deterministic tie-break by `order_columns`.

Usage (library):
    from scripts.build_derived_score_upcross_population import (
        score_with_frozen_model, select_first_upcross_per_regime,
    )
    df["score"] = score_with_frozen_model(
        df, model_artifact_path=..., model_keys_by_direction={"LONG": "LONG_C", "SHORT": "SHORT_C"},
        feature_columns=[...],
    )
    selected, diagnostics = select_first_upcross_per_regime(
        df, score_column="score", threshold_by_direction={"LONG": 0.4365, "SHORT": 0.4215},
    )

Usage (CLI):
    python scripts/build_derived_score_upcross_population.py \\
        --checkpoints checkpoints.parquet --model-artifact frozen_models.joblib \\
        --model-key LONG=LONG_C --model-key SHORT=SHORT_C \\
        --feature-column arrival_velocity --feature-column ema_slope ... \\
        --threshold LONG=0.4365 --threshold SHORT=0.4215 \\
        --regime-direction-map "-1=LONG,1=SHORT" \\
        --out population.parquet --report report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd


class UpcrossPopulationError(RuntimeError):
    """Raised on a malformed checkpoint stream, model artifact, or threshold declaration."""


def _resolve_estimator(record: Any) -> Any:
    """A frozen-model joblib entry may be the raw estimator or a provenance dict wrapping
    it (`{"estimator": ..., "provenance": ..., "fit_identity_sha256": ...}`, the shape
    `research.analysis.modeling.write_model_manifest` produces). Accept either."""
    if hasattr(record, "predict_proba"):
        return record
    if isinstance(record, Mapping):
        est = record.get("estimator") or record.get("model")
        if est is not None and hasattr(est, "predict_proba"):
            return est
    raise UpcrossPopulationError(
        f"UNRESOLVABLE_ESTIMATOR: joblib record has no usable predict_proba "
        f"(type={type(record).__name__})"
    )


def score_with_frozen_model(
    df: pd.DataFrame,
    *,
    model_artifact_path: str | Path,
    model_keys_by_direction: Mapping[str, str],
    feature_columns: Sequence[str],
    direction_column: str = "direction",
) -> pd.Series:
    """Scores every row with the frozen per-direction estimator named in
    `model_keys_by_direction`. Fails closed if any row's direction has no declared model
    key, or if any score comes back null (a silent partial score is worse than a crash)."""
    missing_dirs = set(df[direction_column].unique()) - set(model_keys_by_direction)
    if missing_dirs:
        raise UpcrossPopulationError(
            f"UNMAPPED_DIRECTIONS: {sorted(missing_dirs)} have no entry in "
            f"model_keys_by_direction={dict(model_keys_by_direction)}"
        )
    bundle = joblib.load(model_artifact_path)
    score = pd.Series(np.nan, index=df.index, dtype="float64")
    for direction, model_key in model_keys_by_direction.items():
        mask = df[direction_column] == direction
        if not mask.any():
            continue
        if model_key not in bundle:
            raise UpcrossPopulationError(
                f"MODEL_KEY_NOT_IN_ARTIFACT: {model_key!r} not found in "
                f"{model_artifact_path} (keys: {sorted(bundle.keys())})"
            )
        estimator = _resolve_estimator(bundle[model_key])
        score.loc[mask] = np.asarray(estimator.predict_proba(df.loc[mask, feature_columns]))[:, 1]
    if score.isna().any():
        raise UpcrossPopulationError(
            f"UNSCORED_ROWS: {int(score.isna().sum())} rows received no score"
        )
    return score


def select_first_upcross_per_regime(
    df: pd.DataFrame,
    *,
    score_column: str,
    threshold_by_direction: Mapping[str, float],
    direction_column: str = "direction",
    regime_key_columns: Sequence[str] = ("direction", "regime_start_ns"),
    order_columns: Sequence[str] = ("observation_ts", "checkpoint_index"),
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Pure upcross-selection primitive -- takes an already-scored, already-directioned
    frame. Returns (selected_rows, diagnostics). Does not touch chronology, causality, or
    any market data; the caller is responsible for the input frame's own causal integrity."""
    missing_dirs = set(df[direction_column].unique()) - set(threshold_by_direction)
    if missing_dirs:
        raise UpcrossPopulationError(
            f"UNMAPPED_DIRECTIONS: {sorted(missing_dirs)} have no entry in "
            f"threshold_by_direction={dict(threshold_by_direction)}"
        )

    work = df.copy()
    work["_threshold"] = work[direction_column].map(threshold_by_direction)
    work["_above"] = work[score_column] >= work["_threshold"]
    work["_regime_key"] = list(zip(*(work[c] for c in regime_key_columns)))

    sort_cols = ["_regime_key", *order_columns]
    work = work.sort_values(sort_cols, kind="mergesort")
    work["_prev_above"] = work.groupby("_regime_key")["_above"].shift(1)
    work["_is_first_in_regime"] = work["_prev_above"].isna()
    work["_is_left_censored"] = work["_is_first_in_regime"] & work["_above"]
    work["_is_upcross"] = work["_above"] & (work["_prev_above"] == False)  # noqa: E712

    left_censored_regimes = set(work.loc[work["_is_left_censored"], "_regime_key"])
    total_regimes = int(work["_regime_key"].nunique())
    multi_cross_regimes = int(work[work["_is_upcross"]].groupby("_regime_key").size().gt(1).sum())

    # `left_censored_above_threshold` is DIAGNOSTIC ONLY -- it does not remove the regime
    # from selection. A left-censored regime's own first checkpoint can mechanically never
    # be `_is_upcross` (its `_prev_above` is NaN, not False), so its ambiguous initial state
    # is never selected regardless; but a genuine later below-to-above transition within
    # that same regime (a real dip then recross, fully observed) IS a valid, non-censored
    # crossing and remains eligible. Excluding the whole regime here was tried and is a
    # documented mistake (research corrective note in docs/RESEARCH_WORKFLOW.md §7): it
    # silently dropped ~34/8533 (~0.4%) real TRAIN identities relative to the frozen,
    # already-verified-via-live-collection population.
    upcrosses = work[work["_is_upcross"]].sort_values(sort_cols, kind="mergesort")
    selected = upcrosses.groupby("_regime_key", as_index=False, sort=False).head(1)

    diagnostics = {
        "total_checkpoints": int(len(df)),
        "total_regimes": total_regimes,
        "left_censored_above_threshold_regimes": len(left_censored_regimes),
        "multiple_crossing_regimes": multi_cross_regimes,
        "selected_count": int(len(selected)),
        "selected_by_direction": {
            str(d): int(n) for d, n in selected[direction_column].value_counts().items()
        },
    }
    selected = selected.drop(columns=["_threshold", "_above", "_regime_key", "_prev_above",
                                       "_is_first_in_regime", "_is_left_censored", "_is_upcross"])
    return selected.reset_index(drop=True), diagnostics


def build_derived_score_upcross_population(
    checkpoints: pd.DataFrame,
    *,
    model_artifact_path: str | Path,
    model_keys_by_direction: Mapping[str, str],
    feature_columns: Sequence[str],
    threshold_by_direction: Mapping[str, float],
    regime_direction_map: Mapping[int, str] | None = None,
    raw_direction_column: str = "regime_direction",
    direction_column: str = "direction",
    regime_key_columns: Sequence[str] = ("direction", "regime_start_ns"),
    order_columns: Sequence[str] = ("observation_ts", "checkpoint_index"),
    score_column: str = "score",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """End-to-end orchestrator: map raw direction -> label, score, select. `checkpoints`
    must already carry `raw_direction_column` (or `direction_column` directly, if
    `regime_direction_map` is None) and every column in `feature_columns`."""
    df = checkpoints.copy()
    if regime_direction_map is not None:
        if direction_column not in df.columns:
            df[direction_column] = df[raw_direction_column].map(regime_direction_map)
        unmapped = df[direction_column].isna().sum()
        if unmapped:
            raise UpcrossPopulationError(
                f"UNMAPPED_RAW_DIRECTIONS: {unmapped} rows failed "
                f"regime_direction_map={dict(regime_direction_map)}"
            )
    elif direction_column not in df.columns:
        raise UpcrossPopulationError(
            f"MISSING_DIRECTION_COLUMN: {direction_column!r} not present and no "
            f"regime_direction_map supplied"
        )

    df[score_column] = score_with_frozen_model(
        df, model_artifact_path=model_artifact_path, model_keys_by_direction=model_keys_by_direction,
        feature_columns=list(feature_columns), direction_column=direction_column,
    )
    return select_first_upcross_per_regime(
        df, score_column=score_column, threshold_by_direction=threshold_by_direction,
        direction_column=direction_column, regime_key_columns=regime_key_columns,
        order_columns=order_columns,
    )


def _parse_kv_floats(pairs: Sequence[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        out[key] = float(value)
    return out


def _parse_kv_strs(pairs: Sequence[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        out[key] = value
    return out


def _parse_regime_direction_map(spec: str) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for pair in spec.split(","):
        key, _, value = pair.partition("=")
        out[int(key)] = value
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checkpoints", required=True, help="Parquet: raw checkpoint stream (candidates, already merged with any direction/observation columns needed)")
    parser.add_argument("--model-artifact", required=True, help="Path to the frozen model joblib bundle")
    parser.add_argument("--model-key", action="append", required=True, metavar="DIRECTION=KEY", help="Repeatable, e.g. LONG=LONG_C")
    parser.add_argument("--feature-column", action="append", required=True, dest="feature_columns", metavar="NAME", help="Repeatable, in the exact order the frozen model expects")
    parser.add_argument("--threshold", action="append", required=True, metavar="DIRECTION=VALUE", help="Repeatable, e.g. LONG=0.43654834666810594")
    parser.add_argument("--regime-direction-map", default=None, metavar="RAW=LABEL,RAW=LABEL", help='e.g. "-1=LONG,1=SHORT" -- omit if the checkpoint stream already has a direction column')
    parser.add_argument("--raw-direction-column", default="regime_direction")
    parser.add_argument("--direction-column", default="direction")
    parser.add_argument("--out", required=True, help="Output parquet path for the selected population")
    parser.add_argument("--report", default=None, help="Optional output JSON path for diagnostics")
    args = parser.parse_args(argv)

    checkpoints = pd.read_parquet(args.checkpoints)
    selected, diagnostics = build_derived_score_upcross_population(
        checkpoints,
        model_artifact_path=args.model_artifact,
        model_keys_by_direction=_parse_kv_strs(args.model_key),
        feature_columns=args.feature_columns,
        threshold_by_direction=_parse_kv_floats(args.threshold),
        regime_direction_map=_parse_regime_direction_map(args.regime_direction_map) if args.regime_direction_map else None,
        raw_direction_column=args.raw_direction_column,
        direction_column=args.direction_column,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    selected.to_parquet(out_path, index=False)
    print(f"Selected {len(selected)} rows -> {out_path}")
    print(json.dumps(diagnostics, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Explicitly non-promotable A/B/C fit and 2024 OOS diagnostic.

Only NT-materialized rows enter this runner.  Direction-specific Top-25
selection and every model fit complete from 2021--2023 before the 2024 parquet
is opened.  Outputs are deliberately marked as contract-gate-blocked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import polars as pl
import yaml
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.collector import (
    BASELINE_CANDIDATES, ROLLING_FEATURES, STRUCTURAL_FEATURES,
)
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.execution import authorize_stage


PRIMARY_BUCKETS = ((300.0, 600.0, "300-600s"), (600.0, 900.0, "600-900s"), (900.0, 1800.0, "900-1800s"))
MODEL_BLOCKS = ("A_BASELINE", "B_PLUS_STRUCTURAL", "C_PLUS_ROLLING_5M")
PARAMS = {"max_depth": 3, "learning_rate": 0.05, "max_iter": 200, "random_state": 42}
MODE = "EXPLORATORY — CONTRACT GATE BLOCKED"
NS = 1_000_000_000
STUDY_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "study.yaml"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bucket(age_seconds: float) -> str | None:
    for lower, upper, name in PRIMARY_BUCKETS:
        if lower <= age_seconds < upper:
            return name
    return None


def _matrix(frame: pl.DataFrame, features: list[str]) -> np.ndarray:
    columns = []
    for feature in features:
        column = frame.get_column(feature).cast(pl.Float64, strict=False).to_numpy().astype(float)
        column[~np.isfinite(column)] = np.nan
        columns.append(column)
    return np.column_stack(columns)


def _valid_baselines(frame: pl.DataFrame) -> list[str]:
    valid = []
    for feature in BASELINE_CANDIDATES:
        if feature not in frame.columns:
            continue
        values = frame.get_column(feature).cast(pl.Float64, strict=False).to_numpy().astype(float)
        finite = values[np.isfinite(values)]
        if len(finite) >= 100 and np.nanmax(finite) > np.nanmin(finite):
            valid.append(feature)
    return valid


def _freeze_top25(train: pl.DataFrame, candidates: list[str]) -> list[str]:
    """Use mean univariate edge across the three train-year temporal folds."""
    ranked = []
    for feature in candidates:
        edges = []
        for year in (2021, 2022, 2023):
            fold = train.filter(pl.col("partition_year") == year)
            target = fold.get_column("flip_within_300s").to_numpy().astype(int)
            values = fold.get_column(feature).cast(pl.Float64, strict=False).to_numpy().astype(float)
            mask = np.isfinite(values)
            if mask.sum() < 25 or np.unique(target[mask]).size != 2:
                edges = []
                break
            edges.append(abs(float(roc_auc_score(target[mask], values[mask])) - 0.5))
        if len(edges) == 3:
            ranked.append((float(np.mean(edges)), feature))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = [feature for _, feature in ranked[:25]]
    if len(selected) != 25:
        raise RuntimeError(f"unable to freeze 25 train-only temporal-rank features; got {len(selected)}")
    return selected


def _metrics(y: np.ndarray, score: np.ndarray) -> dict[str, float | int | None]:
    if len(y) == 0:
        return {"n": 0, "positives": 0, "roc_auc": None, "pr_auc": None, "brier": None}
    return {"n": int(len(y)), "positives": int(y.sum()),
            "roc_auc": float(roc_auc_score(y, score)) if np.unique(y).size == 2 else None,
            "pr_auc": float(average_precision_score(y, score)) if np.unique(y).size == 2 else None,
            "brier": float(brier_score_loss(y, score))}


def _minimum_structural_coverage() -> float:
    config = yaml.safe_load(STUDY_CONFIG_PATH.read_text())
    value = config.get("structural_coverage", {}).get("minimum_complete_fraction_per_primary_directional_cell")
    if not isinstance(value, (int, float)) or not 0.0 < float(value) <= 1.0:
        raise RuntimeError("frozen structural coverage threshold is missing or invalid")
    return float(value)


def _assert_structural_coverage(frame: pl.DataFrame, split: str, minimum: float) -> list[dict]:
    """Fail closed when a B/C structural block is mostly unavailable."""
    missing = [name for name in ("structural_available", *STRUCTURAL_FEATURES) if name not in frame.columns]
    if missing:
        raise RuntimeError(f"{split} lacks structural coverage fields: {missing}")
    rows = []
    for value, direction in ((1, "SHORT"), (-1, "LONG")):
        for _, _, bucket in PRIMARY_BUCKETS:
            cell = frame.filter((pl.col("prevailing_direction") == value) & (pl.col("maturity_bucket") == bucket))
            if cell.height == 0:
                raise RuntimeError(f"{split} has empty {direction}/{bucket} coverage cell")
            complete = cell.filter(
                pl.col("structural_available").fill_null(False)
                & pl.all_horizontal([pl.col(name).is_finite() for name in STRUCTURAL_FEATURES])
            ).height
            coverage = complete / cell.height
            rows.append({"mode": MODE, "split": split, "direction": direction, "maturity_bucket": bucket,
                         "n": cell.height, "complete_structural_rows": complete, "coverage": coverage})
            if coverage < minimum:
                raise RuntimeError(
                    f"{split} {direction}/{bucket} structural coverage {coverage:.3%} is below "
                    f"the {minimum:.0%} minimum"
                )
    return rows


def _load_partitions(paths: list[Path], allowed_years: set[int], expected_phase0_sha: str) -> pl.DataFrame:
    partitions = []
    observed_partition_years = []
    for directory in paths:
        manifest = json.loads((directory / "manifest.json").read_text())
        year = int(manifest["start"][:4])
        expected_start = datetime(year, 1, 1, tzinfo=timezone.utc).isoformat()
        expected_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc).isoformat()
        if year not in allowed_years or manifest.get("start") != expected_start or manifest.get("end") != expected_end:
            raise RuntimeError(f"invalid authorized partition interval: {manifest.get('start')} -> {manifest.get('end')}")
        phase0_sha = manifest.get("phase0_sha256")
        if not isinstance(phase0_sha, str) or len(phase0_sha) != 64:
            raise RuntimeError(f"partition {directory} lacks a phase-zero hash")
        if phase0_sha != expected_phase0_sha:
            raise RuntimeError(f"partition {directory} has a different phase-zero lineage")
        features = directory / "features.parquet"
        if _sha(features) != manifest["features_sha256"]:
            raise RuntimeError(f"feature partition hash mismatch: {features}")
        partition = pl.read_parquet(features).with_columns(
            pl.from_epoch("checkpoint_decision_ns", time_unit="ns").dt.year().alias("_row_year")
        )
        actual_years = set(partition.get_column("_row_year").unique().to_list())
        if actual_years != {year}:
            raise RuntimeError(f"partition {features} contains timestamp years {sorted(actual_years)}, expected {year}")
        partitions.append(partition.drop("_row_year").with_columns(pl.lit(year).alias("partition_year")))
        observed_partition_years.append(year)
    if len(observed_partition_years) != len(set(observed_partition_years)) or set(observed_partition_years) != allowed_years:
        raise RuntimeError(f"expected exactly one partition for each year {sorted(allowed_years)}, got {sorted(observed_partition_years)}")
    frame = pl.concat(partitions, how="diagonal_relaxed")
    if "flip_within_300s" not in frame.columns:
        raise RuntimeError("partitions do not contain delayed NT flip labels")
    frame = frame.filter(
        (pl.col("prevailing_direction").is_in([-1, 1]))
        & (pl.col("regime_age_seconds") > 120.0)
        & (pl.col("running_mfe_atr") >= 1.0)
        & (pl.col("new_progress_windows") >= 2)
        & (pl.col("retained_mfe_ratio") >= 0.5)
        & ((pl.col("checkpoint_decision_ns") % (5 * NS)) == 0)
    )
    if frame.get_column("checkpoint_decision_ns").n_unique() != frame.height:
        raise RuntimeError("duplicate checkpoint_decision_ns values across partitions")
    ct = pl.from_epoch("checkpoint_decision_ns", time_unit="ns").dt.replace_time_zone("UTC").dt.convert_time_zone("America/Chicago")
    frame = frame.with_columns(ct.alias("_checkpoint_ct"))
    rth = ((pl.col("_checkpoint_ct").dt.hour() > 8) | ((pl.col("_checkpoint_ct").dt.hour() == 8) & (pl.col("_checkpoint_ct").dt.minute() >= 30))) & (pl.col("_checkpoint_ct").dt.hour() < 15)
    if not frame.select(rth.all()).item():
        raise RuntimeError("non-RTH checkpoint reached the frozen model population")
    frame = frame.drop("_checkpoint_ct")
    ages = frame.get_column("regime_age_seconds").to_numpy().astype(float)
    return frame.with_columns(pl.Series("maturity_bucket", [_bucket(age) for age in ages])).filter(
        pl.col("maturity_bucket").is_not_null()
    )


def run(train_dirs: list[Path], oos_dirs: list[Path], output_dir: Path) -> dict:
    if not train_dirs or not oos_dirs:
        raise RuntimeError("explicit train and OOS partition paths are required")
    output_dir.mkdir(parents=True, exist_ok=True)
    minimum_coverage = _minimum_structural_coverage()
    phase0_path = train_dirs[0] / "phase0_source_manifest.json"
    authorize_stage(phase0_path, "feature_freeze", [2021, 2022, 2023])
    current_phase0_sha = _sha(phase0_path)
    train = _load_partitions(train_dirs, {2021, 2022, 2023}, current_phase0_sha)
    if train.height == 0:
        raise RuntimeError("no eligible 2021-2023 rows")
    coverage_rows = _assert_structural_coverage(train, "TRAIN_2021_2023", minimum_coverage)
    valid = _valid_baselines(train)
    authorize_stage(phase0_path, "fit", [2021, 2022, 2023])
    frozen: dict[str, list[str]] = {}
    fitted: list[tuple[str, str, list[str], HistGradientBoostingClassifier]] = []
    model_dir = output_dir / "models"
    model_dir.mkdir(exist_ok=True)

    for direction_value, direction_name in ((1, "SHORT"), (-1, "LONG")):
        direction_train = train.filter(pl.col("prevailing_direction") == direction_value)
        if direction_train.height == 0:
            raise RuntimeError(f"missing {direction_name} training rows")
        top25 = _freeze_top25(direction_train, valid)
        frozen[direction_name] = top25
        missing_structural = [name for name in STRUCTURAL_FEATURES if name not in direction_train.columns]
        missing_rolling = [name for name in ROLLING_FEATURES if name not in direction_train.columns]
        if missing_structural or missing_rolling:
            raise RuntimeError(f"incomplete exact A/B/C feature block: structural={missing_structural}, rolling={missing_rolling}")
        blocks = {
            "A_BASELINE": top25,
            "B_PLUS_STRUCTURAL": top25 + list(STRUCTURAL_FEATURES),
            "C_PLUS_ROLLING_5M": top25 + list(STRUCTURAL_FEATURES) + list(ROLLING_FEATURES),
        }
        if len({tuple(block) for block in blocks.values()}) != 3 or any(len(block) != len(set(block)) for block in blocks.values()):
            raise RuntimeError("A/B/C feature blocks are not exact, ordered, and distinct")
        target = direction_train.get_column("flip_within_300s").to_numpy().astype(int)
        if np.unique(target).size != 2:
            raise RuntimeError(f"{direction_name} training target has one class")
        for model_name in MODEL_BLOCKS:
            features = blocks[model_name]
            model = HistGradientBoostingClassifier(**PARAMS).fit(_matrix(direction_train, features), target)
            joblib.dump({"mode": MODE, "model": model, "features": features, "direction": direction_name},
                        model_dir / f"{model_name}_{direction_name}.joblib")
            fitted.append((model_name, direction_name, features, model))

    # No 2024 rows or labels have been opened above this point.
    oos = _load_partitions(oos_dirs, {2024}, current_phase0_sha)
    if oos.height == 0:
        raise RuntimeError("no eligible 2024 OOS rows")
    coverage_rows.extend(_assert_structural_coverage(oos, "OOS_2024", minimum_coverage))
    rows, predictions = [], []
    for model_name, direction_name, features, model in fitted:
        value = 1 if direction_name == "SHORT" else -1
        direction_oos = oos.filter(pl.col("prevailing_direction") == value)
        if direction_oos.height == 0:
            raise RuntimeError(f"missing {direction_name} OOS rows")
        target = direction_oos.get_column("flip_within_300s").to_numpy().astype(int)
        missing_oos = [name for name in features if name not in direction_oos.columns]
        if missing_oos:
            raise RuntimeError(f"OOS partition lacks frozen {model_name}/{direction_name} features: {missing_oos}")
        score = model.predict_proba(_matrix(direction_oos, features))[:, 1]
        artifact = model_dir / f"{model_name}_{direction_name}.joblib"
        for _, _, bucket in PRIMARY_BUCKETS:
            mask = direction_oos.get_column("maturity_bucket").to_numpy() == bucket
            rows.append({"mode": MODE, "model": model_name, "direction": direction_name,
                         "maturity_bucket": bucket, "feature_count": len(features), **_metrics(target[mask], score[mask]),
                         "model_sha256": _sha(artifact)})
        predictions.append(direction_oos.select("checkpoint_decision_ns", "regime_start_ns", "maturity_bucket").with_columns(
            pl.lit(MODE).alias("mode"), pl.lit(model_name).alias("model"), pl.lit(direction_name).alias("direction"),
            pl.Series("score", score), pl.Series("label", target),
        ))

    metrics_path = output_dir / "directional_oos_metrics.parquet"
    pl.DataFrame(rows).sort(["model", "direction", "maturity_bucket"]).write_parquet(metrics_path)
    pl.concat(predictions).write_parquet(output_dir / "oos_predictions.parquet")
    (output_dir / "structural_coverage.json").write_text(json.dumps({
        "mode": MODE, "minimum_required_coverage": minimum_coverage, "cells": coverage_rows,
    }, indent=2))
    (output_dir / "frozen_top25.json").write_text(json.dumps({"mode": MODE, "selection_years": [2021, 2022, 2023],
        "ranking_method": "frozen_train_only_temporal_rank", "oos_year": 2024,
        "target": "prevailing_1m_flip_in_(T,T+300s]", "features": frozen}, indent=2))
    summary = {"mode": MODE, "train_rows": train.height, "oos_rows": oos.height, "directional_cells": len(rows),
               "model_params": PARAMS, "metrics_sha256": _sha(metrics_path)}
    (output_dir / "exploratory_model_manifest.json").write_text(json.dumps(summary, indent=2))
    (output_dir / "EXPLORATORY_STUDY_REPORT.md").write_text(
        f"# Exploratory A/B/C Diagnostic\n\n**{MODE}**\n\n"
        "This output is non-promotable, not accepted research, and must not be exported. "
        "It freezes features and fits on 2021-2023 before opening 2024 for OOS scoring.\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-dir", action="append", required=True)
    parser.add_argument("--oos-dir", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(run([Path(path) for path in args.train_dir], [Path(path) for path in args.oos_dir],
                        Path(args.output_dir)), indent=2))


if __name__ == "__main__":
    main()

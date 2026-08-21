"""Deterministic domain, completeness, and denominator validation."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from studies.Codex_structural_regime_geometry_maturity.implementation.paths import COLLECTION_ROOT

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "studies/Codex_structural_regime_geometry_maturity"
COLLECTION = COLLECTION_ROOT
STORE, OUT = ROOT / "data/canonical/regime_complete_v1", STUDY / "results/validation_report.json"
SEALED_2025_NS, GRID_NS = 1_735_689_600_000_000_000, 5_000_000_000
BUCKETS, DIRECTIONS, MODELS = ("300-600s", "600-900s", "900-1800s", ">=1800s"), ("SHORT", "LONG"), ("TOP25", "TOP25_PLUS_STRUCTURAL")
DECISION_KEY = ["checkpoint_decision_ns", "regime_id"]


def expected_auc_cells() -> set[tuple[str, str, str]]:
    return {(model, direction, bucket) for model in MODELS for direction in (*DIRECTIONS, "POOLED_DIRECTION_LABELLED") for bucket in BUCKETS}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_months() -> dict[str, tuple[str, str]]:
    out = {}
    for year in range(2021, 2025):
        for month in range(1, 13):
            start = datetime(year, month, 1, tzinfo=timezone.utc)
            end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
            out[f"{year:04d}-{month:02d}"] = (start.isoformat(), end.isoformat())
    return out


def _csv_gate(name: str, required_rows: int, required_columns: set[str]) -> dict:
    path = STUDY / "results" / name
    if not path.is_file():
        return {"exists": False, "pass": False}
    frame = pl.read_csv(path)
    return {"exists": True, "rows": frame.height, "columns_present": sorted(required_columns & set(frame.columns)), "pass": frame.height == required_rows and required_columns <= set(frame.columns)}


def accepted_surface(scores: pl.LazyFrame) -> pl.LazyFrame:
    """The frozen direction-specific accepted surface, before structural attrition."""
    return scores.filter(
        (pl.col("seconds_from_regime_start") >= 300)
        & (pl.col("bullish_in_domain") | pl.col("bearish_in_domain"))
    ).select(*DECISION_KEY, "entry_year")


def snapshot_join_checks(base: pl.LazyFrame, snapshots: pl.LazyFrame) -> dict:
    """Map snapshots to canonical regime keys, retaining unavailable snapshots."""
    base_keys = base.select(*DECISION_KEY).unique()
    snapshot_keys = snapshots.join(
        base_keys, on="checkpoint_decision_ns", how="left", validate="m:1"
    )
    mapped = snapshot_keys.filter(pl.col("regime_id").is_not_null())
    joined = base_keys.join(
        mapped.select(*DECISION_KEY, pl.lit(True).alias("_has_snapshot")),
        on=DECISION_KEY, how="left",
    )
    return joined.select(
        pl.len().alias("accepted_base_rows"),
        pl.col("_has_snapshot").is_null().sum().alias("missing_snapshot_rows"),
        (pl.col("checkpoint_decision_ns") % GRID_NS != 0).sum().alias("off_5s_grid_rows"),
        pl.struct(*DECISION_KEY).is_duplicated().sum().alias("duplicate_decision_regime_keys"),
        pl.lit(mapped.select(pl.struct(*DECISION_KEY).is_duplicated().sum()).collect().item()).alias("duplicate_snapshot_keys"),
        pl.lit(snapshot_keys.filter(pl.col("regime_id").is_null()).select(pl.len()).collect().item()).alias("snapshots_without_canonical_regime"),
        pl.lit(snapshot_keys.filter(~pl.col("structural_available")).select(pl.len()).collect().item()).alias("unavailable_snapshot_rows"),
    ).collect().to_dicts()[0]


def main() -> None:
    expected, manifests = expected_months(), {path.parent.name: json.loads(path.read_text()) for path in COLLECTION.glob("*/manifest.json")}
    score = (pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
            .filter((pl.col("entry_year") >= 2021) & (pl.col("entry_year") <= 2024) & (pl.col("session") == "RTH"))
            .select("checkpoint_decision_ns", "regime_id", "entry_year", "seconds_from_regime_start", "bullish_in_domain", "bearish_in_domain"))
    # Every observed RTH score dispatch must have exactly one snapshot.  The
    # accepted surface is deliberately narrower and is used only to decide
    # whether a zero-row collection month is allowable.
    all_score_keys = score.select(*DECISION_KEY, "entry_year")
    accepted_base = accepted_surface(score)
    partition_checks = {}
    for key, (start, end) in expected.items():
        item = manifests.get(key)
        data = COLLECTION / key / "structural_rows.parquet"
        start_ns, end_ns = int(datetime.fromisoformat(start).timestamp() * 1_000_000_000), int(datetime.fromisoformat(end).timestamp() * 1_000_000_000)
        base_rows = accepted_base.filter((pl.col("checkpoint_decision_ns") >= start_ns) & (pl.col("checkpoint_decision_ns") < end_ns)).select(pl.len()).collect().item()
        bounds = {"min": None, "max": None}
        if data.is_file():
            bounds = pl.scan_parquet(data).select(pl.col("checkpoint_decision_ns").min().alias("min"), pl.col("checkpoint_decision_ns").max().alias("max")).collect().to_dicts()[0]
        partition_checks[key] = {"present": item is not None, "exact_bounds": item is not None and item.get("start") == start and item.get("end") == end, "base_eligible_rows": base_rows, "zero_row_allowed": item is not None and (item.get("rows", 0) > 0 or base_rows == 0), "hash_matches": item is not None and data.is_file() and sha256(data) == item.get("sha256"), "boundary_membership": bounds["min"] is None or (bounds["min"] >= start_ns and bounds["max"] < end_ns), "sealed": item is not None and item.get("end", "") <= "2025-01-01T00:00:00+00:00"}
    geometry = pl.scan_parquet(str(COLLECTION / "*/structural_rows.parquet"))
    join = snapshot_join_checks(all_score_keys, geometry)
    geo = geometry.filter(pl.col("structural_available"))
    causal = geo.select((pl.col("current_5m_completed_close_ts") <= pl.col("checkpoint_decision_ns")).all().alias("completed_5m_not_after_checkpoint"), (pl.col("five_registry_close_ts") <= pl.col("checkpoint_decision_ns")).all().alias("registry_not_after_checkpoint"), (pl.col("checkpoint_decision_ns") < SEALED_2025_NS).all().alias("no_2025_or_2026_rows"), pl.col("checkpoint_decision_ns").is_duplicated().sum().alias("duplicate_available_geometry_keys")).collect().to_dicts()[0]
    unavailable_reasons = geometry.filter(~pl.col("structural_available")).group_by("structural_unavailable_reason").agg(pl.len().alias("count")).collect().to_dicts()
    causal["unavailable_reasons"] = {row["structural_unavailable_reason"]: row["count"] for row in unavailable_reasons if row["structural_unavailable_reason"] is not None}
    required = {
        "row_metrics": _csv_gate("oos_row_metrics.csv", 24, {"model_set", "direction", "maturity_bucket", "n", "positives", "roc_auc"}),
        "timing": _csv_gate("oos_timing_metrics.csv", 16, {"model_set", "direction", "maturity_bucket", "n_regimes", "spearman_score_pct_vs_neg_secs_to_flip", "median_top_score_secs_to_flip", "mean_final_preflip_score_pct"}),
        "deciles": _csv_gate("oos_deciles.csv", 160, {"model_set", "direction", "maturity_bucket", "train_score_decile", "p_flip_le_300s", "p_confirm_before_1atr"}),
    }
    crossing_path = STUDY / "results/oos_first_crossings.parquet"
    crossing = {"exists": crossing_path.is_file(), "pass": False}
    if crossing_path.is_file():
        frame = pl.read_parquet(crossing_path)
        required_crossing = {"regime_id", "checkpoint_decision_ns", "model_set", "direction", "threshold_quantile", "score", "structural_max_expansion_atr", "confirmed", "eventual_max_mfe_atr"}
        duplicate_arms = frame.select(pl.struct("regime_id", "model_set", "direction", "threshold_quantile").is_duplicated().sum()).item()
        crossing = {"exists": True, "rows": frame.height, "required_columns": sorted(required_crossing & set(frame.columns)), "duplicate_arms": duplicate_arms, "null_label_rows": int(frame.select(pl.col("label").is_null().sum()).item()) if "label" in frame.columns else frame.height, "pass": required_crossing <= set(frame.columns) and duplicate_arms == 0 and "label" in frame.columns and frame.select(pl.col("label").is_null().sum()).item() == 0}
    row_frame = pl.read_csv(STUDY / "results/oos_row_metrics.csv") if (STUDY / "results/oos_row_metrics.csv").is_file() else pl.DataFrame()
    expected_cells = expected_auc_cells()
    observed_cells = set(map(tuple, row_frame.select("model_set", "direction", "maturity_bucket").unique().iter_rows())) if row_frame.height else set()
    denominator = {"expected_model_direction_bucket_cells": len(expected_cells), "observed_model_direction_bucket_cells": len(observed_cells), "exact_auc_cell_grid": observed_cells == expected_cells, "missing_auc_cells": sorted(expected_cells - observed_cells), "unexpected_auc_cells": sorted(observed_cells - expected_cells), "nonpositive_cells": int(row_frame.select((pl.col("positives") <= 0).sum()).item()) if row_frame.height else None}
    partitions_pass = set(manifests) == set(expected) and all(all(check[name] for name in ("present", "exact_bounds", "zero_row_allowed", "hash_matches", "boundary_membership", "sealed")) for check in partition_checks.values())
    validation_pass = partitions_pass and join["missing_snapshot_rows"] == 0 and join["off_5s_grid_rows"] == 0 and join["duplicate_decision_regime_keys"] == 0 and join["duplicate_snapshot_keys"] == 0 and causal["completed_5m_not_after_checkpoint"] and causal["registry_not_after_checkpoint"] and causal["no_2025_or_2026_rows"] and causal["duplicate_available_geometry_keys"] == 0 and all(item["pass"] for item in required.values()) and crossing["pass"] and denominator["exact_auc_cell_grid"] and denominator["nonpositive_cells"] == 0
    report = {"status": "PASS" if validation_pass else "FAIL", "collection_root": str(COLLECTION), "expected_partition_keys": sorted(expected), "partition_count": len(manifests), "partition_checks": partition_checks, "join": join, "causal_completed_bar_checks": causal, "required_artifact_checks": required, "crossing_artifact_check": crossing, "denominator_checks": denominator, "notes": ["Collection uses NautilusTrader's event loop.", "Unavailable snapshots remain explicit rows; only missing or duplicate decision/regime snapshot keys fail the exact join."]}
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({"status": report["status"], "accepted_base_rows": join["accepted_base_rows"], "missing": join["missing_snapshot_rows"]}, indent=2))


if __name__ == "__main__":
    main()

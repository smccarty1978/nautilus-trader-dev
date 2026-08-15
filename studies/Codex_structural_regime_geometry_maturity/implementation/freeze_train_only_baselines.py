"""Freeze direction-specific baseline feature orders using only 2021-2023 labels."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "studies/Codex_structural_regime_geometry_maturity"
OUT = STUDY / "artifacts" / "frozen_train_only_baselines"
STORE = ROOT / "data" / "canonical" / "regime_complete_v1"
OOS_BOUNDARY_NS = 1_704_067_200_000_000_000  # 2024-01-01 UTC
STRICT = {"minimum_age_seconds": 120, "running_mfe_atr": 1.0, "new_progress_windows": 2, "retained_mfe_ratio": 0.5, "cadence_ns": 5_000_000_000}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def feature_hash(features: list[str]) -> str:
    return hashlib.sha256(json.dumps(features, separators=(",", ":")).encode()).hexdigest()


def candidates(prefix: str) -> list[str]:
    schema = pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet").collect_schema().names()
    return sorted(name[len(prefix) + 2:] for name in schema if name.startswith(f"{prefix}__") and not name.endswith("__is_null"))


def freeze(model_id: str, direction: str, prefix: str, gate: str) -> None:
    fields = candidates(prefix)
    score = (pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
             .filter((pl.col("entry_year") >= 2021) & (pl.col("entry_year") <= 2023) & (pl.col("session") == "RTH") & pl.col(gate)
                     & (pl.col("seconds_from_regime_start") > STRICT["minimum_age_seconds"]) & (pl.col("running_mfe_atr") >= STRICT["running_mfe_atr"])
                     & (pl.col("new_progress_windows") >= STRICT["new_progress_windows"]) & (pl.col("retained_mfe_ratio") >= STRICT["retained_mfe_ratio"])
                     & ((pl.col("checkpoint_decision_ns") % STRICT["cadence_ns"]) == 0))
             .select("checkpoint_decision_ns", "regime_id", *[f"{prefix}__{name}" for name in fields]))
    ends = (pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
            .select("regime_id", "regime_end_decision_ns")
            .filter(pl.col("regime_end_decision_ns") < OOS_BOUNDARY_NS))
    frame = (score.join(ends, on="regime_id", how="inner")
             .with_columns((((pl.col("regime_end_decision_ns") - pl.col("checkpoint_decision_ns")) > 0) & ((pl.col("regime_end_decision_ns") - pl.col("checkpoint_decision_ns")) <= 300_000_000_000)).alias("label")))
    frame = frame.drop_nulls([f"{prefix}__{name}" for name in fields]).collect()
    rankings = []
    target = frame["label"].to_numpy()
    for name in fields:
        auc = roc_auc_score(target, frame[f"{prefix}__{name}"].to_numpy())
        rankings.append({"feature": name, "univariate_auc": float(auc), "absolute_distance_from_half": abs(float(auc) - 0.5)})
    rankings.sort(key=lambda row: (-row["absolute_distance_from_half"], row["feature"]))
    selected = [row["feature"] for row in rankings[:25]]
    if len(selected) != 25:
        raise RuntimeError(f"{model_id}: expected 25 candidates, got {len(selected)}")
    destination = OUT / model_id
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "feature_list.json").write_text(json.dumps(selected, indent=2))
    (destination / "manifest.json").write_text(json.dumps({
        "model_id": model_id, "direction": direction, "feature_count": 25, "ordered_feature_list_hash": feature_hash(selected),
        "selection_method": "univariate_roc_auc_absolute_distance_from_half", "selection_years": [2021, 2022, 2023],
        "oos_boundary": "2024-01-01T00:00:00+00:00", "future_years_read": [],
        "target": "prevailing_1m_regime_flip_in_(T,T+300s]", "session": "RTH", "strict_eligibility": STRICT,
        "atr_anchor": "confirmed_1m_regime_start", "right_censoring": "excluded", "candidate_features": fields,
        "source_hashes": {"scores": sha256(STORE / "canonical_regime_scores_all.parquet"), "regimes": sha256(STORE / "canonical_regimes_all.parquet")},
        "selection_rows": frame.height, "selection_positives": int(frame["label"].sum()), "rankings": rankings,
    }, indent=2))


def main() -> None:
    freeze("BULLISH_STRICT_top25_train_2023_v1", "SHORT", "bullish", "bullish_in_domain")
    freeze("LONG_STRICT_top25_train_2023_v1", "LONG", "bearish", "bearish_in_domain")


if __name__ == "__main__":
    main()

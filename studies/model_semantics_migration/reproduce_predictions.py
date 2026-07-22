"""Prove canonical alias resolution does not change frozen model predictions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from model_registry import ROOT, load_registry, resolve_model


OUT = Path(__file__).with_name("prediction_reproduction_report.json")
SHORT_DATA = ROOT / "studies/short_rth_pure_flip_prediction_enriched/_work/prepared_2025.parquet"
LONG_DATA = ROOT / "studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_2025.parquet"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def reproduce(record: dict) -> dict:
    artifact = ROOT / record["artifact_path"]
    model_path = artifact / "model.joblib"
    if sha256(model_path) != record["artifact_hash"]:
        raise RuntimeError(f"Artifact hash mismatch: {record['canonical_name']}")
    model = joblib.load(model_path)

    if (artifact / "validation_fixture.parquet").exists():
        fixture = pd.read_parquet(artifact / "validation_fixture.parquet")
        features = json.loads((artifact / "feature_list.json").read_text())
        expected = np.load(artifact / "validation_fixture_scores.npy")
    else:
        features = pd.read_csv(artifact / "feature_order.csv")["feature_name"].tolist()
        data_path = SHORT_DATA if record["prevailing_regime"] == "bullish" else LONG_DATA
        fixture = pd.read_parquet(data_path, columns=features)
        expected = pd.read_parquet(artifact / "score_reference_2025.parquet", columns=["score"])["score"].to_numpy()

    canonical = resolve_model(record["canonical_name"])
    checked_aliases = []
    for legacy_name in record["legacy_names"]:
        legacy = resolve_model(legacy_name)
        if canonical["artifact_path"] != legacy["artifact_path"]:
            raise RuntimeError(f"Alias resolution mismatch: {legacy_name}")
        checked_aliases.append(legacy_name)
    runtime = resolve_model(record["runtime_alias"])
    if canonical["artifact_path"] != runtime["artifact_path"]:
        raise RuntimeError(f"Runtime alias resolution mismatch: {record['runtime_alias']}")
    actual = model.predict_proba(fixture[features])[:, record["positive_class_index"]]
    max_diff = float(np.max(np.abs(actual - expected)))
    return {
        "canonical_name": record["canonical_name"],
        "legacy_names_checked": checked_aliases,
        "runtime_alias_checked": record["runtime_alias"],
        "rows": int(len(actual)),
        "artifact_hash": record["artifact_hash"],
        "max_abs_prediction_diff": max_diff,
        "bit_exact": bool(np.array_equal(actual, expected)),
        "status": "PASS" if max_diff == 0.0 else "FAIL",
    }


def main() -> None:
    results = [reproduce(record) for record in load_registry()["models"]]
    report = {
        "required_max_abs_prediction_diff": 0.0,
        "overall_status": "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL",
        "models": results,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report["overall_status"] != "PASS":
        raise SystemExit("PREDICTION_REPRODUCTION_FAILED")


if __name__ == "__main__":
    main()

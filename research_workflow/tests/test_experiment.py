from pathlib import Path

import pandas as pd
import pytest

from research_workflow.analysis import first_crossings, score_deciles
from research_workflow.collection import collect_period
from research_workflow.experiment import (
    ExperimentAuthorizationError,
    TrainFreezeRequired,
    assert_oos_open,
    authorize_experiment,
    write_train_freeze,
    runtime_authorization,
    verify_runtime_authorization,
)


def _study(tmp_path: Path) -> Path:
    p = tmp_path / "study"
    p.mkdir()
    (p / "study.yaml").write_text(
        "study:\n  id: demo\nchronology:\n  train: [2021, 2022, 2023]\n  dev: [2024]\n  prohibited: [2025, 2026]\n",
        encoding="utf-8",
    )
    return p


def test_authorization_materializes_disjoint_periods(tmp_path):
    p = _study(tmp_path)
    auth = authorize_experiment(p)
    assert auth.train_years == (2021, 2022, 2023)
    assert auth.oos_years == (2024,)
    assert auth.prohibited_years == (2025, 2026)
    assert (p / "artifacts/experiment_authorization.json").is_file()


def test_runtime_authorization_is_exact_and_rejects_tampering(tmp_path):
    p = _study(tmp_path)
    authorize_experiment(p)
    payload = runtime_authorization(p, "train")
    assert verify_runtime_authorization(p, payload, "2021-01-01", "2023-12-31")["period"] == "train"
    with pytest.raises(ExperimentAuthorizationError):
        verify_runtime_authorization(p, payload, "2025-01-01", "2025-01-02")
    payload["dates"] = ["2025-01-01"]
    with pytest.raises(ExperimentAuthorizationError):
        verify_runtime_authorization(p, payload, "2021-01-01", "2021-01-01")


def test_oos_locked_until_train_freeze(tmp_path):
    p = _study(tmp_path)
    authorize_experiment(p)
    with pytest.raises(TrainFreezeRequired):
        assert_oos_open(p)
    with pytest.raises(TrainFreezeRequired):
        collect_period(p, "oos", execute=False)
    write_train_freeze(p, {
        "partition": "train", "feature_sets": {"A": ["x"]},
        "preprocessing_hash": "a" * 64, "model_hashes": {"A": "b" * 64},
        "thresholds": {}, "deciles": {},
    })
    assert assert_oos_open(p)["partition"] == "train"
    assert verify_runtime_authorization(p, runtime_authorization(p, "oos"), "2024-01-01", "2024-12-31")["period"] == "oos"


def test_deciles_and_first_crossing_are_deterministic():
    frame = pd.DataFrame({
        "score": [0.1, 0.2, 0.3, 0.4], "target": [0, 1, 0, 1],
        "regime": [1, 1, 2, 2], "ts": pd.date_range("2024-01-01", periods=4, freq="min"),
        "flip": pd.date_range("2024-01-01 00:05", periods=4, freq="min"),
    })
    assert sum(r["n"] for r in score_deciles(frame, "score", target_column="target")) == 4
    rows = first_crossings(frame, score_column="score", threshold_records={"p90": {"threshold": 0.25}}, regime_column="regime", timestamp_column="ts", flip_timestamp_column="flip")
    assert len(rows) == 1

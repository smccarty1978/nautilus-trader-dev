"""Model artifact contract v2 (research_workflow.model_store) on synthetic fits."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_workflow import model_store as ms

FEATS = [f"f{i}" for i in range(5)]


def _train_frame(n: int = 600, seed: int = 0) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.normal(size=(n, len(FEATS))), columns=FEATS)
    y = pd.Series(((X["f0"] + 0.5 * X["f1"] + rng.normal(scale=0.5, size=n)) > 0).astype(int))
    return X, y


def _lineage(study: str, **kw) -> ms.ModelLineage:
    base = dict(study_id=study, cell_id="LONG_SL1_0", direction="LONG", target_arm="SL1_0", fold_id="fold_2023", config_id="C1", seed=42,
                ordered_inputs=FEATS, feature_contract_sha256="a" * 64, preprocessing_contract_sha256="b" * 64, target_contract_sha256="c" * 64,
                target_frame_identity="d" * 64, training_population_identity="e" * 64, train_years=[2021, 2022], validation_years=[2023],
                hyperparameters={"n_estimators": 20}, family="lightgbm", fit_identity_sha256="f" * 64)
    base.update(kw)
    return ms.ModelLineage(**base)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "model_root"


def _lgbm(X, y):
    from lightgbm import LGBMClassifier
    return LGBMClassifier(n_estimators=20, max_depth=3, verbose=-1, random_state=42, deterministic=True, n_jobs=1).fit(X, y)


def test_lightgbm_canonical_is_native_and_golden_validates(root: Path):
    X, y = _train_frame(); est = _lgbm(X, y)
    m = ms.store_model(model_id="m1", estimator=est, lineage=_lineage("s"), tier="registry", selection_status="selected",
                       metrics={"roc_auc": 0.9}, golden_train_frame=X, model_root=root)
    assert m["canonical"]["format"] == "lightgbm_text" and m["canonical"]["archival_safety"] == "portable"
    assert m["golden"]["n_rows"] == ms.GOLDEN_MIN_ROWS
    assert ms.validate_golden("m1", root)["status"] == "PASS"
    assert (root / "models" / "m1" / "canonical" / "model.txt").is_file()


def test_golden_frame_is_deterministic_per_model_id_and_real_rows(root: Path):
    X, _ = _train_frame()
    a = ms.build_golden_frame(X, FEATS, "id-A"); b = ms.build_golden_frame(X, FEATS, "id-A"); c = ms.build_golden_frame(X, FEATS, "id-B")
    assert a.equals(b) and not a.equals(c) and len(a) == 256
    merged = a.merge(X, how="inner", on=FEATS)
    assert len(merged) >= 256  # every golden row is an actual TRAIN row


def test_golden_frame_refuses_small_train(root: Path):
    X, _ = _train_frame(n=100)
    with pytest.raises(ms.ModelStoreError):
        ms.build_golden_frame(X, FEATS, "x")


def test_joblib_export_verified_and_resolvable_by_format(root: Path):
    X, y = _train_frame(); est = _lgbm(X, y)
    ms.store_model(model_id="m2", estimator=est, lineage=_lineage("s"), tier="registry", selection_status="selected", metrics={}, golden_train_frame=X, model_root=root)
    rec = ms.add_export("m2", "joblib", model_root=root)
    assert rec["status"] == "verified" and rec["equivalence"]["status"] == "PASS" and rec["source_model_id"] == "m2"
    r = ms.resolve("m2", required_format="joblib", model_root=root)
    assert r["path"].endswith("model.joblib")
    assert np.allclose(ms.score("m2", X.head(10), required_format="joblib", model_root=root), ms.score("m2", X.head(10), model_root=root))
    assert (root / "models" / "m2" / "equivalence" / "joblib.json").is_file()


def test_onnx_export_records_state_without_touching_canonical(root: Path):
    X, y = _train_frame(); est = _lgbm(X, y)
    m = ms.store_model(model_id="m3", estimator=est, lineage=_lineage("s"), tier="registry", selection_status="selected", metrics={}, golden_train_frame=X, model_root=root)
    before = m["canonical"]["byte_sha256"]
    rec = ms.add_export("m3", "onnx", model_root=root)
    assert rec["status"] in {"verified", "failed"}
    after = ms.read_manifest("m3", root)
    assert after["canonical"]["byte_sha256"] == before and after["model_id"] == "m3"
    if rec["status"] == "failed":
        assert "error" in rec
    else:
        assert rec["equivalence"]["tolerance"] == ms.EXPORT_TOLERANCES["onnx"]


def test_missing_format_is_an_error_not_a_path_guess(root: Path):
    X, y = _train_frame(); est = _lgbm(X, y)
    ms.store_model(model_id="m4", estimator=est, lineage=_lineage("s"), tier="registry", selection_status="selected", metrics={}, golden_train_frame=X, model_root=root)
    with pytest.raises(ms.ModelStoreError, match="MODEL_FORMAT_UNAVAILABLE"):
        ms.resolve("m4", required_format="onnx", model_root=root)


def test_sklearn_family_is_environment_bound_pickle(root: Path):
    from sklearn.linear_model import LogisticRegression
    X, y = _train_frame(); est = LogisticRegression(max_iter=200).fit(X, y)
    m = ms.store_model(model_id="m5", estimator=est, lineage=_lineage("s", family="logistic_regression"), tier="registry", selection_status="final_validation", metrics={}, golden_train_frame=X, model_root=root)
    assert m["canonical"]["format"] == "sklearn_pickle" and m["canonical"]["archival_safety"] == "environment_bound"
    assert m["canonical"]["logical_sha256"] is None
    assert ms.validate_golden("m5", root)["status"] == "PASS"


def test_store_is_immutable_per_model_id(root: Path):
    X, y = _train_frame(); est = _lgbm(X, y)
    a = ms.store_model(model_id="m6", estimator=est, lineage=_lineage("s"), tier="registry", selection_status="selected", metrics={"x": 1}, golden_train_frame=X, model_root=root)
    b = ms.store_model(model_id="m6", estimator=est, lineage=_lineage("s"), tier="ledger", selection_status="rejected", metrics={"x": 2}, golden_train_frame=X, model_root=root)
    assert a["tier"] == b["tier"] == "registry" and b["metrics"] == {"x": 1}


def test_ledger_records_bytes_and_permanent_row(root: Path, tmp_path: Path):
    X, y = _train_frame(); est = _lgbm(X, y)
    study = tmp_path / "studies" / "demo"; study.mkdir(parents=True)
    entry = ms.record_fit(study_path=study, fit_id="fit-1", estimator=est, family="lightgbm", model_root=root,
                          row={"selection_status": "rejected", "cell_id": "LONG", "fold_id": "f1", "config_id": "C3", "metrics": {"roc_auc": 0.5}})
    assert entry["tier"] == "ledger" and entry["selection_status"] == "rejected"
    assert Path(entry["bytes"]["ledger_dir"]).joinpath("model.txt").is_file()
    row = json.loads((study / "artifacts" / "fits" / "fit-1.json").read_text())
    assert row["fit_id"] == "fit-1" and row["bytes"]["byte_sha256"]


def test_invalid_tier_or_status_rejected(root: Path):
    X, y = _train_frame(); est = _lgbm(X, y)
    with pytest.raises(ms.ModelStoreError):
        ms.store_model(model_id="m7", estimator=est, lineage=_lineage("s"), tier="reusable", selection_status="selected", metrics={}, golden_train_frame=X, model_root=root)
    with pytest.raises(ms.ModelStoreError):
        ms.store_model(model_id="m7", estimator=est, lineage=_lineage("s"), tier="registry", selection_status="diagnostic", metrics={}, golden_train_frame=X, model_root=root)


def test_list_store(root: Path):
    X, y = _train_frame(); est = _lgbm(X, y)
    ms.store_model(model_id="m8", estimator=est, lineage=_lineage("s"), tier="registry", selection_status="selected", metrics={}, golden_train_frame=X, model_root=root)
    rows = ms.list_store(root)
    assert rows and rows[0]["model_id"] == "m8" and rows[0]["golden"] is True

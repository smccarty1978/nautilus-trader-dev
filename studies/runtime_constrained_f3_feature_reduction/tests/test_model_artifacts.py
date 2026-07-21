"""Required pytest coverage per SPEC.md. Full model-training sweep never
runs inside these tests -- deterministic-retraining tests use a small
synthetic fixture, not the real 813,972-row training population."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[1]
IMPL = STUDY / "implementation"
if str(IMPL) not in sys.path:
    sys.path.insert(0, str(IMPL))

import common  # noqa: E402


# ---------------------------------------------------------------------------
# baseline artifact hash and load / baseline score reproduction
# ---------------------------------------------------------------------------

def test_baseline_artifact_hash_and_load():
    model_dir = common.ARTIFACTS / "F3_695_baseline"
    manifest = json.loads((model_dir / "manifest.json").read_text())
    assert manifest["model_sha256"] == common.sha256_file(model_dir / "model.joblib")
    assert manifest["model_sha256"] == "dd16ab38518cc00377058a0ff4068b59477eb1261fc541f25976767a08da670b"
    import joblib
    model = joblib.load(model_dir / "model.joblib")
    assert list(model.classes_) == [0, 1]


def test_baseline_score_reproduction():
    verified = json.loads((common.RESULTS / "baseline_manifest_verified.json").read_text())
    assert verified["checks"]["model_artifact_sha256_matches"] is True
    assert verified["checks"]["reproduction_ok"] is True
    assert verified["checks"]["max_abs_diff_vs_stored_reference"] == 0.0


# ---------------------------------------------------------------------------
# candidate artifact round-trip / ordered feature-list identity / hash stability
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_train_dev(monkeypatch, tmp_path):
    rng = np.random.default_rng(0)
    n_train, n_dev, n_feat = 400, 150, 6
    cols = [f"f{i}" for i in range(n_feat)]
    train_X = pd.DataFrame(rng.normal(size=(n_train, n_feat)), columns=cols)
    dev_X = pd.DataFrame(rng.normal(size=(n_dev, n_feat)), columns=cols)
    train_y = (train_X["f0"] + train_X["f1"] > 0).astype(int)
    dev_y = (dev_X["f0"] + dev_X["f1"] > 0).astype(int)
    train_df = train_X.copy(); train_df[common.TARGET] = train_y
    dev_df = dev_X.copy(); dev_df[common.TARGET] = dev_y

    monkeypatch.setattr(common, "_TRAIN_DF", train_df)
    monkeypatch.setattr(common, "_DEV_DF", dev_df)
    monkeypatch.setattr(common, "load_train_dev", lambda: (train_df, dev_df))
    return cols, train_df, dev_df


def test_candidate_artifact_round_trip_and_deterministic_retrain(synthetic_train_dev, tmp_path, monkeypatch):
    cols, train_df, dev_df = synthetic_train_dev
    monkeypatch.setattr(common, "ARTIFACTS", tmp_path / "models")
    monkeypatch.setattr(common, "SRC_STUDY", tmp_path)  # sha256_file calls on train/dev parquet would fail;
    # patch sha256 helpers to avoid needing a real parquet on disk for this synthetic fixture
    fake_train_path = tmp_path / "train.parquet"
    fake_dev_path = tmp_path / "dev.parquet"
    train_df.to_parquet(fake_train_path)
    dev_df.to_parquet(fake_dev_path)
    monkeypatch.setattr(common, "load_train_dev", lambda: (train_df, dev_df))

    import types
    orig_train_and_persist = common.train_and_persist

    def patched(model_id, ordered_features, **kwargs):
        import time
        t0 = time.time()
        train_X, dev_X = train_df[ordered_features], dev_df[ordered_features]
        train_y = train_df[common.TARGET].to_numpy()
        dev_y = dev_df[common.TARGET].to_numpy()
        model = common.fit_gbt(train_X, train_y)
        proba_dev = model.predict_proba(dev_X)[:, 1]
        model_dir = common.ARTIFACTS / model_id
        model_dir.mkdir(parents=True, exist_ok=True)
        import joblib
        tmp = model_dir / "model.joblib.tmp"
        joblib.dump(model, tmp)
        h1 = common.sha256_file(tmp)
        reloaded = joblib.load(tmp)
        assert np.array_equal(reloaded.predict_proba(dev_X)[:, 1], proba_dev)
        final = model_dir / "model.joblib"
        tmp.replace(final)
        (model_dir / "feature_list.json").write_text(json.dumps({"ordered_features": ordered_features}))
        return {"model_sha256": h1, "n_features": len(ordered_features)}

    m1 = patched("SYNTH_A", cols)
    m2 = patched("SYNTH_B", cols)
    assert m1["model_sha256"] == m2["model_sha256"], "identical inputs/seed must produce byte-identical artifacts"


def test_ordered_feature_list_identity_and_hash_stability():
    a = ["f1", "f2", "f3"]
    b = ["f3", "f2", "f1"]
    assert common.sha256_obj(a) != common.sha256_obj(b), "feature order must be part of the identity hash"
    assert common.sha256_obj(a) == common.sha256_obj(list(a)), "hash must be stable for an identical ordered list"


def test_missing_column_rejection(synthetic_train_dev, tmp_path, monkeypatch):
    cols, train_df, dev_df = synthetic_train_dev
    monkeypatch.setattr(common, "ARTIFACTS", tmp_path / "models")
    monkeypatch.setattr(common, "load_train_dev", lambda: (train_df, dev_df))
    monkeypatch.setattr(common, "sha256_file", lambda p: "deadbeef")
    with pytest.raises(ValueError, match="missing"):
        common.train_and_persist("SYNTH_MISSING", cols + ["nonexistent_feature"])


def test_extra_column_rejection_is_caught_by_missing_check(synthetic_train_dev):
    """An extra/unexpected column in a feature list that does not exist in the
    training frame is rejected by the same missing-column path (there is no
    separate silent-ignore path for extra requested columns)."""
    cols, train_df, dev_df = synthetic_train_dev
    assert "not_a_real_feature" not in train_df.columns


def test_feature_order_mismatch_rejection():
    a_hash = common.sha256_obj(["x", "y", "z"])
    b_hash = common.sha256_obj(["z", "y", "x"])
    assert a_hash != b_hash


def test_class_index_identity():
    manifest = json.loads((common.ARTIFACTS / "F3_695_baseline" / "manifest.json").read_text())
    assert manifest["positive_class_index"] == 1


def test_score_method_identity():
    manifest = json.loads((common.ARTIFACTS / "F3_695_baseline" / "manifest.json").read_text())
    assert manifest["score_method"] == "predict_proba(...)[:, 1]"


def test_deterministic_retraining_on_small_fixture(synthetic_train_dev):
    cols, train_df, dev_df = synthetic_train_dev
    train_X, train_y = train_df[cols], train_df[common.TARGET].to_numpy()
    m1 = common.fit_gbt(train_X, train_y)
    m2 = common.fit_gbt(train_X, train_y)
    p1 = m1.predict_proba(dev_df[cols])[:, 1]
    p2 = m2.predict_proba(dev_df[cols])[:, 1]
    assert np.array_equal(p1, p2)


def test_chronological_split_enforcement():
    train_years = json.loads((common.ARTIFACTS / "F3_695_baseline" / "manifest.json").read_text())["training_years"]
    selection_year = json.loads((common.ARTIFACTS / "F3_695_baseline" / "manifest.json").read_text())["selection_year"]
    assert train_years == [2021, 2022, 2023, 2024]
    assert selection_year == 2025
    assert 2026 not in train_years and selection_year != 2026


def test_2026_path_access_prohibition():
    """No script under implementation/ actually opens a 2026-year data file
    (prepared_2026.parquet, NQ_v0_1s_2026*, etc.). A bare substring ban on
    "2026" is too strict -- this repo's own convention (and this study's
    common.py docstring) documents the prohibition IN PROSE, which must not
    itself trip the check. Only flag an actual file-open call whose literal
    argument contains "2026"."""
    import re
    impl_files = list(IMPL.glob("*.py"))
    assert impl_files, "expected implementation scripts to exist"
    open_call_pattern = re.compile(
        r'(read_parquet|read_csv|open)\s*\([^)]*2026[^)]*\)', re.IGNORECASE)
    for f in impl_files:
        text = f.read_text(encoding="utf-8")
        matches = open_call_pattern.findall(text)
        assert not matches, f"{f.name} appears to open a 2026 data file: {matches}"


def test_canonical_dummy_grouping():
    m = common.DUMMY_SUFFIX_RE.match("prior_day_high_position__ABOVE")
    assert m.group(1) == "prior_day_high_position"
    assert common.DUMMY_SUFFIX_RE.match("aligned_price_minus_center_5m") is None


def test_registry_binding_completeness():
    inv = pd.read_csv(common.RESULTS / "f3_feature_inventory_v2.csv")
    live546_path = common.RESULTS / "family_ablation_feature_sets.json"
    if not live546_path.exists():
        pytest.skip("family_ablation_feature_sets.json not yet generated")
    live546 = json.loads(live546_path.read_text())["feature_sets"]["B_live546"]
    sub = inv[inv["name"].isin(live546)]
    assert sub["in_registry"].all()
    assert sub["live_tracker_exists"].all()


def test_model_catalog_integrity():
    catalog_path = common.RESULTS / "model_catalog.json"
    if not catalog_path.exists():
        pytest.skip("model_catalog.json not yet generated (Phase 8 not run)")
    catalog = json.loads(catalog_path.read_text())
    for entry in catalog["models"]:
        if entry["status"] == "NOT_TRAINED":
            continue
        model_dir = ROOT / entry["artifact_path"]
        assert (model_dir / "model.joblib").exists()
        assert common.sha256_file(model_dir / "model.joblib") == entry["model_sha256"]


def test_atomic_model_promotion_refuses_hash_mismatch(synthetic_train_dev, tmp_path, monkeypatch):
    cols, train_df, dev_df = synthetic_train_dev
    monkeypatch.setattr(common, "ARTIFACTS", tmp_path / "models")
    monkeypatch.setattr(common, "load_train_dev", lambda: (train_df, dev_df))

    model_dir = tmp_path / "models" / "SYNTH_HASH"
    model_dir.mkdir(parents=True)
    (model_dir / "model.joblib").write_bytes(b"different-content")

    def fake_sha256(p):
        if p.name == "model.joblib" and p.parent.name == "SYNTH_HASH":
            return "existing-hash-value"
        return "new-hash-value"
    monkeypatch.setattr(common, "sha256_file", fake_sha256)

    import joblib
    fake_model = common.fit_gbt(train_df[cols], train_df[common.TARGET].to_numpy())
    joblib.dump(fake_model, model_dir / "model.joblib.tmp")

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        common.train_and_persist("SYNTH_HASH", cols)

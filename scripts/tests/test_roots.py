"""Machine-local root resolution (research_workflow.roots) -- no real catalog required."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research_workflow import roots
from research_workflow.roots import (
    DatasetDigestMismatch, DatasetRootUnresolved, DuplicateDatasetConflict, RootConfig,
    compute_catalog_digest, load_config, resolve_dataset, write_dataset_manifest,
)


def _fake_catalog(path: Path, payload: bytes = b"bars") -> Path:
    (path / "data" / "bar" / "X.Y-1-SECOND-LAST-EXTERNAL").mkdir(parents=True)
    (path / "data" / "bar" / "X.Y-1-SECOND-LAST-EXTERNAL" / "part-0.parquet").write_bytes(payload)
    return path


def _repo(tmp_path: Path, dataset_id: str, digest: str | None, rel: str = "data/catalog/DS") -> Path:
    repo = tmp_path / "repo"
    (repo / "research" / "datasets").mkdir(parents=True)
    spec = {"dataset_id": dataset_id, "instrument_id": "X.Y", "catalog_rel_path": rel,
            "streams": {}, "coverage": {"start": "2020", "end": "2021"}}
    if digest:
        spec["logical_digest"] = digest
        spec["digest_method"] = roots.DIGEST_METHOD
    (repo / "research" / "datasets" / f"{dataset_id}.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    return repo


def _config(tmp_path: Path, catalog_roots: list[Path], model_root: Path | None = None) -> Path:
    p = tmp_path / "config.yaml"
    body = {"catalog_roots": [str(r) for r in catalog_roots]}
    if model_root:
        body["model_root"] = str(model_root)
    p.write_text(yaml.safe_dump(body), encoding="utf-8")
    return p


def test_digest_is_content_only_and_stable_across_copies(tmp_path: Path):
    a = _fake_catalog(tmp_path / "a"); b = _fake_catalog(tmp_path / "b")
    da, db = compute_catalog_digest(a), compute_catalog_digest(b)
    assert da["logical_digest"] == db["logical_digest"]
    c = _fake_catalog(tmp_path / "c", payload=b"other")
    assert compute_catalog_digest(c)["logical_digest"] != da["logical_digest"]


def test_manifest_written_and_read(tmp_path: Path):
    cat = _fake_catalog(tmp_path / "cat")
    m = write_dataset_manifest(cat, "DS", "X.Y")
    assert (cat / roots.DATASET_MANIFEST_NAME).is_file()
    assert roots.read_dataset_manifest(cat)["logical_digest"] == m["logical_digest"]


def test_no_config_is_legacy_repo_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(roots.CONFIG_ENV, str(tmp_path / "missing.yaml"))
    repo = _repo(tmp_path, "DS", None)
    cat = _fake_catalog(repo / "data" / "catalog" / "DS")
    r = resolve_dataset("DS", repo)
    assert r.resolution == "legacy_repo_relative" and r.catalog_path == cat.resolve()


def test_legacy_mode_rejects_digest_drift_when_both_declared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(roots.CONFIG_ENV, str(tmp_path / "missing.yaml"))
    repo = _repo(tmp_path, "DS", "0" * 64)
    cat = _fake_catalog(repo / "data" / "catalog" / "DS"); write_dataset_manifest(cat, "DS")
    with pytest.raises(DatasetDigestMismatch):
        resolve_dataset("DS", repo)


def test_configured_root_resolves_by_id_and_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "root1"; cat = _fake_catalog(root / "DS"); m = write_dataset_manifest(cat, "DS")
    repo = _repo(tmp_path, "DS", m["logical_digest"])
    monkeypatch.setenv(roots.CONFIG_ENV, str(_config(tmp_path, [root])))
    r = resolve_dataset("DS", repo)
    assert r.resolution == "configured_root" and r.catalog_path == cat.resolve() and r.logical_digest == m["logical_digest"]
    assert "catalog_path" not in r.identity()  # receipts carry identity, not path


def test_configured_root_has_no_repo_relative_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "root1"; root.mkdir()
    repo = _repo(tmp_path, "DS", "1" * 64)
    _fake_catalog(repo / "data" / "catalog" / "DS")  # exists repo-relative, must NOT be used
    monkeypatch.setenv(roots.CONFIG_ENV, str(_config(tmp_path, [root])))
    with pytest.raises(DatasetRootUnresolved):
        resolve_dataset("DS", repo)


def test_configured_root_requires_committed_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "root1"; cat = _fake_catalog(root / "DS"); write_dataset_manifest(cat, "DS")
    repo = _repo(tmp_path, "DS", None)
    monkeypatch.setenv(roots.CONFIG_ENV, str(_config(tmp_path, [root])))
    with pytest.raises(DatasetRootUnresolved):
        resolve_dataset("DS", repo)


def test_conflicting_digests_across_roots_hard_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r1 = tmp_path / "r1"; c1 = _fake_catalog(r1 / "DS"); m1 = write_dataset_manifest(c1, "DS")
    r2 = tmp_path / "r2"; c2 = _fake_catalog(r2 / "DS", payload=b"different"); write_dataset_manifest(c2, "DS")
    repo = _repo(tmp_path, "DS", m1["logical_digest"])
    monkeypatch.setenv(roots.CONFIG_ENV, str(_config(tmp_path, [r1, r2])))
    with pytest.raises(DuplicateDatasetConflict):
        resolve_dataset("DS", repo)


def test_identical_digest_in_two_roots_is_acceptable_first_root_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r1 = tmp_path / "r1"; c1 = _fake_catalog(r1 / "DS"); m1 = write_dataset_manifest(c1, "DS")
    r2 = tmp_path / "r2"; c2 = _fake_catalog(r2 / "DS"); write_dataset_manifest(c2, "DS")
    repo = _repo(tmp_path, "DS", m1["logical_digest"])
    monkeypatch.setenv(roots.CONFIG_ENV, str(_config(tmp_path, [r2, r1])))
    assert resolve_dataset("DS", repo).catalog_path == c2.resolve()


def test_wrong_digest_only_copy_is_conflict_not_silent_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r1 = tmp_path / "r1"; c1 = _fake_catalog(r1 / "DS", payload=b"stale"); write_dataset_manifest(c1, "DS")
    repo = _repo(tmp_path, "DS", "2" * 64)
    monkeypatch.setenv(roots.CONFIG_ENV, str(_config(tmp_path, [r1])))
    with pytest.raises(DuplicateDatasetConflict):
        resolve_dataset("DS", repo)


def test_model_root_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(roots.CONFIG_ENV, str(_config(tmp_path, [tmp_path / "r"], model_root=tmp_path / "models")))
    cfg = load_config()
    assert cfg.model_root == (tmp_path / "models").resolve()
    assert roots.resolve_model_root(cfg, create=True).is_dir()


def test_data_plan_uses_root_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """resolve_catalog_plan must open the configured root, not the repo-relative directory."""
    from backtests.nt_runtime import data_plan as dp
    root = tmp_path / "root"; cat = _fake_catalog(root / "NQ_v0_2020_2026"); m = write_dataset_manifest(cat, "NQ_v0_2020_2026", "NQ.XCME")
    repo = tmp_path / "repo"; (repo / "research" / "datasets").mkdir(parents=True)
    spec = yaml.safe_load((Path(dp.__file__).resolve().parents[2] / "research" / "datasets" / "NQ_v0_2020_2026.yaml").read_text(encoding="utf-8"))
    spec["logical_digest"] = m["logical_digest"]; spec["digest_method"] = roots.DIGEST_METHOD
    (repo / "research" / "datasets" / "NQ_v0_2020_2026.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    monkeypatch.setenv(roots.CONFIG_ENV, str(_config(tmp_path, [root])))
    plan = dp.resolve_catalog_plan("NQ", "2023-01-03", "2023-01-03", repo_root=repo)
    assert plan.catalog_path == cat.resolve()
    assert plan.dataset_id == "NQ_v0_2020_2026" and plan.dataset_logical_digest == m["logical_digest"]
    assert plan.dataset_resolution == "configured_root"

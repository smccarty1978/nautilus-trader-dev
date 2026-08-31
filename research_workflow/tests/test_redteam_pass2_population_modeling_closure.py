"""Pass-2 H01/H02 synthetic adversarial regressions."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from research.schemas.study_spec import PopulationQualificationSpec
from research_workflow.generic_collector import verify_checkpoint_identities_authority
from research_workflow.modeling_closure import resolve_modeling_closure
from research_workflow.modeling_drivers import UndeclaredModelingDriverError, assert_declared_modeling_drivers


def _study(tmp_path: Path, files: dict[str, str]) -> Path:
    study = tmp_path / "study"; study.mkdir()
    for rel, body in files.items():
        path = study / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(body, encoding="utf-8")
    return study


def test_allowlist_sha_is_required_and_verified_before_decoder(tmp_path, monkeypatch):
    path = tmp_path / "ids.parquet"; path.write_bytes(b"synthetic-not-a-parquet")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert PopulationQualificationSpec(required_checkpoint_identities_path="ids.parquet", required_checkpoint_identities_sha256=sha)
    with pytest.raises(ValidationError, match="SHA256_REQUIRED"):
        PopulationQualificationSpec(required_checkpoint_identities_path="ids.parquet")
    decoder_called = False
    def decoder(*_a, **_k):
        nonlocal decoder_called; decoder_called = True
    monkeypatch.setattr("research_workflow.generic_collector.pd.read_parquet", decoder)
    with pytest.raises(RuntimeError, match="SHA256_MISMATCH"):
        verify_checkpoint_identities_authority(path, "0" * 64)
    assert not decoder_called
    lineage = verify_checkpoint_identities_authority(path, sha)
    assert lineage == {"path": str(path.resolve()), "sha256": sha}


def test_declared_driver_and_all_helpers_are_explicit_closure_authority(tmp_path):
    s = _study(tmp_path, {"implementation/driver.py": "from . import helper\n",
                           "implementation/helper.py": "from research_workflow.modeling import fit_models\n"})
    with pytest.raises(UndeclaredModelingDriverError, match="helper.py"):
        assert_declared_modeling_drivers(s, ["implementation/driver.py"])
    declared = ["implementation/driver.py", "implementation/helper.py"]
    assert_declared_modeling_drivers(s, declared)
    closure = resolve_modeling_closure(s, driver_relpaths=declared)
    assert any(key.endswith("implementation/helper.py") for key in closure["file_sha256_map"])


def test_subprocess_shell_and_dynamic_local_entrypoints_must_be_declared(tmp_path):
    s = _study(tmp_path, {
        "implementation/driver.py": "import subprocess, sys, importlib\nsubprocess.run([sys.executable, 'implementation/sub.py'])\nimportlib.import_module('implementation.dynamic')\nsubprocess.run(['bash', 'implementation/run.sh'])\n",
        "implementation/sub.py": "from research_workflow.modeling import fit_models\n",
        "implementation/dynamic.py": "from research_workflow.modeling import fit_models\n",
        "implementation/run.sh": "python implementation/shell_helper.py\n",
        "implementation/shell_helper.py": "from research_workflow.modeling import fit_models\n",
    })
    with pytest.raises(UndeclaredModelingDriverError, match="helper"):
        assert_declared_modeling_drivers(s, ["implementation/driver.py"])
    all_declared = ["implementation/driver.py", "implementation/sub.py", "implementation/dynamic.py",
                    "implementation/run.sh", "implementation/shell_helper.py"]
    assert_declared_modeling_drivers(s, all_declared)
    before = resolve_modeling_closure(s, driver_relpaths=all_declared)["modeling_execution_composite_sha256"]
    (s / "implementation/dynamic.py").write_text("from research_workflow.modeling import freeze_train_artifacts\n", encoding="utf-8")
    assert resolve_modeling_closure(s, driver_relpaths=all_declared)["modeling_execution_composite_sha256"] != before


def test_nonliteral_dynamic_import_fails_closed(tmp_path):
    s = _study(tmp_path, {"implementation/driver.py": "import importlib\nimportlib.import_module(name)\n"})
    with pytest.raises(UndeclaredModelingDriverError, match="DYNAMIC_IMPORT_UNRESOLVED"):
        assert_declared_modeling_drivers(s, ["implementation/driver.py"])

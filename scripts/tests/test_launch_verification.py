"""Launch-time dataset byte verification is one governed mechanism shared by collect and backtest modes."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from backtests.nt_runtime import data_plan as dp
from backtests.nt_runtime.modes import backtest as backtest_mode
from backtests.nt_runtime.modes import collect as collect_mode
from research_workflow import roots
from research_workflow.roots import write_dataset_manifest

REPO = Path(__file__).resolve().parents[2]


def _fake_catalog(path: Path, payload: bytes = b"bars") -> Path:
    (path / "data" / "bar" / "NQ.XCME-1-SECOND-LAST-EXTERNAL").mkdir(parents=True)
    (path / "data" / "bar" / "NQ.XCME-1-SECOND-LAST-EXTERNAL" / "part-0.parquet").write_bytes(payload)
    return path


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A configured root holding NQ_v0_2020_2026 with a committed digest in a fixture repo."""
    root = tmp_path / "root"; cat = _fake_catalog(root / "NQ_v0_2020_2026"); m = write_dataset_manifest(cat, "NQ_v0_2020_2026", "NQ.XCME")
    repo = tmp_path / "repo"; (repo / "research" / "datasets").mkdir(parents=True)
    spec = yaml.safe_load((REPO / "research" / "datasets" / "NQ_v0_2020_2026.yaml").read_text(encoding="utf-8"))
    spec["logical_digest"] = m["logical_digest"]
    (repo / "research" / "datasets" / "NQ_v0_2020_2026.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    cfg = tmp_path / "config.yaml"; cfg.write_text(yaml.safe_dump({"catalog_roots": [str(root)]}), encoding="utf-8")
    monkeypatch.setenv(roots.CONFIG_ENV, str(cfg))
    return repo, cat


def test_collect_and_backtest_share_the_same_verifier():
    assert backtest_mode.verify_launch_dataset_bytes is dp.verify_launch_dataset_bytes
    src = (REPO / "backtests" / "nt_runtime" / "modes" / "collect.py").read_text(encoding="utf-8")
    assert "verify_launch_dataset_bytes(data_plan)" in src


def _call_order(module_path: Path, first: str, second: str) -> None:
    src = module_path.read_text(encoding="utf-8")
    i, j = src.index(first), src.index(second)
    assert i < j, f"{first} must precede {second} in {module_path.name}"


def test_verification_precedes_engine_construction_in_both_modes():
    _call_order(REPO / "backtests/nt_runtime/modes/backtest.py", "verify_launch_dataset_bytes(data_plan)", "engine, instrument = build_engine(")
    _call_order(REPO / "backtests/nt_runtime/modes/collect.py", "verify_launch_dataset_bytes(data_plan)", "build_engine(data_plan")


def test_backtest_plan_passes_on_correct_catalog_and_rejects_same_size_mutation(configured, monkeypatch: pytest.MonkeyPatch):
    repo, cat = configured
    calls = []
    real = dp.verify_launch_dataset_bytes
    def spy(plan):
        calls.append(plan.catalog_path); return real(plan)
    monkeypatch.setattr(backtest_mode, "verify_launch_dataset_bytes", spy)
    # engine construction must never be reached during plan resolution
    monkeypatch.setattr(backtest_mode, "build_engine", lambda *a, **k: (_ for _ in ()).throw(AssertionError("build_engine reached during plan resolution")))
    plan = backtest_mode.resolve_backtest_plan("w4_exit_strategy", "NQ", "2023-01-03", "2023-01-03", repo_root=repo)
    assert plan.data_plan.catalog_path == cat.resolve() and calls == [cat.resolve()]
    # same-size byte mutation after the manifest (post-R1) -> refused at launch, before any engine
    part = cat / "data" / "bar" / "NQ.XCME-1-SECOND-LAST-EXTERNAL" / "part-0.parquet"
    part.write_bytes(b"barz")
    with pytest.raises(dp.WrongPhysicalDatasetError):
        backtest_mode.resolve_backtest_plan("w4_exit_strategy", "NQ", "2023-01-03", "2023-01-03", repo_root=repo)
    assert len(calls) == 2  # verifier ran again; build_engine never did


def test_verified_path_is_the_path_the_engine_opens():
    """build_engine opens exactly data_plan.catalog_path -- the object the verifier checked."""
    src = (REPO / "backtests" / "nt_runtime" / "engine_builder.py").read_text(encoding="utf-8")
    assert "CausalDataLoader(data_plan.catalog_path)" in src

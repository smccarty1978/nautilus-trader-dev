"""Regression tests for Phase 1 Packet A2 (resolver + loader hardening).

Covers:
  A2.1 fail-close catalog resolution (no CWD-relative substitution)
  A2.2 declared (DatasetSpec) == resolved (resolve_catalog_plan) == opened (CausalDataLoader)
  A2.3 CausalDataLoader cache key includes catalog identity
  A2.4 warmup-through-run physical coverage validation
  Addition: compiled_study.json vs study.yaml dataset_id parity (existing-guard proof)
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from backtests.nt_runtime.compiled_study_loader import (
    StaleCompiledStudyError,
    load_compiled_study,
)
from backtests.nt_runtime.data_plan import (
    CatalogCoverageError,
    GovernedCatalogNotFoundError,
    UnauthorizedExecutionDomainError,
    WrongPhysicalDatasetError,
    resolve_catalog_plan,
    resolve_data_plan,
)
from research.schemas.study_spec import StudySpec
from scripts.compile_study import compile_study
from utils.runner.data import CausalDataLoader

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_NQ_CATALOG = REPO_ROOT / "data" / "catalog" / "NQ_v0_2020_2026"
CLEAN_FLIP_STUDY = REPO_ROOT / "studies" / "Codex_clean_maturity_flip_rolling_5m_productivity"


# ---------------------------------------------------------------------------
# A2.1 -- fail-close catalog resolution
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not REAL_NQ_CATALOG.exists(), reason="real NQ catalog absent")
def test_governed_catalog_resolves_successfully():
    plan = resolve_catalog_plan("NQ", "2023-10-02", "2023-10-06", warmup_days=5, repo_root=REPO_ROOT)
    assert plan.catalog_path == REAL_NQ_CATALOG.resolve()


def test_missing_governed_catalog_fails_closed(tmp_path: Path):
    empty_repo_root = tmp_path / "repo_with_no_catalog"
    empty_repo_root.mkdir()
    with pytest.raises(GovernedCatalogNotFoundError, match="GOVERNED_CATALOG_NOT_FOUND"):
        resolve_catalog_plan("NQ", "2023-10-02", "2023-10-06", warmup_days=5, repo_root=empty_repo_root)


def test_cwd_fallback_cannot_select_an_alternate_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The prior resolver re-resolved catalog_rel_path against the process CWD when the
    repo_root-relative path was missing. Plant a directory at that same relative path
    under a decoy CWD and prove it is never opened.
    """
    decoy_cwd = tmp_path / "decoy_cwd"
    (decoy_cwd / "data" / "catalog" / "NQ_v0_2020_2026").mkdir(parents=True)

    empty_repo_root = tmp_path / "governed_repo_root_missing_catalog"
    empty_repo_root.mkdir()

    monkeypatch.chdir(decoy_cwd)
    with pytest.raises(GovernedCatalogNotFoundError):
        resolve_catalog_plan("NQ", "2023-10-02", "2023-10-06", warmup_days=5, repo_root=empty_repo_root)


# ---------------------------------------------------------------------------
# A2.2 -- declared (DatasetSpec) == resolved (resolve_catalog_plan) == opened (loader)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (CLEAN_FLIP_STUDY / "compiled_study.json").exists() or not REAL_NQ_CATALOG.exists(),
    reason="CleanFlip study or real NQ catalog absent",
)
def test_declared_dataset_spec_path_equals_resolver_path_for_real_study():
    compiled_data = load_compiled_study(CLEAN_FLIP_STUDY)
    plan = resolve_data_plan(compiled_data, "2023-10-02", "2023-10-06", warmup_days=5, repo_root=REPO_ROOT)
    assert plan.catalog_path == REAL_NQ_CATALOG.resolve()

    loader = CausalDataLoader(plan.catalog_path)
    assert loader.catalog_path == plan.catalog_path, "loader must open the exact resolver-produced path"


@pytest.mark.skipif(
    not (CLEAN_FLIP_STUDY / "compiled_study.json").exists() or not REAL_NQ_CATALOG.exists(),
    reason="CleanFlip study or real NQ catalog absent",
)
def test_drifted_dataset_spec_catalog_path_is_rejected(tmp_path: Path):
    """If the referenced DatasetSpec disagrees with resolve_catalog_plan's own result, the
    runtime must refuse rather than silently trusting the resolver alone.
    """
    compiled_data = load_compiled_study(CLEAN_FLIP_STUDY)

    fake_repo_root = tmp_path / "repo"
    (fake_repo_root / "data" / "catalog" / "NQ_v0_2020_2026").mkdir(parents=True)
    (fake_repo_root / "data" / "catalog" / "NQ_v0_2020_2026" / "data").mkdir(parents=True, exist_ok=True)
    datasets_dir = fake_repo_root / "research" / "datasets"
    datasets_dir.mkdir(parents=True)
    (datasets_dir / "NQ_v0_2020_2026.yaml").write_text(
        yaml.safe_dump({
            "dataset_id": "NQ_v0_2020_2026",
            "instrument_id": "NQ.XCME",
            "catalog_rel_path": "data/catalog/SOME_OTHER_CATALOG",  # deliberately drifted
            "provenance": {"source": "databento"},
            "streams": {
                "1s": {
                    "source": "external", "bar_type": "NQ.XCME-1-SECOND-LAST-EXTERNAL",
                    "source_timestamp_semantics": "interval_open", "availability_rule": "interval_end",
                    "ts_init_delta_ns": 1_000_000_000,
                },
                "1m": {
                    "source": "external", "bar_type": "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
                    "source_timestamp_semantics": "interval_open", "availability_rule": "interval_end",
                    "ts_init_delta_ns": 60_000_000_000,
                },
                "5m": {
                    "source": "derived", "external_catalog_stream": False,
                    "derived_from": "1m", "aggregator": "CompletedMinuteFiveMinuteAggregator",
                },
            },
            "coverage": {"start": "2020-01-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"},
        }),
        encoding="utf-8",
    )

    with pytest.raises(WrongPhysicalDatasetError, match="WRONG_PHYSICAL_DATASET"):
        resolve_data_plan(compiled_data, "2023-10-02", "2023-10-06", warmup_days=5, repo_root=fake_repo_root)


# ---------------------------------------------------------------------------
# A2.3 -- CausalDataLoader cache key includes catalog identity
# ---------------------------------------------------------------------------

def test_two_catalogs_same_bar_query_do_not_cross_contaminate_cache(tmp_path: Path):
    """Regression for the process-global cache keyed only on (bar_type, start, end).

    Under the old 3-tuple key, loader_b's query for the identical bar_type/start/end
    would have returned loader_a's cached bars -- the two catalogs would collide on the
    same cache entry. The new key includes resolved catalog identity, so each loader must
    see only its own catalog's bars.
    """
    CausalDataLoader.clear_cache()
    try:
        catalog_a_dir = tmp_path / "catalog_a"
        catalog_b_dir = tmp_path / "catalog_b"
        catalog_a_dir.mkdir()
        catalog_b_dir.mkdir()

        loader_a = CausalDataLoader(catalog_a_dir)
        loader_b = CausalDataLoader(catalog_b_dir)
        assert loader_a.catalog_path != loader_b.catalog_path

        loader_a.catalog.bars = lambda bar_types, start, end: ["FROM_CATALOG_A"]
        loader_b.catalog.bars = lambda bar_types, start, end: ["FROM_CATALOG_B"]

        bar_type = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
        start = pd.Timestamp("2023-10-02", tz="UTC")
        end = pd.Timestamp("2023-10-03", tz="UTC")

        result_a = loader_a.load_bars(bar_type, start, end)
        result_b = loader_b.load_bars(bar_type, start, end)

        assert result_a == ["FROM_CATALOG_A"]
        assert result_b == ["FROM_CATALOG_B"], (
            "loader_b received loader_a's cached bars -- cache key is not catalog-aware"
        )
        assert len(CausalDataLoader._cache_bars) == 2, "each catalog must occupy its own cache slot"
    finally:
        CausalDataLoader.clear_cache()


# ---------------------------------------------------------------------------
# A2.4 -- warmup-through-run physical coverage validation
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (CLEAN_FLIP_STUDY / "compiled_study.json").exists() or not REAL_NQ_CATALOG.exists(),
    reason="CleanFlip study or real NQ catalog absent",
)
def test_warmup_coverage_missing_fails():
    """Run window (2023-10-05/06) is one of the study's exact authorized_dates and is
    inside catalog coverage, but a 1500-day warmup pushes the required window's start
    (~2019-08-27) before the catalog's earliest bar (2020-01-01) -- must fail, not
    silently pass. Goes through resolve_data_plan, where the coverage check runs after
    chronology so it is exercised on a request that already cleared every chronology gate.
    """
    compiled_data = load_compiled_study(CLEAN_FLIP_STUDY)
    with pytest.raises(CatalogCoverageError, match="CATALOG_COVERAGE_GAP"):
        resolve_data_plan(compiled_data, "2023-10-05", "2023-10-06", warmup_days=1500, repo_root=REPO_ROOT)


@pytest.mark.skipif(
    not (CLEAN_FLIP_STUDY / "compiled_study.json").exists() or not REAL_NQ_CATALOG.exists(),
    reason="CleanFlip study or real NQ catalog absent",
)
def test_warmup_and_run_coverage_present_passes():
    compiled_data = load_compiled_study(CLEAN_FLIP_STUDY)
    plan = resolve_data_plan(compiled_data, "2023-10-02", "2023-10-06", warmup_days=5, repo_root=REPO_ROOT)
    assert plan.warmup_start_dt < plan.start_dt


@pytest.mark.skipif(
    not (CLEAN_FLIP_STUDY / "compiled_study.json").exists() or not REAL_NQ_CATALOG.exists(),
    reason="CleanFlip study or real NQ catalog absent",
)
def test_unauthorized_chronology_reported_before_coverage_gap():
    """A2.4 must not shadow chronology errors: a request that is both out of chronology
    and out of physical coverage must still surface as a chronology violation."""
    compiled_data = load_compiled_study(CLEAN_FLIP_STUDY)
    with pytest.raises(UnauthorizedExecutionDomainError, match="UNAUTHORIZED_EXECUTION_DOMAIN"):
        resolve_data_plan(compiled_data, start_date="2019-03-05", end_date="2019-03-05")


# ---------------------------------------------------------------------------
# Addition -- compiled_study.json vs study.yaml dataset_id parity
# ---------------------------------------------------------------------------

def test_stale_compiled_study_with_edited_dataset_id_is_rejected(tmp_path: Path):
    """Proves load_compiled_study()'s existing hash-integrity guard already catches a
    dataset_id divergence between study.yaml and compiled_study.json -- no new governance
    subsystem is needed for the A2 compiled/study parity requirement.
    """
    src = CLEAN_FLIP_STUDY
    dst = tmp_path / "study_copy"
    dst.mkdir()
    for rel in ("research_decision.yaml", "SPEC.md", "study.yaml", "compiled_study.json"):
        (dst / rel).write_bytes((src / rel).read_bytes())
    (dst / "artifacts").mkdir()
    (dst / "artifacts" / "phase0_source_manifest.json").write_text("{}", encoding="utf-8")

    # Edit only study.yaml's dataset_id; compiled_study.json is left stale on disk.
    with open(dst / "study.yaml", "r", encoding="utf-8") as f:
        ydata = yaml.safe_load(f)
    ydata["execution"]["data_requirements"]["dataset_id"] = "SOME_OTHER_DATASET"
    with open(dst / "study.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(ydata, f)

    with pytest.raises(StaleCompiledStudyError, match="STALE_COMPILED_STUDY"):
        load_compiled_study(dst)


def test_recompiling_after_dataset_id_edit_restores_parity(tmp_path: Path):
    """The same drift, but after running compile_study -- the existing pipeline restores
    parity and load_compiled_study succeeds with the new dataset_id in both places."""
    src = CLEAN_FLIP_STUDY
    dst = tmp_path / "study_copy"
    dst.mkdir()
    for rel in ("research_decision.yaml", "SPEC.md", "study.yaml", "compiled_study.json"):
        (dst / rel).write_bytes((src / rel).read_bytes())
    (dst / "artifacts").mkdir()
    (dst / "artifacts" / "phase0_source_manifest.json").write_text("{}", encoding="utf-8")

    with open(dst / "study.yaml", "r", encoding="utf-8") as f:
        ydata = yaml.safe_load(f)
    ydata["execution"]["data_requirements"]["dataset_id"] = "SOME_OTHER_DATASET"
    with open(dst / "study.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(ydata, f)

    rc = compile_study(dst)
    assert rc == 0

    compiled_data = load_compiled_study(dst)
    assert compiled_data.spec.execution.data_requirements["dataset_id"] == "SOME_OTHER_DATASET"
    with open(dst / "compiled_study.json", "r", encoding="utf-8") as f:
        compiled_json = json.load(f)
    assert compiled_json["spec"]["execution"]["data_requirements"]["dataset_id"] == "SOME_OTHER_DATASET"

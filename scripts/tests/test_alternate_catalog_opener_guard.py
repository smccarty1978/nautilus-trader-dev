"""Regression tests for Phase 1 Packet A3 (alternate entrypoint quarantine).

Covers:
  - scripts/scan_alternate_catalog_openers.py: the RFC's required static guard
  - the quarantine of studies/Codex_clean_maturity_flip_rolling_5m_productivity/
    implementation/run_collect.py, the RFC's named bypass target
"""

from __future__ import annotations

import importlib

import pytest

from scripts.scan_alternate_catalog_openers import (
    scan_source_for_alternate_catalog_openers,
    scan_study_for_alternate_catalog_openers,
)

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLEAN_FLIP_STUDY = REPO_ROOT / "studies" / "Codex_clean_maturity_flip_rolling_5m_productivity"
RUN_COLLECT_PY = CLEAN_FLIP_STUDY / "implementation" / "run_collect.py"


# ---------------------------------------------------------------------------
# 3/4/5 -- guard rule correctness on synthetic sources
# ---------------------------------------------------------------------------

def test_direct_parquet_data_catalog_call_is_flagged():
    src = (
        "from nautilus_trader.persistence.catalog import ParquetDataCatalog\n"
        "catalog = ParquetDataCatalog('data/catalog/NQ_v0_2020_2026')\n"
    )
    findings = scan_source_for_alternate_catalog_openers(src, Path("synthetic.py"))
    rules = {f.rule for f in findings}
    assert "DIRECT_CATALOG_CONSTRUCTION" in rules
    assert "HARDCODED_CATALOG_PATH_LITERAL" in rules


def test_hardcoded_catalog_path_assignment_is_flagged():
    src = 'CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"\n'
    findings = scan_source_for_alternate_catalog_openers(src, Path("synthetic.py"))
    assert len(findings) == 1
    assert findings[0].rule == "HARDCODED_CATALOG_PATH_LITERAL"


def test_windows_style_hardcoded_catalog_path_is_flagged():
    src = 'CATALOG_PATH = "data\\\\catalog\\\\NQ_v0_2020_2026"\n'
    findings = scan_source_for_alternate_catalog_openers(src, Path("synthetic.py"))
    assert any(f.rule == "HARDCODED_CATALOG_PATH_LITERAL" for f in findings)


def test_docstring_mention_is_not_flagged():
    src = (
        '"""This module historically referenced data/catalog/NQ_v0_2020_2026."""\n'
        "from pathlib import Path\n"
    )
    findings = scan_source_for_alternate_catalog_openers(src, Path("synthetic.py"))
    assert findings == []


def test_type_annotation_reference_is_not_flagged():
    src = (
        "from nautilus_trader.persistence.catalog import ParquetDataCatalog\n"
        "def f(catalog: ParquetDataCatalog) -> ParquetDataCatalog:\n"
        "    return catalog\n"
    )
    findings = scan_source_for_alternate_catalog_openers(src, Path("synthetic.py"))
    assert findings == []


def test_comment_mention_is_not_flagged():
    src = (
        "# this line mentions data/catalog/NQ_v0_2020_2026 in a comment\n"
        "x = 1\n"
    )
    findings = scan_source_for_alternate_catalog_openers(src, Path("synthetic.py"))
    assert findings == []


def test_function_and_class_docstrings_are_not_flagged():
    src = (
        "class Foo:\n"
        '    """References data/catalog/NQ_v0_2020_2026 for context."""\n'
        "    def bar(self):\n"
        '        """Also mentions data/catalog/NQ_v0_2020_2026."""\n'
        "        return 1\n"
    )
    findings = scan_source_for_alternate_catalog_openers(src, Path("synthetic.py"))
    assert findings == []


def test_syntax_error_source_is_skipped_not_raised():
    findings = scan_source_for_alternate_catalog_openers("def f(:\n", Path("broken.py"))
    assert findings == []


# ---------------------------------------------------------------------------
# 2 -- study-wide scan covers the full tree, not just top-level / closure
# ---------------------------------------------------------------------------

def test_scan_walks_nested_study_subdirectories(tmp_path: Path):
    (tmp_path / "implementation" / "deep" / "nested").mkdir(parents=True)
    bad_file = tmp_path / "implementation" / "deep" / "nested" / "sneaky.py"
    bad_file.write_text(
        "from nautilus_trader.persistence.catalog import ParquetDataCatalog\n"
        "c = ParquetDataCatalog('data/catalog/NQ_v0_2020_2026')\n",
        encoding="utf-8",
    )
    findings = scan_study_for_alternate_catalog_openers(tmp_path)
    assert any(f.file == bad_file for f in findings), (
        "scan must cover studies/<study>/**/*.py, not merely the execution closure or top level"
    )


def test_scan_is_clean_on_a_study_with_no_bypass(tmp_path: Path):
    (tmp_path / "implementation").mkdir()
    (tmp_path / "implementation" / "clean.py").write_text("x = 1\n", encoding="utf-8")
    assert scan_study_for_alternate_catalog_openers(tmp_path) == []


# ---------------------------------------------------------------------------
# 6 -- the real, quarantined CleanFlip study passes the guard end to end
# ---------------------------------------------------------------------------

def test_clean_flip_study_has_zero_alternate_catalog_openers():
    findings = scan_study_for_alternate_catalog_openers(CLEAN_FLIP_STUDY)
    assert findings == [], f"unexpected alternate catalog opener(s): {findings}"


def test_clean_flip_governed_adjacent_files_individually_pass():
    """The study's own collector/execution/contracts files -- adjacent to but not part
    of the bypass -- must not be false-positived by the guard."""
    for rel in ("implementation/collector.py", "implementation/execution.py", "implementation/contracts.py"):
        fp = CLEAN_FLIP_STUDY / rel
        if not fp.exists():
            continue
        from scripts.scan_alternate_catalog_openers import scan_file_for_alternate_catalog_openers
        findings = scan_file_for_alternate_catalog_openers(fp)
        assert findings == [], f"{rel} unexpectedly flagged: {findings}"


# ---------------------------------------------------------------------------
# 1 -- run_collect.py bypass is no longer executable
# ---------------------------------------------------------------------------

def test_run_collect_module_no_longer_constructs_a_catalog_or_engine():
    findings = scan_study_for_alternate_catalog_openers(CLEAN_FLIP_STUDY)
    assert not any(f.file == RUN_COLLECT_PY for f in findings)

    source = RUN_COLLECT_PY.read_text(encoding="utf-8")
    for forbidden in ("ParquetDataCatalog(", "BacktestEngine(", "CleanFlipCollector("):
        assert forbidden not in source, f"quarantine incomplete: found {forbidden!r} in run_collect.py"


def test_run_collect_main_refuses_to_run():
    mod = importlib.import_module(
        "studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.run_collect"
    )
    importlib.reload(mod)
    with pytest.raises(RuntimeError, match="QUARANTINED_ENTRYPOINT"):
        mod.main()


def test_run_collect_no_longer_exposes_a_collect_function():
    mod = importlib.import_module(
        "studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.run_collect"
    )
    importlib.reload(mod)
    assert not hasattr(mod, "collect"), (
        "the quarantined module must not still expose a working collect() bypass function"
    )


# ---------------------------------------------------------------------------
# 7 -- former dependents either go through the governed path or do not exist
# ---------------------------------------------------------------------------

def test_no_repo_file_imports_the_quarantined_module():
    target_dotted = (
        "studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.run_collect"
    )
    target_relative = "implementation.run_collect"
    hits = []
    self_file = Path(__file__).resolve()
    for py_file in REPO_ROOT.rglob("*.py"):
        if py_file in (RUN_COLLECT_PY, self_file):
            continue
        # Skip heavy/irrelevant trees for speed.
        parts = py_file.parts
        if any(p in (".claude", "__pycache__", "node_modules") for p in parts):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if target_dotted in text or (f"from {target_relative} import" in text):
            hits.append(py_file)
    assert hits == [], f"unexpected importer(s) of quarantined run_collect: {hits}"


def test_governed_entrypoint_module_still_resolves():
    """The one allowed execution route (RFC): backtests/run_nt_study.py -> collect mode."""
    from backtests.nt_runtime.modes.collect import run_collect_mode  # noqa: F401
    from backtests.nt_runtime.data_plan import resolve_data_plan  # noqa: F401
    assert (REPO_ROOT / "backtests" / "run_nt_study.py").exists()

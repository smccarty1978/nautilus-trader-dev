"""DEV-03 (2026-09-05, surfaced by the supv1_shape_a_flip_180s contract audit): the frozen execution closure must contain
every repo-local module the bound trackers/providers import, transitively, including lazy imports inside functions.
Before this the tracker binding shims were frozen but not features/trackers/regime_dual_ema.py (the label event),
rolling_5m_productivity.py or structural_regime_geometry.py, so editing them left every closure gate passing."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_workflow.grammar.compiler import _static_imports, transitive_closure_files  # noqa: E402

OMITTED_BEFORE = ("features/trackers/regime_dual_ema.py", "features/trackers/rolling_5m_productivity.py", "features/trackers/structural_regime_geometry.py")


def _tree(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "features" / "trackers").mkdir(parents=True); (r / "research_workflow").mkdir(); (r / "features" / "tests").mkdir()
    (r / "features" / "__init__.py").write_text("", encoding="utf-8"); (r / "features" / "trackers" / "__init__.py").write_text("", encoding="utf-8")
    (r / "research_workflow" / "__init__.py").write_text("", encoding="utf-8"); (r / "features" / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (r / "features" / "trackers" / "shim.py").write_text(
        "from research_workflow import interfaces\n"
        "class Binding:\n"
        "    def __init__(self):\n"
        "        from features.trackers.impl import Tracker   # lazy import inside a method\n"
        "        self.t = Tracker()\n", encoding="utf-8")
    (r / "features" / "trackers" / "impl.py").write_text("from . import helpers\nfrom .. import registry\nimport json\nclass Tracker: pass\n", encoding="utf-8")
    (r / "features" / "trackers" / "helpers.py").write_text("import numpy\n", encoding="utf-8")
    (r / "features" / "registry.py").write_text("from features.tests import fixtures\n", encoding="utf-8")
    (r / "features" / "tests" / "fixtures.py").write_text("from features.trackers import impl\n", encoding="utf-8")
    (r / "research_workflow" / "interfaces.py").write_text("x = 1\n", encoding="utf-8")
    return r


def test_static_walk_follows_lazy_relative_and_package_imports_but_not_tests(tmp_path):
    r = _tree(tmp_path)
    # a `from pkg import name` names the package (its __init__) AND the submodule when `name` is one
    assert _static_imports("features/trackers/shim.py", r) == {"research_workflow/__init__.py", "research_workflow/interfaces.py", "features/trackers/impl.py"}
    assert _static_imports("features/trackers/impl.py", r) == {"features/trackers/__init__.py", "features/trackers/helpers.py", "features/__init__.py", "features/registry.py"}   # relative + parent-package; json/numpy ignored
    closure = transitive_closure_files({"features/trackers/shim.py"}, r)
    assert closure == {"features/trackers/shim.py", "research_workflow/__init__.py", "research_workflow/interfaces.py", "features/trackers/impl.py",
                       "features/trackers/__init__.py", "features/trackers/helpers.py", "features/__init__.py", "features/registry.py"}
    assert not any("tests" in f for f in closure)
    assert transitive_closure_files({"features/trackers/shim.py"}, r) == closure      # deterministic


def test_reference_study_closure_now_freezes_the_label_and_feature_modules():
    from research_workflow.grammar.compiler import compile_study, load_spec
    out = compile_study(load_spec(ROOT / "studies" / "v2_shape_a_flip_180s"), repo_root=ROOT)
    assert out.ok, out.gaps.to_dict()
    files = set(out.plan.closure["files"])
    for rel in OMITTED_BEFORE:
        assert rel in files, rel
    assert set(out.plan.closure["stages"]["collection"]["files"]) >= set(OMITTED_BEFORE)
    assert out.plan.closure["file_count"] > 45                        # the sealed reference manifest listed 45 files
    assert out.plan.card()["catalog_opened"] is False
    # every closure member exists and is hashed: no phantom paths from the walk
    assert all((ROOT / rel).is_file() for rel in files)
    assert not any("/tests/" in rel for rel in files)


def test_editing_a_previously_unfrozen_module_now_changes_the_composite(tmp_path, monkeypatch):
    """The gate must cover the deliverable it vouches for: a byte change in regime_dual_ema.py changes the closure composite."""
    from research_workflow.grammar import compiler as C
    from research_workflow.grammar.compiler import compile_study, load_spec
    spec = load_spec(ROOT / "studies" / "v2_shape_a_flip_180s")
    before = compile_study(spec, repo_root=ROOT).plan.closure["composite_sha256"]
    real = C.hash_file_v2 if hasattr(C, "hash_file_v2") else None
    from research_workflow import closure_hash
    target = (ROOT / "features/trackers/regime_dual_ema.py").resolve()
    orig = closure_hash.hash_file_v2

    def tampered(p: Path):
        h = orig(p)
        return ("0" * 8 + h[8:]) if Path(p).resolve() == target else h
    monkeypatch.setattr(closure_hash, "hash_file_v2", tampered)
    after = compile_study(spec, repo_root=ROOT).plan.closure["composite_sha256"]
    assert after != before

"""Red-team packet F2: zero-study-Python is mechanically enforced, not taken on faith.

Any *.py/*.pyw/*.ipynb committed OR untracked under a v2 study directory (outside
_work/ and runs/) fails READINESS (R10_zero_study_python) and PREFLIGHT
(ZERO_STUDY_PYTHON), unless the study id is sanctioned in
research_workflow.policy.STUDY_PYTHON_EXCEPTIONS -- a platform code change, never a
study-side declaration.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research_workflow.lifecycle_v2 import LifecycleV2Error, V2Lifecycle, V2Options
from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
from research_workflow.tests.test_lifecycle_v2 import GOLDEN, ROOT, _study_dir, synthetic_bars  # noqa: F401  (fixture reuse)

NS = 1_000_000_000


def _ready_lifecycle(tmp_path: Path, synthetic_bars, study_id: str = "golden_v2_flow") -> V2Lifecycle:
    bars, expected = synthetic_bars
    study = _study_dir(tmp_path)
    if study_id != study.name:
        study = study.rename(study.parent / study_id)
        spec = (study / "study.yaml").read_text(encoding="utf-8").replace("id: golden_v2_flow", f"id: {study_id}")
        (study / "study.yaml").write_text(spec, encoding="utf-8")
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    opts = V2Options(datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS, bar_source=lambda s, e: bars, session_table_spec=session)
    lc = V2Lifecycle(study, repo_root=ROOT, options=opts)
    lc.compile()
    lc.prepare()
    return lc


def test_arbitrary_helper_py_fails_readiness_and_preflight(tmp_path, synthetic_bars):
    lc = _ready_lifecycle(tmp_path, synthetic_bars)
    (lc.study / "helpers.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(LifecycleV2Error, match="READINESS_FAILED"):
        lc.readiness()
    import json
    readiness = json.loads((lc.audit / "readiness.json").read_text())
    r10 = next(c for c in readiness["checks"] if c["id"] == "R10_zero_study_python")
    assert not r10["passed"] and "helpers.py" in r10["detail"]


def test_nested_implementation_py_fails(tmp_path, synthetic_bars):
    lc = _ready_lifecycle(tmp_path, synthetic_bars)
    nested = lc.study / "implementation" / "x.py"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("x = 1\n", encoding="utf-8")
    py_files, exc = lc._zero_study_python()
    assert "implementation/x.py" in py_files and exc is None


def test_notebook_fails(tmp_path, synthetic_bars):
    lc = _ready_lifecycle(tmp_path, synthetic_bars)
    (lc.study / "scratch.ipynb").write_text("{}", encoding="utf-8")
    py_files, exc = lc._zero_study_python()
    assert "scratch.ipynb" in py_files and exc is None


def test_work_directory_python_is_ignored(tmp_path, synthetic_bars):
    lc = _ready_lifecycle(tmp_path, synthetic_bars)
    scratch = lc.study / "_work" / "scratch.py"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text("x = 1\n", encoding="utf-8")
    py_files, exc = lc._zero_study_python()
    assert py_files == []
    card = lc.readiness()
    assert card["status"] == "PASS"


def test_allowlisted_study_id_passes_with_exception_recorded(tmp_path, synthetic_bars, monkeypatch):
    lc = _ready_lifecycle(tmp_path, synthetic_bars, study_id="allowlisted_study")
    (lc.study / "helpers.py").write_text("x = 1\n", encoding="utf-8")
    import research_workflow.policy as policy
    monkeypatch.setitem(policy.STUDY_PYTHON_EXCEPTIONS, "allowlisted_study", "platform migration shim, tracked in policy.py")
    py_files, exc = lc._zero_study_python()
    assert py_files and exc == "platform migration shim, tracked in policy.py"
    card = lc.readiness()
    assert card["status"] == "PASS"
    import json
    r10 = next(c for c in json.loads((lc.audit / "readiness.json").read_text())["checks"] if c["id"] == "R10_zero_study_python")
    assert r10["passed"] and "helpers.py" in r10["detail"] and "platform migration shim" in r10["detail"]


def test_uppercase_py_extension_bypass_still_fails(tmp_path, synthetic_bars):
    """Windows extension matching must be case-insensitive: a `.PY` file is still executable Python."""
    lc = _ready_lifecycle(tmp_path, synthetic_bars)
    (lc.study / "helpers.PY").write_text("x = 1\n", encoding="utf-8")
    py_files, exc = lc._zero_study_python()
    assert "helpers.PY" in py_files and exc is None


def test_preflight_reports_zero_study_python(tmp_path, synthetic_bars):
    lc = _ready_lifecycle(tmp_path, synthetic_bars)
    lc.readiness()
    (lc.study / "helpers.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(LifecycleV2Error, match="ZERO_STUDY_PYTHON"):
        lc.preflight()
    import json
    preflight = json.loads((lc.audit / "preflight.json").read_text())
    assert preflight["check_outcomes"]["ZERO_STUDY_PYTHON"].startswith("FAILED")
    assert preflight["study_python"]["python_files"] == ["helpers.py"]

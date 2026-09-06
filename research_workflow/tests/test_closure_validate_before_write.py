"""DEV-08 (2026-09-05, Supervisor V1 validation, study supv1_shape_a_flip_180s): lifecycle_v2.close() wrote
artifacts/study_closure.json and only then validated it; a rejected closure (undeclared terminal_decision) stayed on
disk and was subsequently honoured as the study's terminal authority. close() must validate before persisting and must
never leave a rejected closure behind."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _study(tmp_path: Path) -> Path:
    s = tmp_path / "studies" / "s1"; (s / "artifacts").mkdir(parents=True)
    (s / "study.yaml").write_text("study: {id: s1}\n", encoding="utf-8")
    (s / "research_decision.yaml").write_text("study_id: s1\nterminal_decisions:\n  DECLARED_A: 'the only admissible decision'\n", encoding="utf-8")
    (s / "compiled_plan.json").write_text('{"plan_sha256": "p"}', encoding="utf-8")
    return s


def test_close_refuses_an_undeclared_decision_and_leaves_no_closure_behind(tmp_path):
    from research_workflow.lifecycle_v2 import LifecycleV2Error, V2Lifecycle, V2Options
    from research_workflow.study_closure import StudyClosureInvalid
    s = _study(tmp_path)
    lc = V2Lifecycle(s, repo_root=ROOT, options=V2Options(execute=True, closure={"outcome": "X", "terminal_decision": "UNDECLARED"}))
    with pytest.raises((StudyClosureInvalid, LifecycleV2Error), match="TERMINAL_DECISION_UNDECLARED"):
        lc.close()
    assert not (s / "artifacts" / "study_closure.json").exists(), "a rejected closure must never persist"


def test_close_removes_a_closure_whose_evidence_authentication_fails(tmp_path):
    """The decision is declared but the bound evidence (seal) is missing: the post-write validator rejects it; nothing remains."""
    from research_workflow.lifecycle_v2 import LifecycleV2Error, V2Lifecycle, V2Options
    from research_workflow.study_closure import StudyClosureInvalid
    s = _study(tmp_path)
    lc = V2Lifecycle(s, repo_root=ROOT, options=V2Options(execute=True, closure={"outcome": "X", "terminal_decision": "DECLARED_A"}))
    with pytest.raises((StudyClosureInvalid, LifecycleV2Error)):
        lc.close()
    assert not (s / "artifacts" / "study_closure.json").exists()

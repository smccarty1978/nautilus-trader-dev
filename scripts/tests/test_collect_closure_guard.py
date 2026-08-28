import json
import pytest
from backtests.nt_runtime.modes import collect

def test_direct_collect_closed_and_malformed_stop_before_loader(tmp_path, monkeypatch):
    study=tmp_path/"s"; (study/"artifacts").mkdir(parents=True)
    monkeypatch.setattr(collect,"load_compiled_study",lambda *_: (_ for _ in ()).throw(AssertionError("loader reached")))
    (study/"artifacts/study_closure.json").write_text(json.dumps({"schema_version":1,"study_id":"s","status":"CLOSED","outcome":"x","terminal_decision":"x"}))
    with pytest.raises(RuntimeError,match="STUDY_CLOSED"): collect.run_collect_mode(study)
    (study/"artifacts/study_closure.json").write_text("{")
    with pytest.raises(RuntimeError,match="STUDY_CLOSURE_INVALID"): collect.run_collect_mode(study)

def test_direct_collect_absence_reaches_loader(tmp_path, monkeypatch):
    study=tmp_path/"s"; study.mkdir()
    monkeypatch.setattr(collect,"load_compiled_study",lambda *_: (_ for _ in ()).throw(RuntimeError("loader reached")))
    with pytest.raises(RuntimeError,match="loader reached"): collect.run_collect_mode(study)

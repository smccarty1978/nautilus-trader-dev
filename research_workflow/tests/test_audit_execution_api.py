import json

from research_workflow import causal_audit, contract_audit


def _frozen_study(tmp_path):
    study = tmp_path / "study"
    audit = study / "audit"
    audit.mkdir(parents=True)
    (audit / "frozen_execution_manifest.json").write_text(
        json.dumps({"frozen_execution_composite_sha256": "a" * 64}), encoding="utf-8"
    )
    return study


def test_causal_api_executes_and_writes_evidence(tmp_path, monkeypatch):
    study = _frozen_study(tmp_path)
    monkeypatch.setattr("scripts.resolve_execution_manifest.resolve_execution_manifest",
                        lambda study: ("a" * 64, {}, {}))
    monkeypatch.setattr(causal_audit, "_run_checks", lambda study, composite: [{"name": "fixture", "passed": True}])
    monkeypatch.setattr("scripts.run_preexec_audits.issue_causal_audit_status_from_report",
                        lambda *args, **kwargs: {"verdict": "CLEAR"})
    result = causal_audit.run_causal_review(study)
    assert result["status"] == "CLEAR"
    assert (study / "audit" / "pass_01.md").is_file()


def test_contract_api_executes_and_writes_evidence(tmp_path, monkeypatch):
    study = _frozen_study(tmp_path)
    (study / "compiled_study.json").write_text(json.dumps({"spec": {"features": {"instances": [{}]}}}), encoding="utf-8")
    (study / "config").mkdir()
    for name in ("deliverables_contract.json", "population_contract.json", "target_contract.json"):
        (study / "config" / name).write_text("{}", encoding="utf-8")
    (study / "artifacts").mkdir()
    (study / "artifacts" / "phase0_source_manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("scripts.resolve_execution_manifest.resolve_execution_manifest",
                        lambda study: ("a" * 64, {}, {}))
    monkeypatch.setattr("scripts.run_preexec_audits.issue_contract_audit_status_from_report",
                        lambda *args, **kwargs: {"verdict": "CLEAR"})
    # The real contract checks require the complete study instance surface; patch
    # only the compiled payload while exercising report/status generation.
    payload = {"spec": {"features": {"instances": [{"feature": "x", "parameters": {}} for _ in range(13)]},
                         "execution": "research_workflow.generic_collector"}}
    (study / "compiled_study.json").write_text(json.dumps(payload), encoding="utf-8")
    result = contract_audit.run_contract_review(study)
    assert result["status"] == "CLEAR"
    assert (study / "audit" / "contract_pass_01.md").is_file()


def test_causal_api_rejects_stale_freeze(tmp_path, monkeypatch):
    study = _frozen_study(tmp_path)
    monkeypatch.setattr("scripts.resolve_execution_manifest.resolve_execution_manifest",
                        lambda study: ("b" * 64, {}, {}))
    result = causal_audit.run_causal_review(study)
    assert result["status"] == "BLOCKED"
    assert "STALE_FREEZE" in result["findings"][0]

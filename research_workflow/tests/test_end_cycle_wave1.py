"""END THE CYCLE Wave 1: intake completeness and terminal evidence integrity."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from research_workflow.grammar.compiler import compile_study, load_spec
from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options
from research_workflow.study_closure import StudyClosureInvalid, load_study_closure
from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures/golden"


def compile_fixture(spec):
    return compile_study(spec, repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)


def test_es_intake_names_missing_threshold_and_importance_producers(tmp_path):
    source = ROOT / "studies/es_180s_model_c_portability"
    study = tmp_path / source.name
    study.mkdir()
    for name in ("study.yaml", "research_decision.yaml"):
        shutil.copyfile(source / name, study / name)
    out = compile_study(load_spec(study), repo_root=ROOT)
    assert not out.ok, "ES intake must never compile with its declared unproduced deliverables"
    missing = [g for g in out.card()["gaps"] if g["kind"] == "MISSING_CAPABILITY"]
    assert any("P90/P95/P97.5" in g["message"] for g in missing), missing
    assert any("feature importance" in g["message"] for g in missing), missing
    assert not (study / "compiled_plan.json").exists()


def test_authority_deliverables_cannot_be_hidden_by_study_yaml(tmp_path):
    spec = load_spec(GOLDEN / "study_barrier.yaml")
    spec["deliverables"] = ["compiled_plan.json"]
    (tmp_path / "study.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    (tmp_path / "research_decision.yaml").write_text("deliverables: ['feature importance table per direction']\n", encoding="utf-8")
    out = compile_fixture(load_spec(tmp_path))
    assert not out.ok
    assert any("feature importance" in g["message"] for g in out.card()["gaps"])


def test_registered_stage_deliverable_has_hashed_producer_binding():
    spec = load_spec(GOLDEN / "study_barrier.yaml")
    spec["deliverables"] = [{"artifact": "compiled_plan.json", "producer": "stage:compile"}]
    out = compile_fixture(spec)
    assert out.ok, out.card()
    proof = out.plan.to_dict()["deliverables"]
    assert proof == [{"artifact": "compiled_plan.json", "producer": "stage:compile"}]
    original = out.plan.plan_sha256
    out.plan.deliverables[0]["producer"] = "stage:invented"
    assert out.plan.seal().plan_sha256 != original


@pytest.mark.parametrize("declaration", [
    "unknown_future_output.json",
    "artifacts/experiment_models.json",  # no model is declared
    "artifacts/experiment_analysis_v2.json",  # neither analysis pipeline nor dev
    "_work/controller/partitions/train/2025/candidates.parquet",  # unauthorized year
    "_work/controller/partitions/oos/2030/candidates.parquet",
    {"artifact": "compiled_plan.json", "producer": "stage:fit"},
    {"artifact": "artifacts/importance.json", "producer": "stage:fit"},
    {"artifact": "artifacts/tuning_trials.json", "producer": "stage:fit"},
    {"artifact": "artifacts/missing.json", "producer": "analysis:missing"},
])
def test_missing_or_inactive_producers_fail_as_typed_gaps(declaration):
    spec = load_spec(GOLDEN / "study_barrier.yaml")
    spec["deliverables"] = [declaration]
    out = compile_fixture(spec)
    assert not out.ok
    assert any(g["kind"] == "MISSING_CAPABILITY" for g in out.card()["gaps"]), out.card()


def closed_fixture(tmp_path):
    study = tmp_path / "closed_v2"
    art = study / "artifacts"
    art.mkdir(parents=True)
    (study / "compiled_plan.json").write_text('{"plan_sha256":"fixture"}', encoding="utf-8")
    (art / "preexec_audit_seal.json").write_text('{"composite_seal_hash":"fixture"}', encoding="utf-8")
    (art / "experiment_analysis_v2.json").write_text('{"metric":0.7}', encoding="utf-8")
    (art / "analysis_decision.json").write_text('{"outcome":"COMPLETE","terminal_decision":"DONE","rationale":"fixture"}', encoding="utf-8")
    lc = V2Lifecycle(study, repo_root=ROOT, options=V2Options(execute=True, closure={"outcome":"COMPLETE", "terminal_decision":"DONE"}))
    lc.close()
    assert load_study_closure(study)
    return study


@pytest.mark.parametrize("filename", ["experiment_analysis_v2.json", "analysis_decision.json"])
def test_v2_final_evidence_perturbation_invalidates_scratch_closed_copy(tmp_path, filename):
    study = closed_fixture(tmp_path)
    scratch = tmp_path / "scratch" / study.name
    shutil.copytree(study, scratch)
    p = scratch / "artifacts" / filename
    p.write_text('{"tampered":true}', encoding="utf-8")
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_MISMATCH"):
        load_study_closure(scratch)
    assert load_study_closure(study)


@pytest.mark.parametrize("key", ["v2_analysis", "v2_decision"])
@pytest.mark.parametrize("bad_value", [None, {}, {"path":"artifacts/other.json","artifact_file_sha256":"a"*64}])
def test_v2_bindings_cannot_be_omitted_malformed_or_redirected(tmp_path, key, bad_value):
    study = closed_fixture(tmp_path)
    p = study / "artifacts/study_closure.json"
    body = json.loads(p.read_text())
    if bad_value is None:
        body["bound_evidence"].pop(key, None)
    else:
        body["bound_evidence"][key] = bad_value
    p.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(StudyClosureInvalid):
        load_study_closure(study)


@pytest.mark.parametrize("filename", ["experiment_analysis_v2.json", "analysis_decision.json"])
def test_deleting_bound_v2_evidence_is_invalid(tmp_path, filename):
    study = closed_fixture(tmp_path)
    (study / "artifacts" / filename).unlink()
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_MISSING"):
        load_study_closure(study)


def test_workflow_engine_perturbation_moves_only_lifecycle(monkeypatch):
    import research_workflow.closure_hash as hashing
    spec = load_spec(GOLDEN / "study_barrier.yaml")
    before = compile_fixture(spec).plan.closure
    original = hashing.hash_file_v2
    target = "research_workflow/workflow_engine.py"

    def perturbed(path):
        digest = original(path)
        if Path(path).resolve() == (ROOT / target).resolve():
            return hashlib.sha256((digest + "perturbation").encode()).hexdigest()
        return digest

    monkeypatch.setattr(hashing, "hash_file_v2", perturbed)
    after = compile_fixture(spec).plan.closure
    assert before["composite_sha256"] != after["composite_sha256"]
    changed = {stage for stage in before["stages"] if before["stages"][stage]["composite_sha256"] != after["stages"][stage]["composite_sha256"]}
    assert changed == {"lifecycle"}
    assert target in after["files"]


def test_decision_deliverables_participate_in_controller_freshness(tmp_path):
    from research_workflow.lifecycle_v2 import spec_sha256
    spec = load_spec(GOLDEN / "study_barrier.yaml")
    (tmp_path / "study.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    decision = tmp_path / "research_decision.yaml"
    decision.write_text("deliverables: ['compiled_plan.json']", encoding="utf-8")
    out = compile_fixture(load_spec(tmp_path))
    assert out.ok, out.card()
    assert spec_sha256(tmp_path) == out.plan.spec_sha256
    decision.write_text("deliverables: ['compiled_plan.json', 'feature importance']", encoding="utf-8")
    assert spec_sha256(tmp_path) != out.plan.spec_sha256
    assert not compile_fixture(load_spec(tmp_path)).ok


def test_analysis_producer_binds_only_its_declared_artifacts():
    from research_workflow.tests.test_declarative_analysis import ANALYSIS
    import copy
    spec = load_spec(GOLDEN / "study_barrier.yaml")
    spec["analysis"] = copy.deepcopy(ANALYSIS)
    artifact = spec["analysis"]["artifacts"][0]
    spec["deliverables"] = [{"artifact": "artifacts/" + artifact["name"], "producer": "analysis:" + artifact["source"]}]
    out = compile_fixture(spec)
    assert out.ok, out.card()
    assert out.plan.deliverables == spec["deliverables"]
    spec["analysis"]["artifacts"].pop(0)
    out = compile_fixture(spec)
    assert not out.ok
    assert any(g["kind"] == "MISSING_CAPABILITY" for g in out.card()["gaps"])


def test_authorized_partition_and_no_model_summary_producers():
    spec = load_spec(GOLDEN / "study_barrier.yaml")
    spec["deliverables"] = ["artifacts/fit_summary.json", "_work/controller/partitions/train/2030/candidates.parquet"]
    out = compile_fixture(spec)
    assert out.ok, out.card()
    assert [b["producer"] for b in out.plan.deliverables] == ["stage:fit", "stage:collection"]

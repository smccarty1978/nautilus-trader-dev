"""Closure fixes B1/B2/B3 (cleanup-and-closure packet, 2026-09-10).

B1  Five closures written before commit 5d3aad6a bind only seal and freeze. They validate through a
    recorded, date-bounded, hash-pinned exemption -- never re-closed. Anything closed after the rule
    with unbound final evidence still fails, and the record cannot be widened past the cutoff.
B2  Site 9: a bound Stage 17 decision whose canonical artifact cannot be classified is refused
    (absence is not FRESH), matching the Stage 16 branch.
B3  V2 final evidence is fresh only when produced from THIS plan and THIS TRAIN freeze: the same
    bytes under a changed plan, an analysis scoring models the bound freeze does not bind, or a
    decision that was not about the analysis on disk are all refused.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from research_workflow import study_closure as sc
from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options
from research_workflow.study_closure import (
    GRANDFATHER_PATH,
    StudyClosureInvalid,
    load_grandfather_record,
    load_study_closure,
)

ROOT = Path(__file__).resolve().parents[2]
GRANDFATHERED = (
    "v2_shape_a_flip_180s",
    "v2_shape_b_deep_pullback_5s",
    "v2_shape_c_barrier_race_fade",
    "first_p90_warning_horizon_march2024",
    "es_180s_model_c_portability",
)
RULE_COMMIT = "5d3aad6a7c529677f8066e34d63be64ac4d0b730"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _rewrite(path: Path, mutate) -> None:
    body = json.loads(path.read_text(encoding="utf-8"))
    mutate(body)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# a hermetic V2 study closed through the real writer
# --------------------------------------------------------------------------- #
def closed_v2_study(tmp_path: Path, *, name: str = "closed_v2", plan: str = "plan-A", model_ids=("m1", "m2")) -> Path:
    study = tmp_path / name
    art = study / "artifacts"
    art.mkdir(parents=True)
    (study / "compiled_plan.json").write_text(json.dumps({"plan_sha256": plan}), encoding="utf-8")
    (art / "preexec_audit_seal.json").write_text('{"composite_seal_hash":"seal"}', encoding="utf-8")
    freeze = {"plan_sha256": plan, "model_hashes": {f"primary:{i}": mid for i, mid in enumerate(model_ids)},
              "model_canonical_sha256": {}, "freeze_sha256": "freeze-" + plan}
    (art / "train_experiment_freeze.json").write_text(json.dumps(freeze), encoding="utf-8")
    analysis = {"schema_version": 2, "plan_sha256": plan, "metric": 0.7,
                "frozen_models_oos": [{"id": mid, "roc_auc": 0.6} for mid in model_ids],
                "train_metrics": [{"id": mid, "metrics": {}} for mid in model_ids]}
    (art / "experiment_analysis_v2.json").write_text(json.dumps(analysis), encoding="utf-8")
    decision = {"study_id": name, "outcome": "COMPLETE", "terminal_decision": "DONE", "rationale": "fixture",
                "evidence": [{"path": "artifacts/experiment_analysis_v2.json", "sha256": _sha(art / "experiment_analysis_v2.json")},
                             {"path": "artifacts/train_experiment_freeze.json", "sha256": _sha(art / "train_experiment_freeze.json")}]}
    (art / "analysis_decision.json").write_text(json.dumps(decision), encoding="utf-8")
    lc = V2Lifecycle(study, repo_root=ROOT, options=V2Options(execute=True, closure={"outcome": "COMPLETE", "terminal_decision": "DONE"}))
    lc.close()
    assert load_study_closure(study)
    return study


# --------------------------------------------------------------------------- #
# B3 -- freshness against the plan and the TRAIN freeze it was produced from
# --------------------------------------------------------------------------- #
def test_writer_binds_plan_and_freeze_into_the_analysis_binding(tmp_path):
    study = closed_v2_study(tmp_path)
    closure = json.loads((study / "artifacts/study_closure.json").read_text())
    binding = closure["bound_evidence"]["v2_analysis"]
    assert binding["plan_sha256"] == "plan-A"
    assert binding["train_freeze_sha256"] == closure["bound_evidence"]["train_freeze_sha256"]


def test_same_bytes_but_plan_changed_underneath_is_refused(tmp_path):
    study = closed_v2_study(tmp_path)
    analysis_before = _sha(study / "artifacts/experiment_analysis_v2.json")
    (study / "compiled_plan.json").write_text(json.dumps({"plan_sha256": "plan-B"}), encoding="utf-8")
    assert _sha(study / "artifacts/experiment_analysis_v2.json") == analysis_before  # unchanged bytes
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_STALE.*produced from plan"):
        load_study_closure(study)


def test_analysis_from_an_earlier_plan_is_refused_even_when_closure_rebinds_its_bytes(tmp_path):
    study = closed_v2_study(tmp_path)
    p = study / "artifacts/experiment_analysis_v2.json"
    _rewrite(p, lambda b: b.__setitem__("plan_sha256", "plan-OLD"))
    # a closure that re-authenticates the stale bytes must still be refused
    _rewrite(study / "artifacts/study_closure.json", lambda b: b["bound_evidence"]["v2_analysis"].__setitem__("artifact_file_sha256", _sha(p)))
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_STALE.*produced from plan"):
        load_study_closure(study)


def test_analysis_scoring_models_the_bound_freeze_does_not_bind_is_refused(tmp_path):
    study = closed_v2_study(tmp_path)
    p = study / "artifacts/experiment_analysis_v2.json"
    _rewrite(p, lambda b: b["frozen_models_oos"].append({"id": "m-from-an-earlier-freeze"}))
    _rewrite(study / "artifacts/study_closure.json", lambda b: b["bound_evidence"]["v2_analysis"].__setitem__("artifact_file_sha256", _sha(p)))
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_STALE.*freeze does not bind"):
        load_study_closure(study)


def test_freeze_of_a_different_plan_is_refused(tmp_path):
    study = closed_v2_study(tmp_path)
    fz = study / "artifacts/train_experiment_freeze.json"
    _rewrite(fz, lambda b: b.__setitem__("plan_sha256", "plan-OLD"))
    # rebind the freeze bytes so only the plan lineage is at issue
    _rewrite(study / "artifacts/study_closure.json", lambda b: b["bound_evidence"].__setitem__("train_freeze_sha256", "freeze-plan-A"))
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_STALE.*TRAIN freeze is of plan"):
        load_study_closure(study)


def test_decision_that_does_not_cite_the_analysis_is_refused(tmp_path):
    study = closed_v2_study(tmp_path)
    p = study / "artifacts/analysis_decision.json"
    _rewrite(p, lambda b: b.__setitem__("evidence", []))
    _rewrite(study / "artifacts/study_closure.json", lambda b: b["bound_evidence"]["v2_decision"].__setitem__("artifact_file_sha256", _sha(p)))
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_STALE.*does not cite"):
        load_study_closure(study)


def test_decision_made_about_a_different_analysis_is_refused(tmp_path):
    study = closed_v2_study(tmp_path)
    p = study / "artifacts/analysis_decision.json"
    _rewrite(p, lambda b: b["evidence"][0].__setitem__("sha256", "0" * 64))
    _rewrite(study / "artifacts/study_closure.json", lambda b: b["bound_evidence"]["v2_decision"].__setitem__("artifact_file_sha256", _sha(p)))
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_STALE.*decided on a different"):
        load_study_closure(study)


def test_decision_citing_by_path_only_is_accepted_when_it_names_the_analysis(tmp_path):
    """The supervisor's scripted decisions cite by relative path without a hash."""
    study = closed_v2_study(tmp_path)
    p = study / "artifacts/analysis_decision.json"
    _rewrite(p, lambda b: b.__setitem__("evidence", ["artifacts/experiment_analysis_v2.json"]))
    _rewrite(study / "artifacts/study_closure.json", lambda b: b["bound_evidence"]["v2_decision"].__setitem__("artifact_file_sha256", _sha(p)))
    assert load_study_closure(study)


def test_close_refuses_an_analysis_that_does_not_carry_its_plan(tmp_path):
    study = tmp_path / "noplan"
    art = study / "artifacts"; art.mkdir(parents=True)
    (study / "compiled_plan.json").write_text('{"plan_sha256":"plan-A"}', encoding="utf-8")
    (art / "preexec_audit_seal.json").write_text('{"composite_seal_hash":"seal"}', encoding="utf-8")
    (art / "experiment_analysis_v2.json").write_text('{"metric":0.7}', encoding="utf-8")
    lc = V2Lifecycle(study, repo_root=ROOT, options=V2Options(execute=True, closure={"outcome": "X", "terminal_decision": "Y"}))
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_STALE"):
        lc.close()
    assert not (art / "study_closure.json").exists()


# --------------------------------------------------------------------------- #
# B1 -- the five grandfathered closures
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("study_id", GRANDFATHERED)
def test_grandfathered_closure_validates_without_reclosing(study_id):
    study = ROOT / "studies" / study_id
    if not (study / "artifacts/study_closure.json").is_file():
        pytest.skip(f"{study_id} not present in this checkout")
    closure = load_study_closure(study)
    assert closure and closure["status"] == "CLOSED"
    assert "v2_analysis" not in (closure.get("bound_evidence") or {})   # NOT re-closed


def test_grandfather_record_is_date_bounded_and_names_exactly_the_five():
    record = load_grandfather_record()
    assert record["rule_commit"] == RULE_COMMIT
    cutoff = sc._utc(record["rule_commit_utc"])
    assert set(record["closures"]) == set(GRANDFATHERED)
    for study_id, entry in record["closures"].items():
        assert sc._utc(entry["closed_at_utc"]) < cutoff, study_id
        assert entry["final_evidence"].get("artifacts/experiment_analysis_v2.json"), study_id


def test_record_entry_at_or_after_the_rule_commit_is_refused(tmp_path, monkeypatch):
    record = json.loads(GRANDFATHER_PATH.read_text(encoding="utf-8"))
    late = tmp_path / "late.json"
    entry = dict(next(iter(record["closures"].values())))
    entry["closed_at_utc"] = record["rule_commit_utc"]
    record["closures"] = {"late_study": entry}
    late.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(StudyClosureInvalid, match="GRANDFATHER_OUT_OF_BOUNDS"):
        load_grandfather_record(late)


def test_closure_after_the_rule_with_unbound_final_evidence_still_fails(tmp_path, monkeypatch):
    """Adversarial: even a study listed in the record is refused when its closure post-dates the rule."""
    study = closed_v2_study(tmp_path, name="post_rule")
    closure_path = study / "artifacts/study_closure.json"

    def strip(b):
        b["bound_evidence"].pop("v2_analysis"); b["bound_evidence"].pop("v2_decision")
    _rewrite(closure_path, strip)
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_MISSING: closure omits"):
        load_study_closure(study)

    # forge an exemption entry for it: the record loader refuses a post-rule closed_at_utc ...
    record = json.loads(GRANDFATHER_PATH.read_text(encoding="utf-8"))
    body = json.loads(closure_path.read_text())
    from scripts.resolve_execution_manifest import canonical_file_sha256
    forged = dict(record)
    forged["closures"] = {"post_rule": {"closed_at_utc": body["closed_at_utc"],
                                        "closure_artifact_sha256": canonical_file_sha256(closure_path),
                                        "final_evidence": {"artifacts/experiment_analysis_v2.json": canonical_file_sha256(study / "artifacts/experiment_analysis_v2.json"),
                                                           "artifacts/analysis_decision.json": canonical_file_sha256(study / "artifacts/analysis_decision.json")}}}
    forged_path = tmp_path / "forged.json"; forged_path.write_text(json.dumps(forged), encoding="utf-8")
    monkeypatch.setattr(sc, "GRANDFATHER_PATH", forged_path)
    monkeypatch.setattr(sc.load_grandfather_record, "__defaults__", (forged_path,))
    with pytest.raises(StudyClosureInvalid, match="GRANDFATHER_OUT_OF_BOUNDS"):
        load_study_closure(study)

    # ... and a back-dated closed_at_utc changes the closure bytes, so the pinned hash refuses it too
    early = (sc._utc(record["rule_commit_utc"]) - timedelta(days=1)).isoformat()
    _rewrite(closure_path, lambda b: b.__setitem__("closed_at_utc", early))
    forged["closures"]["post_rule"]["closed_at_utc"] = early
    forged_path.write_text(json.dumps(forged), encoding="utf-8")
    # the forger did not (cannot, without editing the record) re-pin the closure hash
    forged["closures"]["post_rule"]["closure_artifact_sha256"] = "0" * 64
    forged_path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(StudyClosureInvalid, match="GRANDFATHER_MISMATCH"):
        load_study_closure(study)


@pytest.mark.parametrize("study_id", GRANDFATHERED)
def test_grandfathered_final_evidence_is_authenticated_by_the_record(tmp_path, study_id):
    source = ROOT / "studies" / study_id
    if not (source / "artifacts/study_closure.json").is_file():
        pytest.skip(f"{study_id} not present in this checkout")
    scratch = tmp_path / study_id
    scratch.mkdir()
    shutil.copytree(source / "artifacts", scratch / "artifacts")
    for extra in ("compiled_plan.json", "research_decision.yaml"):
        if (source / extra).is_file():
            shutil.copyfile(source / extra, scratch / extra)
    assert load_study_closure(scratch)   # same bytes, same name: the exemption holds
    p = scratch / "artifacts/experiment_analysis_v2.json"
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_MISMATCH.*grandfathered"):
        load_study_closure(scratch)


# --------------------------------------------------------------------------- #
# B2 -- site 9: an unclassifiable Stage 17 decision is not FRESH
# --------------------------------------------------------------------------- #
def test_stage17_binding_whose_canonical_artifact_is_absent_is_refused(tmp_path):
    study = tmp_path / "s17"
    art = study / "artifacts"; art.mkdir(parents=True)
    (art / "train_experiment_freeze.json").write_text('{"freeze_sha256":"f"}', encoding="utf-8")
    other = art / "decision_elsewhere.json"
    other.write_text(json.dumps({"study_id": "s17", "stage": 17}), encoding="utf-8")
    body = {"schema_version": 1, "study_id": "s17", "status": "CLOSED", "outcome": "o", "terminal_decision": "d",
            "bound_evidence": {"train_freeze_sha256": "f",
                               "stage17_research_decision": {"path": "artifacts/decision_elsewhere.json", "artifact_file_sha256": _sha(other)}}}
    (art / "study_closure.json").write_text(json.dumps(body), encoding="utf-8")
    # classify_stage17_decision returns None (no canonical artifact): previously accepted, now refused
    with pytest.raises(StudyClosureInvalid, match="EVIDENCE_STALE: stage17 decision is not FRESH"):
        load_study_closure(study)

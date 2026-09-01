"""Focused synthetic contracts for production controller leaves."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_workflow.controller_actions import _validate_partition_record, production_actions
from research_workflow.governed_controller import ControllerActions, GovernedStudyController
from research_workflow.partitioning import PartitionSpec


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _part(year: int = 2024) -> PartitionSpec:
    return PartitionSpec(f"train-{year}", "train", f"{year}-01-01", f"{year}-12-31", f"{year-1}-12-27", f"{year}-12-31", f"{year}-12-31", f"{year}-12-31", "a" * 64, "source", "feature", "contract")


def _run(study: Path, part: PartitionSpec) -> Path:
    run = study / "runs" / f"run-{part.partition_id}"; collection = run / "collection"; collection.mkdir(parents=True, exist_ok=True)
    candidates, observations = collection / "candidates.parquet", collection / "observations.parquet"
    candidates.write_bytes(b"candidates"); observations.write_bytes(b"observations")
    hashes = {"candidates_sha256": _sha(candidates), "observations_sha256": _sha(observations)}
    _write(collection / "collection_manifest.json", {"run_id": run.name, "study_id": study.name, **hashes})
    _write(run / "run_manifest.json", {"run_id": run.name, "study_id": study.name, "status": "COMPLETED", "stage": "full", "dates": {"start": part.primary_start, "end": part.primary_end}, "outputs": hashes, "execution_manifest_sha256": "a" * 64, "composite_seal_hash": "a" * 64})
    _write(run / "status.json", {"run_id": run.name, "study_id": study.name, "status": "SUCCESS", "stage": "full"})
    return run


def _study(tmp_path: Path) -> Path:
    study = tmp_path / "s"; study.mkdir(); _write(study / "audit/frozen_execution_manifest.json", {"frozen_execution_composite_sha256": "a" * 64}); _write(study / "artifacts/preexec_audit_seal.json", {"composite_seal_hash": "a" * 64, "execution_manifest_composite_sha256": "a" * 64}); return study


def _patch_collection(monkeypatch, parts, calls):
    import research_workflow.collection as collection
    import research_workflow.seal as seal
    monkeypatch.setattr(seal, "verify_preexec_audit_seal", lambda _: None)
    monkeypatch.setattr(collection, "build_year_partitions", lambda *_args, **_kwargs: parts)
    def collect(study, part, execute):
        calls.append(part.partition_id); return {"status": "COLLECTED", "run": {"run_dir": str(_run(study, part))}}
    monkeypatch.setattr(collection, "collect_partition", collect)


def test_completed_valid_partition_is_skipped(monkeypatch, tmp_path):
    study, part, calls = _study(tmp_path), _part(), []
    _patch_collection(monkeypatch, [part], calls)
    action = production_actions(execute_authorized=True).collection
    action(study); action(study)
    assert calls == [part.partition_id]


def test_corrupted_partition_hash_reruns_only_corrupt_partition(monkeypatch, tmp_path):
    study, part, calls = _study(tmp_path), _part(), []
    _patch_collection(monkeypatch, [part], calls); action = production_actions(execute_authorized=True).collection
    action(study)
    (study / "runs" / "run-train-2024" / "collection" / "candidates.parquet").write_bytes(b"corrupt")
    action(study)
    assert calls == [part.partition_id, part.partition_id]


def test_interrupted_collection_resumes_remaining_partition(monkeypatch, tmp_path):
    study, first, second, calls = _study(tmp_path), _part(2023), _part(2024), []
    _patch_collection(monkeypatch, [first, second], calls)
    action = production_actions(execute_authorized=True).collection
    # A durable first record represents interruption after its atomic progress write.
    run = _run(study, first)
    record = {"status": "PASS", "id": first.partition_id, "partition": first.to_dict(), "provenance_sha256": first.provenance_sha256, "authorization_sha256": first.authorization_sha256, "execution_composite_sha256": "a" * 64, "run_dir": str(run)}
    record.update(_validate_partition_record(study, first, record, "a" * 64, {"composite_seal_hash": "a" * 64, "execution_manifest_sha256": "a" * 64})); _write(study / "_work/controller/partitions/train-2023.json", record)
    action(study)
    assert calls == [second.partition_id]
    assert json.loads((study / "_work/controller/progress.json").read_text())["completed_partitions"] == [first.partition_id, second.partition_id]


def test_reconciliation_uses_partition_and_run_authorities(monkeypatch, tmp_path):
    study, part = _study(tmp_path), _part(); run = _run(study, part)
    record = {"status": "PASS", "id": part.partition_id, "partition": part.to_dict(), "provenance_sha256": part.provenance_sha256, "authorization_sha256": part.authorization_sha256, "execution_composite_sha256": "a" * 64, "run_dir": str(run)}; record.update(_validate_partition_record(study, part, record, "a" * 64, {"composite_seal_hash": "a" * 64, "execution_manifest_sha256": "a" * 64})); _write(study / "_work/controller/partitions/train-2024.json", record)
    import research_workflow.collection as collection, research_workflow.partitioning as partitioning
    import scripts.reconcile_runs as runs
    used = []; monkeypatch.setattr(collection, "build_year_partitions", lambda *_a, **_k: [part]); monkeypatch.setattr(partitioning, "reconcile_partitions", lambda records: used.append("partitions") or {"passed": True}); monkeypatch.setattr(runs, "classify_run", lambda p: used.append("runs") or {"state": "SUCCESS", "run_id": p.name})
    result = production_actions(execute_authorized=True).reconcile(study)
    assert used == ["runs", "partitions"] and Path(result["output_artifacts"][0]).is_file()


def test_analysis_requires_explicit_config_and_binds_hashes(monkeypatch, tmp_path):
    study = _study(tmp_path); frame = study / "_work" / "frame.csv"; frame.parent.mkdir(parents=True); frame.write_text("target,score\n1,0.9\n0,0.1\n", encoding="utf-8")
    import research_workflow.analysis as analysis
    called = []
    def analyze(path, data, **config):
        called.append(config); _write(Path(path) / "artifacts" / config.get("output_name", "experiment_analysis.json"), {"ok": True}); return {"ok": True}
    monkeypatch.setattr(analysis, "analyze_results", analyze)
    with pytest.raises(RuntimeError, match="ANALYSIS_CONFIG_REQUIRED"): production_actions(execute_authorized=True).analyze(study)
    result = production_actions(execute_authorized=True, analysis_config={"frame_path": str(frame), "score_columns": {"A": "score"}, "target_column": "target"}).analyze(study)
    binding = json.loads((study / "_work/controller/analysis_binding.json").read_text())
    assert called and binding["frame_sha256"] == _sha(frame) and len(result["output_artifacts"]) == 2


def test_production_never_enables_synthetic_trust_and_stale_composite_fails(tmp_path):
    actions, study, part = production_actions(execute_authorized=False), _study(tmp_path), _part()
    assert not getattr(actions, "synthetic_test", False)
    run = _run(study, part); manifest = json.loads((run / "run_manifest.json").read_text()); manifest["composite_seal_hash"] = "b" * 64; _write(run / "run_manifest.json", manifest)
    record = {"status": "PASS", "id": part.partition_id, "partition": part.to_dict(), "provenance_sha256": part.provenance_sha256, "authorization_sha256": part.authorization_sha256, "execution_composite_sha256": "a" * 64, "run_dir": str(run)}
    with pytest.raises(RuntimeError, match="COMPOSITE_STALE"): _validate_partition_record(study, part, record, "a" * 64, {"composite_seal_hash": "a" * 64, "execution_manifest_sha256": "a" * 64})


def test_absent_launch_identity_is_rejected(tmp_path):
    study, part = _study(tmp_path), _part(); run = _run(study, part)
    manifest = json.loads((run / "run_manifest.json").read_text()); manifest.pop("execution_manifest_sha256"); _write(run / "run_manifest.json", manifest)
    record = {"status": "PASS", "id": part.partition_id, "partition": part.to_dict(), "provenance_sha256": part.provenance_sha256, "authorization_sha256": part.authorization_sha256, "execution_composite_sha256": "a" * 64, "run_dir": str(run)}
    with pytest.raises(RuntimeError, match="COMPOSITE_STALE"):
        _validate_partition_record(study, part, record, "a" * 64, {"composite_seal_hash": "a" * 64, "execution_manifest_sha256": "a" * 64})


def test_collection_receipt_hashes_terminal_manifest_and_status(monkeypatch, tmp_path):
    study, part, calls = _study(tmp_path), _part(), []
    _patch_collection(monkeypatch, [part], calls)
    result = production_actions(execute_authorized=True).collection(study)
    controller = GovernedStudyController(study, actions=ControllerActions())
    current = {"execution_composite": "a" * 64}
    controller._write_receipt("collection", result, current)
    assert controller._receipt_current("collection", current, require_partitions=True)
    status = study / "runs/run-train-2024/status.json"; _write(status, {**json.loads(status.read_text()), "mutation": True})
    assert not controller._receipt_current("collection", current, require_partitions=True)


def test_action_verbosity_is_redirected_to_the_stage_log(tmp_path, capsys):
    study = _study(tmp_path); output = study / "artifacts" / "result.json"; _write(output, {"ok": True})
    def noisy(_study):
        print("collector diagnostic")
        return {"status": "PASS", "output_artifacts": [output], "partitions": [{"id": "train-2024", "status": "PASS"}]}
    actions = ControllerActions(collection=noisy); actions.synthetic_test = True
    controller = GovernedStudyController(study, actions=actions)
    controller._worktree = lambda: {"unsafe_dirty_paths": [], "dirty_paths": []}
    controller._fingerprints = lambda: {"execution_composite": "a" * 64}
    controller._fresh_stage = lambda stage, _fp: stage != "collection"
    controller.run(through="collection")
    assert capsys.readouterr().out == ""
    assert "collector diagnostic" in (study / "_work/controller/logs/collection.log").read_text(encoding="utf-8")


def test_late_receipts_reject_a_stale_execution_composite(tmp_path):
    study = _study(tmp_path); output = study / "artifacts" / "result.json"; _write(output, {"ok": True})
    actions = ControllerActions(); actions.synthetic_test = True
    controller = GovernedStudyController(study, actions=actions)
    current = {"execution_composite": "a" * 64}
    for stage in ("collection", "reconcile", "analyze"):
        payload = {"status": "PASS", "output_artifacts": [output]}
        if stage == "collection": payload["partitions"] = [{"id": "train-2024", "status": "PASS"}]
        controller._write_receipt(stage, payload, current)
        assert controller._receipt_current(stage, current, require_partitions=stage == "collection")
        stale = {"execution_composite": "b" * 64}
        assert not controller._receipt_current(stage, stale, require_partitions=stage == "collection")

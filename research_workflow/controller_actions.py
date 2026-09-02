"""Production leaves for the governed controller; domain work remains canonical."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from research_workflow.governed_controller import ControllerActions


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _current_composite(study: Path) -> str:
    composite = _read(study / "audit" / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
    if not composite:
        raise RuntimeError("EXECUTION_COMPOSITE_MISSING")
    return str(composite)


def _launch_identities(study: Path) -> dict[str, str]:
    """Read identities from the already-verified production seal."""
    seal = _read(study / "artifacts" / "preexec_audit_seal.json")
    seal_hash = seal.get("composite_seal_hash")
    if not isinstance(seal_hash, str) or not seal_hash:
        raise RuntimeError("PREEXEC_SEAL_IDENTITY_MISSING")
    execution = seal.get("execution_manifest_composite_sha256") or seal_hash
    if not isinstance(execution, str) or not execution:
        raise RuntimeError("PREEXEC_EXECUTION_IDENTITY_MISSING")
    return {"composite_seal_hash": seal_hash, "execution_manifest_sha256": execution}


def _resolve_run_dir(result: Mapping[str, Any]) -> Path:
    run = result.get("run") if isinstance(result.get("run"), Mapping) else {}
    for value in (run.get("run_dir"), run.get("output_dir"), result.get("run_dir"), result.get("output_dir")):
        if value:
            return Path(str(value)).resolve()
    artifacts = run.get("output_artifacts") if isinstance(run.get("output_artifacts"), Mapping) else {}
    if artifacts.get("candidates_parquet"):
        return Path(str(artifacts["candidates_parquet"])).resolve().parent.parent
    raise RuntimeError("COLLECTION_RUN_DIR_UNRESOLVABLE")


def _validate_partition_record(study: Path, partition: Any, record: Mapping[str, Any], composite: str, launch: Mapping[str, str]) -> dict[str, Any]:
    """Revalidate persisted provenance and bytes; records alone are never trust."""
    if record.get("status") != "PASS" or record.get("id") != partition.partition_id:
        raise RuntimeError("PARTITION_RECORD_STATUS_INVALID")
    if record.get("provenance_sha256") != partition.provenance_sha256 or record.get("execution_composite_sha256") != composite:
        raise RuntimeError("PARTITION_RECORD_STALE")
    if record.get("partition") != partition.to_dict() or record.get("authorization_sha256") != partition.authorization_sha256:
        raise RuntimeError("PARTITION_RECORD_PROVENANCE_INVALID")
    run_dir = Path(str(record.get("run_dir", ""))).resolve()
    manifest, status = _read(run_dir / "run_manifest.json"), _read(run_dir / "status.json")
    if not run_dir.is_dir() or status.get("status") != "SUCCESS" or manifest.get("status") != "COMPLETED":
        raise RuntimeError("PARTITION_RUN_NOT_SUCCESSFUL")
    if manifest.get("study_id") != study.name or status.get("study_id") not in {None, study.name}:
        raise RuntimeError("PARTITION_RUN_IDENTITY_INVALID")
    if manifest.get("run_id") != run_dir.name or status.get("run_id") not in {None, run_dir.name} or collection_manifest_id_mismatch(run_dir, run_dir.name, study.name):
        raise RuntimeError("PARTITION_RUN_IDENTITY_INVALID")
    if manifest.get("stage") != "full" or status.get("stage") not in {None, "full"}:
        raise RuntimeError("PARTITION_RUN_STAGE_INVALID")
    dates = manifest.get("dates") or {}
    if dates.get("start") != partition.primary_start or dates.get("end") not in {partition.primary_end, partition.lookahead_end}:
        raise RuntimeError("PARTITION_RUN_DATES_INVALID")
    if manifest.get("composite_seal_hash") != launch["composite_seal_hash"] or manifest.get("execution_manifest_sha256") != launch["execution_manifest_sha256"]:
        raise RuntimeError("PARTITION_EXECUTION_COMPOSITE_STALE")
    paths = {"run_manifest": run_dir / "run_manifest.json", "status": run_dir / "status.json", "candidates": run_dir / "collection" / "candidates.parquet", "observations": run_dir / "collection" / "observations.parquet", "collection_manifest": run_dir / "collection" / "collection_manifest.json"}
    collection_manifest = _read(paths["collection_manifest"])
    outputs = manifest.get("outputs") or {}
    for name, key in (("candidates", "candidates_sha256"), ("observations", "observations_sha256")):
        actual, declared = _sha(paths[name]), outputs.get(key)
        if not actual or not declared or actual != declared or collection_manifest.get(key) != declared:
            raise RuntimeError(f"PARTITION_{name.upper()}_HASH_INVALID")
    artifacts = [{"path": str(path.resolve()), "sha256": _sha(path)} for path in paths.values()]
    if any(not artifact["sha256"] for artifact in artifacts):
        raise RuntimeError("PARTITION_ARTIFACT_MISSING")
    return {"run_dir": str(run_dir), "run_id": run_dir.name, "artifacts": artifacts}


def collection_manifest_id_mismatch(run_dir: Path, run_id: str, study_id: str) -> bool:
    collection = _read(run_dir / "collection" / "collection_manifest.json")
    return (collection.get("run_id") not in {None, run_id} or collection.get("study_id") not in {None, study_id})


def production_actions(*, execute_authorized: bool, period: str = "train", analysis_config: dict[str, Any] | None = None) -> ControllerActions:
    """Return opt-in production leaves; only tests may set ``synthetic_test``."""
    def collection(study: Path) -> dict[str, Any]:
        if not execute_authorized:
            raise RuntimeError("EXECUTE_AUTHORIZATION_REQUIRED")
        from research_workflow.seal import verify_preexec_audit_seal
        from research_workflow.collection import build_year_partitions, collect_partition
        verify_preexec_audit_seal(study)
        composite, launch, records, outputs = _current_composite(study), _launch_identities(study), [], []
        for partition in build_year_partitions(study, period=period):
            record_path = study / "_work" / "controller" / "partitions" / f"{partition.partition_id}.json"
            record = _read(record_path)
            try:
                evidence = _validate_partition_record(study, partition, record, composite, launch)
            except RuntimeError:
                result = collect_partition(study, partition, execute=True)
                if result.get("status") != "COLLECTED":
                    raise RuntimeError(f"PARTITION_COLLECTION_NOT_COMPLETED: {partition.partition_id}")
                record = {"status": "PASS", "id": partition.partition_id, "partition": partition.to_dict(), "provenance_sha256": partition.provenance_sha256, "authorization_sha256": partition.authorization_sha256, "execution_composite_sha256": composite, "run_dir": str(_resolve_run_dir(result))}
                evidence = _validate_partition_record(study, partition, record, composite, launch)
                record.update(evidence)
                _write(record_path, record)
            records.append(record)
            outputs.extend(Path(item["path"]) for item in evidence["artifacts"])
            outputs.append(record_path)
            _write(study / "_work" / "controller" / "progress.json", {"stage": "collection", "last_partition": partition.partition_id, "completed_partitions": [item["id"] for item in records], "execution_composite_sha256": composite})
        return {"status": "PASS", "output_artifacts": outputs, "partitions": [{"id": item["id"], "status": "PASS"} for item in records]}

    def reconcile(study: Path) -> dict[str, Any]:
        from research_workflow.collection import build_year_partitions
        from research_workflow.partitioning import reconcile_partitions
        from scripts.reconcile_runs import classify_run
        composite, launch, expected, records, classifications = _current_composite(study), _launch_identities(study), build_year_partitions(study, period=period), [], []
        record_dir = study / "_work" / "controller" / "partitions"
        if {path.stem for path in record_dir.glob("*.json")} != {part.partition_id for part in expected}:
            raise RuntimeError("PARTITION_RECORD_SET_MISMATCH")
        for partition in expected:
            record = _read(record_dir / f"{partition.partition_id}.json")
            _validate_partition_record(study, partition, record, composite, launch)
            classification = classify_run(Path(record["run_dir"]))
            if classification.get("state") != "SUCCESS":
                raise RuntimeError(f"RUN_RECONCILIATION_NOT_SUCCESS: {partition.partition_id}")
            records.append(record); classifications.append(classification)
        report = reconcile_partitions(records)
        if not report.get("passed"):
            raise RuntimeError(f"PARTITION_RECONCILIATION_FAILED: {report.get('findings')}")
        report.update({"execution_composite_sha256": composite, "runs": classifications, "artifacts": [{"partition_id": rec["id"], "run_id": rec["run_id"], "artifact_hashes": rec["artifacts"]} for rec in records]})
        path = study / "_work" / "controller" / "reconciliation_report.json"; _write(path, report)
        return {"status": "PASS", "output_artifacts": [path, *[record_dir / f"{part.partition_id}.json" for part in expected]]}

    def analyze(study: Path) -> dict[str, Any]:
        if not analysis_config:
            raise RuntimeError("ANALYSIS_CONFIG_REQUIRED")
        import pandas as pd
        from research_workflow.analysis import analyze_results
        config = dict(analysis_config); frame_value = config.pop("frame_path", None)
        if not frame_value or not isinstance(config.get("score_columns"), Mapping) or not config["score_columns"] or not isinstance(config.get("target_column"), str) or not config["target_column"]:
            raise RuntimeError("ANALYSIS_CONFIG_INVALID")
        frame = Path(str(frame_value)).resolve()
        if not frame.is_file(): raise RuntimeError("ANALYSIS_FRAME_UNAUTHORIZED_OR_MISSING")
        if frame.suffix.lower() == ".parquet": data = pd.read_parquet(frame)
        elif frame.suffix.lower() in {".csv", ".tsv"}: data = pd.read_csv(frame, sep="\t" if frame.suffix.lower() == ".tsv" else ",")
        else: raise RuntimeError("ANALYSIS_FRAME_FORMAT_UNSUPPORTED")
        analyze_results(study, data, **config)
        artifact = study / "artifacts" / str(config.get("output_name", "experiment_analysis.json"))
        if not artifact.is_file(): raise RuntimeError("ANALYSIS_ARTIFACT_MISSING")
        binding = {"frame_path": str(frame), "frame_sha256": _sha(frame), "analysis_config_sha256": hashlib.sha256(json.dumps({"frame_path": str(frame), **config}, sort_keys=True, default=str).encode()).hexdigest(), "execution_composite_sha256": _current_composite(study), "analysis_artifact": str(artifact), "analysis_artifact_sha256": _sha(artifact)}
        binding_path = study / "_work" / "controller" / "analysis_binding.json"; _write(binding_path, binding)
        return {"status": "PASS", "output_artifacts": [artifact, binding_path]}

    return ControllerActions(collection=collection, reconcile=reconcile, analyze=analyze)

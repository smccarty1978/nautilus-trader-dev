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


def _partition_record_dir(study: Path, period: str) -> Path:
    """TRAIN records keep their original location; other periods are namespaced."""
    base = study / "_work" / "controller" / "partitions"
    return base if period == "train" else base / period


def _merged_frames(study: Path) -> tuple[Any, Any, dict[str, Any]]:
    """Load the controller's merged TRAIN candidates/observations (written by the merge stage)."""
    import pandas as pd
    receipt = _read(study / "_work" / "controller" / "receipts" / "merge.json")
    if receipt.get("status") != "PASS":
        raise RuntimeError("MERGE_RECEIPT_REQUIRED")
    mdir = study / "_work" / "controller" / "merged"
    cand, obs = pd.read_parquet(mdir / "candidates.parquet"), pd.read_parquet(mdir / "observations.parquet")
    identity = _read(mdir / "identity.json")
    for name, frame in (("candidates", cand), ("observations", obs)):
        if _sha(mdir / f"{name}.parquet") != identity.get(f"{name}_sha256"):
            raise RuntimeError(f"MERGED_{name.upper()}_HASH_INVALID")
    return cand, obs, identity


def _label_column(study: Path, label_column: str | None) -> str:
    """The label a governed fit trains on. Declared or explicit -- never guessed."""
    if label_column:
        return label_column
    compiled = _read(study / "compiled_study.json")
    target = (compiled.get("contracts") or {}).get("target_contract") or {}
    if target.get("label_column"):
        return str(target["label_column"])
    if target.get("primitive") in {None, "flip_within_horizon"} and (target.get("target_type") in {None, "flip"}):
        return "target_flip_within_horizon"
    raise RuntimeError(f"LABEL_COLUMN_REQUIRED: target primitive {target.get('primitive')!r} declares no label_column; pass --label-column")


def _train_matrix(study: Path, *, label_column: str | None, arms: Mapping[str, list[str]] | None):
    """X/y/meta for the TRAIN fit from the merged frames, in declared feature order."""
    import pandas as pd
    from research.analysis.loader import partition_of_year
    cand, obs, identity = _merged_frames(study)
    compiled = _read(study / "compiled_study.json")
    contracts = compiled.get("contracts") or {}
    features = list((contracts.get("feature_contract") or {}).get("feature_list") or [])
    if not features:
        raise RuntimeError("FEATURE_LIST_MISSING_IN_COMPILED_STUDY")
    key = [k for k in ("observation_ts", "regime_start_ns", "checkpoint_index") if k in cand.columns and k in obs.columns]
    merged = cand.merge(obs, on=key, how="inner", validate="one_to_one")
    label = _label_column(study, label_column)
    if label not in merged.columns:
        raise RuntimeError(f"LABEL_COLUMN_MISSING: {label!r} not in merged observations")
    labelled = merged[merged[label].notna()].copy()
    y = labelled[label].astype(int)
    if set(y.unique()) - {0, 1}:
        raise RuntimeError(f"LABEL_NOT_BINARY: {sorted(set(y.unique()))[:5]}")
    X = labelled[features].copy()
    chronology = (compiled.get("spec") or {}).get("chronology") or {}
    years = pd.to_datetime(labelled["observation_ts"], unit="ns", utc=True).dt.year
    meta = labelled[key].copy(); meta["_year"] = years.values
    meta["_partition"] = [partition_of_year(int(y_), chronology) or "unassigned" for y_ in years]
    if set(meta["_partition"].unique()) != {"train"}:
        raise RuntimeError(f"NON_TRAIN_ROWS_IN_FIT_INPUT: {sorted(set(meta['_partition'].unique()))}")
    arms = dict(arms or {})
    if not arms:
        declared = ((compiled.get("spec") or {}).get("model") or {}).get("arms") or ["BASELINE"]
        arms = {str(a): features for a in declared}
    return X.reset_index(drop=True), y.reset_index(drop=True), meta.reset_index(drop=True), arms, {"label_column": label, "n_rows": int(len(X)), "n_censored_dropped": int(len(merged) - len(labelled)), "merge_identity": identity}


def production_actions(*, execute_authorized: bool, period: str = "train", analysis_config: dict[str, Any] | None = None,
                       label_column: str | None = None, arms: Mapping[str, list[str]] | None = None,
                       closure: Mapping[str, Any] | None = None) -> ControllerActions:
    """Return opt-in production leaves; only tests may set ``synthetic_test``."""

    def smoke(study: Path) -> dict[str, Any]:
        from research_workflow.governed_controller import WorkflowActions
        result = WorkflowActions().smoke(study)
        run = result.get("run") if isinstance(result, dict) else {}
        run_dir = _resolve_run_dir(result if isinstance(result, dict) else {})
        outputs = [p for p in (run_dir / "run_manifest.json", run_dir / "status.json", study / "artifacts" / "smoke_reconciled.json") if p.is_file()]
        return {"status": "PASS", "output_artifacts": outputs}

    def _collect_period(study: Path, which: str) -> dict[str, Any]:
        if not execute_authorized:
            raise RuntimeError("EXECUTE_AUTHORIZATION_REQUIRED")
        from research_workflow.seal import verify_preexec_audit_seal
        from research_workflow.collection import build_year_partitions, collect_partition
        verify_preexec_audit_seal(study)
        composite, launch, records, outputs = _current_composite(study), _launch_identities(study), [], []
        for partition in build_year_partitions(study, period=which):
            record_path = _partition_record_dir(study, which) / f"{partition.partition_id}.json"
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
            _write(study / "_work" / "controller" / "progress.json", {"stage": which, "last_partition": partition.partition_id, "completed_partitions": [item["id"] for item in records], "execution_composite_sha256": composite})
        return {"status": "PASS", "output_artifacts": outputs, "partitions": [{"id": item["id"], "status": "PASS"} for item in records]}

    def collection(study: Path) -> dict[str, Any]:
        return _collect_period(study, period)

    def reconcile(study: Path) -> dict[str, Any]:
        from research_workflow.collection import build_year_partitions
        from research_workflow.partitioning import reconcile_partitions
        from scripts.reconcile_runs import classify_run
        composite, launch, expected, records, classifications = _current_composite(study), _launch_identities(study), build_year_partitions(study, period=period), [], []
        record_dir = _partition_record_dir(study, period)
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

    def merge(study: Path) -> dict[str, Any]:
        """Deterministic merge of reconciled TRAIN partitions into one identity-bound frame pair."""
        import pandas as pd
        from research.analysis.identity import canonical_sha256
        from research.analysis.modeling import frame_content_identity
        from research_workflow.collection import build_year_partitions
        from research_workflow.partitioning import merge_partition_outputs, retain_primary_rows
        composite, launch = _current_composite(study), _launch_identities(study)
        expected = build_year_partitions(study, period=period)
        record_dir = _partition_record_dir(study, period)
        cands, obss = [], []
        for partition in expected:
            record = _read(record_dir / f"{partition.partition_id}.json")
            _validate_partition_record(study, partition, record, composite, launch)
            run_dir = Path(record["run_dir"])
            cands.append(retain_primary_rows(pd.read_parquet(run_dir / "collection" / "candidates.parquet"), partition))
            obss.append(retain_primary_rows(pd.read_parquet(run_dir / "collection" / "observations.parquet"), partition))
        merged_c = merge_partition_outputs(cands, expected); merged_o = merge_partition_outputs(obss, expected)
        mdir = study / "_work" / "controller" / "merged"; mdir.mkdir(parents=True, exist_ok=True)
        merged_c.to_parquet(mdir / "candidates.parquet", index=False); merged_o.to_parquet(mdir / "observations.parquet", index=False)
        identity = {"execution_composite_sha256": composite, "partitions": [p.partition_id for p in expected],
                    "candidates_sha256": _sha(mdir / "candidates.parquet"), "observations_sha256": _sha(mdir / "observations.parquet"),
                    "candidates_content_identity": frame_content_identity(merged_c), "observations_content_identity": frame_content_identity(merged_o),
                    "rows": {"candidates": int(len(merged_c)), "observations": int(len(merged_o))}}
        identity["dataset_identity_sha256"] = canonical_sha256({k: identity[k] for k in ("candidates_content_identity", "observations_content_identity", "partitions")})
        _write(mdir / "identity.json", identity)
        return {"status": "PASS", "output_artifacts": [mdir / "candidates.parquet", mdir / "observations.parquet", mdir / "identity.json"]}

    def fit(study: Path) -> dict[str, Any]:
        """Governed TRAIN fit (with the declared bounded selection when the study declares one)."""
        from research.analysis.spec import AnalysisSpec, ModelArm
        from research.schemas.study_spec import StudySpec
        from research_workflow.modeling import fit_models
        X, y, meta, arm_map, info = _train_matrix(study, label_column=label_column, arms=arms)
        compiled = _read(study / "compiled_study.json"); spec_payload = compiled.get("spec") or {}
        study_spec = StudySpec.model_validate(spec_payload)
        model = spec_payload.get("model") or {}
        family = str(model.get("family") or "lightgbm").lower()
        family = {"histgradientboostingclassifier": "gradient_boosting", "lightgbm": "lightgbm", "logisticregression": "logistic_regression"}.get(family, family)
        params = dict(model.get("params") or {})
        selection_manifest = None
        sel = getattr(getattr(study_spec, "model", None), "selection", None)
        if sel is not None and sel.search_method != "none":
            from research_workflow.model_selection import run_model_selection
            meta_sel = meta.copy()
            meta_sel["_selection_role"] = ["tuning" if int(y_) in set(sel.tuning_years or []) else ("final_validation" if int(y_) in set(sel.final_train_validation_years or []) else "unassigned") for y_ in meta["_year"]]
            selection_manifest = run_model_selection(study, {a: X[cols] for a, cols in arm_map.items()}, y, meta_sel, sel)
            if selection_manifest.get("final_validation_policy") == "gated" and selection_manifest.get("final_validation_status") != "PASS":
                raise RuntimeError("MODEL_SELECTION_FINAL_VALIDATION_FAILED")
        analysis_spec = AnalysisSpec(analysis_id=f"{study.name}_controller_fit", run_id="controller_fit", study_id=study.name,
                                     model_arms=tuple(ModelArm(name=a, features=list(cols)) for a, cols in arm_map.items()),
                                     seed=int((sel.random_seed if sel is not None and sel.random_seed is not None else params.get("random_state", 0)) or 0))
        outputs = []
        result_summary = {}
        for arm_name, cols in arm_map.items():
            hp = dict(params)
            if selection_manifest is not None:
                hp = dict((selection_manifest.get("winner") or {}).get(arm_name, {}).get("hyperparameters") or hp)
            fit_result = fit_models(study, X[cols], y, meta=meta, spec=AnalysisSpec(analysis_id=analysis_spec.analysis_id, run_id=analysis_spec.run_id, study_id=study.name,
                                     model_arms=(ModelArm(name=arm_name, features=list(cols)),), seed=analysis_spec.seed),
                                    study_spec=study_spec, dataset_identity_sha256=info["merge_identity"].get("dataset_identity_sha256"), estimator=family, hyperparameters=hp)
            out = study / "artifacts" / f"experiment_models_{arm_name.lower()}.json"
            (study / "artifacts" / "experiment_models.json").replace(out)
            outputs.append(out)
            scores = fit_result["models"][arm_name].predict_proba(X[cols])
            result_summary[arm_name] = {"n_rows": int(len(X)), "hyperparameters": hp, "score_content_sha256": hashlib.sha256(scores.tobytes()).hexdigest(),
                                        "model_artifacts": [{k: r.get(k) for k in ("model_id", "model_role", "artifact_sha256", "model_store_v2")} for r in fit_result["model_artifacts"]["records"]]}
        summary = {"family": family, "label_column": info["label_column"], "n_rows": info["n_rows"], "n_censored_dropped": info["n_censored_dropped"],
                   "dataset_identity_sha256": info["merge_identity"].get("dataset_identity_sha256"), "selection_manifest_sha256": (selection_manifest or {}).get("manifest_sha256"), "arms": result_summary}
        path = study / "_work" / "controller" / "fit_summary.json"; _write(path, summary)
        if selection_manifest is not None:
            outputs.append(study / "artifacts" / "model_selection_manifest.json")
        return {"status": "PASS", "output_artifacts": [path, *outputs]}

    def freeze(study: Path) -> dict[str, Any]:
        """TRAIN freeze from the controller's own fit: feature sets, models, TRAIN-only thresholds/deciles."""
        import pandas as pd
        from research.analysis.identity import canonical_sha256
        from research.schemas.study_spec import StudySpec
        from research_workflow.modeling import freeze_train_artifacts
        fit_summary = _read(study / "_work" / "controller" / "fit_summary.json")
        if not fit_summary:
            raise RuntimeError("FIT_SUMMARY_REQUIRED")
        X, y, meta, arm_map, info = _train_matrix(study, label_column=label_column, arms=arms)
        if info["merge_identity"].get("dataset_identity_sha256") != fit_summary.get("dataset_identity_sha256"):
            raise RuntimeError("FIT_INPUT_IDENTITY_DRIFT")
        compiled = _read(study / "compiled_study.json"); study_spec = StudySpec.model_validate(compiled.get("spec") or {})
        from research_workflow.model_artifacts import resolve_model, load_model_bundle
        registry_root = study.parent / "model_registry"
        score_arrays, deciles, records, arms_manifest = {}, {}, [], {"arms": {}}
        for arm_name, cols in arm_map.items():
            manifest = _read(study / "artifacts" / f"experiment_models_{arm_name.lower()}.json")
            rec = (manifest.get("arms") or {}).get(arm_name)
            if not rec:
                raise RuntimeError(f"FIT_MANIFEST_MISSING: {arm_name}")
            arms_manifest["arms"][arm_name] = rec
            art = next((a for a in fit_summary["arms"][arm_name]["model_artifacts"]), None)
            if not art:
                raise RuntimeError(f"MODEL_ARTIFACT_MISSING: {arm_name}")
            record = resolve_model(art["model_id"], registry_root=registry_root)
            bundle = load_model_bundle(record)
            scores = bundle[record["model_role"]]["estimator"].predict_proba(X[cols])[:, 1]
            score_arrays[arm_name] = [float(v) for v in scores]
            s = pd.Series(score_arrays[arm_name])
            deciles[arm_name] = {"boundaries": [float(s.quantile(q)) for q in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)], "derivation": "TRAIN_ONLY"}
            records.append({k: record.get(k) for k in ("model_id", "model_role", "artifact_path", "artifact_sha256", "golden_fixture_path", "golden_fixture_sha256", "native_booster_path", "native_booster_sha256")})
        feature_sets = {a: list(cols) for a, cols in arm_map.items()}
        pre_hash = canonical_sha256({"calibration": "none", "feature_sets": feature_sets})
        sel_path = study / "artifacts" / "model_selection_manifest.json"
        path = freeze_train_artifacts(study, feature_sets=feature_sets, models_manifest=arms_manifest, preprocessing_hash=pre_hash, score_arrays=score_arrays, meta=meta,
                                      deciles=deciles, study_spec=study_spec, model_selection_manifest_path=(str(sel_path) if sel_path.is_file() else None),
                                      dataset_identity_sha256=info["merge_identity"].get("dataset_identity_sha256"), model_artifact_records=records,
                                      extra_payload={"controller_fit_summary_sha256": _sha(study / "_work" / "controller" / "fit_summary.json"), "label_column": info["label_column"]})
        return {"status": "PASS", "output_artifacts": [path]}

    def oos(study: Path) -> dict[str, Any]:
        """OOS collection; opens only through experiment.assert_oos_open."""
        from research_workflow.experiment import assert_oos_open
        assert_oos_open(study)
        return _collect_period(study, "oos")

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

    def close(study: Path) -> dict[str, Any]:
        """Record an operator-supplied terminal decision; the controller never decides the science."""
        if not closure or not closure.get("outcome") or not closure.get("terminal_decision"):
            raise RuntimeError("CLOSURE_DECISION_REQUIRED: --closure-outcome and --closure-decision")
        from research_workflow.study_closure import load_study_closure
        target = study / "artifacts" / "study_closure.json"
        if target.is_file():
            raise RuntimeError("STUDY_ALREADY_CLOSED")
        payload = {"schema_version": 1, "study_id": study.name, "status": "CLOSED", "outcome": str(closure["outcome"]),
                   "terminal_decision": str(closure["terminal_decision"]), **{k: v for k, v in closure.items() if k not in {"outcome", "terminal_decision"}}}
        _write(target, payload)
        try:
            if load_study_closure(study) is None:
                raise RuntimeError("STUDY_CLOSURE_INVALID")
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {"status": "PASS", "output_artifacts": [target]}

    return ControllerActions(smoke=smoke, collection=collection, reconcile=reconcile, merge=merge, fit=fit, freeze=freeze, oos=oos, analyze=analyze, close=close)


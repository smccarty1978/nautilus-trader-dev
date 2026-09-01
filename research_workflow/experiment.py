"""Governed train/OOS experiment orchestration.

This module is deliberately study-agnostic: study contracts provide chronology,
feature instances, and model-arm declarations; the workflow owns authorization,
collection gates, train-only freezing, and OOS opening.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import pandas as pd

from research.analysis.identity import canonical_sha256


class ExperimentError(RuntimeError):
    pass


class ExperimentAuthorizationError(ExperimentError):
    pass


class TrainFreezeRequired(ExperimentError):
    pass

def _assert_study_open(path: Path) -> None:
    from research_workflow.study_closure import StudyClosureInvalid, load_study_closure
    try:
        if load_study_closure(path) is not None:
            raise ExperimentAuthorizationError("STUDY_CLOSED: closure is terminal and non-destructive")
    except StudyClosureInvalid as exc:
        raise ExperimentAuthorizationError(f"STUDY_CLOSURE_INVALID: {exc}") from exc


@dataclass(frozen=True)
class ExperimentAuthorization:
    study_id: str
    study_path: str
    train_years: tuple[int, ...]
    oos_years: tuple[int, ...]
    prohibited_years: tuple[int, ...]
    authorization_sha256: str
    artifact_path: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "study_id": self.study_id,
            "study_path": self.study_path,
            "train_years": list(self.train_years),
            "oos_years": list(self.oos_years),
            "prohibited_years": list(self.prohibited_years),
            "authorization_sha256": self.authorization_sha256,
            "artifact_path": self.artifact_path,
        }


def _load_study(study_path: Path) -> Dict[str, Any]:
    import yaml

    path = Path(study_path).resolve()
    source = path / "study.yaml"
    if not source.is_file():
        raise ExperimentAuthorizationError(f"study.yaml not found: {source}")
    payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ExperimentAuthorizationError("study.yaml must contain a mapping")
    return payload


def authorize_experiment(study_path: str | Path, *, write: bool = True) -> ExperimentAuthorization:
    """Materialize explicit TRAIN/OOS/prohibited year authority from the study contract."""
    path = Path(study_path).resolve()
    _assert_study_open(path)
    payload = _load_study(path)
    study_id = str((payload.get("study") or {}).get("id") or path.name)
    chronology = payload.get("chronology") or {}
    train = tuple(sorted({int(y) for y in chronology.get("train") or []}))
    oos = tuple(sorted({int(y) for y in chronology.get("dev") or []}))
    prohibited = tuple(sorted({int(y) for y in chronology.get("prohibited") or []}))
    if not train or not oos:
        raise ExperimentAuthorizationError("chronology must declare non-empty train and OOS years")
    if set(train) & set(oos) or set(train) & set(prohibited) or set(oos) & set(prohibited):
        raise ExperimentAuthorizationError("TRAIN, OOS, and prohibited years must be disjoint")
    body = {
        "schema_version": 1,
        "study_id": study_id,
        "study_path": str(path),
        "train_years": list(train),
        "oos_years": list(oos),
        "prohibited_years": list(prohibited),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    digest = canonical_sha256({k: v for k, v in body.items() if k != "generated_at_utc"})
    body["authorization_sha256"] = digest
    artifact = path / "artifacts" / "experiment_authorization.json"
    if write:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return ExperimentAuthorization(
        study_id=study_id,
        study_path=str(path),
        train_years=train,
        oos_years=oos,
        prohibited_years=prohibited,
        authorization_sha256=digest,
        artifact_path=str(artifact),
    )


def load_authorization(study_path: str | Path) -> ExperimentAuthorization:
    path = Path(study_path).resolve()
    artifact = path / "artifacts" / "experiment_authorization.json"
    if not artifact.is_file():
        return authorize_experiment(path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    expected = canonical_sha256({k: payload[k] for k in (
        "schema_version", "study_id", "study_path", "train_years", "oos_years", "prohibited_years"
    )})
    if payload.get("authorization_sha256") != expected:
        raise ExperimentAuthorizationError("experiment authorization artifact hash mismatch")
    current = authorize_experiment(path, write=False)
    if current.authorization_sha256 != expected:
        raise ExperimentAuthorizationError("experiment authorization is stale relative to study.yaml")
    return current


def assert_period_authorized(auth: ExperimentAuthorization, period: str) -> tuple[int, ...]:
    if period == "train":
        return auth.train_years
    if period in {"oos", "dev"}:
        return auth.oos_years
    raise ExperimentAuthorizationError(f"unknown experiment period: {period!r}")


def authorize_diagnostic_period(study_path: str | Path, *, parent_study_path: str | Path) -> Dict[str, Any]:
    """Authorize a child diagnostic year already opened by its frozen parent.

    This intentionally does not classify the diagnostic year as child TRAIN or OOS,
    and is planning-only until the normal seal boundary permits NT execution.
    """
    path = Path(study_path).resolve()
    parent = Path(parent_study_path).resolve()
    _assert_study_open(path)
    child = _load_study(path)
    years = tuple(sorted({int(y) for y in ((child.get("chronology") or {}).get("diagnostic") or [])}))
    prohibited = {int(y) for y in ((child.get("chronology") or {}).get("prohibited") or [])}
    if not years:
        raise ExperimentAuthorizationError("DIAGNOSTIC_YEARS_REQUIRED")
    if set(years) & prohibited:
        raise ExperimentAuthorizationError("DIAGNOSTIC_YEAR_PROHIBITED")
    parent_auth = load_authorization(parent)
    if not set(years).issubset(set(parent_auth.oos_years)):
        raise ExperimentAuthorizationError("DIAGNOSTIC_PARENT_OPEN_AUTHORITY_MISSING")
    body = {"schema_version": 1, "period": "diagnostic", "years": list(years),
            "parent_study": parent_auth.study_id,
            "parent_authorization_sha256": parent_auth.authorization_sha256}
    body["authorization_sha256"] = canonical_sha256(body)
    return body


def authorize_first_p90_diagnostic_period(study_path: str | Path, *, parent_study_path: str | Path, start_date: str, end_date: str) -> Dict[str, Any]:
    """Diagnostic authority that refuses Apr-Dec until the March gate passes."""
    if start_date > end_date or pd.Timestamp(start_date).year != 2024 or pd.Timestamp(end_date).year != 2024:
        raise ExperimentAuthorizationError("FIRST_P90_DIAGNOSTIC_2024_ONLY")
    auth = authorize_diagnostic_period(study_path, parent_study_path=parent_study_path)
    if end_date > "2024-03-31":
        from research_workflow.first_p90_gate import require_march_gate
        compiled = json.loads((Path(study_path) / "compiled_study.json").read_text(encoding="utf-8"))
        diag = (compiled.get("contracts") or {}).get("diagnostic_followup") or {}
        gate = require_march_gate(study_path,
            expected_first=diag.get("march_first_reference_sha256"),
            expected_outcome=diag.get("march_outcome_reference_sha256"))
        auth["march_gate_sha256"] = canonical_sha256(gate)
    auth["dates"] = [d.strftime("%Y-%m-%d") for d in pd.date_range(start_date, end_date, freq="D")]
    auth["period"] = "diagnostic"
    auth["runtime_authorization_sha256"] = canonical_sha256(auth)
    return auth


def runtime_authorization(study_path: str | Path, period: str) -> Dict[str, Any]:
    """Create an authenticated exact calendar-date plan for the NT runtime."""
    path = Path(study_path).resolve()
    auth = load_authorization(path)
    years = assert_period_authorized(auth, period)
    if period in {"oos", "dev"}:
        freeze = assert_oos_open(path)
    else:
        freeze = None
    dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(f"{years[0]}-01-01", f"{years[-1]}-12-31", freq="D")]
    body: Dict[str, Any] = {
        "schema_version": 1,
        "study_id": auth.study_id,
        "period": period,
        "authorization_sha256": auth.authorization_sha256,
        "dates": dates,
    }
    if freeze is not None:
        body["train_freeze_sha256"] = freeze["freeze_sha256"]
    body["runtime_authorization_sha256"] = canonical_sha256(body)
    return body


def verify_runtime_authorization(study_path: str | Path, payload: Mapping[str, Any], start_date: str, end_date: str) -> Dict[str, Any]:
    """Verify the exact bounded plan before handing it to lower-level NT code."""
    path = Path(study_path).resolve()
    auth = load_authorization(path)
    period = str(payload.get("period"))
    if payload.get("study_id") != auth.study_id or payload.get("authorization_sha256") != auth.authorization_sha256:
        raise ExperimentAuthorizationError("runtime authorization is not bound to this study authority")
    expected_hash = canonical_sha256({k: payload[k] for k in payload if k != "runtime_authorization_sha256"})
    if payload.get("runtime_authorization_sha256") != expected_hash:
        raise ExperimentAuthorizationError("runtime authorization hash mismatch")
    years = assert_period_authorized(auth, period)
    dates = payload.get("dates")
    if not isinstance(dates, list) or not dates:
        raise ExperimentAuthorizationError("runtime authorization must contain explicit dates")
    requested = pd.date_range(start_date, end_date, freq="D")
    date_set = set(dates)
    if any(d.strftime("%Y-%m-%d") not in date_set for d in requested):
        raise ExperimentAuthorizationError("runtime date range is outside the authenticated authorization")
    if any(pd.Timestamp(d).year in set(auth.prohibited_years) for d in dates):
        raise ExperimentAuthorizationError("runtime authorization includes prohibited years")
    if period in {"oos", "dev"}:
        freeze = assert_oos_open(path)
        if payload.get("train_freeze_sha256") != freeze.get("freeze_sha256"):
            raise ExperimentAuthorizationError("OOS runtime authorization is not bound to the current TRAIN freeze")
    return {"period": period, "dates": dates, "years": list(years)}


def write_train_freeze(study_path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Persist immutable TRAIN-derived facts; OOS is not opened by this function."""
    path = Path(study_path).resolve()
    auth = load_authorization(path)
    if payload.get("partition") != "train":
        raise TrainFreezeRequired("train freeze must be explicitly marked partition=train")
    required = ("feature_sets", "preprocessing_hash", "model_hashes", "thresholds", "deciles")
    missing = [key for key in required if key not in payload]
    if missing:
        raise TrainFreezeRequired(f"train freeze missing required fields: {missing}")
    record = dict(payload)
    record.update({
        "schema_version": 1,
        "study_id": auth.study_id,
        "authorization_sha256": auth.authorization_sha256,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    record["freeze_sha256"] = canonical_sha256({k: v for k, v in record.items() if k != "generated_at_utc"})
    out = path / "artifacts" / "train_experiment_freeze.json"
    out.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    return out


def assert_oos_open(study_path: str | Path) -> Dict[str, Any]:
    """Fail closed unless a valid TRAIN freeze exists and is bound to current authorization."""
    path = Path(study_path).resolve()
    _assert_study_open(path)
    auth = load_authorization(path)
    freeze = path / "artifacts" / "train_experiment_freeze.json"
    if not freeze.is_file():
        raise TrainFreezeRequired("OOS is locked until TRAIN-derived artifacts are frozen")
    payload = json.loads(freeze.read_text(encoding="utf-8"))
    if payload.get("partition") != "train" or payload.get("authorization_sha256") != auth.authorization_sha256:
        raise TrainFreezeRequired("TRAIN freeze is stale or not bound to current authorization")
    lineage = payload.get("stage_scoped_lineage")
    if lineage is not None:  # additive: historical freezes remain valid as legacy.
        from research_workflow.modeling_closure import resolve_modeling_closure
        from scripts.resolve_execution_manifest import resolve_execution_manifest
        from research_workflow.target_runtime import resolve_target_runtime_closure
        frozen_collection = lineage.get("COLLECTION_PRODUCER_CLOSURE")
        if frozen_collection is not None and resolve_execution_manifest(path)[0] != frozen_collection:
            raise TrainFreezeRequired("TRAIN_COLLECTION_CLOSURE_STALE: collection-producing code changed")
        if lineage.get("TARGET_RUNTIME_CLOSURE") != resolve_target_runtime_closure(path)["target_runtime_closure_sha256"]:
            raise TrainFreezeRequired("TRAIN_TARGET_RUNTIME_CLOSURE_STALE: target runtime changed")
        compiled = path / "compiled_study.json"
        drivers = list((((json.loads(compiled.read_text()).get("spec") or {}).get("execution") or {}).get("modeling_driver_relpaths") or []) if compiled.is_file() else [])
        current = resolve_modeling_closure(path, driver_relpaths=drivers)["modeling_execution_composite_sha256"]
        if lineage.get("MODELING_EXECUTION_CLOSURE") != current:
            raise TrainFreezeRequired("TRAIN_MODELING_CLOSURE_STALE: modeling code changed after TRAIN freeze")
    return payload


def run_experiment(study_path: str | Path, *, execute: bool = False, output_dir: str | Path | None = None) -> Dict[str, Any]:
    """Plan or execute the generic TRAIN -> freeze -> OOS workflow.

    The default is planning-only so merely importing/validating a study cannot
    open data.  Callers must explicitly provide a TRAIN freeze before OOS.
    """
    from research_workflow.collection import collect_period

    auth = authorize_experiment(study_path)
    train = collect_period(study_path, "train", execute=execute, output_dir=output_dir)
    return {
        "status": "PLANNED" if not execute else "TRAIN_COLLECTED",
        "authorization": auth.to_dict(),
        "train": train,
        "oos": "LOCKED_UNTIL_TRAIN_FREEZE",
    }

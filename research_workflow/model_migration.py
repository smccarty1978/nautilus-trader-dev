"""Migrate legacy (schema v1) model_registry records into the v2 model store.

Identity is preserved: the v2 manifest carries the SAME ``model_id`` the v1 record
computed; the native LightGBM booster the v1 writer preserved becomes the canonical
representation (bytes copied, sha256 verified against the v1 record), the v1 joblib
bundle becomes a ``joblib`` export verified against the golden frame, and the v1
two-row golden fixture is retained as ``legacy_registry_record.golden_fixture``.

Nothing is retrained. Nothing in the source study or the legacy registry is modified or
deleted; the legacy bytes stay where they are until the operator removes them.

Tier assignment: a record whose (cell, config) is the cell's selected configuration in the
study's Phase-D report (or which is named in ``selected_ids``) is ``registry/selected``;
final-validation refits are ``registry/final_validation``; everything else is
``ledger/rejected``.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pandas as pd

from research_workflow import model_store as ms


def _read(p: Path) -> Dict[str, Any]:
    return json.loads(Path(p).read_text(encoding="utf-8"))


_ROLE = re.compile(r"^(?P<direction>LONG|SHORT)_(?P<arm>SL\d+_\d+)_C(?P<config>\d+)_(?P<fold>fold_\d+|final)$")


def parse_model_role(role: str) -> Dict[str, Optional[str]]:
    m = _ROLE.match(str(role))
    if not m:
        return {"direction": None, "arm": None, "config": None, "fold": None}
    return {"direction": m.group("direction"), "arm": m.group("arm"), "config": m.group("config"), "fold": m.group("fold")}


def selected_configs_from_phase_d_report(report_path: Path) -> Dict[str, int]:
    """cell_id -> selected configuration_index from artifacts/phase_d/phase_d_modeling_report.json."""
    rep = _read(report_path)
    out = {}
    for cell, body in (rep.get("cells") or {}).items():
        sel = (body or {}).get("selected") or {}
        if isinstance(sel.get("configuration_index"), int):
            out[str(cell)] = int(sel["configuration_index"])
    return out


def _tier_for(record: Mapping[str, Any], selected: Mapping[str, int]) -> tuple[str, str]:
    parsed = parse_model_role(record.get("model_role", ""))
    if parsed["fold"] == "final":
        return "registry", "final_validation"
    cell = f"{parsed['direction']}_{parsed['arm']}" if parsed["direction"] and parsed["arm"] else None
    if cell and parsed["config"] is not None and selected.get(cell) == int(parsed["config"]):
        return "registry", "selected"
    return "ledger", "rejected"


def migrate_legacy_records(*, study_id: str, registry_root: Path, bytes_root: Path, train_frame: Optional[pd.DataFrame],
                           model_root: Optional[Path] = None, selected: Optional[Mapping[str, int]] = None,
                           selected_ids: Iterable[str] = (), exports: Iterable[str] = ("joblib",), limit: Optional[int] = None) -> Dict[str, Any]:
    """Migrate every v1 record of ``study_id`` under ``registry_root`` into the v2 store."""
    registry_root, bytes_root = Path(registry_root), Path(bytes_root)
    selected = dict(selected or {}); selected_ids = set(selected_ids)
    records = []
    for p in sorted(registry_root.glob("*.json")):
        rec = _read(p)
        if rec.get("study_id") == study_id:
            records.append(rec)
    if limit:
        records = records[:limit]
    report: Dict[str, Any] = {"study_id": study_id, "records": len(records), "migrated": 0, "already_present": 0, "failed": [], "tiers": {}, "exports": {}}
    for rec in records:
        mid = rec["model_id"]
        try:
            native_rel = rec.get("native_booster_path")
            joblib_rel = rec.get("artifact_path")
            fam = rec.get("model_family") or "lightgbm"
            if native_rel:
                src = bytes_root / native_rel
                if not src.is_file() or ms._sha(src) != rec.get("native_booster_sha256"):
                    raise ms.ModelStoreError("LEGACY_NATIVE_BYTES_MISSING_OR_CORRUPT")
            else:
                src = bytes_root / joblib_rel
                if not src.is_file() or ms._sha(src) != rec.get("artifact_sha256"):
                    raise ms.ModelStoreError("LEGACY_ARTIFACT_BYTES_MISSING_OR_CORRUPT")
                fam = "sklearn" if fam not in ms.FAMILY_AUTHORITY else fam
            tier, status = _tier_for(rec, selected)
            if mid in selected_ids:
                tier, status = "registry", "selected"
            parsed = parse_model_role(rec.get("model_role", ""))
            lineage = ms.ModelLineage(
                study_id=study_id, cell_id=(f"{parsed['direction']}_{parsed['arm']}" if parsed["direction"] else None),
                direction=parsed["direction"], target_arm=parsed["arm"], fold_id=parsed["fold"], config_id=(f"C{parsed['config']}" if parsed["config"] else None),
                seed=None, ordered_inputs=list(rec.get("ordered_model_inputs") or []),
                feature_contract_sha256=rec.get("feature_contract_identity"),
                preprocessing_contract_sha256=(rec.get("preprocessing_identity") or {}).get("identity") if isinstance(rec.get("preprocessing_identity"), dict) else rec.get("preprocessing_identity"),
                target_contract_sha256=rec.get("target_identity"), target_frame_identity=None,
                training_population_identity=rec.get("train_frame_population_identity"),
                train_years=list(rec.get("training_years") or []), validation_years=[], hyperparameters=dict(rec.get("hyperparameters") or {}),
                family=fam, fit_identity_sha256=None, closure_identities=dict(rec.get("closure_identities") or {}), model_role=rec.get("model_role"))
            existed = (ms.model_dir(mid, model_root) / "manifest.json").is_file()
            legacy = {k: rec.get(k) for k in ("artifact_path", "artifact_sha256", "golden_fixture_path", "golden_fixture_sha256", "native_booster_path", "native_booster_sha256", "scientific_status", "artifact_status", "reuse_status", "runtime_identity_sha256", "schema_version")}
            # The v1 model_id was canonical_sha256({study_id, arm, fit_identity, closures}); the
            # migrated manifest does not retain the raw fit_identity input, so this store cannot
            # independently recompute it. Name the rule so authenticate_model fails closed
            # (MODEL_IDENTITY_UNVERIFIABLE) rather than silently trusting the copied id.
            manifest = ms.store_model(model_id=mid, estimator=None, lineage=lineage, tier=tier, selection_status=status, metrics={},
                                      golden_train_frame=train_frame, model_root=model_root, scientific_status=rec.get("scientific_status", "UNASSESSED"),
                                      legacy_registry_record=legacy, canonical_source_file=src, identity_rule="legacy_v1_immutable_unrecomputable")
            if existed:
                report["already_present"] += 1
            else:
                report["migrated"] += 1
            report["tiers"][f"{manifest['tier']}/{manifest['selection_status']}"] = report["tiers"].get(f"{manifest['tier']}/{manifest['selection_status']}", 0) + 1
            for fmt in exports:
                if manifest["tier"] == "registry":
                    r = ms.add_export(mid, fmt, model_root=model_root)
                    report["exports"][f"{fmt}/{r['status']}"] = report["exports"].get(f"{fmt}/{r['status']}", 0) + 1
        except Exception as exc:
            report["failed"].append({"model_id": mid, "error": f"{type(exc).__name__}: {exc}"})
    return report


def migrate_train_freeze_bundle(*, study_id: str, freeze_path: Path, bundle_path: Path, repo_root: Path,
                                train_frame: Optional[pd.DataFrame] = None, model_root: Optional[Path] = None,
                                golden_rows: int = ms.GOLDEN_MIN_ROWS, tier: str = "registry",
                                selection_status: str = "selected") -> Dict[str, Any]:
    """Import a legacy Model-C-shaped bundle: ONE joblib file mapping arm -> ``{estimator,
    fit_identity_sha256, provenance}``, whose provenance is a study TRAIN freeze
    (``freeze_path``), not an individual v1 ``studies/model_registry/<model_id>.json``
    record (``migrate_legacy_records`` only handles that shape).

    Nothing is retrained; nothing under ``studies/`` is written; every fact this function
    trusts is either read from the bundle's own bytes or the committed freeze -- never
    invented. Each arm is registered under ``model_store.LEGACY_V1_TRAIN_FREEZE_RULE``
    (see ``model_store._verify_legacy_v1_train_freeze``); a bundle arm whose
    ``fit_identity_sha256`` disagrees with the freeze's ``model_hashes[arm]``, or whose
    feature family has no ``feature_sets`` entry, fails that arm (not the whole import).
    """
    import joblib

    freeze_path = Path(freeze_path).resolve()
    bundle_path = Path(bundle_path).resolve()
    repo_root = Path(repo_root).resolve()
    freeze_rel = freeze_path.relative_to(repo_root).as_posix()
    # Authoritative bytes are the git HEAD blob, not the working-tree file: on Windows a
    # working copy checked out with CRLF line endings hashes differently from the LF blob
    # git actually committed, which would silently record a sha the verifier (which also
    # reads the HEAD blob) can never reproduce. `authoritative_freeze_bytes` fails closed
    # (ModelStoreError) if the freeze is not committed identical.
    from research_workflow.policy import head_blob_git_sha

    freeze_blob = ms.authoritative_freeze_bytes(repo_root, freeze_path)
    freeze_sha = hashlib.sha256(freeze_blob).hexdigest()
    freeze_head_sha = head_blob_git_sha(repo_root, freeze_rel)
    freeze = json.loads(freeze_blob.decode("utf-8"))
    if freeze.get("study_id") != study_id:
        raise ms.ModelStoreError(f"TRAIN_FREEZE_STUDY_MISMATCH: {freeze.get('study_id')!r} != {study_id!r}")
    bundle = joblib.load(bundle_path)
    if not isinstance(bundle, Mapping):
        raise ms.ModelStoreError("BUNDLE_NOT_AN_ARM_MAPPING")

    report: Dict[str, Any] = {
        "study_id": study_id, "freeze_path": freeze_rel, "freeze_sha256": freeze_sha,
        "freeze_sha256_source": "git_head_blob", "freeze_head_sha": freeze_head_sha,
        "bundle_path": str(bundle_path), "bundle_sha256": ms._sha(bundle_path),
        "arms": {}, "migrated": 0, "already_present": 0, "failed": [],
    }
    for arm, rec in bundle.items():
        try:
            fit_identity = rec.get("fit_identity_sha256") if isinstance(rec, Mapping) else None
            if not fit_identity or freeze.get("model_hashes", {}).get(arm) != fit_identity:
                raise ms.ModelStoreError(f"BUNDLE_FREEZE_FIT_IDENTITY_MISMATCH: arm={arm}")
            family = arm.rsplit("_", 1)[-1] if "_" in arm else arm
            direction = arm.split("_", 1)[0] if "_" in arm else None
            ordered_inputs = list(freeze.get("feature_sets", {}).get(family) or [])
            if not ordered_inputs:
                raise ms.ModelStoreError(f"BUNDLE_FREEZE_FEATURE_SET_MISSING: arm={arm} family={family}")
            model_id = ms._recompute_legacy_v1_train_freeze_id(study_id, arm, fit_identity, freeze.get("freeze_sha256"))
            feature_contract = hashlib.sha256(json.dumps(ordered_inputs).encode("utf-8")).hexdigest()
            lineage = ms.ModelLineage(
                study_id=study_id, cell_id=None, direction=direction, target_arm=family, fold_id=None, config_id=None,
                seed=None, ordered_inputs=ordered_inputs, feature_contract_sha256=feature_contract,
                preprocessing_contract_sha256="identity", target_contract_sha256=freeze.get("target_contract_sha256"),
                target_frame_identity=None, training_population_identity=freeze.get("merged_dataset_identity_sha256"),
                train_years=[], validation_years=[], hyperparameters={}, family="lightgbm",
                fit_identity_sha256=fit_identity, closure_identities={}, model_role=arm,
            )
            legacy_registry_record = {
                "train_freeze_path": freeze_rel, "train_freeze_sha256": freeze_sha, "arm": arm,
                "train_freeze_sha256_source": "git_head_blob", "train_freeze_head_sha": freeze_head_sha,
                "train_freeze_preprocessing_hash": freeze.get("preprocessing_hash"),
                "train_freeze_provenance": freeze.get("provenance"),
            }
            existed = (ms.model_dir(model_id, model_root) / "manifest.json").is_file()
            estimator = rec.get("estimator")
            manifest = ms.store_model(
                model_id=model_id, estimator=estimator, lineage=lineage, tier=tier, selection_status=selection_status,
                metrics={}, golden_train_frame=train_frame, model_root=model_root, scientific_status="UNASSESSED",
                legacy_registry_record=legacy_registry_record, golden_rows=golden_rows,
                identity_rule=ms.LEGACY_V1_TRAIN_FREEZE_RULE,
            )
            report["arms"][arm] = {"model_id": model_id, "status": "already_present" if existed else "migrated", "tier": manifest.get("tier")}
            report["already_present" if existed else "migrated"] += 1
        except Exception as exc:
            report["failed"].append({"arm": arm, "error": f"{type(exc).__name__}: {exc}"})
    return report


__all__ = ["migrate_legacy_records", "selected_configs_from_phase_d_report", "parse_model_role", "migrate_train_freeze_bundle"]

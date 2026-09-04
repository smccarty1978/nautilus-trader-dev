#!/usr/bin/env python3
"""Write an ADDITIVE TRAIN provenance attestation for a closed study's freeze artifacts.

Some historical TRAIN freezes were written without the ``provenance: "TRAIN_ONLY"`` marker that
``research_workflow.external_model_scoring`` requires before a frozen model may be consumed as a
derived causal input. The freeze is not wrong -- the field was simply never stamped -- but a
closed study's artifacts are immutable (WORKFLOW.md golden rule 11), so the marker cannot be
added in place.

This writes a SEPARATE attestation that binds, by exact hash, the freeze it speaks for, the model
bytes it speaks for, and the parent's audited authority. It never modifies an original artifact.

It is not a way to *assert* TRAIN-only. It PROVES it from the freeze's own contents and refuses to
write when the evidence is absent:

  * ``partition == "train"``
  * every threshold's ``derivation_population == "train"``
  * every decile block's ``derivation == "TRAIN_ONLY"``
  * the parent's closure is CLOSED with causal AND contract audits CLEAR, both bound to the same
    execution composite

A freeze whose thresholds were derived on anything but TRAIN cannot be attested by this tool.

Usage:
    python scripts/write_train_provenance_attestation.py \
        --study studies/<parent_id> \
        --cell LONG=artifacts/train_experiment_freeze_long.json:artifacts/models/<id>.joblib:C \
        --cell SHORT=artifacts/train_experiment_freeze_short.json:artifacts/models/<id>.joblib:C \
        [--out artifacts/train_provenance_attestation.json] [--check]

``--check`` recomputes and compares against the artifact on disk without writing (CI use).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.analysis.identity import canonical_sha256  # noqa: E402

SCHEMA_VERSION = 1
REPAIR_SCHEMA_VERSION = 1
KIND = "train_provenance_attestation"
DEFAULT_OUT = "artifacts/train_provenance_attestation.json"


class AttestationError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AttestationError(f"ATTESTATION_INPUT_UNREADABLE: {path}: {exc}") from exc


def _parent_authority(study: Path) -> dict:
    """The parent's own closed authority: closure identity, execution composite, both audits."""
    closure_rel = "artifacts/study_closure.json"
    closure_path = study / closure_rel
    if not closure_path.is_file():
        raise AttestationError("ATTESTATION_PARENT_NOT_CLOSED: no artifacts/study_closure.json")
    closure = _read(closure_path)
    if closure.get("status") != "CLOSED":
        raise AttestationError(f"ATTESTATION_PARENT_NOT_CLOSED: status={closure.get('status')!r}")
    identity = closure.get("closure_identity_sha256")
    recomputed = canonical_sha256({k: v for k, v in closure.items()
                                   if k not in {"closed_at_utc", "closure_identity_sha256"}})
    if not identity or recomputed != identity:
        raise AttestationError("ATTESTATION_PARENT_CLOSURE_IDENTITY_MISMATCH")
    bound = closure.get("bound_evidence") or {}
    composite = bound.get("execution_composite_sha256")
    if not composite:
        raise AttestationError("ATTESTATION_PARENT_EXECUTION_COMPOSITE_MISSING")
    audits = {}
    for kind, status_name in (("causal", "status.json"), ("contract", "contract_status.json")):
        rec = bound.get(f"{kind}_audit") or {}
        if rec.get("verdict") != "CLEAR":
            raise AttestationError(f"ATTESTATION_PARENT_AUDIT_NOT_CLEAR: {kind}")
        status_path = study / "audit" / status_name
        status = _read(status_path) if status_path.is_file() else {}
        # The audit must bind the SAME execution composite the closure names, or it is not
        # evidence about the artifacts this attestation speaks for.
        audited = status.get("audited_execution_composite_sha256")
        if status and (status.get("verdict") != "CLEAR" or audited != composite):
            raise AttestationError(
                f"ATTESTATION_PARENT_AUDIT_COMPOSITE_MISMATCH: {kind} audited={audited} closure={composite}")
        audits[kind] = {"verdict": "CLEAR", "pass": rec.get("pass"), "auditor": rec.get("auditor"),
                        "report_path": rec.get("report"), "report_sha256": rec.get("report_sha256"),
                        "audited_execution_composite_sha256": audited or composite}
    return {
        "closure_path": closure_rel, "closure_file_sha256": _sha(closure_path),
        "closure_identity_sha256": identity, "closure_status": "CLOSED",
        "execution_composite_sha256": composite,
        "train_freeze_sha256": bound.get("train_freeze_sha256"),
        "audits": audits,
    }


def _cell(study: Path, direction: str, freeze_rel: str, model_rel: str, arm: str) -> dict:
    """One attested cell, with the TRAIN-only evidence proven from the freeze's own contents."""
    freeze_path, model_path = study / freeze_rel, study / model_rel
    for p, code in ((freeze_path, "FREEZE"), (model_path, "MODEL_ARTIFACT")):
        if not p.is_file():
            raise AttestationError(f"ATTESTATION_{code}_MISSING: {p}")
    freeze = _read(freeze_path)
    if freeze.get("study_id") != study.name:
        raise AttestationError(f"ATTESTATION_FREEZE_STUDY_MISMATCH: {freeze.get('study_id')!r} != {study.name!r}")
    if freeze.get("partition") != "train":
        raise AttestationError(f"ATTESTATION_FREEZE_NOT_TRAIN_PARTITION: {freeze.get('partition')!r}")

    thresholds = (freeze.get("thresholds") or {}).get(arm) or {}
    if not thresholds:
        raise AttestationError(f"ATTESTATION_FREEZE_ARM_UNKNOWN: {arm!r}")
    bad = {k: v.get("derivation_population") for k, v in thresholds.items()
           if v.get("derivation_population") != "train"}
    if bad:
        raise AttestationError(f"ATTESTATION_THRESHOLDS_NOT_TRAIN_DERIVED: {bad}")
    decile = (freeze.get("deciles") or {}).get(arm, {}).get("derivation")
    if decile != "TRAIN_ONLY":
        raise AttestationError(f"ATTESTATION_DECILES_NOT_TRAIN_ONLY: {decile!r}")
    surface = list((freeze.get("feature_sets") or {}).get(arm) or [])
    fit_identity = (freeze.get("model_hashes") or {}).get(arm)
    if not surface or not fit_identity:
        raise AttestationError(f"ATTESTATION_FREEZE_ARM_INCOMPLETE: {arm!r}")

    # Two clearly separated groups. Everything at the top level is BINDING: the consuming binder
    # checks each one and refuses on any mismatch. Everything under `descriptive_only` is context
    # for a human reader and is NOT verified by anything -- kept in its own object so the artifact
    # cannot create the impression that it was.
    return {
        "direction": direction, "arm": arm, "cell_id": f"{direction}_{arm}",
        "original_freeze_path": freeze_rel,
        "original_freeze_canonical_sha256": canonical_sha256(freeze),
        "model_artifact_path": model_rel,
        "model_artifact_sha256": _sha(model_path),
        "fit_identity_sha256": fit_identity,
        "preprocessing_hash": freeze.get("preprocessing_hash"),
        "descriptive_only": {
            "_note": "context for readers; NOT verified by the binder. Only top-level fields bind.",
            "original_freeze_file_sha256_at_attestation_time": _sha(freeze_path),
            "original_freeze_file_sha256_is_checkout_dependent": True,
            "freeze_declared_freeze_sha256": freeze.get("freeze_sha256"),
            "freeze_authorization_sha256": freeze.get("authorization_sha256"),
            "ordered_feature_surface": surface,
            "thresholds": {k: v.get("threshold") for k, v in thresholds.items()},
        },
        "train_only_evidence": {
            "partition": freeze.get("partition"),
            "threshold_derivation_population": {k: v.get("derivation_population") for k, v in thresholds.items()},
            "decile_derivation": decile,
            "model_selection_manifest_sha256": freeze.get("model_selection_manifest_sha256"),
        },
    }


def build(study: Path, cells: list[tuple[str, str, str, str]]) -> dict:
    study = Path(study).resolve()
    body = {
        "schema_version": SCHEMA_VERSION,
        "repair_schema_version": REPAIR_SCHEMA_VERSION,
        "kind": KIND,
        "parent_study_id": study.name,
        "assertion": "TRAIN_ONLY",
        "reason": ("the original freeze artifacts predate the provenance marker and are immutable "
                   "closed-study authority; this attestation is additive and modifies nothing"),
        "declarations": {
            "NO_RETRAIN": True,
            "NO_MODEL_BYTE_CHANGE": True,
            "NO_SCORE_CHANGE": True,
            "NO_SCIENTIFIC_AUTHORITY_CHANGE": True,
        },
        "parent_authority": _parent_authority(study),
        "cells": [_cell(study, d, f, m, a) for d, f, m, a in cells],
    }
    body["attestation_sha256"] = canonical_sha256(body)
    return body


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--study", required=True)
    ap.add_argument("--cell", action="append", required=True,
                    metavar="DIRECTION=freeze_rel:model_rel:arm",
                    help="repeatable; e.g. LONG=artifacts/train_experiment_freeze_long.json:artifacts/models/x.joblib:C")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="verify the on-disk artifact instead of writing")
    ns = ap.parse_args(argv)

    cells = []
    for raw in ns.cell:
        direction, _, rest = raw.partition("=")
        parts = rest.split(":")
        if not direction or len(parts) != 3:
            raise SystemExit(json.dumps({"STATUS": "FAIL", "error": f"BAD_CELL: {raw!r}"}))
        cells.append((direction.strip().upper(), parts[0], parts[1], parts[2]))

    study = Path(ns.study).resolve()
    try:
        body = build(study, cells)
    except AttestationError as exc:
        print(json.dumps({"STATUS": "FAIL", "error": str(exc)}))
        return 2

    out = study / ns.out
    if ns.check:
        if not out.is_file():
            print(json.dumps({"STATUS": "FAIL", "error": "ATTESTATION_MISSING", "path": str(out)}))
            return 2
        current = _read(out)
        same = current.get("attestation_sha256") == body["attestation_sha256"]
        print(json.dumps({"STATUS": "OK" if same else "FAIL",
                          "attestation_sha256": current.get("attestation_sha256"),
                          "recomputed": body["attestation_sha256"], "current": same}))
        return 0 if same else 2

    body["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"STATUS": "OK", "path": str(out), "file_sha256": _sha(out),
                      "attestation_sha256": body["attestation_sha256"],
                      "cells": [c["cell_id"] for c in body["cells"]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Provenance-bound runtime scoring of frozen upstream models."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping

import joblib
import pandas as pd

from research.analysis.identity import canonical_sha256
from research.schemas.study_spec import DerivedCausalInputSpec


class ExternalModelScoringError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class DerivedScoreObservation:
    name: str
    score: float
    checkpoint_ts: int
    latest_input_availability_ts: int
    direction: str
    arm: str
    model_hash: str
    preprocessing_hash: str
    # RT-B2: the derived score's TRUE causal availability -- max(every input's availability,
    # the score's own evaluation timestamp) -- never the decision epoch assigned blindly.
    available_at_ns: int = 0
    # How ``latest_input_availability_ts`` (per-input) was derived: either the caller's real,
    # per-column availability (``"per_input_declared"``) or a conservative upper bound equal to
    # the checkpoint timestamp, used when the caller has no finer-grained availability data
    # (``"checkpoint_ts_upper_bound"``). Either value is a sound upper bound; the label is
    # provenance only, never loosens the ``available_at_ns > checkpoint_ts`` refusal above.
    availability_source: str = "checkpoint_ts_upper_bound"


ATTESTATION_KIND = "train_provenance_attestation"


def _resolve_train_provenance(spec: DerivedCausalInputSpec, freeze: Mapping, freeze_path: Path,
                              parent: Path, model_path: Path) -> dict:
    """Establish that the bound freeze is TRAIN-only, and say how.

    Two accepted sources, and only two:

    A. the freeze declares ``provenance: "TRAIN_ONLY"`` itself;
    B. an additive provenance-repair attestation binds THIS freeze's bytes, THIS model's bytes and
       the parent's audited authority, by exact hash.

    There is deliberately no third case. A freeze that declares nothing and carries no attestation
    is refused exactly as before -- "missing provenance" never means "TRAIN".
    """
    if freeze.get("provenance") == "TRAIN_ONLY":
        return {"source": "freeze_declares_train_only", "attestation": None}

    rel, declared_sha = spec.parent_provenance_attestation_path, spec.parent_provenance_attestation_sha256
    cell_id = spec.parent_provenance_cell_id
    if not (rel and declared_sha and cell_id):
        raise ExternalModelScoringError("parent TRAIN freeze is not TRAIN_ONLY")

    path = (parent / str(rel)).resolve()
    if parent.resolve() not in path.parents:
        raise ExternalModelScoringError("PROVENANCE_ATTESTATION_FOREIGN: attestation must live inside the parent study")
    if not path.is_file():
        raise ExternalModelScoringError(f"PROVENANCE_ATTESTATION_MISSING: {rel}")
    actual_sha = _sha256(path)
    if actual_sha != declared_sha:
        raise ExternalModelScoringError(
            f"PROVENANCE_ATTESTATION_SHA_MISMATCH: expected {declared_sha}, got {actual_sha}")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExternalModelScoringError("PROVENANCE_ATTESTATION_MALFORMED") from exc
    if body.get("kind") != ATTESTATION_KIND or body.get("assertion") != "TRAIN_ONLY":
        raise ExternalModelScoringError("PROVENANCE_ATTESTATION_MALFORMED")
    if body.get("parent_study_id") != spec.parent_study_id:
        raise ExternalModelScoringError(
            f"PROVENANCE_ATTESTATION_STUDY_MISMATCH: {body.get('parent_study_id')!r} != {spec.parent_study_id!r}")

    authority = body.get("parent_authority") or {}
    composite = authority.get("execution_composite_sha256")
    if not composite or composite != spec.parent_frozen_execution_composite_sha256:
        raise ExternalModelScoringError(
            f"PROVENANCE_ATTESTATION_EXECUTION_COMPOSITE_MISMATCH: attestation={composite} "
            f"declared={spec.parent_frozen_execution_composite_sha256}")
    audits = authority.get("audits") or {}
    for kind in ("causal", "contract"):
        rec = audits.get(kind) or {}
        if rec.get("verdict") != "CLEAR" or rec.get("audited_execution_composite_sha256") != composite:
            raise ExternalModelScoringError(f"PROVENANCE_ATTESTATION_AUDIT_EVIDENCE_MISSING: {kind}")

    matching = [c for c in (body.get("cells") or []) if c.get("cell_id") == cell_id]
    if len(matching) != 1:
        raise ExternalModelScoringError(f"PROVENANCE_ATTESTATION_CELL_MISMATCH: {cell_id!r} matched {len(matching)} cells")
    cell = matching[0]
    if cell.get("original_freeze_path") != spec.parent_train_freeze_artifact:
        raise ExternalModelScoringError(
            f"PROVENANCE_ATTESTATION_FREEZE_MISMATCH: cell binds {cell.get('original_freeze_path')!r}, "
            f"spec binds {spec.parent_train_freeze_artifact!r}")
    # Bind the freeze by CANONICAL CONTENT identity, not by file bytes. Tracked JSON is subject to
    # end-of-line conversion on checkout, so a byte hash of the working tree says as much about the
    # platform that checked the repo out as about the artifact -- which is precisely the failure
    # that made this repair necessary in the first place. Canonical content identity is exact and
    # checkout-independent: a freeze whose CONTENT differs at all cannot match.
    attested_canonical = cell.get("original_freeze_canonical_sha256")
    if not attested_canonical:
        raise ExternalModelScoringError("PROVENANCE_ATTESTATION_MALFORMED: cell has no freeze content identity")
    if attested_canonical != canonical_sha256(dict(freeze)):
        raise ExternalModelScoringError("PROVENANCE_ATTESTATION_FREEZE_MISMATCH: attested freeze content differs")
    if cell.get("model_artifact_sha256") != _sha256(model_path):
        raise ExternalModelScoringError("PROVENANCE_ATTESTATION_MODEL_ARTIFACT_MISMATCH")
    arm = cell.get("arm")
    if arm not in (spec.model_hashes or {}) or (spec.model_hashes or {}).get(arm) != cell.get("fit_identity_sha256"):
        raise ExternalModelScoringError("PROVENANCE_ATTESTATION_MODEL_ARTIFACT_MISMATCH: arm fit identity differs")
    if cell.get("preprocessing_hash") != spec.preprocessing_hash:
        raise ExternalModelScoringError("PROVENANCE_ATTESTATION_PREPROCESSING_MISMATCH")
    return {"source": "additive_provenance_attestation", "attestation": {
        "path": str(rel), "file_sha256": actual_sha,
        "attestation_sha256": body.get("attestation_sha256"),
        "cell_id": cell_id, "execution_composite_sha256": composite,
        "freeze_canonical_sha256": attested_canonical,
        "declarations": body.get("declarations"),
    }}


class FrozenExternalModelScorer:
    """Load once, verify exact identities, and score causal snapshots without fitting."""

    def __init__(self, spec: DerivedCausalInputSpec, parent_dir: Path, bundle, recovered: Mapping | None = None,
                 train_provenance: Mapping | None = None) -> None:
        self.spec = spec
        self.parent_dir = parent_dir
        self._bundle = bundle
        self._recovered = dict(recovered or {})
        # How this binding established that the freeze is TRAIN-only: the freeze's own marker, or
        # an additive provenance attestation. Recorded so a study's lineage says which.
        self.train_provenance = dict(train_provenance or {})

    @classmethod
    def bind(
        cls, spec: DerivedCausalInputSpec, *, parent_dir: str | Path
    ) -> "FrozenExternalModelScorer":
        # New workflow declarations bind by immutable registry id and intentionally
        # do not consult the source study's current lifecycle state.
        if spec.model_id:
            from research_workflow.model_artifacts import load_model_bundle, resolve_model
            registry = Path(parent_dir).resolve().parents[0] / "model_registry"
            # RT-09: consuming a frozen model as a derived causal input enforces
            # scientific_status + recorded runtime identity, not just reuse_status.
            rec = resolve_model(
                spec.model_id, registry_root=registry,
                reuse_intent="derived_causal_input",
                reuse_policy=(spec.diagnostic_reuse_policy.model_dump()
                              if spec.diagnostic_reuse_policy is not None else None),
            )
            artifact = rec.get("_artifact_path", rec["artifact_path"])
            bundle = load_model_bundle(rec)  # joblib load, with native-booster recovery
            return cls(spec, Path(artifact).parent, bundle, rec)
        required = {
            "model_artifact_path": spec.model_artifact_path,
            "model_artifact_sha256": spec.model_artifact_sha256,
            "preprocessing_artifact_path": spec.preprocessing_artifact_path,
            "preprocessing_artifact_sha256": spec.preprocessing_artifact_sha256,
            "ordered_feature_surfaces": spec.ordered_feature_surfaces,
            "direction_arm_mapping": spec.direction_arm_mapping,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ExternalModelScoringError(
                f"EXTERNAL_SCORER_BINDING_INCOMPLETE: missing {missing}"
            )
        parent = Path(parent_dir).resolve()
        freeze_path = parent / str(spec.parent_train_freeze_artifact)
        if not freeze_path.is_file():
            raise ExternalModelScoringError(f"parent TRAIN freeze missing: {freeze_path}")
        actual_freeze_sha = _sha256(freeze_path)
        if actual_freeze_sha != spec.parent_train_freeze_artifact_sha256:
            raise ExternalModelScoringError(
                "parent TRAIN freeze sha256 mismatch: "
                f"expected {spec.parent_train_freeze_artifact_sha256}, got {actual_freeze_sha}"
            )
        try:
            freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ExternalModelScoringError("parent TRAIN freeze is not valid JSON") from exc
        if freeze.get("study_id") != spec.parent_study_id:
            raise ExternalModelScoringError("parent TRAIN freeze study identity mismatch")
        model_path = parent / str(spec.model_artifact_path)
        prep_path = parent / str(spec.preprocessing_artifact_path)
        provenance = _resolve_train_provenance(spec, freeze, freeze_path, parent, model_path)
        for path, expected, label in (
            (model_path, spec.model_artifact_sha256, "model"),
            (prep_path, spec.preprocessing_artifact_sha256, "preprocessing"),
        ):
            if not path.is_file():
                raise ExternalModelScoringError(f"{label} artifact missing: {path}")
            actual = _sha256(path)
            if actual != expected:
                raise ExternalModelScoringError(
                    f"{label} artifact sha256 mismatch: expected {expected}, got {actual}"
                )
        bundle = joblib.load(model_path)
        if not isinstance(bundle, Mapping):
            raise ExternalModelScoringError("frozen model bundle must be an arm mapping")
        for direction, arm in spec.direction_arm_mapping.items():
            if arm not in bundle:
                raise ExternalModelScoringError(
                    f"direction {direction} maps to absent arm {arm!r}"
                )
            rec = bundle[arm]
            actual_hash = rec.get("fit_identity_sha256") if isinstance(rec, Mapping) else None
            if actual_hash != spec.model_hashes.get(arm):
                raise ExternalModelScoringError(
                    f"arm {arm!r} fit identity does not match declared model_hashes"
                )
            if arm not in spec.ordered_feature_surfaces:
                raise ExternalModelScoringError(f"arm {arm!r} has no ordered feature surface")
            if freeze.get("model_hashes", {}).get(arm) != actual_hash:
                raise ExternalModelScoringError(
                    f"arm {arm!r} does not match parent TRAIN freeze model hash"
                )
            if list(freeze.get("feature_sets", {}).get("C", ())) != list(spec.ordered_feature_surfaces[arm]):
                raise ExternalModelScoringError(
                    f"arm {arm!r} ordered feature surface does not match parent TRAIN freeze"
                )
        if freeze.get("preprocessing_hash") != spec.preprocessing_hash:
            raise ExternalModelScoringError("preprocessing identity does not match parent TRAIN freeze")
        return cls(spec, parent, bundle, train_provenance=provenance)

    def _arm_for(self, direction: str) -> str:
        direction = str(direction).upper()
        routing = self._recovered.get("direction_routing") or self.spec.direction_arm_mapping or {}
        arm = routing.get(direction) or (self._recovered.get("model_role") if len(routing) <= 1 else None)
        if arm is None:
            raise ExternalModelScoringError(f"no frozen arm mapping for {direction!r}")
        return arm

    def ordered_inputs(self, direction: str) -> list[str]:
        """The ordered causal-feature surface this scorer needs for ``direction`` -- from
        the spec's ``ordered_feature_surfaces`` or, for a ``model_id`` binding, the
        registry record's ``ordered_model_inputs`` (RT-04: the collector reads this to
        assemble the snapshot for every declared derived input, not just the first)."""
        arm = self._arm_for(direction)
        surfaces = self.spec.ordered_feature_surfaces or {}
        return list(surfaces.get(arm) or self._recovered.get("ordered_model_inputs") or [])

    def score(
        self,
        causal_snapshot: Mapping[str, float],
        *,
        checkpoint_ts: int,
        direction: str,
        availability_ts: Mapping[str, int],
        score_evaluation_ts: int | None = None,
        availability_source: str = "checkpoint_ts_upper_bound",
    ) -> DerivedScoreObservation:
        """Score at ``checkpoint_ts``. ``score_evaluation_ts`` is when the score itself was
        actually produced (defaults to ``checkpoint_ts`` for synchronous, in-process scoring;
        a future asynchronous/multi-stream scorer passes the real, possibly later, timestamp).
        The observation's causal availability is ``max(every input's availability_ts,
        score_evaluation_ts)`` -- it is NEVER assigned ``checkpoint_ts`` blindly. A score whose
        availability lands after ``checkpoint_ts`` is refused (not exposed re-stamped as if
        current)."""
        direction = str(direction).upper()
        arm = self._arm_for(direction)
        surfaces = self.spec.ordered_feature_surfaces or {}
        features = list(surfaces.get(arm) or self._recovered.get("ordered_model_inputs") or [])
        missing = [name for name in features if name not in causal_snapshot]
        missing_availability = [name for name in features if name not in availability_ts]
        if missing or missing_availability:
            raise ExternalModelScoringError(
                f"causal snapshot incomplete: values={missing}, availability={missing_availability}"
            )
        evaluation_ts = int(checkpoint_ts) if score_evaluation_ts is None else int(score_evaluation_ts)
        latest_input_availability_ts = max((int(availability_ts[n]) for n in features), default=0)
        available_at_ns = max(latest_input_availability_ts, evaluation_ts)
        if available_at_ns > int(checkpoint_ts):
            raise ExternalModelScoringError(
                f"EXTERNAL_SCORE_INPUT_NOT_AVAILABLE_AT_CHECKPOINT: available_at_ns={available_at_ns} > checkpoint_ts={checkpoint_ts}"
            )
        frame = pd.DataFrame(
            [[causal_snapshot[name] for name in features]], columns=features
        )
        if frame.isna().any(axis=None):
            raise ExternalModelScoringError("external score input contains null values")
        rec = self._bundle[arm]
        estimator = rec.get("estimator") if isinstance(rec, Mapping) else rec
        if not hasattr(estimator, "predict_proba"):
            raise ExternalModelScoringError(f"arm {arm!r} has no predict_proba")
        score = float(estimator.predict_proba(frame)[0][1])
        return DerivedScoreObservation(
            name=self.spec.name,
            score=score,
            checkpoint_ts=int(checkpoint_ts),
            latest_input_availability_ts=latest_input_availability_ts,
            available_at_ns=available_at_ns,
            direction=direction,
            arm=arm,
            model_hash=(self.spec.model_hashes or {}).get(arm, rec.get("fit_identity_sha256", "")),
            preprocessing_hash=self.spec.preprocessing_hash or self._recovered.get("preprocessing_identity", ""),
            availability_source=availability_source,
        )


__all__ = [
    "DerivedScoreObservation", "ExternalModelScoringError", "FrozenExternalModelScorer",
]

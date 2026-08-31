"""Provenance-bound runtime scoring of frozen upstream models."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping

import joblib
import pandas as pd

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


class FrozenExternalModelScorer:
    """Load once, verify exact identities, and score causal snapshots without fitting."""

    def __init__(self, spec: DerivedCausalInputSpec, parent_dir: Path, bundle, recovered: Mapping | None = None) -> None:
        self.spec = spec
        self.parent_dir = parent_dir
        self._bundle = bundle
        self._recovered = dict(recovered or {})

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
        if freeze.get("provenance") != "TRAIN_ONLY":
            raise ExternalModelScoringError("parent TRAIN freeze is not TRAIN_ONLY")
        if freeze.get("study_id") != spec.parent_study_id:
            raise ExternalModelScoringError("parent TRAIN freeze study identity mismatch")
        model_path = parent / str(spec.model_artifact_path)
        prep_path = parent / str(spec.preprocessing_artifact_path)
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
        return cls(spec, parent, bundle)

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
    ) -> DerivedScoreObservation:
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
        future = [name for name in features if int(availability_ts[name]) > int(checkpoint_ts)]
        if future:
            raise ExternalModelScoringError(
                f"EXTERNAL_SCORE_INPUT_NOT_AVAILABLE_AT_CHECKPOINT: {future}"
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
            latest_input_availability_ts=max(int(availability_ts[n]) for n in features),
            direction=direction,
            arm=arm,
            model_hash=(self.spec.model_hashes or {}).get(arm, rec.get("fit_identity_sha256", "")),
            preprocessing_hash=self.spec.preprocessing_hash or self._recovered.get("preprocessing_identity", ""),
        )


__all__ = [
    "DerivedScoreObservation", "ExternalModelScoringError", "FrozenExternalModelScorer",
]

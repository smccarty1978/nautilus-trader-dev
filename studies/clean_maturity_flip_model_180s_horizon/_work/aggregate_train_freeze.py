"""Aggregate the two per-direction TRAIN freezes into the canonical
``artifacts/train_experiment_freeze.json`` the OOS gate (``assert_oos_open``) reads.

ARTIFACT-SHAPE / OOS-GATE COMPATIBILITY REPAIR ONLY.
  - no refit, no retune
  - model bytes / ids / hashes: reused verbatim from the frozen per-direction models
  - feature surface / preprocessing hash / tuned HP / seed / TRAIN thresholds+deciles:
    reused verbatim
  - target contract / authorization hash: unchanged
  - both direction-specific selection-manifest bindings are preserved and re-proven
    by the generic direction-qualified binding path in freeze_train_artifacts
    (arms LONG_C / SHORT_C each bind against their own model_selection_manifest_*.json).

The per-direction freezes (train_experiment_freeze_{long,short}.json) are retained
unchanged as component evidence and recorded here by hash.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
STUDY = ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"
sys.path.insert(0, str(ROOT))

from research.schemas.study_spec import StudySpec  # noqa: E402
from research_workflow.modeling import freeze_train_artifacts  # noqa: E402
from research_workflow.experiment import assert_oos_open  # noqa: E402
import yaml  # noqa: E402

ART = STUDY / "artifacts"
DIRS = {"LONG": "long", "SHORT": "short"}
AGG_ARM = {"LONG": "LONG_C", "SHORT": "SHORT_C"}


def _sha256_bytes(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    study_spec = StudySpec.model_validate(yaml.safe_load((STUDY / "study.yaml").read_text(encoding="utf-8")))

    feature_sets: dict[str, list[str]] = {}
    thresholds: dict[str, dict] = {}
    deciles: dict[str, dict] = {}
    model_manifest_arms: dict[str, dict] = {}
    artifact_records: list[dict] = []
    manifest_map: dict[str, str] = {}
    components: dict[str, dict] = {}
    preproc_hashes: set[str] = set()
    auth_hashes: set[str] = set()

    for direction, tag in DIRS.items():
        arm = AGG_ARM[direction]
        fz_path = ART / f"train_experiment_freeze_{tag}.json"
        models_path = ART / f"experiment_models_{tag}.json"
        sel_path = ART / f"model_selection_manifest_{tag}.json"
        fz = json.loads(fz_path.read_text(encoding="utf-8"))
        models = json.loads(models_path.read_text(encoding="utf-8"))
        sel = json.loads(sel_path.read_text(encoding="utf-8"))

        arm_rec = models["arms"]["C"]
        winner = (sel.get("winner") or {}).get("C") or {}

        # Belt-and-suspenders: the frozen model's HP/seed must equal the direction's
        # selection-manifest winner. freeze_train_artifacts re-proves this generically;
        # asserting here too makes the repair self-verifying.
        assert arm_rec["hyperparameters"] == winner.get("hyperparameters"), (
            f"{direction}: frozen HP {arm_rec['hyperparameters']} != manifest winner "
            f"{winner.get('hyperparameters')}"
        )
        assert arm_rec["seed"] == sel.get("random_seed") == 42, f"{direction}: seed mismatch"
        assert fz["model_hashes"]["C"] == arm_rec["fit_identity_sha256"], f"{direction}: model hash drift"
        assert sel.get("final_validation_status") == "PASS", f"{direction}: 2023 gate not PASS"

        feature_sets[arm] = list(fz["feature_sets"]["C"])
        thresholds[arm] = fz["thresholds"]["C"]
        deciles[arm] = fz["deciles"]["C"]
        model_manifest_arms[arm] = {
            "hyperparameters": arm_rec["hyperparameters"],
            "seed": arm_rec["seed"],
            "fit_identity_sha256": arm_rec["fit_identity_sha256"],
        }
        rec = dict(fz["model_artifacts"][0])
        rec["model_role"] = arm  # C -> LONG_C / SHORT_C ; every other field verbatim
        artifact_records.append(rec)
        manifest_map[arm] = str(sel_path)
        preproc_hashes.add(fz["preprocessing_hash"])
        auth_hashes.add(fz["authorization_sha256"])
        components[arm] = {
            "direction": direction,
            "component_freeze_path": f"artifacts/train_experiment_freeze_{tag}.json",
            "component_freeze_sha256": fz["freeze_sha256"],
            "component_freeze_artifact_sha256": _sha256_bytes(fz_path),
            "model_selection_manifest_path": f"artifacts/model_selection_manifest_{tag}.json",
            "model_selection_manifest_sha256": fz["model_selection_manifest_sha256"],
            "model_id": rec["model_id"],
        }

    assert len(preproc_hashes) == 1, f"preprocessing hash differs across directions: {preproc_hashes}"
    assert len(auth_hashes) == 1, f"authorization hash differs across directions: {auth_hashes}"
    preprocessing_hash = next(iter(preproc_hashes))

    extra_payload = {
        "aggregate_of": {
            "kind": "direction_freeze_aggregate",
            "repair": "OOS_GATE_ARTIFACT_SHAPE_ONLY",
            "no_refit": True,
            "no_retune": True,
            "model_bytes_reused_verbatim": True,
            "components": components,
        }
    }

    out = freeze_train_artifacts(
        str(STUDY),
        feature_sets=feature_sets,
        models_manifest={"arms": model_manifest_arms},
        preprocessing_hash=preprocessing_hash,
        score_arrays={arm: [] for arm in feature_sets},   # thresholds supplied -> unused
        meta=pd.DataFrame({"_partition": ["train"]}),
        thresholds=thresholds,
        deciles=deciles,
        study_spec=study_spec,
        model_selection_manifest_path=manifest_map,
        model_artifact_records=artifact_records,
        extra_payload=extra_payload,
    )
    out = Path(out)
    assert out.name == "train_experiment_freeze.json", out
    agg = json.loads(out.read_text(encoding="utf-8"))

    # ---- parity proof vs the per-direction component freezes ----
    for direction, tag in DIRS.items():
        arm = AGG_ARM[direction]
        fz = json.loads((ART / f"train_experiment_freeze_{tag}.json").read_text(encoding="utf-8"))
        assert agg["feature_sets"][arm] == fz["feature_sets"]["C"], f"{arm}: feature set drift"
        assert agg["thresholds"][arm] == fz["thresholds"]["C"], f"{arm}: threshold drift"
        assert agg["deciles"][arm] == fz["deciles"]["C"], f"{arm}: decile drift"
        assert agg["model_hashes"][arm] == fz["model_hashes"]["C"], f"{arm}: model hash drift"
        am = next(r for r in agg["model_artifacts"] if r["model_role"] == arm)
        fm = fz["model_artifacts"][0]
        for k in ("model_id", "artifact_sha256", "golden_fixture_sha256", "native_booster_sha256"):
            assert am[k] == fm[k], f"{arm}: {k} drift"
    assert agg["preprocessing_hash"] == preprocessing_hash
    assert agg["authorization_sha256"] == next(iter(auth_hashes))
    assert agg["stage_scoped_lineage"]["COLLECTION_PRODUCER_CLOSURE"] == \
        json.loads((STUDY / "audit" / "frozen_execution_manifest.json").read_text())["frozen_execution_composite_sha256"]
    assert agg["model_selection_manifest_sha256"] == {
        "LONG_C": components["LONG_C"]["model_selection_manifest_sha256"],
        "SHORT_C": components["SHORT_C"]["model_selection_manifest_sha256"],
    }, agg["model_selection_manifest_sha256"]

    # ---- the OOS gate must now open ----
    freeze_seen = assert_oos_open(str(STUDY))
    assert freeze_seen["freeze_sha256"] == agg["freeze_sha256"]

    print(json.dumps({
        "status": "AGGREGATE_FREEZE_WRITTEN",
        "path": "artifacts/train_experiment_freeze.json",
        "freeze_sha256": agg["freeze_sha256"],
        "arms": sorted(agg["model_hashes"].keys()),
        "model_hashes": agg["model_hashes"],
        "model_ids": {r["model_role"]: r["model_id"] for r in agg["model_artifacts"]},
        "preprocessing_hash": agg["preprocessing_hash"],
        "authorization_sha256": agg["authorization_sha256"],
        "stage_scoped_lineage": agg["stage_scoped_lineage"],
        "model_selection_manifest_sha256": agg["model_selection_manifest_sha256"],
        "assert_oos_open": "PASS",
    }, indent=2))


if __name__ == "__main__":
    main()

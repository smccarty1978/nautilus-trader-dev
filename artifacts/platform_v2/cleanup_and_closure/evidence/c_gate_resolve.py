"""C gate: resolve every model_id derived input of the four consuming studies exactly as PREPARE does."""
import json, sys
from pathlib import Path
ROOT = Path.cwd(); sys.path.insert(0, str(ROOT))
import yaml
from research.schemas.study_spec import DerivedCausalInputSpec
from research_workflow.model_artifacts import ModelArtifactError, resolve_model
STUDIES = ["first_p90_warning_horizon_march2024", "v2_shape_b_deep_pullback_5s", "first_p90_warning_horizon_2024", "workflow_canary_model_reuse_v1"]
out = {}
for sid in STUDIES:
    spec = yaml.safe_load((ROOT / "studies" / sid / "study.yaml").read_text(encoding="utf-8"))
    for di in (spec.get("features") or {}).get("derived_inputs") or []:
        d = DerivedCausalInputSpec.model_validate(di)
        key = f"{sid}:{d.name}"
        if not d.model_id:
            out[key] = {"binding": "legacy_parent_freeze", "model_id": None, "disposition": "NOT_A_REGISTRY_RESOLUTION"}
            continue
        try:
            rec = resolve_model(d.model_id, registry_root=ROOT / "studies" / "model_registry", reuse_intent="derived_causal_input",
                                reuse_policy=(d.diagnostic_reuse_policy.model_dump() if d.diagnostic_reuse_policy is not None else None))
            out[key] = {"binding": "model_id", "model_id": d.model_id, "disposition": "RESOLVED", "artifact_sha256": rec.get("artifact_sha256")}
        except ModelArtifactError as exc:
            out[key] = {"binding": "model_id", "model_id": d.model_id, "disposition": "REFUSED", "error": str(exc).split(":")[0]}
print(json.dumps(out, indent=1, sort_keys=True))
if len(sys.argv) > 1: Path(sys.argv[1]).write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")

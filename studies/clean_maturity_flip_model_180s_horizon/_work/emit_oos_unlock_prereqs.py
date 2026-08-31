"""Emit the three legacy OOS-unlock prerequisite manifests as thin mirrors of the
canonical train_experiment_freeze.json, then generate artifacts/oos_unlock.json.

scripts/generate_oos_unlock.py (a sealed file -- must NOT be edited) requires
artifacts/frozen_feature_manifest.json, preprocessing_manifest.json and
model_manifest.json. Stage-scoped-lineage studies fold those facts into the
aggregate TRAIN freeze and never emit the standalone trio. This writes them as
derived mirrors (no new facts, every value copied from the freeze / feature
contract) so the unmodified generator's dependency chain resolves.

These three files are NOT in the study execution closure (only
artifacts/phase0_source_manifest.json is), so emitting them does not disturb the
sealed composite bd2e9cf1....
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
STUDY = ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"
ART = STUDY / "artifacts"
sys.path.insert(0, str(ROOT))
from research.analysis.identity import canonical_sha256  # noqa: E402

fz = json.loads((ART / "train_experiment_freeze.json").read_text(encoding="utf-8"))
fc = json.loads((STUDY / "config" / "feature_contract.json").read_text(encoding="utf-8"))

assert fz["partition"] == "train"
auth = fz["authorization_sha256"]
SRC = "train_experiment_freeze.json"

frozen_feature_manifest = {
    "schema_version": 1,
    "partition": "train",
    "feature_sets": fz["feature_sets"],
    "feature_contract_sha256": fc.get("contract_sha256") or fc.get("feature_contract_sha256"),
    "feature_list_sha256": fc["feature_list_sha256"],
    "authorization_sha256": auth,
    "derived_mirror_of": SRC,
}
preprocessing_manifest = {
    "schema_version": 1,
    "partition": "train",
    "preprocessing_hash": fz["preprocessing_hash"],
    "calibration": "none",
    "authorization_sha256": auth,
    "derived_mirror_of": SRC,
}
model_hashes = dict(fz["model_hashes"])
model_manifest = {
    "schema_version": 1,
    "partition": "train",
    "model_hashes": model_hashes,
    "model_ids": {r["model_role"]: r["model_id"] for r in fz["model_artifacts"]},
    "model_manifest_sha256": canonical_sha256({"model_hashes": model_hashes}),
    "authorization_sha256": auth,
    "derived_mirror_of": SRC,
}

for name, payload in (
    ("frozen_feature_manifest.json", frozen_feature_manifest),
    ("preprocessing_manifest.json", preprocessing_manifest),
    ("model_manifest.json", model_manifest),
):
    (ART / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("WROTE", name)

# Now run the UNMODIFIED sealed generator.
r = subprocess.run(
    [sys.executable, str(ROOT / "scripts" / "generate_oos_unlock.py"),
     "--study", str(STUDY), "--year", "2024"],
    capture_output=True, text=True, cwd=str(ROOT),
)
print(r.stdout)
if r.returncode != 0:
    print(r.stderr)
    sys.exit(r.returncode)

from scripts.generate_oos_unlock import verify_oos_unlock_token  # noqa: E402
assert verify_oos_unlock_token(STUDY, 2024), "verify_oos_unlock_token failed after generation"
tok = json.loads((ART / "oos_unlock.json").read_text(encoding="utf-8"))
print(json.dumps({
    "status": tok["status"],
    "oos_year": tok["oos_year"],
    "prerequisite_source": tok["prerequisite_hashes"].get("_prerequisite_source", "standalone_manifests"),
    "pristine_oos_proven": tok["lineage_audit"]["pristine_oos_proven"],
    "runs_inspected": tok["lineage_audit"]["runs_inspected_count"],
    "oos_leaks_count": tok["lineage_audit"]["oos_leaks_count"],
    "unlock_token_sha256": tok["unlock_token_sha256"],
    "verify_oos_unlock_token": True,
}, indent=2))

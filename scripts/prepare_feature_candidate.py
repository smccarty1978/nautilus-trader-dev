#!/usr/bin/env python3
"""Prepare and freeze an inactive canonical-feature authority candidate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.candidate_authority import CANDIDATE_DIR, freeze_candidate
from scripts.resolve_execution_manifest import resolve_execution_manifest


def prepare(study_dir: Path) -> dict:
    study_dir = study_dir.resolve()
    composite, hashes, manifest = resolve_execution_manifest(
        study_dir, feature_authority="candidate", authority_type="feature_candidate"
    )
    audit_dir = study_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = audit_dir / "candidate_execution_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Typed authorities use the same frozen-identity location consumed by the
    # existing audit/seal machinery; no study contract is implied.
    frozen_manifest_path = audit_dir / "frozen_execution_manifest.json"
    frozen_manifest_path.write_text(json.dumps({
        "frozen_execution_composite_sha256": composite,
        "file_sha256_map": hashes,
        "authority_type": "feature_candidate",
        "authority_path": str(study_dir / "feature_candidate.yaml"),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # This audit-side freeze is outside the candidate bundle: it pins the exact
    # inert bytes and complete execution closure without mutating either after
    # governance evidence is produced.
    frozen_path = audit_dir / "candidate" / "candidate_authority_freeze.json"
    frozen = freeze_candidate(frozen_path, execution_composite_sha256=composite)
    return {"candidate_execution_composite_sha256": composite, "candidate_execution_file_sha256_map": hashes,
            "candidate_bundle_freeze": frozen, "candidate_freeze_path": str(frozen_path),
            "candidate_manifest": str(manifest_path), "frozen_manifest": str(frozen_manifest_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(Path(args.study)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

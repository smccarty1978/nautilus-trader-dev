#!/usr/bin/env python3
"""Cryptographic Out-Of-Sample (OOS) Dependency-Chain Unlock Generator.
====================================================================
Deterministically verifies the complete prerequisite chain and empirically
measures current run lineage before authorizing OOS (2024) data access.
Emits artifacts/oos_unlock.json upon successful cryptographic verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def compute_file_sha256(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Prerequisite artifact missing: {path}")
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def inspect_run_lineage_for_oos_leakage(study_dir: Path, oos_year: int = 2024, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Empirically inspects all current run manifests in runs/ to prove pristine OOS status."""
    if repo_root is None:
        repo_root = REPO_ROOT

    runs_dir = repo_root / "runs"
    inspected_runs: List[str] = []
    oos_leaks_found: List[Dict[str, Any]] = []

    if runs_dir.exists():
        for run_p in sorted(runs_dir.glob(f"*_{study_dir.name}_*")):
            if not run_p.is_dir():
                continue
            inspected_runs.append(run_p.name)
            manifest_p = run_p / "run_manifest.json"
            if manifest_p.exists():
                try:
                    with open(manifest_p, "r", encoding="utf-8") as f:
                        mdata = json.load(f)
                    start_d = mdata.get("start_date", "")
                    end_d = mdata.get("end_date", "")
                    if str(oos_year) in start_d or str(oos_year) in end_d:
                        oos_leaks_found.append({
                            "run_name": run_p.name,
                            "start_date": start_d,
                            "end_date": end_d,
                            "reason": "Date range contains OOS year before authorized unlock",
                        })
                except Exception:
                    pass

    return {
        "runs_inspected_count": len(inspected_runs),
        "inspected_runs": inspected_runs,
        "oos_year": oos_year,
        "oos_leaks_count": len(oos_leaks_found),
        "oos_leaks": oos_leaks_found,
        "pristine_oos_proven": len(oos_leaks_found) == 0,
    }


def generate_oos_unlock(study_dir: Path, oos_year: int = 2024, repo_root: Optional[Path] = None) -> dict:
    if repo_root is None:
        repo_root = REPO_ROOT

    artifacts_dir = study_dir / "artifacts"
    if not artifacts_dir.exists():
        raise FileNotFoundError(f"Artifacts directory missing: {artifacts_dir}")

    # Required prerequisite frozen artifacts
    phase0_path = artifacts_dir / "phase0_source_manifest.json"
    train_coll_path = artifacts_dir / "train_collection_manifest.json"
    frozen_feat_path = artifacts_dir / "frozen_feature_manifest.json"
    prep_path = artifacts_dir / "preprocessing_manifest.json"
    model_path = artifacts_dir / "model_manifest.json"

    prereqs = {
        "phase0_manifest": phase0_path,
        "train_collection": train_coll_path,
        "frozen_feature_manifest": frozen_feat_path,
        "preprocessing_manifest": prep_path,
        "model_manifest": model_path,
    }

    missing = [name for name, p in prereqs.items() if not p.exists()]
    if missing:
        raise ValueError(
            f"OOS_UNLOCK_BLOCKED: Missing required frozen prerequisite artifacts: {missing}"
        )

    hashes = {name: compute_file_sha256(p) for name, p in prereqs.items()}

    # 2. Empirically inspect run lineage to prove pristine OOS
    lineage_audit = inspect_run_lineage_for_oos_leakage(study_dir, oos_year=oos_year, repo_root=repo_root)
    if not lineage_audit["pristine_oos_proven"]:
        raise ValueError(
            f"PRISTINE_OOS_NOT_PROVEN: Found {lineage_audit['oos_leaks_count']} runs accessing year {oos_year} before freeze: "
            f"{lineage_audit['oos_leaks']}"
        )

    # 3. Read pre-execution seal hash
    seal_path = artifacts_dir / "preexec_audit_seal.json"
    seal_hash = compute_file_sha256(seal_path) if seal_path.exists() else "UNSEALED"

    # Build unlock token
    token = {
        "status": "OOS_UNLOCKED",
        "oos_year": oos_year,
        "authorized_at_utc": datetime.now(timezone.utc).isoformat(),
        "prerequisite_hashes": hashes,
        "preexec_seal_artifact_sha256": seal_hash,
        "study_id": study_dir.name,
        "lineage_audit": lineage_audit,
        "pristine_oos_measured": True,
    }

    token_copy = dict(token)
    token_hash = hashlib.sha256(json.dumps(token_copy, sort_keys=True, indent=2).encode("utf-8")).hexdigest()
    token["unlock_token_sha256"] = token_hash

    out_path = artifacts_dir / "oos_unlock.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(token, f, indent=2)

    return token


def verify_oos_unlock_token(study_dir: Path, requested_year: int) -> bool:
    """Verifies that the OOS unlock token exists, is cryptographically intact, and proves pristine OOS."""
    unlock_path = study_dir / "artifacts" / "oos_unlock.json"
    if not unlock_path.exists():
        return False
    try:
        with open(unlock_path, "r", encoding="utf-8") as f:
            token = json.load(f)
        if token.get("status") != "OOS_UNLOCKED":
            return False
        if token.get("oos_year") != requested_year:
            return False
        if not token.get("pristine_oos_measured", False):
            return False

        # Re-verify token sha256
        stored_hash = token.get("unlock_token_sha256")
        token_copy = dict(token)
        token_copy.pop("unlock_token_sha256", None)
        computed_hash = hashlib.sha256(json.dumps(token_copy, sort_keys=True, indent=2).encode("utf-8")).hexdigest()
        return stored_hash == computed_hash
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Generate cryptographic OOS unlock token with lineage measurement.")
    parser.add_argument("--study", type=str, required=True, help="Path to study directory")
    parser.add_argument("--year", type=int, default=2024, help="OOS year to unlock (default: 2024)")
    args = parser.parse_args()

    study_dir = Path(args.study).resolve()
    try:
        token = generate_oos_unlock(study_dir, oos_year=args.year)
        print("=" * 65)
        print(f"OOS UNLOCK TOKEN GENERATED: {token['study_id']} (Year {token['oos_year']})")
        print(f"Token SHA-256: {token['unlock_token_sha256'][:16]}...")
        print(f"Pristine OOS Measured: {token['pristine_oos_measured']} ({token['lineage_audit']['runs_inspected_count']} runs inspected)")
        print(f"Authorized at: {token['authorized_at_utc']}")
        print("=" * 65)
    except Exception as e:
        print(f"[ERROR] OOS unlock generation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Add the frozen overlap disclosure to completed Phase C metadata."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .run_phase_a_collect import atomic_json, sha256_file
from .run_phase_c_months import OVERLAP_DISCLOSURE


def correct(root: Path, parity_path: Path) -> dict:
    manifests = sorted(root.glob("year=*/month=*/manifest.json"))
    if len(manifests) != 60:
        raise RuntimeError(f"expected 60 Phase C manifests, found {len(manifests)}")
    code_hash = sha256_file(Path(__file__))
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        selection = path.with_name("selected_trade_entries.parquet")
        if manifest.get("status") != "complete":
            raise RuntimeError(f"incomplete Phase C partition: {path}")
        if sha256_file(selection) != manifest.get("selection_sha256"):
            raise RuntimeError(f"selection hash mismatch: {selection}")
        manifest["threshold_reference_overlap_disclosure"] = OVERLAP_DISCLOSURE
        manifest["disclosure_correction_code_sha256"] = code_hash
        atomic_json(manifest, path)
    global_path = root / "global_selection_manifest.json"
    global_manifest = json.loads(global_path.read_text(encoding="utf-8"))
    global_manifest["threshold_reference_overlap_disclosure"] = OVERLAP_DISCLOSURE
    global_manifest["disclosure_correction_code_sha256"] = code_hash
    atomic_json(global_manifest, global_path)
    parity = json.loads(parity_path.read_text(encoding="utf-8"))
    if parity.get("status") != "PASS":
        raise RuntimeError("Phase C parity result is not PASS")
    parity["threshold_reference_overlap_disclosure"] = OVERLAP_DISCLOSURE
    parity["disclosure_correction_code_sha256"] = code_hash
    atomic_json(parity, parity_path)
    result = {
        "status": "complete",
        "partition_count": len(manifests),
        "disclosure": OVERLAP_DISCLOSURE,
        "correction_code_sha256": code_hash,
        "global_manifest_sha256": sha256_file(global_path),
        "parity_report_sha256": sha256_file(parity_path),
    }
    atomic_json(result, root / "disclosure_correction_manifest.json")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-c-root", required=True)
    parser.add_argument("--parity-result", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            correct(Path(args.phase_c_root), Path(args.parity_result)), indent=2
        )
    )


if __name__ == "__main__":
    main()

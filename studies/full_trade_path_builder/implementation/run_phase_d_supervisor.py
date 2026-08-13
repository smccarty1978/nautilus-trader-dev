"""Memory-isolated supervisor for the accepted Phase D monthly runner."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .run_phase_a_collect import ROOT, atomic_json, sha256_file
from .run_phase_d_months import (
    flip_ledger,
    load_phase_d_contract,
    run_month,
    validate_existing,
)


BASE = ROOT / "studies/full_trade_path_builder"
PHASE_B = BASE / "_work/phase_b_monthly"
PHASE_C = BASE / "_work/phase_c_selections"
OUTPUT = BASE / "_work/phase_d_monthly"
PROGRESS = BASE / "_work/phase_d_progress.json"


def accepted_inputs() -> tuple[dict, list[dict], str, dict, dict]:
    cglobal = json.loads((PHASE_C / "global_selection_manifest.json").read_text())
    if cglobal.get("status") != "complete" or cglobal.get("selected_trades") != 5836:
        raise RuntimeError("accepted Phase C global manifest unavailable")
    parity = json.loads((BASE / "results/phase_c_selection_parity.json").read_text())
    if parity.get("status") != "PASS" or parity.get("selected_trades") != 5836:
        raise RuntimeError("accepted Phase C parity unavailable")
    flips, flip_hash = flip_ledger(PHASE_B)
    identity, thresholds = load_phase_d_contract()
    return cglobal, flips, flip_hash, identity, thresholds


def monthly_manifest(
    year: int,
    month: int,
    cglobal: dict,
    flips: list[dict],
    flip_hash: str,
    identity: dict,
    thresholds: dict,
) -> dict:
    cdir = PHASE_C / f"year={year}" / f"month={month:02d}"
    selection_path = cdir / "selected_trade_entries.parquet"
    cmanifest = json.loads((cdir / "manifest.json").read_text())
    if cmanifest.get("status") != "complete":
        raise RuntimeError(f"incomplete Phase C partition: {cdir}")
    if cmanifest.get("phase_c_identity") != cglobal.get("phase_c_identity"):
        raise RuntimeError(f"Phase C identity mismatch: {cdir}")
    selection_hash = sha256_file(selection_path)
    if selection_hash != cmanifest["selection_sha256"]:
        raise RuntimeError(f"Phase C selection hash mismatch: {selection_path}")
    output_dir = OUTPUT / f"entry_year={year}" / f"entry_month={month:02d}"
    existing = validate_existing(output_dir, identity, selection_hash, flip_hash)
    return existing or run_month(
        selection_path,
        PHASE_B,
        output_dir,
        flips,
        flip_hash,
        identity,
        thresholds,
    )


def worker(year: int, month: int) -> None:
    cglobal, flips, flip_hash, identity, thresholds = accepted_inputs()
    manifest = monthly_manifest(
        year, month, cglobal, flips, flip_hash, identity, thresholds
    )
    print(json.dumps({"year": year, "month": month, **manifest}, sort_keys=True))


def completed_manifests() -> list[dict]:
    _, _, flip_hash, identity, _ = accepted_inputs()
    manifests = []
    for year in range(2021, 2026):
        for month in range(1, 13):
            path = OUTPUT / f"entry_year={year}" / f"entry_month={month:02d}" / "manifest.json"
            if not path.exists():
                raise RuntimeError(f"missing Phase D manifest: {path}")
            manifest = json.loads(path.read_text())
            if manifest.get("status") != "complete":
                raise RuntimeError(f"incomplete Phase D manifest: {path}")
            if manifest.get("phase_d_identity") != identity:
                raise RuntimeError(f"Phase D identity mismatch: {path}")
            if manifest.get("global_flip_ledger_sha256") != flip_hash:
                raise RuntimeError(f"Phase D flip identity mismatch: {path}")
            manifests.append(manifest)
    return manifests


def supervisor() -> None:
    completed = 0
    for year in range(2021, 2026):
        for month in range(1, 13):
            command = [
                sys.executable,
                "-m",
                "studies.full_trade_path_builder.implementation.run_phase_d_supervisor",
                "--worker-year",
                str(year),
                "--worker-month",
                str(month),
            ]
            subprocess.run(
                command,
                cwd=ROOT,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            completed += 1
            manifests = [
                json.loads(path.read_text())
                for path in sorted(OUTPUT.glob("entry_year=*/entry_month=*/manifest.json"))
                if json.loads(path.read_text()).get("status") == "complete"
            ]
            atomic_json(
                {
                    "status": "building",
                    "months_completed": len(manifests),
                    "last_completed": f"{year}-{month:02d}",
                    "trade_count": sum(item["trade_count"] for item in manifests),
                    "path_row_count": sum(item["path_row_count"] for item in manifests),
                    "memory_isolation": "one fresh process per entry month",
                },
                PROGRESS,
            )
    manifests = completed_manifests()
    _, _, flip_hash, identity, _ = accepted_inputs()
    result = {
        "status": "complete",
        "month_count": len(manifests),
        "trade_count": sum(item["trade_count"] for item in manifests),
        "path_row_count": sum(item["path_row_count"] for item in manifests),
        "completed_trade_count": sum(
            item["completed_trade_count"] for item in manifests
        ),
        "censored_trade_count": sum(
            item["censored_trade_count"] for item in manifests
        ),
        "phase_d_identity": identity,
        "global_flip_ledger_sha256": flip_hash,
        "memory_isolation": "one fresh process per entry month",
    }
    atomic_json(result, OUTPUT / "global_path_manifest.json")
    atomic_json(result, PROGRESS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-year", type=int)
    parser.add_argument("--worker-month", type=int)
    args = parser.parse_args()
    if args.worker_year is not None or args.worker_month is not None:
        if args.worker_year is None or args.worker_month is None:
            raise RuntimeError("worker year and month must be supplied together")
        worker(args.worker_year, args.worker_month)
    else:
        supervisor()


if __name__ == "__main__":
    main()

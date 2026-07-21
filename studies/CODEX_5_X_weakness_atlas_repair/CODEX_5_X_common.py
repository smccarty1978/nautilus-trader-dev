"""Paths and frozen contracts for the CODEX 5.X weakness-atlas repair."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS = STUDY / "results"
AUDIT = STUDY / "audit"
WORK = STUDY / "_work"
YEAR_DIR = WORK / "CODEX_5_X_repaired_years"
MODEL_DIR = WORK / "CODEX_5_X_models"

UPSTREAM = ROOT / "studies" / "regime_sequence_chop_context"
LEGACY_ATLAS = UPSTREAM / "results" / "weakness_checkpoint_atlas.parquet"
REPAIRED_ATLAS = RESULTS / "CODEX_5_X_weakness_checkpoint_atlas_repaired.parquet"
BUNDLE_PATH = MODEL_DIR / "CODEX_5_X_repaired_w4_bundle.pkl"
MANIFEST_PATH = RESULTS / "CODEX_5_X_frozen_model_manifest.json"
PRE_2026_AUTH_PATH = AUDIT / "CODEX_5_X_pre_2026_authorization.json"
FIRST_2026_OPEN_PATH = AUDIT / "CODEX_5_X_first_2026_open.json"
REQUIRED_DEPENDENCY_RELATIVE = (
    "studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_common.py",
    "studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_build_regime_history.py",
    "studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_build_repaired_atlas.py",
    "studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_train_repaired_w4.py",
    "studies/regime_sequence_chop_context/build_weakness_atlas.py",
    "studies/regime_sequence_chop_context/train_weakness_model.py",
    "studies/regime_sequence_chop_context/reproduce_regimes.py",
    "studies/regime_sequence_chop_context/build_median_centers.py",
    "studies/regime_sequence_chop_context/build_regime_sequence.py",
)

RAW_1S = {
    y: ROOT / "data" / "raw" / (
        f"NQ_v0_1s_{y}_ytd.parquet" if y == 2026 else f"NQ_v0_1s_{y}.parquet"
    )
    for y in range(2021, 2027)
}

NS = 1_000_000_000
SEED = 42
NAN_GATE = "aligned_price_minus_center_5m"
TRAIN_YEARS = (2021, 2022, 2023, 2024)
SELECTION_START_NS = 1735689600000000000  # 2025-01-01 UTC
SELECTION_END_NS = 1751328000000000000    # 2025-07-01 UTC
CALIBRATION_START_NS = SELECTION_END_NS
CALIBRATION_END_NS = 1767225600000000000  # 2026-01-01 UTC
TEST_START_NS = CALIBRATION_END_NS

for p in (RESULTS, AUDIT, WORK, YEAR_DIR, MODEL_DIR):
    p.mkdir(parents=True, exist_ok=True)


def year_atlas_path(year: int) -> Path:
    return YEAR_DIR / f"CODEX_5_X_weakness_atlas_repaired_{year}.parquet"


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def validate_existing_first_open(ledger: dict, expected: dict) -> None:
    if any(ledger.get(k) != v for k, v in expected.items()):
        raise RuntimeError("2026 sealed: first-open ledger contract mismatch")


def require_frozen_pre_2026_contract(reason: str) -> dict:
    """Fail closed unless model freeze and independent audit authorize 2026."""
    if not MANIFEST_PATH.exists() or not BUNDLE_PATH.exists():
        raise RuntimeError("2026 sealed: frozen manifest/bundle is missing")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN_PRE_2026_GATE_PASSED":
        raise RuntimeError("2026 sealed: manifest status is not authorized")
    if manifest.get("gate", {}).get("pass") is not True:
        raise RuntimeError("2026 sealed: repaired W4 gate failed")
    if sha256_file(BUNDLE_PATH) != manifest.get("bundle_sha256"):
        raise RuntimeError("2026 sealed: model bundle hash mismatch")

    for year in TRAIN_YEARS + (2025,):
        expected = manifest.get("repaired_atlas_sha256", {}).get(str(year))
        if not expected or sha256_file(year_atlas_path(year)) != expected:
            raise RuntimeError(f"2026 sealed: repaired atlas hash mismatch for {year}")
    dependency_hashes = manifest.get("dependency_sha256", {})
    if set(dependency_hashes) != set(REQUIRED_DEPENDENCY_RELATIVE):
        raise RuntimeError("2026 sealed: dependency hash inventory incomplete")
    for rel, expected in dependency_hashes.items():
        path = ROOT / rel
        if not path.exists() or sha256_file(path) != expected:
            raise RuntimeError(f"2026 sealed: dependency hash mismatch: {rel}")

    if not PRE_2026_AUTH_PATH.exists():
        raise RuntimeError("2026 sealed: independent pre-2026 audit authorization missing")
    auth = json.loads(PRE_2026_AUTH_PATH.read_text(encoding="utf-8"))
    manifest_hash = sha256_file(MANIFEST_PATH)
    if (auth.get("status") != "PASS"
            or auth.get("manifest_sha256") != manifest_hash
            or auth.get("bundle_sha256") != manifest.get("bundle_sha256")):
        raise RuntimeError("2026 sealed: audit authorization is stale or failed")

    expected_open = {
        "manifest_sha256": manifest_hash,
        "bundle_sha256": manifest["bundle_sha256"],
        "authorization_sha256": sha256_file(PRE_2026_AUTH_PATH),
        "raw_2026_sha256": sha256_file(RAW_1S[2026]),
    }
    if FIRST_2026_OPEN_PATH.exists():
        ledger = json.loads(FIRST_2026_OPEN_PATH.read_text(encoding="utf-8"))
        validate_existing_first_open(ledger, expected_open)
    else:
        write_json(FIRST_2026_OPEN_PATH, {
            "first_open_utc": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            **expected_open,
        })
    return manifest

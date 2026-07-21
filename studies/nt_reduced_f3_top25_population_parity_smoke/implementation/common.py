"""Shared paths/constants for the reduced-model NT population-parity smoke study."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parents[1]
CONFIG, RESULTS, AUDIT, WORK, TESTS = (
    STUDY / "config", STUDY / "results", STUDY / "audit", STUDY / "_work", STUDY / "tests")
for _p in (CONFIG, RESULTS, AUDIT, WORK, TESTS):
    _p.mkdir(parents=True, exist_ok=True)

RC = ROOT / "studies" / "runtime_constrained_f3_feature_reduction"
SRC_STUDY = ROOT / "studies" / "short_rth_pure_flip_prediction_enriched"
POC = ROOT / "studies" / "nt_pure_flip_trigger_poc_and_mirrored_long_model" / "phase2"

MODEL_ID = "F3_top25_gbt_v1"
MODEL_PATH = RC / "artifacts" / "models" / MODEL_ID / "model.joblib"
FEATURE_SETS_PATH = RC / "results" / "candidate_feature_sets.json"
EXPECTED_MODEL_SHA256 = "24bf6bece8319cb951bc82f31ea97ac7d3a0a9a200d598d986965143dec7e944"
EXPECTED_FEATURE_LIST_SHA256 = "8bcfeb74ab3b5453635ad9895fa9d15fd65866044f23fa0415bfc796e5fd6299"
EXPECTED_N_FEATURES = 25

PREPARED_2025_PATH = SRC_STUDY / "_work" / "prepared_2025.parquet"
TARGET = "bearish_regime_flip_within_300s"

# Established-regime filter, verbatim from
# studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_established_fade_policy.json:12-16
FILT_REGIME_AGE_S_MIN = 120.0
FILT_RUNNING_MFE_ATR_MIN = 1.0
FILT_NEW_PROGRESS_WINDOWS_MIN = 2
FILT_RETAINED_MFE_RATIO_MIN = 0.5
PROGRESS_WINDOW_GAP_NS = 120_000_000_000  # 120s, CODEX_5_X_run_established_fade.py:167-179

CANDIDATE_STEP_S = 5
CANDIDATE_TIMEOUT_S = 1800  # build_weakness_atlas.py:72

RTH_START_MIN = 8 * 60 + 30
RTH_END_MIN = 15 * 60

STOP_ATR_MULT = 1.25
NQ_MULT = 20.0
COST_RT = 10.0

SELECTED_MONTH = "2025-03"
CATALOG_PATH = ROOT / "data" / "catalog" / "NQ_v0_2020_2026"
BAR_1S = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
BAR_1M = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def verify_frozen_model_inputs() -> dict:
    """Blocking gate -- raises if any mismatch (per SPEC.md 'Any mismatch is blocking')."""
    import json
    model_hash = sha256_file(MODEL_PATH)
    if model_hash != EXPECTED_MODEL_SHA256:
        raise RuntimeError(f"MODEL HASH MISMATCH: {model_hash} != {EXPECTED_MODEL_SHA256}")
    fs = json.loads(FEATURE_SETS_PATH.read_text())[MODEL_ID]
    if fs["sha256"] != EXPECTED_FEATURE_LIST_SHA256:
        raise RuntimeError(f"FEATURE LIST HASH MISMATCH: {fs['sha256']} != {EXPECTED_FEATURE_LIST_SHA256}")
    if len(fs["features"]) != EXPECTED_N_FEATURES:
        raise RuntimeError(f"expected {EXPECTED_N_FEATURES} features, got {len(fs['features'])}")
    return {"model_sha256": model_hash, "feature_list": fs["features"], "feature_list_sha256": fs["sha256"]}

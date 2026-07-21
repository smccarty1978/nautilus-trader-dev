"""Shared paths/constants + frozen-model contract gate for the long TOP25
March-2025 NT runtime-parity study.

Everything here is read-only with respect to other studies. The short-side smoke
(`nt_reduced_f3_top25_population_parity_smoke`) is being actively modified by
concurrent work, so its modules are FORKED into this study, never imported --
their source SHAs are recorded in `results/fork_provenance.json`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parents[1]
CONFIG, RESULTS, AUDIT, WORK, TESTS = (
    STUDY / "config", STUDY / "results", STUDY / "audit", STUDY / "_work", STUDY / "tests")
for _p in (CONFIG, RESULTS, AUDIT, WORK, TESTS):
    _p.mkdir(parents=True, exist_ok=True)

# ---- frozen model artifact (freeze_reduced_flip_model_artifacts) ----
MODEL_ID = "long_bullish_flip_top25"
ART = ROOT / "studies" / "freeze_reduced_flip_model_artifacts" / "artifacts" / MODEL_ID
MODEL_PATH = ART / "model.joblib"
FEATURE_ORDER_PATH = ART / "feature_order.csv"
COEFFICIENTS_PATH = ART / "coefficients.csv"
INTERCEPT_PATH = ART / "intercept.json"

EXPECTED_MODEL_SHA256 = "ccad9a9b4441a5891ea61bd263ceaedfead42dcd2d5fb2149cdbf2da9e1cc789"
EXPECTED_FEATURE_ORDER_SHA256 = "d601abe692c78c0471088b41cae1fe80bbb918bbe7e7af067ddb45e7b0ce45bf"
EXPECTED_COEFFICIENTS_SHA256 = "5d128d4f1e59ecceb4e8aa8f8166a6e2cd5979546809fa46078c7b3ff3d71778"
EXPECTED_INTERCEPT_SHA256 = "d5046c8ecb969a1586a984bb00643ab0f9ea478243561a83c6cdc903cb2eac39"
EXPECTED_N_FEATURES = 25

TARGET = "bullish_regime_flip_within_300s"

# ---- population / established-regime filter (identical thresholds to the short
# side; only the EXCURSION DIRECTION is mirrored -- see candidate_tracker_long) ----
FILT_REGIME_AGE_S_MIN = 120.0
FILT_RUNNING_MFE_ATR_MIN = 1.0
FILT_NEW_PROGRESS_WINDOWS_MIN = 2
FILT_RETAINED_MFE_RATIO_MIN = 0.5
PROGRESS_WINDOW_GAP_NS = 120_000_000_000
CANDIDATE_STEP_S = 5
CANDIDATE_TIMEOUT_S = 1800

# This population is prevailing-BEARISH regimes; the counter-regime entry is LONG.
PREVAILING_DIRECTION = -1
ENTRY_DIRECTION = +1

# ---- session (America/Chicago) ----
RTH_START_MIN = 8 * 60 + 30
RTH_END_MIN = 15 * 60 + 15
SESSION_TZ = "America/Chicago"

# ---- simplified management contract (brief) ----
STOP_ATR_MULT = 1.25          # frozen at entry, never reset, never trailed
# Exits: fixed stop OR opposing regime flip. No timeout, no PT, no trailing.

# ---- data ----
CATALOG_PATH = ROOT / "data" / "catalog" / "NQ_v0_2020_2026"
BAR_1S = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
BAR_1M = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
RAW_1S_2025 = ROOT / "data" / "raw" / "NQ_v0_1s_2025.parquet"

# March window (Chicago) + warmup. Candidate emission is gated to MARCH_*;
# bars are loaded from WARMUP_START so rolling/regime state is populated.
WARMUP_START_UTC = "2025-02-01 00:00:00+00:00"
MARCH_START_CHI = "2025-03-01 00:00:00"
MARCH_END_CHI = "2025-04-01 00:00:00"

# ---- tolerances ----
TOL_FEATURE = 1e-9
TOL_LOGIT = 1e-10
TOL_PROBA = 1e-10


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def sha256_list(names) -> str:
    return hashlib.sha256(("\n".join(names) + "\n").encode("utf-8")).hexdigest()


def verify_frozen_model_inputs() -> dict:
    """Blocking gate. Any mismatch raises -- the frozen model must be used
    unmodified, so a drifted artifact must stop the run, not be tolerated."""
    import pandas as pd
    checks = {}
    for label, path, expected in (
        ("model", MODEL_PATH, EXPECTED_MODEL_SHA256),
        ("coefficients", COEFFICIENTS_PATH, EXPECTED_COEFFICIENTS_SHA256),
        ("intercept", INTERCEPT_PATH, EXPECTED_INTERCEPT_SHA256),
    ):
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"{label} sha256 mismatch: {actual} != {expected}")
        checks[f"{label}_sha256"] = actual

    feats = pd.read_csv(FEATURE_ORDER_PATH)["feature_name"].tolist()
    if len(feats) != EXPECTED_N_FEATURES:
        raise RuntimeError(f"expected {EXPECTED_N_FEATURES} features, got {len(feats)}")
    order_sha = sha256_list(feats)
    if order_sha != EXPECTED_FEATURE_ORDER_SHA256:
        raise RuntimeError(f"feature order sha256 mismatch: {order_sha} "
                           f"!= {EXPECTED_FEATURE_ORDER_SHA256}")
    checks["feature_order_sha256"] = order_sha
    checks["feature_order"] = feats
    checks["intercept"] = json.loads(INTERCEPT_PATH.read_text())["intercept"]
    return checks


def is_rth_minute_of_day(minute_of_day: int) -> bool:
    return RTH_START_MIN <= minute_of_day < RTH_END_MIN

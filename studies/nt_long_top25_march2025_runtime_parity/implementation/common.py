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
    """DECISION/FILL session rule (08:30-15:15). Governs the candidate
    population only -- NOT the feature path (see `is_rth_feature_minute`)."""
    return RTH_START_MIN <= minute_of_day < RTH_END_MIN


# ---------------------------------------------------------------------------
# OFFLINE FEATURE-ATTACH CONVENTIONS -- reproduced verbatim, deliberately.
#
# The frozen model was TRAINED on features produced by
# `long_rth_mirrored_surface_top100_training/implementation/attach_features_long.py`.
# That replay carries two conventions that differ from the obvious live reading
# of the data. A live engine that "does the sensible thing" instead does NOT
# reproduce the model's inputs. Both are measured, not assumed -- see SPEC.md.
# ---------------------------------------------------------------------------

NS = 1_000_000_000


def minute_bucket_key(bar_ts_ns: int) -> int:
    """The offline minute bucket: `(ts - 1) // 60s`.

    `attach_features.minute_bucket_key` was written for CLOSE-labelled bars
    (`ts` covers `(ts-1s, ts]`) and is imported verbatim by the long attach --
    but the raw 1s bars it replays are OPEN-labelled (`ts` covers
    `[ts, ts+1s)`). The synthesized "minute closing at m" therefore holds the
    1s bars with `ts in (m-60s, m]`, i.e. it is shifted **+1 second** from the
    true minute `[m-60s, m)`, and its rollover fires at the bar `ts == m+1s`,
    not `ts == m`.

    This is NOT a look-ahead: the newest bar it folds in (`ts == m`) covers
    `[m, m+1s)` and the snapshot that can see it is taken at a snap bar
    `S >= m`, for an observation `O > S >= m`, so `m + 1s <= O`. It is a
    labelling quirk that the live engine must mirror to reproduce the frozen
    features. Measured proof: it reproduces the offline reference's
    `rth_vol_cum` exactly (1180 at 08:30:05 and 5253 at 08:31:05 on
    2025-03-03), where the true-minute reading gives 706 / 5226.

    Consequence: the live 1m bar stream must NOT drive the price/RTH trackers.
    Minute bars are re-aggregated from the 1s stream under this rule.
    """
    return (bar_ts_ns - 1) // (60 * NS)


# The offline attach imports `is_rth` from
# `CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py:146`,
# which ends RTH at 15:00 -- NOT the 15:15 used for decisions/fills above.
# The feature path must use 15:00 or `rth_vol_cum`/`rth_elapsed_seconds` stay
# live-populated for 15 minutes after the offline reference has gone null.
RTH_FEATURE_END_MIN = 15 * 60


def is_rth_feature_minute(minute_of_day: int) -> bool:
    """FEATURE-PATH session rule (08:30-15:00). See `RTH_FEATURE_END_MIN`."""
    return RTH_START_MIN <= minute_of_day < RTH_FEATURE_END_MIN

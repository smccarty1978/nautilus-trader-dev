"""Shared frozen contracts for the FABLE5 specialized W4 study."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS, WORK, AUDIT = STUDY / "results", STUDY / "_work", STUDY / "audit"
MODEL_DIR = WORK / "models"
FREEZE_PATH = STUDY / "input_freeze.json"
MANIFEST_PATH = RESULTS / "run_manifest.json"
MODEL_MANIFEST_PATH = WORK / "frozen_selection_manifest.json"
BUNDLE_PATH = MODEL_DIR / "fable5_specialized_w4_bundle.pkl"
PRE_AUDIT = AUDIT / "pre_execution_audit.md"
PRE_AUTH = AUDIT / "pre_execution_authorization.json"
FIRST_2026_OPEN_PATH = AUDIT / "fable5_first_2026_open.json"

REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
MULTI = ROOT / "studies" / "codex_5_w4_multi_candidate_reentry"
ISOLATION = ROOT / "studies" / "codex_5_w4_fade_confirmation_clock_isolation"
PRIOR_PR = ROOT / "studies" / "codex_5_w4_price_response_delayed_entry"
STREAMING = ROOT / "studies" / "codex_5_w4_streaming_lifecycle"
UPSTREAM_SEQ = ROOT / "studies" / "regime_sequence_chop_context"

for p in (REPAIR, MULTI, UPSTREAM_SEQ):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from CODEX_5_X_common import RAW_1S, sha256_file, year_atlas_path  # noqa: E402
from train_weakness_model import CENTER_FEATS, LOCAL_FEATS, SEQUENCE_FEATS  # noqa: E402

NS = 1_000_000_000
TIMEOUT_NS = 300 * NS
MULTIPLIER, COST = 20.0, 10.0
SEED = 42
BOUNDARY_NS = 1751328000000000000  # 2025-07-01 UTC: H1 train | H2 development
POLICY_A_ID = "POLICY_A_COMBINED_1P25_300S"

ATLAS_FEATURES = list(dict.fromkeys(CENTER_FEATS + SEQUENCE_FEATS + LOCAL_FEATS))
CANDIDATE_FEATURES = ["candidate_seq", "new_progress_windows",
                      "retained_mfe_ratio", "atr_at_checkpoint"]
RAW_FEATURES = ATLAS_FEATURES + CANDIDATE_FEATURES
POOLED_CONTEXT = ["direction_flag", "session_flag"]

RETENTION_BANDS = (0.10, 0.20, 0.30, 0.40, 0.50)
SELECTION_BAND = 0.30
MIN_CELL_POS, MIN_CELL_NEG = 150, 150

STRUCTURES = ("baseline_w4", "A_pooled", "B_side", "C_side_session", "D_hier")
YEAR_COUNTS = {"candidates": {2025: 8682, 2026: 3130},
               "opportunities": {2025: 3530, 2026: 1237},
               "policy_a_trades": {2025: 3246, 2026: 1137}}


def candidate_path(year: int) -> Path:
    return MULTI / "_work" / f"candidates_{year}.parquet"


def score_path(year: int) -> Path:
    return REPAIR / "results" / f"CODEX_5_X_repaired_w4_scores_{year}.parquet"


def frozen_trade_path(year: int) -> Path:
    return REPAIR / "results" / f"CODEX_5_X_established_fade_{year}_trades.parquet"


def dataset_path(year: int) -> Path:
    return WORK / f"dataset_{year}.parquet"


def input_hashes() -> dict:
    return {
        "2025_candidates": sha256_file(candidate_path(2025)),
        "2026_candidates": sha256_file(candidate_path(2026)),
        "2025_atlas": sha256_file(year_atlas_path(2025)),
        "2026_atlas": sha256_file(year_atlas_path(2026)),
        "2025_scores": sha256_file(score_path(2025)),
        "2026_scores": sha256_file(score_path(2026)),
        "2025_raw": sha256_file(RAW_1S[2025]),
        "2026_raw": sha256_file(RAW_1S[2026]),
        "2025_frozen_trades": sha256_file(frozen_trade_path(2025)),
        "2026_frozen_trades": sha256_file(frozen_trade_path(2026)),
        "policy_a_isolation_diffs": sha256_file(
            ISOLATION / "results" / "isolation_trade_diffs.parquet"),
        "multi_candidate_policy_results": sha256_file(
            MULTI / "results" / "multi_candidate_policy_results.parquet"),
        "streaming_policy_results": sha256_file(
            STREAMING / "results" / "streaming_portfolio_policy_results.parquet"),
        "prior_pr_policy_results": sha256_file(
            PRIOR_PR / "results" / "price_response_policy_results.parquet"),
        "upstream_simulate_trade": sha256_file(MULTI / "run_study.py"),
    }


def freeze_inputs_or_verify() -> dict:
    hashes = input_hashes()
    if FREEZE_PATH.exists():
        frozen = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
        if frozen.get("input_sha256") != hashes:
            raise RuntimeError("frozen input dependency mismatch")
        return frozen
    payload = {"status": "FROZEN_BEFORE_ANY_EXECUTION", "input_sha256": hashes,
               "expected_counts": {k: {str(y): v for y, v in d.items()}
                                   for k, d in YEAR_COUNTS.items()},
               "boundary_ns": BOUNDARY_NS}
    FREEZE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def script_sha256(path: Path) -> str:
    return sha256_file(path)


def require_authorization() -> None:
    """Fail closed unless a clean pre-execution audit authorizes this code."""
    import re
    if not PRE_AUDIT.exists() or not PRE_AUTH.exists():
        raise RuntimeError("missing pre-execution audit/authorization")
    text = PRE_AUDIT.read_text(encoding="utf-8")
    if not (re.search(r"^\*\*Status:\*\*\s+\*\*PASS", text, re.MULTILINE)
            and re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$",
                          text, re.MULTILINE)):
        raise RuntimeError("pre-execution audit is not a clean PASS")
    auth = json.loads(PRE_AUTH.read_text(encoding="utf-8"))
    expected = {
        "status": "PASS",
        "audit_sha256": sha256_file(PRE_AUDIT),
        "spec_sha256": sha256_file(STUDY / "SPEC.md"),
        "common_sha256": sha256_file(STUDY / "fable5_common.py"),
        "build_dataset_sha256": sha256_file(STUDY / "build_dataset.py"),
        "train_models_sha256": sha256_file(STUDY / "train_models.py"),
        "replay_selection_sha256": sha256_file(STUDY / "replay_selection.py"),
    }
    if any(auth.get(k) != v for k, v in expected.items()):
        raise RuntimeError("pre-execution authorization is stale")


def require_2026_open_allowed(reason: str) -> None:
    """2026 is sealed until the model-selection manifest is frozen."""
    if not MODEL_MANIFEST_PATH.exists() or not BUNDLE_PATH.exists():
        raise RuntimeError("2026 sealed: frozen selection manifest/bundle missing")
    manifest = json.loads(MODEL_MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN_ON_2025_ONLY":
        raise RuntimeError("2026 sealed: selection manifest not frozen")
    if sha256_file(BUNDLE_PATH) != manifest.get("bundle_sha256"):
        raise RuntimeError("2026 sealed: bundle hash mismatch")
    expected = {"bundle_sha256": manifest["bundle_sha256"],
                "manifest_sha256": sha256_file(MODEL_MANIFEST_PATH)}
    if FIRST_2026_OPEN_PATH.exists():
        ledger = json.loads(FIRST_2026_OPEN_PATH.read_text(encoding="utf-8"))
        if any(ledger.get(k) != v for k, v in expected.items()):
            raise RuntimeError("2026 sealed: first-open ledger mismatch")
    else:
        from datetime import datetime, timezone
        FIRST_2026_OPEN_PATH.write_text(json.dumps({
            "first_open_utc": datetime.now(timezone.utc).isoformat(),
            "reason": reason, **expected}, indent=2), encoding="utf-8")


def load_raw(year: int) -> pd.DataFrame:
    from CODEX_5_X_run_established_fade import validate_raw_bars
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close",
                                                 "volume"])
    validate_raw_bars(raw)
    return raw


def raw_arrays(raw: pd.DataFrame):
    ts = raw.index.view(np.int64)
    return (ts, raw["open"].to_numpy(float), raw["high"].to_numpy(float),
            raw["low"].to_numpy(float))


def touched_stop(direction: int, stop: float, high: float, low: float) -> bool:
    return low <= stop if direction == 1 else high >= stop


def stop_fill(direction: int, stop: float, open_px: float) -> float:
    gap = open_px <= stop if direction == 1 else open_px >= stop
    return open_px if gap else stop


def simulate_trade_arrays(ts: np.ndarray, opens: np.ndarray, highs: np.ndarray,
                          lows: np.ndarray, entry_ts: int, entry: float,
                          direction: int, atr: float, align_ts: int,
                          scheduled_decision: int) -> dict:
    """Array-based port of the frozen Policy A management replay.

    Logic is line-identical to codex_5_w4_multi_candidate_reentry.run_study
    simulate_trade; parity is enforced by tests and the frozen-trade
    reconciliation gate before any training.
    """
    timeout_ts = entry_ts + TIMEOUT_NS
    start = int(np.searchsorted(ts, entry_ts, side="left"))
    scheduled_i = int(np.searchsorted(ts, scheduled_decision, side="left"))
    if start >= len(ts) or int(ts[start]) != entry_ts or scheduled_i >= len(ts):
        raise RuntimeError("invalid entry or scheduled exit boundary")
    scheduled_fill_ts = int(ts[scheduled_i])
    pre_stop = entry - direction * 1.25 * atr
    post_stop = entry - direction * 1.5 * atr
    aligned, timeout_pending = False, False
    exit_ts, exit_px, reason = None, np.nan, None
    for i in range(start, scheduled_i + 1):
        now = int(ts[i])
        if not aligned and now >= align_ts and align_ts <= timeout_ts:
            aligned = True
        if timeout_pending and now > timeout_ts:
            exit_ts, exit_px, reason = now, opens[i], "confirmation_timeout_exit"
            break
        if not aligned and now > timeout_ts:
            exit_ts, exit_px, reason = now, opens[i], "confirmation_timeout_exit"
            break
        if now >= scheduled_fill_ts:
            exit_ts, exit_px, reason = now, opens[i], "original_opposing_flip_exit"
            break
        if not aligned and now >= align_ts:
            aligned = True
        if now == timeout_ts and not aligned:
            timeout_pending = True
        stop = post_stop if aligned else pre_stop
        stop_reason = ("original_stop_after_aligned_flip" if aligned
                       else "preflip_policy_stop")
        if touched_stop(direction, stop, highs[i], lows[i]):
            exit_ts = now
            exit_px = stop_fill(direction, stop, opens[i])
            reason = stop_reason
            break
    if exit_ts is None:
        raise RuntimeError("trade replay ended without exit")
    points = direction * (float(exit_px) - entry)
    return {"entry_fill_ts": entry_ts, "entry_fill_px": entry,
            "timeout_ts": timeout_ts, "reached_aligning_flip": aligned,
            "exit_fill_ts": int(exit_ts), "exit_fill_px": float(exit_px),
            "exit_reason": reason, "gross_pnl_pts": points,
            "gross_pnl_usd": points * MULTIPLIER,
            "net_pnl_usd": points * MULTIPLIER - COST}


def profit_factor(pnl: pd.Series) -> float:
    loss = -pnl[pnl < 0].sum()
    return float(pnl[pnl > 0].sum() / loss) if loss > 0 else np.nan


def drawdown(pnl: pd.Series) -> float:
    equity = np.concatenate(([0.0], pnl.cumsum().to_numpy(float)))
    return float(np.max(np.maximum.accumulate(equity) - equity))


def ensure_dirs() -> None:
    for p in (RESULTS, WORK, AUDIT, MODEL_DIR):
        p.mkdir(parents=True, exist_ok=True)

"""Targeted Mutation Verification Tests for Critical Research Guardrails.
========================================================================

Verifies that mutating the implementation of any of the following failure classes
turns tests RED and blocks execution immediately:
  1. Authorized-year domain symmetry (PARTIAL_AUTHORIZED_DOMAIN_GUARD)
  2. Mixed 1s/1m callback order (Callback Inversion)
  3. ts_init_delta bar-close timing (1s, 1m, 3m, 5m)
  4. Stale audit hash binding (STALE_AUDIT)
  5. Stale validation hash binding (STALE_VALIDATION)
  6. Incomplete terminal promotion evidence (INCOMPLETE_TERMINAL_EVIDENCE)
  7. RTH Chicago session boundary attribution (08:30:00 & 15:15:00 CT)
  8. End-to-end vertical slice lifecycle (VERTICAL_SLICE_CLEAR)
"""

import json
import sys
from pathlib import Path
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtests.nt_runtime.data_plan import resolve_data_plan, UnauthorizedExecutionDomainError
from backtests.nt_runtime.compiled_study_loader import load_compiled_study
from utils.causal_registration import verify_callback_causal_order, sort_coincident_bars_causal
from utils.session_boundaries import (
    is_rth_completed_bar_1m,
    is_rth_completed_bar_1s,
    verify_session_attribution_invariants,
)
from scripts.check_artifact_schema import validate_seal_manifest
from scripts.run_vertical_slice import run_canonical_vertical_slice


# ==============================================================================
# 1. Authorized-Year Domain Symmetry & OOS Guard
# ==============================================================================

def test_authorized_domain_symmetry_passes_clean_code():
    study_dir = REPO_ROOT / "studies" / "Gemini_clean_maturity_flip_rolling_5m_productivity"
    cdata = load_compiled_study(study_dir)
    # 2023 is in train partition -> authorized
    dplan = resolve_data_plan(cdata, start_date="2023-03-03", end_date="2023-03-03", repo_root=REPO_ROOT)
    assert dplan.start_dt is not None


def test_partial_authorized_domain_guard_mutation_blocked():
    study_dir = REPO_ROOT / "studies" / "Gemini_clean_maturity_flip_rolling_5m_productivity"
    cdata = load_compiled_study(study_dir)
    # 2026 is in prohibited partition -> blocked
    with pytest.raises(UnauthorizedExecutionDomainError):
        resolve_data_plan(cdata, start_date="2026-01-01", end_date="2026-01-10", repo_root=REPO_ROOT)


# ==============================================================================
# 2. Mixed 1s/1m Callback Ordering
# ==============================================================================

def test_causal_callback_ordering_passes():
    # 1s bars at T precede 1m bar at T
    events = [
        (1000, "1s"),
        (2000, "1s"),
        (2000, "1m"),  # 1s before 1m at coincident close 2000
    ]
    valid, errors = verify_callback_causal_order(events)
    assert valid is True
    assert errors == []


def test_mixed_timeframe_callback_inversion_mutation_detected():
    # Mutate order: 1m bar at coincident close 2000 processed BEFORE 1s bar at 2000
    mutated_events = [
        (1000, "1s"),
        (2000, "1m"),  # Inversion! 1m processes before coincident 1s
        (2000, "1s"),
    ]
    valid, errors = verify_callback_causal_order(mutated_events)
    assert valid is False
    assert any("Callback order inversion" in e for e in errors)


# ==============================================================================
# 3. Semantic Timestamp & Bar-Close Timing Invariants
# ==============================================================================

from utils.catalog_validator import validate_bar_timestamp_semantics

def test_semantic_timestamp_contract_open_stamped():
    # OPEN_STAMPED bars require ts_init - ts_event == bar_duration_ns
    durations = {
        "1s": 1_000_000_000,
        "1m": 60_000_000_000,
        "3m": 180_000_000_000,
        "5m": 300_000_000_000,
    }

    t0 = 1704470400000000000  # 16:00:00 UTC

    for tf, dur in durations.items():
        events = [t0, t0 + dur]
        inits = [t0 + dur, t0 + 2 * dur]
        valid, errors = validate_bar_timestamp_semantics(events, inits, dur, "OPEN_STAMPED")
        assert valid is True
        assert errors == []


def test_open_stamped_zero_delta_mutation_blocked():
    # Mutating 1s open-stamped bar to delta=0 (lookahead) must be blocked
    t0 = 1704470400000000000
    events = [t0]
    inits = [t0]  # Zero delta on open-stamped bar!
    valid, errors = validate_bar_timestamp_semantics(events, inits, 1_000_000_000, "OPEN_STAMPED")
    assert valid is False
    assert any("Semantic delta mismatch" in e for e in errors)


def test_close_stamped_contract_and_double_shift_mutation_blocked():
    # CLOSE_STAMPED bars require ts_init == ts_event (delta=0)
    t0 = 1704470400000000000
    valid, errors = validate_bar_timestamp_semantics([t0], [t0], 60_000_000_000, "CLOSE_STAMPED")
    assert valid is True

    # Mutating close-stamped bar by adding redundant delta (double-shift) must be blocked
    valid_ds, errors_ds = validate_bar_timestamp_semantics([t0], [t0 + 60_000_000_000], 60_000_000_000, "CLOSE_STAMPED")
    assert valid_ds is False
    assert any("Semantic delta mismatch" in e for e in errors_ds)


def test_causal_inversion_ts_init_before_ts_event_blocked():
    t0 = 1704470400000000000
    valid, errors = validate_bar_timestamp_semantics([t0], [t0 - 1000], 1_000_000_000, "OPEN_STAMPED")
    assert valid is False
    assert any("Causal violation" in e for e in errors)


# ==============================================================================
# 4. Stale Audit & Validation Hash Binding
# ==============================================================================

def test_stale_audit_binding_mutation_blocked(tmp_path):
    p = tmp_path / "promotion_manifest.json"
    manifest_data = {
        "seal_id": "PROMOTION_2026_01",
        "code_sha256": "a" * 64,
        "model_sha256": "b" * 64,
        "feature_list_sha256": "c" * 64,
        "spec_sha256": "d" * 64,
        "validation_report_sha256": "e" * 64,
        "audit_status_sha256": "f" * 64,
        "preflight_sha256": "1" * 64,
        "test_evidence_sha256": "2" * 64,
        "promotion_timestamp": "2026-08-14T17:00:00Z",
        "evidence": {
            "audit_status": {
                "path": "audit/status.json",
                "sha256": "f" * 64,
                "audited_code_sha256": "0" * 64  # Mismatch! Stale code hash
            }
        }
    }
    issues = validate_seal_manifest(manifest_data, p)
    assert any(i.code == "STALE_AUDIT" for i in issues)


def test_stale_validation_binding_mutation_blocked(tmp_path):
    p = tmp_path / "promotion_manifest.json"
    manifest_data = {
        "seal_id": "PROMOTION_2026_01",
        "code_sha256": "a" * 64,
        "model_sha256": "b" * 64,
        "feature_list_sha256": "c" * 64,
        "spec_sha256": "d" * 64,
        "validation_report_sha256": "e" * 64,
        "audit_status_sha256": "f" * 64,
        "preflight_sha256": "1" * 64,
        "test_evidence_sha256": "2" * 64,
        "promotion_timestamp": "2026-08-14T17:00:00Z",
        "evidence": {
            "validation_report": {
                "path": "results/validation_report.json",
                "sha256": "e" * 64,
                "validated_model_sha256": "9" * 64  # Mismatch! Different model hash
            }
        }
    }
    issues = validate_seal_manifest(manifest_data, p)
    assert any(i.code == "STALE_VALIDATION" for i in issues)


def test_incomplete_terminal_evidence_mutation_blocked(tmp_path):
    p = tmp_path / "promotion_manifest.json"
    # Missing preflight_sha256 and test_evidence_sha256
    manifest_data = {
        "seal_id": "PROMOTION_2026_01",
        "code_sha256": "a" * 64,
        "model_sha256": "b" * 64,
        "evidence": {
            "audit_status": {"path": "audit/status.json", "sha256": "f" * 64}
        }
    }
    issues = validate_seal_manifest(manifest_data, p)
    assert any(i.code == "INCOMPLETE_TERMINAL_EVIDENCE" for i in issues)


# ==============================================================================
# 5. RTH Chicago Session Boundary Attribution
# ==============================================================================

def test_session_attribution_boundary_invariants_pass():
    valid, errors = verify_session_attribution_invariants(
        is_rth_completed_bar_1m,
        is_rth_completed_bar_1s,
    )
    assert valid is True
    assert errors == []


def test_mutated_0830_session_boundary_turns_red():
    # Mutate 1m classifier to incorrectly classify 08:30:00 CT close as RTH
    def buggy_1m(ts):
        t = pd.to_datetime(ts).time()
        import datetime
        return t >= datetime.time(8, 30, 0) and t <= datetime.time(15, 15, 0)

    valid, errors = verify_session_attribution_invariants(
        buggy_1m,
        is_rth_completed_bar_1s,
    )
    assert valid is False
    assert any("08:30:00 CT close misclassified as RTH" in e for e in errors)


def test_mutated_1515_session_boundary_turns_red():
    # Mutate 1m classifier to incorrectly classify 15:15:00 CT close as ETH
    def buggy_1m(ts):
        t = pd.to_datetime(ts).time()
        import datetime
        return t > datetime.time(8, 30, 0) and t < datetime.time(15, 15, 0)

    valid, errors = verify_session_attribution_invariants(
        buggy_1m,
        is_rth_completed_bar_1s,
    )
    assert valid is False
    assert any("15:15:00 CT close misclassified as ETH" in e for e in errors)


# ==============================================================================
# 6. End-to-End Vertical Slice
# ==============================================================================

def test_canonical_vertical_slice_passes():
    success, code, report = run_canonical_vertical_slice()
    assert success is True
    assert code == "VERTICAL_SLICE_CLEAR"
    assert len(report["stages_passed"]) == 10

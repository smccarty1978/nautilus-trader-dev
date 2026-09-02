"""Tests for the prepare -> freeze boundary and mutation invariants.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from scripts.tests._study_copy import copy_study_as_fresh_identity
from scripts.resolve_execution_manifest import verify_frozen_execution_identity, PostFreezeMutationError
from scripts.prepare_and_freeze import run_prepare_and_freeze

REPO_ROOT = Path(__file__).resolve().parents[2]
STUDY_DIR = REPO_ROOT / "studies" / "Codex_clean_maturity_flip_rolling_5m_productivity"


def _synthetic_timestamp_contract(symbol: str) -> dict:
    """Explicit evidence fixture for this non-catalog PREPARE boundary test.

    This test exercises freeze mutation detection, not timestamp measurement.  It
    must not turn an absent catalog into assumed production evidence, so the mocked
    compiler dependency carries a complete, unmistakably synthetic passing record.
    """
    return {
        "source": "synthetic_test_fixture",
        "instrument_symbol": symbol.upper(),
        "measured_catalog_rel_path": "synthetic://no-catalog-access",
        "raw_timestamp_semantic": "OPEN_STAMPED",
        "raw_index_field": "ts_event",
        "timezone": "UTC",
        "nautilus_catalog": {
            "ts_event_semantic": "OPEN_STAMPED", "ts_init_semantic": "CLOSE_STAMPED",
            "causal_dispatch_field": "ts_init",
            "empirical_measurement": {"status": "MEASURED", "synthetic_test_only": True,
                "measurements": {f"{symbol.upper()}.XCME-1-SECOND-LAST-SYNTHETIC": {
                    "sample_count": 1, "expected_delta_ns": 1_000_000_000,
                    "observed_deltas_ns": [1_000_000_000], "pass": True}}},
        },
        "causal_rule": "FULL_BAR_OHLCV_AVAILABLE_ONLY_AT_INTERVAL_CLOSE",
    }


def test_prepare_freeze_lifecycle_and_mutations(tmp_path, monkeypatch):
    # Copy study to temp path to create a fresh environment with studies directory
    temp_study = tmp_path / "studies" / "test_freeze_study"
    copy_study_as_fresh_identity(STUDY_DIR, temp_study)

    # Need to update the yaml files inside the temp copy to rename the study
    for yaml_p in (temp_study / "study.yaml", temp_study / "config" / "study.yaml"):
        if yaml_p.exists():
            s_yaml_text = yaml_p.read_text(encoding="utf-8")
            yaml_p.write_text(s_yaml_text.replace("Codex_clean_maturity_flip_rolling_5m_productivity", "test_freeze_study"), encoding="utf-8")

    compiled_study_json = temp_study / "compiled_study.json"
    if compiled_study_json.exists():
        c_json_text = compiled_study_json.read_text(encoding="utf-8")
        compiled_study_json.write_text(c_json_text.replace("Codex_clean_maturity_flip_rolling_5m_productivity", "test_freeze_study"), encoding="utf-8")

    # Update phase0 config study id
    phase0_py = temp_study / "implementation" / "phase0.py"
    phase0_text = phase0_py.read_text(encoding="utf-8")
    phase0_py.write_text(phase0_text.replace("Codex_clean_maturity_flip_rolling_5m_productivity", "test_freeze_study"), encoding="utf-8")

    # 1. Run PREPARE and FREEZE. This is a fresh synthetic identity, so sealed
    # reuse is intentionally unavailable; provide explicit synthetic evidence at
    # the compiler dependency instead of weakening the production timestamp gate.
    monkeypatch.setattr("research.study_types.flip_prediction.compile_timestamp_contract", _synthetic_timestamp_contract)
    run_prepare_and_freeze(temp_study)

    # Verify that freeze manifest was written
    frozen_manifest = temp_study / "audit" / "frozen_execution_manifest.json"
    assert frozen_manifest.is_file()

    with open(frozen_manifest, "r", encoding="utf-8") as f:
        fdata = json.load(f)
    assert fdata["study_id"] == "test_freeze_study"
    assert fdata["frozen_execution_composite_sha256"]

    # 2. Verify frozen identity (no mutation)
    verify_frozen_execution_identity(temp_study, REPO_ROOT)  # Should not raise

    # 3. Mutation test 1: Modify collector.py after freeze
    collector_py = temp_study / "implementation" / "collector.py"
    original_collector = collector_py.read_text(encoding="utf-8")

    collector_py.write_text(original_collector + "\n# Modified after freeze\n", encoding="utf-8")
    with pytest.raises(PostFreezeMutationError, match="POST_FREEZE_MUTATION"):
        verify_frozen_execution_identity(temp_study, REPO_ROOT)

    # Revert collector change
    collector_py.write_text(original_collector, encoding="utf-8")
    verify_frozen_execution_identity(temp_study, REPO_ROOT)  # Should pass again

    # 4. Mutation test 2: Regenerate phase0_source_manifest.json after freeze
    phase0_manifest = temp_study / "artifacts" / "phase0_source_manifest.json"
    original_manifest = phase0_manifest.read_text(encoding="utf-8")

    # Simulate a regeneration/change
    phase0_manifest.write_text(original_manifest + "\n", encoding="utf-8")
    with pytest.raises(PostFreezeMutationError, match="POST_FREEZE_MUTATION"):
        verify_frozen_execution_identity(temp_study, REPO_ROOT)

    # Revert manifest change
    phase0_manifest.write_text(original_manifest, encoding="utf-8")
    verify_frozen_execution_identity(temp_study, REPO_ROOT)  # Should pass again

    # 5. Allowed mutations: preflight.json, audit reports, seal artifacts
    # Modify/write preflight.json
    preflight_json = temp_study / "audit" / "preflight.json"
    preflight_json.parent.mkdir(parents=True, exist_ok=True)
    preflight_json.write_text('{"status": "CLEAR"}', encoding="utf-8")

    # Modify/write audit report
    audit_report = temp_study / "audit" / "pass_99.md"
    audit_report.write_text("# Causal pass 99\n", encoding="utf-8")

    # Modify/write seal
    seal_json = temp_study / "artifacts" / "preexec_audit_seal.json"
    seal_json.write_text('{"seal_status": "LOCKED"}', encoding="utf-8")

    # Verify these allowed mutations do NOT raise PostFreezeMutationError
    verify_frozen_execution_identity(temp_study, REPO_ROOT)  # Should pass

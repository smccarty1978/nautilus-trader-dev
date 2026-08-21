"""Tests for artifact and seal validation in scripts/check_artifact_schema.py.
==========================================================================
"""

import json
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_artifact_schema import (
    validate_status_json,
    validate_audit_packet,
    validate_seal_manifest,
    scan_artifacts,
)


def test_valid_status_json(tmp_path):
    data = {
        "study": "test_study",
        "date": "2026-08-14",
        "critical": 0,
        "warning": 0,
        "verdict": "PASS"
    }
    p = tmp_path / "status.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    issues = validate_status_json(data, p)
    assert issues == []


def test_invalid_status_json_missing_verdict(tmp_path):
    data = {
        "study": "test_study",
        "date": "2026-08-14",
        "critical": 0,
        "warning": 0
    }
    p = tmp_path / "status.json"
    issues = validate_status_json(data, p)
    assert any(i.code == "STATUS_SCHEMA" for i in issues)


def test_valid_audit_packet(tmp_path):
    data = {
        "study": "test_study",
        "code_files": [
            {"file": "run_study.py", "sha256": "a" * 64}
        ]
    }
    p = tmp_path / "audit_packet.json"
    issues = validate_audit_packet(data, p)
    assert issues == []


def test_invalid_audit_packet_hash(tmp_path):
    data = {
        "study": "test_study",
        "code_files": [
            {"file": "run_study.py", "sha256": "short_invalid_hash"}
        ]
    }
    p = tmp_path / "audit_packet.json"
    issues = validate_audit_packet(data, p)
    assert any(i.code == "PACKET_INVALID_HASH" for i in issues)


def test_self_referential_seal_rejected(tmp_path):
    p = tmp_path / "seal_manifest.json"
    data = {
        "seal_id": "SEAL_2026_01",
        "evidence": {
            "self": {"path": str(p), "sha256": "b" * 64}
        }
    }
    issues = validate_seal_manifest(data, p)
    assert any(i.code == "SELF_REFERENTIAL_SEAL" for i in issues)


def test_seal_dag_cycle_rejected(tmp_path):
    p = tmp_path / "seal_manifest.json"
    data = {
        "seal_id": "SEAL_2026_01",
        "evidence": {
            "audit": {"path": "audit/status.json", "sha256": "c" * 64}
        },
        "dependencies": ["SEAL_2026_01"]
    }
    issues = validate_seal_manifest(data, p)
    assert any(i.code == "SEAL_DAG_CYCLE" for i in issues)

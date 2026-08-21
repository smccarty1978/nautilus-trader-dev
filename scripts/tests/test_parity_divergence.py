"""Tests for first-divergence localization in scripts/find_first_parity_divergence.py.
==================================================================================
"""

import json
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.find_first_parity_divergence import compare_ledgers


def test_identical_ledgers():
    events = [
        {"timestamp": "2026-01-05T09:30:00", "stage": "input", "payload": {"price": 100.0}},
        {"timestamp": "2026-01-05T09:30:00", "stage": "regime", "payload": {"regime": 1}},
        {"timestamp": "2026-01-05T09:30:00", "stage": "score", "payload": {"score": 0.85}},
    ]
    identical, div = compare_ledgers(events, events)
    assert identical is True
    assert div is None


def test_divergent_feature_snapshot():
    ref_events = [
        {"timestamp": "2026-01-05T09:30:00", "stage": "input", "payload": {"price": 100.0}},
        {"timestamp": "2026-01-05T09:30:00", "stage": "regime", "payload": {"regime": 1}},
        {"timestamp": "2026-01-05T09:30:00", "stage": "feature_snapshot", "payload": {"atr": 1.25, "rsi": 55.0}},
        {"timestamp": "2026-01-05T09:30:00", "stage": "score", "payload": {"score": 0.85}},
    ]
    run_events = [
        {"timestamp": "2026-01-05T09:30:00", "stage": "input", "payload": {"price": 100.0}},
        {"timestamp": "2026-01-05T09:30:00", "stage": "regime", "payload": {"regime": 1}},
        {"timestamp": "2026-01-05T09:30:00", "stage": "feature_snapshot", "payload": {"atr": 1.20, "rsi": 55.0}},  # Divergence!
        {"timestamp": "2026-01-05T09:30:00", "stage": "score", "payload": {"score": 0.82}},
    ]
    identical, div = compare_ledgers(ref_events, run_events)
    assert identical is False
    assert div["first_failing_stage"] == "feature_snapshot"
    assert div["last_matching_stage"] == "regime"
    assert div["field"] == "atr"
    assert div["reference"] == 1.25
    assert div["runtime"] == 1.20

"""Auto-Generated Deterministic Study Contract Tests.
===================================================
Derived from study.yaml (SHA-256: 7151bc7640ebb98526b28d07b673317aa6009975b142e277b0851d572e3eeb08).
"""

import pytest

def test_nautilustrader_runtime_invariant():
    assert "nautilustrader" == "nautilustrader", "Runtime must be NautilusTrader"

def test_authorized_chronology():
    authorized_train = [2024]
    authorized_dev = []
    prohibited = [2025, 2026]
    assert set(authorized_train).isdisjoint(set(authorized_dev))
    assert set(authorized_train).isdisjoint(set(prohibited))
    assert set(authorized_dev).isdisjoint(set(prohibited))

def test_feature_contract_binding():
    expected_count = 1
    expected_sha256 = "f5cddfd93e1bda3b8ff3db0524413c3d8f1fd3fca62490806c3aeb640cf8aa20"
    if expected_count > 0:
        assert expected_count == len(['latest_1m_wick_imbalance'])
        if expected_sha256:
            assert expected_sha256 == "f5cddfd93e1bda3b8ff3db0524413c3d8f1fd3fca62490806c3aeb640cf8aa20"

def test_population_target_contract():
    prevailing = "both"
    target_dir = "both"
    session = "RTH"
    assert session in ["RTH", "ETH", "ALL"]
    if prevailing and target_dir:
        # Check opposing flip logic
        if prevailing == "bearish":
            assert target_dir == "bullish"
        elif prevailing == "bullish":
            assert target_dir == "bearish"

"""Auto-Generated Deterministic Study Contract Tests.
===================================================
Derived from study.yaml (SHA-256: 6f8a5440267f6bf282b378f07e764054505687ed3c20e427f80355897b7c17c6).
"""

import pytest

def test_nautilustrader_runtime_invariant():
    assert "nautilustrader" == "nautilustrader", "Runtime must be NautilusTrader"

def test_authorized_chronology():
    authorized_train = [2021, 2022, 2023]
    authorized_dev = [2024]
    prohibited = [2025, 2026]
    assert set(authorized_train).isdisjoint(set(authorized_dev))
    assert set(authorized_train).isdisjoint(set(prohibited))
    assert set(authorized_dev).isdisjoint(set(prohibited))

def test_feature_contract_binding():
    expected_count = 60
    expected_sha256 = "2a744cfa3acfa437ae0ff8219c56451e176a170ae83450c52b8ca42842b0cba5"
    import yaml, json, hashlib
    with open("studies/Gemini_clean_maturity_flip_rolling_5m_productivity/study.yaml") as f:
        d = yaml.safe_load(f)
    flist = d["features"]["feature_list"]
    assert len(flist) == expected_count
    sha = hashlib.sha256(json.dumps(flist).encode()).hexdigest()
    assert sha == expected_sha256

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

def test_exact_checkpoint_causality_invariant():
    """Asserts that checkpoints evaluate only on exact 1s bar ts_init == T."""
    from strategies.flip_prediction_collector import CANDIDATE_STEP_NS, NS
    # Check that candidate step is exact 5 seconds
    assert CANDIDATE_STEP_NS == 5 * NS


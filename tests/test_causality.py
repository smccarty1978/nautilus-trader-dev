import pytest
import numpy as np
from utils.causality import (
    latest_completed_bar_index,
    htf_close_times_from_opens,
    FeatureTimestampAudit,
    CausalityViolation,
)

def test_latest_completed_bar_index():
    # close_times: 10, 20, 30, 40
    close_times = np.array([10, 20, 30, 40])
    
    # decision_ts = 5: before first close, should return -1
    assert latest_completed_bar_index(close_times, 5) == -1
    
    # decision_ts = 10: exactly at first close, should return index 0
    assert latest_completed_bar_index(close_times, 10) == 0
    
    # decision_ts = 15: between first and second close, should return index 0
    assert latest_completed_bar_index(close_times, 15) == 0
    
    # decision_ts = 20: exactly at second close, should return index 1
    assert latest_completed_bar_index(close_times, 20) == 1
    
    # decision_ts = 45: after last close, should return index 3
    assert latest_completed_bar_index(close_times, 45) == 3

def test_htf_close_times_from_opens():
    open_times = np.array([1000, 2000, 3000])
    bucket_size = 60
    expected_closes = np.array([1060, 2060, 3060])
    
    np.testing.assert_array_equal(
        htf_close_times_from_opens(open_times, bucket_size),
        expected_closes
    )

def test_feature_timestamp_audit_causal():
    # close_ts (20) <= decision_ts (20) -> causal (True)
    audit = FeatureTimestampAudit(
        feature_name="test_feature",
        feature_source_tf="5m",
        feature_bar_open_ts=15,
        feature_bar_close_ts=20,
        decision_ts=20
    )
    assert audit.causal is True
    # Should not raise exception
    audit.assert_causal()
    
    # close_ts (20) <= decision_ts (25) -> causal (True)
    audit2 = FeatureTimestampAudit(
        feature_name="test_feature",
        feature_source_tf="5m",
        feature_bar_open_ts=15,
        feature_bar_close_ts=20,
        decision_ts=25
    )
    assert audit2.causal is True
    audit2.assert_causal()

def test_feature_timestamp_audit_non_causal():
    # close_ts (20) > decision_ts (19) -> non-causal (False)
    audit = FeatureTimestampAudit(
        feature_name="test_feature",
        feature_source_tf="5m",
        feature_bar_open_ts=15,
        feature_bar_close_ts=20,
        decision_ts=19
    )
    assert audit.causal is False
    with pytest.raises(CausalityViolation) as excinfo:
        audit.assert_causal()
    assert "NON-CAUSAL feature read" in str(excinfo.value)
    assert "bar_close_ts=20" in str(excinfo.value)
    assert "decision_ts=19" in str(excinfo.value)

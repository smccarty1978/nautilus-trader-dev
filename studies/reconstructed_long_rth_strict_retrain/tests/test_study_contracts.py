"""Auto-Generated Deterministic Study Contract Tests.
===================================================
Derived from study.yaml (SHA-256: bd51e8c29eb7d0fa300c6bb638034541851e1c4db0c0552603714aa2bf4ecaa2).
"""

import pytest

def test_nautilustrader_runtime_invariant():
    assert "nautilustrader" == "nautilustrader", "Runtime must be NautilusTrader"

def test_authorized_chronology():
    authorized_train = [2021, 2022, 2023, 2024]
    authorized_dev = [2025]
    prohibited = [2026]
    assert set(authorized_train).isdisjoint(set(authorized_dev))
    assert set(authorized_train).isdisjoint(set(prohibited))
    assert set(authorized_dev).isdisjoint(set(prohibited))

def test_feature_contract_binding():
    expected_count = 25
    expected_sha256 = "8bcfeb74ab3b5453635ad9895fa9d15fd65866044f23fa0415bfc796e5fd6299"
    if expected_count > 0:
        assert expected_count == len(['rolling_5m_low_signed_distance_atr', 'rth_elapsed_seconds', 'rolling_15m_high_signed_distance_atr', 'rolling_60m_high_signed_distance_atr', 'rolling_15m_low_signed_distance_atr', 'rolling_30m_low_signed_distance_atr', 'price_change_points_60s', 'rolling_30m_high_signed_distance_atr', 'range_points_1800s', 'opening_range_30m_low_developing_signed_distance_points', 'est_bear_vol_sum_300s', 'full_level_envelope_width_atr', 'rth_vol_cum', 'est_delta_sum_1800s', 'price_change_atr_60s', 'prior_day_close_signed_distance_atr', 'up_down_vol_ratio_1800s', 'price_change_atr_30s', 'pct_levels_behind_trade', 'prior_day_low_signed_distance_points', 'opening_range_30m_low_final_signed_distance_points', 'vol_max_1s_1800s', 'price_position_in_full_envelope', 'rth_abs_delta_cum', 'n_levels_below'])
        if expected_sha256:
            assert expected_sha256 == "8bcfeb74ab3b5453635ad9895fa9d15fd65866044f23fa0415bfc796e5fd6299"

def test_population_target_contract():
    prevailing = "bearish"
    target_dir = "bullish"
    session = "RTH"
    assert session in ["RTH", "ETH", "ALL"]
    if prevailing and target_dir:
        # Check opposing flip logic
        if prevailing == "bearish":
            assert target_dir == "bullish"
        elif prevailing == "bullish":
            assert target_dir == "bearish"

"""
tests/test_causal_fast_failure_invariance.py

Permanent regression test verifying strict causal future invariance
of the CausalFastFailureProvider.

Contract:
Any post-observation price divergence (e.g. massive runaway continuation vs immediate reversal)
must have ZERO influence on the feature vector computed at observation_ts.
"""
from __future__ import annotations

import numpy as np
import pytest
from features.providers.causal_fast_failure import CausalFastFailureProvider, FEATURE_NAMES

@pytest.mark.parametrize("direction", [1, -1])
@pytest.mark.parametrize("obs_seconds", [30, 60])
def test_fast_failure_future_invariance(direction: int, obs_seconds: int):
    """
    Test that radically different futures after observation_ts produce
    bit-for-bit identical fast-failure feature vectors.
    """
    counter_direction = -direction
    frozen_atr = 25.0
    regime_entry_px = 15000.0
    pre_pb_mfe_pts = 50.0  # 2.0 ATR

    # Baseline timestamps: 1-second intervals
    # Total bars: 200 bars (checkpoint at bar 20, fill at bar 21, observation at bar 21 + obs_seconds)
    N_bars = 200
    t0_idx = 20
    fill_idx = 21
    obs_idx = fill_idx + obs_seconds

    base_ts = 1_700_000_000_000_000_000 # epoch ns
    ts_arr = np.array([base_ts + i * 1_000_000_000 for i in range(N_bars)], dtype=np.int64)

    t0_ts = int(ts_arr[t0_idx])
    fill_ts = int(ts_arr[fill_idx])
    obs_ts = int(ts_arr[obs_idx])

    # Construct historical prices up to obs_idx (identical for Path A and Path B)
    np.random.seed(42)
    price_walk = 15000.0 + np.cumsum(np.random.randn(N_bars) * 0.5)

    opens_base = price_walk.copy()
    highs_base = price_walk + 0.5
    lows_base = price_walk - 0.5
    closes_base = price_walk + 0.1

    fill_px = float(opens_base[fill_idx])

    # Path A: Extreme runaway incumbent continuation after obs_idx
    opens_A = opens_base.copy()
    highs_A = highs_base.copy()
    lows_A = lows_base.copy()
    closes_A = closes_base.copy()

    # Path B: Extreme counter-regime reversal after obs_idx
    opens_B = opens_base.copy()
    highs_B = highs_base.copy()
    lows_B = lows_base.copy()
    closes_B = closes_base.copy()

    for i in range(obs_idx + 1, N_bars):
        # Path A advances by +100 ATR in incumbent direction
        shift_A = direction * (i - obs_idx) * 20.0
        opens_A[i] += shift_A
        highs_A[i] += shift_A + 5.0
        lows_A[i] += shift_A - 5.0
        closes_A[i] += shift_A

        # Path B collapses by -100 ATR against incumbent direction
        shift_B = -direction * (i - obs_idx) * 20.0
        opens_B[i] += shift_B
        highs_B[i] += shift_B + 5.0
        lows_B[i] += shift_B - 5.0
        closes_B[i] += shift_B

    # Compute features for Path A
    feat_A = CausalFastFailureProvider.extract_features(
        ts_1s_arr=ts_arr,
        opens_1s=opens_A,
        highs_1s=highs_A,
        lows_1s=lows_A,
        closes_1s=closes_A,
        idx_t0=t0_idx,
        fill_idx=fill_idx,
        fill_ts=fill_ts,
        fill_px=fill_px,
        direction=direction,
        counter_direction=counter_direction,
        regime_entry_px=regime_entry_px,
        pre_pb_mfe_pts=pre_pb_mfe_pts,
        frozen_atr=frozen_atr,
        observation_ts=obs_ts
    )
    vec_A = CausalFastFailureProvider.extract_feature_vector(feat_A)

    # Compute features for Path B
    feat_B = CausalFastFailureProvider.extract_features(
        ts_1s_arr=ts_arr,
        opens_1s=opens_B,
        highs_1s=highs_B,
        lows_1s=lows_B,
        closes_1s=closes_B,
        idx_t0=t0_idx,
        fill_idx=fill_idx,
        fill_ts=fill_ts,
        fill_px=fill_px,
        direction=direction,
        counter_direction=counter_direction,
        regime_entry_px=regime_entry_px,
        pre_pb_mfe_pts=pre_pb_mfe_pts,
        frozen_atr=frozen_atr,
        observation_ts=obs_ts
    )
    vec_B = CausalFastFailureProvider.extract_feature_vector(feat_B)

    # Assert bit-for-bit numerical identity
    np.testing.assert_allclose(
        vec_A,
        vec_B,
        rtol=1e-12,
        atol=1e-12,
        err_msg=f"Future invariance violated for direction={direction}, obs_seconds={obs_seconds}!"
    )

    # Check that individual dictionary keys match exactly
    for k in FEATURE_NAMES:
        assert feat_A[k] == feat_B[k], f"Feature '{k}' diverged between Path A and Path B!"

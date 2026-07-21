import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from studies.regime_sequence_chop_context.reproduce_regimes import RegimeEngine

def test_regime_engine_basic():
    engine = RegimeEngine()
    
    # Update with some values
    # Initial warm-up
    for i in range(15):
        h, l, c = 100.0 + i, 90.0 + i, 95.0 + i
        ema3_h, ema9_h, ema3_l, ema9_l, atr, regime, bars = engine.update(h, l, c)
        
    # Check that after 14 bars, ATR is not nan
    assert not np.isnan(atr)
    assert regime in (-1, 0, 1)
    
    # Try a massive upward move to trigger long regime
    ema3_h, ema9_h, ema3_l, ema9_l, atr, regime, bars = engine.update(200.0, 190.0, 195.0)
    assert regime == 1
    assert bars == 1
    
    # Next bar is also upward -> count increases
    ema3_h, ema9_h, ema3_l, ema9_l, atr, regime, bars = engine.update(201.0, 191.0, 196.0)
    assert regime == 1
    assert bars == 2
    
    # Try a massive downward move to flip to short
    ema3_h, ema9_h, ema3_l, ema9_l, atr, regime, bars = engine.update(50.0, 40.0, 45.0)
    assert regime == -1
    assert bars == 1

def test_rolling_slope():
    from studies.regime_sequence_chop_context.build_median_centers import compute_rolling_slopes
    
    # Linear series: slope is exactly 2.0
    y = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
    sl = compute_rolling_slopes(y, 3)
    
    # For window=3, first 2 are nan
    assert np.isnan(sl.iloc[0])
    assert np.isnan(sl.iloc[1])
    # The rest are exactly 2.0
    assert pytest.approx(sl.iloc[2], 1e-6) == 2.0
    assert pytest.approx(sl.iloc[3], 1e-6) == 2.0
    assert pytest.approx(sl.iloc[4], 1e-6) == 2.0

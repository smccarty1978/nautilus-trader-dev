import unittest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.visualizer import aggregate_bars, compute_indicators

class TestVisualizerHelpers(unittest.TestCase):
    def setUp(self):
        # Create a mock dataframe with 15 seconds of 1s bar data
        data = []
        base_time = 1700000000000000000 # nanoseconds epoch
        
        # 15 seconds
        for i in range(15):
            data.append({
                "timestamp": base_time + (i * 1_000_000_000),
                "open": 100.0 + i,
                "high": 105.0 + i,
                "low": 95.0 + i,
                "close": 101.0 + i,
                "volume": 10
            })
        self.df_1s = pd.DataFrame(data)

    def test_aggregate_bars_5s(self):
        # Aggregate 15 1s bars into 5s bars
        df_5s = aggregate_bars(self.df_1s, "5s")
        
        # We expect 3 bars (15 seconds / 5s)
        self.assertEqual(len(df_5s), 3)
        
        # Check first bar attributes
        # open should be open of first bar (100.0)
        self.assertEqual(df_5s.iloc[0]["open"], 100.0)
        # high should be max high of first 5 bars (105.0 + 4 = 109.0)
        self.assertEqual(df_5s.iloc[0]["high"], 109.0)
        # low should be min low of first 5 bars (95.0 + 0 = 95.0)
        self.assertEqual(df_5s.iloc[0]["low"], 95.0)
        # close should be close of 5th bar (101.0 + 4 = 105.0)
        self.assertEqual(df_5s.iloc[0]["close"], 105.0)
        # volume should be sum of volume (5 * 10 = 50)
        self.assertEqual(df_5s.iloc[0]["volume"], 50)

    def test_compute_indicators(self):
        # We need a longer dataframe to test indicators
        data = []
        base_time = 1700000000000000000
        for i in range(50):
            # Bullish trend close > EMA bands
            data.append({
                "timestamp": base_time + (i * 5_000_000_000),
                "open": 100.0 + i,
                "high": 102.0 + i,
                "low": 98.0 + i,
                "close": 102.0 + i,
                "volume": 10
            })
        df = pd.DataFrame(data)
        indicators = compute_indicators(df)
        
        # Verify indicators were computed
        self.assertIn("short_ema_high", indicators)
        self.assertIn("short_ema_low", indicators)
        self.assertIn("short_ema_close", indicators)
        self.assertIn("long_ema_high", indicators)
        self.assertIn("long_ema_low", indicators)
        self.assertIn("regime", indicators)
        
        # Check list length (should equal dataframe length)
        self.assertEqual(len(indicators["regime"]), len(df))
        
        # Since close > high EMA, regime should eventually warm up and switch to bullish (1)
        # Check last regime value
        self.assertEqual(indicators["regime"][-1]["value"], 1)

if __name__ == "__main__":
    unittest.main()

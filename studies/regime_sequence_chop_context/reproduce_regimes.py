import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional

class RegimeEngine:
    """EMA3/EMA9 regime engine matching collectors/collector_v2/regime_engine.py.
    
    Tracks:
      - ema3_h, ema9_h, ema3_l, ema9_l
      - Wilder ATR(14)
      - regime (+1 / -1 / 0)
      - bars_in_regime
    """
    ALPHA3 = 0.5   # 2.0 / (3 + 1)
    ALPHA9 = 0.2   # 2.0 / (9 + 1)
    ATR_P = 14

    def __init__(self) -> None:
        self.ema3_h: Optional[float] = None
        self.ema9_h: Optional[float] = None
        self.ema3_l: Optional[float] = None
        self.ema9_l: Optional[float] = None
        self.prev_c: Optional[float] = None
        self.atr_warmup: list[float] = []
        self.atr: Optional[float] = None
        self.regime: int = 0
        self.bars_in_regime: int = 0

    def update(self, h: float, l: float, c: float) -> tuple[float, float, float, float, float, int, int]:
        if self.ema3_h is None:
            self.ema3_h = h
            self.ema9_h = h
            self.ema3_l = l
            self.ema9_l = l
        else:
            self.ema3_h = self.ALPHA3 * h + (1 - self.ALPHA3) * self.ema3_h
            self.ema9_h = self.ALPHA9 * h + (1 - self.ALPHA9) * self.ema9_h
            self.ema3_l = self.ALPHA3 * l + (1 - self.ALPHA3) * self.ema3_l
            self.ema9_l = self.ALPHA9 * l + (1 - self.ALPHA9) * self.ema9_l

        if self.prev_c is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - self.prev_c), abs(l - self.prev_c))
        self.prev_c = c

        if self.atr is None:
            self.atr_warmup.append(tr)
            if len(self.atr_warmup) == self.ATR_P:
                self.atr = sum(self.atr_warmup) / self.ATR_P
                self.atr_warmup = []
        else:
            self.atr = (self.atr * (self.ATR_P - 1) + tr) / self.ATR_P

        new = self.regime
        if self.ema3_h is not None and self.ema9_h is not None and c > self.ema3_h and c > self.ema9_h:
            new = 1
        elif self.ema3_l is not None and self.ema9_l is not None and c < self.ema3_l and c < self.ema9_l:
            new = -1

        if new == 0:
            pass
        elif new != self.regime:
            self.bars_in_regime = 1
            self.regime = new
        else:
            self.bars_in_regime += 1

        return (
            self.ema3_h,
            self.ema9_h,
            self.ema3_l,
            self.ema9_l,
            self.atr if self.atr is not None else float("nan"),
            self.regime,
            self.bars_in_regime
        )


def aggregate_and_run_regimes(df_1s: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Aggregates 1s bars to the specified timeframe and runs the regime engine.
    
    Timeframe values: '1m', '5m', '15m', '30m', '60m'.
    """
    tf_ns = {
        "1m": 60 * 1_000_000_000,
        "5m": 5 * 60 * 1_000_000_000,
        "15m": 15 * 60 * 1_000_000_000,
        "30m": 30 * 60 * 1_000_000_000,
        "60m": 60 * 60 * 1_000_000_000,
    }
    bucket_size = tf_ns[timeframe]
    ts_ns = df_1s.index.astype(np.int64)
    df_1s = df_1s.copy()
    df_1s['bucket_id'] = ts_ns // bucket_size

    # Aggregate
    agg = df_1s.groupby('bucket_id').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    })
    
    # Calculate open and close timestamps
    agg['open_ts'] = agg.index * bucket_size
    agg['close_ts'] = (agg.index + 1) * bucket_size

    # Run engine sequentially
    engine = RegimeEngine()
    results = []
    for _, r in agg.iterrows():
        res = engine.update(r['high'], r['low'], r['close'])
        results.append(res)

    res_df = pd.DataFrame(results, columns=[
        'ema3_h', 'ema9_h', 'ema3_l', 'ema9_l', 'atr', 'regime', 'bars_in_regime'
    ], index=agg.index)

    return pd.concat([agg, res_df], axis=1)

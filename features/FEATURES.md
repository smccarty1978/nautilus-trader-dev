# Feature Library Documentation

Comprehensive feature extraction for ML training using NautilusTrader indicators.

## Feature Count: 70+

All features computed bar-by-bar with **no look-ahead bias**.

---

## TREND / MOVING AVERAGE (19 features)

### EMA Distance from Price (6)
| Feature | Description | Units |
|---------|-------------|-------|
| `ema_3_dist_atr` | Price distance from EMA(3) | ATR |
| `ema_5_dist_atr` | Price distance from EMA(5) | ATR |
| `ema_9_dist_atr` | Price distance from EMA(9) | ATR |
| `ema_13_dist_atr` | Price distance from EMA(13) | ATR |
| `ema_21_dist_atr` | Price distance from EMA(21) | ATR |
| `ema_50_dist_atr` | Price distance from EMA(50) | ATR |

### EMA Slopes (6)
| Feature | Description | Units |
|---------|-------------|-------|
| `ema_3_slope` | Slope of EMA(3) over 5 bars | ATR/bar |
| `ema_5_slope` | Slope of EMA(5) over 5 bars | ATR/bar |
| `ema_9_slope` | Slope of EMA(9) over 5 bars | ATR/bar |
| `ema_13_slope` | Slope of EMA(13) over 5 bars | ATR/bar |
| `ema_21_slope` | Slope of EMA(21) over 5 bars | ATR/bar |
| `ema_50_slope` | Slope of EMA(50) over 5 bars | ATR/bar |

### EMA Crossover States (3)
| Feature | Description | Values |
|---------|-------------|--------|
| `ema_3_9_cross` | EMA(3) vs EMA(9) | +1 (above), -1 (below) |
| `ema_9_21_cross` | EMA(9) vs EMA(21) | +1 (above), -1 (below) |
| `ema_21_50_cross` | EMA(21) vs EMA(50) | +1 (above), -1 (below) |

### SMA Distance (3)
| Feature | Description | Units |
|---------|-------------|-------|
| `sma_10_dist_atr` | Price distance from SMA(10) | ATR |
| `sma_20_dist_atr` | Price distance from SMA(20) | ATR |
| `sma_50_dist_atr` | Price distance from SMA(50) | ATR |

### Other Trend (4)
| Feature | Description | Units |
|---------|-------------|-------|
| `hma_dist_atr` | Price distance from Hull MA(20) | ATR |
| `macd` | MACD(12,26) value | ATR |
| `linreg_slope` | Linear Regression(20) slope | ATR |
| `linreg_r2` | Linear Regression R² | 0-1 |

---

## MOMENTUM (21 features)

### RSI (4)
| Feature | Description | Range |
|---------|-------------|-------|
| `rsi_7` | RSI(7) - fast | 0-100 |
| `rsi_14` | RSI(14) - standard | 0-100 |
| `rsi_21` | RSI(21) - slow | 0-100 |
| `rsi_14_zone` | RSI(14) zone | -1 (OS), 0 (neutral), +1 (OB) |

### Stochastics (3)
| Feature | Description | Range |
|---------|-------------|-------|
| `stoch_k` | Stochastic %K(14) | 0-100 |
| `stoch_d` | Stochastic %D(3) | 0-100 |
| `stoch_cross` | %K vs %D position | +1 (K>D), -1 (K<D) |

### Oscillators (3)
| Feature | Description | Range |
|---------|-------------|-------|
| `cci` | CCI(20) | Unbounded |
| `cmo` | Chande Momentum(14) | -100 to +100 |
| `efficiency_ratio` | Efficiency Ratio(10) | 0-1 |

### Rate of Change (3)
| Feature | Description | Range |
|---------|-------------|-------|
| `roc_5` | ROC(5) | % |
| `roc_10` | ROC(10) | % |
| `roc_20` | ROC(20) | % |

### Aroon (3)
| Feature | Description | Range |
|---------|-------------|-------|
| `aroon_up` | Aroon Up(25) | 0-100 |
| `aroon_down` | Aroon Down(25) | 0-100 |
| `aroon_osc` | Aroon Oscillator | -100 to +100 |

### ADX / Directional Movement (4)
| Feature | Description | Range |
|---------|-------------|-------|
| `adx` | ADX(14) - trend strength | 0-100 |
| `di_plus` | +DI(14) | 0-100 |
| `di_minus` | -DI(14) | 0-100 |
| `di_diff` | +DI - (-DI) | -100 to +100 |

---

## VOLATILITY (12 features)

### ATR (3)
| Feature | Description | Units |
|---------|-------------|-------|
| `atr_14` | ATR(14) - standard | Price |
| `atr_50` | ATR(50) - medium | Price |
| `atr_200` | ATR(200) - long | Price |

### ATR Ratios (3)
| Feature | Description | Interpretation |
|---------|-------------|----------------|
| `atr_ratio_14_50` | ATR(14)/ATR(50) | >1 = expanding vol |
| `atr_ratio_14_200` | ATR(14)/ATR(200) | >1 = expanding vol |
| `vol_ratio` | Built-in Volatility Ratio | >1 = expanding |

### Bollinger Bands (2)
| Feature | Description | Units |
|---------|-------------|-------|
| `bb_width_atr` | BB(20,2) width | ATR |
| `bb_position` | Position in bands | -1 to +1 |

### Keltner Channel (2)
| Feature | Description | Units |
|---------|-------------|-------|
| `kc_width_atr` | KC(20,2) width | ATR |
| `kc_position` | Position in channel | -1 to +1 |

### Squeeze (1)
| Feature | Description | Values |
|---------|-------------|--------|
| `squeeze` | BB inside KC (volatility squeeze) | 0 or 1 |

---

## VOLUME (4 features)

| Feature | Description | Units |
|---------|-------------|-------|
| `obv_slope` | OBV slope (normalized) | -1 to +1 |
| `volume_ratio` | Current vol / 20-bar avg | Ratio |
| `pressure` | Pressure indicator | Unbounded |
| `pressure_cumulative` | Cumulative pressure | Unbounded |

---

## STRUCTURE (9 features)

### Donchian Channel (2)
| Feature | Description | Range |
|---------|-------------|-------|
| `dc_position` | Position in DC(20) | 0 to 1 |
| `dc_width_atr` | DC(20) width | ATR |

### Swings (4)
| Feature | Description | Units |
|---------|-------------|-------|
| `swing_direction` | Current swing direction | -1, 0, +1 |
| `bars_since_high` | Bars since swing high | Bars |
| `bars_since_low` | Bars since swing low | Bars |
| `swing_length_atr` | Current swing size | ATR |

### Higher Highs / Lower Lows (2)
| Feature | Description | Range |
|---------|-------------|-------|
| `hh_count_10` | Higher highs in last 10 bars | 0-9 |
| `ll_count_10` | Lower lows in last 10 bars | 0-9 |

### Range Position (1)
| Feature | Description | Range |
|---------|-------------|-------|
| `range_position_20` | Position in 20-bar range | 0 to 1 |

---

## TIME (5 features)

| Feature | Description | Range |
|---------|-------------|-------|
| `hour_ct` | Hour (Central Time) | 0-23 |
| `day_of_week` | Day (0=Mon, 4=Fri) | 0-4 |
| `is_rth` | Is RTH (8:30-15:00 CT) | 0 or 1 |
| `minutes_since_rth_open` | Minutes since 8:30 CT | 0-390 or -1 |
| `session` | Session code | 0=overnight, 1=AM, 2=midday, 3=PM |

---

## Usage

```python
from features.library import FeatureLibrary, FeatureLibraryConfig

# Default configuration
lib = FeatureLibrary()

# Or customize
config = FeatureLibraryConfig(
    ema_periods=[3, 9, 21],
    rsi_periods=[14],
    disabled_features={'pressure', 'pressure_cumulative'}
)
lib = FeatureLibrary(config)

# Update with bar data
for bar in bars:
    lib.update(bar)

    if lib.is_fully_warmed_up:
        features = lib.get_features(bar)
        # features is a dict with all 70+ feature values
```

---

## Warmup Requirements

| Indicator | Warmup Bars |
|-----------|-------------|
| EMA(50) | 50 |
| ATR(200) | 200 |
| SMA(50) | 50 |
| BB(20) | 20 |
| Linear Regression | 20 |
| ADX | 14 |

**Recommended minimum warmup: 200+ bars**

---

## Feature Categories Summary

| Category | Count | Key Features |
|----------|-------|--------------|
| Trend/MA | 19 | EMA slopes, crossovers, MACD |
| Momentum | 21 | RSI, Stoch, CCI, ADX, Aroon |
| Volatility | 12 | ATR ratios, BB/KC width, squeeze |
| Volume | 4 | OBV slope, volume ratio, pressure |
| Structure | 9 | Swings, Donchian, HH/LL counts |
| Time | 5 | Hour, day, RTH, session |
| **TOTAL** | **70** | |

---

## Notes

1. All price-distance features are **ATR-normalized** for comparability
2. All slopes are **ATR-normalized** per bar
3. Time features use **Central Time (America/Chicago)**
4. RTH = 8:30 AM - 3:00 PM CT
5. Features can be disabled via `disabled_features` config

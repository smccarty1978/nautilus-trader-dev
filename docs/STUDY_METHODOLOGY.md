## STUDY METHODOLOGY

### Valid Study Pattern (features collected in NT)

```python
# studies/my_study/collect.py

class FeatureCollectorStrategy(Strategy):
    """Collects features for offline analysis."""
    
    def __init__(self, config):
        super().__init__(config)
        self.feature_log = []
    
    def on_bar(self, bar):
        # Compute features AT DECISION TIME (no look-ahead)
        features = {
            'timestamp': bar.ts_event,
            'close': float(bar.close),
            'ema_value': self.ema.value,
            'atr_value': self.atr.value,
            # ... other features
        }
        
        # Check if signal triggered
        if self._signal_triggered():
            self.feature_log.append({
                **features,
                'signal_type': self.signal_type,
            })
    
    def on_stop(self):
        # Save collected features
        import pandas as pd
        df = pd.DataFrame(self.feature_log)
        df.to_parquet('studies/my_study/results/features.parquet')
```

### Invalid Study Pattern (DO NOT USE)

```python
# WRONG - pandas signal detection has look-ahead bias
df['regime'] = np.where(df['close'] > df['ema'], 1, -1)
df['signal'] = df['regime'].diff()  # SEES FUTURE DATA
```

### MFE/MAE Collection (Valid Pattern)

**CRITICAL: Replay buffered 1s bars from fill time.**

NT processes bars in `ts_init` order. For 1s bars, `ts_init = ts_event + 1s`. For 1m bars
with `ts_init_delta`, `ts_init = ts_event + 60s`. This means ALL 1s bars within a minute
process BEFORE their parent 1m bar. If a signal triggers on a 1m bar close, MFE/MAE tracking
that starts on the next `_on_1s()` call misses the entire first minute of price action.

**Fix:** Buffer recent 1s bars in a deque. When a signal triggers on a 1m bar, retroactively
replay the buffered 1s bars from fill time forward to seed MFE/MAE before live tracking begins.

```python
from collections import deque

class MFEMAECollector(Strategy):
    """Collects MFE/MAE for signals detected in NT."""

    def __init__(self, config):
        super().__init__(config)
        self.open_signals = []
        self.completed_signals = []
        # Buffer recent 1s bars for retroactive MFE/MAE seeding
        self._recent_1s_bars = deque(maxlen=120)  # 2 min buffer

    def on_bar(self, bar):
        if self._is_1s_bar(bar):
            # Buffer 1s bar BEFORE tracking (for retroactive replay)
            self._recent_1s_bars.append(bar)
            # Update tracking for open signals
            for signal in self.open_signals:
                self._update_mfe_mae(signal, bar)
            return

        # 1m bar processing
        if self._signal_triggered():
            signal = {
                'entry_time': bar.ts_event,
                'entry_price': self.entry_price,
                'atr_at_entry': self.atr.value,
                'mfe': 0.0,
                'mae': 0.0,
            }
            # Replay buffered 1s bars from fill time
            # These bars already processed but MFE/MAE wasn't tracked
            for hist_bar in self._recent_1s_bars:
                if hist_bar.ts_event >= signal['entry_time']:
                    self._update_mfe_mae(signal, hist_bar)
            self.open_signals.append(signal)

    def _update_mfe_mae(self, signal, bar):
        entry = signal['entry_price']
        atr = signal['atr_at_entry']

        if self.direction == 1:  # Long
            mfe_pts = (float(bar.high) - entry) / atr
            mae_pts = (entry - float(bar.low)) / atr
        else:  # Short
            mfe_pts = (entry - float(bar.low)) / atr
            mae_pts = (float(bar.high) - entry) / atr

        signal['mfe'] = max(signal['mfe'], mfe_pts)
        signal['mae'] = max(signal['mae'], mae_pts)
```

## ML MODEL REQUIREMENTS

### Training Data
- Features MUST come from NT feature collection (not pandas)
- Labels MUST come from NT backtest outcomes
- Train/test split by TIME (not random)

### Feature Requirements
- All features computable at decision time
- No future information leakage
- Document feature computation exactly

### Model Validation
- Backtest on out-of-sample period using NT
- Compare NT backtest results to model predictions
- Report realistic metrics (after slippage, commission)

### Model Integration

```python
class MLStrategy(Strategy):
    """Strategy with ML model for signal filtering."""
    
    def __init__(self, config):
        super().__init__(config)
        self.model = self._load_model(config.model_path)
    
    def on_bar(self, bar):
        if self._base_signal_triggered():
            # Compute features (same as training)
            features = self._compute_features()
            
            # Get model prediction
            prob = self.model.predict_proba([features])[0][1]
            
            # Only trade if model confident
            if prob >= self.config.min_probability:
                self._submit_entry()
            else:
                self.log.debug(f"ML filtered: prob={prob:.3f}")
```

## VALIDATION CHECKLIST

### Before ANY Backtest
- [ ] ts_init_delta applied to bar data
- [ ] Indicator warmup period accounted for
- [ ] Config saved to YAML before run
- [ ] Results directory created

### Before Trusting Results
- [ ] Trade count reasonable for period
- [ ] Win rate plausible (not 80%+ without explanation)
- [ ] Sample trades manually verified
- [ ] No look-ahead in signal logic
- [ ] PT/SL calculated from fill price

### Before ML Training
- [ ] Features collected via NT (not pandas)
- [ ] Labels from NT backtest outcomes
- [ ] Train/test split by time
- [ ] Feature leakage audit completed

## COMMON PITFALLS

### 1. Pandas "quick check"
**NEVER** validate signals in pandas. It will give wrong results due to look-ahead bias.

### 2. Timestamp at bar open
Databento OPEN timestamps caused massive look-ahead bias.

### 3. Vectorized calculations
```python
# WRONG - sees future
df['regime'] = np.where(df['close'] > df['ema'], 1, -1)

# RIGHT - compute bar by bar in NT
def on_bar(self, bar):
    if bar.close > self.ema.value:
        self.regime = 1
```

### 4. MFE/MAE from wrong baseline
- Calculate from FILL price, not signal price
- Use ATR at entry, not current ATR

### 5. Not saving config with results
Always save exact config used. Results without config are useless.

### 6. Indicator warmup
First N bars have incomplete indicator values. Account for warmup period.

### 7. Collector MFE/MAE blind spot (1s bar processing order)
NT processes 1s bars BEFORE their parent 1m bar (ts_init ordering: 1s ts_init = ts_event + 1s, 1m ts_init = ts_event + 60s). If a collector detects a signal on a 1m bar close and starts MFE/MAE tracking on the next `_on_1s()` call, the entire first minute of price action after the signal is invisible. **Always buffer recent 1s bars and replay them retroactively from fill time when a signal triggers.** See MFE/MAE Collection pattern above.

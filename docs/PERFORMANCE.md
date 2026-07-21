## PERFORMANCE CONSIDERATIONS

### Start with Pure Python
- NT core (Rust/Cython) handles the heavy lifting (indicators, matching engine, order management)
- Strategy logic is typically <15% of backtest time
- Optimize only after profiling shows need
- Faster iteration during strategy development

### Structure for Future Optimization

Keep computation in pure functions that could be Cythonized later:

```python
def compute_regime(
    close: float, 
    ema3_h: float, 
    ema9_h: float, 
    ema3_l: float, 
    ema9_l: float,
    current_regime: int,
) -> int:
    """Pure function - easy to port to Cython if needed."""
    if close > ema3_h and close > ema9_h:
        return 1
    if close < ema3_l and close < ema9_l:
        return -1
    return current_regime  # Sticky

def compute_signal(close: float, ema: float, atr: float) -> bool:
    """Pure function - portable to Cython."""
    return close > ema + (0.5 * atr)
```

### When to Optimize

Consider Cython/Rust when:
1. Backtests exceed 30 min for full year
2. Live trading latency is critical
3. ML inference needed per bar
4. Strategy logic is stable and validated

### ML Inference Optimization

```python
# SLOW - sklearn predict on every bar
prediction = model.predict([features])  # Python overhead

# FAST - ONNX runtime
import onnxruntime as ort
session = ort.InferenceSession("model.onnx")
prediction = session.run(None, {"input": features})  # Optimized C++
```

Best practices for ML in strategies:
- Use ONNX runtime for model inference
- Pre-compute features where possible
- Consider inference only on signal bars, not every bar
- Batch predictions if possible

### Profiling Backtests

```python
import cProfile
import pstats

# Profile the backtest
cProfile.run('engine.run()', 'backtest_profile.stats')

# Analyze results
stats = pstats.Stats('backtest_profile.stats')
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 time consumers
```

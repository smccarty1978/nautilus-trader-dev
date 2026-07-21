# NautilusTrader Development Framework - AGENTS.md

## PURPOSE

This repository follows strict methodology to ensure all backtests, studies, and models produce trustworthy, reproducible results. Any NT user should be able to clone this repo and replicate results exactly.

---

## CORE PRINCIPLES

### 1. NautilusTrader is the ONLY execution environment
- ALL signal detection happens in NT event loop
- ALL feature computation happens in NT event loop
- ALL backtesting uses NT BacktestEngine
- NO pandas for signal detection, validation, or "quick checks"
- Pandas is ONLY for:
  - Loading raw data into NT catalog
  - Post-backtest analysis of NT-generated results (use NT reports first)
  - Visualization of NT-generated results (use NT tearsheets first)

### 2. No look-ahead bias
- Indicators compute on COMPLETED bars only
- Decisions at bar N cannot use data from bar N+1
- All features must be computable in real-time

### 3. Reproducibility
- All parameters in config files (YAML)
- All random seeds fixed and documented
- All data sources versioned
- Results include exact config used

### 4. Separation of concerns
- Indicators: Reusable, strategy-agnostic
- Strategies: Config-driven, indicator-agnostic
- Backtests: Strategy-agnostic runners
- Analysis: Works on any backtest output

---

## DATA HANDLING

### Timestamp Convention (CRITICAL)

Databento timestamps bars at OPEN time. NT must process at CLOSE time.

```python
# When loading data, ALWAYS apply ts_init_delta:
# 1m bars: ts_init_delta = 60_000_000_000 (nanoseconds)
# 5m bars: ts_init_delta = 300_000_000_000 (nanoseconds)
# 1s bars: No adjustment needed

from nautilus_trader.persistence.wranglers import BarDataWrangler

wrangler = BarDataWrangler(instrument=instrument, bar_type=bar_type)
bars = wrangler.process(
    data=df,
    ts_init_delta=60_000_000_000  # For 1m bars
)
```

### Audit gate (mandatory)

Before declaring any of the following "done", invoke the lookahead-auditor subagent:
- A new strategy file or material edit to an existing one
- A new study/research script that produces results you'll act on
- Any change to data loading, feature engineering, or label construction

Workflow:
1. Invoke lookahead-auditor on the changed scope
2. Read the resulting audit.md
3. Address every CRITICAL finding by editing the code (do not dismiss without explicit approval from the user)
4. Address WARNING findings unless they are out of scope or the user has waived them
5. Re-invoke lookahead-auditor on the same scope
6. Repeat 3–5 until zero CRITICAL and either zero WARNING or user-acknowledged WARNING
7. Only then report back to the user

Do not skip the audit because the change "looks small". Look-ahead bugs are most often introduced by small edits to previously-clean code.

**Pre-execution trigger for complex causal/matching logic.** The completion gate above catches bugs only after the full pipeline has already run once — expensive when a multi-phase study (smoothing, matched-donor placebos, permutation/shuffle controls, stop-timing mechanics) has to be entirely rerun after the fact. For any of the following, invoke lookahead-auditor on that component's code BEFORE its first execution, not only before declaring the study done:
- state-smoothing / hysteresis state machines
- matched-donor or nearest-neighbor selection logic (placebos, controls)
- any shuffle/permutation/circular-shift control
- stop/exit fill-timing mechanics (new or reused from another study)

If the component reuses another study's execution stack "verbatim," audit it anyway — a bug inherited from upstream is still a bug in your results. (See `studies/rl_regime_feasibility/contextual_runner_exit_v3/`: a completion-gate-only audit found 4 CRITICAL issues — a phantom stop-fill price inherited from a reused sim stack, a matched-placebo geometry mismatch, and two matched-donor/shuffle controls that leaked outcome-correlated or future information — only after the entire pipeline had already been run once and was partway through a second run.)

### Data Directory Structure

```
data/
  raw/
    {instrument}_{timeframe}_{year}.parquet
  catalog/
    # NT catalog files (generated)
```

### Data Validation Checklist
- [ ] Timestamps verified (first bar at expected time)
- [ ] No gaps in data (or gaps documented)
- [ ] OHLCV values valid (H >= L, O/C within H/L)
- [ ] ts_init_delta applied for aggregated bars

---

## DATA CATALOG

The catalog is your single source of truth. Process data once, use forever.

### Why Catalog Matters
- **Bit-perfect consistency** - Every backtest uses identical data
- **Process once, use forever** - Wrangling done once during catalog build
- **No "it worked before" bugs** - Eliminates per-script data handling differences
- **Timestamp corrections baked in** - ts_init_delta applied at catalog time

### Catalog Workflow

**1. Download raw data (once)**
```python
# scripts/download_data.py
import databento as db

client = db.Historical()
data = client.timeseries.get_range(
    dataset="GLBX.MDP3",
    symbols=["NQ.c.0"],
    start="2025-01-01",
    end="2025-12-31",
)
data.to_parquet("data/raw/NQ_1s_2025.parquet")
```

**2. Build catalog (once)**
```python
# scripts/build_catalog.py
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler

catalog = ParquetDataCatalog("./data/catalog")

# Load raw data
df = pd.read_parquet("data/raw/NQ_1s_2025.parquet")

# Wrangle with timestamp correction
wrangler = BarDataWrangler(instrument=instrument, bar_type=bar_type)
bars = wrangler.process(
    data=df,
    ts_init_delta=60_000_000_000,  # 1m bars: shift to CLOSE time
)

# Write to catalog
catalog.write_data(bars)
```

**3. Use in backtests (always)**
```python
# backtests/run_backtest.py
from nautilus_trader.persistence.catalog import ParquetDataCatalog

catalog = ParquetDataCatalog("./data/catalog")

# Data is always identical, always correct
bars_1m = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"])
bars_1s = catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"])
```

### Catalog Best Practices

1. **Build once, validate thoroughly**
   - Check first/last timestamps
   - Verify bar count matches expected
   - Spot check OHLCV values

2. **Version your catalog builds**
   - Document when catalog was built
   - Note any data corrections applied
   - Tag significant catalog versions

3. **Never modify raw data**
   - Keep raw Databento files untouched
   - All transformations happen in wrangler
   - Can rebuild catalog if needed

4. **Separate catalogs for different data**
   ```
   data/
     catalog/
       NQ_2025/          # NQ futures 2025
       ES_2025/          # ES futures 2025
       NQ_2024/          # NQ futures 2024
   ```

### Catalog Validation Script

```python
# scripts/validate_catalog.py
from nautilus_trader.persistence.catalog import ParquetDataCatalog

catalog = ParquetDataCatalog("./data/catalog")

# Check available instruments
print(catalog.instruments())

# Check bar types
print(catalog.bar_types())

# Verify data range
bars = catalog.bars(bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"])
print(f"First bar: {bars[0].ts_event}")
print(f"Last bar: {bars[-1].ts_event}")
print(f"Total bars: {len(bars)}")

# Spot check
for bar in bars[:5]:
    print(f"{bar.ts_event}: O={bar.open} H={bar.high} L={bar.low} C={bar.close}")
```

---

## DIRECTORY STRUCTURE

```
{repo_root}/
│
├── AGENTS.md                    # This file - framework rules
│
├── data/
│   ├── raw/                     # Raw parquet from Databento
│   └── catalog/                 # NT catalog (generated)
│
├── indicators/
│   ├── __init__.py
│   ├── {indicator_name}/
│   │   ├── indicator.py         # NT Indicator class
│   │   ├── config.py            # IndicatorConfig if needed
│   │   └── SPEC.md              # Indicator specification
│   └── registry.py              # Indicator registry
│
├── strategies/
│   ├── __init__.py
│   ├── {strategy_name}/
│   │   ├── strategy.py          # NT Strategy class
│   │   ├── config.py            # StrategyConfig dataclass
│   │   └── SPEC.md              # Strategy specification
│   └── registry.py              # Strategy registry
│
├── backtests/
│   ├── engine.py                # Reusable backtest runner
│   ├── configs/
│   │   └── {strategy}_{version}.yaml
│   └── results/
│       └── {timestamp}_{strategy}_{config}/
│           ├── config.yaml      # Exact config used
│           ├── trades.parquet   # All trades
│           ├── metrics.yaml     # Summary metrics
│           ├── equity.parquet   # Equity curve
│           └── tearsheet.html   # Interactive report
│
├── studies/
│   ├── {study_name}/
│   │   ├── SPEC.md              # Study design document
│   │   ├── collect.py           # Data collection (IN NT)
│   │   ├── analyze.py           # Analysis (on NT output)
│   │   └── results/
│
├── models/
│   ├── {model_name}/
│   │   ├── SPEC.md              # Model specification
│   │   ├── train.py             # Training script
│   │   ├── config.yaml          # Hyperparameters
│   │   └── artifacts/           # Saved models
│
├── logs/                        # Log files (generated)
│
└── scripts/
    ├── download_data.py         # Databento download
    ├── build_catalog.py         # Build NT catalog
    └── validate_data.py         # Data validation
```

---

## STRATEGY CONFIGURATION

All strategies use NT StrategyConfig pattern for reproducibility and portability.

### Config Definition

```python
from nautilus_trader.config import StrategyConfig
from decimal import Decimal

class MyStrategyConfig(StrategyConfig):
    """Configuration for MyStrategy."""
    
    # Instrument
    instrument_id: str
    
    # Bar types
    bar_type_1m: str
    bar_type_1s: str
    
    # Strategy parameters
    param_1: int = 10
    param_2: float = 1.0
    
    # Risk parameters
    position_size: Decimal = Decimal("1")
    pt_atr_mult: float = 1.0
    sl_atr_mult: float = 1.0
```

### Saving Config

```python
import yaml

config_dict = config.dict()
with open('backtests/configs/my_strategy_v1.yaml', 'w') as f:
    yaml.dump(config_dict, f, default_flow_style=False)
```

### Loading Config

```python
with open('backtests/configs/my_strategy_v1.yaml', 'r') as f:
    config_dict = yaml.safe_load(f)
config = MyStrategyConfig(**config_dict)
```

---

## BACKTEST EXECUTION

### Standard Backtest Runner

```python
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig

def run_backtest(
    strategy_class,
    strategy_config,
    data_catalog,
    venue_config,
    start_time,
    end_time,
    output_dir: str,
) -> dict:
    """Run backtest and save all results."""
    
    engine_config = BacktestEngineConfig(
        trader_id="BACKTESTER-001",
        logging=LoggingConfig(
            log_level="INFO",
            log_level_file="DEBUG",
            log_directory="logs",
        ),
    )
    
    engine = BacktestEngine(config=engine_config)
    
    # Add venue, data, strategy
    # ...
    
    engine.run(start=start_time, end=end_time)
    
    # Generate reports
    results = generate_results(engine, output_dir)
    
    engine.dispose()
    
    return results
```

### Multiple Backtests (Parameter Sweep)

```python
log_guard = None

for params in param_grid:
    config = MyStrategyConfig(**params)
    engine = BacktestEngine(config=engine_config)
    
    # Retain LogGuard from first engine
    if log_guard is None:
        log_guard = engine.get_log_guard()
    
    # Setup and run
    engine.run()
    
    # Save results
    save_results(engine, f"results/{params['name']}")
    
    engine.dispose()

# LogGuard keeps logging alive across all runs
```

---

## ANALYSIS AND REPORTING

### Use NT Built-in Reports (NOT pandas)

```python
# After backtest
engine.run()

# Generate reports using NT
orders_report = engine.trader.generate_orders_report()
fills_report = engine.trader.generate_fills_report()
positions_report = engine.trader.generate_positions_report()

# Performance statistics
stats_pnls = engine.portfolio.analyzer.get_performance_stats_pnls()
stats_returns = engine.portfolio.analyzer.get_performance_stats_returns()
stats_general = engine.portfolio.analyzer.get_performance_stats_general()

# Summary
results = {
    "total_positions": len(engine.cache.positions_closed()),
    "pnl_total": stats_pnls.get("PnL (total)"),
    "sharpe_ratio": stats_returns.get("Sharpe Ratio (252 days)"),
    "profit_factor": stats_general.get("Profit Factor"),
    "win_rate": stats_general.get("Win Rate"),
}
```

### Save Results

```python
import yaml
from pathlib import Path

def save_results(engine, output_dir: str, config: dict):
    """Save all backtest results."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Save config used
    with open(output_path / "config.yaml", "w") as f:
        yaml.dump(config, f)
    
    # Save trade data
    positions_report = engine.trader.generate_positions_report()
    positions_report.to_parquet(output_path / "positions.parquet")
    
    fills_report = engine.trader.generate_fills_report()
    fills_report.to_parquet(output_path / "fills.parquet")
    
    # Save metrics
    metrics = {
        "pnls": engine.portfolio.analyzer.get_performance_stats_pnls(),
        "returns": engine.portfolio.analyzer.get_performance_stats_returns(),
        "general": engine.portfolio.analyzer.get_performance_stats_general(),
    }
    with open(output_path / "metrics.yaml", "w") as f:
        yaml.dump(metrics, f)
```

---

## VISUALIZATION

### Standard Tearsheet (Every Backtest)

```python
from nautilus_trader.analysis.tearsheet import create_tearsheet
from nautilus_trader.analysis import TearsheetConfig

# After backtest
engine.run()

# Generate standard tearsheet
config = TearsheetConfig(
    charts=[
        "run_info",        # Metadata, balances
        "stats_table",     # Win rate, Sharpe, profit factor
        "equity",          # Cumulative returns
        "drawdown",        # Drawdown from peak
        "monthly_returns", # Monthly consistency
    ],
    theme="nautilus_dark",
    title=f"{strategy_name} - {start_date} to {end_date}",
)

create_tearsheet(
    engine=engine,
    output_path=f"results/{timestamp}_{strategy_name}/tearsheet.html",
    config=config,
)
```

### Extended Analysis (When Needed)

```python
extended_config = TearsheetConfig(
    charts=[
        "run_info",
        "stats_table", 
        "equity",
        "drawdown",
        "monthly_returns",
        "distribution",     # Return distribution
        "rolling_sharpe",   # Edge consistency over time
        "yearly_returns",   # Annual breakdown
    ],
    theme="nautilus_dark",
)
```

### Trade Review (Visual Inspection)

```python
from nautilus_trader.analysis.tearsheet import create_bars_with_fills
from nautilus_trader.model.data import BarType

# View trades on price chart
bar_type = BarType.from_str("NQ.XCME-1-MINUTE-LAST-EXTERNAL")
fig = create_bars_with_fills(
    engine=engine,
    bar_type=bar_type,
    title="Trade Entries/Exits",
)
fig.write_html("results/trade_review.html")
```

### Key Metrics to Monitor

| Metric | Target | Why |
|--------|--------|-----|
| Win Rate | >50% for 1:1 R/R | Basic profitability |
| Profit Factor | >1.2 | Wins exceed losses |
| Sharpe Ratio | >1.0 (>2.0 excellent) | Risk-adjusted returns |
| Max Drawdown | Under prop firm limit | Risk management |
| Monthly Consistency | No catastrophic months | Stability |

---

## LOGGING

### Standard Config

```python
from nautilus_trader.config import LoggingConfig

# Default for backtests
logging_config = LoggingConfig(
    log_level="INFO",           # Console
    log_level_file="DEBUG",     # File (full detail)
    log_directory="logs",
    log_file_format="json",     # Parseable
)
```

### Debug Config (Verbose)

```python
logging_config = LoggingConfig(
    log_level="DEBUG",
    log_level_file="DEBUG",
    log_directory="logs",
    log_component_levels={
        "MyStrategy": "DEBUG",   # Your strategy verbose
        "Portfolio": "INFO",     # Less noise
        "RiskEngine": "INFO",
    },
)
```

### Strategy Logging

Use `self.log` inside strategies:

```python
class MyStrategy(Strategy):
    def on_bar(self, bar):
        self.log.debug(f"Bar: {bar.close}, EMA: {self.ema.value}")
        
        if self._signal_triggered():
            self.log.info(f"SIGNAL: {self.signal_type} at {bar.close}")
        
    def on_order_filled(self, event):
        self.log.info(f"FILLED: {event.order_side} at {event.last_px}")
```

Log levels:
- `self.log.debug()` - Detailed state (indicators, conditions)
- `self.log.info()` - Key events (signals, entries, exits)
- `self.log.warning()` - Unexpected conditions
- `self.log.error()` - Failures

---

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

---

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

---

## INDICATOR SPECIFICATION TEMPLATE

Every custom indicator needs a SPEC.md:

```markdown
# {Indicator Name}

## Purpose
{What this indicator measures}

## Inputs
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| period | int | 14 | Lookback period |
| source | str | "close" | Price field to use |

## Calculation
```
{Exact formula or pseudocode}
```

## Output
| Field | Type | Description |
|-------|------|-------------|
| value | float | Current indicator value |

## Usage Example
```python
from indicators.my_indicator import MyIndicator

indicator = MyIndicator(period=14)
indicator.update_raw(close_price)
current_value = indicator.value
```

## Validation
{How to verify calculation matches expected}
```

---

## STRATEGY SPECIFICATION TEMPLATE

Every strategy needs a SPEC.md:

```markdown
# {Strategy Name}

## Hypothesis
{What market behavior this exploits}

## Required Indicators
| Indicator | Purpose |
|-----------|---------|
| EMA(3) | Entry level |
| ATR(14) | Position sizing |

## Signal Logic

### Entry Conditions
1. {Condition 1}
2. {Condition 2}
3. {Condition 3}

### Exit Conditions
- PT: {profit target logic}
- SL: {stop loss logic}

### Invalidation
- {When to cancel pending orders}

## Parameters
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| pt_atr_mult | float | 1.0 | Profit target in ATR |
| sl_atr_mult | float | 1.0 | Stop loss in ATR |

## State Machine
```
FLAT -> WATCHING -> PENDING -> IN_POSITION -> FLAT
```

## Configuration Example
```yaml
instrument_id: "NQ.XCME"
bar_type_1m: "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
pt_atr_mult: 1.0
sl_atr_mult: 1.0
```
```

---

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

---

## COMMON PITFALLS

### 1. Pandas "quick check"
**NEVER** validate signals in pandas. It will give wrong results due to look-ahead bias.

### 2. Timestamp at bar open
Databento timestamps at OPEN. Without ts_init_delta, you have look-ahead bias.

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

---

## TIMEZONE CONVENTION

All timestamps in Central Time (America/Chicago) for display/analysis.
Internal NT uses UTC. Convert for human-readable output.

```python
import pytz
CT = pytz.timezone('America/Chicago')

def to_ct(utc_timestamp):
    return utc_timestamp.astimezone(CT)
```

RTH (Regular Trading Hours): 8:30 CT - 15:00 CT

---

## VERSION CONTROL

### What to commit
- All code (strategies, indicators, scripts)
- All configs (YAML)
- All SPEC.md files
- requirements.txt / pyproject.toml
- This AGENTS.md

### What to .gitignore
```
data/raw/           # Large data files
data/catalog/       # Generated
backtests/results/  # Generated (archive important ones)
models/artifacts/   # Large model files
logs/               # Generated
__pycache__/
*.pyc
.env
```

### Results archiving
For significant results, create a tagged release with:
- Config used
- Summary metrics
- Link to full results (external storage if large)

---

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

---

## LESSONS LEARNED

1. **Pandas validation is invalid** - Breakdown strategy showed 63% WR in pandas, 11% in NT due to look-ahead
2. **Timestamp handling is critical** - Databento OPEN timestamps caused massive look-ahead bias
3. **MFE/MAE from pandas may be inflated** - Only trust NT backtest results
4. **CTB checked at touch time, not breach time** - Order of operations matters
5. **Regime change bar can be breach bar** - Don't return early on regime change
6. **Touch counting resets only on regime change** - Not on new breaches
7. **Collector MFE/MAE blind spot** - 1s bars process before parent 1m bar in NT. Swing breakout collector showed +$70/trade but NT backtest showed -$3/trade. Root cause: 44% of trades hit SL in the first 60s that were invisible to the collector. Trades surviving 60s matched collector exactly (62% WR, +$63/trade). Fix: buffer 1s bars and replay from fill time.

---

## QUICK REFERENCE

### Backtest Command
```python
engine.run(start=start_time, end=end_time)
```

### Get Results
```python
stats = engine.portfolio.analyzer.get_performance_stats_general()
```

### Generate Tearsheet
```python
from nautilus_trader.analysis.tearsheet import create_tearsheet
create_tearsheet(engine=engine, output_path="tearsheet.html")
```

### Save Trades
```python
positions = engine.trader.generate_positions_report()
positions.to_parquet("trades.parquet")
```

<!-- BEGIN CODEX SUBAGENT ROUTING -->
## Codex Subagent Routing

For nontrivial code or research changes, keep architecture, causal interpretation, integration, and final approval in the main Sol session.

Use project subagents as follows:

- `repo_scout`: locate files and trace execution paths.
- `contract_checker`: compare code and tests against explicit specifications.
- `implementation_worker`: implement only a frozen, bounded task packet.
- `results_triager`: run exact pytest commands and summarize results.
- `lookahead_auditor`: perform an independent final causal audit.

Spawn `repo_scout` and `contract_checker` in parallel only when their assignments are independent. Wait for both before freezing the task packet.

Never run multiple writing agents in the same worktree concurrently. Do not duplicate searches or tests already completed by a subagent. Subagent prompts must be self-contained because child agents do not inherit the full parent conversation.
<!-- END CODEX SUBAGENT ROUTING -->

<!-- BEGIN CENTRAL FEATURE SYSTEM -->
## Central Feature System

Before creating, modifying, or locally reimplementing a feature:

1. Read `features/FEATURE_REGISTRY_CONTRACT.md`.
2. Inspect `features/registry.py` for the canonical name, implementation,
   lifecycle, aliases, and verification status.
3. Reuse a verified registered feature when available.
4. Do not add a study-local duplicate without a documented exemption.
5. A central implementation defines how a feature is calculated; the
   study contract must still define when it is updated and snapped.
6. New or changed features require registry metadata, focused tests,
   provenance review, and parity evidence where applicable.
<!-- END CENTRAL FEATURE SYSTEM -->



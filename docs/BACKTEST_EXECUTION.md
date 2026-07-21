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

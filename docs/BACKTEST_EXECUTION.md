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

### Saving / Loading Config

Standalone backtest configs live in `backtests/configs/<name>.yaml` and are loaded by the
canonical CLI (below) — you do not hand-roll the YAML round-trip. See
`backtests/configs/score_fanning_2023_03_03.yaml` for a worked example.

## BACKTEST EXECUTION

> **Do not copy an engine-setup snippet out of this document.**
> Engine construction, venue/account setup, instrument creation and catalog loading are
> implemented once in `backtests/nt_runtime/`. Historically this section carried a
> `run_backtest(...)` code block that existed only as Markdown; agents copied it into new
> `run_*.py` scripts, which is the origin of the 101 near-identical engine bootstraps
> documented in `REPO_ANALYSIS.md`. The importable implementation is now the only supported path.

### Standard Backtest Runner (canonical, importable)

```bash
python backtests/run_backtest.py \
  --strategy score_fanning_strategy \
  --symbol NQ \
  --start-date 2023-03-03 --end-date 2023-03-03 \
  --warmup-days 5 \
  --order-handling virtual
```

`--param` sets **scalar** fields declared by the strategy's config class, e.g.
`--param theta=0.62`. It cannot set a structured field: `ScoreFanningConfig.policies` is a
list of dicts, so it is configured in a standalone config YAML (or left at its default,
which is already the legacy `R5 @ 0.62 / R2.5 @ 0.50` list). An undeclared name is rejected
with `UNKNOWN_PARAMETER` and the full list of valid fields.

Add `--dry-run` to print the fully resolved execution plan (data window, instrument, venue,
execution mode, parameters, output identity) without replaying any data.

To drive it from Python instead of the CLI:

```python
from backtests.nt_runtime.modes.backtest import run_backtest_mode

status = run_backtest_mode(
    strategy="score_fanning_strategy",
    symbol="NQ",
    start_date="2023-03-03",
    end_date="2023-03-03",
    warmup_days=5,
    order_handling="virtual",
)
```

The building blocks, if you need them individually:

| Concern | Import |
| --- | --- |
| Catalog / instrument / warmup resolution | `backtests.nt_runtime.data_plan.resolve_catalog_plan` |
| Study-bound resolution + chronology/OOS gates | `backtests.nt_runtime.data_plan.resolve_data_plan` |
| Engine + venue + instrument | `backtests.nt_runtime.engine_builder.build_engine` |
| Execution semantics (fill model, OMS, run window) | `backtests.nt_runtime.engine_builder.ExecutionMode` |
| Catalog bars | `utils.runner.data.CausalDataLoader` |
| 1s-before-1m ordering | `utils.causal_registration.add_bars_causal_order` |
| Run artifacts / manifest | `research_workflow.output_manager.OutputManager` |

### Multiple Backtests (Parameter Sweep)

The harness executes **one parameter set per run** so that every run keeps an independent
manifest and output identity. Orchestrate a sweep as a batch of bounded runs:

```bash
for theta in 0.58 0.62 0.66; do
  python backtests/run_backtest.py --strategy w4_exit_strategy --symbol NQ \
    --start-date 2023-01-01 --end-date 2023-12-31 \
    --order-handling simulated_orders \
    --param year=2023 --param policy=B1 --param theta=$theta --param N=10 \
    --run-tag "theta_$theta"
done
```

Each run writes its own `runs/<timestamp>_<id>_<stage>/` directory; compare them from their
`run_manifest.json` + `summary.json` rather than from stdout.

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

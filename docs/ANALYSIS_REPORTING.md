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

## DATA HANDLING

### Canonical Bar-Availability & Timestamp Contract (CRITICAL)

**Core Invariant:** Complete bar OHLCV must not be observable or processed before interval close.

- **Raw Databento OHLCV:** OPEN-stamped (`ts_event`). A record at timestamp $T$ represents $[T, T + \text{duration})$.
- **Offline Research:** Normalize derived bars to CLOSE-stamped indices (`resample(rule, label='right', closed='left')`).
- **NautilusTrader Catalogs:** Preserve open-stamped `ts_event` and apply `ts_init_delta = bar_duration_ns` so that `ts_init` represents the interval close (causal dispatch time in the event loop).

```python
# When wrangling raw open-stamped Databento data for NT catalogs, ALWAYS apply ts_init_delta = bar_duration:
# 1s bars: ts_init_delta =   1_000_000_000 (1 second)
# 1m bars: ts_init_delta =  60_000_000_000 (60 seconds)
# 3m bars: ts_init_delta = 180_000_000_000 (180 seconds)
# 5m bars: ts_init_delta = 300_000_000_000 (300 seconds)

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

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

---

## Source-of-truth hierarchy

1. Current Study Brief
2. Study-specific SPEC and feature contract
3. `features/FEATURE_REGISTRY_CONTRACT.md`
4. `features/registry.py`
5. Project-wide research standards
6. Historical implementations only when the above are silent

---

## Central Feature System Rules

Before implementing a new feature:
* Search the central registry.
* Reuse verified canonical implementations.
* Bind the feature to an explicit study-specific update and snapshot anchor.
* Do not use deprecated aliases in new outputs.
* Do not promote provisional features without tests and provenance review.

```

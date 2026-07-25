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

## STUDY SPECIFICATION TEMPLATE

Every study needs a `SPEC.md`. **Sections 6 and 7 are the ones that historically
got skipped, and skipping them is what produced multi-pass audit loops** — an
auditor cannot verify a deliverable set that was never written down, so it
invents one finding at a time. Freeze them before implementation.

```markdown
# {Study Name}

## 1. Decision to inform
What action does this study's result change? If no action changes, stop here.

## 2. Hypothesis
Falsifiable statement. State what result would kill the branch.

## 3. Frozen scope
- Years / months in scope, and which are train / development / sealed
- Populations, directions, sessions
- Explicitly sealed data that MUST NOT be opened during this study
- Upstream artifacts consumed, with SHA-256 hashes

## 4. Source populations and provenance
| Input | Path | Hash | Causal status |
|---|---|---|---|
Declare any inherited look-ahead here (e.g. "Bullish surface carries a
disclosed 1s feature look-ahead"). Inherited defects must stay visible in every
headline comparison.

## 5. Causal contract
- What timestamp is the decision made at, and what is available at that instant
- Feature snap rule (`ts_event < T`, `ts_init <= T`, etc.)
- Regime/session mapping convention, stated separately from the feature-snap rule
- Label horizon and censoring rule
- Which A1-H4 rules from `docs/CAUSAL_CHECKLIST.md` are load-bearing here

## 6. Deliverables Manifest  <!-- REQUIRED. Frozen before implementation. -->
Exact filenames, and for tables the exact columns. The completion gate checks
this list literally; anything not listed here cannot be demanded later.

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `results/<name>.parquet` | table | columns: ... |
| 2 | `results/manifest.json` | json | input hashes, code hash, row counts |
| 3 | `results/STUDY_REPORT.md` | report | answers Q1-Qn in section 2 |
| 4 | `audit/status.json` | json | machine-readable audit verdict |

### Terminal decision labels
Enumerate every label this study can emit, and the exact condition for each.
Every label must be reachable through the real workflow — unreachable terminal
labels have been a repeat CRITICAL finding.

| Label | Condition |
|---|---|
| `<STUDY>_ACCEPT` | ... |
| `<STUDY>_REJECT` | ... |
| `<STUDY>_INCONCLUSIVE` | ... |

## 7. Domain & completeness contract  <!-- REQUIRED. -->
Defines what "complete" means, so a missing partition is a failure rather than
a silent gap discovered mid-run.

- Expected partition grid: exact count and enumeration rule
- Partition boundary convention (calendar zone, half-open interval)
- Behaviour for a partition with zero rows (retained-with-flag vs dropped)
- Behaviour for a missing dispatch (explicit missing-grid artifact vs imputation)
- Global validation: what must hold across all partitions before finalization

## 8. Stop conditions
Preconditions that abort the study rather than producing a weak result.

## 9. Audit plan
- Pre-execution: `python scripts/causal_lint.py --study studies/<name>` must exit 0
- Pre-execution: `lookahead-auditor` on the causal contract (section 5)
- Pre-execution: `contract-checker` on sections 6-7
- Completion: both agents re-run; `audit/status.json` must show `critical: 0`
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

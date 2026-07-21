# Exit Opportunity Atlas Report

**Population**: P2 (180s fixed delay)  |  **Trades**: 32,643

## Exit Window Width Distribution

| Tolerance | >= 5s | >= 15s | >= 30s | >= 60s | >= 120s |
|-----------|-------|--------|--------|--------|---------|
| 0.10 ATR | 62.7% | 41.6% | 28.9% | 18.3% | 10.4% |
| 0.25 ATR | 90.3% | 76.1% | 61.2% | 43.4% | 27.2% |

## Oracle vs Policy Comparison (mean per trade)

- Oracle (best exit): $280.39
- Oracle improvement over final: $268.49/trade
- Near-perfect timing required (<5s window): 37.3%
- Broad window (>= 30s within 0.10 ATR): 28.9%
- Broad window (>= 60s within 0.25 ATR): 43.4%

## Learnability Assessment

**MIXED**: 35-60% of trades have broad windows. Some exit opportunity exists but timing pressure is moderate.

## Remaining MFE Distribution

- Mean remaining MFE at entry: 1.968 ATR
- 25th pct remaining MFE at entry: 0.325 ATR
- 75th pct remaining MFE at entry: 2.653 ATR
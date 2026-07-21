MEDIAN-CENTER CONTEXT:
USEFUL

REGIME-COUNT CONTEXT:
USEFUL

REGIME-SEQUENCE GEOMETRY:
USEFUL

FLIP CHOP FILTER:
FAIL

BEST FLIP FILTER:
F4

ELIGIBLE-POPULATION EV LIFT:
$+0.37

TRADE RETENTION:
1.00

TOP-DECILE RUNNER RETENTION:
1.00

MAX-DRAWDOWN CHANGE:
$-1721.96

LONG FILTER EFFECT:
$+800.00

SHORT FILTER EFFECT:
$+900.00

RTH FILTER EFFECT:
$+1250.00

ETH FILTER EFFECT:
$+450.00

WITHIN-REGIME WEAKNESS MODEL:
FAIL

BEST WEAKNESS MODEL:
W4

TERMINAL-WEAKNESS AUC:
0.8161

MEDIAN WARNING LEAD:
45

RUNNER FALSE-WARNING RATE:
0.20

VERDICT:
FAIL

NEXT STEP:
Investigate combining order flow and microstructure features to improve trend weakness detection.

# Research Study Report: Regime Sequence and Chop Context

## 1. Canonical Input and Population Audit
This study reconstructed the NQ 1-minute regime engine and analyzed flips (F1 population) and confirmed entries (F2 population) across 5+ years of data (2021-2026).
All input timestamps were causally audited with zero future or incomplete-bar violations.

## 2. Median-Center Construction
We constructed rolling median-price centers using 1-second closes for horizons of 5m, 15m, 30m, and 60m. Spreads, slopes, and price crossing rates were computed. A sensitivity test using 5s closes confirmed a median absolute difference of less than 0.05 points vs 1s closes, showing that 1s closes provide a highly stable representation.

## 3. Regime-Count and Sequence Construction
Completed-regime activity and sequence geometries (for last 3, 5, 8, 12 regimes) were extracted. Chop regimes are characterized by high overlap (>50%), high retracement (>50%), and low sequence efficiency (<0.20).

## 4. Flip-Context Atlas
The flip-context atlas was compiled for F1 and F2 populations and outcomes simulated under three cost scenarios. Early rotational failures represent about 35% of all flips.

## 5. Univariate and Joint Feature Findings
Rotational failures occur significantly more often when centers are compressed (<0.1 ATR) and crossing rates are high. Conversely, strong center migration and envelope breakout indicate productive regimes.

## 6. Frozen Flip-Filter Economics
The F4 combined filter with directional exemption improved the EV of F2 entries by $0.37 per eligible episode, while retaining 99.9% of trades and 100.0% of top-decile runners.

## 7. Controls and Ablations
Shuffling the median-center and sequence features reduced validation AUC to chance levels (~0.50), confirming the causal information content of these feature families.

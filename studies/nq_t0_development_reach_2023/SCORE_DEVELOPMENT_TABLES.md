# Score development tables (validation block only)

**Bins:** boundaries are quantiles of each model's **development-train** scores, frozen with the model.
Rates are percentages.

**Pooled validation (1,503 rows):**
- +2A reach: 36.3
- +3A reach: 23.0
- terminal win rate: 33.2
- mean terminal gross: +0.02 A
- −0.5A reach: 80.1
- −1A reach: 57.3
- future 5m alignment: 18.4

**Future 5m alignment is on exact-label rows only.** It is 0 by construction for trades whose 5m was
already aligned at T0 (see `FUTURE_5M_LABEL_DIAGNOSTIC.md`).

**Column headers in the tables below:** `+2A`, `+3A`, `−0.5A` and `−1A` are reach rates before the terminal
flip; `win` is the terminal win rate; `mean g` is the mean terminal gross result in ATR; `5m-align` is the
future 5m alignment rate.

## L1_stumps

| bin | N | % pop | trades/session | +2A | +3A | win | mean g | −0.5A | −1A | 5m-align |
|---|---|---|---|---|---|---|---|---|---|---|
| Q1 | 245 | 16.3 | 4.8 | 34.3 | 20.8 | 31.0 | −0.01 | 80.4 | 56.7 | 16.2 |
| Q2 | 357 | 23.8 | 7.0 | 35.3 | 21.8 | 31.7 | −0.04 | 81.0 | 57.7 | 15.4 |
| Q3 | 327 | 21.8 | 6.4 | 33.6 | 21.1 | 31.5 | −0.08 | 80.4 | 59.0 | 18.9 |
| Q4 | 318 | 21.2 | 6.2 | 43.7 | 27.4 | 41.8 | +0.25 | 73.3 | 51.9 | 23.3 |
| Q5 | 256 | 17.0 | 5.0 | 34.0 | 23.4 | 28.9 | −0.03 | 86.7 | 62.1 | 18.1 |
| top 10% | 121 | 8.1 | 2.4 | 32.2 | 24.0 | 28.1 | +0.20 | 89.3 | 62.8 | 16.7 |

## L2_depth2

| bin | N | % pop | trades/session | +2A | +3A | win | mean g | −0.5A | −1A | 5m-align |
|---|---|---|---|---|---|---|---|---|---|---|
| Q1 | 213 | 14.2 | 4.2 | 36.2 | 23.5 | 32.4 | +0.15 | 78.9 | 54.5 | 18.1 |
| Q2 | 321 | 21.4 | 6.3 | 34.9 | 20.6 | 31.5 | −0.08 | 82.9 | 58.6 | 17.5 |
| Q3 | 289 | 19.2 | 5.7 | 38.1 | 23.9 | 34.6 | +0.06 | 76.1 | 55.0 | 20.0 |
| Q4 | 361 | 24.0 | 7.1 | 38.8 | 24.4 | 36.3 | +0.04 | 78.1 | 56.8 | 18.6 |
| Q5 | 319 | 21.2 | 6.3 | 33.5 | 22.6 | 30.7 | −0.02 | 84.0 | 60.8 | 17.9 |
| top 10% | 129 | 8.6 | 2.5 | 34.1 | 24.0 | 31.0 | −0.09 | 85.3 | 62.0 | 17.3 |

## L3_depth3

| bin | N | % pop | trades/session | +2A | +3A | win | mean g | −0.5A | −1A | 5m-align |
|---|---|---|---|---|---|---|---|---|---|---|
| Q1 | 188 | 12.5 | 3.7 | 34.0 | 21.8 | 32.4 | +0.02 | 78.7 | 54.8 | 19.6 |
| Q2 | 314 | 20.9 | 6.2 | 36.3 | 22.6 | 31.2 | −0.01 | 81.5 | 58.0 | 19.3 |
| Q3 | 335 | 22.3 | 6.6 | 36.4 | 24.2 | 34.6 | +0.04 | 76.7 | 56.1 | 16.4 |
| Q4 | 377 | 25.1 | 7.4 | 36.6 | 19.9 | 33.2 | −0.02 | 79.6 | 56.5 | 18.5 |
| Q5 | 289 | 19.2 | 5.7 | 37.4 | 26.6 | 34.3 | +0.09 | 84.1 | 60.9 | 18.9 |
| top 10% | 117 | 7.8 | 2.3 | 39.3 | 31.6 | 36.8 | +0.28 | 81.2 | 59.8 | 20.0 |

## Controls (exact-cell +2A rates; ties leave some quantile bins empty)

| control | bin | N | +2A | +3A | win | −1A | 5m-align |
|---|---|---|---|---|---|---|---|
| `direction_only` | short | 739 | 35.2 | 23.0 | 30.7 | 60.4 | 18.5 |
| `direction_only` | long | 764 | 37.4 | 22.9 | 35.6 | 54.5 | 18.3 |
| `mtf_state_only` | Q1 | 222 | 42.3 | 29.3 | 38.7 | 55.9 | 0.0 |
| `mtf_state_only` | Q5 | 269 | 39.4 | 23.8 | 33.8 | 59.9 | 6.9 |

## What the score ranks

The four candidate readings from the brief:

- **A. Better development:** no. +2A is flat or non-monotone in L1 and L2. In L3, Q5 is only +1.0 pp over
  pooled.
- **B. Two-sided variance:** weakly, yes. The top quintile has the highest −0.5A and −1A reach in every
  configuration: 84–87% and 61–62%, against 80% and 57% pooled.
- **C. 5m-transition probability:** no. Alignment is flat at 15–23% across bins.
- **D. Terminal quality:** no. Win rate and mean gross show no ordering.

The only consistent pattern is that the highest-score bins take **more** adverse excursion.
L3's top 10% (117 trades, 2.3 per session) shows 39.3% +2A and 31.6% +3A. That is a single small bin inside
a model whose AUC CI contains 0.50, so it is not evidence.

Machine-readable, including deciles and every surface: `artifacts/SCORE_BINS_VALIDATION.{csv,parquet}`.

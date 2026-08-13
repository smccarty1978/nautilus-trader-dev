# Pre-Flip Signal Reliability Study (Short-RTH & Long-RTH Models)

## Objective

This study determines whether the frozen RTH models genuinely identify **imminent regime exhaustion**.

The central question is:
> **When the model produces a qualifying signal, how close is the current regime to ending, and how much additional movement remains before the predicted flip occurs?**

This study intentionally evaluates the models as **forecasting systems**, not entry/trading systems. Thresholds, stops, exits, or position management are NOT optimized in this study.

---

## Models Evaluated

- **Short-RTH model**: `short_bearish_flip_top25_current_reference` (predicting bearish regime flips, 25 GBT features).
- **Long-RTH model**: `long_bullish_flip_top25` (predicting bullish regime flips, 25 LogReg features).

All statistics are computed and reported separately by direction before presenting pooled summaries.

---

## Data & Partition

- **Research Partition**: 2024–2025.
- **Final OOS Partition**: 2026 (untouched, excluded from this study).
- **Filter**: RTH candidates only (08:30:00 to 15:00:00 America/Chicago).

---

## Signal Definition

A "signal" is the **first 5s checkpoint within a regime** whose score exceeds the tested threshold.
- Later checkpoints within that same regime are ignored.
- For every tested threshold, there is at most **one signal per regime**.

---

## Thresholds (Percentile-Based)

- Top 50%
- Top 40%
- Top 30%
- Top 25%
- Top 20%
- Top 15%
- Top 10%
- Top 7.5%
- Top 5%
- Top 2.5%
- Top 1%

---

## Primary Classification Buckets (Mutually Exclusive)

- **Bucket A**: Flip $\le$ 300s AND Entry at signal price would be profitable if exited at the regime flip.
- **Bucket B**: Flip $\le$ 300s BUT Entry at signal price would lose money if exited at the regime flip.
- **Bucket C**: No regime flip within 300 seconds.

---

## Core Measurements & Output Files

- `signal_population.csv`: Per-signal level details (timestamps, prices, remaining MFE/MAE, path MAE, post-flip MFE, bucket).
- `signal_bucket_summary.csv`: Proportions and metrics for Buckets A, B, and C per threshold and direction.
- `remaining_regime_mfe.csv`: Remaining prevailing-regime MFE breakdown (0-0.10 ATR, 0.10-0.25 ATR, 0.25-0.50 ATR, 0.50-1.00 ATR, >1.00 ATR).
- `time_to_flip.csv`: Time-to-flip breakdown (0-30s, 30-60s, 60-120s, 120-300s, >300s, Never flips).
- `threshold_summary.csv`: Complete reliability metrics for each threshold.
- `direction_comparison.csv`: Head-to-head comparison of Short-RTH vs Long-RTH reliability.
- `study_report.md`: Executive summary answering the 7 core forecasting questions.

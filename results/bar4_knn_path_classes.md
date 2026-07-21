# Bar-4 KNN Path-Class Accuracy (per bar)

Predict the trade's remaining-path class from features through bar k. Accuracy rises with k PARTLY tautologically (more path observed). Compare accuracy to the majority-class baseline.

Class base rates (OOS): Failure 9%, Chop 11%, Continuation 32%, Runner 47% · majority baseline = 47%

| Bar | n | accuracy | AUC Failure | AUC Chop | AUC Continuation | AUC Runner | P@10% Failure | P@10% Chop | P@10% Continuation | P@10% Runner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | 20,000 | 42% | 0.84 | 0.68 | 0.63 | 0.65 | 59% | 36% | 49% | 63% |
| 5 | 20,000 | 47% | 0.88 | 0.73 | 0.67 | 0.71 | 59% | 40% | 53% | 77% |
| 6 | 20,000 | 50% | 0.90 | 0.76 | 0.70 | 0.74 | 54% | 35% | 57% | 89% |
| 7 | 20,000 | 54% | 0.91 | 0.80 | 0.72 | 0.77 | 48% | 36% | 63% | 96% |
| 8 | 19,874 | 57% | 0.93 | 0.84 | 0.74 | 0.80 | 45% | 36% | 66% | 99% |
| 9 | 18,200 | 61% | 0.94 | 0.86 | 0.76 | 0.82 | 40% | 35% | 67% | 100% |
| 10 | 16,704 | 64% | 0.95 | 0.87 | 0.78 | 0.84 | 36% | 33% | 70% | 100% |
| 11 | 15,307 | 66% | 0.95 | 0.89 | 0.80 | 0.85 | 31% | 34% | 68% | 100% |
| 12 | 13,974 | 69% | 0.96 | 0.90 | 0.81 | 0.86 | 26% | 32% | 66% | 100% |
| 13 | 12,795 | 72% | 0.96 | 0.92 | 0.83 | 0.88 | 24% | 31% | 67% | 100% |
| 14 | 11,736 | 74% | 0.96 | 0.92 | 0.85 | 0.89 | 20% | 28% | 67% | 100% |
| 15 | 10,737 | 76% | 0.97 | 0.93 | 0.86 | 0.90 | 17% | 27% | 65% | 100% |

## Confusion matrix at Bar 6 (rows = actual, cols = predicted)
| actual ↓ / pred → | Failure | Chop | Continuation | Runner |
| --- | --- | --- | --- | --- |
| Failure | 1,715 | 340 | 474 | 65 |
| Chop | 771 | 613 | 1,577 | 203 |
| Continuation | 681 | 421 | 4,159 | 1,509 |
| Runner | 648 | 338 | 3,067 | 3,419 |
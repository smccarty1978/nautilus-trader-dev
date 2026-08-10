# Model Score Level vs Remaining MFE and Confirmation Probability

## Verdict

Higher frozen-model probability is associated with a higher chance of reaching
the confirming flip before a 1-ATR stop and a shorter time to confirmation.
Remaining unconstrained MFE declines only modestly between Top-10 and Top-5;
the clearer decline occurs at the separately reported Top-2.5 and Top-1
reference levels. This is a descriptive location curve, not a trading rule.

## Independent fixed-level view, 2021–2025

| Side | Level | P(confirm before 1 ATR) | Median seconds to confirm | Median remaining MFE (ATR) |
|---|---|---:|---:|---:|
| Short | Top-10 | 52.4% | 120.0 | 1.767 |
| Short | interp-25 | 53.9% | 115.0 | 1.766 |
| Short | interp-50 | 55.5% | 105.0 | 1.749 |
| Short | interp-75 | 57.9% | 95.0 | 1.751 |
| Short | Top-5 | 59.7% | 85.0 | 1.720 |
| Short | Top-2.5 | 65.3% | 50.0 | 1.627 |
| Short | Top-1* | 74.4% | 40.0 | 1.613 |
| Long | Top-10 | 51.6% | 115.0 | 1.760 |
| Long | interp-25 | 53.1% | 110.0 | 1.757 |
| Long | interp-50 | 54.8% | 100.0 | 1.730 |
| Long | interp-75 | 56.3% | 95.0 | 1.698 |
| Long | Top-5 | 58.1% | 85.0 | 1.691 |
| Long | Top-2.5 | 64.1% | 55.0 | 1.649 |
| Long | Top-1* | 71.5% | 40.0 | 1.543 |

\*Top-1 exists in the accepted canonical threshold contract; it is not treated
as an artifact-frozen reference threshold.

## Answers

1. Confirmation survival rises smoothly from Top-10 to Top-5: 52.4% to 59.6%
   for shorts and 51.6% to 58.1% for longs.
2. Remaining MFE does not disappear rapidly on that ladder: it falls by only
   0.047 ATR for shorts and 0.069 ATR for longs from Top-10 to Top-5.
3. There is no sharp knee within the fixed Top-10→Top-5 probability ladder.
   The later Top-2.5/Top-1 reference points have shorter confirmation times and
   less remaining MFE.
4. The midpoint is closest to the requested 50–55% region: 55.4% short and
   54.8% long; it retains median remaining MFE of 1.749 and 1.730 ATR.
5. Among levels with at least 50% confirmation, canonical Top-1 has the least
   median remaining MFE (1.613 short, 1.543 long). Within the primary five-step
   ladder alone, Top-5 is the least-remaining-MFE point.
6. The largest remaining MFE subject to >=50% confirmation is Top-10 for both
   sides (1.767 short, 1.760 long).
7. The direction-specific curves are similar: probability rises steadily,
   confirmation time falls, and the Top-10→Top-5 MFE reduction is modest.
8. Year and direction detail is in `results/year_direction_breakdown.parquet`.
   Calendar 2025 remains development data, not clean threshold OOS.

The Top-10-armed-later view is persisted separately in the machine-readable
curve and produces the same broad progression; it is not pooled with the
independent view.

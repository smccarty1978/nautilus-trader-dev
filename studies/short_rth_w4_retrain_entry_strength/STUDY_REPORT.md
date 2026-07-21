# Short-RTH W4 Retrain Entry Strength — Study Report

## Decision: `SHORT_RTH_BASELINE_STILL_BEST`

No short-RTH-only model trained on the score-independent 2021-2024 surface
comes close to matching, let alone beating, the current pooled W4 threshold.
Every model, at every retention band, on both 2025 (dev) and 2026 (sealed),
is either unprofitable or barely breakeven — nowhere near Baseline A's
~$24-31/trade. Keep the current 0.688350 threshold; do not promote any
retrained model to NT schedule-driven validation.

## Phase 0 — data readiness (prerequisite, passed)

`PHASE0_PASS`. Joined the 149 causal features onto the 2021-2024 labeled
surface (100% join rate, all 4 years) and built full-surface Policy A labels
for 2025 (198,255 rows) and 2026 (63,021 rows) using the identical, unmodified
labeling functions already used and audited for 2021-2024. Re-verified the
known controls exactly: 650/650 (2025) and 222/222 (2026) crossing candidates,
0 mismatches, 0 rows missing from the feature-joined surface.
(`results/phase0_summary.md`, `results/phase0_manifest.json`.)

## Model diagnostics

| Model | Train AUC | 2025 AUC | 2026 AUC |
|--|--:|--:|--:|
| Logistic regression | 0.562 | 0.529 | 0.518 |
| HistGradientBoosting (depth 3) | 0.658 | 0.526 | 0.518 |
| W4 score (frozen, non-retrained) | n/a | 0.500 | 0.493 |

Both trained models show a clear train-vs-dev AUC gap (worse for GBT: 0.658
train vs 0.526 dev), a classic overfitting signature — the GBT is fitting
train-specific structure that does not generalize. Out-of-sample AUC for
both trained models sits barely above chance (0.52-0.53), and the frozen W4
score has **zero discriminative power** for this specific target on the
full surface (AUC ≈ 0.50 on both years) — expected, since W4 was calibrated
to detect "regime weakness," not specifically "will this get stopped by a
1.25×ATR move within 300s," and it was never tuned against this population.
Calibration deciles (`results/calibration_deciles.csv`) confirm only a weak,
partially non-monotonic relationship between predicted score and actual
stop-hit rate out of sample — consistent with the project's established
pattern that "high AUC ≠ PnL discrimination" cuts both ways: here AUC is
*also* weak, and PnL confirms it, not contradicts it.

Top logistic-regression features by |coefficient|:
`fraction_of_time_on_favorable_side` (−0.71), `fraction_of_time_on_adverse_side`
(−0.65) — both intuitive (more time already favorable ⇒ lower predicted
stop risk). GBT's top permutation-importance feature
(`aligned_price_minus_center_5m`) carries only 0.0058 mean importance —
weak everywhere. Full table: `results/feature_importance.csv`.

## Layer 1 — row-level diagnostics

`results/retention_band_results.csv`. Retention filtering does shift the
row-level stop-hit rate somewhat (e.g., GBT 2025 hit-rate among retained
rows drops from 32.7% at 100% retention toward the low-to-mid 20s% at 20%
retention), confirming the models pick up *some* real signal at the row
level. But row-level PnL here is explicitly **not deployable** (rows overlap
heavily within a regime) — the real test is Layer 2.

## Layer 2 — one-entry-per-regime deployable policy (primary comparison)

`results/economic_results.csv`, `results/monthly_results.csv`,
`results/exit_reason_attribution.csv`. Full table has all 3 models × 6 bands
× {train, 2025, 2026}; key facts:

- **The 100%-retention "take the first eligible checkpoint" policy is
  already a much worse population than the current W4 threshold-crossing
  population**, independent of any model: 1,678 trades in 2025 (net
  −$10,613, −$6.32/tr) and 532 in 2026 (net −$10,799, −$20.30/tr) — versus
  Baseline A's 650 trades/+$15,366 (2025) and 222 trades/+$6,884 (2026) on
  the *same year*. This reconfirms and extends the prior threshold-ladder
  finding (`[[short_rth_threshold_ladder]]`): waiting for the calibrated W4
  score threshold, not just "minimal establishment," is doing most of the
  work. Filtering this weaker starting population post-hoc cannot fully
  recover what was lost by abandoning the calibrated signal.
- **No (model, band) combination reaches positive economics reliably.**
  The single best 2025 result across all 18 combinations is GBT at 35%
  retention: 969 trades, net +$4,606, **+$4.75/trade**, PF 1.029 — positive,
  but roughly 1/5th of Baseline A's +$23.64/trade for 2025 alone. Every
  other combination on 2025 is flat-to-negative. On 2026, GBT/logreg/W4
  comparator all range from mildly to catastrophically negative at every
  band (worst: logreg 20% retention, −$66.23/trade).

## Layer 3 — fixed-807 overlay

`results/layer3_fixed807_overlay.csv`. Applying any model at 100% retention
to the exact 807 confirmed-pocket regimes **moves the entry timestamp on
essentially every trade** (603/604 in 2025, 203/203 in 2026 — i.e., the
"first eligible checkpoint" is almost never the same moment as the
calibrated W4 threshold crossing) and swings the economics from Baseline
B's **+$20,304 (2025) to −$111,400** on the identical 604 regimes. Increasing
selectivity recovers some of this (best: W4-comparator at 20% retention,
−$54.88/tr 2025, −$74.33/tr 2026) but never gets anywhere near positive,
let alone the original +$33.47/trade. This is the single clearest piece of
evidence that entry *timing* — not just entry *filtering* — is the dominant
factor, and no post-hoc classifier recovers it.

## Selection (2025-only) and sealed 2026 result

Selected per SPEC's discipline (highest 2025 Layer-2 per-trade PnL, ties by
PF): **GBT @ 35% retention**. Selection gate (`results/manifest.json` →
`selection_gate`):

| Check | Result |
|--|--|
| 2025 improves over Baseline A ($/tr or PF) | **FAIL** (+$4.75 vs +$23.64/tr) |
| 2026 positive | **FAIL** (−$32.36/tr) |
| 2026 not materially worse than baseline | FAIL (moot — already negative) |

The selected model fails the *very first* gate criterion — it never
beats baseline on the year it was selected on — so the "overfits 2025"
label does not strictly apply (that label is for candidates that *looked*
good on 2025 and then failed 2026; this one never looked good). The correct
terminal label is `SHORT_RTH_BASELINE_STILL_BEST`.

## Failure attribution (GBT @ 35%, vs that same model's own 100%-retention schedule)

| | 2025 | 2026 |
|--|--:|--:|
| Regimes removed by filtering | 709 | 193 |
| Pre-alignment stops avoided | 187 | 57 |
| $ saved from avoided stops | +$61,508 | +$20,179 |
| Winning trades removed | 365 | 107 |
| $ lost from removed winners | **−$153,115** | **−$46,040** |
| ...of which opposing-flip winners | 163 (−$107,010) | 33 (−$25,180) |
| Timeout rate (full → selected) | 47.9% → 43.9% | 50.0% → 41.9% |
| Post-align-stop rate (full → selected) | 0.48% → 0.83% | 0.38% → 1.47% |
| Monthly concentration (top-1 month share) | 24.0% | 48.1% |

**This is the clearest possible confirmation of the "clips winners" failure
mode**, present even in the single best-looking (2025) result: for every
dollar saved by avoiding a pre-alignment stop, the model discards **2.5x
more** in removed winning trades (dominated by opposing-flip winners — the
single most valuable exit-reason cohort throughout this entire project's
history). 2026 shows the identical pattern (2.3x). The model's exposure
reduction is real but backwards: it disproportionately filters out the
trades that would have gone on to win via the opposing-flip cohort,
consistent with `[[short_rth_threshold_ladder]]`'s finding that earlier/looser
entry timing systematically forfeits opposing-flip winners to the
confirmation clock.

## Final report — answers

1. **Does a short-RTH-only model improve over the current W4 threshold
   baseline?** No. Best 2025 result (+$4.75/tr) is ~20% of Baseline A's
   economics; every other combination is flat or negative.
2. **Does it reduce pre-alignment stop-outs?** Yes, modestly (187/57 stops
   avoided, 2025/2026) — but this is the *only* positive finding.
3. **Does it preserve the opposing-flip winner cohort?** No. It removes
   163/33 opposing-flip winners (2025/2026), costing far more than the
   avoided stops save (2.3-2.5x).
4. **Does the improvement survive sealed 2026?** There is no 2025
   improvement to survive — the best 2025 candidate fails 2026 outright
   (−$32.36/tr).
5. **Monthly stability?** Worse under selection: 2026's single best month
   (2026-02) accounts for 48% of the selected schedule's total absolute
   monthly PnL magnitude, versus 24% in 2025 — the result is more, not
   less, month-concentrated after filtering.
6. **Is any model strong enough to promote to NT schedule-driven
   validation?** No.
7. **Should we keep the current W4 short-RTH Policy A baseline?** Yes —
   keep the confirmed 0.688350-threshold short-RTH pocket
   (`[[short_rth_threshold_ladder]]`, `[[nt_short_rth_policy_a_confirmed]]`)
   and proceed to Phase 2 live-W4 NT validation rather than any retrained
   variant.

## Audit

`audit/audit.md` — **PASS, 0 CRITICAL, 3 WARNING, 5 NOTE**. No look-ahead
bias or train/dev/test discipline violation found across all 5 new scripts;
retention cutoffs are frozen strictly on 2025 and applied unchanged to
2026/train; the imputer/scaler and GBT model are fit train-only; selection
reads only 2025 economics; the one-entry-per-regime schedule picks the
temporally-first eligible checkpoint (no hindsight); none of the 149
features are outcome-derived. The 3 warnings (incomplete gate automation
for edge cases, no minimum-trade-count floor, the frozen W4 comparator not
excluded from the "best" candidate pool) did not affect this specific run's
result (verified: GBT won selection on its own merits, not via any of the
unguarded paths) but should be closed before any future rerun of this code
is trusted unattended.

## What would need to change before revisiting this branch

Per the audit's Note on "the Layer-2 population being materially larger
than Baseline A's" — the fundamental issue is that this study filtered a
*fundamentally weaker* starting population ("first eligible checkpoint")
rather than re-ranking the *same* population the calibrated W4 threshold
already selects. A future attempt would need to either (a) train a model
that reproduces the calibrated-threshold-crossing population as its
starting universe (not just "established"), which reintroduces the
original circularity problem this study's predecessor was built to avoid,
or (b) accept that entry timing, not entry filtering, is the lever, and
redirect effort toward Phase 2 live-W4 NT validation instead of further
retraining attempts on this population definition.

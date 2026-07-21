# Study Report: Short-RTH Pure Regime-Flip Prediction

**Study directory:** `studies/short_rth_pure_flip_prediction_enriched/`
**Final decision: `PURE_FLIP_SIGNAL_INCONCLUSIVE`**

## Summary

A single, pure market-state target (`bearish_regime_flip_within_300s`,
independent of any trade-simulation mechanics — a correction versus the
prior age-gate study, see below) is indeed far more learnable at the
**row level** than the prior multi-outcome target: the best combo (F3
combined features, HistGradientBoostingClassifier) reaches row-level AUC
0.671 (2025) / 0.670 (2026) with top-decile lift 2.03x/1.93x — comfortably
clearing even this study's "strong signal" bar. But a completion-gate audit
caught that this headline result was never checked against the study's own
regime-level diagnostics (computed specifically because rows overlap
heavily within a regime — mean 118 rows/regime). Those show **regime-level
AUC of 0.47-0.53 across all 8 (feature_set, model) combinations, both
years — statistically indistinguishable from chance.** The gate was
corrected to require both views to agree; it now correctly returns
`PURE_FLIP_SIGNAL_INCONCLUSIVE`. The row-level signal is real (not noise),
but it does not currently translate into regime-level early-warning
usefulness, which is the practically relevant question for any follow-up
stop/exit study.

## Correction versus the prior study (scout-pass finding, before any results)

Before this study's own results: the primary label was rebuilt from scratch
because `[[age_gate_120_vs_240_inconclusive]]`'s `bearish_flip_within_300s
= aligned` reuse was found to conflate "regime flipped within 300s" with
"a hypothetical trade survived Policy A's 1.25xATR pre-alignment stop long
enough to see it" — ~1-1.4% of rows/year were mislabeled as a result (see
`SPEC.md` finding 1, and the correction now appended to that study's own
report). This study's `bearish_regime_flip_within_300s` is pure
`confirm_flip_ns`/`observation_time` arithmetic, verified by a hand-computed
regression test before the full 6-year run, and confirmed clean by both a
pre-execution and a completion-gate audit.

## 1. Can the enriched features predict bearish regime flip within 300 seconds?

**At the row level, yes, clearly** — every one of the 8 combos beats a
coin flip decisively (row-level AUC 0.648-0.671 across all combos/years,
vs. this study's own multi-outcome predecessor's near-random 0.50-0.58).
**At the regime level, no** — the same features/models, evaluated on one
de-duplicated row per regime (the peak-score checkpoint), separate true
early-warning cases from false alarms no better than chance (AUC 0.47-0.53,
all 8 combos, both years). The honest answer combines both: the features
carry real information about *whether a checkpoint looks like the tail-end
of a regime that's about to flip*, but not enough to reliably identify,
in advance, *which specific moment within a given regime* is the genuine
early-warning signal versus a false alarm.

## 2. Which feature set worked best: existing, volume/delta, price-level, or combined?

F3 (combined) has the best row-level AUC for GBT in both years (0.6712/0.6700)
and the best row-level average precision throughout
(`results/model_metrics.csv`). But the margin over F1 (volume/delta only,
GBT: 0.6678/0.6678) is small (≤0.005 AUC), and F0 (existing features only,
no enrichment at all) already reaches 0.656-0.663 — within 0.01-0.02 of the
full F3 result. Combined is best, but the enrichment's *marginal*
contribution over the pre-existing feature set is modest at the row level,
and (per §1) none of the feature sets clear the regime-level bar.

## 3. Did volume/delta features add signal?

Yes, modestly: F1 vs F0 raw AUC improves by 0.004-0.012 across model/split
combinations, and in the logistic-regression feature-family breakdown,
volume/delta features carry 70.4% of the coefficient mass when added to F0
alone (`results/feature_family_contribution.csv`) — a real, non-trivial
contribution, consistent with `[[short_rth_enriched_retrain_overfits_2025]]`'s
finding that these features carry genuine (if not always monetizable)
signal.

## 4. Did price-level context features add signal?

Yes, similarly: F2 vs F0 raw AUC improves by 0.002-0.014, and price-level
features carry 64.3% of logreg's coefficient mass when added to F0 alone,
and remain the largest single family (42.9%) even in the full F3 combined
model — larger than volume/delta's 36.1% share there.

## 5. Did the signal survive sealed 2026?

**Row-level: yes, remarkably well** — the best combo's AUC moves by only
0.001 between 2025 (0.6712) and 2026 (0.6700), the most stable result of
any study in this line of work. **Regime-level: the question is closer to
moot than "survived,"** since regime-level performance never exceeded
chance in 2025 to begin with (AUC 0.481) — 2026 (AUC 0.521) is nominally
higher but still well below the 0.55 bar and not a meaningful improvement
given the underlying near-chance baseline.

## 6. Is the model calibrated enough to be useful?

Yes — and more interestingly, the **raw (uncalibrated)** scores were
already well-calibrated: for the selected combo, raw Brier score
(0.1733/0.1797, 2025/2026) is nearly identical to isotonic-calibrated
(0.1729/0.1792) and sigmoid-calibrated (0.1731/0.1790) — differences of
≤0.0005, far below the SPEC's 0.02 "materially different" threshold.
`HistGradientBoostingClassifier` produced native probability estimates that
needed essentially no correction on this population. Calibration is
reported (`results/calibration_deciles.csv`) but adds negligible value here.

## 7. At the regime level, does the model give useful lead time before flips?

**Not reliably.** For the selected combo at the top-10%-score threshold
(frozen from 2025): `top10_missed_flip_rate` ≈ 0.54 (2025) / 0.54 (2026) —
**over half of regimes never receive a top-10% alarm during their own
genuine 300s warning window.** `top10_false_positive_rate` ≈ 0.52 (2025) /
0.48 (2026) — of the regimes that DO get an alarm, roughly half of those
alarms fire prematurely (before the flip is genuinely within 300s).
Median lead time among regimes that do cross the threshold is 275-350s —
superficially reasonable, but this statistic is conditioned on the ~61% of
regimes that cross at all, and doesn't account for the high false-alarm
rate among those crossings. Root cause (traced directly, not speculated):
warning-zone rows (the true positive window) already make up a mean 44%
/ median 37.5% of a typical regime's total row count — the "early warning"
framing is less applicable here than in domains where the positive window
is a small minority of the entity's lifetime, which likely also explains
why regime-level discrimination is so much harder than row-level.

## 8. Does high predicted flip probability correspond to more or less pre-flip adverse excursion?

Not analyzed in depth here — per SPEC, this follow-up diagnostic is gated
on the primary model showing "signal viability," and the regime-level
result (§7) means this study does not clear that bar cleanly enough to
justify building it out further. `adverse_move_1p25A_before_bearish_flip`
is joined as a diagnostic in `results/selected_model_predictions_2025.parquet`
/`_2026.parquet` for any follow-up analysis, but no decile-level adverse-
excursion table was built, consistent with not over-investing in a
follow-up study for an inconclusive primary result.

## 9. Does high predicted flip probability correspond to useful post-flip followthrough?

Same as §8 — `post_flip_mfe_atr_300s`/`_600s` are joined in the predictions
parquets for future use but not decile-analyzed here, for the same reason.

## 10. Should the next study move to stop/exit design, or is flip prediction not learnable enough yet?

**Neither, directly.** Row-level flip prediction IS learnable (§1) — the
null hypothesis ("features do not predict flips with enough stability") is
rejected at the row level. But the regime-level result means this is not
yet a foundation solid enough to build a stop/exit study on top of, since
that would require knowing *when within a regime* the signal is
trustworthy, which is exactly what regime-level analysis shows this model
doesn't yet reliably tell you. The most promising next bounded step is
**not** stop/exit design — it's understanding *why* row-level and
regime-level performance diverge so sharply (the warning-zone-is-44%-of-
the-regime finding in §7 is a strong lead) and whether a different
labeling/aggregation choice (e.g., predicting time-to-flip as a regression,
or restricting evaluation to a genuinely small tail of each regime) would
close that gap. This is consistent with, and reinforces,
`[[short_rth_enriched_retrain_overfits_2025]]`'s and
`[[w4_symmetric_bracket_race]]`'s recurring finding that *entry timing
within a regime* — not feature quality — is this population's dominant
unsolved problem.

## Audit

Two passes, per this project's pre-execution-audit standing rule
(`[[feedback_preexecution_audit_gate]]`):

1. **Pre-execution** (on synthetic-data-tested label logic, before the
   6-year run): 0 CRITICAL, 3 WARNING/3 NOTE — none blocking, the core
   fix (finding 1) confirmed correctly implemented and genuinely tested
   (not a tautological test).
2. **Completion-gate** (full pipeline, after the run): **1 CRITICAL** —
   the selection gate computed `PURE_FLIP_SIGNAL_STRONG` from row-level
   metrics alone, never reading the regime-level diagnostics the pipeline
   had already produced. Fixed: `select_and_gate.py`'s gate now requires
   regime-level AUC > 0.55 (both years) as well, corrected decision is
   `PURE_FLIP_SIGNAL_INCONCLUSIVE`. Re-verified: no look-ahead bias,
   train/serve skew, or feature/label leakage found anywhere in the
   pipeline — the unusually strong and stable row-level result was
   independently investigated (given how suspicious that stability looked)
   and traced to a real, if narrower-than-hoped, signal, not a leak.

See `audit/audit.md` for the full two-pass record and the post-audit fix.

## Primary caveats

1. **The row-level vs. regime-level divergence is the central finding of
   this study**, not a footnote — see `[[row_level_vs_entity_level_auc_rule]]`,
   a new standing methodology note this study's audit prompted.
2. **F0 (no enrichment) already gets most of the row-level AUC** (0.656-
   0.663 vs F3's 0.671) — the enrichment's marginal value is real (§3-4)
   but modest, and none of it closes the regime-level gap.
3. Follow-up adverse-excursion/follow-through decile diagnostics (§8-9)
   were intentionally not built out, given the inconclusive primary result.

## Final decision: `PURE_FLIP_SIGNAL_INCONCLUSIVE`

Row-level signal is real and stable across years; regime-level signal
(the practically relevant view, given non-independent rows) is
indistinguishable from chance for every feature set and model tested. Do
not proceed to a stop/exit design study on this foundation. The productive
next step is understanding the row-level/regime-level gap itself (§10),
not iterating on features or models within the current framing.

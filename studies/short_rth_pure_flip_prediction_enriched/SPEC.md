# Short-RTH Pure Regime-Flip Prediction Study

## Status

**COMPLETE. Final decision: `PURE_FLIP_SIGNAL_INCONCLUSIVE`.** See
`STUDY_REPORT.md` for the full write-up. Row-level signal is real and
stable (best combo F3/gbt: AUC 0.671/0.670, top-decile lift 2.03x/1.93x,
2025/2026) — but a completion-gate audit caught that the initial
`PURE_FLIP_SIGNAL_STRONG` call never consulted the regime-level diagnostics
already computed, which show regime-level AUC ≈0.47-0.53 (chance) across
all 8 combos, both years. Gate corrected to require both views; do not
proceed to a stop/exit design study on this foundation. Audit: 2 passes
(pre-execution + completion-gate), 0 CRITICAL remaining after the gate fix.

## Decision to inform

Whether the enriched feature set (existing 149 + 461 new OHLCV volume/delta
+ price-level context) can predict a bearish regime flip within a fixed
300-second forward horizon from qualified bullish-RTH-regime checkpoints —
a pure signal-model question, decoupled from any stop/exit/trade-management
design. Not a trading-promotion study.

## Primary hypothesis

A single, market-state-only target (`bearish_regime_flip_within_300s`) is
cleaner and more stable to learn than the prior enriched retrain's
5-class outcome-aware target, which mixed flip occurrence with stop-survival
and follow-through into one objective.

Null hypothesis: the enriched features do not predict bearish regime flips
with enough stability (2025→2026) to justify a follow-up stop/exit study.

## Scout-pass findings (grounds this SPEC in verified fact, not assumption)

1. **CRITICAL correction versus `[[age_gate_120_vs_240_inconclusive]]`:
   Policy A's `aligned` column is NOT a pure regime-transition label — it
   conflates "did the regime flip within 300s" with "did a hypothetical
   short trade survive (not hit the 1.25×ATR pre-alignment stop) long
   enough to see it."** Traced directly in
   `studies/fable5_specialized_w4/fable5_common.py::simulate_trade_arrays`
   (lines 209-233): the bar-by-bar replay loop `break`s and returns
   `reached_aligning_flip=False` the moment the 1.25×ATR stop is touched —
   **even if the regime's actual confirmed flip (`confirm_flip_ns`) would
   still have occurred later, within the same 300s window.** The prior
   age-gate study's `bearish_flip_within_300s = aligned` reuse (defended at
   the time as "Policy A's own aligned is defined as exactly this") was
   wrong on exactly the case this study's own brief calls out ("do not
   censor as negative simply because Policy A would have stopped out
   first"). **Verified directly on real data, all 6 years**: rows where
   `hit_pre_alignment_stop == True` AND the true regime flip
   (`confirm_flip_ns - observation_time <= 300s`) still occurs within the
   window, but `aligned == False`:

   | Year | Mislabeled rows | % of year |
   |--|--:|--:|
   | 2021 | 2,010 | 0.95% |
   | 2022 | 2,710 | 1.41% |
   | 2023 | 2,299 | 1.12% |
   | 2024 | 2,191 | 1.07% |
   | 2025 | 1,879 | 0.95% |
   | 2026 | 775 | 1.23% |

   Consistent ~1-1.4% every year — small but systematic and real, not
   noise. **This study's primary label is therefore built fresh, by pure
   arithmetic on `confirm_flip_ns` vs. `observation_time`, never via
   `aligned`.** `time_to_bearish_flip_s` and `bearish_flip_within_600s`
   from the age-gate study were already built this correct way (pure
   arithmetic, not `aligned`-derived) and are reused unchanged; only
   `bearish_flip_within_300s`/`no_flip_before_timeout` were affected. A
   correction note has been added to the age-gate study's own record (see
   `[[age_gate_120_vs_240_inconclusive]]`); its qualitative conclusion
   (`AGE_GATE_INCONCLUSIVE`) is unaffected in direction — the systematic
   understatement applies near-identically to both gates being compared,
   since the affected rows are a property of Policy A simulation mechanics,
   not of the age threshold — but the absolute flip-rate figures reported
   there were biased low by ~1-1.4pp.
2. **No censoring is actually needed for the primary label on this
   population.** `confirm_flip_ns` is the already-confirmed next-opposing-
   flip timestamp (sourced from `canonical_regime_timeline`, joined via the
   same mechanism as the age-gate study) and is present for 100% of rows in
   `full_{year}.parquet` (`label_available == True` for all 198,255/198,255
   2025 rows, confirmed previously) — there is no row where "flip within
   300s" is unknowable, only rows where it's known to be false (flip
   happens later, or the regime is still the last one and never flips in
   observed data — also already resolved by `confirm_flip_ns`/`label_error`
   handling upstream). The brief's censoring requirement is satisfied
   trivially (0 censored) and reported as such, not skipped.
3. **Canonical input, population, and feature-set construction are
   identical to the two prior enriched studies** — `full_{year}.parquet`
   (`[[ohlcv_volume_delta_price_level_features_accepted]]`), full-checkpoint
   surface (not first-eligible-only, per this brief), 120s gate unchanged
   (`[[age_gate_120_vs_240_inconclusive]]` found no learnability benefit to
   240s), F0/F1/F2/F3 feature sets and one-hot position-column encoding
   reused verbatim from `[[short_rth_enriched_retrain_overfits_2025]]`'s
   `phase0_prepare_data.py` (`find_position_cols`/`one_hot_position_cols`,
   imported not reimplemented). Row counts confirmed: 2021-2024 combined
   813,972 / 2025 198,255 / 2026 63,021 (matches the brief's expected
   scale exactly).
4. **The one-hot position-column encoding uses a fixed, a-priori category
   list** (`{ABOVE, BELOW, TOUCH, UNAVAILABLE}`), not a data-fit vocabulary
   — applying it uniformly across all years is not a train/dev/test leak
   (the brief's "do not leak 2025/2026 category levels into 2021-2024
   training transforms" concern applies to data-derived encodings; this
   encoding's category set is bounded and known before seeing any data, so
   there is nothing to leak). The `SimpleImputer`/`StandardScaler`
   statistics used by logistic regression, by contrast, ARE fit on
   2021-2024 only and applied unchanged to 2025/2026, per existing
   precedent — genuine train-only statistics stay train-only.
5. **Secondary diagnostic labels other than the 300s primary are reused
   from `[[age_gate_120_vs_240_inconclusive]]`'s `phase0_prepare_data.py`
   unchanged** (already fixed post-audit there): `bearish_flip_within_600s`,
   `time_to_bearish_flip_s` (pure `confirm_flip_ns` arithmetic, unaffected
   by finding 1), `post_flip_mfe_atr_{300,600}s` (raw-bar scan once per
   regime, gap-safe exclusive-boundary fix already applied),
   `bearish_flip_within_{300,600}s_and_followthrough_1A`,
   `adverse_move_1p25A_before_bearish_flip` (= `hit_pre_alignment_stop`,
   still valid for this diagnostic-only role — it correctly answers "did
   the stop-relevant adverse move happen," which is a different question
   from the primary label and is not being repurposed as a flip indicator
   here). Only `bearish_flip_within_300s` and `no_flip_before_timeout` are
   rebuilt from scratch per finding 1.

## Population

`NQ`, short setup context, prevailing bullish regime, RTH only (existing
remediated convention), 120s established-regime gate (unchanged, per
finding 3), **full checkpoint surface** (all eligible checkpoints per
regime, not first-eligible-only — explicit brief requirement, differs from
the age-gate study's first-eligible framing). Years 2021-2026.

## Primary label

```text
bearish_regime_flip_within_300s =
    1 if (confirm_flip_ns - observation_time) <= 300e9 (ns)
    0 otherwise
```

Built independently of `aligned`/Policy A stop simulation (finding 1). 0
censored rows on this population (finding 2) — reported, not assumed.

## Secondary diagnostic labels (never training targets)

`bearish_flip_within_600s`, `time_to_bearish_flip_s`,
`post_flip_mfe_atr_{300,600}s`, `bearish_flip_within_{300,600}s_and_followthrough_1A`,
`adverse_move_1p25A_before_bearish_flip` (finding 5). Policy A outcomes
(`hit_pre_alignment_stop`, `hit_timeout`, `hit_post_alignment_stop`,
`opposing_flip_exit_positive`/loser split per
`[[short_rth_enriched_retrain_overfits_2025]]`'s mapping, `net_pnl`,
`exit_reason`) joined for post-hoc diagnostics only, never as a training
target or model-selection criterion.

## Feature sets

F0/F1/F2/F3 exactly as finding 3/4. Exclusions: provenance columns, `*_name`
columns, raw datetime/row-identifier columns, all outcome/label columns
(including the new primary and secondary labels themselves).

## Train/dev/test discipline

Train 2021-2024, dev/select 2025, sealed test 2026. No 2026 hyperparameter,
feature, threshold, calibration-refit, or label-design selection.

## Model families

Regularized logistic regression (train-only impute/scale) +
`HistGradientBoostingClassifier` (capped depth), same fixed hyperparameters
as `[[short_rth_enriched_retrain_overfits_2025]]`'s `train_and_evaluate.py`
(no hyperparameter search — a declared grid of size 1, satisfying "small
declared grid" without scope creep). Binary target
`bearish_regime_flip_within_300s`. 8 (feature_set × model) combos.

## Calibration

Per selected/promising combo: fit base model on 2021-2024; calibrate
(`sklearn.calibration.CalibratedClassifierCV`, `cv="prefit"`, both
`isotonic` and `sigmoid` available) using 2025 only; evaluate calibrated
AND raw scores on 2026; report both, flagged if materially different (>0.02
Brier-score difference). Never calibrated on 2026.

## Required diagnostics

Data readiness, label quality, model metrics (train/2025/2026 × AUC/average
precision/Brier/log-loss), row-level decile diagnostics (incl. joined
Policy-A-diagnostic-only columns, explicitly labeled non-deployable),
regime-level diagnostics (max pre-flip probability, first-crossing lead
time at top-20/10/5% thresholds, regime-level AUC, false-positive/missed-
flip regime rates), feature-family contribution (existing/volume-delta/
price-level, same family-mapping logic as
`[[short_rth_enriched_retrain_overfits_2025]]`).

## Signal viability gate (not a trading-promotion gate)

Minimum: 2025 AUC meaningfully above 0.55, top-decile flip rate materially
above base rate, calibration not obviously broken; 2026 AUC remains above
0.55, top-decile lift remains above base rate, decile curve not inverted,
not driven by one month. Stronger: 2025 AUC≥0.60 AND 2026 AUC≥0.58 AND
top-decile lift≥1.50× both years.

## Forbidden

No training on Policy A PnL/pre-alignment-stop/opposing-flip-winner/
confirmation-timeout/post-alignment-stop; no entry/stop/exit optimization;
no deployable trade policy; no 2026 selection of any kind.

## Required artifacts

```text
studies/short_rth_pure_flip_prediction_enriched/
  SPEC.md
  results/data_readiness.csv
  results/label_quality_by_year.csv
  results/model_metrics.csv
  results/calibration_deciles.csv
  results/regime_level_diagnostics.csv
  results/feature_family_contribution.csv
  results/feature_importance.csv
  results/selected_model_predictions_2025.parquet
  results/selected_model_predictions_2026.parquet
  results/manifest.json
  audit/audit.md
  STUDY_REPORT.md
  REPRODUCE.md
```

Save best-2025-selected model outputs even if no model clears the viability
gate.

## Final decision labels

```text
PURE_FLIP_SIGNAL_STRONG
PURE_FLIP_SIGNAL_WEAK_BUT_REAL
PURE_FLIP_SIGNAL_INCONCLUSIVE
PURE_FLIP_SIGNAL_FAILS_2026
PURE_FLIP_SIGNAL_NOT_LEARNABLE
PURE_FLIP_STUDY_REMEDIATION_REQUIRED
```

## Final report must answer

1. Can the enriched features predict bearish regime flip within 300s? 2.
Which feature set worked best? 3. Did volume/delta features add signal? 4.
Did price-level features add signal? 5. Did the signal survive sealed 2026?
6. Is the model calibrated enough to be useful? 7. Does the model give
useful regime-level lead time? 8. Does high predicted probability correspond
to more/less pre-flip adverse excursion? 9. Does high predicted probability
correspond to useful post-flip followthrough? 10. Should the next study move
to stop/exit design?

## Process note (self-imposed, per standing project feedback)

`[[feedback_windows_background_training_jobs]]` and the pre-execution-audit
recurrence noted in `[[feedback_preexecution_audit_gate]]`: the corrected
primary-label logic (finding 1) is NEW derivation code, not a verbatim
reuse. Before running the full 6-year pipeline, a small hand-computed test
(synthetic rows spanning the exact `hit_pre_alignment_stop`-but-still-
flips-within-300s edge case) will be written and passed, and the
lookahead-auditor will review the label-construction logic on that small
sample before the expensive multi-model training run — not only at the end.

## Guardrails

Mandatory `lookahead-auditor` pass, 0 CRITICAL required before accepting
results. No entry/exit optimization; diagnostic-only Policy A joins.

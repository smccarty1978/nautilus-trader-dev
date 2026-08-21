# STUDY REPORT: ym_prev5_range_position

**Type:** One-day descriptive TRAIN pilot (feature-expansion decision only)
**Instrument:** YM (XCBT) · **Date:** 2024-09-03 · **Session:** RTH (08:30-15:15 CT)
**Feature under study:** `latest_1m_close_position_prev5_range` (status: `provisional`)
**Run id:** `20260818_132043_ym_prev5_range_position_day`
**Execution composite (sealed):** `4f28b073556e060e91079706473f837aaa7e7bb09b82a5bbbc61d25ff410c758`

## Governed workflow trail

- `research_decision.yaml` → `study.yaml` → `create_study.py` → `compile_study.py` → decision-fidelity `PASSED`
- Deterministic preflight: `CLEAR` (3 iterations; see below)
- Split pre-execution audit: 3 passes, both gates `CLEAR` at pass_03
  (`audit/pass_01.md`..`pass_03.md`, `audit/contract_pass_01.md`..`contract_pass_03.md`)
- PREEXEC seal issued against composite `4f28b073...`
- Collect run via `backtests/run_nt_study.py --mode collect --stage day --date 2024-09-03`
- Deterministic smoke validation: `scripts/validate_smoke.py` → `ACCEPTED`
  (0 future-source violations, exact timestamp equality True, 1/1 declared feature emitted)
- Governed analysis via `research/analysis/*` (loader/spec/metrics/slices/reporting), driver
  script logged below; outputs in `results/tables/` and `results/analysis_context.json`

## Defects found and fixed during this run (all in shared canonical infrastructure)

1. **`strategies/flip_prediction_collector.py`** never instantiated/updated
   `RangePositionTracker` — the study's sole feature would have been `None` on every
   row. Found independently by both `contract-checker` (pass_01, BLOCKED) and
   `lookahead-auditor` (pass_01, non-blocking referral). Fixed by wiring the tracker
   the same way `WickTracker` already was (import, `__init__`, `_handle_1m_bar`
   update, `merged_raw` merge). Re-audited CLEAR at pass_02.
2. **`backtests/nt_runtime/engine_builder.py::create_futures_instrument`** never
   derived `price_precision` from `price_increment`; it silently inherited an
   ES-shaped template default of 2, which crashed instrument construction for YM
   (`price_increment="1"`, precision 0). Fixed by deriving precision from the
   increment's decimal places (matching the identical formula already used in
   `catalog_materializer.py`). No behavioral change for ES/NQ (both derive to 2,
   identical to the prior default). Re-audited CLEAR at pass_03.
3. **`research/analysis/loader.py::load_collection`** read the feature-list hash only
   from `study.yaml` (which the study factory never backfills), instead of the
   authoritative value the factory already computes and stores in
   `compiled_study.json`'s `contracts.feature_contract.feature_list_sha256`. This
   blocked `validate_collection`'s feature-contract check for every study, not just
   this one. Fixed to prefer the compiled-contract value. This is analysis-layer
   code outside the sealed NT execution composite (it runs after collection, not
   during it), so it did not require a new causal/contract audit pass; regression
   suite (`test_analysis_loader.py`, `test_analysis_redteam_regressions.py`, 108
   tests) passed clean after the change.

All three are pre-existing latent defects in shared framework code exposed by being
the first study to exercise the YM provisioning path and the restored Analysis
Harness end-to-end; none are specific to this research question's population or
target logic.

## Population

| Metric | Value |
|---|---|
| Candidates | 1,038 |
| Observations | 1,038 |
| Bullish (long) candidates | 397 |
| Bearish (short) candidates | 641 |
| LABELED_POSITIVE | 321 |
| LABELED_NEGATIVE | 706 |
| CENSORED | 11 |
| Uncensored target base rate | 321 / 1027 = 31.26% |
| First candidate (CT) | 2024-09-03 08:34:15 |
| Last candidate (CT) | 2024-09-03 15:12:50 |

Source: `runs/20260818_132043_ym_prev5_range_position_day/collection/collection_manifest.json`
(`candidate_disposition_reconciliation`, `passed: true`, 0 undisposed/orphaned/duplicate).

## Feature quality — `latest_1m_close_position_prev5_range`

| Stat | Value |
|---|---|
| Available | 1,038 |
| Null | 0 |
| Null rate | 0.0% |
| Distinct | 111 |
| Mean | 0.5029 |
| Std | 0.3901 |
| Min | -0.8919 |
| P10 | 0.0667 |
| P25 | 0.2778 |
| Median (P50) | 0.4915 |
| P75 | 0.8000 |
| P90 | 0.9492 |
| Max | 1.4605 |

Source: `results/tables/descriptive_all.json` (`research/analysis/metrics.py::descriptive_summary`).

## Positive vs negative target

| Group | n | Mean | Median | Std | P10 | P90 |
|---|---|---|---|---|---|---|
| Positive | 321 | 0.6281 | 0.5500 | 0.3205 | 0.2778 | 1.0526 |
| Negative | 706 | 0.4502 | 0.4231 | 0.4061 | -0.0182 | 0.9038 |

Mean gap: +0.178 (≈0.45 pooled-SD). `results/tables/descriptive_positive.json`,
`descriptive_negative.json`.

## Bullish vs bearish candidates

| Group | n | Mean | Median | Std |
|---|---|---|---|---|
| Bullish (long) | 397 | 0.7762 | 0.8026 | 0.3198 |
| Bearish (short) | 641 | 0.3336 | 0.3596 | 0.3291 |

Mean gap: +0.443 (≈1.1 pooled-SD) — substantially larger than the target-conditioned
gap. `results/tables/descriptive_bullish.json`, `descriptive_bearish.json`.

## Structural buckets (predeclared, harness `STUDY_FIXED_EDGES`)

| Bucket | n | Population share | Labeled n | Positive | Target rate (of labeled) |
|---|---|---|---|---|---|
| feature < 0 | 76 | 7.3% | 71 (5 censored) | 0 | 0.0% |
| 0 ≤ feature ≤ 1 | 887 | 85.5% | 881 (6 censored) | 280 | 31.8% |
| feature > 1 | 75 | 7.2% | 75 (0 censored) | 41 | 54.7% |

Source: `results/tables/by_fixed_edges.json`, cross-checked by direct groupby on the
joined candidates/observations frame (diagnostic only, matches harness output exactly).

## Simple distribution-separation statistic

The raw feature value used directly as a "score" against the target (no fit, no
threshold — `research/analysis/metrics.py::classification_bundle`):

| Metric | Value | n |
|---|---|---|
| ROC AUC | 0.6268 | 1,027 |
| PR AUC | 0.4187 | 1,027 |
| Brier | 0.3278 | 1,027 |

By direction (`results/tables/by_direction.json`): long ROC AUC 0.558 (n=397), short
ROC AUC 0.643 (n=641).

## Reproduction

```
python scripts/research_preflight.py --study studies/ym_prev5_range_position
python scripts/run_preexec_audits.py --study studies/ym_prev5_range_position --pass-num 3 --type both
python scripts/preexec_audit_seal.py --study studies/ym_prev5_range_position
python backtests/run_nt_study.py --study studies/ym_prev5_range_position --mode collect --stage day --date 2024-09-03
python scripts/validate_smoke.py --study studies/ym_prev5_range_position --date 2024-09-03
```

Analysis driver: `results/run_analysis.py` (governed `research/analysis/*` calls only
— `AnalysisSpec` → `load_collection` → `validate_collection` →
`get_features_targets_metadata` → `build_descriptive_table` /
`build_target_disposition_table` / `build_fixed_edges_table` / `classification_bundle`).
Outputs are `results/tables/*` and `results/analysis_context.json` in this directory.

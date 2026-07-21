# Look-Ahead & Timestamp Audit

**Date:** 2026-07-19
**Scope:**
- `studies/short_rth_pure_flip_prediction_enriched/phase0_prepare_data.py`
- `studies/short_rth_pure_flip_prediction_enriched/tests/test_build_labels.py`
- `studies/short_rth_pure_flip_prediction_enriched/SPEC.md` (Scout-pass findings, read for context)
- Direct imports/inputs traced for verification (read-only, not separately audited line-by-line):
  `studies/short_rth_established_age_gate_flip_quality/phase0_prepare_data.py` (source of
  `load_gate_columns`, `post_flip_mfe_by_regime`, `followthrough_flag`, and its own buggy
  `aligned`-based `build_labels` used only for contrast),
  `studies/short_rth_enriched_volume_level_retrain/phase0_prepare_data.py` (source of
  `find_position_cols`, `one_hot_position_cols`, `feature_sets.json` construction),
  `studies/short_rth_entry_surface_backfill/label_full_surface.py` and `entry_surface.py`
  (provenance of `confirm_flip_ns`, `hit_pre_alignment_stop`, `label_available`),
  `studies/short_rth_entry_surface_backfill/results/*` (population/`established` filter trace).
**Auditor:** lookahead-auditor v1
**Run type:** PRE-EXECUTION (synthetic-data unit tests only; full 6-year run has NOT happened yet)

## Summary

- Critical: 0
- Warning: 3
- Note: 3

## Critical findings

None.

## Warnings

### [Item 5 / fragility] `phase0_prepare_data.py:42-77` — cross-study bare-name module override is correct today but session-order-fragile across the monorepo

Traced the full save/restore sequence end-to-end, including the self-referential case (this file
imported by `tests/test_build_labels.py:19` via `from phase0_prepare_data import build_labels`,
which means Python's import machinery has already registered *this* partially-initialized module
under `sys.modules["phase0_prepare_data"]` before this file's own top-level code runs). The
save/restore (not a blind `del`) correctly handles that case, and the override correctly makes
`short_rth_established_age_gate_flip_quality/phase0_prepare_data.py`'s own bare
`from phase0_prepare_data import find_position_cols, one_hot_position_cols` (its line 49) resolve
to the enriched-retrain module rather than colliding. **Confirmed functionally correct for a
standalone run/pytest invocation of this study's own test file.**

The fragility: this correctness depends on `sys.modules["phase0_prepare_data"]` being in the
exact state this code expects at the moment it runs. At least one other study in this repo
(`short_rth_established_age_gate_flip_quality/phase0_prepare_data.py:49`) does its own bare
`from phase0_prepare_data import ...`, and this new study's own file registers itself under that
same literal name when imported. If a full-repo/multi-study `pytest` invocation ever runs tests
from more than one of these `phase0_prepare_data.py`-named studies in a single process, import
order determines which study's functions get silently bound where — with no error raised either
way. This is not a bug in the code as it stands (verified correct in isolation), but it is a
real, not hypothetical, footgun given the repo already has ≥2 files with this exact name doing
bare self-imports. Recommend either running this study's tests in a dedicated process/CI job, or
replacing the bare-name trick with `importlib` loads throughout (as `_load_module` already does
for the two upstream modules) so no code anywhere depends on the ambient `sys.modules` bare-name
slot.

### [C1/data-readiness terminology] `phase0_prepare_data.py:147,156-157` — `censored_rows`/`usable_rows` measure Policy-A-simulation non-resolution, not primary-label censoring, and could be misread against SPEC finding 2's "0 censored" claim

```python
censored = int((~labeled["label_available"]).sum()) if "label_available" in labeled else 0
...
"censored_rows": censored,
"usable_rows": len(labeled) - censored,
```

`label_available` (sourced from `short_rth_entry_surface_backfill/label_full_surface.py`) is
`False` when Policy A's hypothetical-trade *simulation* couldn't resolve an exit (e.g.
`"no_next_opposing_flip_in_available_data"` or `"scheduled_exit_beyond_available_raw_data"`, see
`label_full_surface.py:61-72`). It is **not** a statement about whether the primary label
(`bearish_regime_flip_within_300s`, built purely from `confirm_flip_ns`) is knowable — SPEC.md's
finding 2 explicitly claims 0 rows are censored for the primary label, and the label-construction
code confirms this is architecturally true (`confirm_flip_ns` is populated unconditionally at
checkpoint-generation time, `entry_surface.py:136`, sourced from `regime_end`, never NaN).
The `censored_rows`/`usable_rows` fields in `run_year()`'s returned dict will be non-zero on real
data (Policy-A outcome censoring is a known, expected phenomenon, ~unknown exact rate but nonzero
by construction of `label_full_surface.py`). When these numbers land in
`results/data_readiness.csv` or `results/label_quality_by_year.csv`, a reader could reasonably
interpret nonzero `censored_rows` as contradicting SPEC's "0 censored" claim for the *primary*
label, when in fact it is a completely separate, diagnostic-only, Policy-A-simulation statistic.
Recommend renaming these fields (e.g. `policy_a_censored_rows`/`policy_a_usable_rows`) or adding
an explicit `primary_label_censored_rows` (which should always report 0) before the full run, so
the "Required diagnostics: label quality" artifact in SPEC.md is unambiguous on this exact point
the SPEC itself calls out as a finding.

### [Inherited, not new] `phase0_prepare_data.py:107` (and identically in the age-gate study's own `build_labels`) — `adverse_move_1p25A_before_bearish_flip` silently reads `False`, not "unknown," for Policy-A-censored rows

```python
df["adverse_move_1p25A_before_bearish_flip"] = df["hit_pre_alignment_stop"].astype(bool)
```

`hit_pre_alignment_stop` is defined upstream as `exit_reason == "preflip_policy_stop"`
(`label_full_surface.py:127`). For rows where `label_available=False` (Policy A simulation
non-resolution), `exit_reason` is `None`, so `hit_pre_alignment_stop` evaluates to `False` by
plain equality, not `NaN`. This diagnostic column therefore cannot distinguish "confirmed stop
NOT hit" from "stop status never determined." This is **inherited unchanged from the prior
(age-gate) study's identical line** and is explicitly declared reused/diagnostic-only, never a
primary label, per SPEC.md finding 5 — it is not new derivation logic and not in scope for the
CRITICAL correction this study exists to make. Flagging as a warning only because this study's
own `results/row-level decile diagnostics` requirement (SPEC.md "Required diagnostics") will
join this column, and a decile table that silently treats "never resolved" as "no stop hit" could
understate the diagnosed stop-touch rate in rows overlapping Policy-A censoring. No action
required before the run; worth a one-line caveat in the eventual STUDY_REPORT.md if this column
is surfaced in decile tables.

## Notes

### [Defensive coding] `phase0_prepare_data.py:99-102` — no explicit non-null assertion on `confirm_flip_ns` before label arithmetic

`build_labels()` computes `time_to_bearish_flip_s = (confirm_flip_ns - observation_time) / 1e9`
and thresholds it directly. SPEC.md finding 2 states this is empirically 100%-populated on the
real 6-year population, and the provenance trace (`entry_surface.py:129-136`,
`label_full_surface.py:51`) supports that `confirm_flip_ns` is structurally guaranteed non-null
for every row that survives to the checkpoint surface. However, `build_labels()` itself contains
no defensive assertion of this; if a future upstream change ever introduced a null
`confirm_flip_ns`, pandas' `NaN <= 300.0` evaluates to `False`, which would silently relabel an
"unknown" row as a confirmed negative (no flip) rather than raising. Given this is exactly the
kind of silent-mislabeling class this study exists to fix, a one-line
`assert df["confirm_flip_ns"].notna().all()` (or equivalent `RuntimeError`) at the top of
`build_labels()` or in `run_year()` would convert "finding 2's claim silently stops being true"
into a loud, fail-fast error instead of a quiet mislabel. Cheap to add; not blocking.

### [Test coverage, non-blocking] `tests/test_build_labels.py` — strong regression test, one robustness gap

`test_stop_hit_but_true_flip_within_300s_is_positive` genuinely proves the fix rather than passing
by coincidence: `build_labels()` never references `df["aligned"]` anywhere in the corrected code
path, and the test's synthetic rows never include an `aligned` column at all — so if the old
buggy `bearish_flip_within_300s = df["aligned"]` logic were accidentally reintroduced, this test
would raise `KeyError` (loud failure), not silently pass with a wrong value. Combined with
`test_no_flip_within_300s_is_negative`, `test_exact_300s_boundary_is_inclusive`, and
`test_adverse_move_label_reuses_hit_pre_alignment_stop_directly` (which specifically proves
`adverse_move_1p25A_before_bearish_flip` is never repurposed as the primary label), the test
suite meaningfully exercises the finding-1 fix, not a tautology.

Gap: no test includes an explicit `aligned` column set to a value that *contradicts* the correct
`confirm_flip_ns`-derived answer (e.g. `aligned=False` while `confirm_flip_ns` implies a flip
within 300s). Such a test would additionally guard against a future partial regression where code
starts reading `df.get("aligned", fallback)` instead of omitting the reference entirely — the
current tests would only catch a *total* reversion (which raises `KeyError`), not a partial one
that adds an `aligned`-based fallback/override while retaining the corrected primary path. Cheap
to add before the full run; not required to unblock it given the current code has zero references
to `aligned`.

### [Scope note] `tests/test_build_labels.py` exercises `build_labels()` only, not `run_year()`

Consistent with SPEC.md's stated intent ("a small hand-computed test... before the expensive
multi-model training run"), the test suite validates label arithmetic on synthetic rows and does
not exercise `run_year()`'s join/assertion logic (row-count preservation, 100% join-rate,
`regime_age_s >= 120` gate). Those checks were verified by direct code reading (see Clean checks)
rather than by an automated test in this file. This is an accepted scope boundary for this
pre-execution pass, not a gap — SPEC explicitly frames the full 6-year run itself as the test of
the join/assertion logic against real data (all four `RuntimeError` guards in `run_year()` will
fire immediately and loudly on the actual run if any of these assumptions are violated).

## Clean checks

- **C1/C2 (primary label arithmetic).** `bearish_regime_flip_within_300s`,
  `bearish_flip_within_600s`, `time_to_bearish_flip_s`, `no_flip_before_timeout` are computed
  exclusively from `confirm_flip_ns`/`observation_time` arithmetic (`phase0_prepare_data.py:99-102`).
  No reference to `df["aligned"]` or any other Policy-A-simulation-derived column anywhere in
  this file — confirmed by direct grep of the full file, and by re-reading the age-gate study's
  own (still-buggy, left unmodified for contrast) `build_labels()` to confirm the two now diverge
  exactly at the finding-1 line (`bearish_flip_within_300s = df["aligned"]` in the old file vs.
  pure arithmetic in the new one).
- **`adverse_move_1p25A_before_bearish_flip` role.** Confirmed this diagnostic column is set
  exactly once (`phase0_prepare_data.py:107`, `= hit_pre_alignment_stop`), is never read anywhere
  else in this file, and is never assigned to or aliased as
  `bearish_regime_flip_within_300s`/`no_flip_before_timeout`. It answers a different, correctly
  labeled diagnostic question and is not repurposed as a flip indicator (SPEC.md finding 5).
- **`confirm_flip_ns` is a legitimate label-construction input, not a feature-path leak.** Traced
  to `entry_surface.py:129-136`: populated unconditionally from the canonical regime timeline's
  `regime_end_ns` at checkpoint-generation time (not recomputed or joined post-hoc from a
  leak-prone source), and rows are only retained (`fill_ts >= regime_end: continue`) when the
  observation genuinely precedes the confirmed flip — i.e. `time_to_bearish_flip_s` is guaranteed
  positive by construction, and the field is being used correctly here as a **label** target
  (describing the future), never joined into any feature set as a predictor.
- **Feature-set exclusion (Item 3).** `phase0_prepare_data.py:174-175` copies
  `short_rth_enriched_volume_level_retrain/_work/feature_sets.json` byte-for-byte from a prior,
  independent run of that study's own `phase0_prepare_data.py::main()` — a file that was written
  to disk **before** any of this study's new label columns ever existed in any DataFrame that
  script touched. Directly verified by loading the current `feature_sets.json` and grepping F0-F3
  column lists: zero occurrences of `confirm_flip_ns`, `bearish_regime_flip_within_300s`,
  `bearish_flip_within_600s`, `no_flip_before_timeout`, `time_to_bearish_flip_s`, or
  `adverse_move_1p25A_before_bearish_flip` (the only hits for a naive `"aligned"` substring search
  are unrelated moving-average-alignment feature names like `aligned_price_minus_center_5m`, not
  the Policy A `aligned` column). This construction makes cross-contamination structurally
  impossible, not merely coincidentally absent today.
- **Item 4 — join/assertion logic in `run_year()` is real, not tautological.**
  - `merge(..., validate="one_to_one")` (line 129) plus explicit
    `len(merged) != n_before` check: would raise on duplicate keys in either input frame — a
    real, catchable failure mode (not vacuous given `load_gate_columns` itself only guards
    against duplicates in `gate_cols`, not in `full`).
  - `join_rate = merged["regime_age_s"].notna().mean(); != 1.0: raise` — a genuine left-join
    completeness check; would fire on any row in `full` lacking a matching key in `gate_cols`.
  - `regime_age_s >= 120.0` assertion (new in this study vs. the age-gate study's `run_year`,
    which does *not* have this check because its own base population spans ages below 120 and
    gates later in a separate `build_gate_surfaces()` step): traced the full population lineage
    (`ohlcv_volume_delta_price_level_features/attach_features.py` →
    `short_rth_w4_retrain_entry_strength/phase0_prepare_data.py` →
    `short_rth_entry_surface_backfill/label_full_surface.py` →
    `short_rth_entry_surface_backfill/entry_surface.py:99-107`) and confirmed the checkpoint
    population feeding this study is generated under an `established` filter that already
    requires `regime_age_s >= filt["regime_age_s_min"] == 120.0` as one of four AND'd conditions
    (`CODEX_5_X_established_fade_policy.json`). The assertion is therefore a genuine join-
    integrity check (it would fire if the `regime_age_s` join pulled wrong/misaligned values),
    not a tautology restating something the code itself guarantees.
  - Post-`post_flip_mfe_by_regime` merge: `validate="many_to_one"` plus row-count check — correct
    given `post_flip_mfe_by_regime` is keyed uniquely per `regime_start_ns`
    (`nunique_flip != 1: raise` inside that function itself, in the age-gate module).
- **Item 5 — import resolution correctness.** Traced end-to-end (see Warnings for the fragility
  caveat): `find_position_cols`/`one_hot_position_cols` bound in this file
  (`phase0_prepare_data.py:81-82`) are confirmed to originate from
  `short_rth_enriched_volume_level_retrain/phase0_prepare_data.py` (the intended source), not a
  stale or wrong-file version, for a standalone execution of this study.
- **Train/dev/test discipline at data-prep stage.** `main()` concatenates `prepared_{year}.parquet`
  only for `TRAIN_YEARS = (2021, 2022, 2023, 2024)` into `train_2021_2024_prepared.parquet`
  (line 179-181) — no 2025/2026 rows are present in the training artifact this phase produces.
- **No feature engineering in this file.** This script performs joins and label construction
  only; no `rolling`/`ewm`/`expanding`/`.shift(-N)` calls exist anywhere in
  `phase0_prepare_data.py`, so checklist items B1-B7 are not applicable to this file (features
  come from already-audited upstream studies, out of this pass's scope per the user's file list).
- **Secondary diagnostic labels (finding 5).** `bearish_flip_within_600s`, `time_to_bearish_flip_s`,
  `post_flip_mfe_atr_{300,600}s`, `bearish_flip_within_{300,600}s_and_followthrough_1A` are
  reused via import from the age-gate study's already-corrected (for these specific columns)
  functions (`followthrough_flag`, `post_flip_mfe_by_regime`) — confirmed these two functions
  contain no reference to `aligned` and correctly preserve NaN (censored) followthrough status
  rather than silently coercing it to `False` (`followthrough_flag`'s `out[~flip_within] = 0.0`
  line only overrides the no-flip case, never the flip-but-MFE-unavailable case).

---

*Audit complete. This is a PRE-EXECUTION, read-only static-analysis pass against synthetic-data
unit tests, per the project's standing pre-execution-audit-gate rule. It has not run the pipeline
against the real 6-year dataset. 0 CRITICAL findings — nothing found here should block proceeding
to the full 6-year `phase0_prepare_data.py` run. The three WARNING items are recommended
(non-blocking) hardening/clarity improvements; none of them represent silent look-ahead bias or a
mislabeled primary target as currently written.*

---

# COMPLETION-GATE AUDIT (post 6-year run)

**Date:** 2026-07-19
**Scope:**
- `studies/short_rth_pure_flip_prediction_enriched/phase0_prepare_data.py` (re-verified against
  the actual 6-year run outputs: `results/phase0_manifest.json`)
- `studies/short_rth_pure_flip_prediction_enriched/train_and_evaluate.py`
- `studies/short_rth_pure_flip_prediction_enriched/regime_and_family_diagnostics.py`
- `studies/short_rth_pure_flip_prediction_enriched/select_and_gate.py`
- `studies/short_rth_pure_flip_prediction_enriched/build_readiness_and_label_quality.py`
- `_work/feature_sets.json` (F0/F1/F2/F3 column lists, loaded and diffed programmatically)
- `results/model_metrics.csv`, `results/regime_level_diagnostics.csv`, `results/manifest.json`,
  `results/label_quality_by_year.csv`, `results/phase0_manifest.json`,
  `results/train_and_evaluate_manifest.json` (actual 6-year run outputs, inspected directly, not
  assumed from the SPEC's summary)
- Direct imports traced: `studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py`
  (`fit_logistic`, `fit_gbt` — confirmed to fit only on the `train_X` argument passed in),
  `sklearn.calibration.CalibratedClassifierCV` and `sklearn.frozen.FrozenEstimator` source (both
  read directly from the installed sklearn 1.7.2 package to verify actual fit-call semantics, not
  assumed from documentation or code comments)
- `features/registry.py` (`FEATURE_REGISTRY`, used by `feature_family()`), spot-checked provenance
  of `activity_flip_count_30m` (`studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_build_repaired_atlas.py:176-196`,
  "exact causal" trailing-window regime count)
**Auditor:** lookahead-auditor v1
**Run type:** COMPLETION-GATE (real 6-year run outputs inspected; this pass supersedes nothing in
the pre-execution section above, which remains valid for `phase0_prepare_data.py`'s label logic)

## Summary

- Critical: 1
- Warning: 3
- Note: 2

## Critical findings

### [Metric validity / gate completeness] `select_and_gate.py:40-65` (`apply_gate`) — the `PURE_FLIP_SIGNAL_STRONG` decision is computed entirely from row-level AUC/lift, which the pipeline's own regime-level diagnostic shows is not representative of genuine per-regime discriminative power

**This is the single most important finding of this pass and should block accepting
`PURE_FLIP_SIGNAL_STRONG` at face value, or feeding this result into a follow-up stop/exit study,
without addressing it.**

`select_and_gate.py::apply_gate()` (lines 40-65) computes `min_2025_pass`, `min_2026_pass`,
`strong_2025_pass`, `strong_2026_pass` — and therefore the final decision string — using only
`dev_metrics["auc"]` / `test_metrics["auc"]` (row-level AUC from `model_metrics.csv`) and
`dev_lift["top_decile_lift"]` / `test_lift["top_decile_lift"]` (row-level decile lift, computed by
`top_decile_lift()` at lines 23-37 on the full row population). `select_and_gate.py::main()`
**never reads `results/regime_level_diagnostics.csv` at all** — grep-confirmed, that file does
not appear anywhere in `select_and_gate.py`. The gate is therefore structurally incapable of
reflecting the regime-level diagnostic, regardless of what that diagnostic shows.

`regime_and_family_diagnostics.py` (lines 71-114, `regime_level_summary()`) computes exactly the
diagnostic the SPEC itself requires ("regime-level diagnostics (max pre-flip probability,
first-crossing lead time..., regime-level AUC, false-positive/missed-flip regime rates)" — SPEC.md
"Required diagnostics") and its own docstring (lines 12-16) explicitly states its purpose is to
"de-duplicate the heavy within-regime row correlation a naive row-level AUC would inflate." This
is a real, already-built falsification test for exactly the concern this audit was asked to
independently verify (task item 8). **The test was run, and it fails:**

Inspected `results/regime_level_diagnostics.csv` directly (all 8 combos × 2 splits, 16 rows):

| feature_set / model | split | `regime_level_auc` | `regime_level_base_rate` | `regime_level_top_decile_flip_rate` | implied regime-level lift |
|---|---|--:|--:|--:|--:|
| F3_volume_delta_plus_price_levels / gbt (**selected**) | 2025 | **0.4812** | 0.7098 | 0.8095 | **1.14x** |
| F3_volume_delta_plus_price_levels / gbt (**selected**) | 2026 | **0.5206** | 0.7124 | 0.8333 | **1.17x** |
| F0_existing_only / logreg | 2025 | 0.4753 | — | — | — |
| F0_existing_only / gbt | 2025 | 0.4733 | — | — | — |
| (all 16 rows) | both | **range 0.4733–0.5317** | — | — | — |

Every one of the 16 (feature_set, model, split) combinations has `regime_level_auc` within
±0.03 of 0.50 (random) — several are *below* 0.50 (worse than chance). None reaches anything close
to a level that would independently be called "signal." Compare this to the row-level metrics that
actually drove the decision: selected combo's row-level AUC 0.6712 (2025) / 0.6700 (2026), row-level
top-decile lift 2.03x (2025) / 1.93x (2026) (from `results/manifest.json`). The row-level top-decile
lift (2.03x) is roughly **1.8x larger** than the regime-level top-decile lift (1.14x) for the exact
same selected model.

The same disconnect shows up independently in the threshold-crossing diagnostics computed in the
same file (lines 90-113): for the selected F3/gbt combo, `top10_missed_flip_rate` = 0.535 (2025) /
0.539 (2026) — **more than half of all regimes never cross the top-10%-score threshold even during
their own genuine ≤300s warning zone** — and `top10_false_positive_rate` = 0.524 (2025) / 0.479
(2026) — roughly half of all "first alarms" at the top-10% threshold are false alarms (fired on a
row that was not actually within 300s of the real flip). `top10_median_lead_time_s` ≈ 350s, only
~50s beyond the 300s window itself, i.e. essentially no early-warning margin. These are computed
by an entirely different code path (`missed_rate`/`fp_rate`/`median_lead` at lines 98-113) than
`regime_level_auc`, and they corroborate it independently — this is not a single fragile metric,
it is four independently-computed regime-level statistics all pointing the same direction.

**Root-cause investigation (own verification, not just reading the diagnostic file):** re-loaded
`_work/scored_dev_2025.parquet` directly and computed:
- Mean rows per regime: 118.1 (median 101, max 324) — i.e. the "full checkpoint surface" design
  (SPEC-mandated, not a bug) means each of the 1,678 2025 regimes contributes ~100+ correlated
  rows to the row-level AUC computation, sharing one `confirm_flip_ns`.
- `corr(score, regime_age_s)` = 0.304, `corr(score, time_to_bearish_flip_s)` = -0.217, while
  `corr(regime_age_s, label)` alone = only 0.066 and `corr(seconds_in_current_ordering, label)` =
  only 0.073. Individually, elapsed-time-in-regime-style features have weak direct correlation
  with the label, yet the model's combined score correlates with them substantially more than any
  single one does with the label — consistent with the model partly learning a
  market-wide-chop/hazard-style regularity (elevated scores during generally choppy periods, when
  both scores and the imminent-flip base rate rise together across many regimes simultaneously)
  rather than a regime-specific "this particular regime is about to die" signal. This is
  plausible, not proven with certainty (a full mechanistic decomposition was out of scope for this
  pass), but it is directionally consistent with everything else observed: F0 (149 pre-existing
  "chop/geometry" features only, no volume/delta or price-level features) already achieves
  row-level AUC 0.6634/0.6562 — within 0.008–0.014 of the full F3 (695-feature) result — meaning
  the new enrichment this study exists to test contributes only a small increment on top of a
  chop-hazard baseline that was already close to the ceiling.
- Base rates are stable year-over-year (`label_quality_by_year.csv`: 0.225–0.265 across all 6
  years) and regime counts/median durations are similarly stable — consistent with a fairly
  time-stationary market-structure statistic, which independently explains why row-level AUC is
  so tightly clustered 2025→2026 (task item 8's stated concern) without requiring a leak: a stable
  hazard-style regularity would naturally look this stable across years, in the same way that a
  genuine leak would. **Cross-year row-count/label-rate stability is not, by itself,
  discriminating evidence between "genuine edge" and "chop-hazard artifact" — the regime-level
  diagnostic is what actually discriminates the two, and it favors the artifact interpretation.**

**What this is not:** this is not a look-ahead-bias finding in the strict "future data touched the
model" sense — no evidence was found that any feature or the calibration step touches
post-observation-time information (see Clean checks below, all re-verified against the real run).
It is a **metric-selection / promotion-gate correctness** finding: the SPEC's own signal-viability
framing and required diagnostics ("Does the model give useful regime-level lead time?" — final
report question 7) are answered negatively by data the pipeline already computed, and the
automated `apply_gate()` decision path structurally cannot see that answer. As currently computed,
`PURE_FLIP_SIGNAL_STRONG` measures "can this model rank an arbitrary future-flip-imminent row
above an arbitrary future-flip-distant row, pooled across ~2,200 regimes and ~260K rows" — a real
but substantially weaker and less actionable claim than "can this model tell, for a given
currently-active regime, whether it is about to flip," which is the practical question a follow-up
stop/exit study (final report question 10) would actually need answered, and which the data says
is close to unanswerable with these features (regime-level AUC ≈ chance).

**Recommendation (not applied — read-only audit):** before writing `STUDY_REPORT.md` or using this
result to justify a follow-up study, either (a) add regime-level AUC/lift to `apply_gate()`'s
criteria with an explicit threshold and re-run the decision, likely landing on
`PURE_FLIP_SIGNAL_WEAK_BUT_REAL` or `PURE_FLIP_SIGNAL_INCONCLUSIVE` rather than `_STRONG`, or (b)
if row-level AUC is deliberately being kept as the primary promotion criterion, add an explicit,
prominent caveat in `STUDY_REPORT.md` stating that regime-level discriminative power is
approximately chance and that the row-level result should not be read as "the model can flag which
active regimes are dangerous."

## Warnings

### [W1] `select_and_gate.py:23-37` (`top_decile_lift`) — row-level decile lift is subject to the same within-regime pooling as row-level AUC; the 2.03x/1.93x headline figures should not be read as regime-level actionable lift

Direct consequence of the Critical finding above, called out separately because it affects a
specific headline number likely to be quoted on its own. `top_decile_lift()` computes deciles over
the full row population (`d["decile"] = pd.qcut(d[score_col], 10, ...)`), so a single regime
contributing ~100+ rows can populate multiple deciles as its own observation_time advances toward
its flip, and "top decile" row-level membership partly reflects "this row happens to be late in
its regime's life" rather than "this regime, considered as a whole, is unusually dangerous." The
regime-level analogue (`regime_level_top_decile_flip_rate` vs `regime_level_base_rate` in
`regime_level_diagnostics.csv`) gives 1.14x/1.17x for the selected combo, not 2.03x/1.93x. Both
numbers are "real" in the sense that they are computed correctly from the data as specified; they
answer different questions, and only the row-level one appears in `results/manifest.json`'s
headline `signal_viability_gate` block.

### [W2] `train_and_evaluate.py:151-152` / `regime_and_family_diagnostics.py` — no code-level bug found in calibration or threshold-freezing, but both deserve an explicit note given how much weight this audit placed on them

Traced `CalibratedClassifierCV(FrozenEstimator(base_estimator), method=method).fit(dev_X, dev_y)`
against the actual installed `sklearn==1.7.2` source
(`site-packages/sklearn/calibration.py:319-483`, `site-packages/sklearn/frozen/_frozen.py`), not
just the code comments. Confirmed: `FrozenEstimator.__sklearn_clone__` returns `self` (not a real
independent clone), so even though `CalibratedClassifierCV.fit()`'s non-"prefit" branch calls
`clone(estimator)` and re-invokes `.fit(X, y)` on the (identical) frozen estimator once at line 472
and internally via `cross_val_predict`'s per-fold fit calls, `FrozenEstimator.fit()` is a
documented no-op (`check_is_fitted(self.estimator); return self`) — the base model trained on
2021-2024 is never altered by any call made during `.fit(dev_X, dev_y)`. The predictions fed to the
calibrator (`_fit_calibrator`) are therefore always the frozen 2021-2024-trained model's own
`predict_proba(dev_X)`-equivalent output, and the calibrator itself is fit only against `dev_y`
(2025). `test_X`/`test_y` (2026) are never passed to any `.fit()` call anywhere in
`train_and_evaluate.py` — confirmed by reading every `.fit(` call site in the file (lines 118, 125,
152) and their arguments. This item is filed as a Warning only in the "worth recording, not a
finding" sense — flagging it explicitly because SPEC's calibration section is exactly the kind of
claim ("Never calibrated on 2026") this audit exists to verify at the call-graph level rather than
take on faith, and because the deprecated `cv="prefit"` code path (which behaves differently and
raises a `FutureWarning`) was *not* what's actually used here, contrary to what a comment-only
read of related code elsewhere in the repo might suggest. Similarly, `regime_and_family_diagnostics.py`'s
threshold freezing (lines 55-58, 122-132) uses a literal tuple `(("2025", ...), ("2026", ...))` for
the split loop, not a dict — deterministic ordering independent of Python dict-insertion-order
semantics, confirmed by direct reading; `thresholds_by_combo[key]` is always populated during the
"2025" outer-loop iteration before being read during "2026," for all 8 combos. No defect found in
either mechanism; recorded as Warning-level only to document that both were checked at the
call-semantics level, not assumed.

### [W3] `train_and_evaluate.py:110` and feature-set construction — confirmed clean, but the exclusion of gate-input columns (`regime_age_s`, `running_mfe_atr`, `retained_mfe_ratio`, `atr_at_entry`) from all four feature sets is a design choice worth surfacing, not just a pass/fail

`train_X, dev_X, test_X = train_df[cols], dev_df[cols], test_df[cols]` (line 110) restricts to
exactly the `cols` list loaded from `_work/feature_sets.json` per feature set — verified
programmatically that `F3_volume_delta_plus_price_levels` (695 cols, `= F0 | F1 | F2`, confirmed by
set-union check) contains **zero** occurrences of `bearish_regime_flip_within_300s`,
`bearish_flip_within_600s`, `time_to_bearish_flip_s`, `no_flip_before_timeout`,
`post_flip_mfe_atr_{300,600}s`, `confirm_flip_ns`, `adverse_move_1p25A_before_bearish_flip`,
`hit_pre_alignment_stop`, `hit_timeout`, `hit_post_alignment_stop`, `hit_opposing_flip`,
`opposing_flip_exit_positive`, `net_pnl`, `exit_reason`, `regime_start_ns`, `observation_time`,
`label_available`, `regime_end`, or any of the diagnostic label columns, and zero substring hits
for `flip|label|pnl|exit_reason|censor|hit_|aligned` beyond four benign, previously-verified
names (`activity_flip_count_30m`, and three `aligned_price_minus_center_*` moving-average-alignment
features — same false-positive substring hits already dismissed in the pre-execution audit's Clean
checks). `regime_age_s`/`running_mfe_atr`/`retained_mfe_ratio`/`atr_at_entry` (the gate-input/ATR
columns from the task's item 3) are present in `prepared_{year}.parquet`'s wider schema (joined by
`load_gate_columns` in `phase0_prepare_data.py`) but confirmed **absent** from all four feature
sets — they are correctly used only for the `regime_age_s >= 120` gate and label-arithmetic (ATR
normalization of MFE) roles, never as ML features, and they are themselves causal
(`load_gate_columns` joins pre-existing as-of-checkpoint state from `surface_{year}.parquet`, not
anything computed from data after `observation_time` — traced in the age-gate study's own
`load_gate_columns`/`GATE_COLS`, unchanged from the already-audited prior study). Filed as a
Warning rather than a Clean check only because "correctly excluded" here is doing real work: these
are exactly the kind of columns that *could* leak if a future edit ever widened `cols` via a stray
`.join()` or wildcard column selection, and there is currently no unit test guarding this
exclusion (only the `feature_sets.json` byte-for-byte reuse, verified in the pre-execution pass,
prevents it) — recommend a cheap regression test asserting the feature-set JSON never contains any
name matching a small denylist of label/outcome/gate-column patterns, run as part of CI before any
future retrain of this pipeline.

## Notes

### [N1] `regime_and_family_diagnostics.py:61-68` (`feature_family`) — `RuntimeError` on unclassifiable feature is a real, not tautological, integrity check

`feature_family()` raises if a feature name isn't in `f0_feats` and isn't found (by full name or
`__`-prefix base name) in `FEATURE_REGISTRY`. This would fire loudly if `feature_importance.csv`
ever contained a feature name that drifted out of sync with the registry (e.g. a renamed column
upstream) rather than silently mis-attributing it to a family — confirmed by reading the function
body; not exercised as a live bug in the current run (the printed `family_summary` output in the
run log shows both `volume_delta` and `price_level` families present with nonzero
`total_abs_importance` for the F3 combos, meaning classification succeeded for all 546 non-F0
features without hitting the `raise`).

### [N2] Row-count / integrity assertions in `phase0_prepare_data.py`'s real run — re-confirmed against actual output, not just static reading

Re-verified (this pass, against `results/phase0_manifest.json` from the actual 6-year run, not
just by reading the code as the pre-execution pass did): `primary_label_censored_rows == 0` and
`join_rate_gate_cols == 1.0` for all six years (2021-2026) exactly as the pre-execution pass
predicted from the code. Row counts match exactly across every file boundary in the pipeline: phase0
`distinct_regimes` (2025: 1,678, 2026: 532) match `regime_level_diagnostics.csv`'s `n_regimes`
column exactly; phase0 `rows` (2025: 198,255, 2026: 63,021) match
`train_and_evaluate_manifest.json`'s `dev_rows`/`test_rows` exactly; train rows (813,972) match the
SPEC's finding-3 expected count exactly. No silent row drift anywhere in the pipeline.

## Clean checks (completion-gate pass)

- **Feature/label leakage (task item 2).** Programmatically verified (not just grepped by eye):
  `F3_volume_delta_plus_price_levels` = `F0_existing_only ∪ F1_volume_delta_only ∪
  F2_price_levels_only` (695 = union, confirmed via Python set equality), and none of the four
  feature sets contain any label, outcome, Policy-A-diagnostic, or key column — see [W3] for the
  full denylist checked.
- **`train_X = train_df[cols]` construction (task item 2).** `train_and_evaluate.py:110` selects
  columns by exact name from the `cols` list only; no `.join()`, `.merge()`, or wildcard column
  selection anywhere in `train_and_evaluate.py` that could reintroduce excluded columns after the
  `cols` restriction. Grep-confirmed zero `.join(` / `.merge(` calls in the file.
- **Gate-input/ATR column causality (task item 3).** `regime_age_s`, `running_mfe_atr`,
  `retained_mfe_ratio`, `atr_at_entry` are joined from pre-existing as-of-checkpoint surfaces
  (`load_gate_columns`), not recomputed from post-observation data, and are correctly excluded
  from all feature sets (used for gating/label arithmetic only) — see [W3] for detail.
- **Calibration correctness (task item 4).** Traced the actual sklearn 1.7.2 call sequence
  (`CalibratedClassifierCV(FrozenEstimator(...))`, not the deprecated `cv="prefit"` path) and
  confirmed the base estimator is never refit and `test_X`/`test_y` are never passed to any
  `.fit()` call — see [W2] for the full trace.
- **Threshold-freezing loop ordering (task item 5).** `regime_and_family_diagnostics.py`'s
  `for split_name, path in (("2025", ...), ("2026", ...))` is a literal tuple, guaranteeing 2025
  is processed before 2026 for every combo regardless of Python dict semantics — see [W2].
- **Selection uses only 2025 columns (task item 6).** `select_and_gate.py:70`
  (`metrics.sort_values(["2025_auc_raw", "2025_average_precision_raw"], ascending=False)`) — no
  2026 column referenced anywhere in the selection/sort step; 2026 metrics are computed and
  reported (`test_metrics`, `test_lift`, `monthly_auc_ok`) strictly after `best = metrics.iloc[0]`
  has already fixed the selected `(feature_set, model)`, and are never used to alter that choice.
- **Row-count/join-rate assertions are real, not tautological (task item 7).** Re-confirmed against
  actual run output (see [N2]) that every declared row-count-preservation and join-completeness
  check in `phase0_prepare_data.py::run_year()` is consistent with the real data at every stage
  from phase0 through `train_and_evaluate.py` through `select_and_gate.py`'s predictions parquets.
- **No 2026 data used to fit anything.** Across `train_and_evaluate.py`, every `.fit(`/`.fit_transform(`
  call site takes only `train_X`/`train_y` (base models) or `dev_X`/`dev_y` (calibrators);
  `test_df`/`test_X`/`test_y` appear only in `.predict_proba(` and metric-computation contexts.

---

*Completion-gate audit complete. 1 CRITICAL finding: the `PURE_FLIP_SIGNAL_STRONG` decision, as
currently computed by `select_and_gate.py::apply_gate()`, is driven entirely by row-level metrics
that the pipeline's own regime-level diagnostics (already computed, already required by SPEC.md,
never consulted by the gate) show do not reflect genuine per-regime discriminative power
(regime-level AUC ≈ 0.47-0.53 across all 8 combos, both years — statistically indistinguishable
from chance). No look-ahead bias, train/serve skew, or feature/label leakage was found in
`train_and_evaluate.py`, `regime_and_family_diagnostics.py`, `select_and_gate.py`, or
`build_readiness_and_label_quality.py` — the calibration, threshold-freezing, and train/dev/test
discipline all check out at the call-semantics level, re-verified against the real 6-year run
outputs and the installed sklearn source, not assumed from code comments. The result should not be
reported as `PURE_FLIP_SIGNAL_STRONG` (or used to greenlight a follow-up stop/exit study) without
either revising the gate to incorporate regime-level metrics or explicitly, prominently caveating
that regime-level discriminative power is approximately chance.*

## Post-audit fix applied (2026-07-20)

`select_and_gate.py::apply_gate()` was rewritten to make regime-level checks
(`regime_level_auc > 0.55` AND regime-level top-decile flip rate materially
above the regime-level base rate, both years) a REQUIRED gate condition,
not merely computed-and-ignored. `select_and_gate.py` was re-run.

**Corrected decision: `PURE_FLIP_SIGNAL_INCONCLUSIVE`** (was
`PURE_FLIP_SIGNAL_STRONG`). Row-level checks still pass cleanly for the
selected combo (F3/gbt: 2025 AUC 0.671, 2026 AUC 0.670, row-level top-decile
lift 2.03x/1.93x — all comfortably clear both the minimum and strong bars).
But regime-level checks fail both years (regime AUC 0.481/0.521, both below
the 0.55 bar) — exactly SPEC.md's own definition of `INCONCLUSIVE` ("mixed
metrics ... unclear regime-level behavior"), not a pass. `results/manifest.json`
now carries both `regime_level_2025`/`regime_level_2026` blocks alongside
the gate outcome so the row-level/regime-level disagreement is visible
directly in the artifact, not just in this audit note.

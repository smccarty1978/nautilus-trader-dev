# Look-Ahead & Timestamp Audit

**Date:** 2026-07-20
**Scope:** Pre-execution SPEC audit (per SPEC.md "Status" gate and CLAUDE.md invariant 5).
Not a code audit of Phase 3+ implementation (does not exist yet) — an audit of the frozen
plan and every existing file it proposes to reuse or compare against.

Files inspected:
- `studies/runtime_constrained_f3_feature_reduction/SPEC.md` (full)
- `studies/short_rth_pure_flip_prediction_enriched/phase0_prepare_data.py`
- `studies/short_rth_pure_flip_prediction_enriched/train_and_evaluate.py`
- `studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py`
- `studies/short_rth_enriched_volume_level_retrain/phase0_prepare_data.py` (`find_position_cols`/`one_hot_position_cols`/`build_outcome_class`)
- `studies/nt_live_scoring_infra_prereqs/phase0_reconstruct_model.py`
- `studies/nt_live_scoring_infra_prereqs/phase1_feature_inventory.py`
- `studies/nt_live_scoring_infra_prereqs/results/feature_timing_causal_spec.md`
- `features/trackers/median_center.py`
- `features/audit_median_center.md`
- `features/registry.py` (F0 entries, lines 462-589; `FeatureDefinition` defaults, lines 5-33)
- `studies/regime_sequence_chop_context/build_median_centers.py`
- `tests/test_median_center.py`
- `studies/short_rth_pure_flip_score_entry_policy/trigger_logic.py` (spot-check of SPEC's T1/T2/T3 claim)
- Direct filesystem check of `studies/short_rth_pure_flip_prediction_enriched/_work/*.parquet`

**Auditor:** lookahead-auditor v1

## Summary

- Critical: 0
- Warning: 5
- Note: 2

No CRITICAL findings. Per SPEC.md's own stop condition ("Pre-execution audit CRITICAL
finding -> halt, remediate, re-audit before Phase 3"), **this study may proceed to Phase 3+**
subject to the resolving questions below being explicitly answered (not silently assumed) in
this study's own implementation notes, since several are genuine open questions about how
Phase 1's F0 parity harness will be built, not yet-committed code.

## Warnings

### [D2/C3-adjacent] Feature ranking (Phase 3) and selection gates (Phase 7) both evaluate on 2025 only — no held-out check of the "ranked well" claim

`SPEC.md:151-176` (Phase 3, permutation importance "on 2025") and `SPEC.md:207-211` (Phase 7,
"ROC-AUC delta >= -0.005 ... top-5%/2.5% regime overlap >= 95%" also computed on 2025 per
Phase 6, `SPEC.md:201-205`). Candidate models are trained on 2021-2024 (Phase 5), so this is
not literally fitting on the test set — but the **same** 2025 dataset is used to (a) rank
which features survive, (b) pick 8 raw-column candidate sizes, and (c) gate which of those
candidates counts as "passing." This is classic feature-selection-on-dev double-dipping: a
candidate that looks like it "preserves the population" on 2025 is not thereby shown to
generalize — it is shown to match the baseline on the exact set used to choose it. 2026 is
correctly never touched (good — no test-set leakage), but that also means **no year in this
study's own scope will ever confirm the selected reduced model generalizes**, only that it
reproduces baseline behavior on the selection set. `SPEC.md`'s "Final decision vocabulary"
(line 239-243, e.g. `REDUCED_RUNTIME_MODEL_SELECTED`) has no qualifier distinguishing
"selected because it matched on the ranking set" from "validated to generalize." Recommend
`STUDY_REPORT.md` state this explicitly rather than let the decision-vocabulary label imply
more than Phase 7 actually establishes, and record whether a future, separate study is
expected to re-check the frozen selection on 2026 before live deployment.

### [Item 4 — F0 parity harness underspecified] No stated causal lead-in length for the Phase 1 tracker replay

`SPEC.md:132-140` says the parity check will "replay a sample of historical 1s bars for a
handful of regimes" through `MedianCenterTracker` and compare `calculate()` output to the
historical F0 columns. `features/trackers/median_center.py` requires substantial causal
history before its own outputs are non-degenerate: `median_30m_history`/`slope_30m_*` need
1800 samples (line 39, 214-215), `slope_..._aligned_atr` acceleration terms need up to
900+300 samples of lookback (`get_accel`, lines 327-334), and `seq_12r_*` needs 12 **completed
regimes** in `self.completed_regimes` (lines 456-469), which in a choppy regime environment
can require hours of prior history. If the harness feeds only each sampled regime's own bars
(no continuous lead-in from well before it), most of these features will be tracker-side
warmup defaults (0.0, or `None` for `seq_Kr_*`) compared against fully-warmed historical values
computed on the continuous multi-year 1s stream — producing spurious `DIVERGES` verdicts that
are a harness-construction artifact, not evidence the tracker is non-causal (or, in the
opposite failure mode, a harness that always starts warm-but-short could spuriously report
`MATCHES` on degenerate near-zero values for both sides). Resolving question: will Phase 1's
replay feed each sampled checkpoint at least 1800s of continuous, causally-ordered 1s history
(plus enough completed-regime history for `seq_12r_*`) immediately before it, and will the
parity report separately flag rows still inside any feature's warmup as `INCONCLUSIVE` rather
than counting them toward `MATCHES`/`DIVERGES`?

### [B9/parity mismatch] Tracker returns `0.0` for insufficient-window slopes; offline pandas builder returns `NaN` for the same condition

`features/trackers/median_center.py:271-273` (`_calculate_slope`): `if len(y) < N: return 0.0`.
The offline builder it must match, `studies/regime_sequence_chop_context/build_median_centers.py:16-19`
(`compute_rolling_slopes`): `sum_y[:N-1] = np.nan` → slope is `NaN`, not `0.0`, for the same
insufficient-window condition. `features/audit_median_center.md` item 3 ("Warmup Train/Serve
Skew ... RESOLVED") only verifies this for the `seq_Kr_*` family (`median_center.py:456-469`,
which correctly emits `None`) — it does not address the slope functions, which still diverge
from the pandas reference in representation (`0.0` vs `NaN`) during warmup. Combined with the
lead-in question above, Phase 1's parity check must explicitly exclude or separately bucket
warmup-affected rows for the slope/spread/ordering feature groups, not just `seq_Kr_*`, or its
`parity_verdict` will be measuring an artifact of two different null conventions rather than
genuine causal agreement.

### [B9 registry compliance] F0 registry entries leave `warmup` and `null_policy` at dataclass defaults despite real, feature-specific warmup and null behavior

`features/registry.py:462-589`: every `regime_median_center_slope_alignment` entry sets only
`source_timeframe`, `window_unit='bars'`, and `reset_policy='none'` — `warmup` is left at the
`FeatureDefinition` default of `None` (`features/registry.py:17`) and `null_policy` at the
default `"disallow"` (`features/registry.py:21`), even though the tracker has real,
feature-family-specific warmup lengths (60s to 1800s of 1s bars for slopes/medians, up to 12
completed regimes for `seq_12r_*`) and a real, documented null-emission path (`None` for
`seq_Kr_*` under-K). Per checklist item B9 this is exactly the kind of "undocumented or
implicit timeframe assumption" that must be explicit before a tracker is safe to reuse.
Non-blocking for **this** study — F0 is explicitly out of scope for retraining
(`SPEC.md:60-62`) and status remains `provisional` — but should be fixed in `features/registry.py`
before any future study treats F0 as portable, and is worth noting in this study's own
`results/f0_tracker_parity_check.json` write-up since it directly affects how that check's
warmup rows should be interpreted.

### [Item 3 — inherited, not new] `regime_start_ns`'s own construction is still "not independently verified" for causality

`studies/nt_live_scoring_infra_prereqs/results/feature_timing_causal_spec.md:100-114` ("Open
item not independently verified in this pass") discloses that `regime_starts`
(`canonical_regime_timeline` / `timeline_from_flips`) was taken on the strength of its own
docstring and an unrelated NT precedent, not re-traced. `SPEC.md:82-83` correctly carries this
forward as a disclosed residual risk rather than silently assuming it's fine, and does not
re-audit it in this study — consistent with this repo's own governance rule (structural leaks
must be checked before being trusted). Repeating it here because `regime_start_ns` is the
literal grouping key for Phase 6/7's "top-5%/top-2.5% regime overlap >= 95%" gate
(`SPEC.md:37-40, 201-211`): if this timestamp's construction ever turns out to be
non-causal (e.g. snapped to a confirmation time rather than a true start), every regime-level
overlap metric in this study inherits that error silently. Not a new finding, and appropriately
disclosed by the SPEC already — flagged per this auditor's standing instruction to repeat
open risks rather than assume the user has internalized them.

## Notes

### `median_center_5m_5s_sampled` diagnostic column has a genuine look-ahead bug, but is confirmed unused by this study's model

`studies/regime_sequence_chop_context/build_median_centers.py:79-80`:
```
df_5s = df['close'].resample('5s').last().ffill()
df['median_center_5m_5s_sampled'] = df_5s.rolling(60, min_periods=1).median().reindex(df.index, method='ffill')
```
Default `resample('5s')` uses `closed='left', label='left'` — the bin labeled `T` contains
samples `[T, T+5s)` and `.last()` returns the close observed at `T+4s`, but the row is *labeled*
`T`. Reindexing back to the 1s index with `method='ffill'` then assigns that `T+4s`-derived
value to rows `T, T+1s, T+2s, T+3s` as well — i.e., the four seconds *before* `T+4s` see a
median computed from data at `T+4s`, a direct intra-bucket look-ahead. Confirmed via direct
`feature_sets.json` inspection that `median_center_5m_5s_sampled` is **not** one of the 149
`F0_existing_only` columns feeding the frozen baseline model or any candidate in this study —
this is a dead diagnostic column ("Sensitivity calculation" per its own comment) with zero
impact on this study's results. Flagged for the record only; do not let a future study reuse
this helper function assuming it's leak-free.

### `fit_gbt` hyperparameter determinism relies on an unguarded module-level global

`studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py:73-77` (`fit_gbt`)
reads the module constant `RANDOM_STATE` at call time (Python late-binding), not as a passed
parameter. Currently harmless (`RANDOM_STATE = 42`, never mutated anywhere in the repo), and
this study's Phase 0/5 "reload+verify+hash" steps would catch any accidental drift reactively.
Suggest this study's own scripts assert
`_enriched_retrain_train_eval.RANDOM_STATE == 42` immediately after the dynamic import, before
any `fit_gbt` call, and record the asserted value in `results/baseline_manifest_verified.json` —
cheap insurance against a future copy-paste edit elsewhere silently changing what "identical
hyperparameters" means between the baseline and every candidate in this study.

## Clean checks

- No import-time access to `prepared_2026.parquet` anywhere in the reuse chain: `fit_gbt`'s
  home module (`short_rth_enriched_volume_level_retrain/train_and_evaluate.py`) and every
  `train_and_evaluate.py`/`phase0_prepare_data.py` this study's docs cite all guard their
  2026-touching code behind `if __name__ == "__main__":`, and the dynamic
  `importlib.util.spec_from_file_location` loading pattern used throughout this repo's studies
  sets a non-`"__main__"` module name, so `main()` is never invoked as a side effect of import.
  Confirmed directly in `short_rth_enriched_volume_level_retrain/train_and_evaluate.py:173-247`,
  `short_rth_pure_flip_prediction_enriched/train_and_evaluate.py:93-206`, and
  `nt_live_scoring_infra_prereqs/phase0_reconstruct_model.py:78-156` (this last one loads only
  `train_2021_2024_prepared.parquet` and `prepared_2025.parquet`, never 2026).
- Chronological split discipline as stated in `SPEC.md:88-94` (train 2021-2024, rank/select
  2025, 2026 untouched) matches what every reused script actually loads for the calls this
  study will make (`fit_gbt`, `phase0_reconstruct_model.py`'s already-verified reproduction).
- Phase 0 baseline artifact hash and reproduction (`max_abs_diff=0.0`, 198,255 rows) already
  independently verified in a prior study and re-hashed this session per `SPEC.md:24-26`,
  copy-only promotion (no move/mutation of the original).
- Fixed-category one-hot encoding (`short_rth_enriched_volume_level_retrain/phase0_prepare_data.py:76-90`,
  `one_hot_position_cols`) is a row-wise deterministic transform with no fitted statistics —
  consistent with Phase 4's "frozen one-hot policy" claim that `PriceLevelTracker.calculate()`
  emits all four position dummies atomically; no train/serve skew risk from this specific
  encoding step.
- `DUMMY_SUFFIX_RE` reuse citation (`SPEC.md:170-171` → `nt_live_scoring_infra_prereqs/phase1_feature_inventory.py:34`)
  verified accurate by direct read.
- T1/T2/T3-vs-`trig_A/B/C30/C60/D15s/D30s/D60s` naming claim (`SPEC.md:69-76`) verified
  accurate by direct grep of `short_rth_pure_flip_score_entry_policy/trigger_logic.py`.
- `MedianCenterTracker`'s core regime-completion causal ordering is correct at the code level:
  `on_regime_change` (median_center.py:231-269) finalizes the outgoing regime's MFE/MAE/center
  using only state accumulated through the prior bar, before the current bar's high/low/volume
  begin accumulating into the new regime (median_center.py:188-205) — no look-ahead in the
  regime-boundary bookkeeping itself, modulo the already-disclosed, carried-forward question of
  whether the upstream regime-label feed (`current_regime`) is itself causal (see Warning above).
- `compute_rolling_slopes`/`build_median_centers_df`'s rolling/shift usage (`build_median_centers.py:70-186`)
  is causal throughout (trailing `.rolling(...)` with no `center=True`, only positive
  `.shift(N)` offsets used for backward-looking deltas) except the isolated, confirmed-unused
  `median_center_5m_5s_sampled` diagnostic column (see Note above).
- No pandas usage proposed anywhere in this study's actual model-fitting/selection path beyond
  loading and column-subsetting already-frozen parquet files, consistent with CLAUDE.md
  invariant 1 and the SPEC's own Forbidden list (`SPEC.md:102-106`).
- Sections A, E, F, G, H of the standard checklist are N/A: this study contains no new NT
  `Strategy`, backtest, bar subscription, or bracket-simulation code — confirmed by direct
  read of the SPEC's own scope statement and the novel-code list in the task framing.

---

*Audit complete. Findings reflect read-only static analysis of the frozen SPEC and every
existing script/tracker/registry file it names. Phase 1's actual F0 parity-harness code does
not yet exist; the Warnings above are resolving questions that code review at Phase 1
completion must re-check against this document, not items independently re-verifiable before
that code is written.*

---

## Completion-gate audit

**Date:** 2026-07-20
**Scope:** Post-execution completion-gate pass (per SPEC.md "Audits" section and CLAUDE.md
invariant 5) — full read of every `implementation/*.py` script actually run this session, plus
`results/*.json`/`*.csv` decision artifacts and `STUDY_REPORT.md`. Study decision under audit:
`NO_REDUCED_MODEL_PRESERVES_POPULATION` (no model frozen).

Files inspected: `SPEC.md`; `audit/audit.md` (pre-execution pass, above); `implementation/common.py`,
`build_feature_inventory_and_family_sets.py`, `phase2_family_ablations.py`,
`build_importance_sample.py`, `phase3_feature_importance.py`, `phase4_build_candidates.py`,
`phase5_train_candidates.py`, `phase6_evaluate_population.py`, `phase7_selection_gate.py`,
`phase8_freeze_and_catalog.py`, `f0_tracker_parity_check.py`; `tests/test_model_artifacts.py`;
`results/f0_tracker_parity_check.json`, `phase3_importance_summary.json`,
`selection_gate_decision.json`, `phase7_gate_results.csv`, `candidate_population_overlap.csv`,
`model_catalog.json`, `final_decision.json`, `candidate_feature_sets.json`,
`family_ablation_feature_sets.json`; `artifacts/models/*/manifest.json`,
`artifacts/models/*/feature_list.json`; `STUDY_REPORT.md`; plus independent, reproducible
empirical re-derivation (standalone Python re-hashing of the actual repo files, and a standalone
`HistGradientBoostingClassifier` column-order experiment) rather than relying solely on static
reading or inline comments.

**Auditor:** lookahead-auditor v1

### Summary

- Critical: 2
- Warning: 3
- Note: 1

### Critical findings

#### [F0 parity harness / D3] `f0_tracker_parity_check.py` hardcodes `current_regime=-1` for the entire replay; the manually-overwritten `parity_verdict`/`honest_interpretation` do not identify this as the likely dominant cause of divergence

`implementation/f0_tracker_parity_check.py:142-209`: the script computes a full regime timeline
via `canonical_regime_timeline(2025, raw_full)` (line 142), which internally builds its
`timeline` DataFrame via `timeline_from_flips(starts, directions)`
(`studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py:299-311`) — a
DataFrame that includes a `direction` column (+/-1) per regime. The harness extracts only
`regime_starts = np.sort(timeline["regime_start_ns"]...)` (line 143) and **never reads
`timeline["direction"]` anywhere** (confirmed by grep — `direction` appears exactly once in the
whole file, at line 185, a one-time manual `tracker._active_regime_direction = -1` initialization).
Every subsequent call in the 1s replay loop passes a **hardcoded constant**:
`tracker.update_1s(bar, current_regime=-1, current_atr=ATR_CONST)` (line 205) and
`tracker.calculate(current_regime=-1, ...)` (line 209), for the full 2-week window, regardless of
what the true regime direction actually was at each timestamp.

In `features/trackers/median_center.py`, `current_regime` is not a passive label — it directly
multiplies into every "aligned" feature's sign (`s5 = current_regime * median_5m`, lines 121-123;
`s_5m_1m_al = current_regime * slope_5m_1m / atr`, lines 217-219) and it is the sole trigger for
regime-completion bookkeeping (`if current_regime != 0: ... elif self._active_regime_direction !=
current_regime: self.on_regime_change(...)`, lines 189-193). Pinning it to a constant -1 for the
whole replay means: (a) `on_regime_change` — the only place `completed_regimes` grows — **never
fires during the entire replay**, so every `seq_Kr_*` feature is permanently warmup-gated
(consistent with 106/149 features landing in `n_features_all_inconclusive`, not because two weeks
is genuinely too short, but because the harness's own regime-direction feed can never advance the
tracker's internal regime-completion state at all); (b) every regime-direction-dependent feature
is computed with the wrong sign/state whenever the true market regime was actually bullish, not
bearish. Directly reproduced empirically against the actual result file:
`aligned_price_minus_center_15m` diverges on **2418/2418** compared rows (100%, `max_rel_diff`
~154,887), `activity_regime_count_60m` diverges on **2418/2418** rows, while the small
ATR-and-regime-count-*independent* subset (`fraction_of_time_on_favorable_side`,
`price_cross_count_5m`) matches on **2418/2418** rows — a pattern fully explained by the
`current_regime` hardcode alone, without needing the vaguer theories offered in the results file.

`results/f0_tracker_parity_check.json`'s `parity_verdict` field reads `"INCONCLUSIVE_HARNESS_LIMITED"`
and carries an appended `"honest_interpretation"` block — **neither of which the script itself can
produce**: `f0_tracker_parity_check.py:265-270` computes `verdict` as one of only `"MATCHES"`,
`"DIVERGES"`, or `"INCONCLUSIVE"` (and with `n_features_any_divergence=39 > 0` in the actual run,
line 267-268 would set `verdict = "DIVERGES"`), and the `out` dict literal at lines 272-299 never
constructs an `"honest_interpretation"` key. This confirms the JSON was **manually hand-edited
after the script ran** to relabel a raw `DIVERGES` result as inconclusive, with reasoning
(`known_harness_limitations`, in the JSON) that cites "ATR held constant" and a speculative
"regime-source mismatch" — but never mentions, tests, or rules out the much more direct,
mechanically-verifiable cause sitting in the same 300-line file: `current_regime` is never varied
from -1. This is not a case of honestly disclosing a limitation; it is an incomplete diagnosis
that lands on a benign-sounding "harness limited, not necessarily a tracker defect" conclusion
while missing the most obvious checkable cause. `STUDY_REPORT.md` section 3 repeats this framing
verbatim ("not necessarily a tracker defect... F0 remains not demonstrated portable") and uses it
to support "the case for eventually porting [F0] is stronger than the prior... study's finding
implied" — a materially different downstream conclusion than would be warranted if the reader knew
the parity check's regime input was frozen throughout. **Recommend:** strike the manually-added
verdict/interpretation, re-run with `current_regime` looked up per-bar from `timeline["direction"]`
(already computed and discarded), and only then assess whether residual divergence still points to
ATR-constant/regime-source concerns.

#### [Persistence contract / reproducibility] `F3_live546_gbt_v1`'s claimed "byte-identical-artifact hash verification on reuse" (STUDY_REPORT.md section 11) is not substantiated by the actual persisted artifact, and the SPEC-mandated stop condition for a feature-list hash mismatch was not honored

`SPEC.md` (Phase 5, "Never overwrite an existing hash-mismatched artifact -- bump `_v2` instead")
and the "Stop conditions" section ("Feature-list hash mismatch between construction and training
time for any candidate -> halt that candidate, do not silently retrain with a different list")
both anticipate this exact scenario. `phase4_build_candidates.py:59` maps the 546-raw-target
candidate to model_id `"F3_live546_gbt_v1"` — the **same** model_id `phase2_family_ablations.py:15`
assigns to the `B_live546` family ablation. Verified directly (re-derived, not assumed):

- `results/family_ablation_feature_sets.json["feature_sets"]["B_live546"]` (Phase 2's order, F3's
  original 695-order restricted to the live subset) and
  `results/candidate_feature_sets.json["F3_live546_gbt_v1"]["features"]` (Phase 5's order,
  importance-ranked) contain the **identical 546-feature set** but in **different order** (first
  divergence at index 0: `bar_volume` vs `rolling_5m_low_signed_distance_atr`).
- The two orderings hash differently: `results/candidate_feature_sets.json`'s declared spec
  sha256 is `1f8d0dc6769a1a9387875d2fa163b451da90a14e3ac08635525eaaa7387adaf1`, but
  `artifacts/models/F3_live546_gbt_v1/manifest.json`'s `ordered_feature_list_sha256` (and the
  on-disk `feature_list.json`, independently re-hashed) is `bc2d66ca40f86558d01bae86e36f9c10dd489ae443bdbef5e3ca58670b2fef0a`
  — a genuine, non-cosmetic mismatch between the Phase-4-declared candidate spec and the actually
  persisted artifact.
- Since `fit_gbt` (`studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py:73-77`)
  fits `HistGradientBoostingClassifier` directly on a pandas DataFrame, sklearn (1.7.2, confirmed
  installed) records `feature_names_in_` in column order at fit time — independently reproduced in
  a standalone experiment (30 synthetic features, reversed column order, identical data/seed):
  predictions matched exactly, but `joblib.dump` output hashed **differently**
  (`feature_names_in_` differs). A genuine order difference on the real 546-feature candidate is
  therefore virtually guaranteed to produce a real `model.joblib` hash mismatch, not a spurious
  one.
- `artifacts/models/F3_live546_gbt_v1/manifest.json`'s `fit_timestamp` is `2026-07-20T17:41:46Z`
  with `source_model_or_parent_ranking = "Phase 2 family ablation B_live546"` — matching only the
  Phase-2 run window. All 7 other Phase-5 candidates carry Phase-5-batch timestamps
  (`19:38:45Z`-`19:44:27Z`); `F3_live546_gbt_v1` is the sole Phase-5-declared candidate with **no**
  corresponding Phase-5 timestamp anywhere in its manifest.
- `common.py:99-188` (`train_and_persist`) unconditionally rewrites `feature_list.json`,
  `metrics_2025.json`, and `manifest.json` on **every** call that reaches past the
  promotion/hash-check block — including its own "identical artifact, nothing to do" skip branch
  (line 145). The only way these files could still show exclusively Phase-2 provenance is if
  Phase 5's attempted call for this model_id **never reached that point**, i.e. it hit
  `common.py:140-144`'s `raise RuntimeError(...refusing to overwrite...)` branch. This is exactly
  the behavior `tests/test_model_artifacts.py::test_atomic_model_promotion_refuses_hash_mismatch`
  and `test_ordered_feature_list_identity_and_hash_stability` assert *should* happen for any
  content/order difference — the code and its own test suite are behaviorally sound and consistent
  with each other; the mismatch is between what actually happened and how `STUDY_REPORT.md`
  narrates it.

No `_v2` id exists anywhere under `artifacts/models/` (checked directly) and no halt/remediation
decision for this candidate is recorded in any results file. `STUDY_REPORT.md` section 11 instead
states "`F3_live546_gbt_v1` was deduplicated by hash across Phase 2/Phase 5 ... all with
byte-identical-artifact hash verification on reuse" — a specific, confident verification claim
that the evidence above does not support. **Practical impact is very likely small**: the
underlying feature *set* is identical, and GBT split selection is not meaningfully order-sensitive
absent exact histogram-bin ties, so the AUC/regime-overlap numbers reported for
`F3_live546_gbt_v1` in Phase 6/7 (themselves internally self-consistent, since Phase 6 loads
`feature_list.json` from the same artifact it scores) are very likely still numerically valid for
*some* 546-feature GBT model. But the specific candidate Phase 5 was supposed to independently
retrain and verify under its own declared, hashed spec was never actually produced; the pipeline
silently substituted the earlier Phase-2 artifact under a false "verified identical" narrative
rather than the SPEC's own mandated halt. **Recommend:** correct STUDY_REPORT.md section 11's
claim, and either (a) retrain the 546-candidate under a proper `_v2` id from its own declared
ranked-order feature list per the SPEC's stop condition, confirming the gate result is unchanged,
or (b) explicitly document that Phase 5's 546-candidate is, by design, a reuse of Phase 2's
`B_live546` artifact (different order, same set) and drop the "byte-identical verification"
language.

### Warnings

#### [B7/D-adjacent] Phase 6's "quantile-matched" and "count-matched" (operating-point) regime-overlap comparisons are mathematically forced to be near-identical, satisfying the SPEC's letter but not its intent

`implementation/phase6_evaluate_population.py:97-123`: both bands select "top ~N% of the same
fixed 198,255-row 2025 population" — `cand_thresholds_q` via `np.quantile(cand_scores, q)`, and
`find_count_matched_threshold` via matching the candidate's row count to
`len(baseline_row_sets[label])`, itself derived from a quantile on the same fixed population.
Independently re-derived directly against `results/candidate_population_overlap.csv`:
`quantile_matched_regime_overlap` and `count_matched_regime_overlap` are **bit-for-bit identical
in all 26 rows** of the file (e.g. `F3_ablation_C_f0only_gbt_v1`/top5pct: both
`0.8444444444444444`). This confirms the concern raised for this audit: SPEC.md's Phase 6
requirement for "Both quantile-matched and count-matched (operating-point) threshold comparisons —
no blind reuse of the baseline's raw numeric cutoff" was implemented as two computations that can
never diverge given this fixed-population design, not as a genuinely independent operating-point
check. **This is honestly disclosed** in `STUDY_REPORT.md` section 6 ("this study's two required
comparisons did not end up testing materially different things... a real methodological gap, not
hidden") — credit where due — but the disclosure is prose-only; the code itself still presents two
separately-named columns that invite a future reader to treat them as corroborating independent
evidence. A genuine operating-point comparison would require an actual deployment threshold
(explicitly out of this study's scope, per the report). No change to the final decision follows
from this (both numbers already fail the 95% gate), but flag persists for any future reuse of
`find_count_matched_threshold` as a genuinely distinct check.

#### [B9/proxy-definition] `regime_selection_set()`'s "ANY row above threshold" convention is a real, undisclosed-in-prose proxy choice that favors higher apparent overlap

`implementation/phase6_evaluate_population.py:40-41`:
```
def regime_selection_set(df, score_col, threshold):
    return set(df.loc[df[score_col] >= threshold, "regime_start_ns"].unique().tolist())
```
A regime counts as "selected" if **any single checkpoint row** in that regime scores above
threshold — not the majority of its rows, not its peak-scoring checkpoint matching baseline's,
and not anything tied to the actual causal trigger/entry logic (which lives in the separate,
already-completed `short_rth_pure_flip_score_entry_policy` study and is correctly never touched
here). This is a defensible proxy given the study's disclosed scope boundary (`STUDY_REPORT.md`
section 13: "No claim of live NT population parity") but the specific mechanic ("any row
qualifies") is not stated anywhere in `SPEC.md`, the phase6 code comments, or `STUDY_REPORT.md` —
a reader could reasonably assume "regime overlap" means something closer to "the trigger would
have fired the same way," which this convention does not establish. Because it is a *generous*
definition (more regimes qualify as "selected" than a stricter definition would produce), and
because the gate **already fails** at ~95% required overlap under this generous measure, the true
trigger-level overlap is likely *worse*, not better, than reported — meaning this proxy choice
does not undermine the study's negative conclusion, but a reader relying on the reported
percentages as an upper bound on real deployment fidelity would be correctly cautious, not falsely
reassured. Recommend `STUDY_REPORT.md` state the "any row" convention explicitly in section 6/7
rather than leaving it implicit in code.

#### [Re-verification per audit brief] Phase 7's two previously-fixed bugs (self-referential monthly gate; int/str dict-key mismatch) were independently re-derived and confirmed correctly fixed, with plausible non-degenerate output

`implementation/phase7_selection_gate.py:33-42` (`compute_baseline_monthly_auc`) builds an
in-memory, never-JSON-round-tripped, int-keyed dict (`out[int(month)] = ...`) that is used
directly (not reloaded from disk) at line 71's `monthly_deficits` comparison — correctly
baseline-relative, same-month, not self-referential against the candidate's own overall AUC. The
candidate side (`m["monthly_auc"]`, sourced from a CSV column written by
`phase6_evaluate_population.py:94`'s `json.dumps(monthly_auc)`) is correctly re-cast via
`{int(k): v for k, v in json.loads(m["monthly_auc"]).items()}` (line 69) before the dict-membership
comparison against the baseline's already-int-keyed dict — the previously-diagnosed silent-no-op
(string keys never matching int keys) is fixed. Independently confirmed the fix is not merely
present-but-cosmetic: `results/phase7_gate_results.csv`'s `worst_month_deficit_vs_baseline_same_month`
column ranges non-degenerately from 0.00976 (`F3_top40_gbt_v1`) to 0.0636 (`F3_top60_gbt_v1`)
across the 8 candidates — not the suspicious uniform `0.0` that originally exposed the bug.
Recorded here at Warning level (not silently passed over) per this audit's standing instruction to
independently re-derive, not merely trust, code-comment claims about prior fixes.

### Notes

#### `train_and_persist`'s "skip" branch correctness depends entirely on the model-bytes hash check remaining exact; a future weakening would silently corrupt metadata provenance

`implementation/common.py:138-160`: the unconditional metadata rewrite (`feature_list.json`,
`metrics_2025.json`, `manifest.json`) after the promote/skip branch is *currently* safe only
because reaching it via the skip path strictly requires `existing_hash == tmp_hash` on the exact
`model.joblib` bytes (`common.py:139-145`) — a real full-fidelity check, not a set-membership or
truncated-hash check. The Critical finding above shows this exact model_id already sits at the
edge of this failure mode (a genuine mismatch correctly triggered a halt rather than a silent
corruption). No current bug, but recommend adding an explicit assertion that a "skip" call's
`ordered_features` argument content-matches (not just model-hash-matches) the on-disk
`feature_list.json`, so a future refactor that weakens the hash comparison (e.g., to a
feature-set match instead of exact file bytes) is caught at the metadata layer, not only via a
downstream model-behavior surprise.

### Clean checks (completion-gate pass)

- **2026 isolation** confirmed by direct grep across `implementation/`, `tests/`, and the whole
  study directory: every "2026" occurrence is either a prohibition comment/docstring
  (`common.py:76`, `phase8_freeze_and_catalog.py:99`) or a test asserting non-access
  (`tests/test_model_artifacts.py:157-180`, including a regex-based `test_2026_path_access_prohibition`
  that specifically excludes prose mentions from tripping the check). No `read_parquet`/`read_csv`/
  `open` call anywhere references `prepared_2026.parquet` or any 2026-year file.
- **Phase 3 ranking sample vs. Phase 6/7 gate population** correctly separated:
  `build_importance_sample.py` produces a disclosed, hashed, regime-stratified 30,000-row sample
  (`config/importance_sample.json`, `row_index_sha256` recorded) explicitly for ranking only;
  `phase3_feature_importance.py` loads only that sample (`row_idx = np.load(...)`); both
  `phase6_evaluate_population.py:54` and `phase7_selection_gate.py:34` independently load the full
  `prepared_2025.parquet` (198,255 rows) for the actual gate/selection computations — confirmed by
  direct read, not assumed from comments.
- No script in the executed pipeline touches `train_2021_2024_prepared.parquet` for anything but
  `fit_gbt`'s training call inside `train_and_persist`; Phase 3/6/7 all operate exclusively on
  `prepared_2025.parquet` or its frozen sample, consistent with the split discipline in SPEC.md.
- `f0_tracker_parity_check.py`'s warmup-bucketing logic (audit resolutions #2/#3 from the
  pre-execution pass) is implemented as specified: `WARMUP_RULES` independently derives
  warmup-eligibility from window length/regime-count (not tracker output), and warmup-affected
  rows are correctly excluded from `n_matches`/`n_diverges` into `n_inconclusive` (lines 234-238) —
  this part of the harness is sound; only the `current_regime` hardcode (Critical finding above)
  undermines the comparison's substance for the regime-direction-dependent feature families.
- Phase 2's family ablations (`phase2_family_ablations.py`) correctly reuse the already-promoted
  `F3_695_baseline` artifact for family A rather than refitting an identical model under a new id
  (SPEC.md's own "no economic backtest, GBT only" scope respected throughout Phase 2-8 — no pandas
  vectorized backtest or PnL claim found anywhere in the executed scripts).
- `phase4_build_candidates.py`'s frozen one-hot policy (complete dummy-group retention) correctly
  implemented via `canonical_base`/`group_members` sibling expansion (lines 19-58) — consistent
  with SPEC.md's stated rationale that `PriceLevelTracker.calculate()` emits dummy groups
  atomically.
- `phase8_freeze_and_catalog.py` correctly handles the `selected_id is None` path
  (`NO_REDUCED_MODEL_PRESERVES_POPULATION`): no `FROZEN_RUNTIME_MODEL/` directory is created, and
  `model_catalog.json`/`final_decision.json` are still written recording every candidate's
  `gate_fail` status — confirmed directly against the actual `results/model_catalog.json` and
  `results/final_decision.json` on disk.

---

*Completion-gate audit complete. Findings reflect read-only static analysis plus independent,
reproducible empirical re-derivation (hash comparisons, column-order experiments, and direct
per-feature divergence counts against the actual persisted result files) — not reliance on the
implementation's own inline comments or STUDY_REPORT.md's narrative claims. The two Critical
findings above do not change the study's headline decision (`NO_REDUCED_MODEL_PRESERVES_POPULATION`,
no model frozen) but do mean: (1) the F0 parity check's `INCONCLUSIVE_HARNESS_LIMITED` verdict
rests on an incomplete diagnosis and should not be treated as evidence either for or against F0
portability until re-run with a correctly time-varying `current_regime` feed, and (2)
STUDY_REPORT.md's specific claim of verified byte-identical deduplication for `F3_live546_gbt_v1`
should be corrected or the candidate re-trained under a proper `_v2` id per SPEC.md's own stop
condition.*

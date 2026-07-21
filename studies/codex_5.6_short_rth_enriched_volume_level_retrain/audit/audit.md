# Look-Ahead & Timestamp Audit

**Date:** 2026-07-19T16:49:58-05:00  
**Scope:** `AGENTS.md`; the study's `SPEC.md`, `REPRODUCE.md`, `run_study.py`, and `tests/test_study.py`; direct feature-list/registry dependencies; the accepted feature-foundation specification, final audit, and manifests  
**Auditor:** lookahead-auditor v1  
**Scope hash (SHA-256 of ordered path list):** `e1dc179e76e8650379395e2faf4096854e30996c988879ee881b3893dec2806d`  
**Mode:** mandatory pre-execution read-only static audit; the study and tests were not executed

## Summary

- Critical: **6**
- Warning: **5**
- Note: **1**

**Overall: FAIL.** The study is not cleared for first execution. Stage 2 tunes the retention threshold on the sealed 2026 score distribution, the selection seal does not authenticate its own selected result, feature-manifest drift can pass validation, drawdown is neither exit-ordered nor measured from zero, the causal-input/audit gates do not fail closed, and the promotion gate omits required winner-clipping/month-shape checks. A separate deterministic registry-count mismatch currently prevents stage 1 from reaching model fitting.

## Critical findings

### [C4/D4] `run_study.py:291` — feature-manifest drift can pass the stage-2 seal check

Stage 1 seals the hash of the serialized `results/feature_manifest.json` (`run_study.py:252,277`). Stage 2 generates a fresh in-memory manifest, but line 291 accepts the seal when **either** the fresh manifest's differently serialized JSON hash matches **or** the old, mutable results file still matches. The second branch does not compare the old file with the fresh manifest. Consequently, a post-selection change to `features/registry.py` or the dynamically imported F0 feature source can change the feature names/order used to retrain and score 2026 while the unchanged old results file makes validation pass. `code_hash()` covers only `run_study.py` (`run_study.py:242`), not either direct dependency.

Impact: stage 2 can train/serve a different feature contract than the one selected on 2025 without invalidating the seal.

**Recommended fix (do not apply):** seal one canonical serialization of the complete manifest and direct-dependency hashes, then require the freshly regenerated canonical manifest to match that sealed hash exactly before opening 2026. Do not use the mutable results copy as an alternative validator.

### [C3/C4] `run_study.py:282-296` — the selection seal does not authenticate the selected result and 2026 is opened before selection validity is established

Stage 1 calculates and stores `stage1_result_sha256` (`run_study.py:274-275`), but stage 2 never recomputes or verifies it. It reads `seal["result"]["selection"]` only after opening and validating `full_2026.parquet` (`run_study.py:293-296`). It also never verifies `seal["stage"] == "select_2025"` or requires `seal["result"]["decision"] == "selected"`. Because `ranked[0]` is stored as `selection` even when it fails the two-check gate (`run_study.py:263-265`), `evaluate_2026` consumes the sealed test for a 2025 `no-pass` candidate. Manual or accidental edits to the selected family/model/band/checks likewise go undetected.

Impact: the supposedly sealed choice is mutable, and the one-shot 2026 holdout is exposed even when stage 1 did not produce an eligible candidate.

**Recommended fix (do not apply):** before any 2026 path is constructed/read, validate the seal schema/stage, recompute `stage1_result_sha256`, require a successful stage-1 decision, and validate the chosen record against the sealed candidate table.

### [C3] `run_study.py:193-197,311` — stage 2 recomputes the retention cutoff from the full 2026 distribution

Stage 1 stores the 2025 cutoff in `chosen["cutoff"]` (`run_study.py:259-261`). Stage 2 ignores it and calls `select_rows(..., chosen["band"])` (`run_study.py:311`). `select_rows` calculates `np.quantile(scores, 1-band)` over the dataframe it receives (`run_study.py:193-195`), so in stage 2 every 2026 decision depends on the complete 2026 score distribution, including observations and regimes that occur later in the year. This directly violates the frozen 2025-cutoff rule and the prohibition on 2026 threshold tuning.

Impact: 2026 economics are non-deployable and use future cohort information; the sealed test result is biased toward a preselected retention rate rather than the frozen rule selected in 2025.

**Recommended fix (do not apply):** persist the exact inclusive 2025 score cutoff and apply `score >= sealed_cutoff` unchanged in 2026, then stable-sort qualifying observations and take the first per regime.

### [E4/F3/G2] `run_study.py:46,143-155` — causal provenance and immutable accepted-input identity are declared but never validated

`PROVENANCE` is defined at line 46 but is unused. `load_year` does not require any provenance column and never checks `observation_ts == observation_time`, `latest_source_ts_used <= observation_ts`, the 1s/1m close-time provenance bounds, `observation_time <= exit_ts`, year containment, timestamp nulls, or monotonic types. It checks only a hard-coded row count, key uniqueness, selected columns, and label exhaustiveness (`run_study.py:147-155`). It also does not validate each `full_{year}.parquet` against a trusted feature-foundation artifact hash/manifest before selection; hashing the currently found file into a newly created seal is not proof that it is the accepted immutable surface.

Impact: a same-count/same-schema replacement containing future-derived features or changed Policy-A outcomes is silently accepted and then self-certified by stage 1. The actual current 2025/2026 files were read-only spot-checked during this audit and their provenance inequalities are clean, but the executable gate does not enforce that fact.

**Recommended fix (do not apply):** require and validate all four provenance fields and causal inequalities, temporal/year bounds, finite outcomes, exact label/population controls, and trusted per-year hashes from the accepted foundation manifest before fitting.

### [E4] `run_study.py:184-190,259-264` — max drawdown is calculated in dataframe order and omits starting equity zero

`economic` applies `pnl.cumsum()` in the order supplied and computes drawdown from `curve.cummax()` (`run_study.py:184-190`). Selected rows arrive sorted by `regime_start_ns, observation_time` (`run_study.py:195-197`), not by `exit_ts`. The frozen Baseline-A values were calculated on closed-trade exit order and with a leading zero equity point (`studies/fable5_short_rth_threshold_ladder/run_ladder.py:203-205,208-210`). The current formula also reports zero drawdown for an initial losing trade until a later cumulative peak exists.

Impact: the DD improvement check and DD tie-break (`run_study.py:200-202,262`) are not comparable to the baseline and can select the wrong 2025 candidate.

**Recommended fix (do not apply):** validate `exit_ts`, stable-sort closed trades by `exit_ts` with a deterministic tie-break, prepend equity zero, and then compute peak-to-trough drawdown.

### [C4] `run_study.py:312-329` — the 2026 promotion gate omits frozen winner-clipping and monthly-shape requirements

The final survival gate contains only positive net, 90%-of-baseline per-trade/PF, and concentration among positive months (`run_study.py:312-316`). It never calculates whether opposing-flip winners removed/PnL lost erase the saved pre-alignment-stop losses, and it does not compare monthly shape to Baseline A. The positive-month test alone can pass despite a catastrophic losing month. Lines 324-327 can therefore emit `PROMISING` for a candidate that fails two explicit 2026 checks.

Impact: the terminal decision can make a favorable claim unsupported by the frozen selection contract.

**Recommended fix (do not apply):** compute sealed-candidate vs baseline keep/drop outcome attribution, stop savings versus removed-winner loss, and a frozen monthly-shape comparison; make all required checks explicit inputs to the terminal decision.

## Warnings

### [D4] `run_study.py:101-124` and `features/registry.py:351-364` — frozen feature counts are internally inconsistent and stage 1 fails loud

The current registry has 214 `ohlcv_est_delta` entries and **247 total** `price_level_context` entries. Of the latter, two are identity names and 29 (not 28) end in `_position`, leaving 216 numeric columns. The 29 positions follow directly from 13 named base levels plus 16 rolling OHLC levels (`features/registry.py:351-364`). `registry_features` instead requires 275 non-identity entries, 28 positions, and 247 numeric entries (`run_study.py:104-109`). Those conditions cannot hold against the direct dependency, so `manifests()` raises before data loading. The stated F2/F3 dimensions are also arithmetically incompatible with four-way one-hot expansion under the code's claimed counts.

**Recommended fix (do not apply):** reconcile the frozen contract with the accepted registry, explicitly define whether the 247-family count includes identity/categorical fields, and derive/assert the encoded dimensions from that resolved manifest.

### [A/F3] `run_study.py:78-85` — audit acceptance is checked by substring presence, not final counts

The foundation gate passes whenever the file contains the words `critical` and `0`; the local gate passes whenever it contains `critical`, `warning`, and `0`. Any failing report containing a date, a historical "0", a rule identifier, or an earlier audit pass satisfies these tests. The foundation audit itself is append-only and contains earlier summaries of 4 and 1 critical findings before its final zero-critical summary, demonstrating why substring parsing is unsafe.

**Recommended fix (do not apply):** consume a machine-readable final audit status/count record, or strictly parse the uniquely identified final summary and require foundation critical=0 plus local critical=0/warning=0.

### [D2/E3] `run_study.py:220-239,317-323` — fixed-807 overlay cannot perform the promised attribution and parity branch is unreachable

`overlay_status` requires `target_fill_ts` in both the schedule and selected surface (`run_study.py:226-227`), but `load_year` neither requires nor synthesizes it (`run_study.py:147-155`); the accepted `full_{year}.parquet` schemas do not contain that column, so the overlay deterministically returns `NOT_APPLICABLE`. Even when available, it reports only key keep/drop/add and moved-entry IDs, not PnL/outcome attribution, and it never returns a `parity` field. Thus `overlay.get("parity") is False` at lines 320-321 is unreachable.

**Recommended fix (do not apply):** either document a genuinely semantic N/A path and remove the dead parity decision, or use an audited mapping from observation/schedule timestamps and emit the frozen keep/drop/move/add plus outcome/PnL attribution. The overlay must remain non-promotional.

### [D1] `run_study.py:205-217,330-332` — stage-2 JSON serialization is likely to fail on tuple dictionary keys

`diagnostics` converts a grouped `(bin, label)` MultiIndex to a dictionary (`run_study.py:210-211`). Those keys are tuples. `json.dump(..., default=str)` does not convert unsupported dictionary keys, so writing `stage2_report.json` at line 332 raises `TypeError` rather than producing the required report.

**Recommended fix (do not apply):** serialize diagnostics as records or explicitly stringify/structure composite keys before passing them to `atomic_json`.

### [C2/D1] `run_study.py:272-278,330-332` — required outputs and attribution are incomplete

The implementation writes only `feature_manifest.json`, `stage1_candidates.csv`, two JSON reports, and the selection seal. It does not emit the contracted data-readiness tables, class distributions, availability/NaN rates, flat model/calibration tables, gross profit/loss and full exit-reason economics, selected 2025 schedule, selected 2026 trades, stop-savings/winner-clipping attribution, feature coefficients/importances, feature-family contribution, final manifest, or study report. `retention_rows` at line 261 is also calculated after one-per-regime deduplication, so it is not row-level band retention.

**Recommended fix (do not apply):** emit the frozen artifact set with explicit population basis, ordering, hashes, and attribution; do not infer favorable conclusions from the current partial JSON.

## Notes

### [D4] `run_study.py:158-166` — unknown position tokens are silently collapsed to `UNAVAILABLE`

Any value outside `ABOVE/BELOW/TOUCH` is mapped to `UNAVAILABLE` (`run_study.py:161-163`). This is deterministic and not look-ahead, but it hides schema corruption instead of failing closed under the fixed categorical contract.

## Clean checks

- The stage-1 year loop is syntactically restricted to 2021-2025 (`run_study.py:247-251`); no 2026 path is referenced in that stage.
- Training uses only concatenated 2021-2024 rows, while model/feature/band ranking uses 2025 (`run_study.py:251-263`).
- The outcome map is exhaustive and unknown exit reasons fail closed; `loser` remains an explicit zero-weight class (`run_study.py:127-140,178-181`).
- Probability columns are selected through explicit `classes_` lookup rather than positional assumptions (`run_study.py:178-181`).
- Logistic preprocessing is fit only on training rows, with median imputation and scaling inside the pipeline; HistGradientBoosting also uses train-fitted median imputation (`run_study.py:169-175,257`).
- The candidate policy applies the inclusive cutoff first, then stable-sorts and keeps the first qualifying observation per regime (`run_study.py:193-197`). This logic is correct once the cutoff itself is frozen.
- Feature inputs are explicit allowlists; provenance, outcome, PnL, and identity-name columns are not included in model matrices (`run_study.py:88-124,158-166`).
- 2026 diagnostics do not reselect model family or feature set in code; the defect is threshold recalibration and seal/gate integrity, not an explicit label-based 2026 argmax.
- No bracket simulation, reconstructed fill, stop-price fill, resampler, NT bar subscription, or live strategy exists in this study; the corresponding execution checks are not applicable to this post-NT retraining layer.

## Forced compliance matrix

| Rule | Status | Basis |
|---|---|---|
| A1 | N/A | No NT bars are indexed in this study. |
| A2 | N/A | No catalog/bar construction. |
| A3 | N/A | No strategy cache/current-price lookup. |
| A4 | N/A | No timers/events. |
| A5 | WARNING | Timestamp/provenance fields are consumed without validation. |
| B1 | PASS | No centered rolling computation. |
| B2 | WARNING | Accepted causal surface is assumed, not executable-gated by provenance/hash. |
| B3 | N/A | No indicators computed here. |
| B4 | PASS | No negative feature shifts. |
| B5 | PASS | No forward/back fill; train-fitted median imputation only. |
| B6 | N/A | No frequency join. |
| B7 | PASS | Imputation/scaling statistics are train-only. |
| C1 | PASS | Outcome-only future information is confined to target/economic columns. |
| C2 | WARNING | Temporal/label alignment is assumed rather than validated. |
| C3 | CRITICAL | 2026 distribution recalibrates cutoff; no-pass selection can consume test. |
| C4 | CRITICAL | Seal result/manifest integrity and promotion gate are incomplete. |
| D1 | WARNING | Required diagnostics/report serialization and output parity are incomplete. |
| D2 | WARNING | Fixed-807 attribution is unavailable; no live filter cascade exists. |
| D3 | N/A | No ONNX/export. |
| D4 | CRITICAL | Feature-manifest drift can pass; registry dimensions currently mismatch. |
| E1 | N/A | No subscriptions. |
| E2 | N/A | No BarType. |
| E3 | N/A | No venue/fills; fixed-807 overlay is diagnostic only. |
| E4 | CRITICAL | DD is not exit-ordered/comparable to baseline. |
| E5 | N/A | No indicator warmup. |
| F1 | N/A | RTH is inherited from frozen surface. |
| F2 | N/A | Regime/session state is not rebuilt. |
| F3 | CRITICAL | Causal timestamp/provenance constraints are not enforced. |
| F4 | N/A | No timezone session filter is recomputed; monthly conversion is explicit CT. |
| G1 | N/A | Continuous-contract handling is upstream. |
| G2 | WARNING | Upstream gap handling is inherited and foundation warnings are documented dormant. |
| G3 | N/A | No resampling. |
| G4 | N/A | No indicators computed. |
| H1 | N/A | No offline bracket loop. |
| H2 | N/A | No stop monitoring. |
| H3 | N/A | No replay/re-entry simulation. |
| H4 | N/A | No fill-price simulation. |

---

*Audit complete. Findings reflect read-only static analysis plus read-only parquet schema/provenance spot checks. The study and tests were not executed, and no implementation file was modified.*

# Second-Pass Re-Audit

**Date:** 2026-07-19T16:59:01-05:00  
**Patched scope hash (SHA-256 of ordered path list):** `74ee7664ae73313decfefb0fd888a9fb871b092c319d65e4fc558d74d6bdfa9e`  
**Mode:** read-only static re-audit; neither study stage nor tests were executed

## Summary (second pass)

Critical: **2**

Warning: **5**

Overall: FAIL

The patch closes the frozen-cutoff leak, seal-before-2026 ordering defect, feature-manifest drift path, registry dimensions, causal provenance/hash checks, drawdown ordering, audit parsing, and unknown-position handling. The study is still not cleared for execution. One required promotion gate remains causally invalid, and the required output tables are incomplete or structurally corrupt. Three additional fail-loud/output-contract issues also block a complete run.

## Critical findings (second pass)

### [C4] `run_study.py:368-381` — winner-clipping and monthly-shape promotion gates still compare non-identical populations or omit the baseline

The new `prestop_loss_savings` and `winner_clipping` values subtract aggregate selected-schedule PnL from aggregate Baseline-A PnL (`run_study.py:368-370`). The report itself acknowledges these are a "non-identical population" and that no exact Baseline-A schedule exists (`run_study.py:381`). This proxy mixes entry selection, added/dropped regimes, moved entries, and outcomes; it cannot establish that stop savings on comparable opportunities exceed the opposing-flip winners clipped on those same opportunities. Nevertheless `winner_clipping_proxy` is included in `all(survival.values())` and can support `PROMISING` (`run_study.py:370,374-377`).

The two concentration checks examine only the selected schedule's positive and negative months (`run_study.py:361-371`). They never load or compare Baseline-A monthly PnL, so the frozen requirement that monthly shape be "not clearly worse" remains unimplemented. A candidate can therefore receive a favorable terminal decision from an explicitly non-comparable attribution proxy and no baseline monthly-shape comparison.

`prestop_pnl` is now present in both frozen `BASELINE` rows (`run_study.py:42-45`) and is validated from the canonical manifest (`run_study.py:77-85`); the defect is population comparability, not a missing baseline field.

**Recommended fix (do not apply):** construct an audited, identity-aligned Baseline-A comparator or make the winner-clipping/month-shape checks non-promotional and fail closed. Compare saved stop losses and removed opposing-flip winners on matched opportunities, and compare selected versus baseline monthly PnL using a frozen rule.

### [D1/C2] `run_study.py:275-282,353-389` — required result artifacts are incomplete and append operations silently corrupt table schemas

The artifact contract is not merely missing cosmetic files:

- `economic_results.csv` is first written with the stage-1 candidate schema (`run_study.py:280-281`), then stage-2 rows with different fields/order are appended without a header (`run_study.py:353-356,387`). Values such as `split`, `layer`, and `schedule_trades` are written under unrelated stage-1 column names, with extra trailing fields. This is a silently malformed economic table.
- `feature_family_contribution.csv` is created with two columns (`feature_set`, `raw_model_features`) at line 282, then a four-column row (`schedule_id`, `split`, `feature_set`, `matching_f0_checks`) is appended without a header at line 388. It is structurally invalid and contains no measured volume/delta-versus-price-level contribution.
- `calibration_deciles.csv` is deliberately written as an empty header-only placeholder (`run_study.py:389`) despite calibration values having been computed.
- Monthly and exit-reason outputs cover only the single selected 2026 schedule (`run_study.py:385-386`), not the required feature-set × model × retention-band economics/attribution. The 48 frozen-cutoff 2026 schedules receive only aggregate `economic()` rows and no monthly/count or exit-reason breakdown (`run_study.py:353-356`).
- `model_diagnostics.csv` stores nested dictionaries in cells rather than the required normalized per-model/per-split diagnostics and does not emit coefficients/importances (`run_study.py:384`).

Impact: even if execution reached these lines, required artifacts would either be empty, semantically incomplete, or silently mis-columned; they cannot support the study's comparisons or be consumed reproducibly.

**Recommended fix (do not apply):** define and assert one stable schema per artifact, write stage-1 and stage-2 rows by named columns (or rewrite the complete table atomically), flatten diagnostics/calibration to records, and emit substantive attribution plus monthly/exit breakdowns for every required schedule.

## Warnings (second pass)

### [C2/F3] `run_study.py:170-177` — the new input gate rejects the accepted gap-snapped surfaces and validates RTH on the wrong timestamp

Line 173 requires `entry_ts == observation_time` for every row. Read-only inspection of the trusted, hash-matching accepted surfaces shows this is false on exactly the documented gap-snapped populations: 11,119 rows in 2021, 8,396 in 2025, and 2,079 in 2026 (and corresponding rows in the other years). `observation_time`/`observation_ts` is the feature decision timestamp; `entry_ts` is the actual gap-snapped fill timestamp and may legitimately be later. Stage 1 therefore fails loud while loading 2021.

Line 177 checks the RTH window using `observation_ts`. The frozen population convention is remediated fill-time RTH, so the population assertion must be made on `entry_ts` (with any desired decision-time check stated separately). Trusted hashes make the current artifacts immutable, but the validation semantics are still wrong.

**Recommended fix (do not apply):** require `observation_ts == observation_time <= entry_ts <= exit_ts`, retain the feature-provenance bounds at observation time, and validate the RTH population on `entry_ts` converted to America/Chicago.

### [D1] `run_study.py:235-247,380-382` — tuple-key diagnostic dictionaries still make stage-2 JSON serialization fail

`outcome_score_deciles` is still produced by calling `.to_dict()` on a `(bin, label)` MultiIndex (`run_study.py:240-241`), producing tuple dictionary keys. `json.dump(..., default=str)` does not transform unsupported dictionary keys. `atomic_json(stage2_report.json, report)` at line 382 therefore raises `TypeError` before any of the stage-2 parquet/CSV/manifest/report writes at lines 383-391 occur.

**Recommended fix (do not apply):** serialize outcome/calibration bins as ordinary records or explicitly structured string-key dictionaries.

### [D2/E3] `run_study.py:250-269` — fixed-807 overlay is available now but remains incomplete attribution

Using `entry_ts` resolves the prior guaranteed-schema failure, and the overlay now reports kept-selected total/exit-reason PnL. It still does not report drop/add PnL and outcome attribution, baseline PnL on kept regimes, or moved-entry effects. It also returns `AVAILABLE` without an explicit semantic parity flag. This is acceptable only as the documented non-promotional overlay; it does not satisfy the requested keep/drop/move/add attribution by itself.

### [C4/D1] `run_study.py:372-391` — terminal labels and study-report/manifest paths do not match the frozen output contract

The terminal labels are shortened to `BASELINE_STILL_BEST`, `OVERFITS`, `PROMISING`, and `REJECT` (`run_study.py:372-379`), rather than the exact frozen labels `ENRICHED_RETRAIN_BASELINE_STILL_BEST`, `ENRICHED_RETRAIN_OVERFITS_2025`, `ENRICHED_RETRAIN_CLIPS_WINNERS`, `ENRICHED_RETRAIN_PROMISING`, `ENRICHED_RETRAIN_PARITY_FAIL`, and `ENRICHED_RETRAIN_REJECT`. There is no distinct clips-winners or parity-fail outcome.

The final report is written to `results/STUDY_REPORT.md` (`run_study.py:391`), not the required study-root `STUDY_REPORT.md`. Additionally, the `manifest.json` artifact list is evaluated before `manifest.json` itself and `STUDY_REPORT.md` are written (`run_study.py:390-391`), so it cannot enumerate the final artifact set even at its chosen paths.

### [D1] `tests/test_study.py:5-30` — tests remain substring checks and do not guard the repaired causal/output semantics

The added tests assert only that selected strings occur in source. They do not exercise gap-snapped timestamp semantics, seal validation before any 2026 read, frozen-cutoff application, exit-ordered DD, JSON serializability, stable CSV schemas, non-empty calibration, complete 48-schedule monthly/exit tables, exact terminal labels, or root report placement. This is a coverage warning; no tests were run during this audit as instructed.

## Prior-finding disposition

| First-pass finding | Second-pass status | Evidence |
|---|---|---|
| Feature-manifest drift can pass | CLOSED | Canonical manifest plus registry/F0 hashes are sealed and checked before 2026 (`run_study.py:318-336`). |
| Seal result/stage/decision not validated before 2026 | CLOSED | Stage, selected decision, result hash, membership, dependencies, inputs, and manifest validate before line 338 opens 2026 (`run_study.py:323-338`). |
| 2026 quantile recalibration | CLOSED | Stage 2 applies each sealed 2025 `candidate["cutoff"]`; no 2026 quantile is derived (`run_study.py:353-359`). |
| No trusted/provenance validation | CLOSED WITH NEW WARNING | Trusted hashes and causal provenance checks added (`run_study.py:158-180`); `entry_ts` equality/RTH semantics are wrong as described above. |
| DD ordering/zero baseline | CLOSED | Stable exit-time ordering and leading zero are present (`run_study.py:210-214`). |
| Promotion omits clipping/month shape | OPEN CRITICAL | Metrics were added, but attribution is non-comparable and baseline monthly shape remains absent (`run_study.py:368-381`). |
| Registry counts/dimensions mismatch | CLOSED | 247 total, two identities, 29 positions, 216 numeric; F2=481/F3=695 (`run_study.py:115-139`). |
| Audit substring parser | CLOSED | Final-summary sections are isolated and exact zero/PASS markers required (`run_study.py:88-99`). |
| Fixed-807 guaranteed N/A | PARTIAL | Correct fill field now used, but attribution remains incomplete (`run_study.py:250-269`). |
| Tuple-key JSON failure | OPEN WARNING | MultiIndex tuple-key conversion unchanged (`run_study.py:240-241`). |
| Required outputs incomplete | OPEN CRITICAL | Empty/malformed/incomplete tables remain (`run_study.py:275-282,353-391`). |
| Unknown positions silently collapsed | CLOSED | Unknown non-null tokens now fail closed (`run_study.py:183-192`). |

## Clean checks (second pass)

- Canonical baseline, foundation manifest, and all six input SHA-256 constants match the current files by independent read-only hash verification.
- Stage 1 enumerates only 2021-2025 and does not construct or read the 2026 surface.
- 2021-2024 training, 2025 selection, and 2026 post-seal evaluation are separated in code.
- The selected absolute 2025 cutoff is applied unchanged to 2026 for the chosen candidate and all 48 diagnostic schedules.
- Inclusive thresholding followed by stable first-qualifying-observation-per-regime selection is preserved.
- Registry family counts and encoded feature dimensions now match the actual verified registry.
- Model score probability mapping remains explicit by `classes_`; no positional class assumption or 2026 label-based reselection was introduced.
- Input hashes, provenance timestamps, outcome finiteness, population direction, labels, and unique keys now mostly fail closed, subject to the gap-snap/RTH correction above.
- Closed-trade-sequence drawdown now matches the baseline ordering and zero-equity convention.
- Train-only median imputation and deterministic feature order remain intact.

---

*Second-pass audit complete. The study and tests were not executed. Only this audit report was modified.*

# Third-Pass Re-Audit

**Date:** 2026-07-19T17:08:03-05:00  
**Patched scope hash (SHA-256 of ordered path list):** `1bde9893cb981284e9f52f120d27c9aa6738d8647291b320a272c401dfb51257`  
**Mode:** read-only static re-audit with read-only hash/schema checks; the study and tests were not executed

## Summary (third pass)

Critical: **2**

Warning: **4**

Overall: FAIL

The third patch closes the second-pass gap-snap/fill-RTH failure, tuple-key JSON defect, append-schema corruption, placeholder calibration, aggregate-only attribution, shortened principal decision labels, and misplaced root report. The study is still not cleared for execution. Stage 1 exposes 2026-derived baseline results before sealing 2025, and two promotion predicates can still emit a favorable decision without satisfying their exact stated meanings.

## Critical findings (third pass)

### [C3/C4] `run_study.py:43-47,79-87,330-365` — stage 1 reads, validates, returns, and seals 2026 baseline outcomes before 2025 selection

`stage1()` calls `load_baseline()` before it loads the 2021-2025 feature surfaces (`run_study.py:330-335`). `load_baseline()` explicitly parses both the 2025 and **2026** candidate/control summary rows (`run_study.py:79-83`) and validates the 2026 per-trade, PF, DD, pre-stop rate, opposing-flip PnL, and pre-stop PnL against constants already embedded at lines 46-47. Stage 1 then writes the full `BASELINE` object, including the 2026 outcomes, into the selection seal (`run_study.py:363-365`).

The 2025 ranking presently indexes only `BASELINE[2025]`, so there is no direct 2026 term in the sort. Nevertheless, the reproduction contract says the first command must not open 2026, and a sealed-test protocol cannot expose six aggregate 2026 outcome statistics to the selection stage/operator and still claim that 2026 was unseen. The code hash and study source themselves also disclose those values before sealing.

Impact: 2026 can influence model-development or manual selection judgment before the purported atomic seal, invalidating the one-shot holdout discipline even though the current automated ranking uses 2025 only.

**Recommended fix (do not apply):** separate baseline artifacts/constants by stage. Stage 1 may hash-commit to an opaque 2026 baseline artifact but must parse, validate, return, report, and seal only the 2025 comparator. Load/validate 2026 baseline metrics and trades only in stage 2 after every selection-seal check succeeds.

### [C4] `run_study.py:102-113,424-439` — signed attribution and the implemented "positive-month share" can pass candidates that fail the frozen gates

`exact_attribution` correctly outer-joins the selected schedule and Baseline A by `regime_start_ns`, but it returns both signed `clipped_winners_exact` and the non-negative `clipped_winners_floor` (`run_study.py:102-113`). The promotion gate ignores the floor and evaluates `clipped_winners_exact <= stop_savings_exact` (`run_study.py:424-426`). It also does not require stop savings to be non-negative. For example, a candidate with `stop_savings_exact=-10` (pre-stop opportunities worsened) and `clipped_winners_exact=-50` (baseline-winner opportunities improved) passes because `-50 <= -10`, even though it produced no stop savings. This does not implement "winner clipping must not exceed exact comparable pre-stop savings."

The SPEC freezes "selected positive-month share no more than 10pp below Baseline A's positive-month share" (`SPEC.md:27-29`). Line 428 instead computes positive **PnL dollars divided by gross absolute monthly PnL dollars**, not the share of months with positive PnL. The adjacent concentration gate already covers PnL magnitude. A schedule with fewer positive months can therefore pass if those few months contain enough dollars.

Both predicates feed `all(survival.values())` and can support `ENRICHED_RETRAIN_PROMISING` (`run_study.py:426-437`).

**Recommended fix (do not apply):** require `stop_savings_exact >= 0` and compare `clipped_winners_floor <= stop_savings_exact`; define positive-month share explicitly as `count(monthly_pnl > 0) / count(months)` on a common frozen month index and compare percentage points to Baseline A.

## Warnings (third pass)

### [D1] `run_study.py:238-245,309-315,405-412` — all 96 economics schedules are generated, but empty schedules lose the promised monthly/exit coverage and have a reduced metric schema

The nested loop statically covers 4 feature sets × 2 models × 6 bands × 2 splits = **96** frozen-cutoff schedules, and emits one economics and one retention row for each (`run_study.py:392-412`). However, `schedule_breakdowns` returns no monthly or exit rows for an empty schedule (`run_study.py:309-310`), so those tables do not guarantee representation of all 96 schedule IDs. `economic(empty)` likewise returns only seven fields (`run_study.py:238-239`) rather than the full non-empty metric schema at lines 240-245, causing blank/NaN columns instead of explicit zero/undefined values.

This is an output-completeness warning rather than a causal leak; whether it triggers depends on whether a sealed 2025 cutoff retains any 2026 row for every candidate.

### [D2/E3] `run_study.py:276-295` — fixed-807 overlay remains partial keep/drop/move/add attribution

The overlay now has correct fill-time input and is explicitly diagnostic/non-promotional. It reports counts, moved regime IDs, and selected PnL for kept regimes, but not baseline kept PnL, dropped/added outcome PnL, or moved-entry PnL deltas. The exact Baseline-A attribution at lines 102-113 is substantive and promotional; this warning concerns only the separately promised Layer-3 fixed-807 table.

### [C4/D1] `run_study.py:430-463` — exact final-label and manifest coverage remain incomplete

Five exact labels are now present: `ENRICHED_RETRAIN_BASELINE_STILL_BEST`, `...CLIPS_WINNERS`, `...OVERFITS_2025`, `...PROMISING`, and `...REJECT` (`run_study.py:430-439`). The frozen `ENRICHED_RETRAIN_PARITY_FAIL` label is still absent; baseline/hash/count parity errors raise instead of producing that terminal result.

The study report is correctly written at the study root (`run_study.py:460`). The final manifest enumerates only files under `results/` (`run_study.py:461-463`), so it omits the root `STUDY_REPORT.md` and `REPRODUCE.md` from the reproducibility artifact inventory. Its self-reference intentionally has no byte count/hash, which is acceptable if documented, but the root report should be listed and hashed.

### [C3/C4/D1] `tests/test_study.py:14-33` — synthetic tests do not exercise the claims in their names or the remaining gate/output boundaries

The cutoff test derives and applies a cutoff to the same score vector (`tests/test_study.py:14-18`); it does not apply a 2025-derived cutoff to a shifted 2026 distribution and therefore does not demonstrate future-distribution invariance. `test_attribution_and_diagnostics_are_json_records` never calls `diagnostics`; it only JSON-serializes the one-row attribution dictionary (`tests/test_study.py:29-33`). The attribution fixture covers a kept pre-stop only, not dropped/added regimes, winners, signed negative savings, or the clipping floor.

There are no synthetic assertions for gap-snapped `observation_time < entry_ts`, fill-time RTH, 96 unique schedules in all required outputs, stable/full schemas for empty schedules, non-empty calibration, positive-month count share, exact final labels, root report placement, or manifest inventory. The tests are materially better than substring checks but still do not guard the repaired causal/output contract.

## Second-pass finding disposition

| Second-pass finding | Third-pass status | Evidence |
|---|---|---|
| Non-comparable aggregate winner/month gate | PARTIAL / OPEN CRITICAL | Exact hash-gated Baseline-A trade matching is added (`run_study.py:90-113,424-429`), but the signed clipping and positive-month-share predicates are wrong. |
| Malformed/incomplete artifact tables | MOSTLY CLOSED | Separate atomic rewrites and substantive tables now exist (`run_study.py:390-459`); empty-schedule coverage remains a warning. |
| Gap-snapped input rejected / RTH on wrong time | CLOSED | The gate now requires `observation <= entry <= exit` and classifies RTH on `entry_ts` (`run_study.py:198-205`). Independent read-only checks confirm all six trusted surfaces satisfy these conditions. |
| Tuple-key JSON serialization failure | CLOSED | Diagnostics and calibration are ordinary scalar-key records (`run_study.py:263-273,397-400`). |
| Fixed-807 overlay incomplete | OPEN WARNING | Still partial, but remains explicitly non-promotional. |
| Short labels / wrong report path / incomplete manifest | PARTIAL | Principal labels and root report fixed; parity label and root-file inventory remain absent. |
| Substring-only tests | PARTIAL | Real synthetic tests added, but key claims remain unexercised. |

## Clean checks (third pass)

- Baseline trade-table SHA-256 constant matches the current parquet; its 650/222 candidate/control population is hash-gated and keyed uniquely by regime.
- Gap-snap semantics are now correct: `observation_time == observation_ts <= entry_ts <= exit_ts`; causal feature provenance remains bounded at observation time.
- RTH validation is performed on actual `entry_ts` in America/Chicago. Read-only inspection confirms the trusted 2021-2026 inputs pass.
- Registry counts/dimensions, train-only preprocessing, explicit class probability mapping, and exhaustive labels remain correct.
- All selection-seal, dependency-hash, input-hash, and canonical-manifest checks still occur before `full_2026.parquet` is opened.
- Every 2026 candidate uses its immutable 2025 cutoff. No model, family, band, or cutoff is reselected from 2026 labels/results.
- DD remains stable exit-ordered with a leading-zero equity point.
- Diagnostics are JSON-safe scalar records; calibration rows are substantive rather than placeholder output.
- Economics and retention tables are rewritten with consistent named schemas rather than appended under mismatched headers.
- The nested evaluation constructs 96 schedule-level economics/retention rows and schedule-level monthly/exit breakdowns for every non-empty schedule.
- `feature_family_contribution.csv` now contains same-model/band/split F1/F2/F3 deltas versus F0; logistic coefficients and the HistGradientBoosting importance limitation are explicitly reported.
- The root `STUDY_REPORT.md` path and five principal enriched-retrain decision labels are correct.

---

*Third-pass audit complete. The study and tests were not executed. Only this audit report was modified.*

# Fourth-Pass Re-Audit

**Date:** 2026-07-19T17:11:22-05:00  
**Patched scope hash (SHA-256 of ordered path list):** `78699535c714d85cfd2470a3ded23a2722ed121fe566300636a7623dbd55363d`  
**Mode:** read-only static re-audit; neither study stage nor tests were executed

## Summary (fourth pass)

Critical: **1**

Warning: **3**

Overall: FAIL

The fourth patch closes the signed clipping/savings defect, implements positive-month count share, gives empty schedules a full economics schema plus explicit breakdown sentinels, and adds a parity decision helper. Zero/zero acceptance is not reached. Stage 1 still exposes and seals 2026 baseline outcomes before selection, and three output/test warnings remain open.

## Critical findings (fourth pass)

### [C3/C4] `run_study.py:34-47,79-87,339-374` — stage 1 still opens and seals 2026-derived baseline information

The patch changes `load_baseline()` to accept a year and stage 1 calls `load_baseline(2025)` (`run_study.py:79-87,339-340`). This narrows which summary row is used, but it does **not** satisfy sealed isolation:

- `load_baseline(2025)` reads and parses the entire shared manifest file at lines 80-82. That file contains the 2026 summary and is therefore a 2026-derived result artifact.
- The source still hard-codes six 2026 Baseline-A outcome metrics in `BASELINE[2026]` (`run_study.py:43-47`), so they are visible before selection.
- Most directly, stage 1 writes `"baseline": BASELINE` into `_work/selection_seal.json` (`run_study.py:372-374`), embedding both the 2025 and 2026 outcome dictionaries in the pre-2026 seal. Only `result["baseline"]` is correctly narrowed to 2025 (`run_study.py:370`).

The automated rank continues to use only `BASELINE[2025]`, but the explicit contract is that the first command must not open/expose 2026 and that 2026 cannot influence selection or operator judgment. That requirement remains violated.

**Recommended fix (do not apply):** put the 2025 comparator in a genuinely 2025-only artifact/constant used by stage 1. Remove all 2026 outcome constants and values from stage-1-reachable module state and the selection seal. Hash-commit to the unopened 2026 baseline artifact if desired, then parse/validate its values only in stage 2 after all seal checks and the 2026 surface open boundary.

## Warnings (fourth pass)

### [D2/E3] `run_study.py:284-303` — fixed-807 Layer-3 overlay remains only partial attribution

The overlay is correctly non-promotional and reports keep/drop/add counts, moved-entry IDs, kept selected net PnL, and kept selected exit-reason PnL. It still omits baseline kept PnL, dropped/added outcome/PnL, and moved-entry PnL deltas. Thus it does not provide the full keep/drop/move/add attribution requested for Layer 3. The separate Baseline-A promotion attribution is now exact and is not affected by this warning.

### [C4/D1] `run_study.py:263-268,441,462-465` — final decision/output inventory remains incomplete

`ENRICHED_RETRAIN_PARITY_FAIL` now exists in `final_decision` (`run_study.py:263-264`), but the only call always passes `parity_ok=True` (`run_study.py:441`); parity failures elsewhere raise, so the label is unreachable. The frozen `ENRICHED_RETRAIN_REJECT` label is absent entirely from the decision helper.

The root `STUDY_REPORT.md` is now written correctly (`run_study.py:462`), but the manifest enumerates only `results/` files (`run_study.py:463-465`) and omits the root report and `REPRODUCE.md`. On a rerun, an old `results/manifest.json` is also included once with a stale hash by the directory scan and then a second time as the unhashed self-reference entry.

### [C3/C4/D1] `tests/test_study.py:14-33` — synthetic tests are unchanged and still do not verify the repaired contract

The tests remain byte-for-byte unchanged from the third pass. The cutoff test applies the cutoff to the same distribution from which it was derived, not to a shifted future distribution. The test named for diagnostics never calls `diagnostics`. The attribution fixture covers only one kept pre-stop and does not test clipped winners, negative savings, the floor, keep/drop/add, or month gates.

There are still no tests for gap-snapped fill-time RTH, stage-1 absence of 2026 baseline access, 96 unique schedule IDs across outputs, empty-schedule full schemas/sentinels, non-empty calibration, exact final decisions, or manifest/root-report completeness.

## Third-pass finding disposition

| Third-pass finding | Fourth-pass status | Evidence |
|---|---|---|
| Stage 1 exposes 2026 baseline outcomes | OPEN CRITICAL | Year-filtered parsing was added, but shared-manifest parsing, source constants, and the full-baseline seal remain (`run_study.py:34-47,79-87,339-374`). |
| Signed clipping/savings and wrong positive-month share | CLOSED | Stop savings must be non-negative; clipped winners are floored; month share counts positive months (`run_study.py:436-440`). |
| Empty schedule breakdown/schema | CLOSED | Full zero metric schema and explicit `NO_TRADES`/zero exit rows added (`run_study.py:238-245,317-324`). |
| Fixed-807 attribution partial | OPEN WARNING | No material change (`run_study.py:284-303`). |
| Parity/final labels and manifest coverage | PARTIAL / OPEN WARNING | Parity helper added; reject path and reachable parity path absent; root files omitted from manifest. |
| Synthetic coverage gaps | OPEN WARNING | Tests unchanged (`tests/test_study.py:14-33`). |

## Clean checks (fourth pass)

- Exact Baseline-A promotion attribution remains keyed by `regime_start_ns` against the hash-gated 650/222 candidate/control table.
- The stop-savings gate now explicitly requires non-negative savings, and non-negative winner clipping is compared against non-negative savings.
- Monthly worst-loss, positive-month count share, and gross absolute concentration gates match the written SPEC formulas.
- Empty schedules now retain the complete economic schema and explicit monthly/exit sentinel rows, so all 96 schedule IDs can be represented in every required table.
- Gap-snap, fill-time RTH, provenance, immutable cutoff, seal-before-2026-surface, feature manifest, DD ordering, JSON diagnostics/calibration, and non-appending table schemas remain clean.
- Root `STUDY_REPORT.md` placement is correct, and substantive F1/F2/F3-vs-F0 contribution output remains present.

---

*Fourth-pass audit complete. The study and tests were not executed. Only this audit report was modified.*

# Fifth-Pass Re-Audit

**Date:** 2026-07-19T17:15:13-05:00  
**Patched scope hash (SHA-256 of ordered path list):** `7eb2dafcb6c07628a8f489de9ebe268bd0390670cfbaaff6014911edbb5afba3`  
**Mode:** read-only static re-audit; neither study stage nor tests were executed

## Summary (fifth pass)

Critical: **2**

Warning: **2**

Overall: FAIL

The fifth patch successfully separates stage-1 2025 baseline values from stage-2-only 2026 baseline paths/values, orders seal validation before the lazy 2026 import and 2026 surface open, and makes the fixed-807 overlay explicitly `NOT_APPLICABLE`. Zero/zero is not reached because neither new baseline dependency is anchored to the appropriate immutable trust boundary, while final-decision/manifest and synthetic-test warnings remain.

## Critical findings (fifth pass)

### [C3/C4] `run_study.py:34,70-74,296-330` and `baseline_2025.json:1-9` — the new 2025 baseline is mutable and self-sealed rather than trusted

Stage 1 now reads only `baseline_2025.json`, which contains no 2026 value. However, `load_baseline_2025()` accepts whatever numeric values are currently in that file as long as the expected keys and a freely editable provenance string exist (`run_study.py:70-74`). There is no hard-coded trusted SHA-256 or reconciliation to a hash-gated canonical 2025 trade/manifest artifact before those values determine all five economic checks (`run_study.py:296-313`). Stage 1 then hashes the already-consumed file into its own seal (`run_study.py:327-330`).

Hashing an input after accepting it proves only that stage 2 sees the same file; it does not prove that stage 1 used the frozen Baseline A. A same-schema edit to per-trade, PF, DD, pre-stop rate, or opposing-flip PnL silently changes which candidate wins and is then self-certified by the new seal.

The current file's read-only SHA-256 is `8ec12511477d81300d036fcc93c315d0878cb334076a64e182f1ee5435110e09`, and its values match the known 2025 comparator, but the executable trust gate does not enforce that identity.

**Recommended fix (do not apply):** pin an independently supplied expected hash for `baseline_2025.json` in the stage-1 code/contract, or reconcile it against a separately hash-gated 2025-only canonical trade artifact, before using any value for selection.

### [C4/D3] `run_study.py:334-351` and `sealed_2026.py:8-28` — the lazy 2026 module is not committed by the selection seal and its returned metrics are not fully reconciled

Stage 2 correctly validates the run code, 2025 baseline, registry/F0 dependencies, 2021-2025 inputs, and feature manifest before lazily importing `sealed_2026.py` (`run_study.py:334-351`). But the selection seal contains no expected hash for `sealed_2026.py`, and stage 2 does not verify one before import. The module can therefore be changed after 2025 selection without invalidating the seal.

This matters because `sealed_2026.py:13` hard-codes all six comparator metrics used by the survival gates. `load_baseline()` validates the source manifest hash and only the 2026 `net_pnl` (`sealed_2026.py:20-24`); it does not reconcile the returned per-trade, PF, DD, pre-stop rate, opposing-flip PnL, or pre-stop PnL field-by-field against the manifest. A post-seal edit to those constants silently changes the 2026 pass/fail decision while all current stage-2 checks pass.

The current module's read-only SHA-256 is `a84a1ebbdfc517c3328b437d250bdacdb265ac7cdcf8f304c62dd93f75e18199`.

**Recommended fix (do not apply):** include an opaque expected `sealed_2026.py` hash in the stage-1 seal without importing/parsing the module, require it before lazy import, and reconcile every returned baseline field to the hash-gated canonical 2026 manifest row.

## Warnings (fifth pass)

### [C4/D1] `run_study.py:238-243,399-423` — not all frozen terminal decisions are reachable and the final manifest omits root artifacts

`final_decision` defines parity fail, baseline still best, clips winners, overfits, and promising (`run_study.py:238-243`). `ENRICHED_RETRAIN_REJECT` remains absent. The only call still supplies `parity_ok=True` (`run_study.py:399`), so `ENRICHED_RETRAIN_PARITY_FAIL` is syntactically present but unreachable; parity exceptions produce no terminal report.

The root `STUDY_REPORT.md` is written correctly (`run_study.py:420`), but `manifest.json` inventories only files inside `results/` (`run_study.py:421-423`), omitting root `STUDY_REPORT.md`, `REPRODUCE.md`, `SPEC.md`, `baseline_2025.json`, and the stage-2 dependency identity. On reruns, the directory scan can also include the prior manifest with a stale hash and then append a second self-reference entry.

### [C3/C4/D1] `tests/test_study.py:14-33` — requested synthetic semantics are still not exercised

The test file is unchanged from passes three and four. The cutoff test does not use a shifted future distribution; the diagnostics-named test never calls `diagnostics`; attribution tests only one kept pre-stop. There are no tests for stage-1 import/global/seal absence of 2026 dependencies, seal-before-lazy-import ordering, baseline file hash rejection, sealed-module hash rejection, field-by-field 2026 reconciliation, clipping/month gates, explicit overlay N/A, all terminal decisions, 96-output coverage, or manifest/root-report inventory.

## Fourth-pass finding disposition

| Fourth-pass finding | Fifth-pass status | Evidence |
|---|---|---|
| Stage 1 exposes/seals 2026 baseline | CLOSED | Module globals and stage-1 call graph contain only the 2025-only file; the seal contains only 2025 baseline values (`run_study.py:34,296-330`). |
| Fixed-807 overlay partial | CLOSED | It now fails explicitly to `NOT_APPLICABLE` with favorable claims prohibited (`run_study.py:259-260`). |
| Decision/manifest completeness | OPEN WARNING | Parity unreachable, reject absent, root artifacts omitted (`run_study.py:238-243,399-423`). |
| Synthetic coverage gaps | OPEN WARNING | Tests unchanged (`tests/test_study.py:14-33`). |

## Clean checks (fifth pass)

- Importing `run_study.py` does not import `sealed_2026.py`; no 2026 baseline path or outcome value exists in run-module globals or stage-1 seal construction.
- Stage 1 enumerates only 2021-2025 surfaces and uses only the separate 2025 baseline file.
- Stage 2 completes all selection-seal/dependency/input/manifest checks before the lazy `sealed_2026.py` import, then loads the 2026 baseline, then opens `full_2026.parquet`.
- Immutable 2025 cutoffs, temporal split, provenance/gap-snap/fill-RTH semantics, exact regime-key attribution, clipping/savings/month gates, DD, score mapping, registry dimensions, and train-only preprocessing remain clean.
- Fixed-807 is explicitly N/A and cannot support a favorable claim.
- Empty schedules retain full economics and explicit breakdown sentinels; 96 schedule IDs are constructed across the two splits.
- Calibration, diagnostics, feature-family contribution, root report placement, and non-appending CSV schemas remain substantively implemented.

---

*Fifth-pass audit complete. The study and tests were not executed. Only this audit report was modified.*

# Sixth-Pass Re-Audit

**Date:** 2026-07-19T17:20:30-05:00  
**Scope hash (SHA-256 of ordered path list):** `7eb2dafcb6c07628a8f489de9ebe268bd0390670cfbaaff6014911edbb5afba3`  
**Mode:** read-only static re-audit with read-only SHA verification; neither study stage nor tests were executed

## Summary (sixth pass)

Critical: **0**

Warning: **1**

Overall: FAIL

Both fifth-pass critical findings are closed. The trusted SHA pins match the current 2025 baseline and stage-2 module, the seal commits the stage-2 identity without importing it, every 2026 baseline gate metric is reconciled, and parity failures have an exact reported outcome. One workflow-reachability warning prevents the required zero-warning acceptance: `ENRICHED_RETRAIN_REJECT` is unit-callable but cannot be emitted by an actual stage path.

## Warnings (sixth pass)

### [C4/D1] `run_study.py:256-263,333-383` and `tests/test_study.py:86-94` — `ENRICHED_RETRAIN_REJECT` is not reachable through the real two-stage workflow

`final_decision()` correctly defines all six exact labels, including `ENRICHED_RETRAIN_REJECT` when `chosen is None` (`run_study.py:256-263`). The synthetic test proves only direct function reachability by manually calling `final_decision(True, None, ...)` (`tests/test_study.py:86-94`).

The production workflow cannot take that branch:

- Stage 1 records a failed 2025 selection as the internal string `"no-pass"` with `selection=None` (`run_study.py:333-347`), rather than emitting the exact terminal reject label/report.
- Stage 2 requires `seal.result.decision == "selected"` in its first validation condition (`run_study.py:354-358`) and later also rejects a missing selection (`run_study.py:382-383`). It therefore never calls `final_decision()` with `chosen=None`.
- The final fallback reject at `run_study.py:263` is also unreachable for a valid chosen candidate, because feature sets are constrained to F0/F1/F2/F3; F0 returns baseline-still-best and F1/F2/F3 return one of the other exact outcomes.

Impact: a legitimate no-2025-candidate outcome produces only an internal `no-pass` stage-1 state and no final eight-question report/manifest with the frozen `ENRICHED_RETRAIN_REJECT` decision. The test overstates end-to-end reachability.

**Recommended fix (do not apply):** make stage 1's no-pass path atomically emit the exact reject decision and complete terminal artifacts without opening 2026, or add a pre-2026 orchestration path that calls `final_decision(True, None, ...)` and writes the final report/manifest. Test that real path, not only the helper.

## Fifth-pass finding disposition

| Fifth-pass finding | Sixth-pass status | Evidence |
|---|---|---|
| 2025 baseline mutable/self-sealed | CLOSED | `BASELINE_2025_SHA256` is pinned and checked before parsing; current file hash matches (`run_study.py:34-35,73-79`). |
| Stage-2 module not sealed / incomplete reconciliation | CLOSED | Expected module hash is committed in stage 1, checked before import, and all six metrics reconcile to the hash-gated manifest (`run_study.py:36-37,349-375`; `sealed_2026.py:20-27`). |
| Parity label/error path | CLOSED | Module/baseline/trade parity failures write `ENRICHED_RETRAIN_PARITY_FAIL` before raising (`run_study.py:368-379,422-427`). |
| Reject label reachability | OPEN WARNING | Helper-only, not stage-workflow reachable (`run_study.py:256-263,333-383`). |
| Manifest/root artifact completeness | CLOSED | Prior manifest is excluded; results plus root report/SPEC/reproduction/baseline/module/audit are hashed, with one explicit self-reference (`run_study.py:495-500`). |
| Eight-question report | CLOSED | Root report contains selected economics, baselines, all eight required answers, Layer-3 limitation, and audit status (`run_study.py:458-495`). |
| Synthetic tests | SUBSTANTIALLY CLOSED | Tests now cover shifted-score cutoff invariance, exit-ordered DD, labels/categories, gap-snap/fill-RTH, JSON diagnostics/calibration, empty schedules, 96 IDs, and helper decision labels (`tests/test_study.py:17-94`). The reject test's end-to-end overclaim is the single remaining warning. |

## Clean checks (sixth pass)

- `baseline_2025.json` current SHA-256 equals the pinned `8ec12511477d81300d036fcc93c315d0878cb334076a64e182f1ee5435110e09`.
- `sealed_2026.py` current SHA-256 equals the pinned `ac9521c385086ba1c282a8859f40de3080d6731882ac1b663a4b50753f19b354`.
- Stage 1 does not import, open, or embed any 2026 baseline path/value; it seals only the opaque expected module hash.
- Stage 2 authenticates the selection seal and stage-2 file hash before lazy import, reconciles the baseline before opening the 2026 surface, and catches baseline/trade parity errors with the exact parity label.
- All six 2026 baseline fields—per-trade, PF, DD, pre-stop rate, opposing-flip PnL, and pre-stop PnL—are checked field-by-field against the hash-gated canonical manifest; net PnL is separately reconciled.
- Fixed-807 remains explicit `NOT_APPLICABLE` with favorable claims prohibited.
- Clipping/savings/month gates, immutable cutoff, timestamp/population semantics, 96-schedule tables, diagnostics/calibration, contribution output, and empty-schedule schemas remain clean.
- Root report and manifest inventory are materially complete and do not include a stale prior manifest hash.

---

*Sixth-pass audit complete. The study and tests were not executed. Only this audit report was modified.*

# Seventh-Pass Re-Audit

**Date:** 2026-07-19T17:24:28-05:00  
**Scope hash (SHA-256 of ordered path list):** `4d090f1448192692ffdc285501e00de593efae0037517013c405c205805a8282`  
**Mode:** read-only static re-audit with read-only SHA verification; neither study stage nor tests were executed

## Summary (seventh pass)

Critical: **0**

Warning: **0**

Note: **0**

Overall: PASS

The sole sixth-pass warning is closed. A real no-pass result in stage 1 now calls `final_decision(True, None, None, {})`, records the exact `ENRICHED_RETRAIN_REJECT` label with `selection=None`, commits that result to the selection seal, and writes the terminal eight-question `STUDY_REPORT.md` plus `results/manifest.json` (`run_study.py:316-342,362-382`). On that sealed rejection, `evaluate_2026` validates the seal and immediately returns at `run_study.py:392-394`; the first resolution, hash, and import of `sealed_2026.py` occurs only at `run_study.py:403-408`, and the first 2026 surface load occurs at `run_study.py:415-416`.

## Sixth-pass finding disposition

| Sixth-pass finding | Seventh-pass status | Evidence |
|---|---|---|
| Reject label reachable only through helper | CLOSED | The production no-pass branch derives the exact label through `final_decision`, seals it, and invokes the rejection artifact writer (`run_study.py:316-342,362-382`). |
| Rejected `evaluate_2026` could expose 2026 | CLEAN | The authenticated reject branch returns at `run_study.py:392-394`, before any 2026 module path resolution/import or surface load at `run_study.py:403-416`. |

## Focused regression checks

- The rejection report contains exactly eight numbered required questions, states that sealed 2026 was not opened, and prohibits promotion (`run_study.py:319-337`).
- The rejection manifest records the exact reject decision, `sealed_2026_opened: false`, inventories result and root artifacts, excludes a stale prior manifest hash, and writes a single explicit self-reference last (`run_study.py:338-342`).
- The rejection selection seal contains `selection=None`, the exact terminal decision, a canonical result hash, 2021-2025 input identities, and the opaque expected 2026 dependency hash without opening that dependency (`run_study.py:376-380`).
- `evaluate_2026` accepts only `SELECTION_FROZEN` or `ENRICHED_RETRAIN_REJECT`, authenticates the seal result before branching, rejects an inconsistent non-null selection, and returns before rehashing even the development surfaces (`run_study.py:385-400`).
- The current `baseline_2025.json`, `sealed_2026.py`, and foundation-manifest SHA-256 values still match their pinned constants (`run_study.py:35-39`).
- No regression was found in the sixth-pass-clean temporal population, immutable cutoff, train-only preprocessing, exact attribution, economic-gate, diagnostics, output-schema, or manifest paths.

## Forced compliance matrix (seventh pass)

| Rules | Status | Basis |
|---|---|---|
| A1-A4 | N/A | This retrain consumes immutable NT-derived tabular surfaces and has no bar construction, strategy callback, cache lookup, or timer dispatch. |
| A5 | PASS | UTC nanosecond timestamps are converted explicitly to `America/Chicago` only for session/month reporting; no resampling occurs. |
| B1-B7 | PASS | No centered/negative-shift/backfill feature construction exists; feature values and provenance are accepted only from hash-gated causal surfaces, preprocessing fits on training years only, and frozen 2025 cutoffs are reused. |
| C1-C2 | PASS | Exhaustive labels map the NT-derived outcome attached to the same observation row; label columns are not admitted to the feature manifest. |
| C3-C4 | PASS | Training is 2021-2024, selection is 2025, and sealed evaluation is 2026; the frozen selection/cutoff is authenticated before the holdout can open. |
| D1 | PASS | Registered feature identity/order, provenance timestamps, F0 source identity, registry identity, and accepted-surface hashes are validated. |
| D2-D3 | N/A | No filter cascade or ONNX export exists in this scope. |
| D4 | PASS | Categorical vocabulary/order is fixed; imputation/scaling are deterministic pipelines fitted only on training data. |
| E1-E5 | N/A | This is not an NT execution/backtest strategy and submits no orders. |
| F1 | PASS | Short-RTH membership is validated from fill/entry time, not a mislabeled bar-open timestamp. |
| F2 | N/A | The retrain does not maintain cross-session rolling strategy state. |
| F3-F4 | PASS | UTC parsing and `America/Chicago` conversion are explicit and DST-aware. |
| G1-G4 | N/A | Raw contract construction, missing-bar treatment, resampling, and zero-volume filtering belong to the upstream hash-gated surface build, not this retrain. |
| H1-H4 | N/A | No offline bracket simulation or historical price-trigger loop exists in this scope. |

## Clean checks (seventh pass)

- No CRITICAL, WARNING, or NOTE findings remain in the audited pre-execution scope.
- The no-pass terminal path is complete without opening the sealed holdout.
- The selected path preserves the previously audited seal-before-open ordering.
- All prior sixth-pass clean checks remain clean under the focused regression scan.

---

*Seventh-pass audit complete. Findings reflect read-only static analysis. The study and tests were not executed. Only this audit report was modified.*

# Eighth-Pass Re-Audit

**Date:** 2026-07-19T17:26:48-05:00  
**Scope hash (SHA-256 of ordered path list):** `4d090f1448192692ffdc285501e00de593efae0037517013c405c205805a8282`  
**Mode:** read-only static launch-path regression audit with read-only SHA verification; neither study stage nor tests were executed

## Summary (eighth pass)

Critical: **0**

Warning: **0**

Note: **0**

Overall: PASS

The sole launch-path edit is causally neutral. `run_study.py` now imports `sys`, resolves `ROOT` from the script location, and inserts that absolute repository root into the process-local module search path only when absent (`run_study.py:13,28-30`). This makes the deferred canonical registry import at `run_study.py:126-140` available during standalone launch; it does not load a data surface, compute a feature, alter a timestamp, or expose the sealed holdout.

## Focused regression checks

- The new path mutation occurs after third-party imports and before any study function executes; it has no direct file read/write or timestamp behavior (`run_study.py:8-44`).
- The canonical `features.registry` import remains deferred until `registry_features()` is called, and the exact verified family counts, statuses, metadata, feature-set dimensions, and ordering remain fail-closed (`run_study.py:126-150`).
- Stage 1 still enumerates only 2021-2025 and retains the causal provenance, observation/entry ordering, fill-time RTH, immutable input-hash, and train/selection boundaries (`run_study.py:169-204,348-368`).
- The source edit cannot reuse a stale selection seal: stage 1 records `code_hash()` and stage 2 requires the current source hash before any holdout access (`run_study.py:380-394`).
- The no-pass branch still seals the exact `ENRICHED_RETRAIN_REJECT`, writes its eight-question report/manifest, and returns from `evaluate_2026` before resolving or importing `sealed_2026.py` or loading the 2026 surface (`run_study.py:319-345,368-397,406-419`).
- The current `baseline_2025.json`, `sealed_2026.py`, and foundation-manifest SHA-256 values still match their pinned constants (`run_study.py:38-42`).
- All seventh-pass A1-H4 compliance statuses remain unchanged; no causal, seal, train/serve, timestamp, session, data-integrity, or offline-fill regression was introduced.

## Clean checks (eighth pass)

- No CRITICAL, WARNING, or NOTE findings remain in the audited pre-execution scope.
- Standalone registry resolution now uses the canonical repository package rather than a study-local reimplementation.
- Both selected and rejected stage paths preserve their previously audited seal-before-holdout ordering.

---

*Eighth-pass audit complete. Findings reflect read-only static analysis. The study and tests were not executed. Only this audit report was modified.*

# Ninth-Pass Re-Audit

**Date:** 2026-07-19T17:34:23-05:00  
**Scope hash (SHA-256 of ordered path list):** `4d090f1448192692ffdc285501e00de593efae0037517013c405c205805a8282`  
**Mode:** read-only static runtime-schema regression audit with read-only SHA verification; neither study stage nor tests were executed

## Summary (ninth pass)

Critical: **0**

Warning: **0**

Note: **0**

Overall: PASS

The single field-name correction is valid and causally neutral. `economic()` emits `prestop_rate` for empty schedules and constructs the same key for populated schedules (`run_study.py:234-242`). `checks()` now consumes that actual candidate-metric key while retaining `base["prestop"]`, the deliberately frozen baseline schema (`run_study.py:76-82,254-256`). The comparison therefore remains the intended candidate pre-alignment-stop rate versus Baseline-A pre-stop rate; only the runtime `KeyError` is removed.

## Focused regression checks

- The corrected key is used only in the five-check 2025 economic gate; it does not alter features, labels, cutoffs, deduplication, timestamps, or the train/selection split (`run_study.py:245-256,348-368`).
- Candidate rows still persist the same `prestop_rate` field, and contribution analysis already compares `row["prestop_rate"]` against its F0 peer's `base["prestop_rate"]` (`run_study.py:362-364,492`).
- The frozen external baseline continues to require and expose `prestop`; no baseline schema or trusted value was changed (`run_study.py:76-82`).
- The source change is committed by `code_hash()` in the stage-1 seal and rejected by stage 2 if the code identity differs (`run_study.py:286,380-394`).
- Stage 1 still opens only 2021-2025; the rejected path still returns before any 2026 dependency, and the selected path still authenticates the seal and dependency before the first 2026 surface load (`run_study.py:348-353,388-419`).
- Causal provenance, fill-time RTH validation, UTC/Chicago conversion, immutable input hashes, train-only preprocessing, exact attribution, and all terminal-decision/report paths are unchanged.
- The current `baseline_2025.json`, `sealed_2026.py`, and foundation-manifest SHA-256 values still match their pinned constants.
- All eighth-pass A1-H4 compliance statuses remain unchanged; no causal, seal, timestamp, train/serve, session, data-integrity, or offline-fill regression was introduced.

## Clean checks (ninth pass)

- No CRITICAL, WARNING, or NOTE findings remain in the audited pre-execution scope.
- Candidate and peer economic schemas now agree at every internal `prestop_rate` comparison.
- Both selected and rejected stage paths preserve their previously audited seal-before-holdout ordering.

---

*Ninth-pass audit complete. Findings reflect read-only static analysis. The study and tests were not executed. Only this audit report was modified.*

# Tenth-Pass Re-Audit

**Date:** 2026-07-19T18:57:36-05:00  
**Scope hash (SHA-256 of ordered path list):** `4d090f1448192692ffdc285501e00de593efae0037517013c405c205805a8282`  
**Mode:** read-only static directory-initialization regression audit with read-only SHA verification; neither study stage nor tests were executed

## Summary (tenth pass)

Critical: **0**

Warning: **0**

Note: **0**

Overall: PASS

The runtime-only directory initialization is correctly ordered and causally neutral. Stage 1 now creates `_work/` and `results/` with `parents=True, exist_ok=True` after the mandatory audit, trusted 2025 baseline, and canonical feature-manifest gates complete, but before the first stage output write (`run_study.py:348-356`). The targets are fixed descendants of the study directory (`run_study.py:31-33`); no input, dependency, or holdout path is created or opened.

## Focused regression checks

- `WORK.mkdir(...)` and `RESULTS.mkdir(...)` are idempotent directory creation only; they do not delete, enumerate, overwrite, or transform prior artifacts (`run_study.py:350`).
- Initialization occurs before all direct stage-1 CSV/Parquet writes and before the selection seal write (`run_study.py:356-384`). `atomic_json()` independently retains its parent-directory guard and atomic replacement semantics (`run_study.py:64-69`).
- The directories are not created until `require_audits()`, the pinned 2025 baseline load, and canonical registry/F0 manifest construction succeed (`run_study.py:99-150,348-350`).
- Stage 1 still enumerates only 2021-2025, preserves causal provenance and train/selection boundaries, and cannot open the sealed 2026 dependency or surface (`run_study.py:169-204,351-369`).
- The source change is captured by `code_hash()` in the stage-1 seal and enforced by stage 2 before holdout access (`run_study.py:286,380-395`).
- The rejected path still returns before resolving/importing `sealed_2026.py`; the selected path still authenticates the dependency before the first 2026 surface load (`run_study.py:389-420`).
- The current `baseline_2025.json`, `sealed_2026.py`, and foundation-manifest SHA-256 values still match their pinned constants.
- All ninth-pass A1-H4 compliance statuses remain unchanged; no causal, seal, timestamp, train/serve, session, data-integrity, or offline-fill regression was introduced.

## Clean checks (tenth pass)

- No CRITICAL, WARNING, or NOTE findings remain in the audited pre-execution scope.
- Stage-1 output directories now exist before every non-self-creating output writer is reached.
- Both selected and rejected stage paths preserve their previously audited seal-before-holdout ordering.

---

*Tenth-pass audit complete. Findings reflect read-only static analysis. The study and tests were not executed. Only this audit report was modified.*

# Eleventh-Pass Pre-Execution Audit

**Date:** 2026-07-19T20:17:09-05:00  
**Scope hash (SHA-256 of ordered path list):** `4d090f1448192692ffdc285501e00de593efae0037517013c405c205805a8282`  
**Mode:** read-only static recovery-path audit with read-only artifact/SHA inspection; neither study stage nor tests were executed

## Summary (eleventh pass)

Critical: **1**

Warning: **2**

Note: **0**

Overall: FAIL

The new JSON representation is stage-1/stage-2 hash-compatible for genuine positive and negative infinity, and `finalize_2025` does not open 2026. However, the recovery path cannot yet establish that the cached candidate economics, cutoffs, or selected schedule were produced by the failed stage-1 fit. It can silently self-seal stale or modified cache values under the current source hash, so the requested zero/zero pre-execution gate is not met.

## Critical findings (eleventh pass)

### [C4/D1] `run_study.py:399-437` — unauthenticated recovery cache can silently determine and self-seal a different 2025 winner

`finalize_2025` verifies 48 expected schedule IDs and recomputes each stored `checks` count from the other values in the same CSV (`run_study.py:407-415`). That is an internal-consistency check, not provenance: a stale or edited row can change `cutoff`, `net`, `per_trade`, `pf`, `dd`, `prestop_rate`, or `oppflip_pnl`, update `checks` consistently, and then control the ranking at `run_study.py:415-417`.

The ID check also does not bind each ID to its row semantics: `schedule_id`, `feature_set`, `model`, and `band` are not cross-validated against one another. The selected Parquet gate checks only row count and summed net PnL (`run_study.py:418-421`). It does not recompute and compare the chosen schedule's PF, drawdown, pre-stop rate, opposing-flip PnL, regime IDs, observation ordering, cutoff membership, or exact row identity. Both the candidate CSV and selected Parquet therefore remain free inputs to the recovered selection.

Finally, the new seal records `code_hash()` for the recovery-capable source, not the source identity that produced the cache (`run_study.py:433-437`). No digest created before the original serialization failure authenticates either cache artifact. The current read-only hashes are `d2df489e335fe2b7c3da59af262a5156b3c5541a270e416b90fd5b3e8d88c02b` for `results/stage1_candidates.csv` and `cbc11bd2e15dd14cf35c24248a14b49dbe1f5ab5e3940cdd3c0f02776417ccc2` for `results/selected_model_trade_schedule.parquet`, but the executable does not pin or otherwise establish either identity.

Impact: a cache from a different fit/code version, or a partially edited/corrupted cache, can select a different schedule and be certified as a valid current-code 2025 selection. Stage 2 then trusts that selection before opening the sealed holdout. This silently invalidates the temporal selection boundary even though no 2026 file is opened during recovery.

**Recommended fix (do not apply):** require independently trusted expected SHA-256 identities for the exact observed candidate CSV and selected-schedule Parquet (and preferably the readiness/feature cache bundle), or fully recompute the 2025 candidate/schedule semantics from trusted inputs. Do not derive the trusted digests from the same mutable files inside `finalize_2025`. Also bind every schedule ID to its frozen feature-set/model/band tuple and verify all selected economic fields and exact row keys, not only count/net.

## Warnings (eleventh pass)

### [D4] `run_study.py:72-83` — `json_safe` converts NaN to the string `"-Infinity"`

The non-finite branch tests only whether the value is greater than zero (`run_study.py:75-76`). For NaN that comparison is false, so NaN is silently serialized and hashed as `"-Infinity"`. This defeats the prior `allow_nan=False` fail-closed behavior and creates a collision between missing/invalid numeric data and genuine negative infinity. Recovery CSV parsing can itself introduce NaN for blank or malformed cells, and `finalize_2025` has no blanket finiteness/schema validation.

**Recommended fix (do not apply):** handle only `np.isposinf` and `np.isneginf` as the two string sentinels and explicitly reject NaN before serialization/canonical hashing.

### [C4/D4] `run_study.py:407-432` and `tests/test_study.py:1-94` — readiness/cache schema checks are incomplete and the recovery contract has no focused tests

The readiness gate compares only the set of years, then takes `.iloc[0]` for each year (`run_study.py:424-431`). It does not require exactly five unique rows and does not validate the cached class distributions or missing-cell counts written by stage 1. Candidate columns/types, numeric finiteness, band membership, family/model membership, and immutable fields such as qualifying/tie counts are likewise not exhaustively validated. The existing focused test file contains no `json_safe`, infinity/NaN, `finalize_2025`, cache-tamper, stale-code, selected-schedule, or no-2026-access test.

Impact: malformed caches can be ambiguously accepted or fail after partial recovery work, and there is no executable regression proof for this newly introduced trust boundary.

**Recommended fix (do not apply):** require exact candidate/readiness schemas and types, finite values except the explicitly permitted PF infinity, exactly one readiness row per 2021-2025 year, and equality of all cached readiness fields to trusted expectations. Add synthetic fail-closed tests for each tamper case and a guarded test proving `finalize_2025` never resolves/imports/reads a 2026 dependency or surface.

## Clean checks (eleventh pass)

- `atomic_json()` and `canonical_hash()` apply the same `json_safe` transform, so genuine `+/-inf` values have stable serialized/sealed representations (`run_study.py:64-83`).
- `finalize_2025` performs no model fit or score inference.
- Recovery enumerates and hashes only the trusted 2021-2025 inputs (`run_study.py:427-432`); it does not resolve, hash, import, or read `sealed_2026.py` or `full_2026.parquet`.
- The canonical feature manifest and the pinned baseline/registry/F0 identities are revalidated.
- Stage 2 remains structurally compatible with the recovered result and revalidates the current code, baseline, registry/F0, development-input, feature-manifest, and sealed-module identities before the first 2026 surface load (`run_study.py:441-472`).
- The reject path still returns before any 2026 dependency or surface access (`run_study.py:448-450`).
- Existing causal provenance, timestamp, session, training split, attribution, and offline-fill findings remain unchanged; the blocker is the new recovery-cache trust boundary.

---

*Eleventh-pass audit complete. Findings reflect read-only static analysis. The study and tests were not executed. Only this audit report was modified.*

# Twelfth-Pass Pre-Execution Re-Audit

**Date:** 2026-07-19T20:21:00-05:00  
**Scope hash (SHA-256 of ordered path list):** `4d090f1448192692ffdc285501e00de593efae0037517013c405c205805a8282`  
**Mode:** read-only static hardened-recovery audit with read-only SHA verification; neither study stage nor tests were executed

## Summary (twelfth pass)

Critical: **0**

Warning: **0**

Note: **0**

Overall: PASS

All eleventh-pass findings are closed. The recovery path now authenticates the exact four-file observed cache bundle before parsing, validates the frozen 48-row schedule universe and row semantics, reconstructs the winner deterministically, verifies the selected schedule's unique regime population, cutoff membership, and complete economics, reauthenticates all 2021-2025 inputs and canonical dependencies, and records the cache identities in the seal. It performs no fitting and has no executable path to a 2026 dependency or surface.

## Eleventh-pass finding disposition

| Eleventh-pass finding | Twelfth-pass status | Evidence |
|---|---|---|
| Unauthenticated cache can determine/self-seal a different winner | CLOSED | Four independently supplied expected cache hashes are fixed in source and verified before parsing (`run_study.py:41-46,440-449`). Current files match every pin. |
| Candidate IDs not bound to row semantics / ranking inputs | CLOSED | Exact 48 IDs, uniqueness, feature-set/model/band-to-ID identity, allowed domains, numeric finiteness, cutoff contract, and recomputed economic checks are enforced before ranking (`run_study.py:406-425`). |
| Selected schedule checked only by count/net | CLOSED | Required schema, unique regime keys, score cutoff membership, and all 16 economic outputs used by the study are recomputed from the pinned Parquet and compared at zero relative tolerance (`run_study.py:428-434`). |
| NaN conflated with negative infinity | CLOSED | `json_safe` now emits distinct `NaN`, `Infinity`, and `-Infinity` representations; recovery candidate metrics reject every non-finite value (`run_study.py:78-90,417-420`). |
| Readiness/cache schema and test coverage incomplete | CLOSED | The pinned readiness and feature-manifest byte identities eliminate mutable-row ambiguity; years, trusted input hashes/counts, canonical manifest, and current dependencies are rechecked (`run_study.py:446-463`). The synthetic test covers all three non-finite representations plus the exact 48-candidate recovery contract (`tests/test_study.py:97-113`). |

## Cache and seal verification

- `results/stage1_candidates.csv` current SHA-256 is `d2df489e335fe2b7c3da59af262a5156b3c5541a270e416b90fd5b3e8d88c02b`, matching `RECOVERY_CACHE_SHA256["candidates"]`.
- `results/selected_model_trade_schedule.parquet` current SHA-256 is `cbc11bd2e15dd14cf35c24248a14b49dbe1f5ab5e3940cdd3c0f02776417ccc2`, matching `RECOVERY_CACHE_SHA256["selected_schedule"]`.
- `results/feature_manifest.json` current SHA-256 is `abf27c4651ae059a6e3edbeaaf71c04e1098a159ac3ac6076d6b636eb3265619`, matching `RECOVERY_CACHE_SHA256["feature_manifest"]`; its parsed canonical hash must also equal the current registry/F0-derived manifest (`run_study.py:453-454`).
- `_work/stage1_readiness.csv` current SHA-256 is `96a703f53e5057bc48522af6d1b9938512a6a6144c1e44609fa30210243df330`, matching `RECOVERY_CACHE_SHA256["readiness"]`.
- The recovered seal includes the complete `RECOVERY_CACHE_SHA256` map, current code identity, pinned baseline and opaque sealed-module identities, canonical feature manifest, registry/F0 hashes, trusted development inputs, and canonical recovered result (`run_study.py:464-468`).

## Causal and stage-2 compatibility checks

- `finalize_2025` calls only the audit/baseline/manifest gates, cache readers/validators, and SHA reads for `full_2021.parquet` through `full_2025.parquet`; it neither resolves/imports `sealed_2026.py` nor constructs/opens `full_2026.parquet` (`run_study.py:437-469`).
- No model object is constructed or fitted and no score is inferred during recovery. The recovered cutoff and selected population are fixed by the authenticated cache.
- Stage 2 accepts the same `select_2025` seal/result contract, verifies current code/baseline/registry/F0 and 2021-2025 inputs, validates the canonical result/manifest, then authenticates and imports the sealed module before the first 2026 surface load (`run_study.py:472-503`).
- Serialized negative-infinity cutoffs load as `"-Infinity"` and remain consumable through the existing `float(candidate["cutoff"])` conversion in stage 2; canonical hashing uses the identical `json_safe` representation on write and read (`run_study.py:70-90,478,528`).
- The reject path remains terminal before any 2026 dependency or surface access (`run_study.py:479-481`).
- All prior causal provenance, timestamp, RTH/session, temporal split, train-only preprocessing, attribution, output-schema, and H1-H4 statuses remain unchanged and clean/N/A as previously recorded.

## Clean checks (twelfth pass)

- No CRITICAL, WARNING, or NOTE findings remain in the audited pre-execution recovery scope.
- Recovery is restricted to the exact observed post-fit cache bundle and cannot silently accept a stale or modified artifact.
- The recovered selection has the same causal 2025-only boundary and stage-2 interface as the normal stage-1 result.

---

*Twelfth-pass audit complete. Findings reflect read-only static analysis. The study and tests were not executed. Only this audit report was modified.*

# Thirteenth-Pass Pre-Execution Re-Audit

**Date:** 2026-07-19T20:30:57-05:00  
**Scope hash (SHA-256 of ordered path list):** `4d090f1448192692ffdc285501e00de593efae0037517013c405c205805a8282`  
**Mode:** read-only static output-fix and reseal audit with read-only SHA verification; neither study stage nor tests were executed

## Summary (thirteenth pass)

Critical: **0**

Warning: **0**

Note: **0**

Overall: PASS

The populated monthly-breakdown fix is output-only and does not alter selection, economics, promotion gates, timestamps, or sealed-holdout isolation. Resealing with the already audited `finalize_2025` command after this source edit remains causally valid: the recovered 2025 result is mechanically restricted to the same independently hash-pinned cache bundle, while the new seal records and stage 2 enforces the current output-fixed source identity.

## Output-fix verification

- `schedule_breakdowns()` now assigns the derived Central-time month string to the stable public column `month_ct`, groups by that name, and reads `r.month_ct` from `itertuples()` (`run_study.py:314-321`). This removes pandas' leading-underscore tuple-field renaming failure without changing timestamps, group membership, aggregation, or values.
- The month source remains `exit_ts` parsed as UTC and converted with the DST-aware `America/Chicago` zone before conversion to a calendar month (`run_study.py:317`). Empty schedules retain the explicit `NO_TRADES` sentinel and unchanged exit-reason schema (`run_study.py:315-316`).
- The populated regression test exercises a real non-empty row, asserts the exact public `month_ct` record and PnL/trade values, and confirms exit aggregation remains available (`tests/test_study.py:86-92`).
- This function feeds only `monthly_rows` and `exit_rows` output tables inside the already frozen candidate loop (`run_study.py:525-532`). Candidate scores, frozen cutoffs, selected schedules, `economic()` results, attribution, and terminal decisions do not consume its returned records.
- Promotion-month gates use a separate `selected` monthly Series at `run_study.py:535-556`; that logic is unchanged by the column rename.

## Reseal and isolation verification

- The four observed recovery files still exactly match their executable pins: candidates `d2df489e335fe2b7c3da59af262a5156b3c5541a270e416b90fd5b3e8d88c02b`, selected schedule `cbc11bd2e15dd14cf35c24248a14b49dbe1f5ab5e3940cdd3c0f02776417ccc2`, feature manifest `abf27c4651ae059a6e3edbeaaf71c04e1098a159ac3ac6076d6b636eb3265619`, and readiness `96a703f53e5057bc48522af6d1b9938512a6a6144c1e44609fa30210243df330` (`run_study.py:41-46,440-447`).
- `finalize_2025` revalidates candidate identity/ranking semantics, selected unique regimes/cutoff/full economics, canonical feature manifest, and trusted 2021-2025 input hashes before resealing (`run_study.py:406-468`). It constructs no model, fits nothing, and cannot change the pinned selected population.
- The recovery call graph never resolves, hashes, imports, or reads `sealed_2026.py` and never constructs or opens `full_2026.parquet`. Its only year loops are `range(2021, 2026)` (`run_study.py:437-469`). Thus resealing after the prior stage-2 runtime failure cannot use the already-opened holdout to revise the 2025 winner.
- The new seal binds `code_hash()` for the output-fixed source plus the canonical recovered result and all recovery/dependency/input identities (`run_study.py:464-468`). An old seal cannot pass the current source-hash check (`run_study.py:472-478`).
- On retry, stage 2 authenticates the new seal, the 2021-2025 inputs, feature manifest, and sealed-module identity before its first 2026 surface load (`run_study.py:472-503`). The selection remains the pre-existing hash-pinned 2025 selection; only then is the holdout evaluation replayed.
- The prior stage-2 opening does not itself create a causal revision channel in this reseal path: the only source edit affects output record naming, and the executable-pinned recovery bundle prevents any schedule, cutoff, metric, or candidate change.

## Complete contract regression scan

- No negative shift, centered rolling window, backfill, resampling, or bar timestamp substitution was introduced.
- Causal provenance timestamps remain bounded by observation time; fill-time RTH and explicit UTC-to-Chicago handling are unchanged.
- Training remains 2021-2024, selection remains 2025, and evaluation remains sealed 2026. Preprocessing still fits on training data only.
- Registry/F0 identities, feature ordering, label mapping, cutoff/deduplication semantics, exact attribution, clipping/savings/month gates, terminal decisions, and manifests remain unchanged.
- No offline bracket simulation exists in this scope; H1-H4 remain N/A.

## Clean checks (thirteenth pass)

- No CRITICAL, WARNING, or NOTE findings remain.
- The output-only fix is safe to reseal through `finalize_2025` and then retry through `evaluate_2026` under the audited causal contract.
- The study and tests were not executed during this audit.

---

*Thirteenth-pass audit complete. Findings reflect read-only static analysis. Only this audit report was modified.*

# Fourteenth-Pass Pre-Execution Audit — Preserved Stage-2 Finalizer

**Date:** 2026-07-19T21:52:42-05:00  
**Scope hash (SHA-256 of ordered path list):** `5072c783cb9d33a64e0925040c18953f96c76f6ba45da6dcbab8745d664c39ba`  
**Mode:** read-only static report-recovery audit with read-only artifact/schema/SHA inspection; neither the finalizer, study stages, nor tests were executed

## Summary (fourteenth pass)

Critical: **1**

Warning: **2**

Note: **0**

Overall: FAIL

The finalizer is correctly limited to reading preserved outputs and writing only `STUDY_REPORT.md` and `results/manifest.json`; it does not fit, score, select, simulate, or load the raw 2026 surface. The latest internal schema, coverage, economic, and timestamp checks are useful. The pre-execution gate nevertheless fails because the preserved stage-2 artifact set is not independently authenticated, and the current script still references a nonexistent selection-seal key.

## Critical findings (fourteenth pass)

### [C4/D1] `finalize_preserved_stage2.py:35-93,134-138` — mutually consistent mutable stage-2 files can be accepted and self-manifested as preserved results

The script authenticates the unchanged runner against the selection seal (`finalize_preserved_stage2.py:42`) but has no independently trusted hash for `stage2_report.json`, `economic_results.csv`, `selected_model_oos_2026_trades.parquet`, or any other stage-2 machine output. Row counts, schema checks, duplicate checks, and cross-file metric comparisons establish internal consistency only. A stale, partially replaced, or coordinated edited report/CSV/Parquet set can preserve the expected counts and matching selection/metrics while changing the 2026 economics, survival flags, exact attribution, diagnostics, monthly tables, or selected trades.

The selected Parquet is checked for schema, unique regimes, entry-before-exit, 2026 Central-time entries, count, and summed PnL (`finalize_preserved_stage2.py:84-92`), but not independently bound to the completed stage-2 run. Its PF, drawdown, exit mix, and exact row identity are not reconciled to `stage2_report.json`; the report and economic CSV can be modified together. The other seven substantive tables beyond economics/retention/monthly/exit are accepted primarily by row count. The new manifest then hashes the already accepted files (`finalize_preserved_stage2.py:134-138`), which self-seals current contents rather than proving they are the preserved computation.

Impact: the recovery can silently publish a report and manifest for stage-2 results that were not produced by the sealed run, invalidating preserved 2026 result integrity and every downstream claim while leaving all implemented checks green.

Read-only hashes of the current key artifacts include:

- `stage2_report.json`: `9518ada7440d35aaefa0668a893b9192a130ec6e4e9e5c7c57fb81e502a2c891`
- `economic_results.csv`: `f8a5878bc0b16d1e9e590f8175970b1f0898bbc9b52c8e9bd0b4a7b4eb46a71f`
- `selected_model_oos_2026_trades.parquet`: `b18c2f33a371f74dabbb74b42294432aac6f517f0c0ab03225829ec407083c10`
- `monthly_results.csv`: `51478487e58f76b22711d029bc5017c625db6ed40cfcf142aacb74a894164d32`
- `exit_reason_attribution.csv`: `a4c9c285ea95e9e7c9e6c99a8ddc2758fd7304fd886dec56267de7e729400757`

**Recommended fix (do not apply):** pin an independently supplied expected SHA-256 map for every preserved stage-2 output that will be reported or inventoried, and verify the complete map before parsing any file or writing either output. Record that trusted map in the final manifest. Do not compute the expected values dynamically from the same mutable files inside the finalizer.

## Warnings (fourteenth pass)

### [C4] `finalize_preserved_stage2.py:37-43` — selection verification uses the wrong seal field and cannot complete

The audited selection-seal result schema contains `selection`, not `selected`. The current on-disk seal keys are `baseline`, `candidate_rows`, `candidates`, `decision`, `diagnostic_leader`, `overlay_2025`, `recovery`, and `selection`. Line 43 evaluates `seal["result"]["selected"]`, which raises `KeyError` before any table validation or output write.

This fails closed rather than corrupting results, but the report-only recovery cannot run as written.

**Recommended fix (do not apply):** compare `chosen` with `seal["result"]["selection"]`, and include `selection` in the explicit nested seal-schema check.

### [C4/D4] `finalize_preserved_stage2.py:93-130` — hard-coded report conclusions are not fully validated before publication

The finalizer requires the terminal decision string but does not fail unless the sealed choice is exactly F3/logistic/20% with five checks, even though those facts are hard-coded at lines 101 and 116. It serializes the preserved survival and attribution blocks but does not require the specific flags/relationships used by the prose: negative net, failed per-trade/PF/month gates, `winner_clipping_exact == false`, stop savings nonnegative, and clipped-winner dollars greater than stop savings. It also states the fixed-807 overlay is not applicable without requiring the preserved `overlay` field in the report schema or checking its status.

The current preserved files happen to support these statements, but the finalizer is intended to fail closed. A different or malformed yet same-decision report can produce internally contradictory Markdown.

**Recommended fix (do not apply):** assert the exact sealed schedule identity/feature set/model/band/check count; validate required survival and attribution schemas, values, and decision consistency; require `overlay.status == "NOT_APPLICABLE"`; and validate the pinned 2026 input identity before rendering the corresponding claims.

## Clean checks (fourteenth pass)

- The current runner SHA-256 equals the value stored in the selection seal (`c5334c8f2f5071762698b9b2db50809ad3be0cbef87b3b9a6fdd66974e592f44`).
- All nine expected table files currently exist and have the fixed row counts: 96 economics, 96 retention, 768 monthly, 384 exit attribution, 24 diagnostics, 1,200 calibration, 24 readiness, 72 feature contribution, and 204 top-feature rows.
- Strict selected-boolean parsing, economic schedule/split uniqueness and coverage, selected 2025/2026 metric cross-checks, retention/monthly/exit duplicate checks, and selected-trade schema/key/time checks are present (`finalize_preserved_stage2.py:59-92`).
- The selected-trade timestamp check is UTC-aware and uses `America/Chicago`; entry timestamps must not exceed exits and every selected entry must fall in Central-calendar year 2026 (`finalize_preserved_stage2.py:84-92`). No new timestamp relabeling or look-ahead computation occurs.
- The script imports no model/feature/strategy module, constructs no estimator, and has no call to `fit`, `score`, `load_year`, or the raw accepted surface. It reads only the preserved seal/results plus static report dependencies.
- The only intended writes are root `STUDY_REPORT.md` and `results/manifest.json` (`finalize_preserved_stage2.py:132-138`). Existing stage-1/stage-2 machine outputs are not modified.
- The manifest inventories all result files except its own prior version, plus the report, specification, reproduction guide, baseline file, sealed dependency, audit, and finalizer, and records the selection-seal and runner hashes.
- Existing 2025 selection isolation remains intact in the underlying audited seal. The blocker is proving that the mutable preserved 2026 outputs correspond exactly to the completed stage-2 computation.

---

*Fourteenth-pass audit complete. Findings reflect read-only static analysis. The finalizer, study, and tests were not executed. Only this audit report was modified.*

# Fifteenth-Pass Pre-Execution Re-Audit — Preserved Stage-2 Finalizer

**Date:** 2026-07-19T21:56:13-05:00  
**Scope hash (SHA-256 of ordered path list):** `5072c783cb9d33a64e0925040c18953f96c76f6ba45da6dcbab8745d664c39ba`  
**Mode:** read-only static hardened report-recovery audit with read-only SHA verification; neither the finalizer, study stages, nor tests were executed

## Summary (fifteenth pass)

Critical: **0**

Warning: **0**

Note: **0**

Overall: PASS

All fourteenth-pass findings are closed. Before parsing or writing anything, the finalizer now authenticates all eleven preserved stage-2 outputs plus the exact selection seal and runner against an independently witnessed SHA-256 map. It then verifies the corrected sealed selection, exact frozen outcome, trusted 2026 input identity, table coverage, selected economics and trades, survival/clipping decision semantics, and overlay limitation. The recovery remains report-only and does not reopen the raw 2026 surface.

## Fourteenth-pass finding disposition

| Fourteenth-pass finding | Fifteenth-pass status | Evidence |
|---|---|---|
| Mutable stage-2 outputs can be self-manifested | CLOSED | A fixed 13-entry trusted map covers the eleven result outputs, selection seal, and runner, and every hash is checked before the first JSON/CSV/Parquet parse (`finalize_preserved_stage2.py:19-33,49-56`). All current files match. |
| Wrong `result.selected` seal field | CLOSED | The finalizer requires and compares `seal["result"]["selection"]`, matching the audited seal schema (`finalize_preserved_stage2.py:57-63`). |
| Hard-coded selection/report conclusions not gated | CLOSED | Exact F3/logistic/0.2/five-check selection, trusted 2026 input hash/count, failed net/per-trade/PF/month/clipping gates, nonnegative savings with clipping greater than savings, and overlay `NOT_APPLICABLE` are explicit prerequisites (`finalize_preserved_stage2.py:63-64,114-122`). |

## Trusted preserved-set verification

The current files match every executable pin:

- `results/stage2_report.json`: `9518ada7440d35aaefa0668a893b9192a130ec6e4e9e5c7c57fb81e502a2c891`
- `results/economic_results.csv`: `f8a5878bc0b16d1e9e590f8175970b1f0898bbc9b52c8e9bd0b4a7b4eb46a71f`
- `results/retention_band_results.csv`: `424ef2e53999b175ad8d43a00dcac80ae77d1a434ebbb53b032c607f2efe43e7`
- `results/monthly_results.csv`: `51478487e58f76b22711d029bc5017c625db6ed40cfcf142aacb74a894164d32`
- `results/exit_reason_attribution.csv`: `a4c9c285ea95e9e7c9e6c99a8ddc2758fd7304fd886dec56267de7e729400757`
- `results/model_diagnostics.csv`: `2d78a44ba6e7edd70b491e848626095c02a9251b5b3875a915baa299c653c027`
- `results/calibration_deciles.csv`: `26a2fc5604e1eb70fd786e56eac1def1df164866d586e8bed4b4cebe12aae3d9`
- `results/data_readiness.csv`: `05b0f0292f78aa0633051b3b9c0546faa91be86da7cc049a75931087fa177543`
- `results/feature_family_contribution.csv`: `9c4ddd0d6729d9908275acb6f9fe0333796d9513d8ee3d7147be667f6795ebc7`
- `results/top_features.csv`: `a86d04b8fc7354038a4a0740b1ad483fa8f36260b31906982ced02945d1f1083`
- `results/selected_model_oos_2026_trades.parquet`: `b18c2f33a371f74dabbb74b42294432aac6f517f0c0ab03225829ec407083c10`
- `_work/selection_seal.json`: `cea88d078c04e8c8680b477d85624fb45a46050d1275fde3dc00883a06fd61d6`
- `run_study.py`: `c5334c8f2f5071762698b9b2db50809ad3be0cbef87b3b9a6fdd66974e592f44`

The manifest records the same complete `trusted_preserved_sha256` map, in addition to the selection-seal and runner hashes and the per-artifact inventory (`finalize_preserved_stage2.py:163-167`).

## Causal, timestamp, and claim verification

- Exact equality to the independently pinned 2025 selection seal prevents report recovery from reselecting or revising the frozen schedule (`finalize_preserved_stage2.py:57-63`).
- The pinned stage-2 report must identify the trusted accepted 2026 surface hash `877d907b29a4576993be43a47da16ff2dc5382bf91a80bbf9fa693de1001768a` and count 63,021 (`finalize_preserved_stage2.py:64`). The finalizer does not construct or open that raw path.
- Economic results require strict boolean encoding, 48 schedules across exactly 2025/2026 with unique schedule/split rows, exactly two selected rows for the sealed schedule, and metric parity to the seal/report (`finalize_preserved_stage2.py:80-96`).
- Retention, monthly, and exit attribution enforce their expected row counts and duplicate-key exclusions; every table is already byte-authenticated before those semantic checks (`finalize_preserved_stage2.py:66-103`).
- The selected trade artifact is byte-authenticated, requires the reporting schema and unique regimes, enforces `entry_ts <= exit_ts`, converts UTC nanoseconds explicitly to `America/Chicago`, restricts entries to Central-calendar 2026, and matches report count/net (`finalize_preserved_stage2.py:105-113`). No feature or decision is recomputed from future data.
- The terminal `ENRICHED_RETRAIN_CLIPS_WINNERS` claim is fail-closed against the exact decision, required failed gates, stop-savings pass, clipping/savings relationship, and fixed-807 N/A status (`finalize_preserved_stage2.py:114-122`).
- The script has no model/feature import, estimator construction, fit, score, selection, simulation, `load_year`, or raw-surface read. It reads only the authenticated preserved files and writes only `STUDY_REPORT.md` and `results/manifest.json` (`finalize_preserved_stage2.py:49-167`).
- Hashing `sealed_2026.py` for the final artifact inventory does not import it or open the raw 2026 input; the report accurately states that the 2026 input was not reopened.
- Existing A1-H4 causal/timestamp statuses remain unchanged: no bar construction, resampling, feature look-ahead, random split, execution simulation, or bracket replay occurs in this report-only script.

## Clean checks (fifteenth pass)

- No CRITICAL, WARNING, or NOTE findings remain in the report-only recovery scope.
- Preserved 2026 result integrity is anchored independently before parsing and then checked semantically.
- Frozen 2025 selection isolation and the final report/manifest claims are fail-closed.

---

*Fifteenth-pass audit complete. Findings reflect read-only static analysis. The finalizer, study, and tests were not executed. Only this audit report was modified.*

# Sixteenth-Pass Completion Audit

**Date:** 2026-07-19T21:59:42-05:00  
**Scope hash (SHA-256 of ordered path list):** `5072c783cb9d33a64e0925040c18953f96c76f6ba45da6dcbab8745d664c39ba`  
**Mode:** read-only completion audit of emitted report, manifest, seal, runner, finalizer, and preserved machine outputs; only this audit report was modified

## Summary (sixteenth pass)

Critical: **0**

Warning: **1**

Note: **0**

Overall: FAIL

The completed study result itself is causally clean and internally consistent. The frozen 2025 selection is isolated from 2026, all preserved stage-2 outputs match their independently witnessed pins, the report claims agree with those outputs, and `ENRICHED_RETRAIN_CLIPS_WINNERS` is the correct terminal decision. One completion-provenance warning remains: the final manifest hashes `audit/audit.md` as it existed before this mandatory completion audit, so the required audit append makes that manifest entry stale.

## Warnings (sixteenth pass)

### [D4/Reproducibility] `results/manifest.json:103-106` and `audit/audit.md` — mandatory completion audit invalidates the manifest's ordinary audit-file hash

Before this completion audit was appended, all 22 manifest artifact entries matched both byte count and SHA-256 on disk, including the recorded fifteenth-pass audit identity `13036ab4b9542f38891a14782171d8cacb2c7f4b070f95bb3ec544fc48237500` (`results/manifest.json:103-106`). The manifest also matched all 13 independently witnessed preserved-result/seal/runner pins.

This mandatory completion audit must update the same `audit/audit.md` path. Because the user expressly prohibited editing results beyond the audit report, `results/manifest.json` cannot be regenerated afterward. Its audit artifact entry is therefore stale immediately after this report is written, even though every economic, selection, code, seal, and preserved stage-2 artifact remains unchanged.

Impact: the manifest no longer passes a complete artifact-inventory verification. This does not alter the study decision or any machine result, but it prevents a zero-warning completion verdict for manifest integrity/provenance.

**Recommended fix (do not apply):** represent `audit/audit.md` as an explicit post-manifest/self-referential artifact without a fixed byte/hash claim, exclude it from the fixed manifest inventory while retaining the audit path and latest-summary contract, or use a separate immutable pre-completion-audit snapshot whose hash the manifest records. Regenerating the manifest after each audit update without such a convention only recreates the cycle.

## Decision and claim verification

- The selection seal is `select_2025`, contains only input years 2021-2025, and freezes `F3__logistic__rband0.2` with five 2025 checks. It contains no 2026 input identity or selected outcome value.
- The preserved stage-2 report identifies the same exact selection and records matching F0 checks of one. Therefore the enriched F3 candidate clears the peer/baseline branch of `final_decision()` (`run_study.py:276-283`).
- `winner_clipping_exact` is false, so the ordered decision function returns `ENRICHED_RETRAIN_CLIPS_WINNERS` before the general overfit branch (`run_study.py:280-281`). This exactly matches `stage2_report.json`, `STUDY_REPORT.md:5,28`, and `results/manifest.json:114`.
- Selected 2025 economics are 1,247 trades, $46,706.93 net, $37.4554/trade, PF 1.253997, and $7,953.42 drawdown. Selected sealed-2026 economics are 380 trades, -$3,242.93 net, -$8.5340/trade, PF 0.953892, and $16,154.95 drawdown. The report's rounded table matches the exact selected rows (`STUDY_REPORT.md:13-14`).
- Exact attribution records $13,247.14 stop savings and $29,662.68 clipped winners. Net, per-trade, PF, worst-month, positive-month concentration, and winner-clipping gates fail; stop savings, monthly positive share, and monthly absolute-share gates pass. The report states these outcomes without promotion (`STUDY_REPORT.md:20-29`).
- The fixed-807 overlay is explicitly `NOT_APPLICABLE` with favorable claims prohibited. The final report correctly retains W4 Policy A and does not claim NT validation.

## Selection isolation and timestamp verification

- The selected 2025 schedule was recovered solely from the four independently pinned stage-1 cache artifacts and resealed under the unchanged runner. No recovery path fit, rescored, reselected, imported `sealed_2026.py`, or opened `full_2026.parquet`.
- Stage 2 verified the sealed selection, code/dependency identities, canonical manifest, and 2021-2025 inputs before opening the hash-gated 2026 surface (`run_study.py:472-503`). The preserved output selection equals the sealed 2025 selection exactly; no 2026-driven selection channel exists.
- All eleven preserved stage-2 outputs, the selection seal, and runner still match the independently witnessed SHA-256 map recorded in the finalizer and final manifest. The 2026 accepted surface identity remains `877d907b29a4576993be43a47da16ff2dc5382bf91a80bbf9fa693de1001768a` with 63,021 rows.
- The selected trade artifact is the pinned file audited before execution: unique regime keys, `entry_ts <= exit_ts`, UTC nanosecond parsing, explicit `America/Chicago` conversion, and exclusively Central-calendar 2026 entries were required before report generation.
- Upstream causal provenance remains enforced by `latest_source_ts_used`, latest 1-second close, and latest 1-minute close not exceeding observation time; observation precedes entry and entry precedes exit. No negative shift, centered rolling, backfill, resampling, or timestamp relabeling occurs in the finalizer.
- No offline bracket replay or alternate fill simulation exists in this scope; H1-H4 remain N/A.

## Manifest and deliverable verification

- Prior to the required completion-audit append, every one of the 22 manifest artifact byte/hash entries matched disk and all 13 trusted-preserved identities matched the manifest's `trusted_preserved_sha256` map.
- Every result-directory file other than `manifest.json` was listed; no unlisted machine output was found.
- Required deliverables exist and are non-empty: `STUDY_REPORT.md`, `SPEC.md`, `REPRODUCE.md`, `baseline_2025.json`, `sealed_2026.py`, runner, finalizer, selection seal, audit, manifest, stage-1 selection outputs, and all eleven preserved stage-2 outputs.
- The manifest records the correct decision, exact selected candidate, trusted 2026 input identity/schema/count, runner hash, selection-seal hash, complete trusted preserved map, recovery provenance, and per-artifact inventory.
- `STUDY_REPORT.md` accurately discloses the report-only recovery, the prior NumPy-boolean rendering failure, the non-NT-native status, and that the finalizer did not refit, rescore, reselect, or reopen the raw 2026 input (`STUDY_REPORT.md:32-34`).

## Clean checks (sixteenth pass)

- Critical causal/look-ahead/timestamp findings: none.
- The economic result and terminal decision are trustworthy and unchanged by the report-only recovery.
- The only open issue is the audit-file hash cycle in the otherwise complete manifest.

---

*Sixteenth-pass completion audit complete. Findings reflect read-only artifact and static-code analysis. The study, finalizer, and tests were not executed during this audit. Only this audit report was modified.*

# Seventeenth-Pass Pre-Execution Re-Audit — Completion-Audit Packaging

**Date:** 2026-07-19T22:02:21-05:00  
**Scope hash (SHA-256 of ordered path list):** `5072c783cb9d33a64e0925040c18953f96c76f6ba45da6dcbab8745d664c39ba`  
**Mode:** read-only static packaging-cycle audit with read-only SHA verification; neither finalizer nor study code was executed

## Summary (seventeenth pass)

Critical: **0**

Warning: **0**

Note: **0**

Overall: PASS

The sole sixteenth-pass warning is closed. The finalizer no longer makes a fixed byte/hash claim for the necessarily self-updating completion audit. It retains the audit path as an explicit provenance entry with `self_updating_completion_audit: true` and `sha256: null`, while all substantive results and immutable report dependencies remain independently authenticated and/or fixed-hashed.

## Sixteenth-pass finding disposition

| Sixteenth-pass finding | Seventeenth-pass status | Evidence |
|---|---|---|
| Completion audit invalidates manifest audit hash | CLOSED | `audit/audit.md` is excluded from fixed artifact hashing and appended once as an explicit self-updating, null-hash entry (`finalize_preserved_stage2.py:163-167`). Future completion-audit appends no longer contradict any recorded byte count or digest. |

## Packaging and authentication verification

- The fixed artifact list still includes every result file other than `manifest.json`, the generated `STUDY_REPORT.md`, `SPEC.md`, `REPRODUCE.md`, `baseline_2025.json`, `sealed_2026.py`, and the finalizer itself (`finalize_preserved_stage2.py:161-165`). Each receives an exact byte count and SHA-256.
- The runner and selection seal remain outside the ordinary artifact list only because they have dedicated top-level hashes and are also included in the independently witnessed trusted map (`finalize_preserved_stage2.py:19-33,167`).
- All eleven preserved stage-2 outputs, the selection seal, and runner still match all 13 witnessed pins before this re-audit. Their verification remains the first action in `main()`, before any JSON/CSV/Parquet parse or output write (`finalize_preserved_stage2.py:49-56`).
- The audit file currently exists. Its null-hash entry is a deliberate lifecycle declaration, not an omitted deliverable or assertion that the audit is immutable.
- `manifest.json` remains excluded from hashing itself, avoiding a separate self-reference cycle.
- The manifest will record the complete `trusted_preserved_sha256` map, exact selection-seal and runner hashes, selected candidate, trusted 2026 input identity, terminal decision, fixed artifact inventory, and the explicit self-updating audit entry (`finalize_preserved_stage2.py:165-168`).

## Substantive-contract regression scan

- No substantive authentication gate was removed or weakened. The trusted preserved map, exact `result.selection` equality, F3/logistic/0.2/five-check identity, 2026 input hash/count, table coverage, selected economics/trade checks, required failed survival gates, clipping-greater-than-savings relation, and fixed-807 N/A gate are unchanged (`finalize_preserved_stage2.py:19-122`).
- Frozen 2025 selection isolation is unchanged; no fit, score, reselection, simulation, raw-2026 read, or model/feature import exists.
- UTC nanosecond parsing, explicit `America/Chicago` conversion, unique selected regimes, entry-before-exit, and Central-calendar 2026 restrictions remain unchanged.
- The report and decision remain fixed to the independently authenticated preserved outputs and `ENRICHED_RETRAIN_CLIPS_WINNERS`.
- Existing A1-H4 statuses remain clean/N/A; this change affects only manifest treatment of a post-generation audit file.

## Clean checks (seventeenth pass)

- No CRITICAL, WARNING, or NOTE findings remain.
- The packaging cycle is resolved without weakening economic, causal, selection, timestamp, seal, runner, or preserved-result authentication.
- A subsequent mandatory completion-audit append can coexist with a valid manifest under the declared self-updating-audit convention.

---

*Seventeenth-pass pre-execution audit complete. Findings reflect read-only static analysis. The finalizer and study were not executed. Only this audit report was modified.*

# Eighteenth-Pass Final Completion Audit

**Date:** 2026-07-19T22:03:34-05:00  
**Scope hash (SHA-256 of ordered path list):** `5072c783cb9d33a64e0925040c18953f96c76f6ba45da6dcbab8745d664c39ba`  
**Mode:** read-only final artifact, provenance, causal, timestamp, and decision audit; only this self-updating audit report was modified

## Summary (eighteenth pass)

Critical: **0**

Warning: **0**

Note: **0**

Overall: PASS

The study is complete under the audited contract. Every fixed manifest artifact matches its recorded byte count and SHA-256; all 13 independently witnessed stage-2/seal/runner pins match; the self-updating completion-audit declaration is present and cycle-safe; all required deliverables exist; report claims agree with the preserved outputs; the frozen selection is isolated to 2021-2025; and `ENRICHED_RETRAIN_CLIPS_WINNERS` is the correct terminal decision.

## Final manifest integrity

- The regenerated manifest contains 22 artifact entries: 21 fixed byte/hash entries plus one explicit self-updating completion-audit entry. Every fixed entry currently matches disk.
- `audit/audit.md` is declared exactly once with `self_updating_completion_audit: true` and `sha256: null` (`results/manifest.json:109-110`). This completion append changes no fixed manifest claim, so the audit/manifest cycle is resolved.
- All 13 entries in `trusted_preserved_sha256` match disk: the eleven preserved stage-2 outputs, `_work/selection_seal.json`, and `run_study.py`.
- The manifest's dedicated selection-seal hash `cea88d078c04e8c8680b477d85624fb45a46050d1275fde3dc00883a06fd61d6` and runner hash `c5334c8f2f5071762698b9b2db50809ad3be0cbef87b3b9a6fdd66974e592f44` match their files (`results/manifest.json:775,805`).
- Every file in `results/` other than `manifest.json` appears in the artifact inventory; no unlisted machine output or missing listed output was found.
- Fixed root artifacts—`STUDY_REPORT.md`, `SPEC.md`, `REPRODUCE.md`, `baseline_2025.json`, `sealed_2026.py`, and `finalize_preserved_stage2.py`—match the manifest. Runner and seal identities are covered by their dedicated trusted fields.
- The manifest records the exact selected candidate, decision, trusted 2026 input hash/count/schema, report-only recovery status, trusted preserved map, and complete artifact inventory.

## Final report and result agreement

- `STUDY_REPORT.md` and the manifest both state `ENRICHED_RETRAIN_CLIPS_WINNERS` (`STUDY_REPORT.md:5`; `results/manifest.json:114`). The stage-2 report records the same decision.
- The frozen choice is exactly `F3__logistic__rband0.2`, with F3 combined features, logistic regression, 20% retention, and five 2025 checks. The matching F0 peer has one check.
- Selected 2025 results are 1,247 trades, $46,706.930607 net, $37.455438/trade, PF 1.253997, and $7,953.417340 drawdown. The report's rounded row agrees (`STUDY_REPORT.md:13`).
- Selected sealed-2026 results are 380 trades, -$3,242.926779 net, -$8.534018/trade, PF 0.953892, and $16,154.948413 drawdown. The report's rounded row agrees (`STUDY_REPORT.md:14`).
- Exact matched attribution is $13,247.143705 of stop savings versus $29,662.682244 of clipped winners. The report agrees (`STUDY_REPORT.md:22`).
- Net-positive, 90%-per-trade, 90%-PF, worst-month, positive-month-concentration, and exact winner-clipping gates fail. Stop savings, monthly positive share, and monthly absolute-share gates pass. The report reproduces the exact survival map (`STUDY_REPORT.md:23`).
- The fixed-807 overlay remains `NOT_APPLICABLE` with favorable claims prohibited. The report correctly keeps W4 Policy A, rejects promotion, and states that this is research evidence rather than NT-native executable validation.

## Final causal, selection, and timestamp verification

- The selection seal is stage `select_2025`, freezes the same F3 schedule with five checks, and contains input identities only for 2021, 2022, 2023, 2024, and 2025. No 2026 outcome or surface identity participates in selection.
- Stage-1 recovery was restricted to four independently pinned cache artifacts, validated the full 48-candidate universe and selected schedule economics, and performed no fit, score, or holdout read.
- Stage 2 authenticated code, selection seal, baseline, registry/F0, 2021-2025 inputs, feature manifest, and sealed dependency before the first 2026 surface load. The stage-2 selection equals the sealed 2025 selection exactly.
- The accepted 2026 input identity is `877d907b29a4576993be43a47da16ff2dc5382bf91a80bbf9fa693de1001768a` with 63,021 rows. It is evaluation-only.
- The pinned selected-trade artifact passed unique-regime, entry-before-exit, UTC nanosecond, explicit `America/Chicago`, and Central-calendar-2026 checks before report generation.
- Upstream accepted surfaces enforce observation/entry/exit ordering and source, latest 1-second close, and latest 1-minute close timestamps not later than observation. No negative feature shift, centered rolling, backfill, random split, resampling, or bar-open/close substitution was introduced.
- Training is 2021-2024, selection is 2025, and the sealed holdout is 2026. Preprocessing remains train-only and categorical/feature order remains deterministic.
- No offline bracket simulation or alternate execution replay exists here; H1-H4 remain N/A.

## Terminal decision verification

- The chosen enriched model has five checks versus the matching F0 peer's one, so it clears the baseline/peer branch.
- `winner_clipping_exact` is false because clipped winners exceed exact stop savings. In the frozen ordered decision function, that returns `ENRICHED_RETRAIN_CLIPS_WINNERS` before the general overfit branch (`run_study.py:276-283`).
- The terminal instruction is therefore correct: do not promote to NT schedule validation and keep the current W4 Policy A.

## Required deliverables

- Present and non-empty: report, specification, reproduction guide, baseline, sealed dependency, runner, finalizer, selection seal, cycle-safe manifest, audit, stage-1 selection artifacts, and all eleven preserved stage-2 outputs.
- Recovery provenance is disclosed in `STUDY_REPORT.md:32-34`; no machine output was modified by the report-only finalizer.

## Clean checks (eighteenth pass)

- No CRITICAL, WARNING, or NOTE findings remain.
- No look-ahead, timestamp, train/serve, selection-isolation, preserved-result, decision, report, deliverable, or manifest-integrity issue remains.
- Final decision: `ENRICHED_RETRAIN_CLIPS_WINNERS`.

---

*Eighteenth-pass final completion audit complete. Findings reflect read-only artifact and static-code analysis. No implementation or result file was modified; only the declared self-updating audit report was appended.*

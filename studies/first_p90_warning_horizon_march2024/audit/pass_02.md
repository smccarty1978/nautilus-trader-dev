# Look-Ahead & Timestamp Audit — Pass 02 (DELTA)

**Date** 2026-09-04 · **Scope** `research/schemas/study_spec.py` (`DerivedCausalInputSpec` +3
optional fields, binding-XOR), `research_workflow/external_model_scoring.py`
(`_resolve_train_provenance`), `studies/clean_maturity_flip_model_180s_horizon/artifacts/
train_provenance_attestation.json` (new additive artifact, not in closure), `.gitattributes`
(not in closure), `studies/first_p90_warning_horizon_march2024/study.yaml` (derived_inputs:
`model_id` → legacy artifact binding + attestation trio) · **Scope hash (audited composite)**
`89f940ddf8089c88946580006bd6352826f3342f0ec51f1f5d0efe66a043ea70` (confirmed against
`audit/frozen_execution_manifest.json:frozen_execution_composite_sha256`; readiness `R9_closure_current`
current=frozen match) · **Lint** 0 critical / 0 warning (preflight CLEAR, all 8 required checks
PASSED, `FORWARD_OUTCOME_GUARD` PASSED, `leaked_outcome_columns: []`) · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 1 (carried, unchanged) · Note: 1

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | `[B2] features/trackers/host_bindings.py:698-705` — `FrozenExternalScoreBinding.derive()` passes a blanket `availability_ts={n: ts for n in surf}` / `score_evaluation_ts=ts`, making the fail-closed refusal in `FrozenExternalModelScorer.score()` structurally inert | **UNCHANGED — still holds** | `host_bindings.py` is not in this delta's changed-file set (not `study_spec.py`, not `external_model_scoring.py`) and lines 682-706 read byte-identical to pass 01's citation. `derive()` never inspects `spec.model_id` vs. legacy fields — it calls `self._scorer.score(...)` uniformly through the abstraction regardless of which binding path constructed `self._scorer`. This delta changes *how the freeze's TRAIN-only status is proven*, not the scoring/availability call site. No causal effect either way. |
| 2 | Note: flip kernel has no `max_gap_ns` censoring path (`host/outcomes.py`) | **N/A — file unchanged** | `research_workflow/host/outcomes.py` not touched by this delta. |
| 3 | Referred to contract-checker: population is a superset of parent training population (D2) | **N/A — unchanged**, `study.yaml`'s `population.qualify` / `analysis.eligible_when` blocks are byte-identical to what pass 01 audited | See below, re-verified for completeness only |

## Critical findings
None.

## Delta-specific verification (the questions posed)

**Does the delta change what a candidate can see at T?** No. Traced end-to-end:

1. **Same model bytes.** `study.yaml` legacy binding now declares `model_artifact_path`/`_sha256`
   for `ccd587dfed77d1c87029bcd779abb1f6b70fa63beab5c99f5439653746963b0c.joblib` (LONG) and
   `209da0ff0c922e02ab02f78408d0591bd0b2e762a71ecd3ed010856ca45051e6.joblib` (SHORT) — the exact
   two artifacts pass 01 already named as the bound arms under the (now-abandoned) `model_id`
   path. `FIRST_P90_BLOCKER.md` records `max_abs_delta = 0.0` between the LightGBM native booster
   and the `.joblib` estimator's predictions — the models are byte/numerically identical to what
   was already frozen; only the *binding path used to authenticate them* changed.
2. **Same feature surface, same order.** `study.yaml:ordered_feature_surfaces.C` (13 columns,
   `arrival_velocity` … `rolling_300s_giveback_atr`) is identical to
   `train_experiment_freeze_long.json:feature_sets.C` (verified byte-for-byte, `Read` at
   `studies/clean_maturity_flip_model_180s_horizon/artifacts/train_experiment_freeze_long.json:4-18`)
   and to the attestation cell's `ordered_feature_surface`. `FrozenExternalModelScorer.bind()`
   (`external_model_scoring.py:226-235`) additionally cross-checks this order against the freeze
   on every bind, independent of the attestation.
3. **Same arm routing.** `_arm_for()` (`external_model_scoring.py:240-246`) reads
   `spec.direction_arm_mapping` (`LONG: C, SHORT: C`) identically regardless of binding path;
   `derive()` in `host_bindings.py` never branches on binding kind.
4. **Same `score()` call.** `external_model_scoring.py:257-312` (the scoring + availability
   arithmetic) is untouched by this delta — confirmed not in the collection-stage file diff set
   beyond `_resolve_train_provenance`, which is called only inside `bind()`, before any scoring.
5. **Conclusion:** the number produced at a given epoch is the same number the (blocked) `model_id`
   path would have produced. The delta is authentication-of-identity, not a change to inputs,
   features, population, outcome or timing.

**Attestation cannot widen scope.** `DerivedCausalInputSpec.validate_model_binding_xor`
(`study_spec.py:571-592`) refuses attestation fields together with `model_id` and refuses a
partial trio. `_resolve_train_provenance` (`external_model_scoring.py:50-133`) requires, in
order: attestation file lives inside the parent study dir (`72-73`), sha256 match (`76-79`),
`kind`/`assertion` markers (`84-85`), `parent_study_id` match (`86-88`), `execution_composite_sha256`
match to the spec's own declared `parent_frozen_execution_composite_sha256` (`91-95`), both
`causal` and `contract` audits `CLEAR` at that same composite (`96-100`), exact cell match on
`cell_id` (`102-104`), `original_freeze_path` match (`106-109`), **canonical-content** freeze
identity match via `canonical_sha256` — sorted-keys/no-whitespace JSON hash, confirmed
checkout-independent at `research/analysis/identity.py:45-49` (`115-119`), model artifact sha256
match (`120-121`), per-arm `fit_identity_sha256` match against `spec.model_hashes` (`122-124`),
and preprocessing hash match (`125-126`). Every one of these was independently verified against
the actual `train_provenance_attestation.json` bytes and matches exactly — no slack observed.

**No "missing provenance means TRAIN" fallback.** `_resolve_train_provenance` line 63 checks the
self-declared marker; failing that, lines 66-69 raise `ExternalModelScoringError("parent TRAIN
freeze is not TRAIN_ONLY")` unless the full attestation trio is present — confirmed the freeze
files (`train_experiment_freeze_long.json`) carry no `provenance` key, so path B is mandatory here,
exercised, and fully hash-gated. There is no code path that treats an absent/incomplete attestation
as authorization.

## Warnings
Carried unchanged — see adjudication table row 1.

## Notes
- **`.gitattributes` (`*.booster.txt -text`) is infrastructure, not a causal change.** It is not
  in the execution closure and this study's binding path never reads a native booster
  (`study.yaml:69`, "No native booster is read"). Fixes real CRLF corruption for a path this study
  does not use.

## Referred to contract-checker
- (Unchanged from pass 01) Population is a declared strict superset of the frozen parent's
  training population; `parent_long_score`/`parent_short_score` are evaluated outside the domain
  the frozen estimators were fit on. D2 concern, re-verified structurally identical this pass, not
  re-itemized.
- New this pass: whether the attestation's un-checked descriptive fields (`freeze_authorization_sha256`,
  `freeze_declared_freeze_sha256`) create any false impression of additional verification beyond
  what `_resolve_train_provenance` actually checks is a model-integrity-declaration wording
  question, not a causal one.

## Clean checks
B2, B9, C1-C3 clean for the delta (scoring/availability arithmetic untouched; label/outcome files
untouched). F, G, H not implicated — no session, dataset or bracket-price code in the diff.
A1-A5, B1, B3-B7, B10 not applicable to this delta (no timestamp-indexing or rolling-computation
code changed).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor-claude", "critical": 0, "warning": 1, "note": 1, "study": "first_p90_warning_horizon_march2024", "audited_execution_composite_sha256": "89f940ddf8089c88946580006bd6352826f3342f0ec51f1f5d0efe66a043ea70"}
<!-- AUDIT_SUMMARY_V2_END -->

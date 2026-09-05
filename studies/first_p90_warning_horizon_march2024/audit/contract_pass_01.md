# Contract audit — studies/first_p90_warning_horizon_march2024 — pass 01

Reviewer identity: `contract-checker-pass01-2026-09-04` (distinct from
`lookahead-auditor-claude`, the causal identity on this target).
Scope: C4, D, E per `docs/CAUSAL_CHECKLIST.md`; deliverables completeness against the
packet's `deliverables_by_stage`; lifecycle state per `AGENTS.md`. No causal theories
raised here beyond what is already named by the causal auditor.

This study has not executed past `contract_audit` — no `collection`, `analyze`, `freeze`,
`merge` or `close` artifacts exist yet. This is a pre-execution (preexec) governance audit
of the plan, not a post-hoc verification of produced deliverables, because none have been
produced. Findings below are scoped accordingly and say so where relevant.

## Deliverables contract

No `studies/first_p90_warning_horizon_march2024/config/deliverables_contract.json` exists.
This is **not** a missing-contract finding: this study compiles through the newer
packet-v2 pipeline (`compiled_plan.json` + `_work/controller/audit_packet_contract.json`,
`packet_version: 2`), which does not produce a `config/deliverables_contract.json` at all
(`research_workflow/contract_audit.py`'s `deliverables_contract` check is written against
the legacy `compiled_study.json` pipeline other studies in this repo still use — grep
confirms `first_p90_warning_horizon_march2024` is the only study on `compiled_plan.json`).
For packet-v2, the platform-authored, study-independent `DELIVERABLES_BY_STAGE` constant
(`research_workflow/audit_packets_v2.py:37-44`) is echoed into the packet's
`deliverables_by_stage` — that is the literal contract for lifecycle-stage artifacts, and I
used it as such rather than assembling my own list.

The study's *named* deliverables (the 9 `first_p90_*` artifacts + 1 report) are not covered
by `deliverables_by_stage` (which only names the generic `artifacts/experiment_analysis_v2.json`
for the `analyze` stage) — they are declared instead in `research_decision.yaml:188-198` and
mapped 1:1 to `study.yaml`'s declarative `analysis.artifacts:` block (`study.yaml:293-302`).

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| 9 of 10 declared deliverables each map to exactly one declared `analysis` step | PASS | `study.yaml:293-302` — every artifact name in `research_decision.yaml:189-197` has a `source:` pointing to a declared step id (`first_p90`, `cumulative_incidence`, `negative_decomposition`, `control_selection`, `control_incidence`, `score_path` ×2, `warning_subtypes`), and every step id used by an artifact is declared in `analysis.steps` | n/a — no execution has run yet, so no artifact bytes exist to check against these declarations | — |
| 10th deliverable, `FIRST_P90_WARNING_HORIZON_REPORT.md`, hand-authored | PASS, with note | Explicitly disclosed in the module docstring and prompt framing, not silently added; sourced only from the 9 governed artifacts, no bespoke computation | n/a | Recommend the eventual report cite the exact artifact + row/field it draws each number from, since nothing downstream re-audits its prose against the governed JSON/parquet automatically |
| `deliverables_by_stage` lifecycle artifacts (prepare/readiness/preflight/causal_audit/contract_audit reached; collection/analyze/freeze/merge/close not yet) | PASS (as expected for this stage) | `_work/controller/status.json` (`stage: contract_audit`, `last_successful_stage: causal_audit`); no `_work/controller/partitions/`, no `artifacts/experiment_analysis_v2.json` exist yet — consistent with pre-execution state, not a gap | n/a | — |

## C4 / D — model integrity and provenance

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Provenance attestation is additive, does not modify closed-parent artifacts | PASS | `studies/clean_maturity_flip_model_180s_horizon/artifacts/train_provenance_attestation.json` is a new file (`kind: train_provenance_attestation`); `train_experiment_freeze_long.json`/`_short.json` are read-only inputs, matched by **canonical content hash** (`external_model_scoring.py:110-119`, `canonical_sha256`), not file-byte hash — explicitly checkout-independent, closing the EOL-corruption failure mode named in the git history (commit `5bdb7f33`) | n/a (no run yet) | — |
| Binder (`_resolve_train_provenance`) actually checks every field the attestation claims to bind | PASS | `external_model_scoring.py:66-133` checks, in order: attestation lives inside parent dir, file sha256, `kind`/`assertion` markers, `parent_study_id`, `execution_composite_sha256` match to spec's declared parent composite, **both** causal and contract audits `CLEAR` at that composite, exact `cell_id` match, `original_freeze_path` match, canonical freeze-content hash, model-artifact sha256, per-arm `fit_identity_sha256`, preprocessing hash. All independently re-verified against the actual attestation bytes above and match exactly. | n/a | — |
| `descriptive_only` block honestly labelled as unverified | PASS | `train_provenance_attestation.json:8-9`: `"_note": "context for readers; NOT verified by the binder. Only top-level fields bind."` — this directly answers the causal auditor's pass-02 referral ("whether the attestation's un-checked descriptive fields create any false impression of additional verification"). The labelling is unambiguous and sits inline with the fields it disclaims, not in a separate document a reader could miss. | n/a | — |
| Declared P90/P95/P97.5 thresholds match the parent's frozen freezes exactly | PASS (manual cross-check; not machine-gated) | `research_decision.yaml:56-63` LONG `{0.2852887899663343, 0.32770330252959395, 0.3639796684339806}` / SHORT `{0.28485631865861344, 0.33222113070660036, 0.37673375655439945}` are byte-identical to `study.yaml:186,191` (`*frozen_thresholds`) and to `train_provenance_attestation.json`'s `descriptive_only.thresholds` for both cells. These are the literal values the compiled analysis will classify against (`study.yaml:179-199`), so a transcription error here would be a real scoring defect, not cosmetic. The match is exact but only cross-checked by this audit, not asserted by any runtime invariant — the binder does not verify thresholds (see `descriptive_only` note above). | n/a | Low-cost hardening: have `_resolve_train_provenance` additionally assert `spec`-declared thresholds equal the attestation's descriptive thresholds, closing the one gap between "documented" and "gated" |
| Ordered 13-feature surface matches parent's `feature_sets.C` exactly | PASS | `study.yaml:84-98,120-134` (`ordered_feature_surfaces.C`) identical, in order, to `research_decision.yaml:66-79` and to the attestation cells' `ordered_feature_surface`; `FrozenExternalModelScorer.bind()` additionally cross-checks this order against the freeze on every bind per the causal auditor's pass-02 note (`external_model_scoring.py:226-235`), independent of the attestation — this one **is** machine-gated | n/a | — |
| Model-arm delta declarations (identical `fit_identity_sha256` masking a dead block) | NOT APPLICABLE | This study makes no arm-vs-arm delta claim — LONG and SHORT are two distinct frozen estimators consumed as two distinct derived inputs, not two arms of one model being compared for an added-feature effect. `direction_arm_mapping: {LONG: C, SHORT: C}` in both `derived_inputs` blocks routes each direction to its own arm, not to a shared one. | n/a | — |
| `MODEL_CHANGED`/`THRESHOLDS_CHANGED`/`NEW_UNTOUCHED_OOS_CLAIM` all `'NO'` | PASS | Consistent with every artifact above: no retrain, no threshold recalculation, no OOS claim (`oos_years: []` in `artifacts/experiment_authorization.json`) | n/a | — |

## Population identity (D2, referred by causal auditor)

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Parent's 4 eligibility conditions reproduced exactly via `eligible_when` | PASS | `research_decision.yaml:96-100` and `study.yaml:195-199` (`&parent_eligibility`) list the identical 4 predicates (`running_mfe_atr>=1.0`, `new_progress_windows>=2`, `retained_mfe_ratio>=0.5`, `regime_age_seconds<=1800`); both `first_p90` (`study.yaml:179-200`) and `control_selection` (`study.yaml:234-244`) reference the same anchor `*parent_eligibility` alias, so the two places that need parent-identical eligibility use the same literal predicate, not two hand-copied lists that could drift | n/a | — |
| `population_parity_gate` (239 total / LONG 115 / SHORT 124, matched against `validation_march2024/artifacts/first_p90_parity.parquet`) is an executable **STOP GATE** before any scientific reading | **FAIL** | `research_decision.yaml:111-114` calls this a "STOP GATE," but no such gate exists anywhere in the executable spec. `study.yaml`'s `analysis.steps` (lines 174-291) contain no step that loads `first_p90_parity.parquet` or compares its row/direction counts against the `first_p90` step's output; `compiled_plan.json` has no `required_gates` block (grepped for `population_parity_gate`, `first_p90_parity`, `239`, `required_gates` — zero matches beyond incidental hash substrings); `_check_required_gates_declared_and_bound` in `research_workflow/contract_audit.py:84-93` is the mechanism that would enforce a declared gate, but it only runs against the legacy `compiled_study.json` pipeline this study does not use. As written, the 239/115/124 check can only happen if a human manually diffs the eventual `first_p90_warning_horizon_contract.json` against the reference parquet before drafting the hand-authored report — nothing in the pipeline refuses to emit deliverables, and nothing blocks `close`, if the anchor population silently drifts from the parent's. | n/a | Add an `analysis` step (or a `required_gates` entry, if that primitive is available on this closure) that loads `first_p90_parity.parquet` and asserts row/direction-count and identity-key equality against the `first_p90` step's output before the remaining steps (`cumulative_incidence` onward) are allowed to run; fail closed on mismatch |
| Consequence for the D2 referral (scores evaluated outside the domain the estimators were fit on) | **NOT VERIFIED** | Because the STOP GATE above is not mechanically enforced, this audit cannot confirm that the anchor population the analysis actually scores will equal the parent's frozen 239-row population — only that the *declared* eligibility predicates are textually identical. The declared design is sound; its enforcement is not yet built. | n/a | Same remediation as above closes this too |

## Chronology / authorization

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| `chronology.windows` mechanically narrows execution to March 2024, not the whole of 2024 | PASS | `artifacts/experiment_authorization.json`: `partition_windows: ["2024:2024-03-01..2024-03-31"]`, `oos_years: []`, `prohibited_years: [2020,2021,2022,2023,2025,2026]` — generated by `prepare` from the declared `chronology.windows`, not copied from prose; `readiness.json` `CHRONOLOGY_ROLE_TABLE: PASSED` and `preflight.json` `R9_closure_current: current=frozen` confirm this was checked against the current composite, not a stale one | n/a | — |
| `train` role on a `model: none` study is honestly disclosed, not misleading | PASS | `study.yaml:2-11` docstring and `research_decision.yaml:125-129` both state explicitly that 2024 carries the role only because the controller requires a role, nothing is fitted, and `NO_PROTECTED_OOS` is recorded — this is disclosed at the point of declaration, not left implicit | n/a | — |
| `chronology.authorized_dates: ['2024-03-01']` does not silently restrict the real execution window | PASS (not a defect) | `authorized_dates` is used only by the `smoke` stage to pick a single smoke-test day (`lifecycle_v2.py:542`, `smoke.py:6-13`) — a single-day narrowing here is expected and orthogonal to `chronology.windows`, which governs the actual partition scope | n/a | — |
| Prohibited years (Apr–Dec 2024 is not itself a "year" — verify no mechanism opens it) | PASS | The `windows` list contains exactly one entry bounded `2024-03-01..2024-03-31`; there is no separate declaration or fallback that would stream the rest of 2024 — `partition_windows` in the authorization artifact confirms only the March window was resolved | n/a | — |

## Control design deviation

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deviation from the requested direction×age_bucket×time_of_day grid is pre-registered and justified before execution | PASS | `research_decision.yaml:144-163` documents the deviation was computed on the parent's own already-frozen 239 fires (42 cells, max cell size 13, zero cells ≥30) **before this study was created** (`decided_before_execution: true`), and reports the concrete counts rather than asserting the conclusion — this is exactly the test-before-prose discipline the project has previously required | n/a | — |
| `age_bucket_note` (>=1800s bucket structurally empty) is reported as structural, not as a null finding | PASS | `research_decision.yaml:160-163` states this plainly and ties it to the parent's own 1800s grid cap | n/a | — |

## Seal / freshness

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Both audits bind the current composite (post-repair `89f940dd…`, not the pre-repair `6e438b9c…`) | PASS | `audit/frozen_execution_manifest.json:frozen_execution_composite_sha256 = 89f940ddf8089c88946580006bd6352826f3342f0ec51f1f5d0efe66a043ea70`; `_work/controller/audit_packet_contract.json:identity.execution_composite_sha256` — same value; `audit/status.json` (causal, pass_02) — same value; `audit/readiness.json` and `audit/preflight.json` — same value. No stale composite anywhere in the reviewed artifacts. | n/a | — |
| Causal and contract reviews carry distinct declared identities | PASS | Causal: `lookahead-auditor-claude` (`audit/status.json`); this report: `contract-checker-pass01-2026-09-04` | n/a | — |

## Referred to lookahead-auditor

None new. The causal auditor's own carried warning (`[B2]` — `FrozenExternalScoreBinding.derive()`'s blanket availability timestamp makes `FrozenExternalModelScorer.score()`'s fail-closed refusal structurally inert) is squarely causal/timing and stays theirs; I did not re-litigate it.

## Blocking verdict

**BLOCKED.** One demonstrated defect: `research_decision.yaml` declares the 239/LONG-115/SHORT-124
population match against the parent's frozen March identity as a **STOP GATE that must pass
before any scientific reading**, but no artifact in `study.yaml`, `compiled_plan.json`, or the
packet's `deliverables_by_stage` implements that gate — there is no step, no `required_gates`
entry, and no refusal path that would stop deliverables (or the hand-authored report) from being
produced against a silently-drifted anchor population. This is precisely the failure mode this
project has hit before: a chronological/population protocol described correctly in prose but
never wired into an executable check. Everything else reviewed — provenance-attestation binding,
threshold and feature-surface fidelity, chronology narrowing, control-design deviation discipline,
and seal freshness — is sound and current. Remediation is narrow and does not touch scope,
chronology, or the frozen models: add one gate step comparing `first_p90` step output against
`validation_march2024/artifacts/first_p90_parity.parquet` before permitting `cumulative_incidence`
and downstream steps to run, then re-audit.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "audited_execution_composite_sha256": "89f940ddf8089c88946580006bd6352826f3342f0ec51f1f5d0efe66a043ea70", "auditor": "contract-checker-pass01-2026-09-04", "critical": 1, "note": 2, "study": "first_p90_warning_horizon_march2024", "verdict": "BLOCKED", "warning": 1}
<!-- AUDIT_SUMMARY_V2_END -->

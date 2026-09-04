# Contract audit — studies/first_p90_warning_horizon_march2024 — pass 03 (DELTA)

Reviewer identity: `contract-checker-pass03-2026-09-04` (distinct from `lookahead-auditor-claude`,
the causal identity on this target — see `audit/pass_04.md`, `CLEAR`).
Scope: the delta since `contract_pass_02.md` (CLEAR) only — the declared `null_input_policy:
model_native` for both derived-model inputs. Provenance attestation, thresholds, feature surface,
chronology narrowing, control-design deviation, and deliverables mapping are not re-derived (all
cleared in pass 02, none touched by this delta).

## Findings

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Declaration does not contradict `MODEL_CHANGED: NO` / `THRESHOLDS_CHANGED: NO` | PASS | `study.yaml:79-113,114-156` — `model_hashes`, `model_artifact_sha256` (`c94866bd...`, `cccc911c...`), `preprocessing_hash`, `ordered_feature_surfaces`, and `parent_provenance_attestation_sha256` are byte-identical to `research_decision.yaml:53-65` for both LONG and SHORT arms, unchanged from pass 02. `null_input_policy` is a field of `DerivedCausalInputSpec` (`research/schemas/study_spec.py:552-560` per causal pass 04) governing how a *missing input value* reaches an unmodified estimator — it selects no different model bytes, thresholds, or feature ordering. The claim is correct: this is a scoring-time input-handling declaration, not a model or threshold change. | Causal pass 04, delta-question 2: `test_model_native_reproduces_the_estimator_on_missing_inputs_exactly` (`research_workflow/tests/test_train_provenance_attestation.py:393-405`) — passed-through NaN reaches `predict_proba` byte-for-byte identically to a direct call | — |
| Referral closed: ordered-feature-surface/estimator bytes provably the parent's | PASS | Causal pass 04 referred this to contract-checker. `study.yaml` binds both arms to `model_artifact_sha256`/`model_hashes` and `parent_provenance_attestation_sha256: 564b112add0ae4d9d62bd4d475f0cd8794ea6b9782a3bd22525256b60a1e9949`, identical across both derived inputs and identical to `research_decision.yaml:54-64`'s independently-recorded `artifact_sha256` values. The 35,872-row parity evidence and the study's scoring binding therefore share the same attested model bytes by sha256, not a re-resolved equivalent. | n/a (sha256 comparison is direct) | — |
| Evidence is adequate for a declared semantic change and discoverable from the study's own artifacts | PASS | `artifacts/parity/frozen_180s_null_input_policy_evidence.json` records: 35,872/35,872 March candidates scored by the parent, 26,018 (73%) with null `rolling_300s_*`, 181/239 frozen first-P90 fires on such a row, and a re-score of all 239 fires through the real host binding against the parent's own March feature rows with `max_abs_delta_vs_parent_recorded: 0.0` for both arms — an end-to-end check, not a claim about isolated unit cells. `study.yaml:112,155` cites this exact path inline next to each `null_input_policy: model_native` declaration, so the evidence is reachable from the declaration itself without cross-referencing prose. | Causal pass 04 independently confirms the NaN pass-through mechanism (`host_bindings.py:687,706-713`) has no backfill/write-back path (B5 clean) | — |
| Population identity: reproduction, not a new population | PASS | `frozen_180s_null_input_policy_evidence.json` measures the *parent's own* recorded scoring behaviour (35,872/35,872 scored, including null-input rows) — `model_native` makes this study's binding match that, not diverge from it. `research_decision.yaml:111-121` `population_parity_gate` (STOP GATE, EXECUTABLE per pass 02 verification) independently constrains the *anchor* set — the 239 first-P90 fires used for every statistic — to exactly 239/115/124 keyed on `regime_start_ns`/`observation_ts` equality to the reference, and aborts the analyze stage before any artifact is written if it does not hold. The widened *collected* population (superset, unaffected by the gate — pass 02 "D2 referral") is a separately-declared, already-audited design choice; `model_native` does not touch which rows are anchors. | Pass 02: gate tests `research/analysis/tests/test_diagnostic_ops.py:319-369` | — |
| `research_decision.yaml` records the null-input policy as a declared semantic decision | WARNING | Not present. `research_decision.yaml` declarations block (`:190-193`) lists `MODEL_CHANGED`, `THRESHOLDS_CHANGED`, `NEW_UNTOUCHED_OOS_CLAIM` but has no entry for the input-null-handling decision, even though it is declared per-input in `study.yaml:112-113,155-156` with its own evidence citation. The decision is discoverable (grep for `null_input_policy` finds it immediately) and is not hidden, so this is not a compliance failure — but `research_decision.yaml` is this study's top-of-authority contract per its own header (`SPEC.md > study.yaml`... reversed: `research_decision.yaml > SPEC.md > study.yaml`), and a reviewer reading only that file would not learn scoring ran over 73%-null rows. | n/a | Add one line under `declarations:` in `research_decision.yaml`, e.g. `NULL_INPUT_POLICY_CHANGED_TO_MODEL_NATIVE: 'YES'` with a pointer to `artifacts/parity/frozen_180s_null_input_policy_evidence.json` — a single-line, non-blocking addition |
| Seal / freshness | PASS | `audit/frozen_execution_manifest.json:frozen_execution_composite_sha256` = `ac9af444a809134bbea524b04c65d98f5a5f5d69a44871cda275acc820e01e57`. Same value in `audit/pass_04.md` (causal, `CLEAR`) header and its `AUDIT_SUMMARY_V2` block, and in `audit/pass_04.md`'s own composite cross-check against `audit/preflight.json`, `audit/readiness.json`, and `_work/controller/audit_packet_causal.json`. No stale composite found in any artifact read for this delta. | — | — |

## Referred to lookahead-auditor
None new — this delta is a scoring-input-handling declaration already independently audited by
`lookahead-auditor-claude` in pass 04 (`CLEAR`, B5/B7 clean, `null_inputs` provenance-only,
confirmed non-leaking).

## Blocking verdict

**CLEAR.** The declared `null_input_policy: model_native` changes only how a missing scoring
*input* reaches an unmodified, sha256-bound estimator; it alters no model bytes, threshold, or
feature ordering, so it does not violate `MODEL_CHANGED: NO` / `THRESHOLDS_CHANGED: NO`. The
evidence (`artifacts/parity/frozen_180s_null_input_policy_evidence.json`) is an end-to-end check —
all 239 frozen first-P90 fires re-scored through the real host binding against the parent's own
March rows, 181 on null-`rolling_300s_*` inputs, `max_abs_delta_vs_parent_recorded: 0.0` both
arms — and is discoverable directly from the `study.yaml` declaration that cites it. The widened
scored population is confirmed as reproduction of the parent's own scoring behaviour, not a new
population; the anchor set that every statistic is computed over remains mechanically pinned to
239/115/124 by the pass-02-verified `population_parity_gate` STOP GATE, which this delta does not
touch. Causal pass 04's referral (whether the feature-surface/estimator bytes are provably the
parent's) is closed by direct sha256 match between `study.yaml`'s per-arm declarations and
`research_decision.yaml`'s independently-recorded `artifact_sha256` values. One non-blocking gap:
`research_decision.yaml` itself does not record the null-input-policy decision even though
`study.yaml` does with an evidence citation — recommended as a one-line addition, not required for
clearance. Both audits bind the current composite `ac9af444a809134b...` with no stale references
found.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "audited_execution_composite_sha256": "ac9af444a809134bbea524b04c65d98f5a5f5d69a44871cda275acc820e01e57", "auditor": "contract-checker-pass03-2026-09-04", "critical": 0, "note": 0, "study": "first_p90_warning_horizon_march2024", "verdict": "CLEAR", "warning": 1}
<!-- AUDIT_SUMMARY_V2_END -->
